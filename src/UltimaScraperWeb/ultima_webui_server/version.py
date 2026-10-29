"""Which release this WebUI is."""

from __future__ import annotations

import os
from importlib import metadata

PACKAGE = "ultima-scraper-webui-server"


def package_version() -> str:
    """The installed package's version (PEP 440, e.g. 0.1.0.dev20261025004224)."""
    try:
        return metadata.version(PACKAGE)
    except metadata.PackageNotFoundError:
        return ""


def own_version() -> str:
    """This WebUI's release as an image tag, the version a registry install suggests.

    The WebUI image names it in USR_WEBUI_VERSION. A published package records
    the image built from the same commit (e.g. 0.1.0-edge.0123abcd4567), since
    its own dev version is not an image tag. A local build falls back to the
    package version.
    """
    version = os.environ.get("USR_WEBUI_VERSION", "").strip()
    if version and version != "dev":
        return version
    try:
        from . import _build  # type: ignore[attr-defined]
    except ImportError:
        pass
    else:
        if getattr(_build, "IMAGE_VERSION", ""):
            return _build.IMAGE_VERSION
    return package_version()
