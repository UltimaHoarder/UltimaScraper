"""HTTP task uploads must stay bounded before durable MPS staging."""

from __future__ import annotations

import asyncio
import io
import json
import threading
import time
import tracemalloc
from collections.abc import AsyncIterable
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

import test_mps_job_edits as fixtures

from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import Job, Task, TaskType
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


def upload_app(monkeypatch, manager, backend=None):
    app = FastAPI()
    app.include_router(jobs.router)
    backend = backend or SimpleNamespace(
        redis=SimpleNamespace(is_connected=True), distributed_mode=False
    )
    app.dependency_overrides[jobs.get_backend_instance] = lambda: backend
    app.dependency_overrides[jobs.get_backend_manager] = lambda: SimpleNamespace()
    monkeypatch.setattr(jobs, "JobManager", lambda _redis: manager)

    async def build(payload, _manager):
        return Task(
            task_type=TaskType.DOWNLOAD,
            site_name="OnlyFans",
            user_id=payload.params["user_id"],
        )

    monkeypatch.setattr(jobs, "_build_task_from_payload", build)
    return app


@pytest.fixture
def manager():
    job = Job(
        name="Upload fixture",
        created_by="fixture",
        tasks=[],
        metadata={"mps_manifest": "fixture"},
    )
    manager = SimpleNamespace(
        storage=SimpleNamespace(fetch_job=AsyncMock(return_value=job)),
        fetch_job_for_update=AsyncMock(return_value=job),
        database_writes=SimpleNamespace(max_command_bytes=32768, max_queue_bytes=32768),
        seen=0,
        job=job,
    )

    async def update(_job_id, *, tasks, name, **kwargs):
        if isinstance(tasks, AsyncIterable):
            async for task in tasks:
                manager.seen += 1
        elif tasks is not None:
            manager.seen += len(tasks)
        if name is not None:
            job.name = name
        return job

    manager.update_job_by_id = update
    return manager


def request_rows(count):
    async def body():
        yield b'{"tasks":['
        for first in range(0, count, 8):
            chunk = []
            for index in range(first, min(first + 8, count)):
                row = {
                    "task_type": "download",
                    "params": {"user_id": index, "text": "x" * 1024},
                }
                chunk.append((b"," if index else b"") + json.dumps(row).encode())
            yield b"".join(chunk)
        yield b'],"job_name":"Uploaded"}'

    return body()


@pytest.mark.parametrize("count", [1000, 10000])
async def test_http_upload_memory_is_independent_of_total(
    monkeypatch, manager, count, record_property
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "7")
    app = upload_app(monkeypatch, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        assert (
            await client.patch(f"/jobs/{manager.job.job_id}", json={"job_name": "Warm"})
        ).status_code == 200
        started = time.monotonic()
        tracemalloc.start()
        try:
            response = await client.patch(
                f"/jobs/{manager.job.job_id}",
                content=request_rows(count),
                headers={"content-type": "application/json"},
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    assert response.status_code == 200, response.text
    assert manager.seen == count
    assert response.json()["job_name"] == "Uploaded"
    print(f"upload count={count} traced_peak_bytes={peak}")
    record_property("upload_tasks", count)
    record_property("upload_traced_peak_bytes", peak)
    record_property("upload_elapsed_seconds", time.monotonic() - started)
    assert peak < 2 * 1024 * 1024


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"[]",
        b'{"tasks":[{},]}',
        b'{"job_name":"x",}',
        b'{"tasks":[]}garbage',
        b'{"tasks":[{"task_type":"download","params":{}}]',
    ],
)
async def test_malformed_upload_does_not_reach_task_update(monkeypatch, manager, body):
    app = upload_app(monkeypatch, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        response = await client.patch(
            f"/jobs/{manager.job.job_id}",
            content=body,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 422
    assert manager.seen == 0
    assert manager.job.name == "Upload fixture"


async def test_value_byte_limit_and_explicit_increase(monkeypatch, manager):
    row = json.dumps(
        {"task_type": "download", "params": {"user_id": 1, "text": "π" * 2000}},
        ensure_ascii=False,
    ).encode()
    body = b'{"tasks":[' + row + b"]}"
    manager.database_writes.max_command_bytes = len(row) - 1
    app = upload_app(monkeypatch, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        failed = await client.patch(f"/jobs/{manager.job.job_id}", content=body)
        assert failed.status_code == 413
        assert manager.seen == 0
        manager.database_writes.max_command_bytes = len(row)
        accepted = await client.patch(f"/jobs/{manager.job.job_id}", content=body)
    assert accepted.status_code == 200, accepted.text
    assert manager.seen == 1


async def test_split_json_tokens_and_duplicate_field_semantics():
    from ultima_scraper_backend.api.job_update_body import _scan

    class SingleByte(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 1))

    source = SingleByte(
        b'{"tasks":[false],"job_name":"old","tasks":[{"task_type":"download","params":{"user_id":1,"n":1.25e+12,"text":"'
        + "é漢".encode()
        + b'","escaped":"\\"\\\\"}}],"job_name":"new"}'
    )
    model, tasks = _scan(source, 4096, 2, jobs.UpdateJobRequest, jobs.TaskPayload)
    records = [item async for item in tasks]
    assert model.job_name == "new"
    assert len(records) == 1
    assert records[0].params == {
        "user_id": 1,
        "n": 1.25e12,
        "text": "é漢",
        "escaped": '"\\',
    }


def test_openapi_retains_the_update_body_contract(monkeypatch, manager):
    app = upload_app(monkeypatch, manager)
    schema = app.openapi()
    body = schema["paths"]["/jobs/{job_id}"]["patch"]["requestBody"]
    assert body["required"] is True
    fields = body["content"]["application/json"]["schema"]["properties"]
    assert {"job_name", "tasks", "schedule"} == set(fields)
    task_array = next(
        item for item in fields["tasks"]["anyOf"] if item.get("type") == "array"
    )
    assert task_array["items"]["required"] == ["task_type", "params"]


async def test_cancelled_file_call_finishes_before_tempfile_closes(monkeypatch):
    from ultima_scraper_backend.api import job_update_body
    from starlette.requests import Request

    entered = threading.Event()
    release = threading.Event()
    source = io.BytesIO()
    observed = []

    class File:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            observed.append("closed")
            source.close()

        def write(self, data):
            entered.set()
            assert release.wait(5)
            assert not source.closed
            observed.append("written")
            return source.write(data)

    monkeypatch.setattr(
        job_update_body.tempfile, "TemporaryFile", lambda **kwargs: File()
    )
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def upload():
        async with job_update_body.read_job_update(
            Request({"type": "http"}, receive),
            byte_limit=4096,
            batch_limit=2,
            request_model=jobs.UpdateJobRequest,
            task_model=jobs.TaskPayload,
        ):
            pytest.fail("Cancelled upload reached parsing")

    pending = asyncio.create_task(upload())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        pending.cancel()
        await asyncio.sleep(0)
        assert not source.closed
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert observed == ["written", "closed"]


@pytest.mark.parametrize("invalid_tail", [False, True])
async def test_http_upload_uses_durable_batches_and_preserves_invalid_edit(
    store,
    window_runtime,
    monkeypatch,
    invalid_tail,
):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation

    plan, storage, runtime_manager = await fixtures.prepared_window(
        store,
        window_runtime,
        archived=True,
    )
    job_id = plan["job_id"]
    original = store.get(job_id)
    original_ids = await legacy.list_tasks_for_job(storage, job_id)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    runtime_manager.database_writes.max_command_bytes = 32768
    runtime_manager.database_writes.max_queue_bytes = 32768
    submit = runtime_manager.database_writes.submit
    appended = []

    async def record(operation, payload, **kwargs):
        if operation == DatabaseWriteOperation.APPEND_MPS_REPLACEMENT:
            appended.append((payload["offset"], len(payload["tasks"])))
            # Staging cannot alter the previous committed selection/history.
            assert store.get(job_id)["total"] == original["total"]
            assert store.get(job_id)["cursor"] == original["cursor"]
        return await submit(operation, payload, **kwargs)

    monkeypatch.setattr(runtime_manager.database_writes, "submit", record)
    app = upload_app(monkeypatch, runtime_manager, window_runtime)
    tasks = [
        {"task_type": "download", "params": {"user_id": value}}
        for value in range(40, 57)
    ]
    if invalid_tail:
        tasks.append({"task_type": "download"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        response = await client.patch(
            f"/jobs/{job_id}", json={"tasks": tasks, "job_name": "HTTP replacement"}
        )
    assert appended and all(count <= 2 for _, count in appended)
    if invalid_tail:
        assert response.status_code == 422, response.text
        assert response.json()["detail"][0]["loc"] == ["body", "tasks", 17, "params"]
        assert store.get(job_id)["selection"] == original["selection"]
        assert store.get(job_id)["total"] == original["total"]
        assert await legacy.list_tasks_for_job(storage, job_id) == original_ids
        return
    assert response.status_code == 200, response.text
    assert response.json()["task_count"] == 17
    current = store.get(job_id)
    manifest = current["selection"]["task_manifest_id"]
    with store.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.mps_task_definitions WHERE manifest_id=:manifest"
                ),
                {"manifest": manifest},
            )
            == 17
        )
    assert len(await legacy.list_tasks_for_job(storage, job_id)) == 3
    await storage._client().flushall()  # Only the disposable fixture Redis.
    await mps_durable.recover(window_runtime)
    await mps_durable.advance(window_runtime, job_id)
    assert store.get(job_id)["total"] == 17
    restored = await storage.fetch_job(job_id, include_tasks=False)
    assert restored.name == "HTTP replacement"
    assert len(await legacy.list_tasks_for_job(storage, job_id)) == 3


async def test_upload_uses_configured_temp_storage_and_cleans_up(monkeypatch, tmp_path):
    from ultima_scraper_backend.api import job_update_body
    from starlette.requests import ClientDisconnect, Request

    real_file = job_update_body.tempfile.TemporaryFile
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(job_update_body.tempfile, "tempdir", None)
    opened = []

    def temporary(**kwargs):
        source = real_file(**kwargs)
        assert job_update_body.tempfile.gettempdir() == str(tmp_path)
        opened.append(source)
        return source

    monkeypatch.setattr(job_update_body.tempfile, "TemporaryFile", temporary)
    messages = iter(
        [
            {"type": "http.request", "body": b'{"tasks":[', "more_body": True},
            {"type": "http.disconnect"},
        ]
    )

    async def receive():
        return next(messages)

    with pytest.raises(ClientDisconnect):
        async with job_update_body.read_job_update(
            Request({"type": "http"}, receive),
            byte_limit=4096,
            batch_limit=2,
            request_model=jobs.UpdateJobRequest,
            task_model=jobs.TaskPayload,
        ):
            pytest.fail("Disconnected input was accepted")
    assert len(opened) == 1 and opened[0].closed
    assert list(tmp_path.iterdir()) == []


def test_large_value_parser_doubles_reads_within_its_budget():
    from ultima_scraper_backend.api.job_update_body import _Reader

    record = json.dumps({"value": "x" * 250000}).encode()
    reader = _Reader(io.BytesIO(record + b","), len(record))
    decoder = reader.decoder
    calls = []

    def decode(value):
        calls.append(len(value))
        return decoder.raw_decode(value)

    reader.decoder = SimpleNamespace(raw_decode=decode)
    value, size = reader.value()
    assert len(value["value"]) == 250000 and size == len(record)
    assert len(calls) <= 7
    assert max(calls) <= len(record) + 1
