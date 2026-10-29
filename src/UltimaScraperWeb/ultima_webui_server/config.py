"""Settings read from the environment once at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

from .hosts import parse_allowed_hosts

PACKAGE_DIR = Path(__file__).resolve().parent


def env_secret(name: str) -> str | None:
    """A secret from ``NAME`` or the file named by ``NAME_FILE``."""
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    file = (os.environ.get(f"{name}_FILE") or "").strip()
    if file:
        return Path(file).read_text(encoding="utf-8").strip() or None
    return None


def default_data_dir() -> Path:
    return Path(user_data_dir("UltimaScraper", "UltimaScraper")) / "webui"


def default_static_dir() -> Path:
    packaged = PACKAGE_DIR / "static"
    if (packaged / "index.html").is_file():
        return packaged
    repo_dist = PACKAGE_DIR.parent / "webui" / "dist"
    if (repo_dist / "index.html").is_file():
        return repo_dist
    return packaged


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    static_dir: Path
    host: str = "127.0.0.1"
    port: int = 21120
    # The connection /api and /ws reach, as nginx did before this server.
    default_backend_url: str | None = None
    # The token is read on each use: the backend may generate it after we start.
    default_backend_token_file: Path | None = None
    default_backend_token: str | None = None
    # Proxies in front of this server whose X-Forwarded-For is believed,
    # e.g. 127.0.0.1 for a dev server; none by default.
    trusted_proxies: str | None = None
    # Host names served besides IPs, single-label names, this machine's names
    # and private TLDs (see hosts.py); "*" turns the check off.
    allowed_hosts: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> Settings:
        token_file = (os.environ.get("USR_WEBUI_DEFAULT_BACKEND_TOKEN_FILE") or "").strip()
        return cls(
            data_dir=Path(os.environ.get("USR_WEBUI_DATA_DIR") or default_data_dir()),
            static_dir=Path(os.environ.get("USR_WEBUI_STATIC_DIR") or default_static_dir()),
            host=os.environ.get("USR_WEBUI_HOST") or "127.0.0.1",
            port=int(os.environ.get("USR_WEBUI_PORT") or 21120),
            default_backend_url=(os.environ.get("USR_WEBUI_DEFAULT_BACKEND_URL") or "").strip()
            or None,
            default_backend_token_file=Path(token_file) if token_file else None,
            default_backend_token=(os.environ.get("USR_WEBUI_DEFAULT_BACKEND_TOKEN") or "").strip()
            or None,
            trusted_proxies=(os.environ.get("USR_WEBUI_TRUSTED_PROXIES") or "").strip() or None,
            allowed_hosts=parse_allowed_hosts(os.environ.get("USR_WEBUI_ALLOWED_HOSTS")),
        )
