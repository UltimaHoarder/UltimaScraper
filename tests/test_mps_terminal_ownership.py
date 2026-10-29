"""Deferred terminal cleanup must not alter a replacement task definition."""

from __future__ import annotations

import asyncio
import threading
from contextvars import Context
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text

import test_mps_job_edits as fixtures
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
from ultima_scraper_backend.job_system import JobState, JobStorage, Task, TaskType
from ultima_scraper_backend.job_system import mps_attempt, mps_state
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


async def cancelled_window(store, runtime):
    runtime.redis.delete = runtime.redis.client.delete
    plan, storage, manager = await fixtures.prepared_window(
        store, runtime, archived=False
    )
    await manager.update_job_by_id(
        plan["job_id"],
        tasks=[Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=7)],
    )
    job = await manager.cancel_job_by_id(
        plan["job_id"], wait_for_resource_cleanup=False
    )
    await runtime.writes.submit(
        DatabaseWriteOperation.TERMINATE_MPS_JOB,
        {
            "job_id": job.job_id,
            "status": "cancelled",
            "mps_task_manifest": job.metadata["mps_task_manifest"],
        },
    )
    return job, storage, manager


async def test_delayed_cleanup_cannot_purge_replacement_after_archive_check(
    store, window_runtime, monkeypatch
):
    job, storage, manager = await cancelled_window(store, window_runtime)
    entered, release = asyncio.Event(), asyncio.Event()
    clear = manager.storage.clear_task_state

    async def pause_before_clear(*args, **kwargs):
        entered.set()
        await release.wait()
        return await clear(*args, **kwargs)

    monkeypatch.setattr(manager.storage, "clear_task_state", pause_before_clear)
    cleanup = asyncio.create_task(manager.finalize_job_cancellation(job.job_id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        replacement = Task(
            task_id=f"replacement-{uuid4().hex}",
            task_type=TaskType.SCRAPE,
            site_name="OnlyFans",
            user_id=8,
        )
        await manager.update_job_by_id(job.job_id, tasks=[replacement])
        assert await legacy.list_tasks_for_job(storage, job.job_id) == [replacement.task_id]
        release.set()
        await asyncio.wait_for(cleanup, 5)
        assert await legacy.list_tasks_for_job(storage, job.job_id) == [replacement.task_id]
        assert (
            await storage.fetch_job(job.job_id, include_tasks=False)
        ).state == JobState.PENDING
        assert (await storage.get_job_task_stats(job.job_id))["ready"] == 1
        assert store.get(job.job_id)["status"] == "ready"
    finally:
        release.set()
        if not cleanup.done():
            cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)


async def test_cleanup_request_after_replacement_leaves_current_window_alone(
    store, window_runtime
):
    job, storage, manager = await cancelled_window(store, window_runtime)
    replacement = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=8)
    await manager.update_job_by_id(job.job_id, tasks=[replacement])
    dedup_key = storage.DEDUPE_KEY.format(dedup=replacement.dedup_key)
    await storage._client().set(dedup_key, replacement.task_id)
    await manager.finalize_job_cancellation(job.job_id)
    assert await legacy.list_tasks_for_job(storage, job.job_id) == [replacement.task_id]
    assert (await storage.get_job_task_stats(job.job_id))["ready"] == 1
    assert store.get(job.job_id)["status"] == "ready"
    assert await storage._client().get(dedup_key) == replacement.task_id.encode()


async def test_cancel_racing_replacement_does_not_cancel_the_new_definition(
    store, window_runtime, monkeypatch
):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=False
    )
    window_runtime.redis.delete = window_runtime.redis.client.delete
    job_id = plan["job_id"]
    await manager.update_job_by_id(
        job_id, tasks=[Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=7)]
    )
    entered, release = asyncio.Event(), asyncio.Event()
    resolve = manager._resolve_backend_assignment

    async def pause_after_read(*args, **kwargs):
        entered.set()
        await release.wait()
        return await resolve(*args, **kwargs)

    monkeypatch.setattr(manager, "_resolve_backend_assignment", pause_after_read)
    cancellation = asyncio.create_task(
        manager.cancel_job_by_id(job_id, wait_for_resource_cleanup=False)
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        replacement = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=8)
        await manager.update_job_by_id(job_id, tasks=[replacement])
        release.set()
        try:
            await asyncio.wait_for(cancellation, 5)
        except RuntimeError:
            pass  # A changed definition may reject the original cancellation.
        assert (
            await storage.fetch_job(job_id, include_tasks=False)
        ).state == JobState.PENDING
        assert (await storage.get_job_task_stats(job_id))["ready"] == 1
    finally:
        release.set()
        if not cancellation.done():
            cancellation.cancel()
        await asyncio.gather(cancellation, return_exceptions=True)


def archive_payload(job):
    return {
        "job_id": job.job_id,
        "generation": job.completed_at,
        "batch_size": 1,
        "mps_task_manifest": job.metadata["mps_task_manifest"],
    }


async def test_delayed_sql_cancellation_does_not_terminalize_replacement(
    store, window_runtime, monkeypatch
):
    job, storage, manager = await cancelled_window(store, window_runtime)
    old_plan = store.get(job.job_id)
    replacement = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=8)
    await manager.update_job_by_id(job.job_id, tasks=[replacement])
    with monkeypatch.context() as delayed_read:
        delayed_read.setattr(store, "get", lambda _job_id: old_plan)
        assert await mps_durable.advance(window_runtime, job.job_id) is False
    assert (
        await storage.fetch_job(job.job_id, include_tasks=False)
    ).state == JobState.PENDING
    assert await legacy.list_tasks_for_job(storage, job.job_id) == [replacement.task_id]
    assert (await storage.get_job_task_stats(job.job_id))["ready"] == 1
    assert store.get(job.job_id)["status"] == "ready"


@pytest.mark.parametrize("boundary", ["sql_batch", "marker"])
async def test_old_archive_cannot_write_rows_or_marker_after_edit(
    store, window_runtime, monkeypatch, boundary
):
    job, storage, manager = await cancelled_window(store, window_runtime)
    entered, release = threading.Event(), threading.Event()
    if boundary == "sql_batch":
        write = JobStorage._upsert_central_tasks_sync

        def pause_before_batch(rows):
            entered.set()
            assert release.wait(5), "test did not release the archive writer"
            return write(rows)

        monkeypatch.setattr(
            JobStorage, "_upsert_central_tasks_sync", staticmethod(pause_before_batch)
        )
    else:
        publish = JobStorage._publish_task_archive_marker

        async def pause_before_marker(self, *args):
            entered.set()
            assert await asyncio.to_thread(release.wait, 5)
            return await publish(self, *args)

        monkeypatch.setattr(
            JobStorage, "_publish_task_archive_marker", pause_before_marker
        )
    archive = asyncio.create_task(
        window_runtime.writes.submit(
            DatabaseWriteOperation.ARCHIVE_JOB_TASKS, archive_payload(job)
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        replacement = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=8)
        await manager.update_job_by_id(job.job_id, tasks=[replacement])
        release.set()
        outcome = await asyncio.wait_for(archive, 5)
        assert outcome == {"archived_tasks": 0, "stale": True}
        assert not await storage._client().exists(
            storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
        )
        assert await legacy.list_tasks_for_job(storage, job.job_id) == [replacement.task_id]
        with store.session_factory() as session:
            assert (
                session.scalar(
                    text("SELECT count(*) FROM management.job_tasks WHERE job_id=:id"),
                    {"id": job.job_id},
                )
                == 0
            )
    finally:
        release.set()
        await asyncio.gather(archive, return_exceptions=True)


async def test_archive_retries_instead_of_waiting_on_an_edit_in_its_writer_lane(
    store, window_runtime
):
    job, storage, _manager = await cancelled_window(store, window_runtime)
    client = storage._client()
    lock = mps_attempt.lock_key(job.job_id)
    await client.set(lock, "mps-edit:fixture", ex=30)
    command_id = uuid4().hex
    try:
        with pytest.raises(mps_attempt.DefinitionEditInProgress):
            await asyncio.wait_for(
                window_runtime.writes.submit(
                    DatabaseWriteOperation.ARCHIVE_JOB_TASKS,
                    archive_payload(job),
                    command_id=command_id,
                ),
                2,
            )
    finally:
        await client.delete(lock)
    assert await window_runtime.writes.submit(
        DatabaseWriteOperation.ARCHIVE_JOB_TASKS,
        archive_payload(job),
        command_id=command_id,
    ) == {"archived_tasks": 1}


async def test_expired_cleanup_lease_does_not_delete_successor_lease(
    store, window_runtime
):
    job, storage, manager = await cancelled_window(store, window_runtime)
    key = f"ultimascraper:job:{job.job_id}:terminal_cleanup_lock"

    class ExpireDuringArchive:
        async def submit(self, *args, **kwargs):
            result = await window_runtime.writes.submit(*args, **kwargs)
            await storage._client().set(key, "successor-owner", ex=30)
            return result

    manager.database_writes = ExpireDuringArchive()
    await manager.finalize_job_cancellation(job.job_id)
    assert await storage._client().get(key) == b"successor-owner"
    assert await legacy.list_tasks_for_job(storage, job.job_id) == []
    assert await storage._client().hget(mps_state.BUDGET_KEY, "tasks") == b"0"


async def test_dedup_cleanup_does_not_release_a_new_owner_between_read_and_delete(
    store, window_runtime, monkeypatch
):
    job, storage, manager = await cancelled_window(store, window_runtime)
    task = [task async for task in storage.fetch_tasks_stream(job.job_id)][0]
    client = storage._client()
    key = storage.DEDUPE_KEY.format(dedup=task.dedup_key)
    await client.set(key, task.task_id)
    mget = client.mget
    replaced = False

    async def replace_owner_after_read(keys, *args):
        nonlocal replaced
        result = await mget(keys, *args)
        if list(keys) == [key] and not replaced:
            replaced = True
            await client.set(key, "another-job-task")
        return result

    monkeypatch.setattr(client, "mget", replace_owner_after_read)
    await manager.finalize_job_cancellation(job.job_id)
    assert replaced
    assert await client.get(key) == b"another-job-task"


async def test_api_reports_definition_conflict_from_real_cancellation(
    store, window_runtime, monkeypatch
):
    from fastapi import HTTPException
    from ultima_scraper_backend.api.routes import jobs

    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=False
    )
    job_id = plan["job_id"]
    replacement = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=8)

    async def replace_during_assignment(_job_id):
        # This is a separate API request, with no cancellation attempt context.
        await asyncio.create_task(
            manager.update_job_by_id(job_id, tasks=[replacement]), context=Context()
        )
        return None

    # Updates resolve routing too; restore the real method before doing the edit.
    resolve = manager._resolve_backend_assignment

    async def replace_once(_job_id):
        monkeypatch.setattr(manager, "_resolve_backend_assignment", resolve)
        return await replace_during_assignment(_job_id)

    monkeypatch.setattr(manager, "_resolve_backend_assignment", replace_once)
    monkeypatch.setattr(jobs, "JobManager", lambda _redis: manager)
    publish = AsyncMock()
    monkeypatch.setattr(jobs, "publish_ws_event", publish)
    with pytest.raises(HTTPException) as conflict:
        await jobs.cancel_job(job_id, backend=window_runtime)
    assert conflict.value.status_code == 409
    publish.assert_not_awaited()
    assert (
        await storage.fetch_job(job_id, include_tasks=False)
    ).state == JobState.PENDING
