"""Grouping a cluster's nodes into hosts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ultima_webui_server.fleet_hosts import build_hosts, rename_host
from ultima_webui_server.store import DeploymentRecord, Store

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
RECENT = (NOW - timedelta(seconds=20)).isoformat()
OLD = (NOW - timedelta(hours=2)).isoformat()


def _backend(backend_id: str, address: str | None, **extra) -> dict:
    return {
        "backend_id": backend_id,
        "hostname": extra.pop("hostname", backend_id),
        "address": address,
        "status": "online",
        "last_seen": RECENT,
        "cluster_id": "c-1",
        "version": "0.1.0",
        "max_workers": 0,
        "workers": [],
        **extra,
    }


def _client(client_id: str, name: str, address: str | None, **extra) -> dict:
    return {
        "id": client_id,
        "name": name,
        "kind": "webui",
        "last_seen_at": RECENT,
        "last_address": address,
        "version": "0.1.0",
        "revoked_at": None,
        "is_self": False,
        **extra,
    }


def _build(store: Store, **changes):
    values = dict(
        store=store,
        cluster_id="c-1",
        cluster_name="Home",
        backends=[
            _backend("hoarder01", "192.168.1.20", max_workers=8, active_workers=2),
            _backend("alpha-9d4b85", "192.168.50.120", max_workers=4, active_workers=4, hostname="1a2b3c4d5e6f"),
        ],
        reporter_backend_id="hoarder01",
        clients=[
            # Through Docker on the dev box: an address only the backend there knows.
            _client("me", "WebUI on devbox", "172.18.0.5", is_self=True),
            _client("pi", "WebUI on alpha", "192.168.50.120"),
            _client("nas", "WebUI on nas01", "192.168.50.40", last_seen_at=OLD),
            _client("gone", "Old", "192.168.1.99", revoked_at=RECENT),
        ],
        databases=[{"host": "192.168.50.40", "port": 30432, "database_name": "ultima_archive", "is_connected": True}],
        redis_address="localhost:6379",
        connections_by_backend={"hoarder01": "default"},
        deployments=[],
        this_machine="192.168.1.20",
        answered_by="default",
        now=NOW,
    )
    values.update(changes)
    return build_hosts(**values)


def test_nodes_are_grouped_into_the_machines_they_run_on(tmp_path: Path) -> None:
    out = _build(Store(tmp_path / "w.db"))

    hosts = {host.name: host for host in out.hosts}
    assert sorted(hosts) == ["192.168.50.120", "192.168.50.40", "hoarder01"]
    devbox = hosts["hoarder01"]
    assert devbox.address == "192.168.1.20"
    # Redis at localhost and the Docker-addressed WebUI are the reporting backend's machine.
    assert devbox.roles == ["backend", "workers", "webui", "redis"]
    assert next(node for node in devbox.nodes if node.role == "webui").is_self
    assert next(node for node in devbox.nodes if node.role == "backend").connection_id == "default"
    alpha = hosts["192.168.50.120"]
    # A worker-only host has no API server.
    assert alpha.roles == ["workers", "webui"]
    assert next(node for node in alpha.nodes if node.role == "workers").detail == "4/4 busy · 0 pending"
    nas = hosts["192.168.50.40"]
    # Its WebUI has not checked in for two hours: left out; the database is still there.
    assert nas.roles == ["postgres"]
    assert all(node.name != "Old" for host in out.hosts for node in host.nodes)


def test_hosts_take_their_installer_name_or_the_one_given(tmp_path: Path) -> None:
    store = Store(tmp_path / "w.db")
    deployment = DeploymentRecord(
        id="d-1",
        name="alpha",
        target="ultima@192.168.50.120",
        details={"kind": "ssh", "host": "192.168.50.120", "components": {"worker": True, "webui": True, "redis": True}},
        connection_id=None,
        state="active",
        created_at=1.0,
        updated_at=1.0,
    )
    rename_host(store, "192.168.50.40", "nas01")

    out = _build(store, deployments=[deployment])

    hosts = {host.name: host for host in out.hosts}
    assert sorted(hosts) == ["alpha", "hoarder01", "nas01"]
    alpha = hosts["alpha"]
    assert alpha.deployment_id == "d-1"
    # Installed there but not reporting to the cluster: shown, marked.
    redis = next(node for node in alpha.nodes if node.role == "redis")
    assert redis.installed_only and redis.state == "unknown"
    assert alpha.state == "healthy"
    rename_host(store, "192.168.50.40", "")
    assert "nas01" not in {host.name for host in _build(store).hosts}


def test_without_an_answer_the_installed_nodes_still_show(tmp_path: Path) -> None:
    deployment = DeploymentRecord(
        id="d-2",
        name="devbox",
        target="local",
        details={"kind": "local", "components": {"backend": True, "worker": True}},
        connection_id="default",
        state="active",
        created_at=1.0,
        updated_at=1.0,
    )

    out = _build(
        Store(tmp_path / "w.db"),
        backends=None,
        reporter_backend_id=None,
        clients=[],
        databases=[],
        redis_address=None,
        deployments=[deployment],
        answered_by=None,
    )

    assert out.error == "No member of this cluster answered."
    assert [(host.name, host.address, host.roles) for host in out.hosts] == [
        ("devbox", "192.168.1.20", ["backend", "workers"])
    ]


def test_a_backend_without_an_address_is_found_on_the_host_that_runs_it(tmp_path: Path) -> None:
    def alpha(details: dict) -> DeploymentRecord:
        return DeploymentRecord(
            id="d-alpha",
            name="alpha",
            target="ultima@192.168.50.120",
            details={"kind": "ssh", "host": "192.168.50.120", "project": "usr-alpha", **details,
                     "components": {"worker": True, "webui": True}},
            connection_id=None,
            state="active",
            created_at=1.0,
            updated_at=1.0,
        )

    old_worker = [
        _backend("hoarder01", "192.168.1.20", max_workers=8),
        # An image from before addresses were reported.
        _backend("alpha-9d4b85", None, max_workers=4, active_workers=1),
    ]
    for details in ({}, {"backend_id": "alpha-9d4b85"}):
        out = _build(Store(tmp_path / "w.db"), backends=old_worker, clients=[], deployments=[alpha(details)])
        hosts = {host.name: host for host in out.hosts}
        assert "alpha" in hosts and "alpha-9d4b85" not in hosts
        workers = next(node for node in hosts["alpha"].nodes if node.role == "workers")
        # The reporting worker, not the installer's placeholder.
        assert workers.backend_id == "alpha-9d4b85" and not workers.installed_only

    # Another install's id is not taken for it.
    out = _build(
        Store(tmp_path / "w.db"),
        backends=[*old_worker, _backend("alpha2-aaaaaa", None, max_workers=1)],
        clients=[],
        deployments=[alpha({})],
    )
    assert "alpha2-aaaaaa" in {host.name for host in out.hosts}


def test_a_webui_that_stopped_checking_in_is_offline_then_left_out(tmp_path: Path) -> None:
    store = Store(tmp_path / "w.db")
    late = (NOW - timedelta(minutes=10)).isoformat()

    out = _build(store, clients=[_client("pi", "WebUI on alpha", "192.168.50.120", last_seen_at=late)])
    alpha = next(host for host in out.hosts if host.address == "192.168.50.120")
    assert next(node for node in alpha.nodes if node.role == "webui").state == "offline"

    out = _build(store, clients=[_client("pi", "WebUI on alpha", "192.168.50.120", last_seen_at=OLD)])
    alpha = next(host for host in out.hosts if host.address == "192.168.50.120")
    assert "webui" not in alpha.roles
