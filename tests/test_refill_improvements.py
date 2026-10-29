"""Refill throughput: no sleep after full planner batches, a cached proxy pool,
and archive passes in their own process."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import fakeredis.aioredis
import pytest
from sqlalchemy import event, text
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from ultima_scraper_backend.job_system import idle as idle_module
from ultima_scraper_backend.job_system import ledger_runtime
from ultima_scraper_backend.job_system.ledger import ExecutionLedger, Limits

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def _backend():
    def pipeline(**kwargs):
        return SimpleNamespace(publish=Mock(), rpush=Mock(), ltrim=Mock(), expire=Mock(),
                               execute=AsyncMock(return_value=[]))

    return SimpleNamespace(redis=SimpleNamespace(
        is_connected=True,
        client=SimpleNamespace(pipeline=pipeline, set=AsyncMock(return_value=True),
                               eval=AsyncMock(return_value=1)),
    ))


class FakeLedger:
    limits = SimpleNamespace(batch=128)

    def __init__(self, productive):
        self.productive = productive
        self.ticks = 0
        self.archive_ticks = 0

    def recover_expired(self):
        return 0

    def tick(self, *, diagnostics, refill_only, outcome):
        self.ticks += 1
        outcome[:] = ["progress"]
        return "job-busy" if self.productive(self.ticks) else None

    def archive_tick(self, *, diagnostics, outcome):
        self.archive_ticks += 1
        outcome[:] = ["idle"]
        return None

    def relay(self, *, publish_many, outcome):
        outcome[:] = ["idle"]
        return 0

    def record_progress(self, *, previous):
        return {}

    def reindex_bloated_queue_indexes(self):
        return []


async def _run_service(monkeypatch, fake, seconds):
    # A long backoff makes any sleep after a batch obvious.
    monkeypatch.setattr(idle_module.IdleDelay, "__init__",
                        lambda self, initial=30.0, maximum=30.0: setattr(self, "initial", initial)
                        or setattr(self, "maximum", maximum) or setattr(self, "delay", initial))
    monkeypatch.setattr(ledger_runtime, "ExecutionLedger", lambda: fake)
    service = asyncio.create_task(ledger_runtime.service(_backend()))
    try:
        await asyncio.sleep(seconds)
    finally:
        service.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(service, 2)


@pytest.mark.asyncio
async def test_planner_plans_again_at_once_after_a_full_productive_batch(monkeypatch):
    fake = FakeLedger(productive=lambda tick: True)
    await _run_service(monkeypatch, fake, 0.5)
    # Previously one batch of 8, then a sleep; now batch after batch.
    assert fake.ticks > 3 * ledger_runtime.PLANNER_BATCH_TICKS


@pytest.mark.asyncio
async def test_planner_still_waits_after_a_short_batch(monkeypatch):
    fake = FakeLedger(productive=lambda tick: tick <= 3)
    await _run_service(monkeypatch, fake, 0.5)
    # Three admitting ticks, one empty tick, then the (30 s) wait.
    assert fake.ticks == 4


@pytest.mark.asyncio
async def test_control_plane_skips_archivers_when_they_run_in_their_own_process(monkeypatch):
    monkeypatch.setenv("ULTIMA_ARCHIVE_PROCESS", "1")
    fake = FakeLedger(productive=lambda tick: False)
    await _run_service(monkeypatch, fake, 0.3)
    assert fake.archive_ticks == 0
    monkeypatch.setenv("ULTIMA_ARCHIVE_PROCESS", "0")
    fake = FakeLedger(productive=lambda tick: False)
    await _run_service(monkeypatch, fake, 0.3)
    assert fake.archive_ticks >= 1


@pytest.mark.asyncio
async def test_archiver_process_runs_its_passes_under_its_own_lease(monkeypatch):
    from test_job_system import FakeRedisManager
    from ultima_scraper_backend.job_system import archiver_process

    monkeypatch.setenv("ULTIMA_ARCHIVE_PARALLEL_PASSES", "2")
    client = fakeredis.aioredis.FakeRedis()
    manager = FakeRedisManager(client)
    manager.is_connected = True
    running, peak, calls = 0, 0, 0
    stop = asyncio.Event()

    class Ledger:
        def archive_tick(self, *, diagnostics, outcome):
            nonlocal running, peak, calls
            running += 1
            peak = max(peak, running)
            import time
            time.sleep(0.02)
            running -= 1
            calls += 1
            outcome[:] = ["progress"]
            return "job-a" if calls < 40 else None

    async def stop_later():
        while calls < 20:
            await asyncio.sleep(0.01)
        keys = await client.keys("ultimascraper:ledger:scheduler:*")
        stop.set()
        return keys

    try:
        keys, _ = await asyncio.wait_for(
            asyncio.gather(stop_later(), archiver_process.run_archiver(manager, ledger=Ledger(), stop=stop)), 10
        )
    finally:
        await client.aclose()
    assert calls >= 20 and peak == 2  # both passes ran at once, in their own threads
    assert [key.decode() for key in keys] and all(key.decode().endswith(":archiver") for key in keys)


def test_launcher_starts_the_archiver_only_when_enabled(monkeypatch):
    import main

    started = []
    monkeypatch.setattr(main, "start_process", lambda context, target, name, description: started.append(name) or name)
    monkeypatch.delenv("ULTIMA_ARCHIVE_PROCESS", raising=False)
    assert main.start_ledger_archiver(None) == []
    monkeypatch.setenv("ULTIMA_ARCHIVE_PROCESS", "1")
    assert main.start_ledger_archiver(None) == [("ledger archiver", "ledger-archiver")]
    assert started == ["ledger-archiver"]


def test_refill_reads_the_proxy_pool_only_when_it_changes(ledger):
    planner = ExecutionLedger(ledger.session_factory, limits=Limits(tasks=2, global_tasks=4, batch=2, planner_batch=2))
    submit(planner, [task(f"pool-{index}") for index in range(12)], identity="job-pool")
    with ledger.session_factory() as session:
        session.execute(text("UPDATE management.mps_plans SET proxy_pool_json=:pool WHERE job_id='job-pool'"),
                        {"pool": '["http://a:1", "http://b:2"]'})
        session.commit()
        engine = session.get_bind()
    reads = []

    def capture(_conn, _cursor, statement, *_args):
        if "proxy_pool_json" in statement and "md5" not in statement and statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        for _ in range(3):
            planner.tick(refill_only=True)
        assert len(reads) == 1
        cached = planner._proxy_pools["job-pool"][1]
        assert cached == ("http://a:1", "http://b:2")
        with ledger.session_factory() as session:
            session.execute(text("UPDATE management.mps_plans SET proxy_pool_json=:pool WHERE job_id='job-pool'"),
                            {"pool": '["http://c:3"]'})
            session.commit()
        planner.tick(refill_only=True)
        assert len(reads) == 2 and planner._proxy_pools["job-pool"][1] == ("http://c:3",)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    # The cached snapshot equals the full snapshot apart from the pool's type.
    with ledger.session_factory() as session:
        from ultima_scraper_db_archive.global_db import MPSPlanModel
        from sqlalchemy import func, select

        source, digest = session.execute(
            select(MPSPlanModel, func.md5(MPSPlanModel.proxy_pool_json)).where(MPSPlanModel.job_id == "job-pool")
        ).one()
        full = planner.manifests._snapshot(source)
        cached = planner._planner_snapshot(session, source, digest)
    assert {**cached, "proxy_pool": list(cached["proxy_pool"])} == full
