"""A cluster as machines: hosts, and the nodes (services) each one runs.

A node has one role: backend (an API server), workers, webui (a client of the
cluster), postgres or redis. Nodes are grouped into hosts by their network
address, from what the cluster reports:

- backends and workers: the backend presence, with the address each reports;
- WebUIs: the cluster's clients, at the address a backend saw them connect from;
- PostgreSQL and Redis: the addresses in the cluster's settings;
- this WebUI's deployments: the components its installer put on each host,
  shown even before (or without) them reporting.

An address that only means something to the backend that reported it
(loopback, a Compose service name, a Docker network address nobody else has)
is that backend's own host.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from .store import DeploymentRecord, Store

Role = Literal["backend", "workers", "webui", "postgres", "redis"]
State = Literal["healthy", "warning", "offline", "unknown"]

_ROLE_ORDER: dict[str, int] = {"backend": 0, "workers": 1, "webui": 2, "postgres": 3, "redis": 4}
_STATE_RANK: dict[str, int] = {"offline": 3, "warning": 2, "healthy": 1, "unknown": 0}
_NAME_KEY = "host_name:"
# A container's own hostname: its id's start.
_CONTAINER_ID = re.compile(r"[0-9a-f]{12}")
# Backends and WebUIs report every minute or so.
_STALE_SECONDS = 180
# A WebUI gone this long is left out (it is back once it checks in); revoke it to remove it for good.
WEBUI_GONE_SECONDS = 3600


class NodeOut(BaseModel):
    role: Role
    name: str
    state: State
    version: str | None = None
    # A one-line summary, e.g. "3/4 workers busy".
    detail: str | None = None
    last_seen: str | None = None
    backend_id: str | None = None
    client_id: str | None = None
    # This WebUI's connection to it (backends), or this WebUI itself (webui).
    connection_id: str | None = None
    is_self: bool = False
    # Put there by this WebUI's installer, but not reporting.
    installed_only: bool = False


class HostOut(BaseModel):
    # The address, or an id when it has none; names are kept by it.
    key: str
    name: str
    address: str | None = None
    roles: list[Role]
    state: State
    nodes: list[NodeOut]
    deployment_id: str | None = None


class ClusterHostsOut(BaseModel):
    cluster_id: str
    name: str
    hosts: list[HostOut]
    # Which connection's backend described the cluster.
    answered_by: str | None = None
    error: str | None = None


def host_name(store: Store, key: str) -> str | None:
    return store.get_setting(f"{_NAME_KEY}{key}")


def rename_host(store: Store, key: str, name: str) -> str:
    cleaned = name.strip()[:80]
    if cleaned:
        store.set_setting(f"{_NAME_KEY}{key}", cleaned)
    else:
        store.delete_setting(f"{_NAME_KEY}{key}")
    return cleaned


def _host_of(value: str | None) -> str | None:
    """The host part of "host", "host:port" or "[v6]:port"."""
    if not value:
        return None
    raw = value.strip()
    if raw.startswith("["):
        return raw[1 : raw.index("]")] if "]" in raw else raw.strip("[]")
    if raw.count(":") == 1:
        raw = raw.split(":", 1)[0]
    return raw.lower() or None


def _local_to_reporter(host: str) -> bool:
    """Whether an address only means something on the machine that reported it."""
    if host in {"localhost", "host.docker.internal"} or "." not in host and ":" not in host:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _docker_network(host: str) -> bool:
    """Docker's default address pools (172.17.0.0/16 and up, within 172.16.0.0/12)."""
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network("172.16.0.0/12")
    except ValueError:
        return False


def _age(last_seen: str | None, now: datetime) -> float | None:
    if not last_seen:
        return None
    try:
        seen = datetime.fromisoformat(last_seen)
    except ValueError:
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    return (now - seen).total_seconds()


def _presence_state(status: str, last_seen: str | None, now: datetime) -> State:
    if status.lower() in {"offline", "stopped", "unreachable"}:
        return "offline"
    age = _age(last_seen, now)
    if age is not None and age > _STALE_SECONDS:
        return "offline"
    return "warning" if status.lower() in {"degraded", "warning"} else "healthy"


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _deployment_address(record: DeploymentRecord, this_machine: str | None) -> str | None:
    return (record.details.get("host") if record.details.get("kind") == "ssh" else this_machine) or None


def _ran_by(record: DeploymentRecord, backend_id: str) -> bool:
    """Whether a backend id is the one this deployment's installer gave it."""
    recorded = record.details.get("backend_id")
    if recorded:
        return recorded == backend_id
    # Before ids were recorded: the installer names them <project name>-<6 hex>.
    slug = str(record.details.get("project") or "").removeprefix("usr-")
    return bool(slug) and re.fullmatch(rf"{re.escape(slug)}-[0-9a-f]{{6}}", backend_id) is not None


class _Host:
    def __init__(self, key: str, address: str | None) -> None:
        self.key = key
        self.address = address
        self.nodes: list[NodeOut] = []
        self.names: list[str] = []
        self.deployment: DeploymentRecord | None = None


def build_hosts(
    *,
    store: Store,
    cluster_id: str,
    cluster_name: str,
    backends: list[dict[str, Any]] | None,
    reporter_backend_id: str | None,
    clients: list[dict[str, Any]],
    databases: list[dict[str, Any]],
    redis_address: str | None,
    connections_by_backend: dict[str, str],
    deployments: Iterable[DeploymentRecord],
    this_machine: str | None,
    answered_by: str | None,
    now: datetime | None = None,
) -> ClusterHostsOut:
    now = now or datetime.now(UTC)
    hosts: dict[str, _Host] = {}
    live = [entry for entry in backends or [] if entry.get("cluster_id") in (cluster_id, None)]
    deployments = list(deployments)
    # A backend that reports no address (older ones) is where the deployment that runs it is.
    live = [
        entry
        if entry.get("address")
        else {
            **entry,
            "address": next(
                (
                    _deployment_address(record, this_machine)
                    for record in deployments
                    if _ran_by(record, str(entry.get("backend_id") or ""))
                ),
                None,
            ),
        }
        for entry in live
    ]
    reporter = next((entry for entry in live if entry.get("backend_id") == reporter_backend_id), None)
    reporter_key = _host_of(reporter.get("address")) if reporter else None
    if reporter and not reporter_key:
        reporter_key = f"backend:{reporter['backend_id']}"
    known_addresses = {_host_of(entry.get("address")) for entry in live} - {None}

    def host(address: str | None, fallback_key: str, *, docker_alias: bool = False) -> _Host:
        resolved = _host_of(address)
        if resolved and (
            _local_to_reporter(resolved)
            or (docker_alias and resolved not in known_addresses and _docker_network(resolved))
        ):
            # Means the reporting backend's own machine.
            resolved = None
            key = reporter_key or fallback_key
        else:
            key = resolved or fallback_key
        if key not in hosts:
            hosts[key] = _Host(key, resolved if key == resolved else None)
        return hosts[key]

    for entry in live:
        backend_id = str(entry.get("backend_id") or "")
        if not backend_id:
            continue
        target = host(entry.get("address"), f"backend:{backend_id}")
        hostname = str(entry.get("hostname") or "")
        if hostname and not _CONTAINER_ID.fullmatch(hostname):
            target.names.append(hostname)
        state = _presence_state(str(entry.get("status") or ""), entry.get("last_seen"), now)
        version = str(entry.get("version") or "") or None
        connection_id = connections_by_backend.get(backend_id)
        if entry.get("api_url") or connection_id or backend_id == reporter_backend_id:
            target.nodes.append(
                NodeOut(
                    role="backend",
                    name=backend_id,
                    state=state,
                    version=version,
                    detail=entry.get("api_url") or None,
                    last_seen=entry.get("last_seen") or None,
                    backend_id=backend_id,
                    connection_id=connection_id,
                )
            )
        max_workers = _int(entry.get("max_workers"))
        workers = [worker for worker in entry.get("workers") or [] if isinstance(worker, dict)]
        if max_workers or workers:
            active = _int(entry.get("active_workers"))
            target.nodes.append(
                NodeOut(
                    role="workers",
                    name=backend_id,
                    state=state,
                    version=version,
                    detail=f"{active}/{max_workers or len(workers)} busy · {_int(entry.get('pending_jobs'))} pending",
                    last_seen=entry.get("last_seen") or None,
                    backend_id=backend_id,
                    connection_id=connection_id,
                )
            )

    for client in clients:
        if client.get("revoked_at"):
            continue
        age = _age(client.get("last_seen_at"), now)
        if age is None or age > WEBUI_GONE_SECONDS:
            continue
        target = host(client.get("last_address"), f"webui:{client['id']}", docker_alias=True)
        target.nodes.append(
            NodeOut(
                role="webui",
                name=str(client.get("name") or "WebUI"),
                state="healthy" if age is not None and age <= _STALE_SECONDS else "offline",
                version=client.get("version") or None,
                detail=client.get("last_address") or None,
                last_seen=client.get("last_seen_at") or None,
                client_id=str(client["id"]),
                is_self=bool(client.get("is_self")),
            )
        )

    seen_databases: set[str] = set()
    for database in databases:
        address = str(database.get("host") or "")
        port = database.get("port")
        label = f"{address}:{port}" if port else address
        if not address or label in seen_databases:
            continue
        seen_databases.add(label)
        target = host(address, f"postgres:{label}")
        target.nodes.append(
            NodeOut(
                role="postgres",
                name=str(database.get("database_name") or "PostgreSQL"),
                state="healthy" if database.get("is_connected") else "offline",
                detail=label,
            )
        )

    if redis_address:
        target = host(redis_address, f"redis:{redis_address}")
        target.nodes.append(
            NodeOut(
                role="redis",
                name="Redis",
                # The backends' presence lives in Redis: listing them reached it.
                state="healthy" if backends is not None else "unknown",
                detail=redis_address,
            )
        )

    for record in deployments:
        target = host(_deployment_address(record, this_machine), f"deployment:{record.id}")
        target.deployment = target.deployment or record
        present = {node.role for node in target.nodes}
        components = record.details.get("components") or {}
        for role, component in (
            ("backend", "backend"),
            ("workers", "worker"),
            ("webui", "webui"),
            ("postgres", "postgres"),
            ("redis", "redis"),
        ):
            if components.get(component) and role not in present:
                target.nodes.append(
                    NodeOut(
                        role=role,  # type: ignore[arg-type]
                        name=record.name,
                        state="unknown",
                        version=record.details.get("version") or None,
                        detail="Installed here; not reporting to this cluster",
                        installed_only=True,
                    )
                )

    out: list[HostOut] = []
    for key, item in hosts.items():
        nodes = sorted(item.nodes, key=lambda node: (_ROLE_ORDER[node.role], node.name.lower()))
        states = [node.state for node in nodes]
        state: State = max(states, key=lambda value: _STATE_RANK[value]) if states else "unknown"
        name = (
            host_name(store, key)
            or (item.deployment.name if item.deployment else None)
            or (item.names[0] if item.names else None)
            or item.address
            or next((node.name for node in nodes), key)
        )
        roles: list[Role] = []
        for node in nodes:
            if node.role not in roles:
                roles.append(node.role)
        out.append(
            HostOut(
                key=key,
                name=name,
                address=item.address,
                roles=roles,
                state=state,
                nodes=nodes,
                deployment_id=item.deployment.id if item.deployment else None,
            )
        )
    out.sort(key=lambda value: value.name.lower())
    return ClusterHostsOut(
        cluster_id=cluster_id,
        name=cluster_name,
        hosts=out,
        answered_by=answered_by,
        error=None if backends is not None else "No member of this cluster answered.",
    )
