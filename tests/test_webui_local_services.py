"""The backend and workers a WebUI runs in its own container."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from ultima_webui_server import Settings
from ultima_webui_server import local_services as module
from ultima_webui_server.connections import Connections
from ultima_webui_server.local_services import LocalServices, LocalServicesIn
from ultima_webui_server.store import Store
from ultima_webui_server.tunnels import TunnelManager
from ultima_webui_server.vault import Vault, load_or_create_key

# Stands in for the image's entrypoint: records what it was started with.
_STUB = """
import json, os, sys, time
out = os.environ["STUB_DIR"]
role = os.environ["USR_CONTAINER_ROLE"]
# The environment first, whole, so a counted start always has it to read.
with open(os.path.join(out, role + ".json.tmp"), "w") as env:
    json.dump(dict(os.environ), env)
os.replace(os.path.join(out, role + ".json.tmp"), os.path.join(out, role + ".json"))
with open(os.path.join(out, role + ".starts"), "a") as starts:
    starts.write("x")
print(role, "started", flush=True)
code = int(os.environ.get("STUB_EXIT", "-1"))
if code >= 0:
    sys.exit(code)
time.sleep(60)
"""


class _Stores:
    """A cluster backend's /system/cluster-stores, with PostgreSQL and Redis listening."""

    def __init__(self) -> None:
        self.servers: list[asyncio.base_events.Server] = []
        self.ports: dict[str, int] = {}

    async def listen(self) -> None:
        for kind in ("database", "redis"):
            server = await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", 0)
            self.servers.append(server)
            self.ports[kind] = server.sockets[0].getsockname()[1]

    async def read(self, connection_id: str) -> dict:
        return {
            "available": True,
            "cluster_id": "c-1",
            "database": {
                "host": "127.0.0.1",
                "port": self.ports["database"],
                "name": "ultima_archive",
                "username": "ultimascraper",
                "password": "p@ss/word",
            },
            "redis": {"host": "127.0.0.1", "port": self.ports["redis"], "db": 2, "password": "redis-pass"},
            "secret_key": "cluster-secret-key",
            "settings_id": 1,
        }

    def close(self) -> None:
        for server in self.servers:
            server.close()


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_DIR", str(tmp_path))
    # The WebUI's own settings, which must not reach the services.
    monkeypatch.setenv("USR_SECRET_KEY_FILE", "/run/secrets/webui-only")
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-this")
    monkeypatch.setattr(module, "_FIRST_RESTART_SECONDS", 0.05)
    data = tmp_path / "data"
    data.mkdir()
    store = Store(data / "webui.db")
    vault = Vault(load_or_create_key(data))
    connections = Connections(Settings(data_dir=data, static_dir=tmp_path), store, vault)
    source = connections.create_installed(name="source", base_url="http://127.0.0.1:1", token="t", tunnel=None)
    stores = _Stores()
    await stores.listen()
    registered: list[dict] = []

    async def register_worker(*args, **kwargs) -> bool:
        registered.append(kwargs)
        return True

    def build() -> LocalServices:
        return LocalServices(
            store,
            vault,
            connections,
            TunnelManager(),
            read_stores=stores.read,
            cluster_connections=lambda cluster_id: [connections.get(source.id)],
            register_worker=register_worker,
            command=[sys.executable, "-c", _STUB],
            is_available=lambda: True,
        )

    built: list[LocalServices] = []

    def make() -> LocalServices:
        built.append(build())
        return built[-1]

    yield {"make": make, "store": store, "connections": connections, "dir": tmp_path, "registered": registered}
    for services in built:
        await services.stop_all()
    stores.close()


async def _started(directory: Path, role: str, times: int = 1) -> dict:
    for _ in range(200):
        starts = directory / f"{role}.starts"
        if starts.exists() and len(starts.read_text()) >= times:
            return json.loads((directory / f"{role}.json").read_text())
        await asyncio.sleep(0.02)
    raise AssertionError(f"{role} did not start {times} time(s)")


async def test_each_service_starts_with_the_clusters_settings(setup) -> None:
    services = setup["make"]()

    out = await services.configure(
        LocalServicesIn(cluster_id="c-1", backend=True, worker=True, advertise_host="192.0.2.84")
    )

    api = await _started(setup["dir"], "api")
    worker = await _started(setup["dir"], "worker")
    assert out.backend and out.worker
    assert api["RUN_MODE"] == "api" and worker["RUN_MODE"] == "worker"
    # One id per host, as a Compose host's backend and workers share.
    assert api["BACKEND_ID"] == worker["BACKEND_ID"] == out.backend_id
    assert out.backend_id.startswith("192-0-2-84-")
    assert api["ULTIMA_ARCHIVE_DATABASE_URL"].startswith("postgresql+psycopg://ultimascraper:p%40ss%2Fword@127.0.0.1:")
    assert (api["REDIS_PASSWORD"], api["REDIS_DB"]) == ("redis-pass", "2")
    assert api["USR_SECRET_KEY"] == worker["USR_SECRET_KEY"] == "cluster-secret-key"
    assert api["USR_ADVERTISE_HOST"] == "192.0.2.84"
    assert api["USR_ADMIN_TOKEN"] and "USR_ADMIN_TOKEN" not in worker
    assert "USR_SECRET_KEY_FILE" not in api and "DATABASE_URL" not in api
    # Listed in the cluster's inventory, which stores only IP addresses.
    assert setup["registered"][0]["backend_id"] == out.backend_id
    assert setup["registered"][0]["address"] == "192.0.2.84"


async def test_the_backend_gets_a_connection_and_secrets_are_stored_sealed(setup) -> None:
    services = setup["make"]()
    await services.configure(LocalServicesIn(cluster_id="c-1", backend=True, worker=False))
    api = await _started(setup["dir"], "api")

    stored = setup["store"].get_setting("local_services")
    for secret in ("cluster-secret-key", "redis-pass", api["USR_ADMIN_TOKEN"], "p%40ss"):
        assert secret not in stored
    own = json.loads(stored)["connection_id"]
    connection = setup["connections"].get(own)
    assert connection.base_url == "http://127.0.0.1:21121"
    assert connection.token() == api["USR_ADMIN_TOKEN"]

    out = await services.configure(LocalServicesIn(cluster_id="c-1", backend=False, worker=False))
    assert not out.backend
    assert next(service for service in out.services if service.name == "backend").state == "stopped"
    assert own not in {connection.id for connection in setup["connections"].all()}


async def test_a_service_that_exits_is_started_again(setup, monkeypatch) -> None:
    monkeypatch.setenv("STUB_EXIT", "3")
    services = setup["make"]()
    await services.configure(LocalServicesIn(cluster_id="c-1", backend=False, worker=True))

    await _started(setup["dir"], "worker", times=3)
    worker = next(service for service in services.describe().services if service.name == "worker")
    assert worker.exit_code == 3
    assert "Exited with code 3." in worker.log


async def test_services_start_again_with_the_webui(setup) -> None:
    await setup["make"]().configure(LocalServicesIn(cluster_id="c-1", backend=False, worker=True))
    await _started(setup["dir"], "worker")
    await setup["make"]().resume()

    await _started(setup["dir"], "worker", times=2)


async def test_unreachable_stores_and_other_images_are_refused(setup, monkeypatch) -> None:
    services = setup["make"]()
    monkeypatch.setattr(module, "_reachable", lambda host, port: asyncio.sleep(0, result=False))
    with pytest.raises(HTTPException, match="cannot reach the cluster's PostgreSQL"):
        await services.configure(LocalServicesIn(cluster_id="c-1", backend=True, worker=False))
    assert setup["store"].get_setting("local_services") is None

    services._is_available = lambda: False
    with pytest.raises(HTTPException) as refused:
        await services.configure(LocalServicesIn(cluster_id="c-1", backend=True, worker=False))
    assert refused.value.status_code == 409


async def test_the_refusal_says_why_each_backend_gave_nothing(setup) -> None:
    services = setup["make"]()

    async def unavailable(connection_id: str) -> dict:
        return {"available": False, "reasons": ["Home backend: HTTP 404 from http://192.0.2.10:21121"]}

    services._read_stores = unavailable
    with pytest.raises(HTTPException) as refused:
        await services.configure(LocalServicesIn(cluster_id="c-1", backend=True, worker=False))
    assert refused.value.status_code == 502
    assert "Home backend: HTTP 404 from http://192.0.2.10:21121" in refused.value.detail

    async def other_cluster(connection_id: str) -> dict:
        return {"available": True, "cluster_id": "c-2", "database": {}, "redis": {}}

    services._read_stores = other_cluster
    with pytest.raises(HTTPException, match=r"belongs to another cluster \(c-2\)"):
        await services.configure(LocalServicesIn(cluster_id="c-1", backend=True, worker=False))


def test_only_a_full_image_container_can_run_them(monkeypatch) -> None:
    monkeypatch.setattr(module, "in_container", lambda: True)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    assert module.available()
    # The slim WebUI image has no backend.
    monkeypatch.setattr(module.shutil, "which", lambda name: None if name == "ultimascraper" else f"/bin/{name}")
    assert not module.available()
    monkeypatch.setattr(module, "in_container", lambda: False)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/usr/local/bin/{name}")
    assert not module.available()


def test_a_store_on_the_source_backends_own_machine_is_reached_there() -> None:
    from ultima_webui_server.connections import Connection

    source = Connection(
        id="s", name="s", base_url="http://192.0.2.98:21121", tls_verify=True, managed=False, _token=None
    )
    assert module._source_host(source) == "192.0.2.98"
    assert module._loopback_or_service_name("postgres")
    assert module._loopback_or_service_name("127.0.0.1")
    assert not module._loopback_or_service_name("192.0.2.84")


def test_the_inventory_always_gets_an_ip_address() -> None:
    assert module._inventory_address("192.0.2.84") == "192.0.2.84"
    assert module._inventory_address("localhost") == "127.0.0.1"
    # No address given: this container's own.
    module.ipaddress.ip_address(module._inventory_address(None))
