"""Archive chunks must give already waiting worker finishers their next turn."""

import asyncio
from types import SimpleNamespace

import pytest
import test_mps_throughput_regressions as fixtures
from ultima_scraper_backend.job_system import durable, materializer, mps_attempt, mps_state
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
import legacy_redis_runtime as legacy

redis_manager = fixtures.redis_manager
postgres_engine = fixtures.postgres_engine
store = fixtures.store
window_runtime = fixtures.window_runtime


@pytest.mark.parametrize("blocked", [False, True])
async def test_finish_acquisition_checks_definition_in_one_redis_round_trip(
    redis_manager, monkeypatch, blocked,
):
    storage, job, task = await fixtures._finish_context(redis_manager)
    redis = redis_manager.client
    key = mps_attempt.lock_key(job.job_id)
    if blocked:
        await redis.set(key, "materializer:existing", ex=90)
    attempts = []
    observed = asyncio.Event()
    original_eval = redis.eval

    async def observe(script, *args):
        result = await original_eval(script, *args)
        attempts.append(script)
        if script.endswith(mps_attempt._ACQUIRE_SHARED_FINISH):
            observed.set()
        return result

    async def finish():
        async with mps_attempt.finish_lock(storage, job, task):
            assert len(attempts) == 1, "Definition guards added separate Redis round trips"

    monkeypatch.setattr(redis, "eval", observe)
    worker = asyncio.create_task(finish())
    try:
        if blocked:
            await asyncio.wait_for(observed.wait(), 1)
            assert len(attempts) == 1, "Each blocked retry repeats a separate definition guard"
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker
        else:
            await asyncio.wait_for(worker, 1)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize("finisher_count", [1, 8])
async def test_next_archive_pass_waits_for_workers_blocked_by_previous_pass(
    redis_manager, monkeypatch, finisher_count,
):
    storage, job, task = await fixtures._finish_context(redis_manager)
    redis = redis_manager.client
    key = mps_attempt.lock_key(job.job_id)
    await redis.hset(mps_state.PLAN_KEY.format(job_id=job.job_id), "version", mps_state.PLAN_VERSION)
    await redis.set(key, "materializer:previous", ex=90)
    blocked = set()
    entered = set()
    finished = set()
    all_blocked = asyncio.Event()
    all_entered = asyncio.Event()
    release_workers = asyncio.Event()
    archive_entered = asyncio.Event()
    original_eval = redis.eval

    async def observe_acquisition(script, *args):
        result = await original_eval(script, *args)
        if script.endswith(mps_attempt._ACQUIRE_SHARED_FINISH) and result == 0:
            blocked.add(asyncio.current_task())
            if len(blocked) == finisher_count:
                all_blocked.set()
        return result

    async def finish(index):
        async with mps_attempt.finish_lock(storage, job, task):
            entered.add(index)
            if len(entered) == finisher_count:
                all_entered.set()
            await release_workers.wait()
            finished.add(index)  # Protected terminal bookkeeping completed.

    async def advance(*args, **kwargs):
        assert finished == set(range(finisher_count)), "The next archive pass overtook blocked finishers"
        assert await redis.get(key) == kwargs["lock_owner"].encode()
        archive_entered.set()
        return False

    monkeypatch.setattr(redis, "eval", observe_acquisition)
    monkeypatch.setattr(durable, "advance", advance)
    workers = [asyncio.create_task(finish(index)) for index in range(finisher_count)]
    archive = None
    try:
        await asyncio.wait_for(all_blocked.wait(), 1)
        await redis.delete(key)  # The previous archive has just released its lease.
        archive = asyncio.create_task(materializer._materialize_mps_job(
            SimpleNamespace(redis=redis_manager, instance_id="next"), job.job_id,
        ))
        await asyncio.wait_for(all_entered.wait(), 1)
        assert not archive_entered.is_set()
        release_workers.set()
        assert await asyncio.wait_for(archive, 1) is False
        await asyncio.gather(*workers)
        assert archive_entered.is_set()
        assert not await redis.exists(key, f"{key}:waiting", f"{key}:finishers", f"{key}:finish_waiters")
    finally:
        release_workers.set()
        executions = workers + ([archive] if archive else [])
        for execution in executions:
            execution.cancel()
        await asyncio.gather(*executions, return_exceptions=True)


async def test_cancelling_a_blocked_finisher_removes_only_its_request(redis_manager, monkeypatch):
    storage, job, task = await fixtures._finish_context(redis_manager)
    redis = redis_manager.client
    key = mps_attempt.lock_key(job.job_id)
    waiters = f"{key}:finish_waiters"
    await redis.set(key, "materializer:existing", ex=90)
    blocked = asyncio.Event()
    original_eval = redis.eval

    async def observe_acquisition(script, *args):
        result = await original_eval(script, *args)
        if script.endswith(mps_attempt._ACQUIRE_SHARED_FINISH) and result == 0:
            blocked.set()
        return result

    async def finish():
        async with mps_attempt.finish_lock(storage, job, task):
            pytest.fail("The worker entered an exclusive archive lease")

    monkeypatch.setattr(redis, "eval", observe_acquisition)
    worker = asyncio.create_task(finish())
    try:
        await asyncio.wait_for(blocked.wait(), 1)
        assert await redis.zcard(waiters) == 1
        assert 0 < await redis.ttl(waiters) <= 3
        now = int((await redis.time())[0])
        await redis.zadd(waiters, {"another-worker": now + 3})
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        assert await redis.zrange(waiters, 0, -1) == [b"another-worker"]
        assert await redis.get(key) == b"materializer:existing"
        assert not await redis.exists(f"{key}:waiting", f"{key}:finishers")
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_expired_finisher_requests_cannot_block_refill(redis_manager):
    redis = redis_manager.client
    key = "test:expired-finish-requests"
    now = int((await redis.time())[0])
    await redis.zadd(f"{key}:finish_waiters", {"crashed-worker": now - 1})
    assert await materializer._acquire_mps_materialization_lock(
        redis, lock_key=key, owner="materializer:recovered", wait_seconds=0.05,
    )
    assert await redis.get(key) == b"materializer:recovered"
    assert not await redis.exists(f"{key}:finish_waiters", f"{key}:waiting")


async def test_cancellation_racing_acquisition_reply_releases_its_lease(
    redis_manager, monkeypatch,
):
    storage, job, task = await fixtures._finish_context(redis_manager)
    redis = redis_manager.client
    key = mps_attempt.lock_key(job.job_id)
    original_eval = redis.eval
    acquired = asyncio.Event()

    async def delayed_reply(script, *args):
        result = await original_eval(script, *args)
        if script.endswith(mps_attempt._ACQUIRE_SHARED_FINISH) and result == 1:
            acquired.set()
            await asyncio.Event().wait()  # The reply is interrupted after Redis acquires.
        return result

    async def finish():
        async with mps_attempt.finish_lock(storage, job, task):
            pytest.fail("The cancelled worker entered bookkeeping")

    monkeypatch.setattr(redis, "eval", delayed_reply)
    worker = asyncio.create_task(finish())
    try:
        await asyncio.wait_for(acquired.wait(), 1)
        assert await redis.get(key) == b"mps-finish:active"
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        assert not await redis.exists(key, f"{key}:finishers", f"{key}:finish_waiters")
        assert await materializer._acquire_mps_materialization_lock(
            redis, lock_key=key, owner="materializer:after-cancel", wait_seconds=0.05,
        )
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_cancelled_materializer_releases_an_unobserved_acquisition(
    redis_manager, monkeypatch,
):
    redis = redis_manager.client
    key = "test:cancelled-materializer-acquisition"
    owner = "materializer:cancelled-reply"
    original_eval = redis.eval
    acquired = asyncio.Event()

    async def delayed_reply(script, *args):
        result = await original_eval(script, *args)
        if args[:2] == (3, key) and result == 1:
            acquired.set()
            await asyncio.Event().wait()
        return result

    monkeypatch.setattr(redis, "eval", delayed_reply)
    writer = asyncio.create_task(materializer._acquire_mps_materialization_lock(
        redis, lock_key=key, owner=owner,
    ))
    try:
        await asyncio.wait_for(acquired.wait(), 1)
        assert await redis.get(key) == owner.encode()
        writer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await writer
        assert not await redis.exists(key, f"{key}:waiting")
    finally:
        writer.cancel()
        await asyncio.gather(writer, return_exceptions=True)


async def test_archive_chunks_commit_a_blocked_workers_result_before_next_pass(
    store, window_runtime, monkeypatch,
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "6")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "6")
    monkeypatch.setenv("ULTIMA_JOB_ARCHIVE_BATCH_SIZE", "2")
    windows = fixtures.window_fixtures
    job_id = await windows.create_job(store, window_runtime, "mps", 17)
    storage = fixtures.JobStorage(window_runtime.redis)
    redis = storage._client()
    await windows.advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    job = await storage.fetch_job(job_id, include_tasks=False)
    finishing, slow = tasks[-2:]
    assert await legacy.mark_task_started(storage, job_id, slow.task_id)
    for task in tasks[:-2]:
        await windows.finish(storage, job_id, task)
    key = mps_attempt.lock_key(job_id)
    blocked, committed = asyncio.Event(), asyncio.Event()
    batches = []
    worker = None
    original_eval = redis.eval
    writes = type(window_runtime.writes)
    original_submit = writes.submit

    async def observe_acquisition(script, *args):
        result = await original_eval(script, *args)
        if script.endswith(mps_attempt._ACQUIRE_SHARED_FINISH) and result == 0:
            blocked.set()
        return result

    async def finish():
        async with mps_attempt.finish_lock(storage, job, finishing):
            assert store.get(job_id)["cursor"] == 2
            await windows.finish(storage, job_id, finishing)
            committed.set()

    async def archive_submit(self, operation, payload, **kwargs):
        nonlocal worker
        if operation == DatabaseWriteOperation.ARCHIVE_MPS_WINDOW:
            batches.append([task["task_id"] for task in payload["tasks"]])
            if len(batches) == 1:
                worker = asyncio.create_task(finish())
                await asyncio.wait_for(blocked.wait(), 1)
                assert not committed.is_set()
            else:
                assert committed.is_set(), "An archive chunk overtook the blocked worker"
        return await original_submit(self, operation, payload, **kwargs)

    monkeypatch.setattr(redis, "eval", observe_acquisition)
    monkeypatch.setattr(writes, "submit", archive_submit)
    try:
        assert await materializer._materialize_mps_job(window_runtime, job_id) is True
        # Immediately retry the next chunk, as the real reliable consumer does.
        assert await materializer._materialize_mps_job(window_runtime, job_id) is True
        await asyncio.wait_for(worker, 1)
        assert await materializer._materialize_mps_job(window_runtime, job_id) is False
        assert list(map(len, batches)) == [2, 2, 1]
        archived = {task_id for batch in batches for task_id in batch}
        assert len(archived) == 5
        assert archived == {task.task_id for task in tasks[:-1]}
        plan = store.get(job_id)
        assert (plan["cursor"], plan["completed"], plan["failed"]) == (5, 5, 0)
        assert await redis.sismember(storage.TASKS_INFLIGHT_KEY.format(job_id=job_id), slow.task_id)
        assert await redis.scard(storage.TASKS_READY_KEY.format(job_id=job_id)) == 5
        assert int(await redis.hget(mps_state.BUDGET_KEY, "tasks")) == 6
        assert not await redis.exists(key, f"{key}:waiting", f"{key}:finishers", f"{key}:finish_waiters")
    finally:
        if worker:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
