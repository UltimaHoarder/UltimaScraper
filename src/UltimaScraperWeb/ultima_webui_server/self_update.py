"""The WebUI updating itself from PyPI, where each release is published.

A WebUI installed with `uv tool install` checks the index for a newer
ultima-scraper-webui-server, installs exactly that version with uv, and starts
again in its own process (os.execv), so it works with or without systemd.

Settings come from the environment:

  USR_WEBUI_UPDATE_INDEX    PEP 503 simple index to update from; defaults to
                            PyPI (https://pypi.org/simple)
  USR_WEBUI_UPDATE_CHANNEL  release (X.Y.Z only) or edge (also builds of main);
                            defaults to the channel the running version is on
  USR_WEBUI_UV              the uv executable, when it is not on PATH
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import Auth
from .installer.runner import in_container
from .version import PACKAGE, package_version

logger = logging.getLogger("ultima_webui_server.self_update")

# .github/workflows/webui-package.yml publishes every release here.
DEFAULT_INDEX = "https://pypi.org/simple"

Channel = Literal["release", "edge"]
InstallKind = Literal["uv-tool", "container", "other"]

_VERSION_RE = re.compile(r"^(?P<release>\d+(?:\.\d+)*)(?:(?P<pre>a|b|rc)(?P<pre_n>\d+))?(?:\.dev(?P<dev>\d+))?$")
_WHEEL_RE = re.compile(r"ultima_scraper_webui_server-(?P<version>[^-]+)-py3-none-any\.whl")
_PRE_RANK = {"a": 0, "b": 1, "rc": 2}
UPDATE_TIMEOUT = 600.0


def version_key(version: str) -> tuple | None:
    """A sort key for the PEP 440 versions CI publishes; None for anything else.

    X.Y.Z.devN < X.Y.ZaN < X.Y.ZbN < X.Y.ZrcN < X.Y.Z, as in PEP 440.
    """
    match = _VERSION_RE.match(version.strip())
    if match is None:
        return None
    release = tuple(int(part) for part in match["release"].split("."))
    release += (0,) * (3 - len(release))
    if match["pre"]:
        phase = (_PRE_RANK[match["pre"]], int(match["pre_n"]))
    elif match["dev"] is not None:
        phase = (-1, 0)
    else:
        phase = (3, 0)
    dev = int(match["dev"]) if match["dev"] is not None else float("inf")
    return (release, phase, dev)


def is_prerelease(version: str) -> bool:
    key = version_key(version)
    return key is not None and (key[1][0] != 3 or key[2] != float("inf"))


def newest(versions: list[str], channel: Channel) -> str | None:
    candidates = [v for v in versions if version_key(v) is not None and (channel == "edge" or not is_prerelease(v))]
    return max(candidates, key=version_key, default=None)


def versions_in_index(body: str, content_type: str) -> list[str]:
    """Versions of the WebUI package on a PEP 691 (JSON) or PEP 503 (HTML) project page."""
    if "json" in content_type:
        filenames = [entry.get("filename", "") for entry in json.loads(body).get("files", [])]
    else:
        filenames = [html.unescape(name) for name in re.findall(r">([^<]+\.whl)<", body)]
    return sorted({match["version"] for name in filenames if (match := _WHEEL_RE.search(name))})


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.username or parts.password:
        netloc = parts.hostname or ""
        if parts.port:
            netloc += f":{parts.port}"
        return urlunsplit((parts.scheme, f"***@{netloc}", parts.path, parts.query, parts.fragment))
    return url


@dataclass(frozen=True)
class Environment:
    index: str
    channel: Channel | None
    uv: str | None
    kind: InstallKind

    @classmethod
    def detect(cls) -> Environment:
        channel = os.environ.get("USR_WEBUI_UPDATE_CHANNEL", "").strip().lower()
        return cls(
            index=os.environ.get("USR_WEBUI_UPDATE_INDEX", "").strip() or DEFAULT_INDEX,
            channel=channel if channel in ("release", "edge") else None,  # type: ignore[arg-type]
            uv=find_uv(),
            kind=install_kind(),
        )


def install_kind() -> InstallKind:
    if in_container():
        return "container"
    # uv writes this receipt into every environment `uv tool install` creates.
    if (Path(sys.prefix) / "uv-receipt.toml").is_file():
        return "uv-tool"
    return "other"


def find_uv() -> str | None:
    configured = os.environ.get("USR_WEBUI_UV", "").strip()
    if configured:
        return configured if os.access(configured, os.X_OK) else None
    found = shutil.which("uv")
    if found:
        return found
    for candidate in (Path.home() / ".local/bin/uv", Path.home() / ".cargo/bin/uv"):
        if os.access(candidate, os.X_OK):
            return str(candidate)
    return None


class UpdateStatus(BaseModel):
    version: str
    install_kind: InstallKind
    channel: Channel
    index: str
    latest: str | None
    update_available: bool
    can_update: bool
    # Why there is no update to offer, when there is none.
    reason: str | None


class UpdateResult(BaseModel):
    version: str
    log: str
    restarting: bool


class SelfUpdater:
    def __init__(self, environment: Environment | None = None) -> None:
        self.environment = environment or Environment.detect()
        self._lock = asyncio.Lock()

    def channel(self, current: str) -> Channel:
        if self.environment.channel:
            return self.environment.channel
        return "edge" if is_prerelease(current) else "release"

    async def latest(self, channel: Channel) -> str | None:
        url = f"{self.environment.index.rstrip('/')}/{PACKAGE}/"
        headers = {"Accept": "application/vnd.pypi.simple.v1+json, text/html;q=0.1"}
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return newest(versions_in_index(response.text, response.headers.get("content-type", "")), channel)

    async def status(self) -> UpdateStatus:
        current = package_version()
        env = self.environment
        channel = self.channel(current)
        reason: str | None = None
        latest: str | None = None
        if env.kind == "container":
            reason = "This WebUI runs in a container: pull a newer webui image to update it."
        elif env.kind != "uv-tool":
            reason = "Only a WebUI installed with `uv tool install` updates itself."
        elif not env.index:
            reason = "Set USR_WEBUI_UPDATE_INDEX to the package index to update from."
        elif not env.uv:
            reason = "uv was not found; set USR_WEBUI_UV to its path."
        if env.index:
            try:
                latest = await self.latest(channel)
            except (httpx.HTTPError, ValueError) as exc:
                reason = reason or f"Could not read the package index: {exc}"
        newer = bool(
            latest
            and version_key(latest) is not None
            and (version_key(current) is None or version_key(latest) > version_key(current))
        )
        return UpdateStatus(
            version=current,
            install_kind=env.kind,
            channel=channel,
            index=redact_url(env.index),
            latest=latest,
            update_available=newer,
            can_update=newer and reason is None,
            reason=reason if not newer or reason else None,
        )

    def install_command(self, version: str) -> list[str]:
        assert self.environment.uv
        python = f"{sys.version_info.major}.{sys.version_info.minor}"
        return [
            self.environment.uv,
            "tool",
            "install",
            "--force",
            "--python",
            python,
            # Ours first, PyPI for everything else.
            "--index",
            self.environment.index,
            f"{PACKAGE}=={version}",
        ]

    async def update(self) -> UpdateResult:
        if self._lock.locked():
            raise HTTPException(status_code=409, detail="An update is already running.")
        async with self._lock:
            status = await self.status()
            if not status.can_update or status.latest is None:
                raise HTTPException(status_code=400, detail=status.reason or "This WebUI is up to date.")
            command = self.install_command(status.latest)
            logger.info("Updating the WebUI from %s to %s", status.version, status.latest)
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=uv_environment()
            )
            try:
                output, _ = await asyncio.wait_for(process.communicate(), timeout=UPDATE_TIMEOUT)
            except TimeoutError:
                process.kill()
                raise HTTPException(status_code=504, detail="The update took too long and was stopped.") from None
            log = output.decode(errors="replace").replace(self.environment.index, redact_url(self.environment.index))
            if process.returncode != 0:
                raise HTTPException(status_code=502, detail=f"uv could not install {status.latest}:\n{log[-2000:]}")
            schedule_restart()
            return UpdateResult(version=status.latest, log=log[-4000:], restarting=True)


def uv_environment() -> dict[str, str]:
    """uv trusts only its own certificate list unless told otherwise; a private
    index (e.g. Forgejo behind a local CA) needs the system store or the bundle in
    SSL_CERT_FILE, which uv honours either way. Both names, for older uv too."""
    return {**os.environ, "UV_SYSTEM_CERTS": "1", "UV_NATIVE_TLS": "1"}


def schedule_restart(delay: float = 1.0) -> None:
    """Start this process again on the newly installed code, once the reply has gone out."""
    asyncio.get_running_loop().call_later(delay, restart)


def restart() -> None:
    logger.info("Restarting the WebUI on the updated package")
    os.execv(sys.executable, [sys.executable, *sys.argv])


def self_update_router(updater: SelfUpdater, auth: Auth) -> APIRouter:
    router = APIRouter(prefix="/webui/api/v1/self", dependencies=[Depends(auth.require)])

    @router.get("", response_model=UpdateStatus)
    async def status() -> UpdateStatus:
        return await updater.status()

    @router.post("/update", response_model=UpdateResult)
    async def update() -> UpdateResult:
        return await updater.update()

    return router
