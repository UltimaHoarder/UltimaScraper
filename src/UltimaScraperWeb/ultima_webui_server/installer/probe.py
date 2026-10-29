"""What the install target is: CPU architecture, OS, Docker, free ports and space."""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from typing import Any

from .images import LocalRelease, local_releases
from .targets import Target, passwordless_sudo

# `uname -m` to the Docker platform architecture the release images are built for.
ARCHITECTURES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
LOW_MEMORY_MB = 2048
LOW_DISK_MB = 5120


class UnsupportedHost(RuntimeError):
    pass


@dataclass(frozen=True)
class HostFacts:
    architecture: str
    os_name: str
    user: str
    home: str
    docker_version: str | None
    compose_version: str | None
    # Docker works only through sudo for this user (not in the docker group).
    docker_needs_sudo: bool
    memory_mb: int | None
    home_free_mb: int | None
    listening_ports: frozenset[int] = field(default_factory=frozenset)
    hostname: str = ""
    sudo_mode: str = "none"  # "none" | "passwordless" | "password"
    existing_projects: tuple[str, ...] = ()
    existing_install: dict[str, Any] | None = None
    services: dict[str, dict[str, Any]] = field(default_factory=dict)
    local_images: tuple[LocalRelease, ...] = ()
    warnings: tuple[str, ...] = ()

    def free_port(self, preferred: int) -> int:
        """The preferred port, or the next one not already listening."""
        port = preferred
        while port in self.listening_ports:
            port += 1
        return port


def _int(value: str) -> int | None:
    try:
        return int(value.strip())
    except ValueError:
        return None


def _resolve_dir(home: str, install_dir: str) -> str:
    if install_dir == "~":
        return home
    if install_dir.startswith("~/"):
        return f"{home}/{install_dir[2:]}"
    return install_dir


def needs_sudo_for(facts: HostFacts) -> list[str]:
    reasons: list[str] = []
    if not facts.docker_version or not facts.compose_version:
        reasons.append("install Docker")
    elif facts.docker_needs_sudo:
        reasons.append("docker group")
    return reasons


def recommend_components(facts: HostFacts) -> dict[str, str]:
    return {
        "backend": "install",
        "worker": "install",
        "postgres": "existing" if facts.services.get("postgres", {}).get("detected") else "install",
        "redis": "existing" if facts.services.get("redis", {}).get("detected") else "install",
        "webui": "reuse",
    }


_SERVICE_HOST_RE = re.compile(r"[A-Za-z0-9._:-]{1,253}")
SERVICE_CHECK_TIMEOUT = 3


async def check_service(target: Target, *, host: str, port: int) -> tuple[bool, str]:
    """Run a TCP reachability check from the target host to host:port."""
    cleaned_host = host.strip().removeprefix("[").removesuffix("]")
    if not _SERVICE_HOST_RE.fullmatch(cleaned_host) or not 0 < port <= 65535:
        return False, "Provide a valid host name or IP address and port."
    # The host and port reach the probe as arguments, never as shell text.
    args = f"{shlex.quote(cleaned_host)} {int(port)}"
    seconds = SERVICE_CHECK_TIMEOUT
    cmd = (
        "if command -v bash >/dev/null 2>&1; then "
        f"timeout {seconds} bash -c 'exec 3<>\"/dev/tcp/$1/$2\"' probe {args}; "
        f"else nc -z -w {seconds} {args}; fi"
    )
    result = await target.run(cmd, check=False)
    if result.exit_status == 0:
        return True, f"Connected to {cleaned_host}:{int(port)} from {target.description}."
    if result.exit_status == 124:
        return False, f"No answer from {cleaned_host}:{int(port)} within {seconds}s, checked from {target.description}."
    detail = (result.stderr or result.stdout).strip()
    suffix = f" ({detail})" if detail else ""
    return False, f"Could not reach {cleaned_host}:{int(port)} from {target.description}{suffix}."


_PUBLISHED_RE = re.compile(r"(?:[\d.]+|\[[0-9a-f:]*\]|::):(\d+)->(\d+)/tcp")
_SERVICE_IMAGES = {"postgres": ("postgres", "pgvector", "postgis"), "redis": ("redis", "valkey")}
_SERVICE_PORTS = {"postgres": 5432, "redis": 6379}


def _detect_services(listening: frozenset[int], ps_lines: list[str]) -> dict[str, dict[str, Any]]:
    """PostgreSQL and Redis this host's containers can reach through host.docker.internal.

    A container counts only when it publishes its port on the host; one that
    keeps it on its own network (another stack's bundled database) is listed as
    unreachable instead, so it is never preselected.
    """
    services: dict[str, dict[str, Any]] = {}
    for kind, default_port in _SERVICE_PORTS.items():
        published: tuple[str, int] | None = None
        unpublished: list[str] = []
        for line in ps_lines:
            image, _, rest = line.partition("\t")
            name, _, ports = rest.partition("\t")
            if not any(token in image.lower() for token in _SERVICE_IMAGES[kind]):
                continue
            host_ports = [
                int(host_port)
                for host_port, container_port in _PUBLISHED_RE.findall(ports)
                if int(container_port) == default_port
            ]
            if host_ports and published is None:
                published = (name or image, host_ports[0])
            elif not host_ports:
                unpublished.append(name or image)
        if published is not None:
            services[kind] = {
                "detected": True,
                "host": "localhost",
                "port": published[1],
                "listening": True,
                "container": published[0],
            }
        elif default_port in listening:
            services[kind] = {
                "detected": True,
                "host": "localhost",
                "port": default_port,
                "listening": True,
                "container": None,
            }
        if unpublished:
            services.setdefault(kind, {"detected": False, "listening": False})["unreachable_containers"] = unpublished
    return services


async def probe(
    target: Target,
    *,
    sudo_available: bool,
    install_dir: str = "~/ultimascraper",
) -> HostFacts:
    machine = (await target.run("uname -m")).stdout.strip()
    architecture = ARCHITECTURES.get(machine)
    if architecture is None:
        raise UnsupportedHost(f"Release images exist for x86_64 and arm64; this host is {machine}.")

    os_name = (
        await target.run('. /etc/os-release 2>/dev/null && printf "%s" "$PRETTY_NAME"', check=False)
    ).stdout.strip() or "unknown"
    user = (await target.run("id -un")).stdout.strip()
    home = (await target.run('printf "%s" "$HOME"')).stdout.strip()
    hostname_res = await target.run("hostname 2>/dev/null || uname -n", check=False)
    hostname = hostname_res.stdout.strip() or "localhost"

    docker_needs_sudo = False
    docker = await target.run("docker version --format '{{.Server.Version}}'", check=False)
    permission_denied = docker.exit_status != 0 and "permission denied" in docker.stderr.lower()

    has_passwordless_sudo = False
    if docker.exit_status != 0:
        has_passwordless_sudo = await passwordless_sudo(target)

    can_sudo = sudo_available or has_passwordless_sudo
    if permission_denied and can_sudo:
        docker = await target.run("docker version --format '{{.Server.Version}}'", sudo=True, check=False)
        docker_needs_sudo = docker.exit_status == 0
    elif permission_denied:
        # User is not in the docker group and sudo needs a password.
        docker_needs_sudo = True
        cli = await target.run("docker --version", check=False)
        if cli.exit_status == 0 and cli.stdout.strip():
            m = re.search(r"Docker version\s+([^\s,]+)", cli.stdout)
            docker_version = m.group(1) if m else cli.stdout.strip()
        else:
            docker_version = None
    if not (permission_denied and not can_sudo):
        docker_version = docker.stdout.strip() if docker.exit_status == 0 else None

    compose_version = None
    if docker_version:
        compose = await target.run(
            "docker compose version --short",
            sudo=docker_needs_sudo and can_sudo,
            check=False,
        )
        compose_version = compose.stdout.strip() if compose.exit_status == 0 else None

    if docker_version and compose_version and not docker_needs_sudo:
        sudo_mode = "none"
    elif has_passwordless_sudo:
        sudo_mode = "passwordless"
    else:
        sudo_mode = "password"

    memory = await target.run("awk '/^MemTotal:/ {print int($2 / 1024)}' /proc/meminfo", check=False)
    space = await target.run('df -Pm "$HOME" | awk \'NR == 2 {print $4}\'', check=False)
    ports = await target.run(
        "(ss -ltnH 2>/dev/null || netstat -ltn 2>/dev/null) | awk '{print $4}'", check=False
    )
    listening = frozenset(
        int(match.group(1)) for line in ports.stdout.splitlines() if (match := re.search(r":(\d+)$", line.strip()))
    )

    existing_projects: tuple[str, ...] = ()
    ps_lines: list[str] = []
    if docker_version and (not docker_needs_sudo or can_sudo):
        compose_ls = await target.run("docker compose ls --format json", sudo=docker_needs_sudo, check=False)
        if compose_ls.exit_status == 0 and compose_ls.stdout.strip():
            try:
                parsed_ls = json.loads(compose_ls.stdout)
            except json.JSONDecodeError:
                parsed_ls = []
            if isinstance(parsed_ls, list):
                existing_projects = tuple(
                    item["Name"]
                    for item in parsed_ls
                    if isinstance(item, dict)
                    and isinstance(item.get("Name"), str)
                    and item["Name"].startswith("usr-")
                )
        docker_ps = await target.run(
            "docker ps --format '{{.Image}}\t{{.Names}}\t{{.Ports}}'",
            sudo=docker_needs_sudo,
            check=False,
        )
        if docker_ps.exit_status == 0 and docker_ps.stdout.strip():
            ps_lines = [line.strip() for line in docker_ps.stdout.splitlines() if line.strip()]

    existing_install: dict[str, Any] | None = None
    resolved_dir = _resolve_dir(home, install_dir)
    state_res = await target.run(
        f"cat {shlex.quote(resolved_dir + '/.usr-install.json')} 2>/dev/null",
        check=False,
    )
    if state_res.exit_status == 0 and state_res.stdout.strip():
        try:
            parsed_state = json.loads(state_res.stdout)
            if isinstance(parsed_state, dict) and "project" in parsed_state and "version" in parsed_state:
                existing_install = {**parsed_state, "install_dir": resolved_dir}
        except json.JSONDecodeError:
            existing_install = None

    services = _detect_services(listening, ps_lines)

    memory_mb = _int(memory.stdout)
    home_free_mb = _int(space.stdout)
    warnings: list[str] = []
    if memory_mb is not None and memory_mb < LOW_MEMORY_MB:
        warnings.append(f"Low memory: {memory_mb} MB detected (at least {LOW_MEMORY_MB} MB recommended).")
    if home_free_mb is not None and home_free_mb < LOW_DISK_MB:
        warnings.append(f"Low disk space: {home_free_mb} MB free in {home} (at least {LOW_DISK_MB} MB recommended).")

    local_imgs = tuple(await local_releases())

    return HostFacts(
        architecture=architecture,
        os_name=os_name,
        user=user,
        home=home,
        docker_version=docker_version,
        compose_version=compose_version,
        docker_needs_sudo=docker_needs_sudo,
        memory_mb=memory_mb,
        home_free_mb=home_free_mb,
        listening_ports=listening,
        hostname=hostname,
        sudo_mode=sudo_mode,
        existing_projects=existing_projects,
        existing_install=existing_install,
        services=services,
        local_images=local_imgs,
        warnings=tuple(warnings),
    )

