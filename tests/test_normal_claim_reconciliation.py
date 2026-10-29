"""Ordinary queued work must survive overlap with runtime reconciliation."""


import pytest
import test_normal_task_windows as windows
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.job_system import JobStorage, mps_state
import legacy_redis_runtime as legacy

postgres_engine = windows.postgres_engine
store = windows.store
redis_manager = windows.redis_manager
window_runtime = windows.window_runtime


@pytest.mark.parametrize("blocked_by", ["cancelled", "scheduled", "stale", "removed", "inflight", "missing_plan"])
async def test_unrunnable_claim_does_not_reactivate_or_recreate_a_window(
    store, window_runtime, blocked_by
):
    from ultima_scraper_backend.job_system import mps_attempt

    job = await windows.admit(window_runtime, count=1)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await mps_durable.advance(window_runtime, job.job_id, activate=False)
    [task] = [task async for task in storage.fetch_tasks_stream(job.job_id)]
    plan_key = mps_state.PLAN_KEY.format(job_id=job.job_id)
    state_key = storage.JOB_STATE_KEY.format(job_id=job.job_id)
    await client.hset(plan_key, "activated", 1)
    if blocked_by == "cancelled":
        await client.hset(state_key, "status", "cancelled")
    elif blocked_by == "scheduled":
        await client.hset(state_key, "mps_schedule_pending", 1)
    elif blocked_by == "stale":
        task.mps_task_manifest = "stale-definition"
    elif blocked_by == "removed":
        await client.zrem(storage.TASK_INDEX_KEY.format(job_id=job.job_id), task.task_id)
    elif blocked_by == "inflight":
        assert await legacy.mark_task_started(storage, job.job_id, task.task_id)
    elif blocked_by == "missing_plan":
        await client.delete(plan_key)
    async with mps_durable._schedule_edit_lock(storage, job.job_id):
        with mps_attempt.bind(job, task):
            assert not await legacy.mark_task_started(storage, job.job_id, task.task_id)
    activated = await client.hget(plan_key, "activated")
    assert activated is None if blocked_by == "missing_plan" else activated in ("1", b"1")
