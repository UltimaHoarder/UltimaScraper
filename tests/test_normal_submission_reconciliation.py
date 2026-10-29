"""An accepted ordinary job survives concurrent background publication."""

import asyncio

import httpx
import pytest
from sqlalchemy import text

import test_normal_create_inputs as creation
import test_normal_task_windows as windows
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import materializer as mps
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.job_system import JobManager, JobStorage, mps_state

postgres_engine = windows.postgres_engine
store = windows.store
redis_manager = windows.redis_manager
window_runtime = windows.window_runtime


@pytest.mark.parametrize("publisher_interrupted", [False, True])
async def test_http_creation_survives_reconciliation_owning_publication(
    store, window_runtime, monkeypatch, publisher_interrupted
):
    app = creation.app_for(monkeypatch, window_runtime)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    entered, release = asyncio.Event(), asyncio.Event()
    original_ensure = mps_durable.ensure_job
    original_activate = JobManager.activate_job
    recovery = None
    accepted_id = None

    async def pause_publication(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original_ensure(*args, **kwargs)

    async def overlap(self, job, **kwargs):
        nonlocal recovery, accepted_id
        accepted_id = job.job_id
        assert store.get(job.job_id) is not None
        recovery = asyncio.create_task(mps_durable.recover(window_runtime))
        await asyncio.wait_for(entered.wait(), 3)
        return await original_activate(self, job, **kwargs)

    monkeypatch.setattr(mps_durable, "ensure_job", pause_publication)
    monkeypatch.setattr(JobManager, "activate_job", overlap)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture",
            headers={"Content-Type": "application/json"},
        ) as connection:
            response = await connection.post("/jobs", content=creation.body_rows(1))
        assert response.status_code == 200, response.text
        assert response.json()["job_id"] == accepted_id
        assert response.json()["task_count"] == 1
        jobs.publish_ws_event.assert_awaited_once()
        # The competing owner has not published a header yet. A premature queue
        # hint would make the consumer interpret this as a missing runtime plan.
        assert not await client.exists(storage.JOB_CONFIG_KEY.format(job_id=accepted_id))
        assert not await client.exists(mps_state.QUEUE_KEY)
    finally:
        if recovery is not None:
            if publisher_interrupted:
                recovery.cancel()
            release.set()
            outcomes = await asyncio.wait_for(asyncio.gather(recovery, return_exceptions=True), 3)
            if publisher_interrupted:
                assert isinstance(outcomes[0], asyncio.CancelledError)
            else:
                assert outcomes == [""]

    if publisher_interrupted:
        assert not await client.exists(storage.JOB_CONFIG_KEY.format(job_id=accepted_id))
        await mps_durable.recover(window_runtime)
    assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [accepted_id.encode()]
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.jobs")) == 1
    await mps._materialize_mps_job(window_runtime, accepted_id)
    tasks = await windows.fixtures.complete_window(storage, accepted_id)
    assert len(tasks) == 1
    await mps._materialize_mps_job(window_runtime, accepted_id)
    assert store.get(accepted_id)["completed"] == 1
    assert (await storage.fetch_job(accepted_id, include_tasks=False)).state.value == "completed"
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 0


async def test_unrelated_publication_failure_is_not_acknowledged(
    store, window_runtime, monkeypatch
):
    app = creation.app_for(monkeypatch, window_runtime)

    async def failed(*args, **kwargs):
        raise RuntimeError("Fixture publication failure")

    monkeypatch.setattr(mps_durable, "ensure_plan", failed)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture",
        headers={"Content-Type": "application/json"},
    ) as connection:
        response = await connection.post("/jobs", content=creation.body_rows(1))
    assert response.status_code == 500
    assert "Fixture publication failure" in response.json()["detail"]
    jobs.publish_ws_event.assert_not_awaited()
    assert not await window_runtime.redis.client.exists(mps_state.QUEUE_KEY)


async def test_nonordinary_activation_keeps_its_publication_conflict(
    store, window_runtime
):
    from ultima_scraper_backend.job_system import Job

    plan = windows.fixtures.prepare_runtime_plan(store, 1)
    storage = JobStorage(window_runtime.redis)
    async with mps_durable._schedule_edit_lock(storage, plan["job_id"]):
        with pytest.raises(RuntimeError, match="is materializing"):
            await JobManager(window_runtime.redis).activate_job(
                Job.from_dict(plan["job_config"]), distributed_mode=True
            )
    assert not await storage._client().exists(mps_state.QUEUE_KEY)
