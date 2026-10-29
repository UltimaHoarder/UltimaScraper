"""Ordinary edits stage complete inputs with bounded buffers before taking a lease."""

import asyncio
import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

import test_normal_edit_dispatch as edits
import test_mps_http_inputs as http
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.api.routes import job_central_store
from ultima_scraper_backend.job_system import task_inputs
from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded

postgres_engine = edits.postgres_engine
database = edits.database
redis_manager = edits.redis_manager
manager = http.manager


def replacement(index, marker):
    task = edits.inputs.task(index + 50, width=0)
    task.created_at = task.updated_at = datetime(
        2026, 9, 8, tzinfo=timezone.utc
    ).isoformat()
    task.payload.args["marker"] = marker
    if index:
        task.depends_on = [f"task-{index + 49:09}"]
    return task


def app_for(monkeypatch, manager, backend):
    app = http.upload_app(monkeypatch, manager, backend)

    async def build(payload, _manager):
        if payload.params.get("reject"):
            raise HTTPException(400, "Fixture task cannot be built")
        return replacement(payload.params["index"], payload.params["marker"])

    monkeypatch.setattr(jobs, "_build_task_from_payload", build)
    return app


async def body_rows(count, marker="é" * 1000, *, invalid=False):
    yield b'{"job_name":"Streamed","tasks":['
    for index in range(count):
        row = {"task_type": "api_command", "params": {"index": index, "marker": marker}}
        if invalid and index == count - 1:
            row.pop("task_type")
        yield (b"," if index else b"") + json.dumps(row, ensure_ascii=False).encode()
    yield b"]}"


async def test_http_replacement_preserves_inputs_and_bounds_sql_batches(
    database, redis_manager, monkeypatch
):
    storage, job, backend, manager, route = await edits.fixture(
        monkeypatch, redis_manager
    )
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "3")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_BATCH_SIZE", "2")
    sample = replacement(1, "é" * 1000)
    sample.job_id = job.job_id
    budget = task_inputs._row_size(job_central_store._task_to_central_row(job.job_id, sample)) * 2
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_MAX_BYTES", str(budget))
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_MAX_BYTES", str(budget))
    with database.begin() as connection:
        connection.execute(
            text("UPDATE management.jobs SET args_json=:args WHERE job_id=:job"),
            {
                "job": job.job_id,
                "args": json.dumps({"tasks": ["old redundant input"], "kept": 17}),
            },
        )
    batches = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO management.job_tasks"):
            values = context.compiled_parameters
            batches.append(len(values))
            assert len(values) <= 3
            assert sum(task_inputs._row_size(row) for row in values) <= budget

    event.listen(database, "before_cursor_execute", capture)
    app = app_for(monkeypatch, manager, backend)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            response = await client.patch(f"/jobs/{job.job_id}", content=body_rows(7))
    finally:
        event.remove(database, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    assert sum(batches) == 7 and len(batches) >= 4
    with database.connect() as connection:
        summary = json.loads(
            connection.scalar(
                text("SELECT args_json FROM management.jobs WHERE job_id=:job"),
                {"job": job.job_id},
            )
        )
    assert summary == {"job_name": "Streamed", "task_count": 7, "kept": 17}
    current = await storage.fetch_job(job.job_id, include_tasks=False)
    assert current.total_tasks == 7 and current.tasks == [] and current.task_ids == []
    for index, (_, _, raw) in enumerate(edits.sql_snapshot(database, job.job_id)[1]):
        task = replacement(index, "é" * 1000)
        task.job_id = job.job_id
        assert json.loads(raw) == task.to_dict(include_result=False)
    route.assert_awaited_once()
    await edits.assert_no_edit(storage, job.job_id)


@pytest.mark.parametrize(
    "failure,expected",
    [("invalid", 422), ("oversize", 413), ("factory", 400), ("empty", 400)],
)
async def test_rejected_stream_leaves_sql_and_redis_untouched(
    database, redis_manager, monkeypatch, failure, expected
):
    storage, job, backend, manager, route = await edits.fixture(
        monkeypatch, redis_manager
    )
    before = edits.sql_snapshot(database, job.job_id)
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_BATCH_SIZE", "1")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "1")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_MAX_BYTES", "2000")
    app = app_for(monkeypatch, manager, backend)
    options = {
        "content": body_rows(
            4,
            marker="x" * (4000 if failure == "oversize" else 10),
            invalid=failure == "invalid",
        )
    }
    if failure == "factory":
        options = {
            "json": {
                "tasks": [{"task_type": "api_command", "params": {"reject": True}}]
            }
        }
    elif failure == "empty":
        options = {"json": {"tasks": []}}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        response = await client.patch(f"/jobs/{job.job_id}", **options)
    assert response.status_code == expected, response.text
    assert edits.sql_snapshot(database, job.job_id) == before
    assert (await storage.fetch_job(job.job_id, include_tasks=False)).name == job.name
    route.assert_not_awaited()
    await edits.assert_no_edit(storage, job.job_id)


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_oversized_input_closes_consumed_iterator(monkeypatch, asynchronous):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_MAX_BYTES", "1500")
    closed = []

    def source():
        try:
            yield edits.inputs.task(1, width=10000)
            pytest.fail("Rejected source was consumed further")
        finally:
            closed.append(True)

    async def async_source():
        try:
            yield edits.inputs.task(1, width=10000)
            pytest.fail("Rejected source was consumed further")
        finally:
            closed.append(True)

    iterator = async_source() if asynchronous else source()
    with pytest.raises(TaskPayloadBudgetExceeded):
        async with task_inputs.stage_task_inputs(
            iterator, job_id="fixture", input_max_bytes=1500
        ):
            pytest.fail("Oversized input reached the edit")
    assert closed == [True]


async def test_staging_does_not_hold_edit_lease_or_sql_session(
    database, redis_manager, monkeypatch
):
    storage, job, backend, manager, _ = await edits.fixture(monkeypatch, redis_manager)
    entered, release = asyncio.Event(), asyncio.Event()

    async def source():
        yield replacement(0, "x")
        entered.set()
        await release.wait()
        yield replacement(1, "x")

    pending = asyncio.create_task(
        manager.update_job_by_id(job.job_id, tasks=source(), route_immediate_job=False)
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await edits.assert_no_edit(storage, job.job_id)
        assert database.pool.checkedout() == 0
        updated = await edits.edit(monkeypatch, backend, job, name="During upload")
        assert updated.job_name == "During upload"
    finally:
        release.set()
        result = await asyncio.wait_for(pending, 5)
    assert result.name == "During upload" and result.total_tasks == 2


async def test_cancelled_staging_drains_file_write_and_source_finalizer(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "1")
    entered, release = threading.Event(), threading.Event()
    finalizing, finish = asyncio.Event(), asyncio.Event()
    opened = []
    real_file = task_inputs.tempfile.TemporaryFile

    class HeldFile:
        def __init__(self):
            self.source = real_file()
            opened.append(self.source)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.source.close()

        def write(self, value):
            entered.set()
            assert release.wait(5)
            assert not self.source.closed
            return self.source.write(value)

    monkeypatch.setattr(
        task_inputs.tempfile, "TemporaryFile", lambda **kwargs: HeldFile()
    )

    async def source():
        try:
            yield replacement(0, "x")
            yield replacement(1, "x")
        finally:
            finalizing.set()
            await finish.wait()

    async def work():
        async with task_inputs.stage_task_inputs(
            source(), job_id="fixture", input_max_bytes=32768
        ):
            pytest.fail("Cancelled staging reached the edit")

    pending = asyncio.create_task(work())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        pending.cancel()
        await asyncio.sleep(0)
        assert not opened[0].closed
        release.set()
        await asyncio.wait_for(finalizing.wait(), 3)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done() and not opened[0].closed
    finally:
        release.set()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 5)
    assert opened[0].closed


async def test_staging_write_failure_closes_source_and_file(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "1")
    opened, closed = [], []
    real_file = task_inputs.tempfile.TemporaryFile

    def temporary(**kwargs):
        source = real_file(**kwargs)
        opened.append(source)
        return source

    async def failed_write(*args):
        raise OSError("Fixture staging storage full")

    async def source():
        try:
            yield replacement(0, "x")
            yield replacement(1, "x")
        finally:
            closed.append(True)

    monkeypatch.setattr(task_inputs.tempfile, "TemporaryFile", temporary)
    monkeypatch.setattr(task_inputs, "_file_call", failed_write)
    with pytest.raises(OSError, match="storage full"):
        async with task_inputs.stage_task_inputs(
            source(), job_id="fixture", input_max_bytes=32768
        ):
            pytest.fail("Failed write reached the edit")
    assert closed == [True] and opened[0].closed


async def test_ordinary_and_mps_upload_admission_are_independent(monkeypatch, manager):
    manager.job.metadata.pop("mps_manifest")
    monkeypatch.setenv("ULTIMA_JOB_UPLOAD_CONCURRENCY", "1")
    monkeypatch.setenv("ULTIMA_JOB_UPLOAD_MAX_INFLIGHT_BYTES", "32768")
    monkeypatch.setenv("ULTIMA_MPS_UPLOAD_CONCURRENCY", "2")
    monkeypatch.setenv("ULTIMA_MPS_UPLOAD_MAX_INFLIGHT_BYTES", "65536")
    entered, release = asyncio.Event(), asyncio.Event()
    rejected_read = False

    async def held():
        entered.set()
        yield b'{"job_name":'
        await release.wait()
        yield b'"Released"}'

    async def rejected():
        nonlocal rejected_read
        rejected_read = True
        yield b"{}"

    app = http.upload_app(monkeypatch, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        path = f"/jobs/{manager.job.job_id}"
        pending = asyncio.create_task(client.patch(path, content=held()))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            assert (await client.patch(path, content=rejected())).status_code == 503
            assert not rejected_read
            manager.job.metadata["mps_manifest"] = "fixture"
            assert (
                await client.patch(path, json={"job_name": "MPS"})
            ).status_code == 200
        finally:
            release.set()
            assert (await pending).status_code == 200
        manager.job.metadata.pop("mps_manifest")
        assert (
            await client.patch(path, json={"job_name": "Ordinary again"})
        ).status_code == 200


async def test_validated_python_request_builds_tasks_lazily(monkeypatch, manager):
    manager.job.metadata.clear()
    build_count = 0

    async def build(payload, _manager):
        nonlocal build_count
        assert build_count == manager.seen
        build_count += 1
        return replacement(build_count, "x")

    monkeypatch.setattr(jobs, "JobManager", lambda _redis: manager)
    monkeypatch.setattr(jobs, "_build_task_from_payload", build)
    backend = SimpleNamespace(
        redis=SimpleNamespace(is_connected=True), distributed_mode=False
    )
    response = await jobs._update_job(
        manager.job.job_id,
        jobs.UpdateJobRequest(
            tasks=[
                jobs.TaskPayload(task_type="api_command", params={}) for _ in range(10)
            ]
        ),
        backend,
        SimpleNamespace(),
    )
    assert response.job_id == manager.job.job_id and manager.seen == build_count == 10
