"""Retain task results through worker completion and subsequent archival.

These use owned PostgreSQL and fake/native Redis fixtures. The handler is a
deterministic substitute for the external API; task execution, terminal state,
SQL window archival and Redis cleanup run through the production code.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import test_mps_manifest as mps_fixtures
from ultima_scraper_backend.job_system import JobStorage, TaskResult, TaskState
from ultima_scraper_backend.job_system.models import Task, TaskType
import legacy_redis_runtime as legacy

postgres_engine = mps_fixtures.postgres_engine
store = mps_fixtures.store
redis_manager = mps_fixtures.redis_manager
window_runtime = mps_fixtures.window_runtime


@pytest.fixture
def redis_storage(redis_manager):
    client = redis_manager.client
    return JobStorage(SimpleNamespace(
        client=client, get=client.get, set=client.set, delete=client.delete
    ))


async def test_late_result_update_does_not_recreate_purged_task(redis_storage):
    storage = redis_storage
    task = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1)
    await storage.persist_task("retention-job", task)
    key = storage.TASK_KEY.format(job_id="retention-job", task_id=task.task_id)
    await storage._client().delete(key)
    task.result = TaskResult(success=True, message="finished")
    await legacy.persist_task_result(storage, "retention-job", task)
    assert not await storage._client().exists(key)


@pytest.mark.usefixtures("no_ledger_runs")
async def test_result_update_preserves_index_order_and_existing_expiry(redis_storage):
    storage = redis_storage
    client = storage._client()
    task = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1)
    await storage.persist_task("retention-job", task)
    key = storage.TASK_KEY.format(job_id="retention-job", task_id=task.task_id)
    index = storage.TASK_INDEX_KEY.format(job_id="retention-job")
    before_score = await client.zscore(index, task.task_id)
    await client.pexpire(key, 60_000)
    task.result = TaskResult(success=True, message="finished")
    task.state = TaskState.COMPLETED
    await legacy.persist_task_result(storage, "retention-job", task)
    assert (await storage.fetch_task("retention-job", task.task_id)).result.message == "finished"
    assert await client.zscore(index, task.task_id) == before_score
    assert 0 < await client.pttl(key) <= 60_000


async def test_state_update_does_not_recreate_task_purged_after_read(
    redis_storage, monkeypatch
):
    storage = redis_storage
    client = storage._client()
    task = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1)
    await storage.persist_task("retention-job", task)
    key = storage.TASK_KEY.format(job_id="retention-job", task_id=task.task_id)

    async def read_then_purge(requested_key):
        raw = await client.get(requested_key)
        assert requested_key == key
        await client.delete(key)
        return raw

    monkeypatch.setattr(storage.redis, "get", read_then_purge)
    await storage._set_task_state("retention-job", task.task_id, "completed")
    assert not await client.exists(key)


async def test_worker_accepts_own_materializer_reservation(redis_storage):
    storage = redis_storage
    client = storage._client()
    task = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1)
    key = storage.DEDUPE_KEY.format(dedup=task.dedup_key)
    assert await storage.reserve_dedup_many([task]) == [task.task_id]
    await client.expire(key, 1)
    assert await storage.reserve_dedup(task, ttl_seconds=60)
    assert 1 < await client.ttl(key) <= 60

    other_task = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1)
    assert not await storage.reserve_dedup(other_task, ttl_seconds=1)
    assert await client.get(key) in (task.task_id, task.task_id.encode())


async def test_late_worker_cleanup_preserves_new_dedup_owner(redis_storage):
    storage = redis_storage
    client = storage._client()
    old = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1)
    new = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1)
    key = storage.DEDUPE_KEY.format(dedup=old.dedup_key)
    assert await storage.reserve_dedup(old)
    # Simulate expiry followed by admission of another task before old cleanup.
    await client.delete(key)
    assert await storage.reserve_dedup(new)
    await storage.release_dedup(old)
    assert await client.get(key) in (new.task_id, new.task_id.encode())
    await storage.release_dedup(new)
    assert not await client.exists(key)
