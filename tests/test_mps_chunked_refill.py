"""Large completion waves must expose replacement work between archive chunks."""

import pytest

import test_job_window_refill as fixtures
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
from ultima_scraper_backend.job_system import Job, JobStorage, durable, materializer, mps_state
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


@pytest.fixture(autouse=True)
def small_archive_chunks(window_runtime, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "6")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "6")
    monkeypatch.setenv("ULTIMA_JOB_ARCHIVE_BATCH_SIZE", "2")


def record_archives(runtime, monkeypatch):
    batches = []
    writes = type(runtime.writes)
    submit = writes.submit

    async def recorded(self, operation, payload, **kwargs):
        if operation == DatabaseWriteOperation.ARCHIVE_MPS_WINDOW:
            batches.append([task["task_id"] for task in payload["tasks"]])
        return await submit(self, operation, payload, **kwargs)

    monkeypatch.setattr(writes, "submit", recorded)
    return batches


@pytest.mark.parametrize("producer", ["mps", "ordinary"])
async def test_refills_between_archive_chunks_without_repeating_active_work(
    store, window_runtime, monkeypatch, producer
):
    job_id = await fixtures.create_job(store, window_runtime, producer, 17)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await fixtures.advance(window_runtime, job_id)
    initial = [task async for task in storage.fetch_tasks_stream(job_id)]
    assert len(initial) == 6
    slow = initial[-1]
    assert await legacy.mark_task_started(storage, job_id, slow.task_id)
    for index, task in enumerate(initial[:-1]):
        await fixtures.finish(storage, job_id, task, success=index != 1)
    batches = record_archives(window_runtime, monkeypatch)
    initial_ids = {task.task_id for task in initial}
    for cursor, more, ready in [(2, True, 2), (4, True, 4), (5, False, 5)]:
        assert await durable.advance(window_runtime, job_id, refill_after_archive=True) is more
        assert store.get(job_id)["cursor"] == cursor
        assert await client.scard(storage.TASKS_READY_KEY.format(job_id=job_id)) == ready
        assert await client.sismember(storage.TASKS_INFLIGHT_KEY.format(job_id=job_id), slow.task_id)
        assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=job_id)) == 6
        assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 6
        stats = await storage.get_job_task_stats(job_id)
        assert (stats["total"], stats["completed"], stats["failed"]) == (17, 4, 1)
    assert list(map(len, batches)) == [2, 2, 1]
    archived = [task_id for batch in batches for task_id in batch]
    assert len(set(archived)) == 5
    assert set(archived) == initial_ids - {slow.task_id}
    after = [task async for task in storage.fetch_tasks_stream(job_id)]
    assert len({task.task_id for task in after} - initial_ids) == 5


async def test_consumer_reoffers_remaining_chunks_after_releasing_lease(
    store, window_runtime
):
    job_id = await fixtures.create_job(store, window_runtime, "mps", 17)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await fixtures.advance(window_runtime, job_id)
    initial = [task async for task in storage.fetch_tasks_stream(job_id)]
    for task in initial:
        await fixtures.finish(storage, job_id, task)
    await client.delete(mps_state.QUEUE_KEY, mps_state.SCHEDULED_KEY)
    await client.lpush(mps_state.PROCESSING_KEY, job_id)
    again = await materializer._materialize_mps_job(window_runtime, job_id)
    assert again is True
    assert not await client.exists(materializer._mps_materialization_lock_key(job_id))
    await mps_state.acknowledge(client, job_id, again=again)
    assert await client.lrange(mps_state.PROCESSING_KEY, 0, -1) == []
    assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [job_id.encode()]
    assert store.get(job_id)["cursor"] == 2
    assert await client.scard(storage.TASKS_READY_KEY.format(job_id=job_id)) == 2


async def test_chunk_recovers_after_sql_commit_before_cache_cleanup(
    store, window_runtime, monkeypatch
):
    job_id = await fixtures.create_job(store, window_runtime, "mps", 17)
    storage = JobStorage(window_runtime.redis)
    await fixtures.advance(window_runtime, job_id)
    initial = [task async for task in storage.fetch_tasks_stream(job_id)]
    for task in initial:
        await fixtures.finish(storage, job_id, task)

    async def crash(*args, **kwargs):
        raise RuntimeError("interrupted chunk cleanup")

    with monkeypatch.context() as fault:
        fault.setattr(durable, "_purge_archived_window", crash)
        with pytest.raises(RuntimeError, match="interrupted chunk cleanup"):
            await durable.advance(window_runtime, job_id, refill_after_archive=True)
    assert store.get(job_id)["cursor"] == 2
    assert len(await legacy.list_tasks_for_job(storage, job_id)) == 6
    for _ in range(4):
        await durable.advance(window_runtime, job_id, refill_after_archive=True)
    assert store.get(job_id)["cursor"] == 6
    after = [task async for task in storage.fetch_tasks_stream(job_id)]
    assert len(after) == 6
    assert not {task.task_id for task in initial}.intersection(task.task_id for task in after)
    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "tasks")) == 6
    await storage._client().flushdb()
    await fixtures.advance(window_runtime, job_id)
    recovered = [task async for task in storage.fetch_tasks_stream(job_id)]
    assert len(recovered) == 6
    assert not {task.task_id for task in initial}.intersection(task.task_id for task in recovered)


async def test_last_window_drains_without_chunk_requeue(store, window_runtime, monkeypatch):
    job_id = await fixtures.create_job(store, window_runtime, "mps", 6)
    storage = JobStorage(window_runtime.redis)
    await fixtures.advance(window_runtime, job_id)
    for task in [task async for task in storage.fetch_tasks_stream(job_id)]:
        await fixtures.finish(storage, job_id, task)
    batches = record_archives(window_runtime, monkeypatch)
    assert await durable.advance(window_runtime, job_id, refill_after_archive=True) is False
    assert list(map(len, batches)) == [6]
    plan = store.get(job_id)
    assert (plan["status"], plan["cursor"], plan["completed"]) == ("complete", 6, 6)
    assert await storage._client().hmget(mps_state.BUDGET_KEY, "tasks", "bytes") == [b"0", b"0"]


@pytest.mark.parametrize("producer", ["mps", "ordinary"])
@pytest.mark.parametrize("unfinished_state", ["ready", "inflight"])
async def test_final_admitted_window_keeps_chunks_while_execution_remains(
    store, window_runtime, monkeypatch, producer, unfinished_state,
):
    job_id = await fixtures.create_job(store, window_runtime, producer, 6)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await fixtures.advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    unfinished = tasks[-1]
    if unfinished_state == "inflight":
        assert await legacy.mark_task_started(storage, job_id, unfinished.task_id)
    for index, task in enumerate(tasks[:-1]):
        await fixtures.finish(storage, job_id, task, success=index != 1)
    batches = record_archives(window_runtime, monkeypatch)

    for cursor, again in [(2, True), (4, True), (5, False)]:
        assert await materializer._materialize_mps_job(window_runtime, job_id) is again
        assert store.get(job_id)["cursor"] == cursor
        assert not await client.exists(materializer._mps_materialization_lock_key(job_id))
        state_key = (storage.TASKS_READY_KEY if unfinished_state == "ready"
                     else storage.TASKS_INFLIGHT_KEY).format(job_id=job_id)
        assert await client.sismember(state_key, unfinished.task_id)
        assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 6 - cursor

    assert list(map(len, batches)) == [2, 2, 1]
    assert len({task_id for batch in batches for task_id in batch}) == 5
    assert (await storage.get_job_task_stats(job_id))["total"] == 6
    await fixtures.finish(storage, job_id, unfinished, started=unfinished_state == "inflight")
    assert await materializer._materialize_mps_job(window_runtime, job_id) is False
    plan = store.get(job_id)
    assert (plan["status"], plan["cursor"], plan["completed"], plan["failed"]) == ("complete", 6, 5, 1)
    assert await client.hmget(mps_state.BUDGET_KEY, "tasks", "bytes") == [b"0", b"0"]


async def test_chunk_yields_released_capacity_to_waiting_job(store, window_runtime):
    first = await fixtures.create_job(store, window_runtime, "mps", 17)
    other = Job.create(name="Waiting range", created_by="tests", tasks=[],
        metadata={"site": "onlyfans", "source": "manual", "mps_manifest": True})
    second = store.create(job_id=other.job_id, site="onlyfans", job_config=other.to_dict(),
        selection={"start_id": 101, "end_id": 117}, proxy_pool=[],
        site_session_factory=store.session_factory)["job_id"]
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await fixtures.advance(window_runtime, first)
    await fixtures.advance(window_runtime, second)
    assert second.encode() in await client.lrange(mps_state.WAITING_KEY, 0, -1)
    for task in [task async for task in storage.fetch_tasks_stream(first)]:
        await fixtures.finish(storage, first, task)
    assert await durable.advance(window_runtime, first, refill_after_archive=True) is True
    assert store.get(first)["cursor"] == 2
    assert await client.scard(storage.TASKS_READY_KEY.format(job_id=first)) == 0
    await fixtures.advance(window_runtime, second)
    assert await client.scard(storage.TASKS_READY_KEY.format(job_id=second)) == 2
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 6
