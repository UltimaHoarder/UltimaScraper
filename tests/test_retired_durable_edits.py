"""Normal and MPS durable jobs remain editable after terminal Redis cleanup."""

import httpx
import pytest
from sqlalchemy import text

import test_durable_job_history as history
import test_mps_manifest as manifests
import test_normal_durable_inputs as inputs
import test_normal_task_windows as windows
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import JobManager, JobStorage

postgres_engine = history.postgres_engine
store = history.store
redis_manager = history.redis_manager
window_runtime = history.window_runtime
public_route_session = history.public_route_session


async def retired(store, runtime, *, ordinary):
    if ordinary:
        job = await windows.admit(runtime, count=7)
        job_id = job.job_id
    else:
        job_id = manifests.prepare_runtime_plan(store, 7)["job_id"]
    await history.complete_job(store, runtime, job_id)
    storage = JobStorage(runtime.redis)
    storage.database_writes = runtime.writes
    assert await storage.cleanup_completed_jobs(0, batch_size=1) == 1
    assert not await storage._client().exists(
        storage.JOB_CONFIG_KEY.format(job_id=job_id)
    )
    return job_id, storage


def app_for(monkeypatch, runtime):
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.manager.DatabaseWriteClient",
        type(runtime.writes),
    )
    app = history.app_for(monkeypatch, runtime)
    app.dependency_overrides[jobs.get_backend_manager] = lambda: None
    return app


@pytest.mark.parametrize("ordinary", [True, False])
async def test_rename_after_retirement_preserves_work_and_counters(
    store, window_runtime, monkeypatch, ordinary
):
    job_id, storage = await retired(store, window_runtime, ordinary=ordinary)
    before = store.get(job_id)
    app = app_for(monkeypatch, window_runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        response = await http.patch(
            f"/jobs/{job_id}", json={"job_name": "  Retained rename  "}
        )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["job_name"] == "Retained rename"
    assert result["status"] == "completed"
    assert result["task_count"] == result["completed_tasks"] == 7
    after = store.get(job_id)
    for field in ("selection", "status", "total", "cursor", "completed", "failed"):
        assert after[field] == before[field]
    assert after["job_config"]["metadata"].get("durable_job_kind") == (
        "ordinary" if ordinary else None
    )
    assert (
        await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job_id)) == 0
    )
    with store.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"),
                {"job": job_id},
            )
            == 7
        )
    # Explicit edits may restore the compact header; cleanup can retire it again.
    assert await storage.cleanup_completed_jobs(0, batch_size=1) == 1
    assert store.get(job_id)["job_config"]["name"] == "Retained rename"


@pytest.mark.parametrize("ordinary", [True, False])
async def test_replacement_after_retirement_uses_existing_window_budgets(
    store, window_runtime, monkeypatch, ordinary
):
    job_id, storage = await retired(store, window_runtime, ordinary=ordinary)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "2")
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "3")
    app = app_for(monkeypatch, window_runtime)

    async def build(payload, _manager):
        return inputs.task(payload.params["index"], width=10)

    monkeypatch.setattr(jobs, "_build_task_from_payload", build)
    body = {
        "job_name": "Replacement",
        "tasks": [
            {"task_type": "api_command", "params": {"index": i}} for i in range(11)
        ],
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        response = await http.patch(f"/jobs/{job_id}", json=body)
    assert response.status_code == 200, response.text
    after = store.get(job_id)
    assert after["total"] == 11
    assert after["cursor"] == after["completed"] == after["failed"] == 0
    assert after["job_config"]["metadata"].get("durable_job_kind") == (
        "ordinary" if ordinary else None
    )
    assert await storage._client().zcard(
        storage.TASK_INDEX_KEY.format(job_id=job_id)
    ) == 2
    definition = after["selection"]["task_manifest_id"]
    with store.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.mps_task_definitions WHERE manifest_id=:manifest"
                ),
                {"manifest": definition},
            )
            == 11
        )


@pytest.mark.parametrize("direct", [False, True])
async def test_retained_edit_header_budget_fails_before_mutation(
    store, window_runtime, monkeypatch, direct
):
    job_id, storage = await retired(store, window_runtime, ordinary=True)
    before = store.get(job_id)
    monkeypatch.setenv("ULTIMA_JOB_HISTORY_MAX_BYTES", "128")
    app = app_for(monkeypatch, window_runtime)
    if direct:
        from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded

        with pytest.raises(TaskPayloadBudgetExceeded):
            await JobManager(window_runtime.redis).update_job_by_id(
                job_id, name="Too large"
            )
    else:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as http:
            response = await http.patch(
                f"/jobs/{job_id}", json={"job_name": "Too large"}
            )
        assert response.status_code == 413, response.text
    assert store.get(job_id) == before
    assert not await storage._client().exists(
        storage.JOB_CONFIG_KEY.format(job_id=job_id)
    )


async def test_noop_reads_retained_header_without_rehydrating_redis(
    store, window_runtime, monkeypatch
):
    job_id, storage = await retired(store, window_runtime, ordinary=True)
    app_for(monkeypatch, window_runtime)
    restored = await JobManager(window_runtime.redis).update_job_by_id(job_id)
    assert restored.total_tasks == restored.completed_tasks == 7
    assert not restored.task_ids and not restored.tasks
    assert restored.state.value == "completed"
    assert not await storage._client().exists(
        storage.JOB_CONFIG_KEY.format(job_id=job_id)
    )


async def test_unknown_job_remains_not_found(store, window_runtime, monkeypatch):
    app = app_for(monkeypatch, window_runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        response = await http.patch("/jobs/missing-job", json={"job_name": "Missing"})
    assert response.status_code == 404, response.text


@pytest.mark.parametrize("total", [1_000, 1_000_000])
async def test_edit_lookup_does_not_expand_profile_ranges(
    store, window_runtime, monkeypatch, total
):
    job_id = manifests.prepare_runtime_plan(store, total)["job_id"]
    app_for(monkeypatch, window_runtime)
    manager = JobManager(window_runtime.redis)
    restored = await manager.update_job_by_id(job_id)
    assert restored.total_tasks == total
    assert not restored.tasks and not restored.task_ids
    client = manager.storage._client()
    assert not await client.exists(
        manager.storage.JOB_CONFIG_KEY.format(job_id=job_id),
        manager.storage.TASK_INDEX_KEY.format(job_id=job_id),
    )
    with store.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.mps_candidate_ranges WHERE job_id=:job"
                ),
                {"job": job_id},
            )
            == 1
        )
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"),
                {"job": job_id},
            )
            == 0
        )


async def test_retained_header_read_failure_is_unavailable_without_publication(
    store, window_runtime, monkeypatch
):
    from sqlalchemy.exc import SQLAlchemyError
    from ultima_scraper_backend.database import job_history

    job_id, storage = await retired(store, window_runtime, ordinary=True)
    app = app_for(monkeypatch, window_runtime)

    def unavailable(*_args):
        raise SQLAlchemyError("fixture read failure")

    monkeypatch.setattr(job_history, "headers", unavailable)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        response = await http.patch(f"/jobs/{job_id}", json={"job_name": "Unavailable"})
    assert response.status_code == 503, response.text
    assert not await storage._client().exists(
        storage.JOB_CONFIG_KEY.format(job_id=job_id)
    )
