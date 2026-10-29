"""Refill must progress under continuous completion without rereading active work."""

import asyncio
from unittest.mock import AsyncMock

import pytest

import test_job_window_refill as fixtures
from ultima_scraper_backend.job_system import JobManager, JobStorage, TaskResult, TaskState, durable, materializer, mps_state
from ultima_scraper_backend.job_system.routing import BackendRouter
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


@pytest.mark.parametrize("producer", ["ordinary", "mps"])
async def test_refill_progresses_when_another_task_finishes_between_passes(
    store, window_runtime, producer
):
    job_id = await fixtures.create_job(store, window_runtime, producer, 10)
    storage = JobStorage(window_runtime.redis)
    await fixtures.advance(window_runtime, job_id)
    initial = [task async for task in storage.fetch_tasks_stream(job_id)]
    await fixtures.finish(storage, job_id, initial[-1])
    assert await durable.advance(window_runtime, job_id)
    # Workers keep finishing while the materializer yields its queue slot.
    await fixtures.finish(storage, job_id, initial[-2])
    await durable.advance(window_runtime, job_id)
    resident = set(await legacy.list_tasks_for_job(storage, job_id))
    assert resident - {task.task_id for task in initial}, "Completions postponed refill again"
    assert len(resident) <= 3


@pytest.mark.parametrize("producer", ["ordinary", "mps"])
async def test_archiving_one_completion_does_not_load_the_other_999_tasks(
    store, window_runtime, monkeypatch, producer
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1000")
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", str(8 * 1024 * 1024))
    job_id = await fixtures.create_job(store, window_runtime, producer, 1001)
    storage = JobStorage(window_runtime.redis)
    await fixtures.advance(window_runtime, job_id)
    initial = [task async for task in storage.fetch_tasks_stream(job_id)]
    await fixtures.finish(storage, job_id, initial[-1])
    loaded = []
    fetch = JobStorage.fetch_tasks_by_ids

    async def observe(self, requested_job, task_ids):
        if requested_job == job_id:
            loaded.extend(task_ids)
        return await fetch(self, requested_job, task_ids)

    monkeypatch.setattr(JobStorage, "fetch_tasks_by_ids", observe)
    assert await durable.advance(window_runtime, job_id)
    assert loaded == [initial[-1].task_id]
    assert store.get(job_id)["cursor"] == 1


@pytest.mark.parametrize("producer", ["ordinary", "mps"])
async def test_terminal_result_waits_for_worker_completion_before_archival(
    store, window_runtime, producer
):
    job_id = await fixtures.create_job(store, window_runtime, producer, 5)
    storage = JobStorage(window_runtime.redis)
    await fixtures.advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    finishing = tasks[0]
    assert await legacy.mark_task_started(storage, job_id, finishing.task_id)
    finishing.state = TaskState.COMPLETED
    finishing.result = TaskResult(success=True, output={"items_processed": 1})
    await legacy.persist_task_result(storage, job_id, finishing)
    await fixtures.finish(storage, job_id, tasks[-1])

    assert await durable.advance(window_runtime, job_id)
    assert store.get(job_id)["cursor"] == 1
    assert await storage.fetch_task(job_id, finishing.task_id) is not None
    assert await storage._client().sismember(
        storage.TASKS_INFLIGHT_KEY.format(job_id=job_id), finishing.task_id
    )


@pytest.mark.parametrize("producer", ["ordinary", "mps"])
async def test_refill_does_not_requeue_a_task_already_claimed_by_a_worker(
    store, window_runtime, monkeypatch, producer
):
    monkeypatch.setattr(JobManager, "activate_materialized_job", fixtures.ordinary.activate_materialized_job)
    monkeypatch.setattr(JobManager, "_resolve_backend_assignment", AsyncMock(return_value=window_runtime.instance_id))
    job_id = await fixtures.create_job(store, window_runtime, producer, 5)
    storage = JobStorage(window_runtime.redis)
    router = BackendRouter(window_runtime.redis)
    await fixtures.advance(window_runtime, job_id)
    claimed = await router.claim_ready_task(window_runtime.instance_id, timeout=1)
    finished = await router.claim_ready_task(window_runtime.instance_id, timeout=1)
    assert claimed is not None and finished is not None
    task = await storage.fetch_task(*finished)
    await fixtures.finish(storage, job_id, task)
    # The first worker has popped its task and is still doing setup before
    # mark_task_started removes it from the per-job ready set.
    await fixtures.advance(window_runtime, job_id)
    queued = await storage._client().zrange(router.QUEUE_PREFIX + window_runtime.instance_id, 0, -1)
    assert (job_id + ":" + claimed[1]).encode() not in queued
    assert len(queued) == 2


@pytest.mark.parametrize("capacity", [1, 3])
async def test_successful_materializer_rechecks_completion_after_releasing_its_slot(
    window_runtime, monkeypatch, capacity
):
    client = window_runtime.redis.client
    storage = JobStorage(window_runtime.redis)
    job_id = "job-wakeup-race"
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", str(capacity))
    await client.hset(storage.JOB_STATE_KEY.format(job_id=job_id), mapping={
        "mps_manifest": 1, "status": "running", "rolling_window": 1, "mps_window_end": 1,
    })
    await client.sadd(storage.TASKS_COMPLETED_KEY.format(job_id=job_id), "done")
    await mps_state.schedule(client, job_id)
    monkeypatch.setattr(materializer, "_recover_stale_mps_materializations", AsyncMock(return_value=0))
    monkeypatch.setattr(durable, "recover", AsyncMock(return_value=""))
    resumed = asyncio.Event()
    calls = 0

    async def advance_with_competing_consumer(backend, requested):
        nonlocal calls
        calls += 1
        if calls > 1:
            resumed.set()
            return False
        await mps_state.notify_complete(storage, job_id)
        if await client.rpoplpush(mps_state.QUEUE_KEY, mps_state.PROCESSING_KEY):
            # Another consumer saw the still-held lease and discarded its
            # duplicate notification. The successful owner must reoffer it.
            await client.srem(mps_state.SCHEDULED_KEY, job_id)
            await mps_state.acknowledge(client, job_id)
        return False

    monkeypatch.setattr(materializer, "_materialize_mps_job", advance_with_competing_consumer)
    loop = asyncio.create_task(materializer._mps_materialization_loop(window_runtime))
    try:
        await asyncio.wait_for(resumed.wait(), 1)
    finally:
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)


@pytest.mark.parametrize("trigger", ["low_backlog", "half_complete"])
async def test_completions_are_coalesced_while_workers_have_a_ready_backlog(
    window_runtime, trigger
):
    client = window_runtime.redis.client
    storage = JobStorage(window_runtime.redis)
    job_id = "job-prefetch"
    await client.hset(storage.JOB_STATE_KEY.format(job_id=job_id), mapping={
        "mps_manifest": 1, "status": "running", "rolling_window": 1, "mps_window_end": 1000,
    })
    await client.sadd(storage.TASKS_COMPLETED_KEY.format(job_id=job_id), "done")
    await client.sadd(storage.TASKS_READY_KEY.format(job_id=job_id), *(f"ready-{i}" for i in range(943)))
    await client.sadd(storage.TASKS_INFLIGHT_KEY.format(job_id=job_id), *(f"active-{i}" for i in range(56)))
    await mps_state.notify_complete(storage, job_id)
    assert not await client.llen(mps_state.QUEUE_KEY)
    await client.delete(storage.TASKS_READY_KEY.format(job_id=job_id))
    ready_count = 56 if trigger == "low_backlog" else 444
    await client.sadd(storage.TASKS_READY_KEY.format(job_id=job_id), *(f"ready-{i}" for i in range(ready_count)))
    if trigger == "half_complete":
        await client.sadd(storage.TASKS_COMPLETED_KEY.format(job_id=job_id), *(f"done-{i}" for i in range(499)))
    await mps_state.notify_complete(storage, job_id)
    assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [job_id.encode()]
