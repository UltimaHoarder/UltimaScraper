"""Result delivery batching, bounded observer ownership and durable fallback."""

import asyncio
from datetime import UTC, datetime

import pytest
from redis.exceptions import ConnectionError, ResponseError
from test_database_write_queue import redis_manager
from ultima_scraper_backend.database.write_queue import (
    WRITE_TIMING_KEY,
    DatabaseWriteClient,
    DatabaseWriteError,
    DatabaseWriteResult,
    DatabaseWriteTimeout,
)

__all__ = ["redis_manager"]


async def publish(redis, client, command_id):
    clock = await redis.time()
    result = DatabaseWriteResult(
        command_id=command_id,
        success=True,
        payload={"id": command_id, WRITE_TIMING_KEY: {}},
        error=None,
        completed_at=datetime.now(UTC).isoformat(),
    )
    await redis.mset(
        {
            client.result_key(command_id): result.to_json(),
            client.result_available_key(command_id): clock[0] * 1000 + clock[1] / 1000,
        }
    )


async def test_bulk_results_share_bounded_atomic_snapshots(redis_manager, monkeypatch):
    redis = redis_manager.client
    client = DatabaseWriteClient(redis_manager)
    count = 300
    for i in range(count):
        await publish(redis, client, str(i))
    reads = []
    pipeline = redis.pipeline

    class ObservedPipeline:
        def __init__(self, inner):
            self.inner = inner

        async def __aenter__(self):
            await self.inner.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self.inner.__aexit__(*args)

        async def mget(self, keys):
            reads.append(tuple(keys))
            return await self.inner.mget(keys)

        def __getattr__(self, key):
            return getattr(self.inner, key)

    monkeypatch.setattr(
        redis, "pipeline", lambda **kwargs: ObservedPipeline(pipeline(**kwargs))
    )
    results = await asyncio.gather(
        *(client.wait_for_result(str(i), include_timing=True) for i in range(count))
    )
    assert [result["id"] for result in results] == [str(i) for i in range(count)]
    assert len(reads) <= 4  # Per-task polling used 300 MGETs and 300 clocks.
    assert all(len(keys) <= 128 * 3 for keys in reads)
    assert all(
        result[WRITE_TIMING_KEY]["writer_result_observed_at_ms"]
        >= result[WRITE_TIMING_KEY]["writer_result_available_at_ms"]
        for result in results
    )
    assert not client._result_waiter.pending


async def test_slow_neighbor_does_not_delay_ready_result(redis_manager):
    client = DatabaseWriteClient(redis_manager)
    await redis_manager.client.set(client.submitted_key("slow"), "queued")
    slow = asyncio.create_task(client.wait_for_result("slow"))
    try:
        await publish(redis_manager.client, client, "ready")
        assert (await asyncio.wait_for(client.wait_for_result("ready"), 1))[
            "id"
        ] == "ready"
        assert not slow.done()
    finally:
        slow.cancel()
        await asyncio.gather(slow, return_exceptions=True)
    assert await redis_manager.client.get(client.submitted_key("slow")) is not None
    assert not client._result_waiter.pending


async def test_observer_capacity_and_cancellation_preserve_accepted_work(redis_manager):
    client = DatabaseWriteClient(redis_manager, max_queue_commands=2)
    for i in range(3):
        await redis_manager.client.set(client.submitted_key(str(i)), "queued")
    waiting = [asyncio.create_task(client.wait_for_result(str(i))) for i in range(3)]
    await asyncio.sleep(0.02)
    assert len(client._result_waiter.pending) == 2
    waiting[0].cancel()
    await asyncio.gather(waiting[0], return_exceptions=True)
    await publish(redis_manager.client, client, "2")
    assert (await asyncio.wait_for(waiting[2], 1))["id"] == "2"
    waiting[1].cancel()
    await asyncio.gather(waiting[1], return_exceptions=True)
    assert not client._result_waiter.pending
    with pytest.raises(DatabaseWriteTimeout):
        await client.wait_for_result("1", timeout_seconds=0.01)
    assert await redis_manager.client.get(client.submitted_key("1")) is not None
    assert not client._result_waiter.pending


async def test_snapshot_failure_releases_all_observers_and_can_retry(
    redis_manager, monkeypatch
):
    client = DatabaseWriteClient(redis_manager)
    await publish(redis_manager.client, client, "ready")
    from redis.asyncio.client import Pipeline

    execute = Pipeline.execute

    async def failed(self, **kwargs):
        raise ConnectionError("fixture connection interrupted")

    monkeypatch.setattr(Pipeline, "execute", failed)
    results = await asyncio.gather(
        *(client.wait_for_result("ready") for _ in range(5)), return_exceptions=True
    )
    assert all(isinstance(result, DatabaseWriteError) for result in results)
    assert not client._result_waiter.pending
    monkeypatch.setattr(Pipeline, "execute", execute)
    assert (await client.wait_for_result("ready"))["id"] == "ready"


async def test_optional_clock_failure_keeps_committed_result(
    redis_manager, monkeypatch
):
    client = DatabaseWriteClient(redis_manager)
    await publish(redis_manager.client, client, "ready")
    from redis.asyncio.client import Pipeline

    execute = Pipeline.execute

    async def without_clock(self, **kwargs):
        values = await execute(self, **kwargs)
        return values[0], ResponseError("fixture TIME permission denied")

    monkeypatch.setattr(Pipeline, "execute", without_clock)
    result = await client.wait_for_result("ready", include_timing=True)
    assert result["id"] == "ready"
    assert (
        result[WRITE_TIMING_KEY]["writer_result_split_missing_reason"]
        == "observation_timestamp_unavailable"
    )


def test_waiter_poll_interval_defaults_to_5ms_and_is_switchable(monkeypatch):
    monkeypatch.delenv("ULTIMA_DATABASE_WRITE_RESULT_WAITER_POLL_SECONDS", raising=False)
    monkeypatch.delenv("ULTIMA_DATABASE_WRITE_RESULT_POLL_MAX_SECONDS", raising=False)
    assert DatabaseWriteClient(None).result_waiter_poll_seconds == 0.005
    # As before, a smaller fallback cap also bounds the waiter.
    assert DatabaseWriteClient(None, result_poll_max_seconds=0.002).result_waiter_poll_seconds == 0.002
    monkeypatch.setenv("ULTIMA_DATABASE_WRITE_RESULT_WAITER_POLL_SECONDS", "0.025")
    assert DatabaseWriteClient(None).result_waiter_poll_seconds == 0.025
    for bad in ("0", "-1", "nan", "soon"):
        monkeypatch.setenv("ULTIMA_DATABASE_WRITE_RESULT_WAITER_POLL_SECONDS", bad)
        with pytest.raises(ValueError, match="RESULT_WAITER_POLL_SECONDS"):
            DatabaseWriteClient(None)


async def _polls_while_pending(redis_manager, monkeypatch, interval, seconds=0.3):
    redis = redis_manager.client
    client = DatabaseWriteClient(redis_manager, result_waiter_poll_seconds=interval)
    await redis.set(client.submitted_key("slow"), "queued")
    reads = []
    pipeline = redis.pipeline

    def observed(**kwargs):
        inner = pipeline(**kwargs)
        mget = inner.mget

        def counted(keys):
            reads.append(len(keys))
            return mget(keys)

        inner.mget = counted
        return inner

    monkeypatch.setattr(redis, "pipeline", observed)
    waiting = asyncio.create_task(client.wait_for_result("slow"))
    await asyncio.sleep(seconds)
    polls = len(reads)
    await publish(redis, client, "slow")
    result = await asyncio.wait_for(waiting, 1)
    assert result["id"] == "slow" and not client._result_waiter.pending
    return polls


async def test_longer_waiter_interval_reads_redis_less_often(redis_manager, monkeypatch):
    fast = await _polls_while_pending(redis_manager, monkeypatch, 0.005)
    slow = await _polls_while_pending(redis_manager, monkeypatch, 0.025)
    # ~60 polls at 5 ms against ~12 at 25 ms over 0.3 s; bounds allow for
    # scheduler and fixture overhead.
    assert slow <= 0.3 / 0.025 + 3
    assert fast >= 3 * slow


async def test_longer_waiter_interval_delivers_within_one_interval(redis_manager):
    client = DatabaseWriteClient(redis_manager, result_waiter_poll_seconds=0.025)
    await redis_manager.client.set(client.submitted_key("later"), "queued")
    waiting = asyncio.create_task(client.wait_for_result("later"))
    await asyncio.sleep(0.05)
    published = asyncio.get_running_loop().time()
    await publish(redis_manager.client, client, "later")
    assert (await asyncio.wait_for(waiting, 1))["id"] == "later"
    assert asyncio.get_running_loop().time() - published < 0.025 + 0.05
