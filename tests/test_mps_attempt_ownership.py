"""An executing worker must not alter a subsequently committed MPS definition.

Handlers are deterministic; worker, Task.run, storage, event processing, SQL
writer and task replacement use production code against owned PG/Redis fixtures.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import text

import test_mps_job_edits as fixtures
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
from ultima_scraper_backend.job_system import JobStorage, Task, TaskResult, TaskState
from ultima_scraper_backend.job_system import mps_attempt, mps_state
from ultima_scraper_backend.job_system.event_log import EventLog
from ultima_scraper_backend.job_system.models import TaskRegistry, TaskType
from ultima_scraper_backend.redis.worker_registry import WorkerRegistry
from ultima_scraper_backend.workers.worker_pool import (
    Worker,
    UltimaScraperCollectionConfig,
)
from functools import partial

import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


def legacy_task_status(job_id, task, status):
    """A command already queued by a worker from before status deferral."""
    return {
        "job_id": job_id,
        "task_id": task.task_id,
        "mps_task_manifest": task.mps_task_manifest or "",
        "status": status,
        "event_time": "2026-09-13T00:00:00+00:00",
    }


def worker_for(runtime, storage, queued):
    worker = Worker(
        worker_id="attempt-test",
        redis_url="redis://unused",
        supported_sites=["onlyfans"],
        config=UltimaScraperCollectionConfig(),
        backend_id=runtime.instance_id,
    )
    worker.task_job_storage = storage
    worker.backend_router = SimpleNamespace(enqueue_ready_tasks=AsyncMock())
    worker.apis = {"onlyfans": object()}
    worker._refresh_storage_config_before_task = AsyncMock()
    worker._ensure_auth_loaded_for_task = AsyncMock()
    worker._requeue_deferred_tasks = AsyncMock()
    worker.event_log = EventLog(runtime.redis)
    worker.worker_registry = WorkerRegistry(
        runtime.redis, runtime.instance_id, worker_id=worker.worker_id
    )

    async def enqueue(operation, payload, **kwargs):
        queued.append((operation, payload, kwargs))

    worker.database_writes = SimpleNamespace(
        enqueue=enqueue, submit=runtime.writes.submit
    )
    return worker


@pytest.mark.parametrize("reuse_task_id", [False, True])
@pytest.mark.parametrize(
    "outcome", ["success", "failure", "exception", "setup_failure"]
)
async def test_running_worker_discards_result_after_replacement(
    store, window_runtime, monkeypatch, reuse_task_id, outcome
):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=True
    )
    job_id = plan["job_id"]
    old = [task async for task in storage.fetch_tasks_stream(job_id)][0]
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(task, context):
        entered.set()
        await release.wait()
        if outcome == "exception":
            raise RuntimeError("obsolete handler failure")
        return TaskResult(
            success=outcome == "success", message="obsolete handler result"
        )

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, handler)
    queued = []
    worker = worker_for(window_runtime, storage, queued)
    if outcome == "setup_failure":

        async def setup_failure(task, site):
            entered.set()
            await release.wait()
            raise RuntimeError("obsolete setup failure")

        worker._ensure_auth_loaded_for_task = setup_failure
    execution = asyncio.create_task(worker._execute_ready_task(job_id, old.task_id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        # Inject the supported paused state while a claimed handler is still
        # unwinding; replacement uses the public manager's normal edit path.
        await storage._client().hset(
            storage.JOB_STATE_KEY.format(job_id=job_id), "status", "paused"
        )
        replacement = Task(
            task_id=old.task_id if reuse_task_id else uuid4().hex,
            task_type=old.task_type,
            site_name=old.site_name,
            user_id=old.user_id,
            content_type=old.content_type,
            auth_id=old.auth_id,
            payload={"replacement": True},
        )
        await manager.update_job_by_id(job_id, tasks=[replacement])
        current = await storage.fetch_task(job_id, replacement.task_id)
        before_task = current.to_dict()
        before_state = await storage._client().hgetall(
            storage.JOB_STATE_KEY.format(job_id=job_id)
        )
        dedup_key = storage.DEDUPE_KEY.format(dedup=current.dedup_key)
        assert await storage._client().get(dedup_key) in (
            current.task_id,
            current.task_id.encode(),
        )
        release.set()
        assert await asyncio.wait_for(execution, 5) == (False, False, None)
        assert (
            await storage.fetch_task(job_id, current.task_id)
        ).to_dict() == before_task
        assert (
            await storage._client().hgetall(storage.JOB_STATE_KEY.format(job_id=job_id))
            == before_state
        )
        assert await legacy.list_tasks_for_job(storage, job_id) == [current.task_id]
        assert await storage._client().get(dedup_key) in (
            current.task_id,
            current.task_id.encode(),
        )
        assert await storage.get_task_output(job_id, current.task_id) is None
        registry = json.loads(
            await storage._client().get(worker.worker_registry._worker_key())
        )
        assert registry["current_task"] is None
        assert registry["tasks_completed"] == 0
        assert registry["tasks_failed"] == 1

        # New workers need no pre-archive SQL telemetry. A command from an
        # older worker must still be fenced if it arrives after replacement.
        assert queued == []
        result = await window_runtime.writes.submit(
            DatabaseWriteOperation.SYNC_TASK_STATUS,
            legacy_task_status(job_id, old, "running"),
        )
        assert result == {"synced": False, "stale": True}
        assert store.get(job_id)["cursor"] == 0
        assert store.get(job_id)["total"] == 1
    finally:
        release.set()
        if not execution.done():
            execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)


@pytest.mark.parametrize("reuse_task_id", [False, True])
async def test_direct_late_result_cannot_change_replacement(
    store, window_runtime, reuse_task_id
):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=True
    )
    job_id = plan["job_id"]
    old_job = await storage.fetch_job(job_id, include_tasks=False)
    old = [task async for task in storage.fetch_tasks_stream(job_id)][0]
    replacement = Task(
        task_id=old.task_id if reuse_task_id else uuid4().hex,
        task_type=TaskType.DOWNLOAD,
        site_name=old.site_name,
        user_id=old.user_id,
    )
    await manager.update_job_by_id(job_id, tasks=[replacement])
    new = await storage.fetch_task(job_id, replacement.task_id)

    old.result = TaskResult(success=True, message="stale")
    old.state = TaskState.COMPLETED
    for write in (storage.persist_task, partial(legacy.persist_task_result, storage)):
        with pytest.raises(mps_attempt.StaleTaskDefinition):
            await write(job_id, old)
    with mps_attempt.bind(old_job, old):
        for write in (
            lambda: legacy.store_task_output(storage, job_id, old.task_id, {"stale": True}),
            lambda: legacy.mark_task_completed(storage, job_id, old.task_id),
            lambda: legacy.mark_task_failed(storage, job_id, old.task_id),
            lambda: legacy.remove_task_from_inflight(storage, job_id, old.task_id),
            lambda: legacy.mark_task_deferred(storage, job_id, old.task_id, old.dedup_key),
            lambda: storage.persist_job(old_job),
            lambda: manager.router.clear_job_routing(
                job_id=job_id, backend_id=window_runtime.instance_id
            ),
        ):
            with pytest.raises(mps_attempt.StaleTaskDefinition):
                await write()
    assert (await storage.fetch_task(job_id, new.task_id)).to_dict() == new.to_dict()


@pytest.mark.parametrize("succeeds", [True, False])
async def test_last_worker_window_archives_before_job_completion(
    store, window_runtime, monkeypatch, succeeds
):
    plan = fixtures.fixtures.prepare_runtime_plan(store, 1)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job_id)
    (task_id,) = await legacy.list_tasks_for_job(storage, job_id)
    task = await storage.fetch_task(job_id, task_id)

    async def handler(task, context):
        return TaskResult(
            success=succeeds,
            message="last window evidence",
            continue_job_on_failure=not succeeds,
        )

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, handler)
    queued = []
    worker = worker_for(window_runtime, storage, queued)
    assert await worker._execute_ready_task(job_id, task_id) == (True, False, None)
    registry = json.loads(
        await storage._client().get(worker.worker_registry._worker_key())
    )
    assert registry["current_task"] is None
    assert registry["tasks_completed"] == int(succeeds)
    assert registry["tasks_failed"] == int(not succeeds)
    assert store.get(job_id)["cursor"] == 0
    assert (
        await storage.fetch_task(job_id, task_id)
    ).result.message == "last window evidence"
    # The materializer performs terminal persistence and only then purges Redis.
    assert await mps_durable.advance(window_runtime, job_id) is False
    assert store.get(job_id)["cursor"] == 1
    assert queued == []
    # Delayed telemetry from an older worker must not regress the archive.
    for status in ("running", "completed" if succeeds else "failed"):
        await window_runtime.writes.submit(
            DatabaseWriteOperation.SYNC_TASK_STATUS,
            legacy_task_status(job_id, task, status),
        )
    with store.session_factory() as session:
        row = session.execute(
            text("SELECT status, result_success FROM management.jobs WHERE job_id=:id"),
            {"id": job_id},
        ).one()
        assert row.status == ("completed" if succeeds else "failed")
        assert row.result_success is succeeds
        row = session.execute(
            text("SELECT status, result_json FROM management.job_tasks WHERE task_id=:id"),
            {"id": task_id},
        ).one()
        assert row.status == ("completed" if succeeds else "failed")
        assert json.loads(row.result_json)["message"] == "last window evidence"
    assert await storage.fetch_task(job_id, task_id) is None
    assert await storage._client().hget(mps_state.BUDGET_KEY, "tasks") in (b"0", "0")


async def test_stale_sql_job_status_does_not_cancel_new_definition(
    store, window_runtime
):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=False
    )
    job_id = plan["job_id"]
    old = await storage.fetch_job(job_id, include_tasks=False)
    await manager.update_job_by_id(
        job_id, tasks=[Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=7)]
    )
    response = await window_runtime.writes.submit(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        {
            "job_id": job_id,
            "mps_task_manifest": "",
            "status": "cancelled",
            "job_snapshot": {"name": "obsolete name"},
        },
    )
    assert response == {"synced": False, "stale": True}
    response = await window_runtime.writes.submit(
        DatabaseWriteOperation.TERMINATE_MPS_JOB,
        {
            "job_id": job_id,
            "mps_task_manifest": "",
            "status": "cancelled",
        },
    )
    assert response == {"committed": False, "stale": True}
    assert store.get(job_id)["status"] == "ready"
    worker = worker_for(window_runtime, storage, [])
    with pytest.raises(mps_attempt.StaleTaskDefinition):
        await worker._sync_job_status_to_database(old, "cancelled")


async def test_worker_cleanup_remains_fenced_if_its_finish_lease_is_lost(
    store, window_runtime, monkeypatch
):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=False
    )
    job_id = plan["job_id"]
    old = [task async for task in storage.fetch_tasks_stream(job_id)][0]
    worker = worker_for(window_runtime, storage, [])
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(task, context):
        return TaskResult(success=True, message="finished before lease loss")

    enqueue_status = worker._enqueue_task_database_status

    async def held_status(**kwargs):
        result = await enqueue_status(**kwargs)
        if kwargs["status"] == TaskState.COMPLETED:
            entered.set()
            await release.wait()
        return result

    worker._enqueue_task_database_status = held_status
    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, handler)
    execution = asyncio.create_task(worker._execute_ready_task(job_id, old.task_id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        client = storage._client()
        # Deterministically inject an expired/stolen materialization lease.
        assert await client.get(mps_attempt.lock_key(job_id))
        await client.delete(mps_attempt.lock_key(job_id))
        await client.hset(
            storage.JOB_STATE_KEY.format(job_id=job_id), "status", "paused"
        )
        await manager.update_job_by_id(
            job_id,
            tasks=[
                Task(
                    task_id=old.task_id,
                    task_type=TaskType.SCRAPE,
                    site_name=old.site_name,
                    user_id=old.user_id,
                    content_type=old.content_type,
                    auth_id=old.auth_id,
                    payload={"replacement": True},
                )
            ],
        )
        current = await storage.fetch_task(job_id, old.task_id)
        state = await client.hgetall(storage.JOB_STATE_KEY.format(job_id=job_id))
        release.set()
        assert await asyncio.wait_for(execution, 5) == (False, False, None)
        assert (
            await client.hgetall(storage.JOB_STATE_KEY.format(job_id=job_id)) == state
        )
        assert (
            await storage.fetch_task(job_id, old.task_id)
        ).to_dict() == current.to_dict()
        assert await storage.get_task_output(job_id, old.task_id) is None
    finally:
        release.set()
        if not execution.done():
            execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)


@pytest.mark.parametrize("replaced_while_cancelling", [False, True])
async def test_cancel_endpoint_stamps_definition_and_honors_sql_rejection(
    store, window_runtime, monkeypatch, replaced_while_cancelling
):
    from ultima_scraper_backend.api.routes import jobs

    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=False
    )
    job_id = plan["job_id"]
    await manager.update_job_by_id(
        job_id,
        tasks=[
            Task(
                task_type=TaskType.SCRAPE,
                site_name="OnlyFans",
                user_id=7,
            )
        ],
    )
    cancelled = await storage.fetch_job(job_id, include_tasks=False)
    if replaced_while_cancelling:
        await manager.update_job_by_id(
            job_id,
            tasks=[
                Task(
                    task_type=TaskType.SCRAPE,
                    site_name="OnlyFans",
                    user_id=8,
                )
            ],
        )
    # Exercise the endpoint's SQL acknowledgement boundary; manager cancellation
    # and resource cleanup have independent coverage.
    monkeypatch.setattr(
        jobs,
        "JobManager",
        lambda _redis: SimpleNamespace(
            cancel_job_by_id=AsyncMock(return_value=cancelled),
            database_writes=window_runtime.writes,
        ),
    )
    cleanup = Mock()
    monkeypatch.setattr(jobs, "_schedule_cancel_cleanup", cleanup)
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    if replaced_while_cancelling:
        with pytest.raises(jobs.HTTPException) as raised:
            await jobs.cancel_job(job_id, backend=window_runtime)
        assert raised.value.status_code == 409
        jobs.publish_ws_event.assert_not_awaited()
    else:
        await jobs.cancel_job(job_id, backend=window_runtime)
    assert cleanup.call_count == (0 if replaced_while_cancelling else 1)
    assert store.get(job_id)["status"] == (
        "ready" if replaced_while_cancelling else "cancelled"
    )
