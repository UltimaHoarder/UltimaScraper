"""Explicit deletion must remove durable work without archive-sized reads."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

import test_mps_job_edits as fixtures
from test_mps_terminal_ownership import cancelled_window
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.job_system import Job, JobState, JobStorage, Task, TaskType
from ultima_scraper_backend.job_system import mps_attempt, mps_state
from ultima_scraper_db_archive import global_db
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


@pytest.fixture
def route_runtime(postgres_engine, window_runtime, monkeypatch):
    from ultima_scraper_db_archive.execution_models import EXECUTION_MODELS
    with postgres_engine.begin() as connection:
        for model in EXECUTION_MODELS:
            model.__table__.create(connection, checkfirst=True)

    @contextmanager
    def session_factory():
        with Session(postgres_engine) as session:
            session.execute(
                text("SET LOCAL search_path = onlyfans, management, public")
            )
            yield session

    redis = window_runtime.redis
    for name in ("delete", "lrem", "srem", "hgetall"):
        setattr(redis, name, getattr(redis.client, name))
    monkeypatch.setattr(global_db, "global_session", session_factory)
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    return window_runtime


@pytest.mark.parametrize("explicit", [False, True])
async def test_delete_removes_durable_plan_and_releases_window(
    store, route_runtime, explicit
):
    plan, storage, manager = await fixtures.prepared_window(
        store, route_runtime, archived=False
    )
    job_id = plan["job_id"]
    if explicit:
        await manager.update_job_by_id(
            job_id,
            tasks=[Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=7)],
        )
    response = await jobs.delete_job(job_id, backend=route_runtime)
    assert response == {"status": "deleted", "job_id": job_id}
    assert store.get(job_id) is None
    assert await storage.fetch_job(job_id, include_tasks=False) is None
    assert await storage.list_task_ids_window(job_id, offset=0, limit=10) == []
    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "tasks") or 0) == 0
    assert not await storage._client().exists(mps_state.PLAN_KEY.format(job_id=job_id))
    assert await mps_durable.recover(route_runtime) == ""
    assert await storage.fetch_job(job_id, include_tasks=False) is None


async def test_delete_does_not_read_whole_task_or_key_collections(
    store, route_runtime, monkeypatch
):
    plan, _storage, _manager = await fixtures.prepared_window(
        store, route_runtime, archived=False
    )
    monkeypatch.setattr(
        route_runtime.redis,
        "keys",
        AsyncMock(side_effect=AssertionError("whole keyspace")),
    )
    await jobs.delete_job(plan["job_id"], backend=route_runtime)
    assert store.get(plan["job_id"]) is None


async def test_delete_rejects_active_edit_without_removing_sql(store, route_runtime):
    plan, storage, _manager = await fixtures.prepared_window(
        store, route_runtime, archived=False
    )
    job_id = plan["job_id"]
    lock_key = mps_attempt.lock_key(job_id)
    await storage._client().set(lock_key, "mps-edit:other", ex=30)
    try:
        with pytest.raises(HTTPException) as error:
            await jobs.delete_job(job_id, backend=route_runtime)
        assert error.value.status_code == 409
        assert store.get(job_id) is not None
        assert await storage.get_total_task_count(job_id) == 1_000_000
        assert (
            await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job_id))
            == 3
        )
    finally:
        await storage._client().delete(lock_key)


async def test_stale_publication_cannot_recreate_deleted_job(store, route_runtime):
    plan, storage, _manager = await fixtures.prepared_window(
        store, route_runtime, archived=False
    )
    await jobs.delete_job(plan["job_id"], backend=route_runtime)
    try:
        await mps_durable.ensure_plan(storage, plan)
    except mps_attempt.StaleTaskDefinition:
        pass
    assert await storage.fetch_job(plan["job_id"], include_tasks=False) is None
    assert not await storage._client().exists(
        mps_state.PLAN_KEY.format(job_id=plan["job_id"])
    )


async def test_old_runtime_delete_cannot_purge_a_replacement(
    store, route_runtime, monkeypatch
):
    plan, storage, manager = await fixtures.prepared_window(
        store, route_runtime, archived=False
    )
    job_id = plan["job_id"]
    entered, release = asyncio.Event(), asyncio.Event()
    read = storage.list_task_ids_window

    async def pause_after_read(*args, **kwargs):
        result = await read(*args, **kwargs)
        if not entered.is_set():
            entered.set()
            await release.wait()
        return result

    monkeypatch.setattr(storage, "list_task_ids_window", pause_after_read)
    deletion = asyncio.create_task(storage.delete_job(job_id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        replacement = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=7)
        await manager.update_job_by_id(job_id, tasks=[replacement])
        release.set()
        try:
            await asyncio.wait_for(deletion, 5)
        except mps_attempt.StaleTaskDefinition:
            pass
        assert await legacy.list_tasks_for_job(storage, job_id) == [replacement.task_id]
        assert (await storage.get_job_task_stats(job_id))["ready"] == 1
    finally:
        release.set()
        if not deletion.done():
            deletion.cancel()
        await asyncio.gather(deletion, return_exceptions=True)


async def test_sql_failure_does_not_remove_runtime(store, route_runtime, monkeypatch):
    plan, storage, _manager = await fixtures.prepared_window(
        store, route_runtime, archived=False
    )
    session_factory = global_db.global_session

    @contextmanager
    def unavailable_writer():
        with session_factory() as session:
            monkeypatch.setattr(
                session,
                "commit",
                lambda: (_ for _ in ()).throw(
                    OperationalError(
                        "fixture failure", {}, RuntimeError("database down")
                    )
                ),
            )
            yield session

    monkeypatch.setattr(global_db, "global_session", unavailable_writer)
    with pytest.raises(HTTPException) as error:
        await jobs.delete_job(plan["job_id"], backend=route_runtime)
    assert error.value.status_code == 503
    assert store.get(plan["job_id"]) is not None
    assert (
        await storage._client().zcard(
            storage.TASK_INDEX_KEY.format(job_id=plan["job_id"])
        )
        == 3
    )
    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "tasks")) == 3


async def test_retry_after_sql_commit_finishes_runtime_cleanup(
    store, route_runtime, monkeypatch
):
    plan, storage, _manager = await fixtures.prepared_window(
        store, route_runtime, archived=False
    )
    with monkeypatch.context() as interrupted:
        interrupted.setattr(
            JobStorage,
            "_delete_job_runtime",
            AsyncMock(side_effect=ConnectionError("fixture interruption")),
        )
        with pytest.raises(ConnectionError, match="fixture interruption"):
            await jobs.delete_job(plan["job_id"], backend=route_runtime)
    assert store.get(plan["job_id"]) is None
    assert (
        await storage.fetch_job(plan["job_id"], include_tasks=False)
    ).state.value == "cancelled"
    task_ids = await storage.list_task_ids_window(plan["job_id"], offset=0, limit=3)
    assert not await mps_state.claim_task(storage, plan["job_id"], task_ids[0])
    assert await mps_durable.recover(route_runtime) == ""
    await jobs.delete_job(plan["job_id"], backend=route_runtime)
    assert await storage.fetch_job(plan["job_id"], include_tasks=False) is None
    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "tasks")) == 0


async def test_delete_sql_only_plan_after_redis_loss(store, route_runtime):
    plan, storage, _manager = await fixtures.prepared_window(
        store, route_runtime, archived=False
    )
    await storage._client().flushall()  # This fixture owns the empty Redis server.
    await jobs.delete_job(plan["job_id"], backend=route_runtime)
    assert store.get(plan["job_id"]) is None
    assert await storage.fetch_job(plan["job_id"], include_tasks=False) is None


async def test_mps_delete_requires_available_coordination(store, route_runtime):
    plan, _storage, _manager = await fixtures.prepared_window(
        store, route_runtime, archived=False
    )
    with pytest.raises(HTTPException) as error:
        await jobs.delete_job(plan["job_id"], backend=SimpleNamespace(redis=None))
    assert error.value.status_code == 503
    assert store.get(plan["job_id"]) is not None


async def test_delete_cannot_remove_definition_edited_before_sql_lock(
    store, route_runtime, monkeypatch
):
    plan, storage, manager = await fixtures.prepared_window(
        store, route_runtime, archived=False
    )
    entered, release = asyncio.Event(), asyncio.Event()
    edit_lock = mps_durable._schedule_edit_lock

    @asynccontextmanager
    async def pause_before_lock(*args, **kwargs):
        if not entered.is_set():
            entered.set()
            await release.wait()
        async with edit_lock(*args, **kwargs) as lease:
            yield lease

    monkeypatch.setattr(mps_durable, "_schedule_edit_lock", pause_before_lock)
    deletion = asyncio.create_task(
        jobs.delete_job(plan["job_id"], backend=route_runtime)
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        replacement = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=7)
        await manager.update_job_by_id(plan["job_id"], tasks=[replacement])
        release.set()
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(deletion, 5)
        assert error.value.status_code == 409
        assert store.get(plan["job_id"]) is not None
        assert await legacy.list_tasks_for_job(storage, plan["job_id"]) == [replacement.task_id]
    finally:
        release.set()
        if not deletion.done():
            deletion.cancel()
        await asyncio.gather(deletion, return_exceptions=True)


async def test_ordinary_large_job_deletes_with_explicit_batch_setting(
    store, route_runtime, monkeypatch
):
    storage = JobStorage(route_runtime.redis)
    job = Job.create(name="Ordinary deletion fixture", created_by="fixture", tasks=[])
    await storage.persist_job(job, persist_tasks=False)
    for start in range(0, 520, 20):
        await storage.persist_tasks(
            job.job_id,
            [
                Task(
                    task_id=f"ordinary-{i}",
                    task_type=TaskType.SCRAPE,
                    site_name="OnlyFans",
                    user_id=i,
                )
                for i in range(start, start + 20)
            ],
        )
    windows = []
    read = JobStorage.list_task_ids_window

    async def record(self, *args, **kwargs):
        result = await read(self, *args, **kwargs)
        windows.append((kwargs["limit"], len(result)))
        return result

    monkeypatch.setenv("ULTIMA_RECOVERY_SCAN_COUNT", "7")
    monkeypatch.setattr(JobStorage, "list_task_ids_window", record)
    await jobs.delete_job(job.job_id, backend=route_runtime)
    assert await storage.fetch_job(job.job_id, include_tasks=False) is None
    # Dedupe cleanup retains its existing bounded 1000-item reads; task deletion
    # uses the explicit recovery setting, including its final partial page.
    purges = [length for limit, length in windows if limit == 7 and length]
    assert sum(purges) == 520 and max(purges) == 7
    assert all(length <= limit for limit, length in windows)


async def test_unknown_job_returns_not_found(route_runtime):
    with pytest.raises(HTTPException) as error:
        await jobs.delete_job("absent-job", backend=route_runtime)
    assert error.value.status_code == 404


async def test_delete_cancels_live_runtime_before_removing_it(route_runtime, monkeypatch):
    storage = JobStorage(route_runtime.redis)
    job = Job.create(name="Live deletion fixture", created_by="fixture", tasks=[])
    await storage.persist_job(job, persist_tasks=False)
    cancellation = AsyncMock(return_value={"job_id": job.job_id, "status": "cancelled"})
    monkeypatch.setattr(jobs, "cancel_job", cancellation)

    await jobs.delete_job(job.job_id, backend=route_runtime)

    cancellation.assert_awaited_once_with(job.job_id, backend=route_runtime)
    assert await storage.fetch_job(job.job_id, include_tasks=False) is None


async def test_delete_does_not_recancel_cancelled_materializing_job(route_runtime, monkeypatch):
    storage = JobStorage(route_runtime.redis)
    job = Job.create(name="Cancelled deletion fixture", created_by="fixture", tasks=[])
    job.state = JobState.CANCELLED
    job.metadata["materialization_status"] = "materializing"
    await storage.persist_job(job, persist_tasks=False)
    cancellation = AsyncMock(side_effect=AssertionError("cancelled job was recancelled"))
    monkeypatch.setattr(jobs, "cancel_job", cancellation)

    await jobs.delete_job(job.job_id, backend=route_runtime)

    cancellation.assert_not_awaited()
    assert await storage.fetch_job(job.job_id, include_tasks=False) is None


async def test_retention_receipt_cannot_delete_a_replacement(store, route_runtime):
    job, storage, manager = await cancelled_window(store, route_runtime)
    entered, release = asyncio.Event(), asyncio.Event()

    async def archive_then_pause(*args, **kwargs):
        result = await route_runtime.writes.submit(*args, **kwargs)
        entered.set()
        await release.wait()
        return result

    storage.database_writes = SimpleNamespace(submit=archive_then_pause, max_command_bytes=route_runtime.writes.max_command_bytes)
    cleanup = asyncio.create_task(storage.cleanup_completed_jobs(0))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        replacement = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=8)
        await manager.update_job_by_id(job.job_id, tasks=[replacement])
        release.set()
        assert await asyncio.wait_for(cleanup, 5) == 0
        assert await legacy.list_tasks_for_job(storage, job.job_id) == [replacement.task_id]
        assert (await storage.get_job_task_stats(job.job_id))["ready"] == 1
    finally:
        release.set()
        if not cleanup.done():
            cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)


async def test_stale_metadata_publisher_cannot_restore_deleted_header(
    store, route_runtime
):
    plan, storage, _manager = await fixtures.prepared_window(
        store, route_runtime, archived=False
    )
    await jobs.delete_job(plan["job_id"], backend=route_runtime)
    with pytest.raises(mps_attempt.StaleTaskDefinition):
        await mps_durable.ensure_job(storage, plan)
    assert await storage.fetch_job(plan["job_id"], include_tasks=False) is None


async def test_delete_job_purges_tasks_in_chunks_and_cleans_db(
    route_runtime,
):
    from ultima_scraper_db_archive.global_db import (
        CentralJobModel, CentralTaskModel, global_session,
    )
    from sqlmodel import select as sql_select

    job_id = "test-job-chunked-delete"
    with global_session() as session:
        session.add(
            CentralJobModel(
                job_id=job_id,
                job_type="mass_profile_scrape",
                site="onlyfans",
                status="completed",
            )
        )
        for i in range(12):
            session.add(
                CentralTaskModel(
                    task_id=f"chunked-task-{i}",
                    job_id=job_id,
                    task_type="scrape",
                    status="completed",
                )
            )
        session.commit()

    response = await jobs.delete_job(job_id, backend=route_runtime)
    assert response == {"status": "deleted", "job_id": job_id}

    with global_session() as session:
        assert session.get(CentralJobModel, job_id) is None
        remaining = session.execute(
            sql_select(CentralTaskModel).where(CentralTaskModel.job_id == job_id)
        ).scalars().all()
        assert len(remaining) == 0

