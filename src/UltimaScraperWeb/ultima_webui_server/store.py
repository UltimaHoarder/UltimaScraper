"""SQLite storage for sign-in, sessions, connections, deployments and their operations."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    ip_address TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT '',
    last_seen REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS connections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    token TEXT,
    tls_verify INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at REAL NOT NULL,
    event TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS installs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    target TEXT NOT NULL,
    state TEXT NOT NULL,
    connection_id TEXT,
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS deployments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    target TEXT NOT NULL,
    details TEXT NOT NULL,
    connection_id TEXT,
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS identities (
    connection_id TEXT PRIMARY KEY,
    identity TEXT NOT NULL,
    seen_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS cluster_credentials (
    cluster_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    client_id TEXT NOT NULL,
    token TEXT NOT NULL,
    entry_url TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS install_events (
    install_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    at REAL NOT NULL,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    PRIMARY KEY (install_id, seq)
);
"""

# Columns added after the first release, applied to existing databases.
_ADDED_COLUMNS = {
    "installs": {"operation": "TEXT NOT NULL DEFAULT 'install'", "deployment_id": "TEXT"},
    "sessions": {
        "ip_address": "TEXT NOT NULL DEFAULT ''",
        "user_agent": "TEXT NOT NULL DEFAULT ''",
        "last_seen": "REAL NOT NULL DEFAULT 0",
    },
    "cluster_credentials": {"entry_certificate": "TEXT"},
}
_CONNECTION_COLUMNS = {
    "ssh_host": "TEXT",
    "ssh_port": "INTEGER",
    "ssh_user": "TEXT",
    "ssh_key": "TEXT",
    "ssh_host_key": "TEXT",
    # The pinned self-signed certificate (PEM), for a backend reached over HTTPS.
    "tls_certificate": "TEXT",
}


@dataclass(frozen=True)
class StoredTunnel:
    """Reach the backend through SSH: base_url is then an address on that host."""

    host: str
    port: int
    user: str
    # Encrypted with the vault.
    private_key: str
    # The OpenSSH host key the user accepted at install time.
    host_key: str


@dataclass(frozen=True)
class StoredSession:
    id: str
    token_hash: str
    created_at: float
    expires_at: float
    ip_address: str
    user_agent: str
    last_seen: float


@dataclass(frozen=True)
class StoredConnection:
    id: str
    name: str
    base_url: str
    # Encrypted with the vault; None when the backend needs no token.
    token: str | None
    tls_verify: bool
    tunnel: StoredTunnel | None = None
    # A pinned self-signed certificate (PEM); then the only one accepted.
    tls_certificate: str | None = None


@dataclass(frozen=True)
class ClusterCredential:
    """This WebUI's own membership of a cluster, from redeeming an invite."""

    cluster_id: str
    name: str
    client_id: str
    # The client token, encrypted with the vault; every member accepts it.
    token: str
    # The member the invite named.
    entry_url: str
    created_at: float
    # That member's certificate (PEM) when it was reached over pinned HTTPS:
    # the way to it when no connection of this WebUI is safe for the token.
    entry_certificate: str | None = None


@dataclass(frozen=True)
class InstallRecord:
    """One run: an install, or a repair, upgrade or uninstall of a deployment."""

    id: str
    name: str
    target: str
    # running, succeeded or failed.
    state: str
    connection_id: str | None
    created_at: float
    finished_at: float | None
    operation: str = "install"
    deployment_id: str | None = None


@dataclass(frozen=True)
class DeploymentRecord:
    """Something the installer put on a host, kept so it can be managed later."""

    id: str
    name: str
    target: str
    # Non-secret facts: where it is, what runs, which version. Never credentials.
    details: dict
    connection_id: str | None
    # active or removed.
    state: str
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class InstallEvent:
    seq: int
    at: float
    # step, output, error or done.
    kind: str
    message: str


_CONNECTION_SELECT = (
    "SELECT id, name, base_url, token, tls_verify, ssh_host, ssh_port, ssh_user, ssh_key, ssh_host_key, "
    "tls_certificate FROM connections"
)


def _connection(row: tuple) -> StoredConnection:
    tunnel = StoredTunnel(row[5], row[6], row[7], row[8], row[9]) if row[5] else None
    return StoredConnection(row[0], row[1], row[2], row[3], bool(row[4]), tunnel, row[10])


def _deployment(row: tuple) -> DeploymentRecord:
    return DeploymentRecord(row[0], row[1], row[2], json.loads(row[3]), row[4], row[5], row[6], row[7])


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(_SCHEMA)
        for table, columns in {"connections": _CONNECTION_COLUMNS, **_ADDED_COLUMNS}.items():
            existing = {row[1] for row in self._connection.execute(f"PRAGMA table_info({table})")}
            for column, kind in columns.items():
                if column not in existing:
                    self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        # An install cannot still be running after a restart.
        self._connection.execute(
            "UPDATE installs SET state = 'failed', finished_at = ? WHERE state = 'running'", (time.time(),)
        )
        self._lock = threading.Lock()
        path.chmod(0o600)

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            yield self._connection.cursor()

    def close(self) -> None:
        self._connection.close()

    def get_setting(self, key: str) -> str | None:
        with self._cursor() as cursor:
            row = cursor.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def delete_setting(self, key: str) -> None:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM settings WHERE key = ?", (key,))

    def set_setting_once(self, key: str, value: str) -> bool:
        """Store a value only if none exists; False when one already did."""
        with self._cursor() as cursor:
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
            return cursor.rowcount == 1

    def add_session(
        self,
        token_hash: str,
        lifetime_seconds: float,
        ip_address: str = "",
        user_agent: str = "",
    ) -> None:
        now = time.time()
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            cursor.execute(
                "INSERT INTO sessions (token_hash, created_at, expires_at, ip_address, user_agent, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (token_hash, now, now + lifetime_seconds, ip_address, user_agent, now),
            )

    def touch_session(
        self,
        token_hash: str,
        ip_address: str = "",
        user_agent: str = "",
        min_interval: float = 30.0,
    ) -> None:
        now = time.time()
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE sessions SET "
                "last_seen = ?, "
                "ip_address = CASE WHEN ? != '' THEN ? ELSE ip_address END, "
                "user_agent = CASE WHEN ? != '' THEN ? ELSE user_agent END "
                "WHERE token_hash = ? AND (last_seen < ? OR ip_address = '' OR user_agent = '')",
                (now, ip_address, ip_address, user_agent, user_agent, token_hash, now - min_interval),
            )

    def list_sessions(self) -> list[StoredSession]:
        now = time.time()
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT token_hash, created_at, expires_at, ip_address, user_agent, last_seen "
                "FROM sessions WHERE expires_at > ? ORDER BY last_seen DESC, created_at DESC",
                (now,),
            ).fetchall()
        return [
            StoredSession(
                id=row[0][:16],
                token_hash=row[0],
                created_at=row[1],
                expires_at=row[2],
                ip_address=row[3] or "",
                user_agent=row[4] or "",
                last_seen=row[5] or row[1],
            )
            for row in rows
        ]

    def session_valid(self, token_hash: str) -> bool:
        with self._cursor() as cursor:
            row = cursor.execute(
                "SELECT 1 FROM sessions WHERE token_hash = ? AND expires_at > ?",
                (token_hash, time.time()),
            ).fetchone()
        return row is not None

    def delete_session(self, token_hash: str) -> None:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_session_by_id(self, session_id: str) -> bool:
        with self._cursor() as cursor:
            # An exact prefix match: LIKE would treat % and _ in the id as wildcards.
            cursor.execute("DELETE FROM sessions WHERE substr(token_hash, 1, 16) = ?", (session_id,))
            return cursor.rowcount > 0

    def delete_all_sessions(self) -> None:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM sessions")

    def list_connections(self) -> list[StoredConnection]:
        with self._cursor() as cursor:
            rows = cursor.execute(f"{_CONNECTION_SELECT} ORDER BY created_at").fetchall()
        return [_connection(row) for row in rows]

    def get_connection(self, connection_id: str) -> StoredConnection | None:
        with self._cursor() as cursor:
            row = cursor.execute(f"{_CONNECTION_SELECT} WHERE id = ?", (connection_id,)).fetchone()
        return _connection(row) if row else None

    def save_connection(self, connection: StoredConnection) -> None:
        tunnel = connection.tunnel
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO connections (id, name, base_url, token, tls_verify, created_at, "
                "ssh_host, ssh_port, ssh_user, ssh_key, ssh_host_key, tls_certificate) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "name = excluded.name, base_url = excluded.base_url, token = excluded.token, "
                "tls_verify = excluded.tls_verify, ssh_host = excluded.ssh_host, "
                "ssh_port = excluded.ssh_port, ssh_user = excluded.ssh_user, "
                "ssh_key = excluded.ssh_key, ssh_host_key = excluded.ssh_host_key, "
                "tls_certificate = excluded.tls_certificate",
                (
                    connection.id,
                    connection.name,
                    connection.base_url,
                    connection.token,
                    int(connection.tls_verify),
                    time.time(),
                    tunnel.host if tunnel else None,
                    tunnel.port if tunnel else None,
                    tunnel.user if tunnel else None,
                    tunnel.private_key if tunnel else None,
                    tunnel.host_key if tunnel else None,
                    connection.tls_certificate,
                ),
            )

    def delete_connection(self, connection_id: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
            return cursor.rowcount == 1

    def save_cluster_credential(self, credential: ClusterCredential) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO cluster_credentials "
                "(cluster_id, name, client_id, token, entry_url, created_at, entry_certificate) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(cluster_id) DO UPDATE SET name = excluded.name, "
                "client_id = excluded.client_id, token = excluded.token, entry_url = excluded.entry_url, "
                "entry_certificate = excluded.entry_certificate",
                (
                    credential.cluster_id,
                    credential.name,
                    credential.client_id,
                    credential.token,
                    credential.entry_url,
                    credential.created_at,
                    credential.entry_certificate,
                ),
            )

    def cluster_credentials(self) -> list[ClusterCredential]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT cluster_id, name, client_id, token, entry_url, created_at, entry_certificate "
                "FROM cluster_credentials"
            ).fetchall()
        return [ClusterCredential(*row) for row in rows]

    def get_cluster_credential(self, cluster_id: str) -> ClusterCredential | None:
        return next((item for item in self.cluster_credentials() if item.cluster_id == cluster_id), None)

    def delete_cluster_credential(self, cluster_id: str) -> None:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM cluster_credentials WHERE cluster_id = ?", (cluster_id,))

    def save_identity(self, connection_id: str, identity: str) -> None:
        """The last identity a backend reported, kept for when it is unreachable."""
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO identities (connection_id, identity, seen_at) VALUES (?, ?, ?) "
                "ON CONFLICT(connection_id) DO UPDATE SET identity = excluded.identity, seen_at = excluded.seen_at",
                (connection_id, identity, time.time()),
            )

    def identities(self) -> dict[str, tuple[str, float]]:
        with self._cursor() as cursor:
            rows = cursor.execute("SELECT connection_id, identity, seen_at FROM identities").fetchall()
        return {row[0]: (row[1], row[2]) for row in rows}

    def delete_identity(self, connection_id: str) -> None:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM identities WHERE connection_id = ?", (connection_id,))

    def audit(self, event: str, detail: str = "") -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO audit (at, event, detail) VALUES (?, ?, ?)", (time.time(), event, detail)
            )

    def create_install(
        self,
        install_id: str,
        name: str,
        target: str,
        *,
        operation: str = "install",
        deployment_id: str | None = None,
    ) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO installs (id, name, target, state, created_at, operation, deployment_id) "
                "VALUES (?, ?, ?, 'running', ?, ?, ?)",
                (install_id, name, target, time.time(), operation, deployment_id),
            )

    def finish_install(self, install_id: str, state: str, connection_id: str | None) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE installs SET state = ?, connection_id = ?, finished_at = ? WHERE id = ?",
                (state, connection_id, time.time(), install_id),
            )

    def get_install(self, install_id: str) -> InstallRecord | None:
        with self._cursor() as cursor:
            row = cursor.execute(
                "SELECT id, name, target, state, connection_id, created_at, finished_at, operation, deployment_id "
                "FROM installs WHERE id = ?",
                (install_id,),
            ).fetchone()
        return InstallRecord(*row) if row else None

    def save_deployment(self, deployment: DeploymentRecord) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO deployments (id, name, target, details, connection_id, state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET name = excluded.name, "
                "target = excluded.target, details = excluded.details, connection_id = excluded.connection_id, "
                "state = excluded.state, updated_at = excluded.updated_at",
                (
                    deployment.id,
                    deployment.name,
                    deployment.target,
                    json.dumps(deployment.details),
                    deployment.connection_id,
                    deployment.state,
                    deployment.created_at,
                    time.time(),
                ),
            )

    def list_deployments(self) -> list[DeploymentRecord]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT id, name, target, details, connection_id, state, created_at, updated_at "
                "FROM deployments WHERE state = 'active' ORDER BY created_at"
            ).fetchall()
        return [_deployment(row) for row in rows]

    def get_deployment(self, deployment_id: str) -> DeploymentRecord | None:
        with self._cursor() as cursor:
            row = cursor.execute(
                "SELECT id, name, target, details, connection_id, state, created_at, updated_at "
                "FROM deployments WHERE id = ?",
                (deployment_id,),
            ).fetchone()
        return _deployment(row) if row else None

    def add_install_event(self, install_id: str, kind: str, message: str) -> None:
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO install_events (install_id, seq, at, kind, message) VALUES (?, "
                "(SELECT COALESCE(MAX(seq), 0) + 1 FROM install_events WHERE install_id = ?), ?, ?, ?)",
                (install_id, install_id, time.time(), kind, message),
            )

    def install_events(self, install_id: str, after: int = 0) -> list[InstallEvent]:
        with self._cursor() as cursor:
            rows = cursor.execute(
                "SELECT seq, at, kind, message FROM install_events WHERE install_id = ? AND seq > ? ORDER BY seq",
                (install_id, after),
            ).fetchall()
        return [InstallEvent(*row) for row in rows]
