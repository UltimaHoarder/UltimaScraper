"""Ordinary dependent tasks reach their assigned backend without recovery."""

import json

import pytest
from sqlalchemy import text
import test_normal_task_windows as windows
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.job_system import JobManager, JobStorage
import legacy_redis_runtime as legacy

postgres_engine = windows.postgres_engine
store = windows.store
redis_manager = windows.redis_manager
window_runtime = windows.window_runtime


@pytest.mark.parametrize("distributed", [True, False])
async def test_next_normal_window_routes_to_the_assigned_backend(
    store, window_runtime, monkeypatch, distributed
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    parent = windows.inputs.task(1, width=10)
    child = windows.inputs.task(2, width=10)
    child.depends_on = [parent.task_id]
    job = await windows.admit(window_runtime, tasks=[parent, child])
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    manager = JobManager(window_runtime.redis)
    router = manager.router
    backend_id = "owned-handoff"
    window_runtime.distributed_mode = distributed
    monkeypatch.setattr(
        JobManager, "activate_materialized_job", windows.activate_materialized_job
    )

    await mps_durable.advance(window_runtime, job.job_id, activate=False)
    # The first window is assigned and routed by the normal job claimer.
    await client.hset(
        storage.JOB_STATE_KEY.format(job_id=job.job_id), "backend_id", backend_id
    )
    await legacy.route_job_tasks_to_backend(router, 
        job_id=job.job_id,
        backend_id=backend_id,
        task_items=[(job.job_id, parent.task_id, 0)],
    )
    assert await router.claim_ready_task(backend_id, timeout=1) == (
        job.job_id, parent.task_id
    )
    completed = await windows.fixtures.complete_window(storage, job.job_id)
    assert [task.task_id for task in completed] == [parent.task_id]

    # Committing the parent's evidence releases its window; the next pass
    # admits the child. No worker recovery sweep runs between these steps.
    assert await mps_durable.advance(window_runtime, job.job_id)
    await mps_durable.advance(window_runtime, job.job_id)
    assert await client.sismember(
        storage.TASKS_READY_KEY.format(job_id=job.job_id), child.task_id
    )
    assert await client.zscore(
        router._queue_key(backend_id),
        router._encode_ready_member(job.job_id, child.task_id),
    ) is not None
    assert await router.claim_ready_task(backend_id, timeout=1) == (
        job.job_id, child.task_id
    )
    assert await manager._resolve_backend_assignment(job.job_id) == backend_id
    assert not await client.lrange(router.UNCLAIMED_JOBS_KEY, 0, -1)
    stats = await storage.get_job_task_stats(job.job_id)
    assert stats["total"] == 2 and stats["completed"] == 1
    output = await storage.get_task_output(job.job_id, parent.task_id)
    assert output["items_processed"] == 1
    with store.session_factory() as session:
        result = session.scalar(text(
            "SELECT result_json FROM management.job_tasks "
            "WHERE job_id=:job AND task_id=:task"
        ), {"job": job.job_id, "task": parent.task_id})
    assert json.loads(result)["output"]["items_processed"] == 1
