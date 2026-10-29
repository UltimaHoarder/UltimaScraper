from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text

from ultima_scraper_backend import cluster
from ultima_scraper_backend.ultima_control.backend_registry import BackendInfo, BackendRegistry


@pytest.fixture(autouse=True)
def _fresh_cache():
    cluster.reset_cluster_id_cache()
    yield
    cluster.reset_cluster_id_cache()


def _shared_database(tmp_path: Path):
    """A SQLite stand-in for PostgreSQL with a management schema."""
    engine = create_engine(f"sqlite:///{tmp_path / 'main.db'}")
    management = tmp_path / "management.db"

    @event.listens_for(engine, "connect")
    def _attach(connection, _record) -> None:
        connection.execute(f"ATTACH DATABASE '{management}' AS management")

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE management.cluster (id INTEGER PRIMARY KEY DEFAULT 1, "
                "cluster_id TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))))"
            )
        )
    return engine


def _use(monkeypatch: pytest.MonkeyPatch, engine) -> None:
    from ultima_scraper_db_archive import global_db

    monkeypatch.setattr(cluster, "archive_database_url", lambda: "postgresql://fixture.invalid/archive")
    monkeypatch.setattr(global_db, "get_global_engine", lambda: engine)


def test_every_backend_on_one_database_reads_the_same_cluster_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = _shared_database(tmp_path)
    _use(monkeypatch, engine)

    first = cluster.get_cluster_id()
    cluster.reset_cluster_id_cache()  # another backend process
    second = cluster.get_cluster_id()

    assert first and first == second
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM management.cluster")).scalar() == 1


def test_no_database_or_an_older_schema_means_no_cluster(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cluster, "archive_database_url", lambda: None)
    assert cluster.get_cluster_id() is None

    # The table appears with a schema upgrade; the id is read then.
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    _use(monkeypatch, engine)
    assert cluster.get_cluster_id() is None
    _use(monkeypatch, _shared_database(tmp_path))
    assert cluster.get_cluster_id() is not None


def test_identity_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BACKEND_ID", "nas-1")

    assert cluster.backend_id() == "nas-1"
    assert cluster.public_api_url() is None


def test_registry_entries_carry_the_cluster_and_address() -> None:
    info = BackendInfo("nas-1", "nas", "10.0.0.2", "linux", "1.0", cluster_id="c-1", api_url="http://nas:21121")

    assert BackendInfo.from_json(info.to_json()).cluster_id == "c-1"
    # Entries written by older backends have neither.
    old = BackendInfo.from_dict({"backend_id": "old", "hostname": "old"})
    assert (old.cluster_id, old.api_url) == (None, None)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, *keys):
        return 0

    async def exists(self, *keys):
        return 0

    async def expire(self, key, seconds):
        return True

    async def sadd(self, name, *values):
        return 1

    async def srem(self, name, *values):
        return 1

    async def smembers(self, name):
        return set()


async def test_registration_publishes_the_cluster_once_the_database_has_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.ultima_control import backend_registry

    answers = iter([None, "c-1"])
    monkeypatch.setattr(backend_registry, "get_cluster_id", lambda: next(answers))
    redis = _FakeRedis()
    registry = BackendRegistry(redis, backend_id="nas-1")

    await registry.register()
    assert BackendInfo.from_json(redis.values[registry._backend_key()]).cluster_id is None
    await registry.heartbeat()
    published = BackendInfo.from_json(redis.values[registry._backend_key()])
    assert (published.cluster_id, published.api_url) == ("c-1", None)


class _PresenceRedis(_FakeRedis):
    """Also exposes the raw client, as RedisManager does."""

    @property
    def client(self):
        return self

    async def scan_iter(self, match: str, count: int = 100):
        prefix = match.rstrip("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key.encode()


async def test_presence_announces_cluster_members_outside_the_routing_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.api.routes.system import RemoteBackendInfo, _merge_presence

    monkeypatch.setattr(cluster, "get_cluster_id", lambda: "c-1")
    redis = _PresenceRedis()
    await cluster.publish_presence(redis, "nas-2", ttl=60)
    redis.values["ultimascraper:backend:presence:broken"] = "not json"

    presence = await cluster.read_presence(redis)
    assert [(entry["backend_id"], entry["cluster_id"], entry["api_url"]) for entry in presence] == [
        ("nas-2", "c-1", None)
    ]

    # A routing member keeps its details and gains the cluster; others are added.
    routed = RemoteBackendInfo(backend_id="nas-1", hostname="nas", status="busy", last_seen="t", max_workers=4, version="1")
    listed = [routed]
    _merge_presence(listed, [*presence, {"backend_id": "nas-1", "cluster_id": "c-1", "api_url": "http://nas-1:21121"}])
    assert [(entry.backend_id, entry.status, entry.cluster_id) for entry in listed] == [
        ("nas-1", "busy", "c-1"),
        ("nas-2", "online", "c-1"),
    ]
    assert listed[0].api_url == "http://nas-1:21121"
