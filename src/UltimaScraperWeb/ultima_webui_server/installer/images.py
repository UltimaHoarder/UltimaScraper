"""Getting the release images onto the target.

Images are either pulled by the target from a registry, or copied from this
machine's Docker (`docker save` streamed into the target's `docker load`) when
the target cannot reach the registry or nothing is published yet.
"""

from __future__ import annotations

import asyncio
import shutil
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass

from .targets import OutputCallback, Target

IMAGE_NAMES = ("backend", "worker", "webui")
_LOCAL_PREFIX = "ultimascraper-"
_CHUNK = 1 << 20
_PROGRESS_EVERY = 100 * _CHUNK


class ImagesUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalRelease:
    """Release images this machine's Docker has, for one version and architecture."""

    version: str
    architecture: str
    # Which of backend / worker / webui exist for this version.
    names: tuple[str, ...]


def docker_cli_available() -> bool:
    return shutil.which("docker") is not None


async def _docker(*args: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await process.communicate()
    return process.returncode or 0, out.decode(), err.decode()


async def local_releases() -> list[LocalRelease]:
    """Every version of the release images this machine's Docker holds."""
    if not docker_cli_available():
        return []
    status, out, _ = await _docker(
        "image", "ls", "--format", "{{.Repository}}:{{.Tag}}", "--filter", f"reference={_LOCAL_PREFIX}*"
    )
    if status != 0:
        return []
    found: dict[tuple[str, str], set[str]] = defaultdict(set)
    for reference in sorted(set(out.split())):
        repository, _, version = reference.rpartition(":")
        name = repository.removeprefix(_LOCAL_PREFIX)
        if name not in IMAGE_NAMES or version == "<none>":
            continue
        status, architecture, _ = await _docker("image", "inspect", "--format", "{{.Architecture}}", reference)
        if status == 0:
            found[(version, architecture.strip())].add(name)
    return [
        LocalRelease(version, architecture, tuple(name for name in IMAGE_NAMES if name in names))
        for (version, architecture), names in sorted(found.items())
    ]


async def require_images_on_target(
    target: Target, references: list[str], *, docker_sudo: bool, architecture: str
) -> None:
    """Check images the host already has (built or loaded there) before using them."""
    missing = []
    for reference in references:
        found = await target.run(
            f"docker image inspect --format '{{{{.Architecture}}}}' {reference}", sudo=docker_sudo, check=False
        )
        if found.exit_status != 0:
            missing.append(reference)
        elif found.stdout.strip() != architecture:
            missing.append(f"{reference} ({found.stdout.strip()}, not {architecture})")
    if missing:
        raise ImagesUnavailable(f"The host does not have {', '.join(missing)}.")


async def copy_images(
    target: Target,
    names: list[str],
    version: str,
    *,
    docker_sudo: bool,
    on_output: OutputCallback,
) -> None:
    """Stream the named local images into the target's Docker."""
    references = [f"{_LOCAL_PREFIX}{name}:{version}" for name in names]
    process = await asyncio.create_subprocess_exec(
        "docker", "save", *references, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    assert process.stdout and process.stderr

    async def chunks() -> AsyncIterator[bytes]:
        sent = 0
        next_report = _PROGRESS_EVERY
        while chunk := await process.stdout.read(_CHUNK):  # type: ignore[union-attr]
            yield chunk
            sent += len(chunk)
            if sent >= next_report:
                await on_output(f"Copied {sent // _CHUNK} MB of images")
                next_report += _PROGRESS_EVERY

    await target.run("docker load", sudo=docker_sudo, stdin=chunks(), on_output=on_output)
    if await process.wait() != 0:
        raise ImagesUnavailable((await process.stderr.read()).decode().strip() or "docker save failed")
