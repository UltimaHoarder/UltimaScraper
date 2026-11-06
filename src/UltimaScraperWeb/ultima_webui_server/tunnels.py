"""SSH tunnels to backends whose API is only published on their own loopback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

import asyncssh

from .connections import Connection
from .installer.targets import reachable_host


class TunnelUnavailable(ConnectionError):
    pass


@dataclass
class _Tunnel:
    ssh: asyncssh.SSHClientConnection
    listener: asyncssh.SSHListener
    local_port: int


class TunnelManager:
    def __init__(self) -> None:
        # Keyed by connection and event loop: a tunnel's sockets belong to its loop.
        self._tunnels: dict[tuple[str, int], _Tunnel] = {}
        self._locks: dict[tuple[str, int], asyncio.Lock] = {}

    async def resolve(self, connection: Connection) -> Connection:
        """The connection, with base_url pointing at its tunnel when it has one."""
        if connection.tunnel is None:
            return connection
        remote = urlsplit(connection.base_url)
        local_port = await self._ensure(connection, remote.hostname or "127.0.0.1", remote.port or 21121)
        return replace(connection, base_url=f"{remote.scheme}://127.0.0.1:{local_port}")

    async def _ensure(self, connection: Connection, remote_host: str, remote_port: int) -> int:
        key = (connection.id, id(asyncio.get_running_loop()))
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            current = self._tunnels.get(key)
            if current is not None and not current.ssh.is_closed():
                return current.local_port
            tunnel = connection.tunnel
            assert tunnel is not None
            try:
                ssh = await asyncssh.connect(
                    reachable_host(tunnel.host),
                    tunnel.port,
                    username=tunnel.user,
                    client_keys=[asyncssh.import_private_key(tunnel.private_key)],
                    known_hosts=([asyncssh.import_public_key(tunnel.host_key)], [], []),
                    agent_path=None,
                    password=None,
                    login_timeout=15,
                    keepalive_interval=30,
                )
                listener = await ssh.forward_local_port("127.0.0.1", 0, remote_host, remote_port)
            except (OSError, asyncssh.Error) as exc:
                raise TunnelUnavailable(f"Could not open the SSH tunnel to {tunnel.host}: {exc}") from exc
            self._tunnels[key] = _Tunnel(ssh, listener, listener.get_port())
            return listener.get_port()

    async def close(self, connection_id: str | None = None) -> None:
        """Close one connection's tunnels (after it is removed), or all of them."""
        for key in [key for key in self._tunnels if connection_id in (None, key[0])]:
            tunnel = self._tunnels.pop(key)
            tunnel.listener.close()
            tunnel.ssh.close()
