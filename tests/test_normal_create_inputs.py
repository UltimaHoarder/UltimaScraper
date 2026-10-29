"""Ordinary HTTP creation stages inputs and resolves the complete graph in SQL."""

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import event, text
from starlette.requests import Request

import test_mps_manifest as fixtures
import test_normal_durable_inputs as inputs
from ultima_scraper_api import ContentType
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.job_system import Job, JobStorage, TaskType, job_builder, task_inputs

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


def app_for(monkeypatch, runtime):
    app = FastAPI()
    app.include_router(jobs.router)
    app.dependency_overrides[jobs.get_backend_instance] = lambda: runtime
    app.dependency_overrides[jobs.get_backend_manager] = lambda: SimpleNamespace()
    runtime.distributed_mode = False
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    monkeypatch.setattr(job_builder, "create_usr_database_manager", lambda **kwargs: SimpleNamespace(disconnect=lambda: None))

    async def build(payload, manager, **kwargs):
        if payload.params.get("reject"):
            raise HTTPException(400, "Fixture input cannot be built")
        if payload.task_type == "refresh_subscriptions":
            return None
        return inputs.task(payload.params["index"], width=0).model_copy(update={
            "payload": {"command": "fixture", "args": {"marker": payload.params.get("marker", "x")}}
        })

    monkeypatch.setattr(jobs, "_build_task_from_payload", build)
    return app


async def body_rows(count, *, marker="é" * 500, invalid=False):
    yield b'{"job_name":"Streamed creation","created_by":"fixture","tasks":['
    for index in range(count):
        row = {"task_type": "api_command", "params": {"index": index, "marker": marker}}
        if invalid and index == count - 1:
            row.pop("task_type")
        yield (b"," if index else b"") + json.dumps(row, ensure_ascii=False).encode()
    yield b"]}"


def definitions(store, job_id):
    plan = store.get(job_id)
    with store.session_factory() as session:
        return [json.loads(raw) for raw in session.execute(text(
            "SELECT task_json FROM management.mps_task_definitions WHERE manifest_id=:manifest ORDER BY ordinal"
        ), {"manifest": plan["selection"]["task_manifest_id"]}).scalars()]


@pytest.mark.parametrize("count", [7, 1000])
async def test_http_creation_never_builds_a_full_task_list(store, window_runtime, monkeypatch, count):
    app = app_for(monkeypatch, window_runtime)
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "8")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_MAX_BYTES", "32768")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_BATCH_SIZE", "3")
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")

    def forbidden(*args, **kwargs):
        pytest.fail("Ordinary creation must not materialize its full body or task list")

    monkeypatch.setattr(Request, "body", forbidden)
    monkeypatch.setattr(Request, "json", forbidden)
    monkeypatch.setattr(jobs, "build_job", forbidden)
    batches = []
    original = task_inputs.StagedTaskInputs.batches

    def capture(self):
        for batch in original(self):
            assert len(batch) <= 8
            batches.append(len(batch))
            yield batch

    monkeypatch.setattr(task_inputs.StagedTaskInputs, "batches", capture)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture", headers={"Content-Type": "application/json"}) as client:
        response = await client.post("/jobs", content=body_rows(count))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["task_count"] == count
    assert sum(batches) == count
    rows = definitions(store, result["job_id"])
    assert len(rows) == count
    assert [row["payload"]["args"]["marker"] for row in rows] == ["é" * 500] * count
    assert all(row["result"] is None and row["state"] == "pending" for row in rows)
    storage = JobStorage(window_runtime.redis)
    assert await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=result["job_id"])) == 0
    await mps_durable.advance(window_runtime, result["job_id"])
    assert await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=result["job_id"])) == 2
    schema = app.openapi()["paths"]["/jobs"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert "tasks" in schema["required"] and schema["properties"]["tasks"]["type"] == "array"


@pytest.mark.parametrize("kind,code", [("invalid", 422), ("missing", 422), ("null", 422), ("empty", 400), ("oversize", 413), ("factory", 400), ("refresh", 400)])
async def test_bad_creation_input_never_publishes_a_partial_job(store, window_runtime, monkeypatch, kind, code):
    app = app_for(monkeypatch, window_runtime)
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "1")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_MAX_BYTES", "2000")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_BATCH_SIZE", "2")
    kwargs = {"content": body_rows(7, marker="tiny", invalid=True)}
    if kind in {"missing", "null", "empty", "factory", "refresh"}:
        value = {"job_name": "Bad input", "created_by": "fixture"}
        if kind != "missing":
            value["tasks"] = None if kind == "null" else []
        if kind == "factory":
            value["tasks"] = [{"task_type": "api_command", "params": {"reject": True}}]
        if kind == "refresh":
            value["tasks"] = [{"task_type": "refresh_subscriptions", "params": {}}]
        kwargs = {"json": value}
    elif kind == "oversize":
        kwargs = {"content": body_rows(7, marker="x" * 3000)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture", headers={"Content-Type": "application/json"}) as client:
        response = await client.post("/jobs", **kwargs)
    assert response.status_code == code, response.text
    if kind == "refresh":
        assert "No active auth accounts" in response.text
    with store.session_factory() as session:
        for table in ("jobs", "mps_plans", "mps_task_definitions"):
            assert session.scalar(text(f"SELECT count(*) FROM management.{table}")) == 0
    assert store.active_page(limit=5) == []
    jobs.publish_ws_event.assert_not_awaited()


def task(kind, index, *, site="OnlyFans", user=10, auth=None, content=ContentType.POSTS, deps=(), media_ids=None):
    result = job_builder.build_task(kind, site_name=site, user_id=user, user_username=f"profile-{user}",
        content_type=content, auth_id=auth, media_ids=media_ids, use_guest_auth=kind == TaskType.SCRAPE)
    return result.model_copy(update={"task_id": f"build-{index}", "depends_on": list(deps)})


@pytest.mark.parametrize("scenario", ["content", "fallback", "site_auth", "rewritten", "media", "mixed_sites"])
async def test_streamed_builder_matches_complete_list_dependencies(store, window_runtime, monkeypatch, scenario):
    app_for(monkeypatch, window_runtime)
    S, D = TaskType.SCRAPE, TaskType.DOWNLOAD
    source = [task(D, 1, deps=["gone"]), task(S, 2, auth=7), task(S, 3, auth=8, content=ContentType.MESSAGES)]
    if scenario == "fallback":
        source = [task(D, 1, content=ContentType.HIGHLIGHTS), task(S, 2, auth=7), task(S, 3, auth=7, content=ContentType.MESSAGES)]
    elif scenario == "site_auth":
        source = [task(D, 1, user=0, auth=7, deps=["build-3", "build-3", "gone"]),
                  task(S, 2, user=20, auth=7), task(S, 3, user=30), task(S, 4, auth=8)]
    elif scenario == "rewritten":
        source[1].payload.use_guest_auth = False
        expanded = source[1].model_copy(update={"task_id": "new-scrape-id", "auth_id": 42})
        source = [source[0].model_copy(update={"depends_on": ["build-2"]}), source[1]]
        monkeypatch.setattr(job_builder, "iter_scrape_tasks_by_db_subscriptions", lambda **kwargs: iter([expanded]))
    elif scenario == "media":
        source = [task(D, 1, media_ids=[12, 13, 14]), task(S, 2, auth=7)]
    elif scenario == "mixed_sites":
        source = [task(D, 1, site="Fansly"), task(S, 2, auth=7), task(S, 3, site="Fansly", auth=8), task(D, 4)]

    import itertools
    ids = itertools.count()
    monkeypatch.setattr(job_builder, "uuid4", lambda: SimpleNamespace(hex=f"{next(ids):032x}"[::-1]))
    expected = job_builder.build_job(source).job.tasks
    ids = itertools.count()
    job = Job(name="SQL builder", created_by="fixture", tasks=[])
    async with task_inputs.stage_task_inputs(source, job_id=job.job_id, input_max_bytes=100000) as staged:
        config = await jobs._persist_central_job_submission(job_id=job.job_id, job_type="SQL builder", site=staged.sites[0],
            args_payload={}, tasks=staged.tasks_by_site(), job_config=job.to_config(include_task_ids=False).to_dict(), windowed=True, build_tasks=True)
    rows = definitions(store, job.job_id)
    def relevant(row):
        return {key: row[key] for key in ("task_id", "task_type", "site_name", "user_id", "auth_id", "depends_on", "payload", "capabilities", "ip_lock_key")}
    assert [relevant(row) for row in rows] == [relevant(value.to_dict()) for value in expected]
    assert config["total_tasks"] == len(expected)


async def test_inferred_dependencies_must_fit_configured_row_budget(store, window_runtime, monkeypatch):
    app_for(monkeypatch, window_runtime)
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_MAX_BYTES", "1800")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_MAX_BYTES", "2500")
    source = [task(TaskType.DOWNLOAD, 1, user=0)] + [task(TaskType.SCRAPE, i + 2, user=i + 100) for i in range(150)]
    job = Job(name="Fan in", created_by="fixture", tasks=[])
    from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded
    with pytest.raises(TaskPayloadBudgetExceeded):
        await jobs._persist_central_job_submission(job_id=job.job_id, job_type="fan in", site="onlyfans", args_payload={},
            tasks=source, job_config=job.to_config(include_task_ids=False).to_dict(), windowed=True, build_tasks=True)
    assert store.active_page(limit=5) == []
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.mps_task_definitions")) == 0


async def test_cancelled_creation_keeps_staging_alive_until_sql_finishes(store, window_runtime, monkeypatch):
    app_for(monkeypatch, window_runtime)
    entered, release = threading.Event(), threading.Event()
    files = []
    original = task_inputs.tempfile.TemporaryFile
    def capture(*args, **kwargs):
        stream = original(*args, **kwargs)
        files.append(stream)
        return stream
    monkeypatch.setattr(task_inputs.tempfile, "TemporaryFile", capture)
    with store.session_factory() as session:
        engine = session.get_bind()
    def pause(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO management.mps_task_definitions") and not entered.is_set():
            entered.set()
            assert release.wait(10)
            assert files and not files[0].closed
    event.listen(engine, "before_cursor_execute", pause)
    request = jobs.CreateJobRequest(job_name="Cancelled", created_by="fixture",
        tasks=[jobs.TaskPayload(task_type="api_command", params={"index": i}) for i in range(7)])
    running = asyncio.create_task(jobs.create_job(request, window_runtime, SimpleNamespace()))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        running.cancel()
        await asyncio.sleep(0)
        running.cancel()
        await asyncio.sleep(0)
        assert not running.done() and not files[0].closed
    finally:
        release.set()
        try:
            await running
        except asyncio.CancelledError:
            pass
        event.remove(engine, "before_cursor_execute", pause)
    assert all(stream.closed for stream in files)
    jobs.publish_ws_event.assert_not_awaited()
    assert len(store.active_page(limit=5)) == 1


async def test_many_profile_pairs_keep_specific_dependencies(store, window_runtime, monkeypatch):
    app = app_for(monkeypatch, window_runtime)
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "16")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_BATCH_SIZE", "8")
    async def profile_tasks(payload, manager, **kwargs):
        index = payload.params["index"]
        return [task(TaskType.DOWNLOAD, f"download-{index}", user=index + 1),
                task(TaskType.SCRAPE, f"scrape-{index}", user=index + 1, auth=7)]
    monkeypatch.setattr(jobs, "_build_task_from_payload", profile_tasks)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture", headers={"Content-Type": "application/json"}) as client:
        response = await client.post("/jobs", content=body_rows(1000, marker="x"))
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    assert response.json()["task_count"] == 2000
    rows = definitions(store, job_id)
    for index in range(1000):
        download, scrape = rows[index * 2:index * 2 + 2]
        assert download["depends_on"] == [scrape["task_id"]]
        assert download["auth_id"] == scrape["auth_id"] == 7
