"""Idle CPU changes: ownership safety, bounded pools and import-free readiness."""

import asyncio
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool, QueuePool
from ultima_scraper_backend.job_system.idle import IdleDelay, SchedulingLease
from ultima_scraper_backend.workers.readiness import WorkerReadiness
from ultima_scraper_db_archive import global_db


def probe():
    path = Path(__file__).resolve().parents[1] / "docker/worker-healthcheck.py"
    spec = importlib.util.spec_from_file_location("worker_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "mode,role,pool,size",
    [
        ("unknown", "application", NullPool, None),
        ("session", "application", NullPool, None),
        ("unknown", "worker_reader", NullPool, None),
        ("transaction", "application", QueuePool, 2),
        ("transaction", "worker_reader", QueuePool, 2),
        ("session", "writer", QueuePool, 8),
    ],
)
def test_management_pool_policy_is_explicit_and_bounded(
    monkeypatch, mode, role, pool, size
):
    captured = {}
    engine = create_engine("sqlite://")
    monkeypatch.setattr(
        global_db,
        "runtime_env_value",
        lambda key: {
            "ULTIMA_PGBOUNCER_GLOBAL_POOL_MODE": mode,
            "ULTIMA_DATABASE_PROCESS_ROLE": role,
            "ULTIMA_DATABASE_WRITER_CONCURRENCY": "8",
        }.get(key),
    )
    monkeypatch.setattr(
        global_db,
        "create_engine",
        lambda url, **kwargs: captured.update(kwargs) or engine,
    )
    monkeypatch.setattr(global_db, "set_postgres_engine", lambda value: None)
    global_db.set_postgres_url("postgresql://ultimascraper:secret@pooler:6432/archive")
    assert captured["poolclass"] is pool
    assert captured.get("pool_size") == size
    assert captured.get("max_overflow", 0) == 0
    assert captured["connect_args"]["prepare_threshold"] is None
    if mode == "transaction":
        assert captured["pool_timeout"] == 5
        assert captured["pool_pre_ping"] is True
        assert captured["pool_reset_on_return"] == "rollback"
    engine.dispose()


def test_unknown_pool_mode_is_rejected(monkeypatch):
    monkeypatch.setattr(
        global_db,
        "runtime_env_value",
        lambda key: "typo" if key == "ULTIMA_PGBOUNCER_GLOBAL_POOL_MODE" else None,
    )
    with pytest.raises(ValueError, match="must be unknown"):
        global_db.set_postgres_url("postgresql://localhost:6432/archive")


def test_pool_guard_reconnects_in_a_different_process_identity(monkeypatch):
    engine = create_engine("sqlite://", poolclass=QueuePool)
    monkeypatch.setattr(global_db, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(global_db, "set_postgres_engine", lambda value: None)
    global_db.set_postgres_url("postgresql://localhost:5432/archive")
    with engine.connect() as connection:
        original = connection.connection.driver_connection
    monkeypatch.setattr(global_db.os, "getpid", lambda: 999999)
    with engine.connect() as connection:
        assert connection.connection.driver_connection is not original
        assert connection.scalar(text("SELECT 1")) == 1
    engine.dispose()


def test_empty_claim_backoff_is_bounded_and_resets():
    delay = IdleDelay(initial=0.05)
    assert [delay.next(True) for _ in range(8)] == [0.05, 0.1, 0.2, 0.4, 0.8, 1, 1, 1]
    assert delay.next(False) == 0.05
    assert delay.next(True) == 0.05


@pytest.mark.asyncio
async def test_wake_hint_interrupts_idle_wait_and_resets_delay():
    delay = IdleDelay(initial=0.01)
    delay.delay = 1
    event = asyncio.Event()
    task = asyncio.create_task(delay.wait(event, idle=True))
    await asyncio.sleep(0)
    event.set()
    await asyncio.wait_for(task, 0.2)
    assert delay.delay == 0.01
    assert not event.is_set()


@pytest.mark.asyncio
async def test_scheduling_lease_failover_tokens_and_redis_outage():
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis()
    manager = SimpleNamespace(client=client, is_connected=True)
    one, two = SchedulingLease(manager), SchedulingLease(manager)
    try:
        await one.update()
        await two.update()
        assert one.allowed and not two.allowed
        await one.close()
        await two.update()
        assert two.allowed
        # Old owner cannot renew or delete its replacement's lease.
        await one.close()
        assert await client.get(two.key) == two.token.encode()
        await one.update()
        assert not one.allowed
        two.deadline = time.monotonic() - 1
        assert not two.allowed
        await client.delete(two.key)  # Simulate Redis expiry, no wall-clock wait.
        await one.update()
        assert one.allowed
        manager.is_connected = False
        await one.update()
        assert one.allowed and one.state == "fallback"
    finally:
        await client.aclose()


def test_readiness_is_atomic_secret_free_and_scales_to_zero(tmp_path, monkeypatch):
    path = tmp_path / "ready.json"
    marker = WorkerReadiness(path)
    marker.publish("backend", 2, ["b", "a"], force=True)
    assert path.stat().st_mode & 0o777 == 0o600
    module = probe()
    monkeypatch.setenv("USR_WORKER_READINESS_FILE", str(path))
    value = module._read_readiness()
    assert value["worker_ids"] == ["a", "b"]
    marker.publish("backend", 0, [], force=True)
    assert module._read_readiness()["expected_workers"] == 0
    newer = WorkerReadiness(path)
    newer.publish("backend", 1, ["new"], force=True)
    marker.close()
    assert path.exists()
    newer.close()
    assert not path.exists()


@pytest.mark.parametrize("change", ["stale", "dead", "reused_pid", "corrupt"])
def test_readiness_rejects_invalid_parent_or_marker(tmp_path, monkeypatch, change):
    path = tmp_path / "ready.json"
    WorkerReadiness(path).publish("backend", 1, ["a"], force=True)
    value = json.loads(path.read_text())
    if change == "stale":
        value["updated_monotonic"] -= 46
    if change == "dead":
        value["pid"] = 2147483647
    if change == "reused_pid":
        value["process_started"] -= 100
    path.write_text("bad json" if change == "corrupt" else json.dumps(value))
    module = probe()
    monkeypatch.setenv("USR_WORKER_READINESS_FILE", str(path))
    with pytest.raises((ValueError, KeyError, module.psutil.Error)):
        module._read_readiness()


def test_probe_imports_no_application_or_database_packages():
    path = Path(__file__).resolve().parents[1] / "docker/worker-healthcheck.py"
    code = """import builtins,runpy,sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
 if name.startswith(('ultima_scraper','sqlalchemy','psycopg')):raise AssertionError(name)
 return original(name,*args,**kwargs)
builtins.__import__=guarded
runpy.run_path(sys.argv[1],run_name='probe_import_test')
"""
    subprocess.run([sys.executable, "-c", code, str(path)], check=True, timeout=5)


@pytest.mark.asyncio
async def test_empty_sampler_discovery_backs_off_and_wakes(monkeypatch):
    from unittest.mock import Mock

    from ultima_scraper_backend.database import threads
    from ultima_scraper_backend.job_system.ledger import ExecutionLedger
    from ultima_scraper_backend.services import job_runtime_telemetry_sampler as module

    clock = [0.0]
    monkeypatch.setattr(
        module,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 1000 + clock[0]),
    )
    reads = Mock(return_value=[])
    monkeypatch.setattr(ExecutionLedger, "active_run_ids", reads)

    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(threads, "run_database_call", inline)
    pipeline = SimpleNamespace(smembers=Mock(), execute=AsyncMock(return_value=[]))
    client = SimpleNamespace(
        set=AsyncMock(return_value=True),
        zrange=AsyncMock(return_value=[]),
        pipeline=Mock(return_value=pipeline),
    )
    sampler = module.JobRuntimeTelemetrySampler(SimpleNamespace())
    sampler.storage = SimpleNamespace(_client=lambda: client)
    await sampler._sample_active_jobs(1000)
    clock[0] = 4
    await sampler._sample_active_jobs(1004)
    assert reads.call_count == 1
    sampler._discovery_wake.set()
    await sampler._sample_active_jobs(1004)
    assert reads.call_count == 2
    clock[0] = 9
    await sampler._sample_active_jobs(1009)
    assert reads.call_count == 3


def test_probe_uses_only_current_pool_worker_ids_and_requires_redis(monkeypatch):
    import fakeredis

    module = probe()
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(module, "Redis", lambda **kwargs: client)
    monkeypatch.setenv("REDIS_HOST", "test")
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.delenv("REDIS_PASSWORD_FILE", raising=False)
    readiness = {"backend_id": "shared", "worker_ids": ["current", "missing"]}
    client.sadd("ultimascraper:backend:shared:workers", "current", "other-pool")
    for name in ["current", "other-pool"]:
        client.set("ultimascraper:workers:" + name, "1")
        client.set("ultimascraper:workers:heartbeat:" + name, "1")
    assert module._active_worker_count(readiness) == 1
    client.delete("ultimascraper:workers:heartbeat:current")
    assert module._active_worker_count(readiness) == 0
    monkeypatch.setattr(
        client, "pipeline", lambda **kwargs: (_ for _ in ()).throw(ConnectionError())
    )
    with pytest.raises(ConnectionError):
        module._active_worker_count(readiness)


def test_corrupt_readiness_marker_does_not_interrupt_shutdown(tmp_path):
    path = tmp_path / "ready.json"
    marker = WorkerReadiness(path)
    marker.publish("backend", 1, ["worker"], force=True)
    path.write_text("invalid JSON")
    marker.close()
    assert path.read_text() == "invalid JSON"
