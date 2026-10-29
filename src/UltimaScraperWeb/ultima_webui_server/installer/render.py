"""The files an install writes: the Compose files and a generated .env."""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

COMPOSE_DIR = Path(__file__).resolve().parent / "compose"
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.backend-port.yml")
STORE_PORTS_FILE = "docker-compose.store-ports.yml"
# Present only when the backend serves HTTPS for other machines.
BACKEND_TLS_FILE = "docker-compose.backend-tls.yml"
DEFAULT_BACKEND_TLS_PORT = 8443
COMPONENT_RULES_PATH = Path(__file__).resolve().parent / "component_rules.json"
_PROJECT_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def load_component_rules() -> dict[str, Any]:
    return json.loads(COMPONENT_RULES_PATH.read_text(encoding="utf-8"))


COMPONENT_RULES: dict[str, Any] = load_component_rules()
_COMBINATION_INDEX: dict[tuple[str, str, str, str, str], dict[str, Any]] = {
    (
        row["backend"],
        row["worker"],
        row["postgres"],
        row["redis"],
        row["webui"],
    ): row
    for row in COMPONENT_RULES["combinations"]
}


class InvalidSpec(ValueError):
    pass


@dataclass(frozen=True)
class Components:
    backend: bool = True
    worker: bool = True
    postgres: bool = True
    redis: bool = True
    webui: bool = False

    def profiles(self) -> list[str]:
        return [name for name in ("webui", "backend", "worker", "postgres", "redis") if getattr(self, name)]

    @property
    def store_only(self) -> bool:
        """PostgreSQL or Redis for other hosts: their ports are published."""
        return not self.backend and not self.worker and (self.postgres or self.redis)


@dataclass(frozen=True)
class DatabaseSpec:
    host: str = "localhost"
    port: int = 5432
    name: str = "ultima_archive"
    user: str = "ultimascraper"
    password: str = ""


@dataclass(frozen=True)
class DeploySpec:
    # Compose project name; keeps several installs on one host apart.
    project: str
    install_dir: str
    components: Components
    # Registry root (e.g. forgejo.example/org/ultimascraper), or "" for
    # the local image names that copied images keep.
    image_prefix: str
    version: str
    # Unique per install: backends sharing a database must not share an id.
    backend_id: str
    backend_port: int
    web_port: int
    database_url: str | None = None
    database: DatabaseSpec | None = None
    postgres_port: int = 5432
    redis_host: str | None = None
    redis_port: int = 6379
    redis_password: str | None = None
    # Names the host's own WebUI is opened at, for its HTTPS certificate.
    webui_hostnames: tuple[str, ...] = ()
    secret_key: str | None = None
    default_backend_url: str | None = None
    default_backend_token: str | None = None
    # Let other machines use this backend: HTTPS on backend_tls_port of every
    # interface.
    share_backend: bool = False
    # The host's address on its network, which its containers report.
    advertise_host: str = ""
    backend_tls_port: int = DEFAULT_BACKEND_TLS_PORT


@dataclass(frozen=True)
class Rendered:
    # Path relative to the install directory -> (content, file mode).
    files: dict[str, tuple[bytes, int]]
    admin_token: str

    def compose_command(self, spec: DeploySpec) -> str:
        ordered = [name for name in (*COMPOSE_FILES, STORE_PORTS_FILE, BACKEND_TLS_FILE) if name in self.files]
        files = " ".join(f"-f {name}" for name in ordered)
        return f"docker compose --project-name {spec.project} {files}"


def rewrite_host_for_container(host: str) -> str:
    stripped = host.strip()
    if stripped.lower() in _LOCAL_HOSTS:
        return "host.docker.internal"
    return stripped


def build_database_url(db: DatabaseSpec) -> str:
    host = rewrite_host_for_container(db.host)
    user = quote(db.user, safe="")
    name = quote(db.name, safe="")
    if db.password:
        password = quote(db.password, safe="")
        auth = f"{user}:{password}"
    else:
        auth = user
    return f"postgresql+asyncpg://{auth}@{host}:{db.port}/{name}"


def rewrite_database_url(database_url: str) -> str:
    raw = database_url.strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    hostname = parsed.hostname
    if hostname is None or hostname.lower() not in _LOCAL_HOSTS:
        return raw
    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    port_suffix = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{userinfo}host.docker.internal{port_suffix}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def resolve_database_url(spec: DeploySpec) -> str:
    if spec.database is not None:
        return build_database_url(spec.database)
    if spec.database_url:
        return rewrite_database_url(spec.database_url)
    return ""


def component_modes(spec: DeploySpec) -> tuple[str, str, str, str, str]:
    c = spec.components
    has_existing_db = bool(spec.database_url or (spec.database is not None and spec.database.host.strip()))
    return (
        "install" if c.backend else "none",
        "install" if c.worker else "none",
        "install" if c.postgres else ("existing" if has_existing_db else "none"),
        "install" if c.redis else ("existing" if spec.redis_host else "none"),
        "install" if c.webui else "reuse",
    )


def validate_modes(backend: str, worker: str, postgres: str, redis: str, webui: str) -> None:
    row = _COMBINATION_INDEX.get((backend, worker, postgres, redis, webui))
    if row is None:
        raise InvalidSpec(f"Unsupported component combination: {(backend, worker, postgres, redis, webui)!r}")
    if not row["valid"]:
        error_code = row["error_code"]
        message = COMPONENT_RULES["error_messages"].get(error_code, "Invalid component combination.")
        raise InvalidSpec(message)


def normalize_image_prefix(prefix: str) -> str:
    """Normalize a registry image prefix for Docker.

    Strips protocol (https:// or http://), trailing slashes, and lowercases the
    repository path so Docker daemon doesn't reject uppercase repository names.
    """
    cleaned = prefix.strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip("/").lower()


def image_reference(spec: DeploySpec, name: str) -> str:
    prefix = normalize_image_prefix(spec.image_prefix)
    image = f"{prefix}/{name}" if prefix else f"ultimascraper-{name}"
    return f"{image}:{spec.version}"


def validate(spec: DeploySpec) -> None:
    if not _PROJECT_RE.fullmatch(spec.project):
        raise InvalidSpec("Use lowercase letters, digits, '-' and '_' for the deployment name.")
    validate_modes(*component_modes(spec))
    db_fields = (
        (spec.database.host, spec.database.name, spec.database.user, spec.database.password)
        if spec.database is not None
        else ()
    )
    if spec.share_backend and not spec.components.backend:
        raise InvalidSpec("Only a backend can be shared with other machines.")
    if spec.share_backend and not spec.advertise_host.strip():
        raise InvalidSpec("Say which address other machines reach this backend at.")
    for value in (
        spec.database_url,
        spec.redis_host,
        spec.redis_password,
        spec.install_dir,
        spec.advertise_host,
        *db_fields,
    ):
        if value and ("\n" in value or "\r" in value):
            raise InvalidSpec("Values cannot contain line breaks.")


def render(spec: DeploySpec) -> Rendered:
    validate(spec)
    admin_token = spec.default_backend_token or secrets.token_urlsafe(32)
    resolved_db_url = "" if spec.components.postgres else resolve_database_url(spec)
    resolved_redis_host = "redis" if spec.components.redis else rewrite_host_for_container(spec.redis_host or "")
    store_only = spec.components.store_only
    secret_key = spec.secret_key or secrets.token_urlsafe(32)
    default_webui_url = "http://backend:21121" if spec.components.backend else (spec.default_backend_url or "")
    environment = {
        "COMPOSE_PROFILES": ",".join(spec.components.profiles()),
        "USR_VERSION": spec.version,
        "USR_BACKEND_IMAGE": image_reference(spec, "backend").rsplit(":", 1)[0],
        "USR_WORKER_IMAGE": image_reference(spec, "worker").rsplit(":", 1)[0],
        "USR_WEBUI_IMAGE": image_reference(spec, "webui").rsplit(":", 1)[0],
        "BACKEND_ID": spec.backend_id,
        # Known to the WebUI that installs this backend, which adds it to requests.
        "USR_ADMIN_TOKEN": admin_token,
        "USR_SECRET_KEY": secret_key,
        "USR_BACKEND_PORT": str(spec.backend_port),
        "USR_WEB_PORT": str(spec.web_port),
        # A WebUI installed without a backend connects to the cluster backend if provided,
        # or starts with no default connection.
        "USR_WEBUI_DEFAULT_BACKEND_URL": default_webui_url,
        "ULTIMA_ARCHIVE_DATABASE_URL": resolved_db_url,
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "REDIS_HOST": resolved_redis_host,
        "REDIS_PORT": str(spec.redis_port) if (not spec.components.redis or store_only) else "6379",
        "REDIS_PASSWORD": secrets.token_urlsafe(24) if spec.components.redis else spec.redis_password or "",
    }
    if store_only and spec.components.postgres:
        environment["POSTGRES_PORT"] = str(spec.postgres_port)
    if spec.components.webui:
        # People open that WebUI directly over the network: HTTPS, with a
        # certificate it creates for the host's names.
        environment["USR_WEBUI_TLS"] = "self-signed"
        environment["USR_WEBUI_TLS_HOSTNAMES"] = ",".join(spec.webui_hostnames)
    if spec.advertise_host.strip():
        environment["USR_ADVERTISE_HOST"] = spec.advertise_host.strip()
    if spec.share_backend:
        environment["USR_BACKEND_TLS_PORT"] = str(spec.backend_tls_port)
    env_file = "".join(f"{key}={_env_value(value)}\n" for key, value in environment.items())
    compose_names = (*COMPOSE_FILES, STORE_PORTS_FILE) if store_only else COMPOSE_FILES
    if spec.share_backend:
        compose_names = (*compose_names, BACKEND_TLS_FILE)
    files: dict[str, tuple[bytes, int]] = {
        name: ((COMPOSE_DIR / name).read_bytes(), 0o644) for name in compose_names
    }
    files[".env"] = (
        b"# Written by the UltimaScraper WebUI installer. Holds this install's secrets.\n"
        + env_file.encode("utf-8"),
        0o600,
    )
    return Rendered(files=files, admin_token=admin_token)


def _env_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@%+,=-]*", value):
        return value
    # Compose takes single-quoted values literally, with no way to escape a quote.
    if "'" in value:
        raise InvalidSpec("Values cannot contain single quotes.")
    return f"'{value}'"

