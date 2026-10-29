"""This WebUI as a member of clusters: invites, joining, and keeping up.

A WebUI joins a cluster by redeeming a one-time invite at one member over
HTTPS, trusting only the certificate whose fingerprint the invite carries. The
member answers with the cluster's members, each with its HTTPS address and
fingerprint, and a client token that every member accepts. The WebUI then
connects to each member, pinning its certificate.

Every SYNC_SECONDS it asks the cluster again: members that appeared are added,
a member whose certificate changed is re-pinned (the fingerprint is vouched for
by a member reached over a pinned connection), the cluster's name is taken
from the cluster, and the WebUI checks in so other WebUIs see it.

Writes do not fail over: each page talks to the member it was opened on.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from .clusters import (
    ClusterOverviews,
    Identity,
    cluster_connections,
    cluster_name,
    rename_cluster,
)
from .connections import Connection, Connections
from .pinning import (
    PinMismatch,
    certificate_fingerprint,
    normalise_fingerprint,
    pinned_certificate,
    pinned_context,
)
from .store import ClusterCredential, Store
from .tickets import create_cluster_join_invite, local_only, parse_cluster_join_invite
from .version import own_version

logger = logging.getLogger(__name__)

SYNC_SECONDS = 60.0
_FIRST_SYNC_SECONDS = 10.0
# A WebUI that could not enrol tries again after this long (e.g. once a backend shares HTTPS).
_ENROL_RETRY_SECONDS = 600.0
_TIMEOUT = httpx.Timeout(10.0)

Resolver = Callable[[str], Awaitable[Connection]]


class ClusterMemberIn(BaseModel):
    backend_id: str
    name: str
    api_url: str | None = None
    tls_fingerprint: str | None = None
    version: str = ""


class ClusterInfoIn(BaseModel):
    cluster_id: str | None
    name: str | None = None
    members: list[ClusterMemberIn] = []


class ClusterClientOut(BaseModel):
    id: str
    name: str
    kind: str
    created_at: str
    last_seen_at: str | None = None
    last_address: str | None = None
    version: str | None = None
    revoked_at: str | None = None
    is_self: bool = False


class JoinedMemberOut(BaseModel):
    name: str
    base_url: str | None = None
    connection_id: str | None = None
    # Why it was not added (already connected, no HTTPS address, ...).
    note: str | None = None


class ClusterJoinOut(BaseModel):
    cluster_id: str
    name: str
    created: list[str]
    skipped: list[str]
    members: list[JoinedMemberOut] = []


class JoinPreviewOut(BaseModel):
    entry_url: str
    fingerprint: str
    # The member answered and presented the certificate the invite names.
    verified: bool
    error: str | None = None


class InviteCreated(BaseModel):
    invite: str
    entry_url: str
    expires_at: str
    # Members another WebUI will be able to reach, and the rest.
    members: list[ClusterMemberIn]


def webui_name() -> str:
    """How this WebUI introduces itself to a cluster."""
    return f"WebUI on {socket.gethostname()}"


def _trusted_channel(connection: Connection) -> bool:
    """Whether a token may travel to this backend: over HTTPS, or within this host."""
    return connection.base_url.startswith("https://") or local_only(connection.base_url)


class ClusterMembership:
    def __init__(
        self, connections: Connections, store: Store, resolve: Resolver, overviews: ClusterOverviews
    ) -> None:
        self.connections = connections
        self.store = store
        self.resolve = resolve
        self.overviews = overviews
        # Clusters this WebUI tried to enrol in since it started, to try once.
        # When this WebUI last tried to enrol in each cluster.
        self._enrol_tried: dict[str, float] = {}

    # ---- Talking to a cluster ----------------------------------------------

    def client_token(self, cluster_id: str) -> str | None:
        credential = self.store.get_cluster_credential(cluster_id)
        return self.connections.vault.decrypt(credential.token) if credential else None

    async def _request(
        self,
        cluster_id: str,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        as_client: bool = False,
    ) -> httpx.Response:
        """Ask the first member that answers. With as_client, send this WebUI's own
        client token (so the cluster knows which client is asking)."""
        client_token = self.client_token(cluster_id) if as_client else None
        if as_client and not client_token:
            raise HTTPException(status_code=409, detail="This WebUI has not joined that cluster with an invite.")
        members = cluster_connections(self.connections, self.store, cluster_id)
        if not members:
            raise HTTPException(status_code=404, detail="This WebUI has no connection in that cluster.")
        last_error = "No member of this cluster answered."
        for connection, _identity in members:
            if client_token and not _trusted_channel(connection):
                continue
            try:
                reached = await self.resolve(connection.id)
                token = client_token or reached.token()
                async with httpx.AsyncClient(
                    base_url=reached.base_url, verify=reached.verify, timeout=_TIMEOUT
                ) as client:
                    response = await client.request(
                        method, path, json=body, headers={"x-usr-admin-token": token} if token else {}
                    )
            except (httpx.HTTPError, HTTPException, OSError) as exc:
                last_error = f"{connection.name}: {exc}"
                continue
            if response.status_code >= 500:
                last_error = f"{connection.name} answered {response.status_code}."
                continue
            return response
        credential = self.store.get_cluster_credential(cluster_id) if client_token else None
        if credential and credential.entry_certificate:
            # No connection is safe for the client token: the member it enrolled at, pinned.
            try:
                async with httpx.AsyncClient(
                    base_url=credential.entry_url,
                    verify=pinned_context(credential.entry_certificate),
                    timeout=_TIMEOUT,
                ) as client:
                    response = await client.request(
                        method, path, json=body, headers={"x-usr-admin-token": client_token}
                    )
                if response.status_code < 500:
                    return response
                last_error = f"{credential.entry_url} answered {response.status_code}."
            except httpx.HTTPError as exc:
                last_error = f"{credential.entry_url}: {exc}"
        raise HTTPException(status_code=502, detail=last_error)

    async def read_from_one(self, cluster_id: str, paths: list[str]) -> tuple[str | None, dict[str, Any]]:
        """GET each path from the first member that answers the first one.

        Returns which connection answered, and each path's JSON (None where it
        failed). Everything comes from one member, so it is one view of the
        cluster.
        """
        for connection, _identity in cluster_connections(self.connections, self.store, cluster_id):
            try:
                reached = await self.resolve(connection.id)
            except HTTPException:
                continue
            token = reached.token()
            results: dict[str, Any] = {}
            try:
                async with httpx.AsyncClient(
                    base_url=reached.base_url, verify=reached.verify, timeout=_TIMEOUT
                ) as client:
                    for index, path in enumerate(paths):
                        try:
                            response = await client.get(
                                path, headers={"x-usr-admin-token": token} if token else {}
                            )
                            results[path] = response.json() if response.is_success else None
                        except (httpx.HTTPError, ValueError):
                            if index == 0:
                                raise
                            results[path] = None
                        if index == 0 and results[path] is None:
                            break
            except (httpx.HTTPError, OSError, ValueError):
                continue
            if results.get(paths[0]) is not None:
                return connection.id, results
        return None, {}

    async def cluster_info(self, cluster_id: str) -> ClusterInfoIn | None:
        """The cluster as its members describe it; None from backends without cluster routes."""
        response = await self._request(cluster_id, "GET", "/api/v1/cluster")
        if response.status_code == 404:
            return None
        _raise_for(response)
        return ClusterInfoIn.model_validate(response.json())

    # ---- Invites -----------------------------------------------------------

    async def create_invite(self, cluster_id: str) -> InviteCreated | None:
        """A one-time invite naming an HTTPS member; None when no member serves
        HTTPS, or the backends predate invites."""
        info = await self.cluster_info(cluster_id)
        if info is None:
            return None
        entry = next((member for member in info.members if member.api_url and member.tls_fingerprint), None)
        if entry is None:
            return None
        response = await self._request(cluster_id, "POST", "/api/v1/cluster/invites", body={})
        if response.status_code == 404:
            return None
        _raise_for(response)
        created = response.json()
        assert entry.api_url and entry.tls_fingerprint
        return InviteCreated(
            invite=create_cluster_join_invite(
                code=created["code"], entry_url=entry.api_url, fingerprint=entry.tls_fingerprint
            ),
            entry_url=entry.api_url,
            expires_at=str(created["expires_at"]),
            members=info.members,
        )

    async def preview(self, invite: str) -> JoinPreviewOut:
        """Whether the invite's member answers with the certificate it names; the
        code is not used."""
        parsed = _parse(invite)
        try:
            await pinned_certificate(parsed["entry_url"], parsed["fingerprint"])
        except PinMismatch as exc:
            return JoinPreviewOut(**_preview_fields(parsed), verified=False, error=str(exc))
        except (TimeoutError, OSError, ValueError) as exc:
            return JoinPreviewOut(
                **_preview_fields(parsed), verified=False, error=f"{parsed['entry_url']} did not answer: {exc}"
            )
        return JoinPreviewOut(**_preview_fields(parsed), verified=True)

    # ---- Joining -----------------------------------------------------------

    async def join(self, invite: str) -> ClusterJoinOut:
        parsed = _parse(invite)
        entry_url = parsed["entry_url"]
        try:
            entry_certificate = await pinned_certificate(entry_url, parsed["fingerprint"])
        except PinMismatch as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (TimeoutError, OSError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"{entry_url} did not answer: {exc}") from exc
        try:
            async with httpx.AsyncClient(
                base_url=entry_url, verify=pinned_context(entry_certificate), timeout=_TIMEOUT
            ) as client:
                response = await client.post(
                    "/api/v1/cluster/join",
                    json={"code": parsed["code"], "name": webui_name(), "kind": "webui", "version": own_version()},
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"{entry_url} did not answer: {exc}") from exc
        if response.status_code in (400, 403, 404):
            raise HTTPException(status_code=400, detail=_detail(response))
        _raise_for(response)
        joined = response.json()
        info = ClusterInfoIn.model_validate(joined)
        if not info.cluster_id:
            raise HTTPException(status_code=502, detail="The member did not say which cluster it is in.")
        cluster_id = info.cluster_id
        token = str(joined["token"])
        self.store.save_cluster_credential(
            ClusterCredential(
                cluster_id=cluster_id,
                name=info.name or "",
                client_id=str(joined["client_id"]),
                token=self.connections.vault.encrypt(token),
                entry_url=entry_url,
                created_at=time.time(),
                entry_certificate=entry_certificate,
            )
        )
        known = {entry_url: entry_certificate}
        results = [await self._add_member(cluster_id, member, token, known) for member in info.members]
        if info.name:
            rename_cluster(self.store, cluster_id, info.name)
        self.overviews.forget(cluster_id)
        created = [item.connection_id for item in results if item.connection_id and not item.note]
        self.store.audit("cluster_joined", f"{cluster_id} {len(created)} added (invite)")
        return ClusterJoinOut(
            cluster_id=cluster_id,
            name=cluster_name(self.store, cluster_id),
            created=created,
            skipped=[item.name for item in results if item.note],
            members=results,
        )

    def _connection_for(self, member: ClusterMemberIn) -> Connection | None:
        known = self.store.identities()
        for connection in self.connections.all():
            if member.api_url and connection.base_url.rstrip("/") == member.api_url.rstrip("/"):
                return connection
            raw = known.get(connection.id)
            if raw and json.loads(raw[0]).get("backend_id") == member.backend_id:
                return connection
        return None

    async def _add_member(
        self, cluster_id: str, member: ClusterMemberIn, token: str, certificates: dict[str, str]
    ) -> JoinedMemberOut:
        """Connect to a member the cluster reported, pinning the certificate it reported."""
        existing = self._connection_for(member)
        if existing is not None:
            return JoinedMemberOut(
                name=member.name, base_url=existing.base_url, connection_id=existing.id, note="Already connected."
            )
        if not member.api_url or not member.tls_fingerprint:
            return JoinedMemberOut(name=member.name, note="It serves no HTTPS address for other machines.")
        try:
            certificate = certificates.get(member.api_url) or await pinned_certificate(
                member.api_url, member.tls_fingerprint
            )
        except (TimeoutError, PinMismatch, OSError, ValueError) as exc:
            return JoinedMemberOut(name=member.name, base_url=member.api_url, note=f"Not added: {exc}")
        connection = self.connections.create_pinned(
            name=member.name, base_url=member.api_url, token=token, certificate=certificate
        )
        self.store.save_identity(
            connection.id,
            Identity(
                backend_id=member.backend_id,
                cluster_id=cluster_id,
                api_url=member.api_url,
                version=member.version,
                tls_fingerprint=member.tls_fingerprint,
            ).model_dump_json(),
        )
        return JoinedMemberOut(name=member.name, base_url=member.api_url, connection_id=connection.id)

    # ---- Keeping up --------------------------------------------------------

    async def sync(self, cluster_id: str) -> None:
        """Add new members, re-pin renewed certificates, take the cluster's name, check in."""
        info = await self.cluster_info(cluster_id)
        if info is None or info.cluster_id != cluster_id:
            return
        if info.name and info.name != cluster_name(self.store, cluster_id):
            rename_cluster(self.store, cluster_id, info.name)
            self.overviews.forget(cluster_id)
        token = self.client_token(cluster_id)
        if token is None:
            token = await self._enrol(cluster_id)
        if token is None:
            return
        for member in info.members:
            connection = self._connection_for(member)
            if connection is None:
                added = await self._add_member(cluster_id, member, token, {})
                if added.connection_id:
                    logger.info("Added cluster member %s at %s", member.name, member.api_url)
                    self.overviews.forget(cluster_id)
            elif connection.tls_certificate and member.tls_fingerprint:
                await self._repin(connection, member)
        response = await self._request(
            cluster_id,
            "POST",
            "/api/v1/cluster/clients/heartbeat",
            body={"name": webui_name(), "version": own_version()},
            as_client=True,
        )
        if response.status_code == 401:
            logger.warning("This WebUI's membership of cluster %s was revoked", cluster_id)

    async def _enrol(self, cluster_id: str) -> str | None:
        """Become a listed client of a cluster this WebUI reaches with an admin token.

        It invites itself and redeems the invite where the reply, a token, is
        safe: at the same member when that is over HTTPS or loopback, otherwise
        at a member the cluster reports serving HTTPS, pinned to the
        fingerprint the cluster reports for it. That fingerprint arrives over
        the plain link, like the admin token itself already travels: the
        client token it protects can do no more than that admin token.
        """
        tried = self._enrol_tried.get(cluster_id)
        if tried is not None and time.monotonic() - tried < _ENROL_RETRY_SECONDS:
            return None
        self._enrol_tried[cluster_id] = time.monotonic()
        for connection, _identity in cluster_connections(self.connections, self.store, cluster_id):
            admin_token = connection.token()
            if not admin_token or admin_token.startswith("usrc_") or not _token_safe(connection.base_url):
                continue
            try:
                reached = await self.resolve(connection.id)
                async with httpx.AsyncClient(
                    base_url=reached.base_url, verify=reached.verify, timeout=_TIMEOUT
                ) as client:
                    invite = await client.post(
                        "/api/v1/cluster/invites", json={}, headers={"x-usr-admin-token": admin_token}
                    )
                    if invite.status_code != 201:
                        continue
                    joined = await client.post(
                        "/api/v1/cluster/join",
                        json={
                            "code": invite.json()["code"],
                            "name": webui_name(),
                            "kind": "webui",
                            "version": own_version(),
                        },
                    )
            except (httpx.HTTPError, HTTPException, OSError, KeyError, ValueError):
                logger.debug("Could not enrol in cluster %s through %s", cluster_id, connection.name, exc_info=True)
                continue
            if not joined.is_success:
                continue
            reply = joined.json()
            token = str(reply["token"])
            self.store.save_cluster_credential(
                ClusterCredential(
                    cluster_id=cluster_id,
                    name=str(reply.get("name") or ""),
                    client_id=str(reply["client_id"]),
                    token=self.connections.vault.encrypt(token),
                    entry_url=connection.base_url,
                    created_at=time.time(),
                )
            )
            logger.info("Listed this WebUI in cluster %s, through %s", cluster_id, connection.name)
            return token
        return await self._enrol_over_https(cluster_id)

    async def _enrol_over_https(self, cluster_id: str) -> str | None:
        """Enrol through the HTTPS member the cluster reports, asked over a plain admin connection."""
        for connection, _identity in cluster_connections(self.connections, self.store, cluster_id):
            admin_token = connection.token()
            if not admin_token or admin_token.startswith("usrc_"):
                continue
            headers = {"x-usr-admin-token": admin_token}
            try:
                reached = await self.resolve(connection.id)
                async with httpx.AsyncClient(
                    base_url=reached.base_url, verify=reached.verify, timeout=_TIMEOUT
                ) as client:
                    described = await client.get("/api/v1/cluster", headers=headers)
                    if not described.is_success:
                        continue
                    info = ClusterInfoIn.model_validate(described.json())
                    entry = next(
                        (member for member in info.members if member.api_url and member.tls_fingerprint), None
                    )
                    if entry is None or entry.api_url is None or entry.tls_fingerprint is None:
                        continue
                    certificate = await pinned_certificate(entry.api_url, entry.tls_fingerprint)
                    invite = await client.post("/api/v1/cluster/invites", json={}, headers=headers)
                    if invite.status_code != 201:
                        continue
                async with httpx.AsyncClient(
                    base_url=entry.api_url, verify=pinned_context(certificate), timeout=_TIMEOUT
                ) as pinned:
                    joined = await pinned.post(
                        "/api/v1/cluster/join",
                        json={
                            "code": invite.json()["code"],
                            "name": webui_name(),
                            "kind": "webui",
                            "version": own_version(),
                        },
                    )
            except (TimeoutError, httpx.HTTPError, HTTPException, OSError, KeyError, ValueError, ValidationError):
                logger.debug("Could not enrol in cluster %s over HTTPS", cluster_id, exc_info=True)
                continue
            if not joined.is_success:
                continue
            reply = joined.json()
            token = str(reply["token"])
            self.store.save_cluster_credential(
                ClusterCredential(
                    cluster_id=cluster_id,
                    name=str(reply.get("name") or ""),
                    client_id=str(reply["client_id"]),
                    token=self.connections.vault.encrypt(token),
                    entry_url=entry.api_url,
                    created_at=time.time(),
                    entry_certificate=certificate,
                )
            )
            logger.info("Listed this WebUI in cluster %s, through %s over HTTPS", cluster_id, entry.api_url)
            return token
        return None

    async def _repin(self, connection: Connection, member: ClusterMemberIn) -> None:
        assert connection.tls_certificate and member.tls_fingerprint and member.api_url
        if certificate_fingerprint(connection.tls_certificate) == normalise_fingerprint(member.tls_fingerprint):
            return
        try:
            certificate = await pinned_certificate(connection.base_url, member.tls_fingerprint)
        except (TimeoutError, PinMismatch, OSError, ValueError):
            logger.warning("%s reports a new certificate, but did not present it", connection.name, exc_info=True)
            return
        self.connections.repin(connection.id, certificate)
        logger.info("Re-pinned %s: its certificate was renewed", connection.name)

    def known_clusters(self) -> list[str]:
        clusters: set[str] = {credential.cluster_id for credential in self.store.cluster_credentials()}
        for raw, _seen in self.store.identities().values():
            try:
                cluster_id = Identity.model_validate(json.loads(raw)).cluster_id
            except (ValueError, ValidationError):
                continue
            if cluster_id:
                clusters.add(cluster_id)
        return sorted(clusters)

    async def sync_all(self) -> None:
        for cluster_id in self.known_clusters():
            try:
                await self.sync(cluster_id)
            except HTTPException as exc:
                logger.debug("Cluster %s sync: %s", cluster_id, exc.detail)
            except Exception:
                logger.warning("Cluster %s sync failed", cluster_id, exc_info=True)

    async def run(self) -> None:
        await asyncio.sleep(_FIRST_SYNC_SECONDS)
        while True:
            await self.sync_all()
            await asyncio.sleep(SYNC_SECONDS)

    # ---- Name and clients --------------------------------------------------

    async def push_name(self, cluster_id: str, name: str) -> None:
        """Give the cluster the name for every WebUI; this WebUI's own name stays when it cannot."""
        try:
            response = await self._request(cluster_id, "PUT", "/api/v1/cluster/name", body={"name": name})
        except HTTPException as exc:
            logger.info("Cluster %s keeps its name: %s", cluster_id, exc.detail)
            return
        if not response.is_success and response.status_code != 404:
            logger.info("Cluster %s keeps its name: %s", cluster_id, _detail(response))

    async def clients(self, cluster_id: str) -> list[ClusterClientOut]:
        as_client = self.client_token(cluster_id) is not None
        response = await self._request(cluster_id, "GET", "/api/v1/cluster/clients", as_client=as_client)
        if response.status_code == 404:
            return []
        _raise_for(response)
        return [ClusterClientOut.model_validate(item) for item in response.json()]

    async def revoke(self, cluster_id: str, client_id: str) -> None:
        response = await self._request(cluster_id, "DELETE", f"/api/v1/cluster/clients/{client_id}")
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail=_detail(response))
        _raise_for(response)
        credential = self.store.get_cluster_credential(cluster_id)
        if credential and credential.client_id == client_id:
            self.store.delete_cluster_credential(cluster_id)
        self.store.audit("cluster_client_revoked", f"{cluster_id} {client_id}")


def _token_safe(base_url: str) -> bool:
    """Whether a member answers a join there: over HTTPS, or on this machine."""
    from urllib.parse import urlsplit

    if base_url.startswith("https://"):
        return True
    host = (urlsplit(base_url).hostname or "").lower()
    return host in {"localhost", "::1"} or host.startswith("127.")


def _parse(invite: str) -> dict[str, str]:
    try:
        return parse_cluster_join_invite(invite)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _preview_fields(parsed: dict[str, str]) -> dict[str, str]:
    return {"entry_url": parsed["entry_url"], "fingerprint": normalise_fingerprint(parsed["fingerprint"])}


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return str(detail or f"The member answered {response.status_code}.")


def _raise_for(response: httpx.Response) -> None:
    if not response.is_success:
        raise HTTPException(status_code=502, detail=_detail(response))
