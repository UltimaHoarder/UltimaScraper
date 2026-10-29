"""Completed tasks make room for new work while unrelated tasks remain active."""

import pytest
from sqlalchemy import insert

import test_mps_manifest as fixtures
import test_normal_task_windows as ordinary
from test_mps_graph_retry import clone as clone_retry
from ultima_scraper_backend.api.routes import mps_history
from ultima_scraper_backend.job_system import JobManager, JobStorage, TaskResult, TaskState, mps_state
from ultima_scraper_backend.job_system import durable
from ultima_scraper_backend.job_system.storage import _task_to_central_row
from ultima_scraper_db_archive.global_db import CentralTaskModel
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


async def create_job(store, runtime, producer, count):
    if producer == "ordinary":
        return (await ordinary.admit(runtime, count=count)).job_id
    return fixtures.prepare_runtime_plan(store, count)["job_id"]


async def advance(runtime, job_id):
    if await durable.advance(runtime, job_id):
        await durable.advance(runtime, job_id)


async def finish(storage, job_id, task, *, started=False, success=True):
    if not started:
        assert await legacy.mark_task_started(storage, job_id, task.task_id)
    task.state = TaskState.COMPLETED if success else TaskState.FAILED
    task.result = TaskResult(
        success=success, continue_job_on_failure=True, output={"items_processed": 1}
    )
    await legacy.persist_task_result(storage, job_id, task)
    if success:
        await legacy.mark_task_completed(storage, job_id, task.task_id)
    else:
        await legacy.mark_task_failed(storage, job_id, task.task_id)


@pytest.mark.parametrize("producer", ["ordinary", "mps"])
async def test_first_straggler_does_not_hold_back_the_rest_of_the_job(
    store, window_runtime, producer
):
    job_id = await create_job(store, window_runtime, producer, 17)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    slow = tasks[0]
    assert await legacy.mark_task_started(storage, job_id, slow.task_id)
    completed = set()
    for _ in range(8):
        tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
        ready = [task for task in tasks if task.task_id != slow.task_id]
        assert ready, "The unfinished first task blocked rolling refill"
        for task in ready:
            assert task.task_id not in completed
            await finish(storage, job_id, task)
            completed.add(task.task_id)
        await advance(window_runtime, job_id)
        assert await client.sismember(
            storage.TASKS_INFLIGHT_KEY.format(job_id=job_id), slow.task_id
        )
        assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=job_id)) <= 3
        assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) <= 3
        assert store.get(job_id)["cursor"] == len(completed)
    assert len(completed) == 16
    assert (await storage.get_job_task_stats(job_id))["inflight"] == 1
    await finish(storage, job_id, slow, started=True)
    await advance(window_runtime, job_id)
    assert store.get(job_id)["status"] == "complete"
    assert (await storage.get_job_task_stats(job_id))["completed"] == 17
    assert await client.hmget(mps_state.BUDGET_KEY, "tasks", "bytes") == [b"0", b"0"]


@pytest.mark.parametrize("producer", ["ordinary", "mps"])
async def test_partial_archive_recovers_after_commit_reply_or_redis_loss(
    store, window_runtime, monkeypatch, producer
):
    job_id = await create_job(store, window_runtime, producer, 10)
    storage = JobStorage(window_runtime.redis)
    await advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    await finish(storage, job_id, tasks[-1])

    async def crash(*args, **kwargs):
        raise RuntimeError("injected crash after partial SQL commit")

    with monkeypatch.context() as fault:
        fault.setattr(durable, "_purge_archived_window", crash)
        with pytest.raises(RuntimeError, match="partial SQL commit"):
            await advance(window_runtime, job_id)
    assert store.get(job_id)["cursor"] == 1
    await advance(window_runtime, job_id)
    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "tasks")) == 3
    await storage._client().flushdb()
    await advance(window_runtime, job_id)
    recovered = [task async for task in storage.fetch_tasks_stream(job_id)]
    recovered_ids = {task.task_id for task in recovered}
    assert len(recovered) == 3
    assert tasks[-1].task_id not in recovered_ids
    assert {task.task_id for task in tasks[:-1]} <= recovered_ids
    assert store.get(job_id)["cursor"] == 1


@pytest.mark.parametrize("producer", ["ordinary", "mps"])
async def test_one_finished_task_refills_a_thousand_task_window(
    store, window_runtime, monkeypatch, producer
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1000")
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", str(8 * 1024 * 1024))
    job_id = await create_job(store, window_runtime, producer, 1001)
    storage = JobStorage(window_runtime.redis)
    await advance(window_runtime, job_id)
    before = [task async for task in storage.fetch_tasks_stream(job_id)]
    assert len(before) == 1000
    assert await legacy.mark_task_started(storage, job_id, before[0].task_id)
    await finish(storage, job_id, before[1])
    await advance(window_runtime, job_id)
    after = [task async for task in storage.fetch_tasks_stream(job_id)]
    before_ids = {task.task_id for task in before}
    after_ids = {task.task_id for task in after}
    assert len(after) == 1000 and len(after_ids - before_ids) == 1
    assert before[1].task_id not in after_ids
    assert await storage._client().sismember(
        storage.TASKS_INFLIGHT_KEY.format(job_id=job_id), before[0].task_id
    )
    assert store.get(job_id)["cursor"] == 1


@pytest.mark.parametrize("producer", ["ordinary", "mps"])
async def test_terminal_history_alone_does_not_skip_the_durable_checkpoint(
    store, window_runtime, producer
):
    job_id = await create_job(store, window_runtime, producer, 5)
    storage = JobStorage(window_runtime.redis)
    await advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    await finish(storage, job_id, tasks[-1])
    with store.session_factory() as session:
        session.execute(insert(CentralTaskModel), [_task_to_central_row(tasks[-1], job_id)])
        session.commit()
    assert store.get(job_id)["cursor"] == 0
    await advance(window_runtime, job_id)
    assert store.get(job_id)["cursor"] == 1
    assert tasks[-1].task_id not in await legacy.list_tasks_for_job(storage, job_id)
    assert len(await legacy.list_tasks_for_job(storage, job_id)) == 3


async def test_shared_dependency_output_survives_until_its_last_active_consumer(
    store, window_runtime
):
    slow, parent, first, second, filler = [ordinary.inputs.task(i, width=10) for i in range(5)]
    first.depends_on = second.depends_on = [parent.task_id]
    job = await ordinary.admit(window_runtime, tasks=[slow, parent, first, second, filler])
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await advance(window_runtime, job.job_id)
    assert await legacy.mark_task_started(storage, job.job_id, slow.task_id)
    await finish(storage, job.job_id, parent)
    await advance(window_runtime, job.job_id)
    assert first.task_id in await legacy.list_tasks_for_job(storage, job.job_id)
    await finish(storage, job.job_id, filler)
    await advance(window_runtime, job.job_id)
    assert second.task_id in await legacy.list_tasks_for_job(storage, job.job_id)
    outputs = storage.TASK_OUTPUTS_KEY.format(job_id=job.job_id)
    assert await client.hexists(outputs, parent.task_id)
    await finish(storage, job.job_id, first)
    await advance(window_runtime, job.job_id)
    assert await client.hexists(outputs, parent.task_id)
    await finish(storage, job.job_id, second)
    await advance(window_runtime, job.job_id)
    assert not await client.hexists(outputs, parent.task_id)
    assert await client.sismember(storage.TASKS_INFLIGHT_KEY.format(job_id=job.job_id), slow.task_id)


@pytest.mark.parametrize("failed_only", [False, True])
async def test_range_retry_starts_fresh_after_out_of_order_completion(
    store, window_runtime, failed_only
):
    job_id = await create_job(store, window_runtime, "mps", 5)
    storage = JobStorage(window_runtime.redis)
    await advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    await finish(storage, job_id, tasks[-1], success=not failed_only)
    await advance(window_runtime, job_id)
    assert store.get(job_id)["cursor"] == 1
    retry = clone_retry(store, store.get(job_id))
    await storage._client().flushdb()
    completed = []
    for _ in range(5):
        await advance(window_runtime, retry["job_id"])
        if store.get(retry["job_id"])["status"] == "complete":
            break
        for task in [task async for task in storage.fetch_tasks_stream(retry["job_id"])]:
            completed.append(task.user_id)
            await finish(storage, retry["job_id"], task)
    assert store.get(retry["job_id"])["status"] == "complete"
    assert sorted(completed) == ([tasks[-1].user_id] if failed_only else list(range(1, 6)))


async def test_out_of_order_completion_remains_in_history_without_redis(
    store, window_runtime
):
    job_id = await create_job(store, window_runtime, "mps", 5)
    storage = JobStorage(window_runtime.redis)
    await advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    await finish(storage, job_id, tasks[-1])
    await advance(window_runtime, job_id)
    await storage._client().flushdb()
    page = await mps_history.task_page(None, job_id, offset=0, limit=5, state="completed")
    assert [task.task_id for task in page.tasks] == [tasks[-1].task_id]


@pytest.mark.parametrize("producer", ["ordinary", "mps"])
async def test_byte_limited_refill_still_dispatches_existing_ready_tasks(
    store, window_runtime, monkeypatch, producer
):
    job_id = await create_job(store, window_runtime, producer, 5)
    storage = JobStorage(window_runtime.redis)
    await durable.advance(window_runtime, job_id, activate=False)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    assert await legacy.mark_task_started(storage, job_id, tasks[0].task_id)
    await finish(storage, job_id, tasks[-1])
    assert await durable.advance(window_runtime, job_id, activate=False)
    occupied = int(await storage._client().hget(mps_state.BUDGET_KEY, "bytes"))
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", str(occupied + 1))
    JobManager.activate_materialized_job.reset_mock()
    await durable.advance(window_runtime, job_id)
    JobManager.activate_materialized_job.assert_awaited_once()
    stats = await storage.get_job_task_stats(job_id)
    assert stats["ready"] == 1 and stats["inflight"] == 1
    assert len(await legacy.list_tasks_for_job(storage, job_id)) == 2


async def test_waiting_job_is_not_routed_before_it_can_admit_work(
    store, window_runtime
):
    first = await create_job(store, window_runtime, "mps", 5)
    await advance(window_runtime, first)
    waiting = await create_job(store, window_runtime, "ordinary", 5)
    JobManager.activate_materialized_job.reset_mock()
    await advance(window_runtime, waiting)
    JobManager.activate_materialized_job.assert_not_awaited()
    assert await window_runtime.redis.client.sismember(mps_state.WAITING_SET_KEY, waiting)
