"""Public job history and retries survive Redis retirement with bounded reads."""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, text
from sqlmodel import Session

import test_mps_manifest as fixtures
import test_normal_durable_inputs as inputs
import test_normal_task_windows as windows
from ultima_scraper_backend.api.routes import jobs, mps_history
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.database import job_history, mps_retry
from ultima_scraper_backend.job_system import JobStorage, mps_state

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


@pytest.fixture(autouse=True)
def public_route_session(window_runtime, store, monkeypatch):
    # Public routes use SQLModel Session.exec, whereas the manifest fixture only
    # requires SQLAlchemy. Keep the actual route/session contract in this suite.
    from ultima_scraper_db_archive import global_db

    with store.session_factory() as session:
        engine = session.get_bind()

    @contextmanager
    def session_factory():
        with Session(engine) as session:
            session.execute(
                text("SET LOCAL search_path = onlyfans, management, public")
            )
            yield session

    monkeypatch.setattr(global_db, "global_session", session_factory)


def app_for(monkeypatch, runtime):
    app = FastAPI()
    app.include_router(jobs.router)
    app.dependency_overrides[jobs.get_backend_instance] = lambda: runtime
    runtime.distributed_mode = False
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    return app


async def complete_job(store, runtime, job_id):
    storage = JobStorage(runtime.redis)
    for _ in range(30):
        plan = store.get(job_id)
        if plan["cursor"] == plan["total"]:
            return
        await mps_durable.advance(runtime, job_id)
        await fixtures.complete_window(storage, job_id)
        await mps_durable.advance(runtime, job_id)
    pytest.fail("Fixture job did not finish")


@pytest.mark.parametrize("redis_available", [True, False])
async def test_public_history_and_headers_survive_actual_retirement(
    store, window_runtime, monkeypatch, redis_available
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    job = await windows.admit(
        window_runtime,
        count=7,
        metadata={"run_count": 4, "last_ran_at": "2026-09-01T00:00:00+00:00"},
    )
    await complete_job(store, window_runtime, job.job_id)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    storage.database_writes = mps_durable.DatabaseWriteClient(window_runtime.redis)
    assert await storage.cleanup_completed_jobs(0, batch_size=1) == 1
    assert not await client.exists(
        storage.JOB_CONFIG_KEY.format(job_id=job.job_id),
        storage.JOB_STATE_KEY.format(job_id=job.job_id),
    )
    backend = (
        window_runtime
        if redis_available
        else SimpleNamespace(redis=None, distributed_mode=False)
    )
    app = app_for(monkeypatch, backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        detail = await http.get(f"/jobs/{job.job_id}")
        assert detail.status_code == 200, detail.text
        assert (
            detail.json()["task_stats"]["total"]
            == detail.json()["task_stats"]["completed"]
            == 7
        )
        assert (
            detail.json()["run_count"] == 4 and detail.json()["status"] == "completed"
        )
        listing = await http.get("/jobs")
        assert listing.status_code == 200, listing.text
        row = next(row for row in listing.json()["jobs"] if row["job_id"] == job.job_id)
        assert row["completed_tasks"] == 7 and row["run_count"] == 4
        offset, received = "0", []
        while offset is not None:
            response = await http.get(
                f"/jobs/{job.job_id}/tasks", params={"cursor": offset, "limit": 2}
            )
            assert response.status_code == 200, response.text
            page = response.json()
            received.extend(page["tasks"])
            offset = page["next_cursor"]
        assert len(received) == 7 and len({row["task_id"] for row in received}) == 7
        assert all(
            row["status"] == "completed"
            and row["payload"] is not None
            and row["result"]["success"]
            for row in received
        )
        inline = await http.get(f"/jobs/{job.job_id}", params={"include_tasks": True})
        assert inline.status_code == 200, inline.text
        assert len(inline.json()["tasks"]) == 7
    assert not await client.exists(
        storage.JOB_CONFIG_KEY.format(job_id=job.job_id),
        storage.JOB_STATE_KEY.format(job_id=job.job_id),
    )


async def test_unmaterialized_definitions_remain_visible_after_redis_loss(
    store, window_runtime, monkeypatch
):
    job = await windows.admit(window_runtime, count=20)
    storage = JobStorage(window_runtime.redis)
    await storage._client().flushdb()
    with store.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.jobs SET last_event_at='2020-01-01', created_at='2020-01-01' WHERE job_id=:job"
            ),
            {"job": job.job_id},
        )
        session.commit()
    app = app_for(monkeypatch, window_runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        page = await http.get(
            f"/jobs/{job.job_id}/tasks", params={"offset": 17, "limit": 3}
        )
        assert page.status_code == 200, page.text
        assert [row["task_id"] for row in page.json()["tasks"]] == [
            inputs.task(i, width=10).task_id for i in range(17, 20)
        ]
        detail = await http.get(f"/jobs/{job.job_id}")
        assert (
            detail.status_code == 200 and detail.json()["status"] == "pending"
        ), detail.text
        listing = await http.get("/jobs")
        assert (
            listing.status_code == 200
            and listing.json()["jobs"][0]["status"] == "pending"
        ), listing.text
    assert (
        await jobs._fetch_job_task_detail(
            job.job_id, inputs.task(19).task_id, window_runtime
        )
    ).payload is not None
    with store.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT status FROM management.jobs WHERE job_id=:job"),
                {"job": job.job_id},
            )
            == "pending"
        )
    assert await storage._client().dbsize() == 0


@pytest.mark.parametrize("source", ["definition", "archive", "runtime"])
async def test_oversized_history_payloads_fail_before_transfer(
    store, window_runtime, monkeypatch, source
):
    tasks = [inputs.task(0, width=20000 if source == "definition" else 10)]
    job = await windows.admit(window_runtime, tasks=tasks)
    storage = JobStorage(window_runtime.redis)
    if source != "definition":
        await mps_durable.advance(window_runtime, job.job_id)
        if source == "archive":
            await fixtures.complete_window(storage, job.job_id)
            await mps_durable.advance(window_runtime, job.job_id)
            with store.session_factory() as session:
                session.execute(
                    text(
                        "UPDATE management.job_tasks SET result_json=:result WHERE job_id=:job"
                    ),
                    {
                        "job": job.job_id,
                        "result": json.dumps(
                            {"success": True, "output": {"marker": "x" * 20000}}
                        ),
                    },
                )
                session.commit()
        else:
            key = storage.TASK_KEY.format(job_id=job.job_id, task_id=tasks[0].task_id)
            raw = json.loads(await storage._client().get(key))
            raw["payload"]["args"]["marker"] = "x" * 20000
            await storage._client().set(key, json.dumps(raw))
    monkeypatch.setenv("ULTIMA_JOB_HISTORY_MAX_BYTES", "4096")
    app = app_for(monkeypatch, window_runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        response = await http.get(f"/jobs/{job.job_id}/tasks", params={"limit": 5})
        assert response.status_code == 413, response.text
    with pytest.raises(Exception) as error:
        await jobs._fetch_job_task_detail(job.job_id, tasks[0].task_id, window_runtime)
    assert error.value.status_code == 413
    assert store.get(job.job_id)["total"] == 1


@pytest.mark.parametrize("reverse", [False, True])
async def test_history_byte_boundaries_do_not_skip_tasks(
    store, window_runtime, monkeypatch, reverse
):
    job = await windows.admit(
        window_runtime, tasks=[inputs.task(i, width=1400) for i in range(9)]
    )
    await complete_job(store, window_runtime, job.job_id)
    storage = JobStorage(window_runtime.redis)
    storage.database_writes = mps_durable.DatabaseWriteClient(window_runtime.redis)
    await storage.cleanup_completed_jobs(0, batch_size=1)
    monkeypatch.setenv("ULTIMA_JOB_HISTORY_MAX_BYTES", "20000")
    monkeypatch.setenv("ULTIMA_JOB_TASK_PAGE_SCAN_MAX_TASKS", "7")
    seen, offset, pages = [], 0, 0
    while True:
        page = await mps_history.task_page(
            storage,
            job.job_id,
            offset=offset,
            limit=7,
            state="completed" if reverse else None,
        )
        pages += 1
        assert 0 < len(page.tasks) < 7
        seen.extend(task.task_id for task in page.tasks)
        if not page.has_more:
            break
        offset = int(page.next_cursor)
    expected = [inputs.task(i).task_id for i in range(9)]
    assert seen == (list(reversed(expected)) if reverse else expected)
    assert pages > 1


async def test_archived_retry_keeps_ordinary_budgets_and_routing(
    store, window_runtime, monkeypatch
):
    tasks = [inputs.task(i, width=10) for i in range(7)]
    for index, task in enumerate(tasks):
        task.capabilities = [f"cap-{index % 2}"]
        task.ip_lock_key = "original-route"
    job = await windows.admit(window_runtime, tasks=tasks)
    await complete_job(store, window_runtime, job.job_id)
    storage = JobStorage(window_runtime.redis)
    storage.database_writes = mps_durable.DatabaseWriteClient(window_runtime.redis)
    await storage.cleanup_completed_jobs(0, batch_size=1)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "2")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "2")
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "5")
    app = app_for(monkeypatch, window_runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        response = await http.post(f"/jobs/{job.job_id}/retry", json={})
    assert response.status_code == 200, response.text
    retry_id = response.json()["job_id"]
    plan = store.get(retry_id)
    while plan["status"] == "preparing":
        await mps_durable.advance(window_runtime, retry_id)
        plan = store.get(retry_id)
    metadata = plan["job_config"]["metadata"]
    assert metadata["durable_job_kind"] == "ordinary"
    assert metadata["dispatch_backend_id"] == window_runtime.instance_id
    assert metadata["required_capabilities"] == ["cap-0", "cap-1"]
    assert metadata["ip_lock_key"] == "original-route"
    assert mps_retry.retry_batch_limits(plan["job_config"])[0] == 2
    assert mps_retry.retry_batch_limits()[0] == 5
    with store.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT job_type FROM management.jobs WHERE job_id=:job"),
                {"job": retry_id},
            )
            == "retry"
        )
    await mps_durable.advance(window_runtime, retry_id)
    client = storage._client()
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=retry_id)) == 2
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 2
    assert not await client.exists(mps_state.LEGACY_MPS_BUDGET_KEY)


async def test_sql_history_sizing_and_payload_read_share_a_snapshot(
    store, window_runtime, monkeypatch
):
    job = await windows.admit(
        window_runtime, tasks=[inputs.task(i, width=1000) for i in range(6)]
    )
    plan = store.get(job.job_id)
    with store.session_factory() as session:
        engine = session.get_bind()
    queries = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if not statement.startswith("SET LOCAL"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        rows = job_history.task_records(
            store.session_factory,
            job.job_id,
            [inputs.task(i).task_id for i in range(6)],
            definition_id=plan["selection"]["task_manifest_id"],
            byte_limit=14000,
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(queries) == 1
    assert 0 < len(rows) < 6 and sum(row.read_bytes for row in rows) <= 14000
    assert all(row.definition is not None for row in rows)


async def test_history_rejects_replacement_during_read(
    store, window_runtime, monkeypatch
):
    job = await windows.admit(window_runtime, count=2)
    original = job_history.task_records

    def replace_after_read(*args, **kwargs):
        rows = original(*args, **kwargs)
        with store.session_factory() as session:
            session.execute(
                text(
                    "UPDATE management.mps_plans SET selection_json=jsonb_set(selection_json::jsonb, '{task_manifest_id}', '\"replacement\"'::jsonb)::text WHERE job_id=:job"
                ),
                {"job": job.job_id},
            )
            session.commit()
        return rows

    monkeypatch.setattr(job_history, "task_records", replace_after_read)
    app = app_for(monkeypatch, window_runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        response = await http.get(f"/jobs/{job.job_id}/tasks")
    assert response.status_code == 409, response.text


async def test_history_does_not_read_another_jobs_task(
    store, window_runtime, monkeypatch
):
    own = await windows.admit(window_runtime, tasks=[inputs.task(0)])
    other = await windows.admit(window_runtime, tasks=[inputs.task(1)])
    await complete_job(store, window_runtime, other.job_id)
    assert (
        await jobs._fetch_job_task_detail(
            own.job_id, inputs.task(1).task_id, window_runtime
        )
        is None
    )


@pytest.mark.parametrize("endpoint", ["/jobs", "/jobs/{job_id}"])
async def test_header_byte_limit_returns_413(
    store, window_runtime, monkeypatch, endpoint
):
    job = await windows.admit(window_runtime, count=1, metadata={"marker": "x" * 10000})
    await JobStorage(window_runtime.redis)._client().flushdb()
    monkeypatch.setenv("ULTIMA_JOB_HISTORY_MAX_BYTES", "4096")
    app = app_for(monkeypatch, window_runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        response = await http.get(endpoint.format(job_id=job.job_id))
    assert response.status_code == 413, response.text


async def test_inline_history_obeys_bytes_for_live_window(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "200000")
    job = await windows.admit(window_runtime, tasks=[inputs.task(0, width=20000)])
    await mps_durable.advance(window_runtime, job.job_id)
    monkeypatch.setenv("ULTIMA_JOB_HISTORY_MAX_BYTES", "4096")
    app = app_for(monkeypatch, window_runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        response = await http.get(f"/jobs/{job.job_id}", params={"include_tasks": True})
    assert response.status_code == 413, response.text
