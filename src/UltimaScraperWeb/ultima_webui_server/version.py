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


# The image every push to main publishes, for a WebUI with no image of its own.
EDGE_IMAGE = "edge"


def _image_version() -> str:
    """The image this WebUI was built as, if any (e.g. 0.1.0-edge.0123abcd4567)."""
    version = os.environ.get("USR_WEBUI_VERSION", "").strip()
    if version and version != "dev":
        return version
    try:
        from . import _build  # type: ignore[attr-defined]
    except ImportError:
        return ""
    return getattr(_build, "IMAGE_VERSION", "") or ""


def own_version() -> str:
    """This WebUI's release as an image tag, the version it reports to a cluster.

    The WebUI image names it in USR_WEBUI_VERSION. A published package records
    the image built from the same commit (e.g. 0.1.0-edge.0123abcd4567), since
    its own dev version is not an image tag. A local build falls back to the
    package version.
    """
    return _image_version() or package_version()


def install_version() -> str:
    """The image tag an install pulls unless told otherwise.

    This WebUI's own image, so the services match it; a local build has none,
    and its package version names no published image, so it installs edge.
    """
    return _image_version() or EDGE_IMAGE
