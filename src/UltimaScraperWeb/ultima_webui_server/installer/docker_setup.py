"""Installs Docker Engine and the Compose plugin from the distribution's packages.

Distribution packages are used rather than piping a download script into a
root shell. Hosts this does not know are told what to install themselves.
"""

from __future__ import annotations

from .targets import OutputCallback, Target

# On apt systems prefer the Compose v2 package; Ubuntu's plain docker-compose
# is the retired Python v1, which cannot run these Compose files.
_APT = (
    "export DEBIAN_FRONTEND=noninteractive; apt-get update -q && "
    "compose=docker-compose-v2; "
    "apt-cache show docker-compose-v2 >/dev/null 2>&1 || compose=docker-compose; "
    'apt-get install -y -q docker.io "$compose"'
)
_INSTALL = {
    "debian": _APT,
    "ubuntu": _APT,
    "fedora": "dnf install -y moby-engine docker-compose",
    "alpine": "apk add --no-cache docker docker-cli-compose",
    "arch": "pacman -Sy --noconfirm --needed docker docker-compose",
}
_SERVICE_MANAGER = (
    "if [ -d /run/systemd/system ] && command -v systemctl >/dev/null; then echo systemd; "
    "elif command -v rc-service >/dev/null; then echo openrc; "
    # Alpine's docker package ships an OpenRC script there; without OpenRC
    # there is no `service` to run it.
    "elif [ -x /etc/init.d/docker ] && command -v service >/dev/null; then echo init.d; "
    "else echo none; fi"
)
_START = {
    "systemd": "systemctl enable --now docker",
    "openrc": "rc-update add docker default && rc-service docker start",
    "init.d": "service docker start",
    # No service manager (a container, a minimal system): run the daemon itself.
    "none": "nohup dockerd >/var/log/dockerd.log 2>&1 </dev/null &",
}


class DockerSetupFailed(RuntimeError):
    pass


async def distribution(target: Target) -> str | None:
    """The supported family this host belongs to, from ID and ID_LIKE in os-release."""
    result = await target.run('. /etc/os-release 2>/dev/null && printf "%s %s" "$ID" "$ID_LIKE"', check=False)
    for name in result.stdout.split():
        if name in _INSTALL:
            return name
    return None


async def install_docker(target: Target, on_output: OutputCallback) -> None:
    """Install and start Docker Engine with Compose; needs sudo on the target."""
    family = await distribution(target)
    if family is None:
        raise DockerSetupFailed(
            "This installer knows Debian, Ubuntu, Fedora, Alpine and Arch. Install Docker Engine with the "
            "Compose plugin on this host yourself (https://docs.docker.com/engine/install/), then run the "
            "install again."
        )
    await on_output(f"Installing Docker from the {family} packages")
    await target.run(_INSTALL[family], sudo=True, on_output=on_output)
    manager = (await target.run(_SERVICE_MANAGER)).stdout.strip()
    await target.run(_START.get(manager, _START["none"]), sudo=True, on_output=on_output)
    if manager not in ("systemd", "openrc", "init.d"):
        await on_output(
            "This host has no service manager, so dockerd was started directly. "
            "It will not start again by itself after a reboot."
        )
    # Wait for the daemon socket before the install goes on.
    await target.run(
        "for _ in $(seq 30); do docker info >/dev/null 2>&1 && exit 0; sleep 1; done; docker info",
        sudo=True,
        on_output=on_output,
    )
    compose = await target.run("docker compose version --short", sudo=True, check=False)
    if compose.exit_status != 0:
        raise DockerSetupFailed(
            "Docker is installed, but its packages lack the Compose plugin. Install docker-compose-plugin "
            "from Docker's repository, then run the install again."
        )
