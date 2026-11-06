"""Runs installs, and repairs, upgrades and uninstalls of what they installed.

Each run is recorded step by step for the WebUI to show. Credentials are held
only while a run lasts and are redacted from everything it records.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import shlex
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import asyncssh
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from ..clusters import describe_clusters
from ..connections import Connection, Connections
from ..store import DeploymentRecord, Store, StoredTunnel
from ..tunnels import TunnelManager
from .docker_setup import DockerSetupFailed, install_docker
from .images import IMAGE_NAME, ImagesUnavailable, copy_images, local_releases, require_images_on_target
from .probe import HostFacts, UnsupportedHost, check_service, needs_sudo_for, probe, recommend_components
from .render import (
    BACKEND_TLS_FILE,
    COMPOSE_DIR,
    COMPOSE_FILES,
    DEFAULT_BACKEND_TLS_PORT,
    STORE_PORTS_FILE,
    Components,
    DatabaseSpec,
    DeploySpec,
    InvalidSpec,
    Rendered,
    image_reference,
    normalize_image_prefix,
    render,
    validate_modes,
)
from .targets import CommandFailed, LocalTarget, OutputCallback, SSHTarget, Target, scan_host_key

logger = logging.getLogger("ultima_webui_server.installer")

DEFAULT_BACKEND_PORT = 21121
DEFAULT_WEB_PORT = 21120
# Written into the install folder; marks it as ours and records what runs there.
# The .env as it was before an upgrade, until the new version runs.
ENV_BACKUP = ".env.usr-before-upgrade"
# Added to each Compose file's name for its copy from before an upgrade.
COMPOSE_BACKUP_SUFFIX = ".usr-before-upgrade"
_LEGACY_IMAGE_KEYS_EDIT = " ".join(
    f"-e '/^USR_{role}_IMAGE=/d'" for role in ("BACKEND", "WORKER", "WEBUI")
)
STATE_FILE = ".usr-install.json"
_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
# A registry path; it is written into .env and a sed expression, so nothing else.
_REGISTRY_PATTERN = r"^[A-Za-z0-9._:/-]*$"
ImageSource = Literal["copy", "target", "registry"]
Emit = Callable[[str, str], Awaitable[None]]


class InstallError(RuntimeError):
    """A failure with a message meant for the person running the install."""


class TargetIn(BaseModel):
    kind: Literal["local", "ssh"] = "local"
    host: str | None = Field(default=None, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, max_length=500)
    private_key: str | None = Field(default=None, max_length=20000)
    # The OpenSSH host key the user checked and accepted.
    host_key: str | None = Field(default=None, max_length=5000)
    # Only needed when Docker requires sudo for this user, or to install Docker.
    sudo_password: str | None = Field(default=None, max_length=500)


class ComponentsIn(BaseModel):
    backend: bool = True
    worker: bool = True
    postgres: bool = True
    redis: bool = True
    webui: bool = False

    @field_validator("backend", "worker", "postgres", "redis", "webui", mode="before")
    @classmethod
    def _coerce_mode(cls, value: object) -> object:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered == "install":
                return True
            if lowered in ("none", "existing", "reuse"):
                return False
        return value


class DatabaseIn(BaseModel):
    host: str = Field(default="localhost", min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    name: str = Field(default="ultima_archive", min_length=1, max_length=128)
    user: str = Field(default="ultimascraper", min_length=1, max_length=128)
    password: str = Field(default="", max_length=500)


class InstallIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    target: TargetIn = Field(default_factory=TargetIn)
    components: ComponentsIn = Field(default_factory=ComponentsIn)
    install_dir: str = Field(default="~/ultimascraper", min_length=1, max_length=200)
    # copy: from this server's Docker; target: already on the host; registry: pulled there.
    image_source: ImageSource = "copy"
    version: str = Field(default="0.1.0", min_length=1, max_length=128, pattern=_VERSION_PATTERN)
    # Registry root for image_source=registry, e.g. forgejo.example/org/ultimascraper.
    image_prefix: str = Field(default="", max_length=300, pattern=_REGISTRY_PATTERN)
    # Install Docker from the distribution's packages when the host lacks it.
    install_docker: bool = False
    database_url: str | None = Field(default=None, max_length=1000)
    database: DatabaseIn | None = None
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    redis_host: str | None = Field(default=None, max_length=255)
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_password: str | None = Field(default=None, max_length=500)
    # When installing a worker without a backend, the backend connection it joins.
    join_connection_id: str | None = Field(default=None, max_length=128)
    # Let other machines (WebUIs, backends) use this backend over HTTPS.
    share_backend: bool = False

    @field_validator("image_prefix", mode="before")
    @classmethod
    def _normalize_prefix(cls, value: Any) -> str:
        if isinstance(value, str):
            return normalize_image_prefix(value)
        return value or ""


class DetectIn(BaseModel):
    target: TargetIn = Field(default_factory=TargetIn)
    install_dir: str = Field(default="~/ultimascraper", min_length=1, max_length=200)


class CheckServiceIn(BaseModel):
    target: TargetIn = Field(default_factory=TargetIn)
    kind: Literal["postgres", "redis"]
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)


class RegisterExistingIn(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    target: TargetIn = Field(default_factory=TargetIn)
    install_dir: str = Field(default="~/ultimascraper", min_length=1, max_length=200)


class CredentialsIn(BaseModel):
    """Asked for again for every operation: the WebUI never stores them."""

    password: str | None = Field(default=None, max_length=500)
    private_key: str | None = Field(default=None, max_length=20000)
    sudo_password: str | None = Field(default=None, max_length=500)


class ServicesIn(BaseModel):
    """The services a host should run; PostgreSQL and Redis stay as installed."""

    backend: bool
    worker: bool
    webui: bool


class OperationIn(BaseModel):
    action: Literal["repair", "upgrade", "uninstall", "services"]
    credentials: CredentialsIn = Field(default_factory=CredentialsIn)
    # upgrade
    version: str | None = Field(default=None, max_length=128, pattern=_VERSION_PATTERN)
    image_source: ImageSource | None = None
    image_prefix: str = Field(default="", max_length=300, pattern=_REGISTRY_PATTERN)
    # services: the backend, workers and WebUI the host should run from now on.
    services: ServicesIn | None = None
    # uninstall
    delete_data: bool = False
    remove_files: bool = True
    # The WebUI password, checked again before an uninstall; never stored or logged.
    webui_password: str | None = Field(default=None, max_length=500)

    @field_validator("image_prefix", mode="before")
    @classmethod
    def _normalize_prefix(cls, value: Any) -> str:
        if isinstance(value, str):
            return normalize_image_prefix(value)
        return value or ""


class Redactor:
    def __init__(self) -> None:
        self._secrets: set[str] = set()

    def add(self, *values: str | None) -> None:
        self._secrets.update(value for value in values if value and len(value) >= 4)

    def __call__(self, text: str) -> str:
        for value in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(value, "[REDACTED]")
        return text


def project_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "backend"


def describe_target(target: TargetIn) -> str:
    if target.kind == "local":
        return "this machine"
    return f"{target.username}@{target.host}" + (f":{target.port}" if target.port != 22 else "")


def compose_names(components: Components, *, shared: bool = False) -> tuple[str, ...]:
    """The Compose files an install of these components uses."""
    names = (*COMPOSE_FILES, STORE_PORTS_FILE) if components.store_only else COMPOSE_FILES
    return (*names, BACKEND_TLS_FILE) if shared else names


def compose_command(install_dir: str, project: str, components: Components, *, shared: bool = False) -> str:
    files = " ".join(f"-f {name}" for name in compose_names(components, shared=shared))
    return f"cd {shlex.quote(install_dir)} && docker compose --project-name {project} {files}"


def _env_values(rendered: Rendered) -> dict[str, str]:
    content = rendered.files[".env"][0].decode()
    values: dict[str, str] = {}
    for line in content.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip("'")
    return values


def _store_connection(host: str | None, spec: DeploySpec, rendered: Rendered) -> dict:
    """What backends and workers on other hosts enter to use this store-only install."""
    env = _env_values(rendered)
    connection: dict = {"host": host or "", "install_dir": spec.install_dir}
    if spec.components.postgres:
        connection["postgres"] = {
            # The bundled image's defaults (docker-compose.yml).
            "port": spec.postgres_port,
            "name": "ultima_archive",
            "user": "ultimascraper",
            "password": env.get("POSTGRES_PASSWORD", ""),
        }
    if spec.components.redis:
        connection["redis"] = {"port": spec.redis_port, "password": env.get("REDIS_PASSWORD", "")}
    return connection


class Installer:
    def __init__(self, store: Store, connections: Connections, tunnels: TunnelManager, *, local_allowed: bool) -> None:
        self.store = store
        self.connections = connections
        self.tunnels = tunnels
        # Only a WebUI server running directly on the host can install onto it
        # without SSH; inside Docker, "this machine" is reached over SSH instead.
        self.local_allowed = local_allowed
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # One operation at a time per deployment.
        self._busy: set[str] = set()
        # Where other hosts reach a store-only install, by run; kept in memory
        # only, since it holds the generated passwords.
        self._store_connections: dict[str, dict] = {}

    def _validate_target(self, target: TargetIn) -> None:
        if target.kind == "local" and not self.local_allowed:
            raise HTTPException(
                status_code=400,
                detail="This WebUI runs in a container. Install on this machine over SSH instead.",
            )
        if target.kind == "ssh":
            if not (target.host and target.username and target.host_key):
                raise HTTPException(status_code=400, detail="Give the host, the user, and the accepted host key.")
            if not (target.password or target.private_key):
                raise HTTPException(status_code=400, detail="Give the SSH password or a private key.")

    async def open_target(self, target_in: TargetIn) -> Target:
        if target_in.kind == "ssh" and target_in.host and not target_in.host_key:
            try:
                scanned = await scan_host_key(target_in.host, target_in.port)
                target_in.host_key = scanned.openssh
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Could not reach SSH host key on {target_in.host}:{target_in.port}: {exc}",
                ) from exc
        self._validate_target(target_in)
        if target_in.kind == "local":
            return LocalTarget(sudo_password=target_in.sudo_password)
        assert target_in.host and target_in.username and target_in.host_key
        return await SSHTarget.connect(
            host=target_in.host,
            port=target_in.port,
            username=target_in.username,
            host_key=target_in.host_key,
            password=target_in.password,
            private_key=target_in.private_key,
            sudo_password=target_in.sudo_password,
        )

    async def detect(self, request: DetectIn, *, default_version: str = "0.1.0") -> dict:
        target = await self.open_target(request.target)
        try:
            facts = await probe(
                target,
                sudo_available=bool(request.target.sudo_password),
                install_dir=request.install_dir,
            )
        finally:
            await target.close()

        existing_install = dict(facts.existing_install) if facts.existing_install else None
        if existing_install is not None:
            matching = next(
                (
                    d
                    for d in self.store.list_deployments()
                    if d.details.get("project") == existing_install.get("project")
                    and d.details.get("install_dir") == existing_install.get("install_dir")
                ),
                None,
            )
            existing_install["deployment_id"] = matching.id if matching else None

        arch_releases = [r for r in facts.local_images if r.architecture == facts.architecture]
        if arch_releases:
            preferred = next((r for r in arch_releases if r.version == default_version), arch_releases[0])
            recommended_image_source = "target" if request.target.kind == "local" else "copy"
            recommended_version = preferred.version
        else:
            recommended_image_source = "registry"
            recommended_version = default_version or "0.1.0"

        return {
            "facts": {
                "architecture": facts.architecture,
                "os_name": facts.os_name,
                "user": facts.user,
                "home": facts.home,
                "hostname": facts.hostname,
                "docker_version": facts.docker_version,
                "compose_version": facts.compose_version,
                "docker_needs_sudo": facts.docker_needs_sudo,
                "sudo_mode": facts.sudo_mode,
                "memory_mb": facts.memory_mb,
                "home_free_mb": facts.home_free_mb,
                "listening_ports": sorted(facts.listening_ports),
                "existing_projects": list(facts.existing_projects),
                "existing_install": existing_install,
                "services": facts.services,
                "local_images": [
                    {"version": r.version, "architecture": r.architecture, "names": list(r.names)}
                    for r in facts.local_images
                ],
                "warnings": list(facts.warnings),
            },
            "recommended_components": recommend_components(facts),
            "needs_sudo_for": needs_sudo_for(facts),
            "recommended_image_source": recommended_image_source,
            "recommended_version": recommended_version,
        }

    async def check_target_service(self, request: CheckServiceIn) -> dict:
        target = await self.open_target(request.target)
        try:
            ok, message = await check_service(target, host=request.host, port=request.port)
        finally:
            await target.close()
        return {
            "reachable": ok,
            "kind": request.kind,
            "host": request.host,
            "port": request.port,
            "message": message,
        }

    async def get_cluster_stores(
        self,
        *,
        connection_id: str | None = None,
        target_is_remote: bool = False,
    ) -> dict[str, Any]:
        """Return database and redis connection details for joining the cluster."""
        conns: list[Connection] = []
        if connection_id:
            try:
                conns = [self.connections.get(connection_id)]
            except HTTPException:
                conns = []
        if not conns:
            conns = self.connections.all()

        # Why each backend gave nothing, for the caller to show.
        reasons: list[str] = []
        for conn in conns:
            try:
                reached = await self.tunnels.resolve(conn)
                token = reached.token()
                async with httpx.AsyncClient(
                    base_url=reached.base_url,
                    verify=reached.tls_verify,
                    timeout=5.0,
                ) as client:
                    resp = await client.get(
                        "/api/v1/system/cluster-stores",
                        headers={"x-usr-admin-token": token} if token else {},
                    )
                    if not resp.is_success:
                        reasons.append(f"{conn.name}: HTTP {resp.status_code} from {reached.base_url}")
                    else:
                        data = resp.json()
                        if not data.get("available"):
                            reasons.append(f"{conn.name}: it has no database or Redis settings")
                        else:
                            db = data.get("database")
                            redis = data.get("redis")
                            lan_ip = _local_lan_ip() if target_is_remote else None
                            if db and target_is_remote and db.get("host") in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                                db["host"] = lan_ip
                            if redis and target_is_remote and redis.get("host") in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                                redis["host"] = lan_ip

                            api_url = data.get("api_url")
                            if target_is_remote and api_url:
                                parts = urlsplit(api_url)
                                if parts.hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                                    api_url = f"{parts.scheme or 'http'}://{lan_ip}:{parts.port or 21121}"
                            elif target_is_remote and not api_url and conn.base_url:
                                parts = urlsplit(conn.base_url)
                                h = parts.hostname or "127.0.0.1"
                                if h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                                    h = lan_ip
                                api_url = f"{parts.scheme or 'http'}://{h}:{parts.port or 21121}"

                            return {
                                "available": True,
                                "cluster_id": data.get("cluster_id"),
                                "database": db,
                                "redis": redis,
                                "source_backend_name": conn.name,
                                "secret_key": data.get("secret_key"),
                                "settings_id": data.get("settings_id"),
                                "backend_id": data.get("backend_id"),
                                "api_url": api_url,
                            }
            except Exception as exc:
                logger.debug("Failed querying cluster stores from connection %s: %s", conn.id, exc)
                reasons.append(f"{conn.name}: {exc or type(exc).__name__}")

        # Fallback to local server environment if no backend answered over HTTP
        try:
            from sqlalchemy.engine import make_url
            from ultima_scraper_core import archive_database_url, runtime_env_value

            configured_db = archive_database_url()
            redis_host = (runtime_env_value("REDIS_HOST") or "").strip()
            if configured_db or redis_host:
                db_out = None
                redis_out = None
                lan_ip = _local_lan_ip() if target_is_remote else None

                if configured_db:
                    url = make_url(configured_db)
                    db_h = url.host or "localhost"
                    if target_is_remote and db_h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                        db_h = lan_ip
                    db_out = {
                        "host": db_h,
                        "port": url.port or 5432,
                        "name": url.database or "ultima_archive",
                        "username": url.username or "",
                        "password": url.password or "",
                    }

                if redis_host:
                    r_h = redis_host
                    if target_is_remote and r_h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                        r_h = lan_ip
                    redis_out = {
                        "host": r_h,
                        "port": int(runtime_env_value("REDIS_PORT") or 6379),
                        "db": int(runtime_env_value("REDIS_DB") or 0),
                        "password": runtime_env_value("REDIS_PASSWORD") or "",
                    }

                configured_secret = runtime_env_value("USR_SECRET_KEY")
                api_port = int(runtime_env_value("CONTROL_PORT") or runtime_env_value("USR_BACKEND_PORT") or 21121)
                api_url_out = f"http://{lan_ip if target_is_remote else '127.0.0.1'}:{api_port}"
                return {
                    "available": True,
                    "cluster_id": None,
                    "database": db_out,
                    "redis": redis_out,
                    "source_backend_name": "Local Server",
                    "secret_key": configured_secret,
                    "settings_id": None,
                    "backend_id": runtime_env_value("BACKEND_ID"),
                    "api_url": api_url_out,
                }
        except Exception as exc:
            logger.debug("Failed resolving cluster stores from local environment: %s", exc)

        return {
            "available": False,
            "cluster_id": None,
            "database": None,
            "redis": None,
            "source_backend_name": None,
            "reasons": reasons,
        }

    async def register_existing(self, request: RegisterExistingIn) -> DeploymentRecord:
        target = await self.open_target(request.target)
        try:
            facts = await probe(
                target,
                sudo_available=bool(request.target.sudo_password),
                install_dir=request.install_dir,
            )
            install_dir = request.install_dir.strip()
            if install_dir == "~" or install_dir.startswith("~/"):
                install_dir = facts.home.rstrip("/") + install_dir[1:]

            existing_state = facts.existing_install
            env_res = await target.run(f"cat {shlex.quote(install_dir + '/.env')} 2>/dev/null", check=False)
            env_vars: dict[str, str] = {}
            if env_res.exit_status == 0:
                for line in env_res.stdout.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or "=" not in stripped:
                        continue
                    k, v = stripped.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip("'")

            if not existing_state and not env_vars:
                raise HTTPException(status_code=404, detail=f"No existing installation found in {install_dir}.")

            project = (
                (existing_state or {}).get("project")
                or (facts.existing_projects[0] if facts.existing_projects else f"usr-{project_slug(request.name or facts.hostname or 'backend')}")
            )
            existing_record = next(
                (
                    d
                    for d in self.store.list_deployments()
                    if d.details.get("project") == project and d.details.get("install_dir") == install_dir
                ),
                None,
            )
            if existing_record is not None:
                return existing_record

            profiles = (
                (existing_state or {}).get("components")
                or [p.strip() for p in env_vars.get("COMPOSE_PROFILES", "backend,worker,postgres,redis").split(",") if p.strip()]
            )
            components_dict = {
                name: (name in profiles) for name in ("backend", "worker", "postgres", "redis", "webui")
            }
            version = (existing_state or {}).get("version") or env_vars.get("USR_VERSION") or "0.1.0"
            backend_port = int((existing_state or {}).get("backend_port") or env_vars.get("USR_BACKEND_PORT") or DEFAULT_BACKEND_PORT)
            web_port = int((existing_state or {}).get("web_port") or env_vars.get("USR_WEB_PORT") or DEFAULT_WEB_PORT)
            image_source = (existing_state or {}).get("image_source") or "copy"
            image_prefix = (existing_state or {}).get("image_prefix") or ""
            admin_token = env_vars.get("USR_ADMIN_TOKEN") or ""
            display_name = (request.name or "").strip() or project.removeprefix("usr-") or facts.hostname or "Backend"

            connection_id: str | None = None
            if components_dict["backend"] and admin_token:
                spec = DeploySpec(
                    project=project,
                    install_dir=install_dir,
                    components=Components(**components_dict),
                    image_prefix=image_prefix,
                    version=version,
                    backend_id=env_vars.get("BACKEND_ID", f"{project}-registered"),
                    backend_port=backend_port,
                    web_port=web_port,
                )
                rendered = Rendered(files={}, admin_token=admin_token)
                conn = await self._register(target, request.target, display_name, spec, rendered)
                connection_id = conn.id

            record = DeploymentRecord(
                id=secrets.token_hex(8),
                name=display_name,
                target=describe_target(request.target),
                details={
                    "kind": request.target.kind,
                    "host": request.target.host,
                    "port": request.target.port,
                    "username": request.target.username,
                    "host_key": request.target.host_key,
                    "install_dir": install_dir,
                    "project": project,
                    "version": version,
                    "image_source": image_source,
                    "image_prefix": image_prefix,
                    "components": components_dict,
                    "architecture": facts.architecture,
                    "backend_port": backend_port,
                    "web_port": web_port,
                    "backend_id": env_vars.get("BACKEND_ID") or None,
                    # The HTTPS override is written with its port in the .env.
                    "share_backend": bool(env_vars.get("USR_BACKEND_TLS_PORT")),
                },
                connection_id=connection_id,
                state="active",
                created_at=time.time(),
                updated_at=time.time(),
            )
            self.store.save_deployment(record)
            return record
        finally:
            await target.close()

    # ---- Starting runs -------------------------------------------------

    def start(self, request: InstallIn) -> str:
        target = request.target
        self._validate_target(target)
        if request.image_source == "registry" and not request.image_prefix.strip():
            raise HTTPException(status_code=400, detail="Give the registry the images are pulled from.")
        joins_backend = request.components.worker and not request.components.backend
        if joins_backend and not request.join_connection_id:
            raise HTTPException(status_code=400, detail="Choose the backend this worker joins.")
        if joins_backend and request.join_connection_id:
            self.connections.get(request.join_connection_id)
        try:
            render(self._spec(request, backend_port=DEFAULT_BACKEND_PORT, web_port=DEFAULT_WEB_PORT, home="/"))
        except InvalidSpec as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        redact = Redactor()
        redact.add(
            target.password,
            target.private_key,
            target.sudo_password,
            request.redis_password,
            request.database_url,
            request.database.password if request.database else None,
        )
        outputs: dict = {}
        run_id = self._launch(
            request.name,
            describe_target(target),
            "install",
            None,
            redact,
            lambda emit: self._install(request, redact, emit, outputs),
        )
        self._store_connections[run_id] = outputs
        return run_id

    def store_connection(self, run_id: str) -> dict | None:
        """How other hosts reach the PostgreSQL/Redis a store-only run installed."""
        return self._store_connections.get(run_id, {}).get("store_connection")

    def _checked(self, deployment_id: str, request: OperationIn) -> tuple[DeploymentRecord, TargetIn]:
        """The deployment and how to reach it, when the operation can start."""
        deployment = self.store.get_deployment(deployment_id)
        if deployment is None or deployment.state != "active":
            raise HTTPException(status_code=404, detail="No such deployment.")
        if deployment_id in self._busy:
            raise HTTPException(
                status_code=409, detail=f"Another operation on {deployment.name} is still running."
            )
        target = self._target(deployment, request.credentials)
        if target.kind == "ssh" and not (target.password or target.private_key):
            raise HTTPException(
                status_code=400, detail=f"Give the SSH password or a private key for {deployment.name}."
            )
        if request.action == "services" and request.services is None:
            raise HTTPException(status_code=400, detail="Say which services the host should run.")
        if request.action == "upgrade":
            if not request.version:
                raise HTTPException(status_code=400, detail="Give the version to upgrade to.")
            if (request.image_source or deployment.details["image_source"]) == "registry" and not (
                request.image_prefix.strip() or deployment.details.get("image_prefix")
            ):
                raise HTTPException(
                    status_code=400, detail=f"Give the registry {deployment.name}'s images are pulled from."
                )
        return deployment, target

    def start_upgrades(self, name: str, requests: list[tuple[str, OperationIn]]) -> str:
        """Upgrade several deployments one after another, in one run.

        A failed upgrade rolls its own deployment back and stops the run, so the
        ones after it keep their version.
        """
        if not requests:
            raise HTTPException(status_code=400, detail="There is nothing to upgrade.")
        checked = [(*self._checked(deployment_id, request), request) for deployment_id, request in requests]
        if any(request.action != "upgrade" for _, _, request in checked):
            raise HTTPException(status_code=400, detail="Only upgrades run together.")
        redact = Redactor()
        for _, target, _ in checked:
            redact.add(target.password, target.private_key, target.sudo_password)
        ids = [deployment.id for deployment, _, _ in checked]
        self._busy.update(ids)

        async def body(emit: Emit) -> str | None:
            for index, (deployment, target, request) in enumerate(checked, 1):
                await emit("step", f"Upgrading {deployment.name} ({index} of {len(checked)})")
                try:
                    await self._upgrade(deployment, target, request, emit)
                except Exception:
                    rest = [item.name for item, _, _ in checked[index:]]
                    if rest:
                        await emit("output", f"Not upgraded, still on their version: {', '.join(rest)}")
                    raise
            return None

        run_id = self._launch(name, f"{len(checked)} deployments", "upgrade", None, redact, body)
        self._tasks[run_id].add_done_callback(lambda _: self._busy.difference_update(ids))
        return run_id

    def start_operation(self, deployment_id: str, request: OperationIn) -> str:
        deployment, target = self._checked(deployment_id, request)

        redact = Redactor()
        redact.add(target.password, target.private_key, target.sudo_password)
        self._busy.add(deployment_id)
        runners = {
            "repair": self._repair,
            "upgrade": self._upgrade,
            "uninstall": self._uninstall,
            "services": self._change_services,
        }
        run_id = self._launch(
            deployment.name,
            deployment.target,
            request.action,
            deployment_id,
            redact,
            lambda emit: runners[request.action](deployment, target, request, emit),
        )
        self._tasks[run_id].add_done_callback(lambda _: self._busy.discard(deployment_id))
        return run_id

    def _launch(
        self,
        name: str,
        target_description: str,
        operation: str,
        deployment_id: str | None,
        redact: Redactor,
        body: Callable[[Emit], Awaitable[str | None]],
    ) -> str:
        run_id = secrets.token_hex(8)
        self.store.create_install(run_id, name, target_description, operation=operation, deployment_id=deployment_id)
        self.store.audit(f"{operation}_started", f"{run_id} {target_description}")

        async def emit(kind: str, message: str) -> None:
            self.store.add_install_event(run_id, kind, redact(message))

        async def run() -> None:
            try:
                connection_id = await body(emit)
            except Exception as exc:  # The run's log is where every failure is reported.
                await emit("error", _failure_message(exc))
                self.store.finish_install(run_id, "failed", None)
                logger.info("%s %s failed", operation, run_id, exc_info=True)
            else:
                self.store.finish_install(run_id, "succeeded", connection_id)

        task = asyncio.create_task(run())
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))
        return run_id

    # ---- Install -------------------------------------------------------

    def _spec(
        self,
        request: InstallIn,
        *,
        backend_port: int,
        web_port: int,
        home: str,
        hostname: str = "",
        backend_tls_port: int = DEFAULT_BACKEND_TLS_PORT,
        secret_key: str | None = None,
        default_backend_url: str | None = None,
        default_backend_token: str | None = None,
    ) -> DeploySpec:
        slug = project_slug(request.name)
        install_dir = request.install_dir.strip()
        if install_dir == "~" or install_dir.startswith("~/"):
            install_dir = home.rstrip("/") + install_dir[1:]
        if request.target.kind == "ssh" and request.target.host:
            webui_hostnames: tuple[str, ...] = (request.target.host,)
        elif request.target.kind == "local" and hostname:
            webui_hostnames = (hostname,)
        else:
            webui_hostnames = ()
        share_backend = request.share_backend and request.components.backend
        # The host's address as other machines know it: the SSH target, or this machine's.
        if request.target.kind == "ssh":
            advertise_host = request.target.host or ""
        else:
            advertise_host = _local_lan_ip()
        return DeploySpec(
            project=f"usr-{slug}",
            install_dir=install_dir,
            components=Components(**request.components.model_dump()),
            image_prefix=normalize_image_prefix(request.image_prefix) if request.image_source == "registry" else "",
            version=request.version,
            backend_id=f"{slug}-{secrets.token_hex(3)}",
            backend_port=backend_port,
            web_port=web_port,
            database_url=request.database_url,
            database=DatabaseSpec(**request.database.model_dump()) if request.database else None,
            postgres_port=request.postgres_port,
            redis_host=request.redis_host,
            redis_port=request.redis_port,
            redis_password=request.redis_password,
            webui_hostnames=webui_hostnames,
            secret_key=secret_key,
            default_backend_url=default_backend_url,
            default_backend_token=default_backend_token,
            share_backend=share_backend,
            advertise_host=advertise_host,
            backend_tls_port=backend_tls_port,
        )

    async def _install(
        self, request: InstallIn, redact: Redactor, emit: Emit, outputs: dict | None = None
    ) -> str | None:
        target_in = request.target
        target = await self._connect(target_in, emit)
        try:
            facts = await self._check_host(target, target_in, emit, install_missing_docker=request.install_docker)

            cluster_info: dict[str, Any] | None = None
            secret_key: str | None = None
            default_backend_url: str | None = None
            default_backend_token: str | None = None

            if request.join_connection_id:
                try:
                    cluster_info = await self.get_cluster_stores(
                        connection_id=request.join_connection_id,
                        target_is_remote=(target_in.kind == "ssh"),
                    )
                except Exception as exc:
                    logger.debug("Failed querying cluster stores in _install: %s", exc)

                secret_key = cluster_info.get("secret_key") if cluster_info else None
                default_backend_url = cluster_info.get("api_url") if cluster_info else None
                try:
                    conn = self.connections.get(request.join_connection_id)
                    default_backend_token = conn.token()
                    if not default_backend_url and conn.base_url:
                        parts = urlsplit(conn.base_url)
                        h = parts.hostname or "127.0.0.1"
                        if target_in.kind == "ssh" and h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                            h = _local_lan_ip()
                        default_backend_url = f"{parts.scheme or 'http'}://{h}:{parts.port or 21121}"
                except Exception as exc:
                    logger.debug("Failed resolving backend connection token/url: %s", exc)

            spec = self._spec(
                request,
                backend_port=facts.free_port(DEFAULT_BACKEND_PORT),
                web_port=facts.free_port(DEFAULT_WEB_PORT),
                home=facts.home,
                hostname=facts.hostname,
                backend_tls_port=facts.free_port(DEFAULT_BACKEND_TLS_PORT),
                secret_key=secret_key,
                default_backend_url=default_backend_url,
                default_backend_token=default_backend_token,
            )
            rendered = render(spec)
            redact.add(rendered.admin_token)
            for content, _ in rendered.files.values():
                for line in content.decode().splitlines():
                    if line.startswith(("USR_SECRET_KEY=", "POSTGRES_PASSWORD=", "REDIS_PASSWORD=")):
                        redact.add(line.split("=", 1)[1])

            await emit("step", f"Writing the deployment to {spec.install_dir}")
            created_dir = await self._write_files(target, spec, rendered)

            names = _image_names(spec.components)
            compose = compose_command(spec.install_dir, spec.project, spec.components, shared=spec.share_backend)
            try:
                await self._provide_images(
                    target, facts, target_in.kind, request.image_source, spec, names, compose, emit
                )
            except Exception:
                # Nothing runs yet: take the files back so the same folder can be retried.
                await self._remove_files(target, spec, rendered, created_dir, emit)
                raise

            if spec.components.worker and not spec.components.backend and request.join_connection_id:
                await self._register_worker_inventory(
                    spec, request.name, target_in, request.join_connection_id, cluster_info, emit
                )

            await self._start_services(target, facts, compose, emit)
            await self._write_state(target, spec, request.image_source)

            # Saved as soon as the services run, so a later failure (the
            # worker's cluster check, connecting the backend) still leaves an
            # install that can be repaired or uninstalled from this WebUI.
            record = DeploymentRecord(
                id=secrets.token_hex(8),
                name=request.name,
                target=describe_target(target_in),
                details={
                    "kind": target_in.kind,
                    "host": target_in.host,
                    "port": target_in.port,
                    "username": target_in.username,
                    "host_key": target_in.host_key,
                    "install_dir": spec.install_dir,
                    "project": spec.project,
                    # What its backend and workers report as, for finding them in the cluster.
                    "backend_id": spec.backend_id,
                    "version": spec.version,
                    "image_source": request.image_source,
                    "image_prefix": spec.image_prefix,
                    "components": request.components.model_dump(),
                    "architecture": facts.architecture,
                    "backend_port": spec.backend_port,
                    "web_port": spec.web_port,
                    "join_connection_id": request.join_connection_id,
                    "share_backend": spec.share_backend,
                    "backend_tls_port": spec.backend_tls_port if spec.share_backend else None,
                    "image_version": await _running_image_version(target, facts, compose, spec.components),
                },
                connection_id=None,
                state="active",
                created_at=time.time(),
                updated_at=time.time(),
            )
            self.store.save_deployment(record)

            if spec.components.worker and not spec.components.backend and request.join_connection_id:
                await self._verify_worker_cluster(
                    target, facts, compose, spec, request.join_connection_id, emit
                )

            connection_id: str | None = None
            if spec.components.backend:
                await emit("step", "Connecting this WebUI to the new backend")
                connection = await self._register(target, target_in, request.name, spec, rendered)
                connection_id = connection.id
                self.store.save_deployment(replace(record, connection_id=connection_id, updated_at=time.time()))
                await self._wait_for_backend(connection, emit)
            if spec.components.webui:
                await emit("output", f"Its own WebUI listens on port {spec.web_port}.")
            if spec.components.store_only and outputs is not None:
                outputs["store_connection"] = _store_connection(
                    target_in.host if target_in.kind == "ssh" else facts.hostname, spec, rendered
                )
                await emit("output", f"Other hosts reach these services at {outputs['store_connection']['host']}.")
            await emit("done", f"{request.name} is installed.")
            return connection_id
        finally:
            await target.close()

    # ---- Operations on a deployment --------------------------------------

    @staticmethod
    def _target(deployment: DeploymentRecord, credentials: CredentialsIn) -> TargetIn:
        details = deployment.details
        return TargetIn(
            kind=details["kind"],
            host=details.get("host"),
            port=details.get("port") or 22,
            username=details.get("username"),
            host_key=details.get("host_key"),
            password=credentials.password,
            private_key=credentials.private_key,
            sudo_password=credentials.sudo_password,
        )

    async def _repair(
        self, deployment: DeploymentRecord, target_in: TargetIn, request: OperationIn, emit: Emit
    ) -> str | None:
        details = deployment.details
        target = await self._connect(target_in, emit)
        try:
            facts = await self._check_host(target, target_in, emit, install_missing_docker=False)
            await self._read_state(target, details)
            components = Components(**details["components"])
            compose = compose_command(
                details["install_dir"], details["project"], components, shared=bool(details.get("share_backend"))
            )
            await self._start_services(target, facts, compose, emit)
            image_version = await _running_image_version(target, facts, compose, components)
            if image_version and image_version != details.get("image_version"):
                self.store.save_deployment(
                    replace(deployment, details={**details, "image_version": image_version}, updated_at=time.time())
                )
            await self._check_connection(deployment, emit)
            await emit("done", f"{deployment.name} is running.")
            return deployment.connection_id
        finally:
            await target.close()

    async def _upgrade(
        self, deployment: DeploymentRecord, target_in: TargetIn, request: OperationIn, emit: Emit
    ) -> str | None:
        details = dict(deployment.details)
        assert request.version
        source: ImageSource = request.image_source or details["image_source"]
        prefix = (
            (normalize_image_prefix(request.image_prefix) or normalize_image_prefix(details.get("image_prefix") or ""))
            if source == "registry"
            else ""
        )
        target = await self._connect(target_in, emit)
        try:
            facts = await self._check_host(target, target_in, emit, install_missing_docker=False)
            await self._read_state(target, details)
            await emit("output", f"From version {details['version']} to {request.version}")
            spec = DeploySpec(
                project=details["project"],
                install_dir=details["install_dir"],
                components=Components(**details["components"]),
                image_prefix=prefix,
                version=request.version,
                backend_id="",
                backend_port=details["backend_port"],
                web_port=details["web_port"],
                share_backend=bool(details.get("share_backend")),
            )
            compose = compose_command(spec.install_dir, spec.project, spec.components, shared=spec.share_backend)

            env_file = shlex.quote(spec.install_dir + "/.env")
            backup = shlex.quote(spec.install_dir + "/" + ENV_BACKUP)
            compose_files = compose_names(spec.components, shared=spec.share_backend)
            # Kept until the new version runs, so a failed upgrade can go back.
            await target.run(f"cp -p {env_file} {backup}")
            for name in compose_files:
                path = shlex.quote(f"{spec.install_dir}/{name}")
                await target.run(f"cp -p {path} {path}{COMPOSE_BACKUP_SUFFIX}")

            await emit("step", "Pointing the deployment at the new images")
            # Only the image settings change; the generated secrets stay as they are.
            settings = {"USR_VERSION": spec.version, "USR_IMAGE": image_reference(spec).rsplit(":", 1)[0]}
            try:
                for key, value in settings.items():
                    await target.run(_set_env_command(env_file, key, value))
                # Installs from here run the full image; the per-service images an
                # older install names would override it and are not the ones provided.
                await target.run(f"sed -i {_LEGACY_IMAGE_KEYS_EDIT} {env_file}")
                # This WebUI's Compose files: an install from before the single
                # image still names one image per role.
                for name in compose_files:
                    await self._put(target, f"{spec.install_dir}/{name}", (COMPOSE_DIR / name).read_bytes(), 0o644)
                await self._provide_images(
                    target, facts, target_in.kind, source, spec, _image_names(spec.components), compose, emit
                )
                await self._start_services(target, facts, compose, emit)
            except Exception as exc:
                previous = details["version"]
                restored = await self._roll_back_upgrade(
                    target, facts, compose, env_file, backup, spec.install_dir, compose_files, previous, emit
                )
                outcome = (
                    f"The upgrade to {spec.version} was undone: {deployment.name} is back on version {previous}."
                    if restored
                    else f"Going back to version {previous} failed too; run Repair once the cause is fixed."
                )
                raise InstallError(f"{_failure_message(exc)} {outcome}") from exc
            await self._write_state(target, spec, source)
            await target.run(f"rm -f -- {backup}", check=False)
            for name in compose_files:
                await target.run(
                    f"rm -f -- {shlex.quote(f'{spec.install_dir}/{name}{COMPOSE_BACKUP_SUFFIX}')}", check=False
                )
            details.update(
                version=spec.version,
                image_source=source,
                image_prefix=prefix,
                image_version=await _running_image_version(target, facts, compose, spec.components),
            )
            self.store.save_deployment(
                DeploymentRecord(
                    deployment.id,
                    deployment.name,
                    deployment.target,
                    details,
                    deployment.connection_id,
                    "active",
                    deployment.created_at,
                    time.time(),
                )
            )
            await self._check_connection(deployment, emit)
            await emit("done", f"{deployment.name} runs version {spec.version}.")
            return deployment.connection_id
        finally:
            await target.close()

    async def _change_services(
        self, deployment: DeploymentRecord, target_in: TargetIn, request: OperationIn, emit: Emit
    ) -> str | None:
        """Turn the backend, workers or WebUI on or off in a host's existing install.

        Only the profiles in its .env change (and the WebUI's HTTPS settings when
        it is added); the generated secrets and data stay. A new backend is
        connected to this WebUI; a removed one is disconnected. If the services
        do not come up, the previous .env and services are restored.
        """
        assert request.services is not None
        details = dict(deployment.details)
        current = Components(**details["components"])
        wanted = Components(
            backend=request.services.backend,
            worker=request.services.worker,
            postgres=current.postgres,
            redis=current.redis,
            webui=request.services.webui,
        )
        target = await self._connect(target_in, emit)
        try:
            facts = await self._check_host(target, target_in, emit, install_missing_docker=False)
            await self._read_state(target, details)
            install_dir = details["install_dir"]
            env_file = shlex.quote(install_dir + "/.env")
            env = _parse_env((await target.run(f"cat {env_file}", check=False)).stdout)
            # The stores the backend and workers use: installed here, or existing ones in the .env.
            postgres = "install" if wanted.postgres else ("existing" if env.get("ULTIMA_ARCHIVE_DATABASE_URL") else "none")
            redis = "install" if wanted.redis else ("existing" if env.get("REDIS_HOST") not in (None, "", "redis") else "none")
            try:
                validate_modes(
                    "install" if wanted.backend else "none",
                    "install" if wanted.worker else "none",
                    postgres,
                    redis,
                    "install" if wanted.webui else "reuse",
                )
            except InvalidSpec as exc:
                raise InstallError(str(exc)) from exc
            added = [name for name in ("backend", "worker", "webui") if getattr(wanted, name) and not getattr(current, name)]
            removed = [name for name in ("backend", "worker", "webui") if getattr(current, name) and not getattr(wanted, name)]
            if not added and not removed:
                await emit("done", f"{deployment.name} already runs these services.")
                return deployment.connection_id
            await emit("step", "Changing services: " + ", ".join([f"+{name}" for name in added] + [f"-{name}" for name in removed]))

            shared = bool(details.get("share_backend")) and wanted.backend
            spec = DeploySpec(
                project=details["project"],
                install_dir=install_dir,
                components=wanted,
                image_prefix=normalize_image_prefix(details.get("image_prefix") or ""),
                version=details["version"],
                backend_id=details.get("backend_id") or env.get("BACKEND_ID") or "",
                backend_port=details["backend_port"],
                web_port=details["web_port"],
                share_backend=shared,
            )
            before = compose_command(install_dir, details["project"], current, shared=bool(details.get("share_backend")))
            compose = compose_command(install_dir, details["project"], wanted, shared=shared)
            backup = shlex.quote(install_dir + "/" + ENV_BACKUP)
            await target.run(f"cp -p {env_file} {backup}")

            settings = {"COMPOSE_PROFILES": ",".join(wanted.profiles())}
            if "webui" in added:
                # As an install with a WebUI: HTTPS with a certificate for the host's name.
                settings |= {
                    "USR_WEBUI_TLS": "self-signed",
                    "USR_WEBUI_TLS_HOSTNAMES": target_in.host if target_in.kind == "ssh" and target_in.host else facts.hostname,
                }
            try:
                for key, value in settings.items():
                    await target.run(_set_env_command(env_file, key, value))
                await self._provide_images(
                    target, facts, target_in.kind, details["image_source"], spec, _image_names(Components(
                        backend="backend" in added, worker="worker" in added, postgres=False, redis=False, webui="webui" in added
                    )), compose, emit
                )
                if removed:
                    await emit("step", "Stopping " + ", ".join(removed))
                    profiles = " ".join(f"--profile {name}" for name in removed)
                    await target.run(
                        f"{before} {profiles} rm --stop --force {' '.join(removed)}",
                        sudo=facts.docker_needs_sudo,
                        on_output=lambda line: emit("output", line),
                    )
                await self._start_services(target, facts, compose, emit)
            except Exception as exc:
                await emit("step", "Going back to the services it ran before")
                restored = (await target.run(f"mv -f -- {backup} {env_file}", check=False)).exit_status == 0
                if restored:
                    restored = (
                        await target.run(
                            f"{before} up --detach --wait --wait-timeout 300",
                            sudo=facts.docker_needs_sudo,
                            check=False,
                            on_output=lambda line: emit("output", line),
                        )
                    ).exit_status == 0
                outcome = "It runs the services it ran before." if restored else "Going back failed too; run Repair once the cause is fixed."
                raise InstallError(f"{_failure_message(exc)} {outcome}") from exc
            await target.run(f"rm -f -- {backup}", check=False)
            await self._write_state(target, spec, details["image_source"])

            connection_id = deployment.connection_id
            if "backend" in removed and connection_id:
                self.connections.delete(connection_id)
                connection_id = None
            details.update(components={**details["components"], **request.services.model_dump()}, share_backend=shared)
            record = replace(deployment, details=details, connection_id=connection_id, updated_at=time.time())
            self.store.save_deployment(record)
            if "backend" in added:
                await emit("step", "Connecting this WebUI to the new backend")
                connection = await self._register(
                    target, target_in, deployment.name, spec, Rendered(files={}, admin_token=env.get("USR_ADMIN_TOKEN", ""))
                )
                connection_id = connection.id
                self.store.save_deployment(replace(record, connection_id=connection_id, updated_at=time.time()))
                await self._wait_for_backend(connection, emit)
            if "webui" in added:
                await emit("output", f"Its own WebUI listens on port {details['web_port']}.")
            await emit("done", f"{deployment.name} now runs: {', '.join(wanted.profiles()) or 'nothing'}.")
            return connection_id
        finally:
            await target.close()

    @staticmethod
    async def _roll_back_upgrade(
        target: Target,
        facts: HostFacts,
        compose: str,
        env_file: str,
        backup: str,
        install_dir: str,
        compose_files: tuple[str, ...],
        version: str,
        emit: Emit,
    ) -> bool:
        """Restores the previous .env and Compose files and starts that version again from the images still on the host."""
        await emit("step", f"Going back to version {version}")
        if (await target.run(f"mv -f -- {backup} {env_file}", check=False)).exit_status != 0:
            return False
        for name in compose_files:
            path = shlex.quote(f"{install_dir}/{name}")
            if (await target.run(f"mv -f -- {path}{COMPOSE_BACKUP_SUFFIX} {path}", check=False)).exit_status != 0:
                return False
        result = await target.run(
            f"{compose} up --detach --wait --wait-timeout 300",
            sudo=facts.docker_needs_sudo,
            check=False,
            on_output=lambda line: emit("output", line),
        )
        return result.exit_status == 0

    async def _uninstall(
        self, deployment: DeploymentRecord, target_in: TargetIn, request: OperationIn, emit: Emit
    ) -> str | None:
        details = deployment.details
        directory = shlex.quote(details["install_dir"])
        target = await self._connect(target_in, emit)
        try:
            facts = await self._check_host(target, target_in, emit, install_missing_docker=False)
            ours = await target.run(f"test -f {directory}/{STATE_FILE}", check=False)
            if ours.exit_status == 0:
                await self._read_state(target, details)
                await emit("step", "Removing the containers" + (" and their data" if request.delete_data else ""))
                down = "down --remove-orphans" + (" --volumes" if request.delete_data else "")
                compose = compose_command(
                    details["install_dir"],
                    details["project"],
                    Components(**details["components"]),
                    shared=bool(details.get("share_backend")),
                )
                await target.run(
                    f"{compose} {down}",
                    sudo=facts.docker_needs_sudo,
                    on_output=lambda line: emit("output", line),
                )
            else:
                await emit("output", f"{details['install_dir']} holds no install any more; nothing to stop there.")

            if target_in.kind == "ssh":
                await emit("step", "Removing this WebUI's SSH key from the host")
                marker = shlex.quote(f"ultimascraper-webui {details['project']}")
                await target.run(
                    "if [ -f ~/.ssh/authorized_keys ]; then "
                    f"grep -vF -- {marker} ~/.ssh/authorized_keys > ~/.ssh/authorized_keys.usr-tmp || true; "
                    # cat keeps the original file, with its owner and mode.
                    "cat ~/.ssh/authorized_keys.usr-tmp > ~/.ssh/authorized_keys && rm ~/.ssh/authorized_keys.usr-tmp; fi"
                )
            if request.remove_files and ours.exit_status == 0:
                await emit("step", f"Removing {details['install_dir']}")
                await target.run(f"rm -rf -- {directory}")
            elif ours.exit_status == 0:
                await emit("output", f"Kept {details['install_dir']}; its .env holds this install's secrets.")

            if deployment.connection_id:
                await self.tunnels.close(deployment.connection_id)
                try:
                    self.connections.delete(deployment.connection_id)
                except HTTPException:
                    pass
            self.store.save_deployment(
                DeploymentRecord(
                    deployment.id,
                    deployment.name,
                    deployment.target,
                    deployment.details,
                    None,
                    "removed",
                    deployment.created_at,
                    time.time(),
                )
            )
            kept = "" if request.delete_data else " Its data volumes were kept."
            await emit("done", f"{deployment.name} is uninstalled.{kept}")
            return None
        finally:
            await target.close()

    # ---- Shared steps ----------------------------------------------------

    async def _connect(self, target_in: TargetIn, emit: Emit) -> Target:
        await emit("step", f"Connecting to {describe_target(target_in)}")
        return await self.open_target(target_in)

    async def _check_host(
        self, target: Target, target_in: TargetIn, emit: Emit, *, install_missing_docker: bool
    ) -> HostFacts:
        await emit("step", "Checking the host")
        facts = await probe(target, sudo_available=True)
        if facts.docker_version is None and install_missing_docker:
            await emit("step", "Installing Docker")
            await install_docker(target, lambda line: emit("output", line))
            facts = await probe(target, sudo_available=True)
        await emit(
            "output",
            f"{facts.os_name}, {facts.architecture}, Docker {facts.docker_version or 'not found'}, "
            f"Compose {facts.compose_version or 'not found'}"
            + (", Docker through sudo" if facts.docker_needs_sudo else ""),
        )
        if facts.docker_version is None:
            hint = (
                ""
                if target_in.sudo_password
                else f" If it is installed, add {facts.user} to the docker group or give the sudo password."
            )
            raise InstallError(
                "Docker Engine is not available on this host. Choose to install it, or install it with the "
                f"Compose plugin yourself (https://docs.docker.com/engine/install/), then try again.{hint}"
            )
        if facts.compose_version is None:
            raise InstallError(
                "The Docker Compose plugin is missing. Install docker-compose-plugin, then try again."
            )
        return facts

    @staticmethod
    async def _write_files(target: Target, spec: DeploySpec, rendered: Rendered) -> bool:
        """Writes the install's files; True when the folder did not exist before."""
        directory = shlex.quote(spec.install_dir)
        existing = await target.run(f"test -e {directory}/.env", check=False)
        if existing.exit_status == 0:
            raise InstallError(f"{spec.install_dir} already holds an install. Choose another folder or name.")
        created = (await target.run(f"test -d {directory}", check=False)).exit_status != 0
        await target.run(f"mkdir -p {directory} && chmod 700 {directory}")
        for name, (content, mode) in rendered.files.items():
            await Installer._put(target, f"{spec.install_dir}/{name}", content, mode)
        return created

    @staticmethod
    async def _remove_files(
        target: Target, spec: DeploySpec, rendered: Rendered, created_dir: bool, emit: Emit
    ) -> None:
        """Removes only the files this install wrote, and the folder if it made it."""
        await emit("output", f"Removing the files written to {spec.install_dir}")
        files = " ".join(shlex.quote(f"{spec.install_dir}/{name}") for name in rendered.files)
        command = f"rm -f -- {files}"
        if created_dir:
            command += f" && rmdir -- {shlex.quote(spec.install_dir)}"
        result = await target.run(command, check=False)
        if result.exit_status != 0:
            await emit("output", f"Could not remove them all; delete {spec.install_dir} before retrying.")

    @staticmethod
    async def _put(target: Target, path: str, content: bytes, mode: int) -> None:
        quoted = shlex.quote(path)
        # umask keeps the file private while it is written.
        await target.run(f"umask 077 && cat > {quoted} && chmod {mode:o} {quoted}", stdin=content)

    @staticmethod
    async def _write_state(target: Target, spec: DeploySpec, image_source: str) -> None:
        state = {
            "schema": 1,
            "installed_by": "ultimascraper-webui",
            "project": spec.project,
            "version": spec.version,
            "image_source": image_source,
            "image_prefix": spec.image_prefix,
            "components": spec.components.profiles(),
            "backend_port": spec.backend_port,
            "web_port": spec.web_port,
            "share_backend": spec.share_backend,
            "updated_at": time.time(),
        }
        await Installer._put(target, f"{spec.install_dir}/{STATE_FILE}", json.dumps(state, indent=2).encode(), 0o600)

    @staticmethod
    async def _read_state(target: Target, details: dict) -> dict:
        """The host's state file, which must describe this deployment."""
        result = await target.run(f"cat {shlex.quote(details['install_dir'] + '/' + STATE_FILE)}", check=False)
        try:
            state = json.loads(result.stdout) if result.exit_status == 0 else None
        except ValueError:
            state = None
        if not state or state.get("project") != details["project"]:
            raise InstallError(
                f"{details['install_dir']} on the host is not this deployment any more "
                "(its install record is missing or differs)."
            )
        return state

    async def _provide_images(
        self,
        target: Target,
        facts: HostFacts,
        target_kind: str,
        source: str,
        spec: DeploySpec,
        names: list[str],
        compose: str,
        emit: Emit,
    ) -> None:
        if not names:
            return
        if source == "copy" and target_kind == "local":
            # This server's Docker is the target's: the images are already there.
            source = "target"
        if source == "copy":
            await emit("step", f"Copying the {facts.architecture} images from this server")
            releases = [
                release
                for release in await local_releases()
                if release.version == spec.version and release.architecture == facts.architecture
            ]
            if not releases:
                raise InstallError(
                    f"This server has no {facts.architecture} images for version {spec.version}. "
                    "Build or load them here, or pull from a registry instead."
                )
            missing = [name for name in names if name not in releases[0].names]
            if missing:
                raise InstallError(f"This server lacks the {', '.join(missing)} image for version {spec.version}.")
            await copy_images(
                target,
                names,
                spec.version,
                docker_sudo=facts.docker_needs_sudo,
                on_output=lambda line: emit("output", line),
            )
        elif source == "target":
            await emit("step", "Checking the images already on the host")
            await require_images_on_target(
                target,
                [image_reference(spec)],
                docker_sudo=facts.docker_needs_sudo,
                architecture=facts.architecture,
            )
        else:
            await emit("step", "Pulling the images")
            await target.run(
                f"{compose} pull --quiet", sudo=facts.docker_needs_sudo, on_output=lambda line: emit("output", line)
            )

    @staticmethod
    async def _start_services(target: Target, facts: HostFacts, compose: str, emit: Emit) -> None:
        await emit("step", "Starting the services")
        try:
            await target.run(
                f"{compose} up --detach --wait --wait-timeout 600",
                sudo=facts.docker_needs_sudo,
                on_output=lambda line: emit("output", line),
            )
        except CommandFailed:
            await target.run(
                f"{compose} ps", sudo=facts.docker_needs_sudo, check=False, on_output=lambda line: emit("output", line)
            )
            raise InstallError("The services did not become healthy. The log above shows their state.") from None

    async def _register_worker_inventory(
        self,
        spec: DeploySpec,
        node_name: str,
        target_in: TargetIn,
        join_connection_id: str,
        cluster_info: dict[str, Any] | None,
        emit: Emit,
    ) -> None:
        await emit("step", "Registering worker in cluster inventory")
        registered = await register_worker_inventory(
            self.connections,
            self.tunnels,
            connection_id=join_connection_id,
            node_name=node_name,
            backend_id=spec.backend_id,
            address=target_in.host if (target_in.kind == "ssh" and target_in.host) else _local_lan_ip(),
            settings_id=cluster_info.get("settings_id") if cluster_info else None,
        )
        if registered:
            await emit("output", f"Registered worker '{spec.backend_id}' in cluster inventory.")

    async def _verify_worker_cluster(
        self,
        target: Target,
        facts: HostFacts,
        compose: str,
        spec: DeploySpec,
        join_connection_id: str,
        emit: Emit,
    ) -> None:
        await emit("step", "Checking worker cluster identity against the backend")

        async def resolve_connection(cid: str) -> Connection:
            return await self.tunnels.resolve(self.connections.get(cid))

        clusters_out = await describe_clusters(self.connections, self.store, resolve_connection)
        member = next((m for m in clusters_out.members if m.connection_id == join_connection_id), None)
        expected_cluster_id = member.identity.cluster_id if (member and member.identity) else None
        if not expected_cluster_id:
            raise InstallError(
                f"Could not verify cluster identity for backend connection '{join_connection_id}'."
            )

        worker_cluster_id: str | None = None
        for cluster in clusters_out.clusters:
            if any(s.backend_id == spec.backend_id for s in cluster.suggestions):
                worker_cluster_id = cluster.cluster_id
                break

        if worker_cluster_id is None:
            probe_cmd = (
                f"{compose} exec -T worker python -c "
                "\"from ultima_scraper_backend.cluster import get_cluster_id; print(get_cluster_id() or '')\""
            )
            result = await target.run(probe_cmd, sudo=facts.docker_needs_sudo, check=False)
            if result.exit_status == 0 and result.stdout.strip():
                worker_cluster_id = result.stdout.strip().splitlines()[-1].strip()

        if worker_cluster_id != expected_cluster_id:
            raise InstallError(
                f"Cluster identity mismatch: worker reported '{worker_cluster_id or 'none'}', "
                f"but backend '{member.name if member else join_connection_id}' is in cluster '{expected_cluster_id}'. "
                "Ensure PostgreSQL and Redis point to that backend's stores. The install was kept: "
                "uninstall it from the Backends page, or correct its .env and repair it."
            )
        await emit("output", f"Worker joined cluster {expected_cluster_id}.")

    async def _register(
        self, target: Target, target_in: TargetIn, name: str, spec: DeploySpec, rendered: Rendered
    ) -> Connection:
        base_url = f"http://127.0.0.1:{spec.backend_port}"
        tunnel: StoredTunnel | None = None
        if target_in.kind == "ssh":
            assert target_in.host and target_in.username and target_in.host_key
            # A key that can do nothing but forward to this backend's port.
            key = asyncssh.generate_private_key("ssh-ed25519", comment=f"ultimascraper-webui {spec.project}")
            public = key.export_public_key().decode().strip()
            line = f'restrict,port-forwarding,permitopen="127.0.0.1:{spec.backend_port}" {public}'
            await target.run(
                "umask 077 && mkdir -p ~/.ssh && touch ~/.ssh/authorized_keys && "
                f"(grep -qxF {shlex.quote(line)} ~/.ssh/authorized_keys || "
                f"printf '%s\\n' {shlex.quote(line)} >> ~/.ssh/authorized_keys)"
            )
            tunnel = StoredTunnel(
                host=target_in.host,
                port=target_in.port,
                user=target_in.username,
                private_key=key.export_private_key().decode(),
                host_key=target_in.host_key,
            )
        return self.connections.create_installed(
            name=name, base_url=base_url, token=rendered.admin_token, tunnel=tunnel
        )

    async def _check_connection(self, deployment: DeploymentRecord, emit: Emit) -> None:
        if not deployment.connection_id:
            return
        await emit("step", "Checking this WebUI's connection")
        await self._wait_for_backend(self.connections.get(deployment.connection_id), emit)

    async def _wait_for_backend(self, connection: Connection, emit: Emit) -> None:
        message = ""
        for _ in range(20):
            try:
                result = await self.connections.test(await self.tunnels.resolve(connection))
            except ConnectionError as exc:
                message = str(exc)
            else:
                if result.authenticated:
                    await emit("output", f"Connected ({result.latency_ms} ms).")
                    return
                message = result.message
            await asyncio.sleep(3)
        raise InstallError(f"The backend is running, but this WebUI cannot reach it: {message}")


async def _running_image_version(target: Target, facts: HostFacts, compose: str, components: Components) -> str:
    """The exact build the deployment runs (e.g. 0.1.0-edge.0123abcd4567), from its image label.

    A tag such as edge or latest moves; the label names the build behind it.
    Empty when no UltimaScraper service runs or the image has no label.
    """
    service = next((name for name in _service_names(components)), None)
    if service is None:
        return ""
    label = '{{ index .Config.Labels "org.opencontainers.image.version" }}'
    result = await target.run(
        f"{compose} ps -q {service} | head -n 1 | xargs -r docker inspect --format {shlex.quote(label)}",
        sudo=facts.docker_needs_sudo,
        check=False,
    )
    version = result.stdout.strip().splitlines()[-1].strip() if result.exit_status == 0 and result.stdout.strip() else ""
    return "" if version == "<no value>" else version


def _parse_env(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip("'")
    return values


def _set_env_command(env_file: str, key: str, value: str) -> str:
    """Replace KEY=... in the .env, or add it."""
    line = shlex.quote(f"{key}={value}")
    edit = shlex.quote(f"s|^{key}=.*|{key}={value}|")
    return f"if grep -q '^{key}=' {env_file}; then sed -i {edit} {env_file}; else printf '%s\\n' {line} >> {env_file}; fi"


def _service_names(components: Components) -> list[str]:
    """The UltimaScraper services these components run."""
    return [name for name in ("backend", "worker", "webui") if getattr(components, name)]


def _image_names(components: Components) -> list[str]:
    """The images they need: the one image every service runs, when any runs."""
    return [IMAGE_NAME] if _service_names(components) else []


def _failure_message(exc: BaseException) -> str:
    if isinstance(exc, (InstallError, UnsupportedHost, InvalidSpec, ImagesUnavailable, DockerSetupFailed)):
        return str(exc)
    if isinstance(exc, asyncssh.HostKeyNotVerifiable):
        return "The host's SSH key is not the one you accepted. Check the host, then start again."
    if isinstance(exc, asyncssh.PermissionDenied):
        return "SSH sign-in was refused. Check the user and password or key."
    if isinstance(exc, CommandFailed):
        return f"A command failed: {exc}"
    if isinstance(exc, OSError):
        return f"Could not reach the host: {exc}"
    return f"Unexpected error: {exc}"


async def register_worker_inventory(
    connections: Connections,
    tunnels: TunnelManager,
    *,
    connection_id: str,
    node_name: str,
    backend_id: str,
    address: str,
    settings_id: int | None,
) -> bool:
    """List a worker host in the cluster's inventory through one of its backends."""
    try:
        reached = await tunnels.resolve(connections.get(connection_id))
        token = reached.token()
        headers = {"x-usr-admin-token": token} if token else {}
        async with httpx.AsyncClient(base_url=reached.base_url, verify=reached.tls_verify, timeout=10.0) as client:
            if not settings_id:
                list_resp = await client.get("/api/v1/settings/db/backends", headers=headers)
                if list_resp.is_success and list_resp.json():
                    settings_id = list_resp.json()[0].get("settings_id") or 1
                else:
                    settings_id = 1
            resp = await client.put(
                "/api/v1/settings/db/backends",
                headers=headers,
                json={
                    "backend_name": node_name,
                    "hostname": backend_id,
                    "local_ip": address,
                    "settings_id": settings_id,
                },
            )
        if resp.is_success:
            return True
        logger.warning("Failed registering worker inventory (HTTP %s): %s", resp.status_code, resp.text)
    except Exception as exc:
        logger.warning("Failed registering worker in cluster inventory: %s", exc)
    return False


def in_container() -> bool:
    return Path("/.dockerenv").exists()


def _local_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

