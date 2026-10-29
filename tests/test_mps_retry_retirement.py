"""Retry recovery must propagate the durable source cancellation safely."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import test_mps_graph_retry as retry_fixtures
import test_mps_job_edits as fixtures
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.api.routes import mps_durable as mps_submission
from ultima_scraper_backend.job_system import (
    JobManager,
    JobState,
    JobStorage,
    Task,
    TaskType,
)
from ultima_scraper_backend.job_system.mps_attempt import lock_key
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


@pytest.fixture
def runtime(window_runtime, monkeypatch):
    window_runtime.redis.delete = window_runtime.redis.client.delete
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "6")

    def manager(redis):
        instance = JobManager(redis)
        instance.database_writes = window_runtime.writes
        return instance

    # Use real manager cleanup and the owned fixture's SQL writer, rather than
    # replacing retirement with a stub or waiting for an absent queue consumer.
    monkeypatch.setattr(mps_durable, "JobManager", manager)
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    return window_runtime


@pytest.mark.parametrize("explicit", [False, True])
async def test_live_retry_releases_its_edit_lease_before_source_cleanup(
    store, runtime, explicit
):
    plan, storage, manager = await fixtures.prepared_window(
        store, runtime, archived=False
    )
    source_id = plan["job_id"]
    if explicit:
        await manager.update_job_by_id(
            source_id,
            tasks=[Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=11)],
        )
    result = await asyncio.wait_for(
        mps_submission.retry_job(
            store.get(source_id), request=SimpleNamespace(auth_id=None), backend=runtime
        ),
        3,
    )
    assert result.task_count == (1 if explicit else 1_000_000)
    assert store.get(source_id)["status"] == "cancelled"
    assert (
        await storage.fetch_job(source_id, include_tasks=False)
    ).state == JobState.CANCELLED
    assert await legacy.list_tasks_for_job(storage, source_id) == []
    assert not await storage._client().exists(lock_key(source_id))
    await mps_durable.advance(runtime, result.job_id)
    assert len(await legacy.list_tasks_for_job(storage, result.job_id)) == (
        1 if explicit else 3
    )


async def test_retry_recovery_does_not_cancel_a_replacement_source(store, runtime):
    plan, storage, manager = await fixtures.prepared_window(
        store, runtime, archived=False
    )
    retried = retry_fixtures.clone(store, store.get(plan["job_id"]))
    replacement = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=8)
    await manager.update_job_by_id(plan["job_id"], tasks=[replacement])
    await mps_durable.advance(runtime, retried["job_id"])
    current = await storage.fetch_job(plan["job_id"], include_tasks=False)
    assert current.state == JobState.PENDING
    assert store.get(plan["job_id"])["status"] == "ready"
    assert await legacy.list_tasks_for_job(storage, plan["job_id"]) == [replacement.task_id]
    assert (await storage.get_job_task_stats(plan["job_id"]))["ready"] == 1
    assert len(await legacy.list_tasks_for_job(storage, retried["job_id"])) == 3


async def test_retirement_snapshot_cannot_cancel_an_edit_that_wins_during_cleanup(
    store, runtime, monkeypatch
):
    plan, storage, manager = await fixtures.prepared_window(
        store, runtime, archived=False
    )
    job_id = plan["job_id"]
    retried = retry_fixtures.clone(store, store.get(job_id))
    entered, release = asyncio.Event(), asyncio.Event()
    resolve = JobManager._resolve_backend_assignment
    retirement = None

    async def pause_retirement(self, source_id):
        if source_id == job_id and asyncio.current_task() is retirement:
            entered.set()
            await release.wait()
        return await resolve(self, source_id)

    monkeypatch.setattr(JobManager, "_resolve_backend_assignment", pause_retirement)
    retirement = asyncio.create_task(mps_durable._retire_retry_source(storage, retried))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        replacement = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=8)
        await manager.update_job_by_id(job_id, tasks=[replacement])
        release.set()
        await asyncio.wait_for(retirement, 3)
        assert (
            await storage.fetch_job(job_id, include_tasks=False)
        ).state == JobState.PENDING
        assert await legacy.list_tasks_for_job(storage, job_id) == [replacement.task_id]
        assert (await storage.get_job_task_stats(job_id))["ready"] == 1
    finally:
        release.set()
        if not retirement.done():
            retirement.cancel()
        await asyncio.gather(retirement, return_exceptions=True)


@pytest.mark.parametrize(
    "recovery_case", ["retained-source", "empty-redis", "edited-source-empty-redis"]
)
async def test_committed_retry_recovers_after_publication_failure(
    store, runtime, monkeypatch, recovery_case
):
    plan, storage, manager = await fixtures.prepared_window(
        store, runtime, archived=False
    )
    source_id = plan["job_id"]
    interrupted = AsyncMock(side_effect=ConnectionError("interrupted after SQL clone"))
    with monkeypatch.context() as failed:
        failed.setattr(mps_submission, "_publish_retry_job", interrupted)
        with pytest.raises(ConnectionError, match="after SQL clone"):
            await mps_submission.retry_job(
                store.get(source_id),
                request=SimpleNamespace(auth_id=None),
                backend=runtime,
            )
    prepared = interrupted.await_args.args[0]
    retry_id = prepared["job_id"]
    assert store.get(retry_id)["total"] == 1_000_000
    assert store.get(source_id)["status"] == "cancelled"
    assert not await storage._client().exists(lock_key(source_id))
    replacement = None
    if recovery_case == "edited-source-empty-redis":
        replacement = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=8)
        await manager.update_job_by_id(source_id, tasks=[replacement])
    if recovery_case != "retained-source":
        await storage._client().flushdb()  # This fixture owns this Redis server.
    await mps_durable.recover(runtime)
    await mps_durable.advance(runtime, retry_id)
    restored = JobStorage(runtime.redis)
    assert len(await legacy.list_tasks_for_job(restored, retry_id)) == 3
    if replacement is not None:
        await mps_durable.advance(runtime, source_id)
        assert (
            await restored.fetch_job(source_id, include_tasks=False)
        ).state == JobState.PENDING
        assert await legacy.list_tasks_for_job(restored, source_id) == [replacement.task_id]
        assert store.get(source_id)["status"] == "ready"
    elif recovery_case == "retained-source":
        assert (
            await restored.fetch_job(source_id, include_tasks=False)
        ).state == JobState.CANCELLED
        assert await legacy.list_tasks_for_job(restored, source_id) == []
    else:
        assert await restored.fetch_job(source_id, include_tasks=False) is None
    assert store.get(retry_id)["total"] == 1_000_000
