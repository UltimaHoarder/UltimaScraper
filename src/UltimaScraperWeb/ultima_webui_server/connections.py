"""Backend connections: the default one from the environment, plus stored ones."""

from __future__ import annotations

import json
import re
import secrets
import ssl
import time
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .pinning import pinned_context
from .store import Store, StoredConnection, StoredTunnel
from .vault import Vault

DEFAULT_CONNECTION_ID = "default"
_CONNECTION_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


@dataclass(frozen=True)
class Tunnel:
    """SSH access used to reach the backend; base_url is an address on that host."""

    host: str
    port: int
    user: str
    private_key: str
    host_key: str


@dataclass(frozen=True)
class Connection:
    id: str
    name: str
    base_url: str
    tls_verify: bool
    # Configured by the deployment, so it cannot be edited or removed here.
    managed: bool
    _token: str | None
    _token_file: Path | None = None
    tunnel: Tunnel | None = None
    # A pinned self-signed certificate (PEM): then the only one accepted.
    tls_certificate: str | None = None

    @property
    def verify(self) -> ssl.SSLContext | bool:
        """What an HTTPS client to this backend verifies against."""
        if self.tls_certificate:
            return pinned_context(self.tls_certificate)
        return self.tls_verify

    def token(self) -> str | None:
        """The admin token, read fresh so a backend's first-start token is picked up."""
        if self._token_file is not None:
            try:
                return self._token_file.read_text(encoding="utf-8").strip() or None
            except OSError:
                return self._token
        return self._token


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=1, max_length=500)
    # Omitted on update to keep the stored token.
    token: str | None = Field(default=None, max_length=500)
    tls_verify: bool = True


class ConnectionOut(BaseModel):
    id: str
    name: str
    base_url: str
    tls_verify: bool
    managed: bool
    has_token: bool
    # The SSH host the backend is reached through, when tunnelled.
    ssh_host: str | None = None
    # Whether this backend's native plugins may run code in the WebUI page.
    trust_plugins: bool = False


class PluginTrustIn(BaseModel):
    trusted: bool


class ConnectionTest(BaseModel):
    reachable: bool
    authenticated: bool
    message: str
    latency_ms: float | None = None


class TicketOut(BaseModel):
    ticket: str
    # What the ticket says, and why its address may not work on another WebUI.
    name: str
    base_url: str
    warning: str | None = None


class TicketIn(BaseModel):
    ticket: str


class TicketParseOut(BaseModel):
    name: str
    base_url: str
    token: str | None = None
    tls_verify: bool = True
    cluster_id: str | None = None


class ClusterNameIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class InviteMemberOut(BaseModel):
    name: str
    base_url: str


class InviteExcludedOut(BaseModel):
    name: str
    reason: str


class ClusterInviteOut(BaseModel):
    invite: str
    name: str
    members: list[InviteMemberOut]
    # Members this WebUI cannot share, and why.
    excluded: list[InviteExcludedOut]
    # 2: a one-time code redeemed over pinned HTTPS. 1: the members' admin tokens.
    version: int = 1
    expires_at: str | None = None
    warning: str | None = None


class InvitePreviewMemberOut(BaseModel):
    name: str
    backend_id: str
    base_url: str
    # This WebUI already has a connection to it, so joining leaves it as is.
    already_connected: bool


class InvitePreviewOut(BaseModel):
    # Unknown for a version 2 invite until it is redeemed.
    cluster_id: str | None
    name: str
    members: list[InvitePreviewMemberOut]
    version: int = 1
    # Version 2: the member it is redeemed at, and whether it presented the
    # certificate the invite names.
    entry_url: str | None = None
    fingerprint: str | None = None
    verified: bool | None = None
    error: str | None = None


def normalise_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise HTTPException(status_code=400, detail="Use an http:// or https:// backend address.")
    if parts.query or parts.fragment:
        raise HTTPException(status_code=400, detail="The backend address cannot have a query or fragment.")
    return url


class Connections:
    def __init__(self, settings: Settings, store: Store, vault: Vault) -> None:
        self.settings = settings
        self.store = store
        self.vault = vault

    def _default(self) -> Connection | None:
        if not self.settings.default_backend_url:
            return None
        return Connection(
            id=DEFAULT_CONNECTION_ID,
            name="This server",
            base_url=self.settings.default_backend_url.rstrip("/"),
            tls_verify=True,
            managed=True,
            _token=self.settings.default_backend_token,
            _token_file=self.settings.default_backend_token_file,
        )

    def _from_stored(self, stored: StoredConnection) -> Connection:
        tunnel = stored.tunnel
        return Connection(
            id=stored.id,
            name=stored.name,
            base_url=stored.base_url,
            tls_verify=stored.tls_verify,
            managed=False,
            _token=self.vault.decrypt(stored.token) if stored.token else None,
            tls_certificate=stored.tls_certificate,
            tunnel=Tunnel(
                tunnel.host, tunnel.port, tunnel.user, self.vault.decrypt(tunnel.private_key), tunnel.host_key
            )
            if tunnel
            else None,
        )

    def all(self) -> list[Connection]:
        default = self._default()
        stored = [self._from_stored(item) for item in self.store.list_connections()]
        return ([default] if default else []) + stored

    def get(self, connection_id: str) -> Connection:
        if connection_id == DEFAULT_CONNECTION_ID and (default := self._default()):
            return default
        stored = self.store.get_connection(connection_id)
        if stored is not None:
            return self._from_stored(stored)
        for item in self.all():
            if item.id == connection_id or item.name == connection_id:
                return item
        for conn_id, (ident_str, _) in self.store.identities().items():
            try:
                data = json.loads(ident_str)
                if data.get("backend_id") == connection_id:
                    return self.get(conn_id)
            except Exception:
                continue
        raise HTTPException(status_code=404, detail="No such backend connection.")

    def default(self) -> Connection:
        default = self._default()
        if default is None:
            raise HTTPException(
                status_code=503,
                detail="This WebUI has no default backend. Add a backend connection.",
            )
        return default

    def plugins_trusted(self, connection: Connection) -> bool:
        """Native plugin code runs in the page that holds every connection's
        session, so only backends the user trusts may load it. The deployment's
        own backend is trusted unless the user says otherwise."""
        stored = self.store.get_setting(_trust_key(connection.id))
        if stored is None:
            return connection.managed
        return stored == "1"

    def set_plugin_trust(self, connection_id: str, trusted: bool) -> Connection:
        connection = self.get(connection_id)
        self.store.set_setting(_trust_key(connection.id), "1" if trusted else "0")
        self.store.audit("plugins_trusted" if trusted else "plugins_untrusted", connection.id)
        return connection

    def describe(self, connection: Connection) -> ConnectionOut:
        return ConnectionOut(
            id=connection.id,
            name=connection.name,
            base_url=connection.base_url,
            tls_verify=connection.tls_verify,
            managed=connection.managed,
            has_token=connection.token() is not None,
            ssh_host=f"{connection.tunnel.user}@{connection.tunnel.host}" if connection.tunnel else None,
            trust_plugins=self.plugins_trusted(connection),
        )

    def create(self, data: ConnectionIn) -> Connection:
        connection_id = _slug(data.name)
        while connection_id == DEFAULT_CONNECTION_ID or self.store.get_connection(connection_id):
            connection_id = f"{_slug(data.name)[:50]}-{secrets.token_hex(3)}"
        self.store.save_connection(
            StoredConnection(
                id=connection_id,
                name=data.name.strip(),
                base_url=normalise_base_url(data.base_url),
                token=self.vault.encrypt(data.token.strip()) if data.token and data.token.strip() else None,
                tls_verify=data.tls_verify,
            )
        )
        self.store.audit("connection_added", connection_id)
        return self.get(connection_id)

    def create_installed(
        self, *, name: str, base_url: str, token: str, tunnel: StoredTunnel | None
    ) -> Connection:
        """Register a backend the installer just deployed; tunnel keys arrive unencrypted."""
        connection_id = _slug(name)
        while connection_id == DEFAULT_CONNECTION_ID or self.store.get_connection(connection_id):
            connection_id = f"{_slug(name)[:50]}-{secrets.token_hex(3)}"
        self.store.save_connection(
            StoredConnection(
                id=connection_id,
                name=name,
                base_url=base_url,
                token=self.vault.encrypt(token),
                tls_verify=True,
                tunnel=StoredTunnel(
                    tunnel.host, tunnel.port, tunnel.user, self.vault.encrypt(tunnel.private_key), tunnel.host_key
                )
                if tunnel
                else None,
            )
        )
        self.store.audit("connection_installed", connection_id)
        return self.get(connection_id)

    def create_pinned(self, *, name: str, base_url: str, token: str, certificate: str) -> Connection:
        """A cluster member reached over HTTPS, trusting exactly that certificate."""
        connection_id = _slug(name)
        while connection_id == DEFAULT_CONNECTION_ID or self.store.get_connection(connection_id):
            connection_id = f"{_slug(name)[:50]}-{secrets.token_hex(3)}"
        self.store.save_connection(
            StoredConnection(
                id=connection_id,
                name=name.strip(),
                base_url=normalise_base_url(base_url),
                token=self.vault.encrypt(token),
                tls_verify=True,
                tls_certificate=certificate,
            )
        )
        self.store.audit("connection_added", f"{connection_id} pinned")
        return self.get(connection_id)

    def repin(self, connection_id: str, certificate: str) -> None:
        """A member renewed its certificate (vouched for by the cluster): trust the new one."""
        stored = self.store.get_connection(connection_id)
        if stored is None:
            return
        self.store.save_connection(replace(stored, tls_certificate=certificate))
        self.store.audit("connection_repinned", connection_id)

    def update(self, connection_id: str, data: ConnectionIn) -> Connection:
        current = self._editable(connection_id)
        token = current.token
        if data.token is not None:
            token = self.vault.encrypt(data.token.strip()) if data.token.strip() else None
        self.store.save_connection(
            StoredConnection(
                id=connection_id,
                name=data.name.strip(),
                base_url=normalise_base_url(data.base_url),
                token=token,
                tls_verify=data.tls_verify,
                tunnel=current.tunnel,
                tls_certificate=current.tls_certificate,
            )
        )
        self.store.audit("connection_updated", connection_id)
        return self.get(connection_id)

    def delete(self, connection_id: str) -> None:
        self._editable(connection_id)
        self.store.delete_connection(connection_id)
        # A later connection with the same id starts untrusted.
        self.store.delete_setting(_trust_key(connection_id))
        self.store.delete_identity(connection_id)
        self.store.audit("connection_removed", connection_id)

    def _editable(self, connection_id: str) -> StoredConnection:
        if connection_id == DEFAULT_CONNECTION_ID and self._default():
            raise HTTPException(
                status_code=409,
                detail="This connection is configured by the deployment (USR_WEBUI_DEFAULT_BACKEND_URL).",
            )
        stored = self.store.get_connection(connection_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="No such backend connection.")
        return stored

    async def test(self, connection: Connection) -> ConnectionTest:
        """Reachability via the public health route, then whether the token works."""
        started = time.perf_counter()
        async with httpx.AsyncClient(
            base_url=connection.base_url, verify=connection.verify, timeout=10.0
        ) as client:
            try:
                health = await client.get("/api/v1/admin/health")
            except httpx.HTTPError as exc:
                return ConnectionTest(reachable=False, authenticated=False, message=f"Unreachable: {exc}")
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            if health.status_code >= 500 or health.status_code == 404:
                return ConnectionTest(
                    reachable=False,
                    authenticated=False,
                    message=f"Not an UltimaScraper backend (HTTP {health.status_code}).",
                    latency_ms=latency_ms,
                )
            token = connection.token()
            headers = {"x-usr-admin-token": token} if token else {}
            try:
                identity = await client.get("/api/v1/system/backend", headers=headers)
            except httpx.HTTPError as exc:
                return ConnectionTest(
                    reachable=True, authenticated=False, message=f"Request failed: {exc}", latency_ms=latency_ms
                )
        if identity.status_code in (401, 403):
            return ConnectionTest(
                reachable=True,
                authenticated=False,
                message="Reached the backend, but it refused the admin token.",
                latency_ms=latency_ms,
            )
        return ConnectionTest(
            reachable=True,
            authenticated=identity.is_success,
            message="Connected." if identity.is_success else f"HTTP {identity.status_code}",
            latency_ms=latency_ms,
        )


def _trust_key(connection_id: str) -> str:
    return f"plugin_trust:{connection_id}"


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:63] or "backend"
    return slug if _CONNECTION_ID_RE.fullmatch(slug) else "backend"
