"""Groups backend connections into clusters.

Backends that share a database report the same cluster id from
``/api/v1/system/identity``. Each cluster also lists live members, from any
reachable member's ``/api/v1/system/backends``, that this WebUI has no
connection for yet. Backends too old to report an identity stand alone.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from .connections import Connection, Connections
from .store import Store

_TIMEOUT = httpx.Timeout(5.0)


class Identity(BaseModel):
    backend_id: str
    instance: str = ""
    cluster_id: str | None = None
    api_url: str | None = None
    version: str = ""
    api_version: int = 0
    # SHA-256 of the certificate its HTTPS listener serves, for pinning.
    tls_fingerprint: str | None = None


class MemberOut(BaseModel):
    connection_id: str
    name: str
    reachable: bool
    # The last identity reported; kept while the backend is unreachable.
    identity: Identity | None = None
    seen_at: float | None = None


class SuggestedMember(BaseModel):
    """A live cluster member this WebUI has no connection for."""

    backend_id: str
    hostname: str
    status: str
    last_seen: str
    api_url: str | None = None


class ClusterOut(BaseModel):
    cluster_id: str
    # What this WebUI calls it (see cluster_name).
    name: str = ""
    connection_ids: list[str]
    suggestions: list[SuggestedMember] = []
    # Ids reported by more than one running backend: they share settings and
    # overwrite each other's registration.
    conflicting_backend_ids: list[str] = []


class ClustersOut(BaseModel):
    members: list[MemberOut]
    clusters: list[ClusterOut]
    # The cluster this WebUI opens on.
    main_cluster_id: str | None = None


Resolver = Callable[[str], Awaitable[Connection]]


async def _get(connection: Connection, path: str) -> httpx.Response:
    token = connection.token()
    async with httpx.AsyncClient(
        base_url=connection.base_url, verify=connection.verify, timeout=_TIMEOUT
    ) as client:
        return await client.get(path, headers={"x-usr-admin-token": token} if token else {})


async def _probe(resolve: Resolver, connection: Connection) -> tuple[bool, Identity | None, Connection | None]:
    """Whether the backend answered, the identity it reported, and how it was reached."""
    try:
        reached = await resolve(connection.id)
        response = await _get(reached, "/api/v1/system/identity")
    except (httpx.HTTPError, HTTPException, OSError):
        return False, None, None
    if not response.is_success:
        # 404: a backend from before clusters. 401: a token it refuses.
        return response.status_code < 500, None, None
    try:
        return True, Identity.model_validate(response.json()), reached
    except (ValueError, ValidationError):
        return True, None, None


async def known_identity(store: Store, resolve: Resolver, connection: Connection) -> Identity | None:
    """What the backend says about itself now, or what it said last."""
    _, identity, _ = await _probe(resolve, connection)
    if identity is not None:
        store.save_identity(connection.id, identity.model_dump_json())
        return identity
    raw = store.identities().get(connection.id)
    if raw is None:
        return None
    try:
        return Identity.model_validate(json.loads(raw[0]))
    except (ValueError, ValidationError):
        return None


async def _live_members(reached: Connection) -> list[dict] | None:
    try:
        response = await _get(reached, "/api/v1/system/backends")
        if response.is_success:
            return list(response.json().get("backends") or [])
    except (httpx.HTTPError, ValueError, AttributeError, OSError):
        pass
    return None


def cluster_peers(connections: Connections, store: Store, connection_id: str) -> list[str]:
    """Other connections last seen in the same cluster, by their stored identities."""
    known = store.identities()
    if connection_id not in known:
        return []
    try:
        cluster_id = Identity.model_validate(json.loads(known[connection_id][0])).cluster_id
    except (ValueError, ValidationError):
        return []
    if not cluster_id:
        return []
    existing = {connection.id for connection in connections.all()}
    peers = []
    for other, (raw, _) in sorted(known.items(), key=lambda item: -item[1][1]):
        if other == connection_id or other not in existing:
            continue
        try:
            if Identity.model_validate(json.loads(raw)).cluster_id == cluster_id:
                peers.append(other)
        except (ValueError, ValidationError):
            continue
    return peers


async def describe_clusters(connections: Connections, store: Store, resolve: Resolver) -> ClustersOut:
    every = connections.all()
    probes = await asyncio.gather(*(_probe(resolve, connection) for connection in every))
    stored = store.identities()
    members: list[MemberOut] = []
    reached_by_id: dict[str, Connection] = {}
    for connection, (reachable, identity, reached) in zip(every, probes):
        seen_at: float | None = None
        if identity is not None:
            store.save_identity(connection.id, identity.model_dump_json())
            seen_at = time.time()
            if reached is not None:
                reached_by_id[connection.id] = reached
        elif connection.id in stored:
            raw, seen_at = stored[connection.id]
            try:
                identity = Identity.model_validate(json.loads(raw))
            except (ValueError, ValidationError):
                identity, seen_at = None, None
        members.append(
            MemberOut(
                connection_id=connection.id,
                name=connection.name,
                reachable=reachable,
                identity=identity,
                seen_at=seen_at,
            )
        )

    grouped: dict[str, list[MemberOut]] = {}
    for member in members:
        if member.identity and member.identity.cluster_id:
            grouped.setdefault(member.identity.cluster_id, []).append(member)

    clusters: list[ClusterOut] = []
    for cluster_id, in_cluster in grouped.items():
        known = {member.identity.backend_id for member in in_cluster if member.identity}
        # Fresh identities only: a stored one may predate a restart.
        fresh = [member for member in in_cluster if member.connection_id in reached_by_id]
        instances: dict[str, set[str]] = {}
        for member in fresh:
            assert member.identity is not None
            instances.setdefault(member.identity.backend_id, set()).add(member.identity.instance)
        suggestions: list[SuggestedMember] = []
        for member in fresh:
            live = await _live_members(reached_by_id[member.connection_id])
            if live is None:
                continue
            for entry in live:
                backend_id = str(entry.get("backend_id") or "")
                if not backend_id or backend_id in known or entry.get("cluster_id") != cluster_id:
                    continue
                suggestions.append(
                    SuggestedMember(
                        backend_id=backend_id,
                        hostname=str(entry.get("hostname") or ""),
                        status=str(entry.get("status") or ""),
                        last_seen=str(entry.get("last_seen") or ""),
                        api_url=entry.get("api_url") or None,
                    )
                )
            break
        clusters.append(
            ClusterOut(
                cluster_id=cluster_id,
                name=cluster_name(store, cluster_id),
                connection_ids=[member.connection_id for member in in_cluster],
                suggestions=sorted(suggestions, key=lambda item: item.backend_id),
                conflicting_backend_ids=sorted(
                    backend_id for backend_id, seen in instances.items() if len(seen) > 1
                ),
            )
        )
    return ClustersOut(members=members, clusters=clusters)


# ---- One cluster in detail ---------------------------------------------------

_NAME_KEY = "cluster_name:"
_OVERVIEW_TTL = 10.0


class OverviewBackend(BaseModel):
    """An API server in the cluster."""

    backend_id: str
    # The friendly name from the backend inventory (e.g. "alpha"), else its host.
    name: str
    address: str | None = None
    version: str = ""
    status: str = ""
    last_seen: str = ""
    # This WebUI's connection to it, when it has one.
    connection_id: str | None = None


class OverviewWorker(BaseModel):
    worker_id: str
    status: str
    current_job: str | None = None


class WorkerHost(BaseModel):
    """A machine running workers, whether or not it also serves the API."""

    backend_id: str
    name: str
    status: str = ""
    version: str = ""
    active_workers: int = 0
    max_workers: int = 0
    pending_jobs: int = 0
    workers: list[OverviewWorker] = []


class ClusterOverview(BaseModel):
    cluster_id: str
    name: str
    backends: list[OverviewBackend]
    worker_hosts: list[WorkerHost]
    # Which connection's backend described the cluster; None when none answered.
    answered_by: str | None = None
    error: str | None = None


def cluster_name(store: Store, cluster_id: str) -> str:
    """The name this WebUI gives the cluster; its id's start until one is set."""
    return store.get_setting(f"{_NAME_KEY}{cluster_id}") or f"Cluster {cluster_id[:8]}"


def rename_cluster(store: Store, cluster_id: str, name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Give the cluster a name.")
    store.set_setting(f"{_NAME_KEY}{cluster_id}", cleaned[:80])
    return cleaned[:80]


def cluster_connections(connections: Connections, store: Store, cluster_id: str) -> list[tuple[Connection, Identity]]:
    """This WebUI's connections in the cluster, by their last known identities."""
    known = store.identities()
    found: list[tuple[Connection, Identity]] = []
    for connection in connections.all():
        raw = known.get(connection.id)
        if raw is None:
            continue
        try:
            identity = Identity.model_validate(json.loads(raw[0]))
        except (ValueError, ValidationError):
            continue
        if identity.cluster_id == cluster_id:
            found.append((connection, identity))
    return found


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def build_overview(
    cluster_id: str,
    name: str,
    members: list[tuple[Connection, Identity]],
    live: list[dict] | None,
    answered_by: str | None,
) -> ClusterOverview:
    """The cluster's API servers and worker hosts, from one member's view of it.

    Only API servers are backends: a member this WebUI connects to, or one that
    advertises an address. Every member that runs workers is a worker host.
    """
    connected = {identity.backend_id: connection for connection, identity in members}
    backends: dict[str, OverviewBackend] = {}
    hosts: list[WorkerHost] = []
    for entry in live or []:
        backend_id = str(entry.get("backend_id") or "")
        # One Redis per cluster, so its list is this cluster; older members omit the id.
        if not backend_id or entry.get("cluster_id") not in (cluster_id, None):
            continue
        name_of = str(entry.get("hostname") or backend_id)
        connection = connected.get(backend_id)
        api_url = entry.get("api_url") or None
        if connection is not None or api_url:
            backends[backend_id] = OverviewBackend(
                backend_id=backend_id,
                name=name_of,
                address=api_url or (connection.base_url if connection else None),
                version=str(entry.get("version") or ""),
                status=str(entry.get("status") or ""),
                last_seen=str(entry.get("last_seen") or ""),
                connection_id=connection.id if connection else None,
            )
        workers = [
            OverviewWorker(
                worker_id=str(worker.get("worker_id") or ""),
                status=str(worker.get("status") or ""),
                current_job=worker.get("current_job") or None,
            )
            for worker in entry.get("workers") or []
            if isinstance(worker, dict)
        ]
        max_workers = _int(entry.get("max_workers"))
        if workers or max_workers:
            hosts.append(
                WorkerHost(
                    backend_id=backend_id,
                    name=name_of,
                    status=str(entry.get("status") or ""),
                    version=str(entry.get("version") or ""),
                    active_workers=_int(entry.get("active_workers")),
                    max_workers=max_workers,
                    pending_jobs=_int(entry.get("pending_jobs")),
                    workers=workers,
                )
            )
    # Connected members the cluster did not list are down, or nothing answered.
    for backend_id, connection in connected.items():
        if backend_id not in backends:
            backends[backend_id] = OverviewBackend(
                backend_id=backend_id,
                name=connection.name,
                address=connection.base_url,
                status="unreachable" if live is not None else "unknown",
                connection_id=connection.id,
            )
    return ClusterOverview(
        cluster_id=cluster_id,
        name=name,
        backends=sorted(backends.values(), key=lambda item: item.name.lower()),
        worker_hosts=sorted(hosts, key=lambda item: item.name.lower()),
        answered_by=answered_by,
        error=None if live is not None else "No member of this cluster answered.",
    )


class ClusterOverviews:
    """Cluster details, asked of one reachable member at a time and kept briefly."""

    def __init__(self, connections: Connections, store: Store, resolve: Resolver) -> None:
        self.connections = connections
        self.store = store
        self.resolve = resolve
        self._cache: dict[str, tuple[float, ClusterOverview]] = {}

    def forget(self, cluster_id: str) -> None:
        self._cache.pop(cluster_id, None)

    async def get(self, cluster_id: str) -> ClusterOverview:
        cached = self._cache.get(cluster_id)
        if cached and time.monotonic() - cached[0] < _OVERVIEW_TTL:
            return cached[1].model_copy(update={"name": cluster_name(self.store, cluster_id)})
        members = cluster_connections(self.connections, self.store, cluster_id)
        if not members:
            raise HTTPException(status_code=404, detail="This WebUI has no connection in that cluster.")
        live: list[dict] | None = None
        answered_by: str | None = None
        for connection, _identity in members:
            try:
                reached = await self.resolve(connection.id)
            except HTTPException:
                continue
            live = await _live_members(reached)
            if live is not None:
                answered_by = connection.id
                break
        overview = build_overview(cluster_id, cluster_name(self.store, cluster_id), members, live, answered_by)
        self._cache[cluster_id] = (time.monotonic(), overview)
        return overview
