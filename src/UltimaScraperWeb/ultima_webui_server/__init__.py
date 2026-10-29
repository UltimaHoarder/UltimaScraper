"""Serves the UltimaScraper WebUI and connects it to one or more backends."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .app import create_app
    from .config import Settings

__all__ = ["Settings", "create_app"]


def __getattr__(name: str) -> Any:
    # Loaded on first use: main.py imports only .launcher, which must not
    # pull the server's web and SSH stack into the runtime supervisor.
    if name == "create_app":
        from .app import create_app

        return create_app
    if name == "Settings":
        from .config import Settings

        return Settings
    raise AttributeError(name)
