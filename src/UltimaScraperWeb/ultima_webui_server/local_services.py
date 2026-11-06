"""The backend and workers, run inside this WebUI's own container.

The full image holds every role, but a container started without database or
Redis settings runs only the WebUI (a NAS app, for one). Once this WebUI is in
a cluster, it can run the backend and workers itself, as child processes that
use the cluster's PostgreSQL, Redis and secret key. Each runs through the
image's entrypoint, as its own container would, and is restarted when it exits
and when this WebUI starts again.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import signal
import socket
import sys
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote, urlsplit

from fastapi import HTTPException
from pydantic import BaseModel

from .connections import Connection, Connections
from .store import Store
from .tunnels import TunnelManager
from .vault import Vault

logger = logging.getLogger("ultima_webui_server.local_services")

ENTRYPOINT = "usr-container-entrypoint"
BACKEND_PORT = 21121
_SETTING = "local_services"
_SECRET_FIELDS = ("database_url", "redis_password", "secret_key", "admin_token")
_LOG_LINES = 200
_STOP_SECONDS = 20
_FIRST_RESTART_SECONDS = 5.0
_MAX_RESTART_SECONDS = 60.0
# A run this long counts as healthy, so the next restart waits the least again.
_HEALTHY_RUN_SECONDS = 60.0
_CHECK_SECONDS = 3.0

ServiceName = Literal["backend", "worker"]
ServiceState = Literal["running", "restarting", "stopped"]
_ROLES: dict[ServiceName, str] = {"backend": "api", "worker": "worker"}


def in_container() -> bool:
    return os.path.exists("/.dockerenv")


def available() -> bool:
    """A container of the full image: it can run the backend and workers too."""
    return in_container() and shutil.which(ENTRYPOINT) is not None and shutil.which("ultimascraper") is not None


class ServiceOut(BaseModel):
    name: ServiceName
    state: ServiceState
    exit_code: int | None = None
    log: list[str]


class LocalServicesOut(BaseModel):
    available: bool
    backend: bool
    worker: bool
    cluster_id: str | None = None
    backend_id: str | None = None
    advertise_host: str | None = None
    services: list[ServiceOut]


class LocalServicesIn(BaseModel):
    cluster_id: str
    backend: bool
    worker: bool
    # This machine's address on its network; a container cannot see it.
    advertise_host: str | None = None


@dataclass
class LocalHost:
    """What fleet_hosts needs to place these services on this WebUI's host."""

    cluster_id: str | None
    address: str | None
    backend: bool
    worker: bool
    backend_id: str | None


def _loopback_or_service_name(host: str) -> bool:
    """Whether an address only means something on the machine that reported it."""
    if host in {"localhost", "host.docker.internal"} or ("." not in host and ":" not in host):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _source_host(connection: Connection) -> str | None:
    """The machine a connection's backend runs on, as other machines reach it."""
    host = connection.tunnel.host if connection.tunnel else urlsplit(connection.base_url).hostname
    return None if not host or _loopback_or_service_name(host) else host


def _database_url(database: dict[str, Any]) -> str:
    user = quote(str(database.get("username") or ""), safe="")
    password = quote(str(database.get("password") or ""), safe="")
    credentials = f"{user}:{password}@" if password else f"{user}@"
    host = str(database["host"])
    if ":" in host:
        host = f"[{host}]"
    name = quote(str(database.get("name") or "ultima_archive"), safe="")
    return f"postgresql+psycopg://{credentials}{host}:{int(database.get('port') or 5432)}/{name}"


async def _reachable(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=_CHECK_SECONDS)
    except (OSError, TimeoutError):
        return False
    writer.close()
    return True


def _inventory_address(advertise_host: str | None) -> str:
    """An IP address for the cluster's inventory, which stores only addresses."""
    if advertise_host:
        try:
            return str(ipaddress.ip_address(advertise_host))
        except ValueError:
            try:
                return socket.gethostbyname(advertise_host)
            except OSError:
                pass
    # This container's own address, the one its outgoing connections use.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:40] or "usr"


class _Service:
    """One child process, restarted when it exits until it is stopped."""

    def __init__(self, name: ServiceName, command: list[str]) -> None:
        self.name = name
        self.command = command
        self.state: ServiceState = "stopped"
        self.exit_code: int | None = None
        self.log: deque[str] = deque(maxlen=_LOG_LINES)
        self.environment: dict[str, str] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self, environment: dict[str, str]) -> None:
        self.environment = environment
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.environment = None
        task, self._task = self._task, None
        process = self._process
        if process is not None and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), timeout=_STOP_SECONDS)
            except ProcessLookupError:
                pass
            except TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.state = "stopped"

    def _record(self, line: str) -> None:
        self.log.append(line)
        # The container's own log shows it too, as its own container's would.
        sys.stdout.write(f"[{self.name}] {line}\n")
        sys.stdout.flush()

    async def _run(self) -> None:
        delay = _FIRST_RESTART_SECONDS
        while self.environment is not None:
            started = time.monotonic()
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *self.command,
                    env=self.environment,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    # Its own process group, so stopping it reaches its children.
                    start_new_session=True,
                )
            except OSError as exc:
                self._record(f"Could not start: {exc}")
                self.exit_code = None
            else:
                self.state = "running"
                assert self._process.stdout is not None
                async for raw in self._process.stdout:
                    self._record(raw.decode("utf-8", "replace").rstrip())
                self.exit_code = await self._process.wait()
                self._record(f"Exited with code {self.exit_code}.")
            if self.environment is None:
                break
            if time.monotonic() - started >= _HEALTHY_RUN_SECONDS:
                delay = _FIRST_RESTART_SECONDS
            self.state = "restarting"
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_RESTART_SECONDS)
        self.state = "stopped"


StoresReader = Callable[[str], Awaitable[dict[str, Any]]]


class LocalServices:
    def __init__(
        self,
        store: Store,
        vault: Vault,
        connections: Connections,
        tunnels: TunnelManager,
        *,
        read_stores: StoresReader,
        cluster_connections: Callable[[str], list[Connection]],
        register_worker: Callable[..., Awaitable[bool]],
        command: list[str] | None = None,
        is_available: Callable[[], bool] = available,
    ) -> None:
        self.store = store
        self.vault = vault
        self.connections = connections
        self.tunnels = tunnels
        self._read_stores = read_stores
        self._cluster_connections = cluster_connections
        self._register_worker = register_worker
        self._is_available = is_available
        command = command or [ENTRYPOINT, "ultimascraper"]
        self._services: dict[ServiceName, _Service] = {name: _Service(name, command) for name in _ROLES}
        self._lock = asyncio.Lock()

    # ---- Saved configuration -----------------------------------------

    def _load(self) -> dict[str, Any]:
        raw = self.store.get_setting(_SETTING)
        if not raw:
            return {}
        config = json.loads(raw)
        for field in _SECRET_FIELDS:
            if config.get(field):
                config[field] = self.vault.decrypt(config[field])
        return config

    def _save(self, config: dict[str, Any]) -> None:
        sealed = dict(config)
        for field in _SECRET_FIELDS:
            if sealed.get(field):
                sealed[field] = self.vault.encrypt(sealed[field])
        self.store.set_setting(_SETTING, json.dumps(sealed))

    def local_host(self) -> LocalHost | None:
        config = self._load()
        if not config:
            return None
        return LocalHost(
            cluster_id=config.get("cluster_id"),
            address=config.get("advertise_host"),
            backend=bool(config.get("backend")),
            worker=bool(config.get("worker")),
            backend_id=config.get("backend_id"),
        )

    def describe(self) -> LocalServicesOut:
        config = self._load()
        return LocalServicesOut(
            available=self._is_available(),
            backend=bool(config.get("backend")),
            worker=bool(config.get("worker")),
            cluster_id=config.get("cluster_id"),
            backend_id=config.get("backend_id"),
            advertise_host=config.get("advertise_host"),
            services=[
                ServiceOut(name=name, state=service.state, exit_code=service.exit_code, log=list(service.log))
                for name, service in self._services.items()
            ],
        )

    # ---- Changing what runs ------------------------------------------

    async def _stores(self, cluster_id: str) -> tuple[dict[str, Any], Connection]:
        """The cluster's database, Redis and secret key, from a backend of it."""
        members = [
            connection
            for connection in self._cluster_connections(cluster_id)
            # Never this container's own backend: it gets them from here.
            if connection.id != self._load().get("connection_id")
        ]
        for connection in members:
            stores = await self._read_stores(connection.id)
            if not stores.get("available") or stores.get("cluster_id") not in (cluster_id, None):
                continue
            source_host = _source_host(connection)
            for kind in ("database", "redis"):
                found = stores.get(kind)
                if found and source_host and _loopback_or_service_name(str(found.get("host") or "")):
                    # Where that backend runs, which is not this machine.
                    found["host"] = source_host
            return stores, connection
        raise HTTPException(
            status_code=502,
            detail="No backend of this cluster gave its database and Redis settings. Check that one is running.",
        )

    async def configure(self, request: LocalServicesIn) -> LocalServicesOut:
        if not self._is_available():
            raise HTTPException(
                status_code=409,
                detail="This WebUI cannot run the backend or workers: it does not run from the full UltimaScraper image.",
            )
        async with self._lock:
            config = self._load()
            if request.backend or request.worker:
                stores, source = await self._stores(request.cluster_id)
                database, redis = stores.get("database"), stores.get("redis")
                if not database or not redis:
                    raise HTTPException(status_code=502, detail="The cluster did not report both PostgreSQL and Redis.")
                for label, found, default_port in (("PostgreSQL", database, 5432), ("Redis", redis, 6379)):
                    host, port = str(found["host"]), int(found.get("port") or default_port)
                    if not await _reachable(host, port):
                        raise HTTPException(
                            status_code=502,
                            detail=f"This container cannot reach the cluster's {label} at {host}:{port}.",
                        )
                if not stores.get("secret_key"):
                    raise HTTPException(
                        status_code=502, detail="The cluster's backend did not give its USR_SECRET_KEY."
                    )
                advertise = (request.advertise_host or "").strip() or None
                config.update(
                    cluster_id=request.cluster_id,
                    source_connection_id=source.id,
                    settings_id=stores.get("settings_id"),
                    advertise_host=advertise,
                    backend_id=config.get("backend_id")
                    or f"{_slug(advertise or socket.gethostname())}-{secrets.token_hex(3)}",
                    admin_token=config.get("admin_token") or secrets.token_urlsafe(32),
                    database_url=_database_url(database),
                    redis_host=str(redis["host"]),
                    redis_port=int(redis.get("port") or 6379),
                    redis_db=int(redis.get("db") or 0),
                    redis_password=str(redis.get("password") or ""),
                    secret_key=str(stores["secret_key"]),
                )
            config.update(backend=request.backend, worker=request.worker)
            self._save(config)
            await self._apply(config)
            if (request.backend or request.worker) and config.get("source_connection_id"):
                # Ties this host's backend id to the cluster's settings, which
                # its backend and workers wait for before they start work.
                await self._register_worker(
                    self.connections,
                    self.tunnels,
                    connection_id=config["source_connection_id"],
                    node_name=config["backend_id"],
                    backend_id=config["backend_id"],
                    address=_inventory_address(config.get("advertise_host")),
                    settings_id=config.get("settings_id"),
                )
            self.store.audit(
                "local_services_changed",
                f"backend={'on' if request.backend else 'off'} workers={'on' if request.worker else 'off'}",
            )
        return self.describe()

    def _environment(self, name: ServiceName, config: dict[str, Any]) -> dict[str, str]:
        role = _ROLES[name]
        environment = dict(os.environ)
        chosen = {
            "USR_CONTAINER_ROLE": role,
            "RUN_MODE": role,
            "BACKEND_ID": config["backend_id"],
            "ULTIMA_ARCHIVE_DATABASE_URL": config["database_url"],
            "REDIS_HOST": config["redis_host"],
            "REDIS_PORT": str(config["redis_port"]),
            "REDIS_DB": str(config["redis_db"]),
            "REDIS_PASSWORD": config["redis_password"],
            "USR_SECRET_KEY": config["secret_key"],
            "USR_ENCRYPT_SECRETS": "true",
        }
        if name == "backend":
            chosen["USR_ADMIN_TOKEN"] = config["admin_token"]
        if config.get("advertise_host"):
            chosen["USR_ADVERTISE_HOST"] = config["advertise_host"]
        # The WebUI's own settings would otherwise reach the service: a direct
        # value next to its _FILE twin is refused, and DATABASE_URL is an alias.
        for key in (*chosen, "USR_ADMIN_TOKEN", "DATABASE_URL"):
            environment.pop(key, None)
            environment.pop(f"{key}_FILE", None)
        environment.update(chosen)
        return environment

    async def _apply(self, config: dict[str, Any]) -> None:
        for name, service in self._services.items():
            if config.get(name):
                environment = self._environment(name, config)
                if service.environment != environment:
                    await service.stop()
                    service.start(environment)
            else:
                await service.stop()
        self._sync_connection(config)

    def _sync_connection(self, config: dict[str, Any]) -> None:
        """This WebUI's connection to its own backend, while that runs."""
        connection_id = config.get("connection_id")
        if config.get("backend") and not connection_id:
            name = f"{config.get('advertise_host') or socket.gethostname()} backend"
            connection = self.connections.create_installed(
                name=name, base_url=f"http://127.0.0.1:{BACKEND_PORT}", token=config["admin_token"], tunnel=None
            )
            config["connection_id"] = connection.id
            self._save(config)
        elif not config.get("backend") and connection_id:
            self.store.delete_connection(connection_id)
            self.store.delete_identity(connection_id)
            config.pop("connection_id")
            self._save(config)

    async def resume(self) -> None:
        """Start what was running when this WebUI last stopped."""
        if not self._is_available():
            return
        config = self._load()
        if config.get("backend") or config.get("worker"):
            async with self._lock:
                await self._apply(config)

    async def stop_all(self) -> None:
        for service in self._services.values():
            await service.stop()
