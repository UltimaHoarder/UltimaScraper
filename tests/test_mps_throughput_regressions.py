"""Delivery and refill regressions exposed by the completed MPS benchmark."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import test_database_write_queue as fixtures
import test_job_window_refill as window_fixtures
from ultima_scraper_backend.database import write_queue
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteClient, DatabaseWriteOperation, DatabaseWriteResult, WRITE_TIMING_KEY,
)
from ultima_scraper_backend.job_system import JobStorage, durable, materializer, mps_attempt, mps_state
import legacy_redis_runtime as legacy

redis_manager = fixtures.redis_manager
postgres_engine = window_fixtures.postgres_engine
store = window_fixtures.store
window_runtime = window_fixtures.window_runtime


async def test_publication_between_result_poll_and_marker_check_uses_cache(
    redis_manager, monkeypatch,
):
    client = DatabaseWriteClient(redis_manager)
    command_id = await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS, {"job_id": "delivery-race"},
    )
    redis = redis_manager.client
    original_pipeline = redis.pipeline
    reads = []
    cached = DatabaseWriteResult(
        command_id=command_id, success=True, payload={"committed": True},
        error=None, completed_at=write_queue._utc_now(),
    )

    def pipeline(*args, transaction=True, **kwargs):
        pipe = original_pipeline(*args, transaction=transaction, **kwargs)
        if transaction:
            return pipe
        # The result waiter reads result, availability and submitted state in
        # one non-transactional MGET snapshot.
        original_execute = pipe.execute

        async def publish_after_first_read(*execute_args, **execute_kwargs):
            result = await original_execute(*execute_args, **execute_kwargs)
            reads.append(result)
            if len(reads) == 1:
                # The writer publishes and acknowledges immediately after the
                # producer's first Redis read. Its next read must use the cache.
                async with original_pipeline(transaction=True) as publish:
                    publish.set(client.result_key(command_id), cached.to_json())
                    publish.set(client.result_available_key(command_id), 1)
                    publish.delete(client.submitted_key(command_id))
                    await publish.execute()
            return result

        pipe.execute = publish_after_first_read
        return pipe

    def unexpected_receipt_lookup(command_id):
        pytest.fail("A concurrent cache publication caused a SQL receipt fallback")

    monkeypatch.setattr(redis, "pipeline", pipeline)
    monkeypatch.setattr(write_queue, "_lookup_write_receipt", unexpected_receipt_lookup)
    result = await client.wait_for_result(command_id, timeout_seconds=1, include_timing=True)
    assert result["committed"] is True
    assert result[WRITE_TIMING_KEY]["writer_result_source"] == "cache"
    assert len(reads) == 2


async def _finish_context(redis_manager):
    storage = JobStorage(redis_manager)
    job = SimpleNamespace(job_id="refill-handoff", metadata={"mps_manifest": True})
    task = SimpleNamespace(mps_task_manifest="definition-one")
    await redis_manager.client.hset(
        storage.JOB_STATE_KEY.format(job_id=job.job_id),
        mapping={"mps_manifest": 1, "mps_task_manifest": task.mps_task_manifest,
                 "status": "running"},
    )
    return storage, job, task


async def _wait_for_waiter(redis, key, execution):
    async with asyncio.timeout(1):
        while not await redis.exists(key):
            if execution.done():
                execution.result()
                pytest.fail("Materializer returned before registering its handoff")
            await asyncio.sleep(0.001)


async def test_refill_gets_a_turn_before_new_finishers_join(redis_manager, monkeypatch):
    storage, job, task = await _finish_context(redis_manager)
    redis = redis_manager.client
    key = mps_attempt.lock_key(job.job_id)
    waiter_key = f"{key}:waiting"
    first_entered, release_first, refill_entered, release_refill, late_entered = (
        asyncio.Event() for _ in range(5)
    )

    async def first():
        async with mps_attempt.finish_lock(storage, job, task):
            first_entered.set()
            await release_first.wait()

    async def late():
        async with mps_attempt.finish_lock(storage, job, task):
            late_entered.set()

    async def advance(backend, job_id, **kwargs):
        assert job_id == job.job_id
        assert await redis.get(key) == kwargs["lock_owner"].encode()
        assert not late_entered.is_set()
        refill_entered.set()
        await release_refill.wait()
        return False

    monkeypatch.setattr(durable, "advance", advance)
    first_task = asyncio.create_task(first())
    writer = late_task = None
    try:
        await asyncio.wait_for(first_entered.wait(), 1)
        writer = asyncio.create_task(materializer._materialize_mps_job(
            SimpleNamespace(redis=redis_manager, instance_id="test"), job.job_id,
        ))
        await _wait_for_waiter(redis, waiter_key, writer)
        late_task = asyncio.create_task(late())
        await asyncio.sleep(0.02)
        assert not late_entered.is_set()
        release_first.set()
        await asyncio.wait_for(refill_entered.wait(), 1)
        assert not late_entered.is_set()
        release_refill.set()
        assert await asyncio.wait_for(writer, 1) is False
        await asyncio.wait_for(late_entered.wait(), 1)
        await asyncio.gather(first_task, late_task)
        assert not await redis.exists(key, waiter_key, f"{key}:finishers")
    finally:
        release_first.set()
        release_refill.set()
        tasks = [execution for execution in (first_task, writer, late_task) if execution]
        for execution in tasks:
            execution.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_cancelled_refill_releases_only_its_waiter(redis_manager, monkeypatch):
    storage, job, task = await _finish_context(redis_manager)
    redis = redis_manager.client
    key = mps_attempt.lock_key(job.job_id)
    writer = None
    monkeypatch.setattr(durable, "advance", AsyncMock())
    async with mps_attempt.finish_lock(storage, job, task):
        try:
            writer = asyncio.create_task(materializer._materialize_mps_job(
                SimpleNamespace(redis=redis_manager, instance_id="test"), job.job_id,
            ))
            await _wait_for_waiter(redis, f"{key}:waiting", writer)
            writer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await writer
            assert not await redis.exists(f"{key}:waiting")
            assert await redis.get(key) == b"mps-finish:active"
            assert await redis.zcard(f"{key}:finishers") == 1
        finally:
            if writer:
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)


async def test_refill_handoff_times_out_without_releasing_active_finisher(redis_manager):
    storage, job, task = await _finish_context(redis_manager)
    redis = redis_manager.client
    key = mps_attempt.lock_key(job.job_id)
    async with mps_attempt.finish_lock(storage, job, task):
        assert not await materializer._acquire_mps_materialization_lock(
            redis, lock_key=key, owner="materializer:bounded", wait_seconds=0.01,
        )
        assert await redis.get(key) == b"mps-finish:active"
        assert not await redis.exists(f"{key}:waiting")
        # A failed handoff immediately restores concurrent finishing.
        async with mps_attempt.finish_lock(storage, job, task):
            assert await redis.zcard(f"{key}:finishers") == 2


async def test_refill_handoff_preserves_replacement_waiter(redis_manager):
    storage, job, task = await _finish_context(redis_manager)
    redis = redis_manager.client
    key = mps_attempt.lock_key(job.job_id)
    writer = None
    async with mps_attempt.finish_lock(storage, job, task):
        try:
            writer = asyncio.create_task(materializer._acquire_mps_materialization_lock(
                redis, lock_key=key, owner="materializer:original",
            ))
            await _wait_for_waiter(redis, f"{key}:waiting", writer)
            assert 0 < await redis.ttl(f"{key}:waiting") <= 3
            await redis.set(f"{key}:waiting", "materializer:replacement", ex=3)
            assert not await asyncio.wait_for(writer, 1)
            assert await redis.get(f"{key}:waiting") == b"materializer:replacement"
            assert await redis.get(key) == b"mps-finish:active"
        finally:
            if writer:
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)


async def test_refill_does_not_wait_for_an_exclusive_owner(redis_manager):
    redis = redis_manager.client
    key = "test:refill:exclusive"
    await redis.set(key, "mps-edit:existing", ex=90)
    assert not await materializer._acquire_mps_materialization_lock(
        redis, lock_key=key, owner="materializer:new",
    )
    assert await redis.get(key) == b"mps-edit:existing"
    assert not await redis.exists(f"{key}:waiting")


@pytest.mark.parametrize("capacity", [1, 3])
async def test_completion_queues_refill_during_shared_finish_without_duplicates(
    redis_manager, monkeypatch, capacity,
):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", str(capacity))
    storage, job, task = await _finish_context(redis_manager)
    redis = redis_manager.client
    plan = mps_state.PLAN_KEY.format(job_id=job.job_id)
    await redis.hset(plan, "version", mps_state.PLAN_VERSION)
    await redis.hset(storage.JOB_STATE_KEY.format(job_id=job.job_id), mapping={
        "rolling_window": 1, "mps_window_end": 10, "completed_tasks": 1,
    })
    await redis.sadd(storage.TASKS_COMPLETED_KEY.format(job_id=job.job_id), "finished")
    await redis.sadd(storage.TASKS_READY_KEY.format(job_id=job.job_id), "ready-1", "ready-2")
    await redis.sadd(storage.TASKS_INFLIGHT_KEY.format(job_id=job.job_id), *(
        f"active-{index}" for index in range(7)
    ))

    async with mps_attempt.finish_lock(storage, job, task):
        async with mps_attempt.finish_lock(storage, job, task):
            await asyncio.gather(*(mps_state.notify_complete(storage, job.job_id) for _ in range(100)))
            assert await redis.lrange(mps_state.QUEUE_KEY, 0, -1) == [job.job_id.encode()]
            assert await redis.hget(plan, "refill_cycle") == b"1"
            assert await redis.hget(plan, "notification_pending") is None
            assert await redis.get(mps_attempt.lock_key(job.job_id)) == b"mps-finish:active"

            # Once a consumer has dequeued it, arrivals coalesce even before
            # the shared-to-exclusive handoff has acquired the archive lease.
            assert await redis.rpoplpush(mps_state.QUEUE_KEY, mps_state.PROCESSING_KEY) == job.job_id.encode()
            await redis.srem(mps_state.SCHEDULED_KEY, job.job_id)
            await asyncio.gather(*(mps_state.notify_complete(storage, job.job_id) for _ in range(100)))
            assert await redis.llen(mps_state.QUEUE_KEY) == 0
            assert await redis.llen(mps_state.PROCESSING_KEY) == 1
            assert await redis.hget(plan, "refill_cycle") == b"1"
            assert await redis.hget(plan, "notification_pending") == b"1"
            if capacity == 1:
                assert not await mps_state.schedule(redis, "other-job")
            await mps_state.acknowledge(redis, job.job_id)
            assert await redis.lrange(mps_state.QUEUE_KEY, 0, -1) == [job.job_id.encode()]
            assert await redis.llen(mps_state.PROCESSING_KEY) == 0
            assert await redis.hget(plan, "notification_pending") is None

    assert await redis.llen(mps_state.QUEUE_KEY) == 1


async def test_handoff_refills_without_waiting_for_the_active_window_to_drain(
    store, window_runtime,
):
    job_id = await window_fixtures.create_job(store, window_runtime, "mps", 10)
    storage = JobStorage(window_runtime.redis)
    redis = storage._client()
    await window_fixtures.advance(window_runtime, job_id)
    # The first window has been published; only a worker completion can now
    # produce the notification that starts the consumer's next refill pass.
    await redis.delete(mps_state.QUEUE_KEY, mps_state.SCHEDULED_KEY)
    initial = [task async for task in storage.fetch_tasks_stream(job_id)]
    job = await storage.fetch_job(job_id, include_tasks=False)
    finishing, late, slow = initial
    assert await legacy.mark_task_started(storage, job_id, slow.task_id)
    key = mps_attempt.lock_key(job_id)
    writer = late_worker = None
    late_entered = asyncio.Event()

    async def finish_later():
        async with mps_attempt.finish_lock(storage, job, late):
            # The committed checkpoint and replacement must be visible before
            # this worker can enter the next completion wave.
            assert store.get(job_id)["cursor"] == 1
            resident = set(await legacy.list_tasks_for_job(storage, job_id))
            assert resident - {task.task_id for task in initial}
            assert len(resident) == 3
            late_entered.set()
            await window_fixtures.finish(storage, job_id, late)

    try:
        async with mps_attempt.finish_lock(storage, job, finishing):
            await window_fixtures.finish(storage, job_id, finishing)
            assert await redis.rpoplpush(mps_state.QUEUE_KEY, mps_state.PROCESSING_KEY) == job_id.encode()
            await redis.srem(mps_state.SCHEDULED_KEY, job_id)
            writer = asyncio.create_task(materializer._materialize_mps_job(window_runtime, job_id))
            await _wait_for_waiter(redis, f"{key}:waiting", writer)
            late_worker = asyncio.create_task(finish_later())
            await asyncio.sleep(0.02)
            assert not late_entered.is_set()
        await asyncio.wait_for(writer, 3)
        await asyncio.wait_for(late_worker, 1)
        assert await redis.sismember(storage.TASKS_INFLIGHT_KEY.format(job_id=job_id), slow.task_id)
        assert not await redis.exists(key, f"{key}:waiting", f"{key}:finishers")
    finally:
        executions = [execution for execution in (writer, late_worker) if execution]
        for execution in executions:
            execution.cancel()
        await asyncio.gather(*executions, return_exceptions=True)
        await mps_state.acknowledge(redis, job_id)
