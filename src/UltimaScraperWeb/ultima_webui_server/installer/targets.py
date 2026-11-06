"""Where install commands run: this machine, or a host reached over SSH."""

from __future__ import annotations

import asyncio
import shlex
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import asyncssh

OutputCallback = Callable[[str], Awaitable[None]]
Stdin = bytes | AsyncIterator[bytes] | None


class CommandFailed(RuntimeError):
    def __init__(self, command: str, result: CommandResult) -> None:
        detail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        super().__init__(f"{command!r} exited with {result.exit_status}: {' / '.join(detail)}")
        self.result = result


@dataclass(frozen=True)
class CommandResult:
    exit_status: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class HostKey:
    algorithm: str
    # SHA256:... as `ssh-keygen -lf` prints it, for the user to compare.
    fingerprint: str
    # The OpenSSH public key line, pinned once the user accepts it.
    openssh: str


# Ask for the key type people compare first: ssh-keygen -lf on ssh_host_ed25519_key.pub.
_HOST_KEY_PREFERENCE = [
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "rsa-sha2-512",
    "rsa-sha2-256",
    "ssh-rsa",
]


DOCKER_HOST_NAME = "host.docker.internal"


def _default_gateway(route_table: str = "/proc/net/route") -> str | None:
    try:
        lines = Path(route_table).read_text(encoding="ascii").splitlines()[1:]
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        # The default route; the gateway is a little-endian hex IPv4 address.
        if len(fields) > 2 and fields[1] == "00000000" and fields[2] != "00000000":
            return socket.inet_ntoa(bytes.fromhex(fields[2])[::-1])
    return None


def reachable_host(host: str) -> str:
    """The host to connect to for ``host``.

    Compose maps host.docker.internal to the machine a container runs on. A
    container started without that (a NAS app, a plain docker run) has no such
    name, so it reaches the machine through its default gateway instead.
    """
    if host != DOCKER_HOST_NAME or not Path("/.dockerenv").exists():
        return host
    try:
        socket.getaddrinfo(host, None)
        return host
    except OSError:
        return _default_gateway() or host


async def scan_host_key(host: str, port: int) -> HostKey:
    key = await asyncio.wait_for(
        asyncssh.get_server_host_key(reachable_host(host), port, server_host_key_algs=_HOST_KEY_PREFERENCE),
        timeout=15,
    )
    if key is None:
        raise ConnectionError(f"{host}:{port} did not present an SSH host key.")
    return HostKey(
        algorithm=key.get_algorithm(),
        fingerprint=key.get_fingerprint("sha256"),
        openssh=key.export_public_key().decode("ascii").strip(),
    )


class Target(Protocol):
    description: str

    async def run(
        self,
        command: str,
        *,
        sudo: bool = False,
        stdin: Stdin = None,
        check: bool = True,
        on_output: OutputCallback | None = None,
    ) -> CommandResult: ...

    async def close(self) -> None: ...


def _sudo_wrapped(command: str, sudo: bool, sudo_password: str | None) -> tuple[str, bytes]:
    """The command to run, and bytes to send to stdin ahead of any input."""
    if not sudo:
        return command, b""
    if sudo_password is None:
        # -n fails instead of waiting for a password nobody will type.
        return f"sudo -n sh -c {shlex.quote(command)}", b""
    # -S reads the password from the first stdin line; -p '' prints no prompt.
    return f"sudo -S -p '' sh -c {shlex.quote(command)}", sudo_password.encode() + b"\n"


async def passwordless_sudo(target: Target) -> bool:
    """True when the target user can run commands via sudo without a password."""
    result = await target.run("sudo -n true", check=False)
    return result.exit_status == 0


async def _feed(writer: Callable[[bytes], Awaitable[None]], prefix: bytes, stdin: Stdin) -> None:
    if prefix:
        await writer(prefix)
    if isinstance(stdin, bytes):
        await writer(stdin)
    elif stdin is not None:
        async for chunk in stdin:
            await writer(chunk)


async def _pump(stream: asyncio.StreamReader | asyncssh.SSHReader, sink: list[str], on_output: OutputCallback | None) -> None:
    while True:
        line = await stream.readline()
        if not line:
            return
        text = (line.decode("utf-8", "replace") if isinstance(line, bytes) else line).rstrip("\n")
        sink.append(text)
        if on_output is not None:
            await on_output(text)


class LocalTarget:
    """This machine, for a WebUI server that runs directly on it (not in Docker)."""

    description = "this machine"

    def __init__(self, sudo_password: str | None = None) -> None:
        self._sudo_password = sudo_password

    async def run(
        self,
        command: str,
        *,
        sudo: bool = False,
        stdin: Stdin = None,
        check: bool = True,
        on_output: OutputCallback | None = None,
    ) -> CommandResult:
        wrapped, prefix = _sudo_wrapped(command, sudo, self._sudo_password)
        process = await asyncio.create_subprocess_shell(
            wrapped,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdin and process.stdout and process.stderr

        async def write(data: bytes) -> None:
            process.stdin.write(data)  # type: ignore[union-attr]
            await process.stdin.drain()  # type: ignore[union-attr]

        async def feed() -> None:
            try:
                await _feed(write, prefix, stdin)
            finally:
                process.stdin.close()  # type: ignore[union-attr]

        out: list[str] = []
        err: list[str] = []
        await asyncio.gather(feed(), _pump(process.stdout, out, on_output), _pump(process.stderr, err, on_output))
        result = CommandResult(await process.wait(), "\n".join(out), "\n".join(err))
        if check and result.exit_status != 0:
            raise CommandFailed(command, result)
        return result

    async def close(self) -> None:
        return None


class SSHTarget:
    """A host reached over SSH, with its host key pinned in advance."""

    def __init__(self, connection: asyncssh.SSHClientConnection, description: str, sudo_password: str | None) -> None:
        self._connection = connection
        self.description = description
        self._sudo_password = sudo_password

    @classmethod
    async def connect(
        cls,
        *,
        host: str,
        port: int,
        username: str,
        host_key: str,
        password: str | None = None,
        private_key: str | None = None,
        sudo_password: str | None = None,
    ) -> SSHTarget:
        """Connect only if the host presents exactly the key the user accepted."""
        connection = await asyncssh.connect(
            reachable_host(host),
            port,
            username=username,
            password=password,
            client_keys=[asyncssh.import_private_key(private_key)] if private_key else None,
            known_hosts=([asyncssh.import_public_key(host_key)], [], []),
            agent_path=None,
            login_timeout=30,
            keepalive_interval=30,
        )
        return cls(connection, f"{username}@{host}", sudo_password)

    async def run(
        self,
        command: str,
        *,
        sudo: bool = False,
        stdin: Stdin = None,
        check: bool = True,
        on_output: OutputCallback | None = None,
    ) -> CommandResult:
        wrapped, prefix = _sudo_wrapped(command, sudo, self._sudo_password)
        process = await self._connection.create_process(wrapped, encoding=None)

        async def write(data: bytes) -> None:
            process.stdin.write(data)
            await process.stdin.drain()

        async def feed() -> None:
            try:
                await _feed(write, prefix, stdin)
            finally:
                process.stdin.write_eof()

        out: list[str] = []
        err: list[str] = []
        await asyncio.gather(feed(), _pump(process.stdout, out, on_output), _pump(process.stderr, err, on_output))
        completed = await process.wait()
        # None means the command was killed by a signal.
        exit_status = completed.exit_status if completed.exit_status is not None else 255
        result = CommandResult(exit_status, "\n".join(out), "\n".join(err))
        if check and result.exit_status != 0:
            raise CommandFailed(command, result)
        return result

    async def close(self) -> None:
        self._connection.close()
        await self._connection.wait_closed()
