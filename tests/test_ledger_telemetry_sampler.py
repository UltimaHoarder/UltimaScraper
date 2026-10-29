"""Ledger diagnostics discover SQL runs even without legacy queue assignments."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ultima_scraper_backend.job_system.ledger import ExecutionLedger
from ultima_scraper_backend.services.job_runtime_telemetry_sampler import (
    JobRuntimeTelemetrySampler,
)


@pytest.mark.asyncio
async def test_sampler_discovers_ledger_run_without_redis_backend_assignments(
    monkeypatch,
):
    monkeypatch.delenv("ULTIMA_JOB_ENGINE", raising=False)
    monkeypatch.setattr(ExecutionLedger, "stats_many", lambda self, ids: {})
    monkeypatch.setattr(
        ExecutionLedger, "active_run_ids", lambda self, **kwargs: ["job-ledger"]
    )
    pipeline = SimpleNamespace(smembers=Mock(), execute=AsyncMock(return_value=[]))
    client = SimpleNamespace(
        set=AsyncMock(return_value=True),
        zrange=AsyncMock(return_value=[]),
        pipeline=Mock(return_value=pipeline),
        hset=AsyncMock(),
        expire=AsyncMock(),
    )
    sampler = JobRuntimeTelemetrySampler(SimpleNamespace())
    sampler.storage = SimpleNamespace(
        _client=lambda: client,
        JOB_STATE_KEY="state:{job_id}",
        get_job_task_stats=AsyncMock(
            return_value={
                "total": 1000,
                "ready": 240,
                "inflight": 16,
                "completed": 300,
                "failed": 0,
            }
        ),
        append_job_runtime_samples=AsyncMock(),
    )
    await sampler._sample_active_jobs(1)
    sample = next(iter(sampler.storage.append_job_runtime_samples.await_args.args[0]))
    assert sample[0] == "job-ledger"
    assert sample[1]["ready"] == 240 and sample[1]["inflight"] == 16
    client.hset.assert_awaited_once_with(
        "state:job-ledger",
        mapping={
            "total_tasks": 1000,
            "ready_tasks": 240,
            "inflight_tasks": 16,
            "completed_tasks": 300,
            "failed_tasks": 0,
            "blocked_tasks": 0,
        },
    )


@pytest.mark.asyncio
async def test_sampler_stamps_before_slow_stats_read_and_keys_by_tick(monkeypatch):
    from ultima_scraper_backend.services import job_runtime_telemetry_sampler
    monkeypatch.setattr(ExecutionLedger, "stats_many", lambda self, ids: {})

    monkeypatch.setattr(
        ExecutionLedger, "active_run_ids", lambda self, **kwargs: ["job-ledger"]
    )
    clock = {"now": 1_000.25}
    monkeypatch.setattr(job_runtime_telemetry_sampler.time, "time", lambda: clock["now"])

    async def slow_stats(job_id):
        clock["now"] += 0.9
        return {"total": 10, "ready": 1, "inflight": 2, "completed": 5, "failed": 0}

    pipeline = SimpleNamespace(smembers=Mock(), execute=AsyncMock(return_value=[]))
    client = SimpleNamespace(
        set=AsyncMock(return_value=True),
        zrange=AsyncMock(return_value=[]),
        pipeline=Mock(return_value=pipeline),
        hset=AsyncMock(),
        expire=AsyncMock(),
    )
    sampler = JobRuntimeTelemetrySampler(SimpleNamespace())
    sampler.storage = SimpleNamespace(
        _client=lambda: client,
        JOB_STATE_KEY="state:{job_id}",
        get_job_task_stats=slow_stats,
        append_job_runtime_samples=AsyncMock(),
    )
    await sampler._sample_active_jobs(1_000)
    call = sampler.storage.append_job_runtime_samples.await_args
    (_, sample), = list(call.args[0])
    assert sample["timestamp_ms"] == 1_000_250
    assert call.kwargs["tick_ms"] == 1_000_000


@pytest.mark.asyncio
async def test_runtime_samples_stay_in_tick_order_when_a_late_tick_finishes_last():
    import fakeredis.aioredis
    from test_job_system import FakeRedisManager
    from ultima_scraper_backend.job_system.storage import JobStorage

    client = fakeredis.aioredis.FakeRedis()
    storage = JobStorage(FakeRedisManager(client))

    def sample(timestamp_ms, completed):
        return ("job-ledger", {"timestamp_ms": timestamp_ms, "completed": completed})

    try:
        await storage.append_job_runtime_samples([sample(1_000_010, 100)], tick_ms=1_000_000)
        await storage.append_job_runtime_samples([sample(1_002_005, 300)], tick_ms=1_002_000)
        # Tick 1_001 finished after tick 1_002 on another worker; it is dropped.
        await storage.append_job_runtime_samples([sample(1_001_020, 200)], tick_ms=1_001_000)
        page = await storage.get_job_runtime_samples("job-ledger")
        assert [row["cursor"] for row in page["samples"]] == ["1000000-0", "1002000-0"]
        assert [row["completed"] for row in page["samples"]] == [100, 300]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_ledger_aggregate_counts_steady_progress_without_a_sql_poll():
    import fakeredis.aioredis
    from test_job_system import FakeRedisManager
    from ultima_scraper_backend.job_system.storage import JobStorage

    client = fakeredis.aioredis.FakeRedis()
    storage = JobStorage(FakeRedisManager(client))
    try:
        for index in range(10):
            await storage.record_task_runtime_telemetry(
                "job-ledger",
                started_ms=1000 + index * 1000,
                finished_ms=2000 + index * 1000,
                queue_wait_ms=0,
                setup_ms=0,
                handler_ms=1000,
                writer_ms=0,
                post_ms=0,
                release_ms=0,
                route_active_ms=1000,
                route_attempts=1,
                success=True,
                total_tasks=10,
                completed_count=None,
            )
        metrics = await storage.get_job_runtime_telemetry("job-ledger")
        assert metrics["task_count"] == 10
        assert metrics["steady_task_count"] == 9
        assert metrics["steady_throughput"] == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_failed_tasks_advance_steady_window_but_not_successful_throughput():
    import fakeredis.aioredis
    from test_job_system import FakeRedisManager
    from ultima_scraper_backend.job_system.storage import JobStorage

    client = fakeredis.aioredis.FakeRedis()
    storage = JobStorage(FakeRedisManager(client))
    try:
        for index in range(10):
            await storage.record_task_runtime_telemetry(
                "job-failed-ledger",
                started_ms=1000 + index * 1000,
                finished_ms=2000 + index * 1000,
                queue_wait_ms=0,
                setup_ms=0,
                handler_ms=1000,
                writer_ms=0,
                post_ms=0,
                release_ms=0,
                route_active_ms=1000,
                route_attempts=1,
                success=index < 3,
                total_tasks=10,
                completed_count=None,
            )
        metrics = await storage.get_job_runtime_telemetry("job-failed-ledger")
        assert metrics["task_count"] == 10
        assert metrics["succeeded_tasks"] == 3
        assert metrics["failed_tasks"] == 7
        assert metrics["steady_window_basis"] == "terminal_tasks"
        assert metrics["steady_window_ms"] == 8000
        assert metrics["steady_task_count"] == 9
        assert metrics["steady_terminal_throughput"] == 1
        assert metrics["steady_throughput"] == 0.25
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_refill_diagnostics_keep_bounded_sql_observations():
    import fakeredis.aioredis
    from ultima_scraper_backend.job_system import mps_state
    from ultima_scraper_backend.job_system.ledger_runtime import (
        publish_refill_diagnostics,
    )

    client = fakeredis.aioredis.FakeRedis()
    try:
        observations = [
            {
                "job_id": "job-ledger",
                "timestamp_ms": index,
                "ready": index,
                "inflight": 80,
                "stage": "ledger_refill",
                "controls": {"window_tasks": 20000},
            }
            for index in range(300)
        ]
        await publish_refill_diagnostics(client, observations)
        values = await client.lrange(
            mps_state.REFILL_TRACE_KEY.format(job_id="job-ledger"), 0, -1
        )
        assert len(values) == 256
        assert json.loads(values[0])["timestamp_ms"] == 44
        assert json.loads(values[-1])["ready"] == 299
        assert json.loads(values[-1])["controls"]["window_tasks"] == 20000
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_service_refills_while_event_and_diagnostic_publication_are_blocked(
    monkeypatch,
):
    from anyio import from_thread
    from ultima_scraper_backend.job_system import ledger_runtime

    event_started, diagnostic_started = asyncio.Event(), asyncio.Event()
    release_event, release_diagnostic, continued = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    class FakeLedger:
        limits = SimpleNamespace(batch=128)

        def recover_expired(self):
            return 0

        def tick(self, *, diagnostics, refill_only, outcome):
            assert refill_only is True
            diagnostics.append({"job_id": "job-ledger", "stage": "ledger_refill"})
            if event_started.is_set() and diagnostic_started.is_set():
                from_thread.run_sync(continued.set)

        def archive_tick(self, *, diagnostics, outcome):
            return None

        def relay(self, *, publish_many, outcome):
            publish_many([{"event": "task_completed"}])
            return 1

        def record_progress(self, *, previous):
            return {}

        def reindex_bloated_queue_indexes(self):
            return []

    def pipeline(**kwargs):
        result = SimpleNamespace(
            publish=Mock(), rpush=Mock(), ltrim=Mock(), expire=Mock()
        )

        async def execute():
            if result.publish.called:
                event_started.set()
                await release_event.wait()
            else:
                diagnostic_started.set()
                await release_diagnostic.wait()
            return []

        result.execute = execute
        return result

    monkeypatch.setattr(ledger_runtime, "ExecutionLedger", FakeLedger)
    backend = SimpleNamespace(
        redis=SimpleNamespace(
            is_connected=True,
            client=SimpleNamespace(pipeline=pipeline, set=AsyncMock(return_value=True), eval=AsyncMock(return_value=1)),
        )
    )
    service = asyncio.create_task(ledger_runtime.service(backend))
    try:
        await asyncio.wait_for(continued.wait(), 2)
        assert not release_event.is_set()
        assert not release_diagnostic.is_set()
    finally:
        release_event.set()
        release_diagnostic.set()
        service.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(service, 2)
