"""Native/fake Redis recovery races and bounded sparse-history scans."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

import test_database_write_queue as redis_fixtures
from test_job_system import FakeRedisManager
from ultima_scraper_backend.job_system import recovery_scripts
from ultima_scraper_backend.job_system.models import Task, TaskState, TaskType
from ultima_scraper_backend.job_system.mps_state import DEFERRED_RETENTION_MEMBER
from ultima_scraper_backend.job_system.routing import BackendRouter
from ultima_scraper_backend.job_system.storage import JobStorage
import legacy_redis_runtime as legacy

# These exercise the Redis runtime; the SQL execution ledger holds no runs.
pytestmark = pytest.mark.usefixtures("no_ledger_runs")

redis_manager = redis_fixtures.redis_manager


@pytest.fixture
def storage(redis_manager):
    return JobStorage(FakeRedisManager(redis_manager.client))


async def deferred(
    storage,
    *,
    task_id="one",
    job_id="job",
    state="deferred",
    dedup="fixture",
    mps=False,
):
    client = storage._client()
    task = Task(
        task_id=task_id,
        user_id=9007199254740993,
        task_type=TaskType.SCRAPE,
        state=TaskState(state),
        deferred_dedup_key=dedup,
        payload={"precision": 9007199254740993},
    )
    task_key = storage.TASK_KEY.format(job_id=job_id, task_id=task_id)
    await client.set(task_key, json.dumps(task.to_dict()), ex=600)
    await client.hset(
        storage.JOB_STATE_KEY.format(job_id=job_id),
        mapping={
            "status": "running",
            "backend_id": "backend",
            "deferred_tasks": 1,
            "ready_tasks": 0,
            "mps_manifest": int(mps),
        },
    )
    member = f"{job_id}:{task_id}"
    key = storage.DEFERRED_TASKS_KEY.format(dedup_key=dedup)
    await client.sadd(key, member)
    if mps:
        await client.sadd(key, DEFERRED_RETENTION_MEMBER)
    return task_key, key, member


@pytest.mark.asyncio
async def test_requeue_commits_state_counter_and_queue_atomically(storage, monkeypatch):
    client = storage._client()
    task_key, key, member = await deferred(storage, mps=True)
    await client.set(
        storage.JOB_CONFIG_KEY.format(job_id="job"),
        json.dumps({"metadata": {"priority": -3}}),
    )
    monkeypatch.setattr(
        BackendRouter,
        "enqueue_ready_task",
        AsyncMock(side_effect=AssertionError("enqueue must be in the transition")),
    )
    assert await storage.requeue_deferred_tasks_for_dedup("fixture") == 1
    task = json.loads(await client.get(task_key))
    assert task["state"] == "pending"
    assert task["payload"]["precision"] == 9007199254740993
    assert task["user_id"] == 9007199254740993
    assert 0 < await client.ttl(task_key) <= 600
    assert not await client.exists(key)
    assert await client.ttl(storage.TASKS_READY_KEY.format(job_id="job")) == -1
    assert (
        await client.hget(storage.JOB_STATE_KEY.format(job_id="job"), "ready_tasks")
        == b"1"
    )
    assert (
        await client.hget(storage.JOB_STATE_KEY.format(job_id="job"), "deferred_tasks")
        == b"0"
    )
    assert (
        await client.zscore(BackendRouter.QUEUE_PREFIX + "backend", member)
        == -3 * BackendRouter.READY_SCORE_SCALE + 1
    )
    assert await storage.requeue_deferred_tasks_for_dedup("fixture") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", ["completed", "failed", "cancelled", "running", "pending"]
)
async def test_stale_deferred_members_never_resurrect_tasks(storage, state):
    client = storage._client()
    task_key, key, member = await deferred(storage, state=state)
    before = await client.get(task_key)
    assert await storage.requeue_deferred_tasks_for_dedup("fixture") == 0
    assert await client.get(task_key) == before
    assert not await client.sismember(key, member)
    assert not await client.exists(storage.TASKS_READY_KEY.format(job_id="job"))
    assert not await client.exists(BackendRouter.QUEUE_PREFIX + "backend")


@pytest.mark.asyncio
async def test_missing_task_is_not_reconstructed_from_a_marker(storage):
    task_key, key, member = await deferred(storage)
    await storage._client().delete(task_key)
    assert await storage.requeue_deferred_tasks_for_dedup("fixture") == 0
    assert not await storage._client().sismember(key, member)
    assert not await storage._client().exists(task_key)


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["task", "job", "owner", "exec", "dedup", "backend"])
async def test_requeue_rechecks_state_and_ownership_at_mutation(
    storage, monkeypatch, race
):
    client = storage._client()
    task_key, key, member = await deferred(storage)
    original = client.eval
    mutated = False

    async def racing(script, numkeys, *args):
        nonlocal mutated
        if script == recovery_scripts.REQUEUE_DEFERRED and not mutated:
            mutated = True
            if race == "task":
                blob = json.loads(await client.get(task_key))
                blob["state"] = "completed"
                await client.set(task_key, json.dumps(blob))
            elif race == "job":
                await client.hset(
                    storage.JOB_STATE_KEY.format(job_id="job"), "status", "cancelled"
                )
            elif race == "owner":
                await client.set(
                    storage.DEFERRED_REQUEUE_LOCK_KEY.format(dedup_key="fixture"),
                    "replacement",
                    ex=30,
                )
            elif race == "exec":
                await client.set(
                    storage.TASK_EXEC_LOCK_KEY.format(task_id="one"), "worker", ex=30
                )
            elif race == "dedup":
                await client.set(
                    storage.DEDUPE_KEY.format(dedup="fixture"), "other", ex=30
                )
            elif race == "backend":
                await client.hset(
                    storage.JOB_STATE_KEY.format(job_id="job"),
                    "backend_id",
                    "elsewhere",
                )
        return await original(script, numkeys, *args)

    monkeypatch.setattr(client, "eval", racing)
    assert await storage.requeue_deferred_tasks_for_dedup("fixture") == 0
    assert mutated
    assert not await client.exists(BackendRouter.QUEUE_PREFIX + "backend")
    assert not await client.exists(storage.TASKS_READY_KEY.format(job_id="job"))
    blob = json.loads(await client.get(task_key))
    assert blob["state"] == ("completed" if race == "task" else "deferred")
    if race == "owner":
        assert (
            await client.get(
                storage.DEFERRED_REQUEUE_LOCK_KEY.format(dedup_key="fixture")
            )
            == b"replacement"
        )


@pytest.mark.asyncio
async def test_redeferred_marker_survives_successful_atomic_requeue(
    storage, monkeypatch
):
    client = storage._client()
    task_key, key, member = await deferred(storage)
    original = client.eval

    async def redefer_after(script, numkeys, *args):
        result = await original(script, numkeys, *args)
        if script == recovery_scripts.REQUEUE_DEFERRED and result == 1:
            await legacy.mark_task_deferred(storage, "job", "one", "fixture")
        return result

    monkeypatch.setattr(client, "eval", redefer_after)
    assert await storage.requeue_deferred_tasks_for_dedup("fixture") == 1
    assert await client.sismember(key, member)
    assert json.loads(await client.get(task_key))["state"] == "deferred"


@pytest.mark.asyncio
async def test_deferred_scan_never_collects_the_whole_set(
    storage, monkeypatch, request
):
    for index in range(12):
        await deferred(storage, task_id=str(index))
    monkeypatch.setattr(storage, "DEFAULT_WRITE_BATCH_SIZE", 3)
    monkeypatch.setattr(
        storage._client(), "smembers", AsyncMock(side_effect=AssertionError("SMEMBERS"))
    )
    requeued = await storage.requeue_deferred_tasks_for_dedup("fixture")
    if request.node.callspec.params["redis_manager"] == "real":
        assert requeued == 12
    else:
        # fakeredis uses positional SSCAN cursors; deleting visited entries can
        # move unread entries behind that cursor. Redis's native cursor is also
        # tested above and must complete this fixed set in one pass.
        for _ in range(3):
            requeued += await storage.requeue_deferred_tasks_for_dedup("fixture")
        assert requeued == 12
    assert await storage._client().zcard(BackendRouter.QUEUE_PREFIX + "backend") == 12


@pytest.mark.asyncio
async def test_sparse_history_stops_at_budget_and_continues_without_skipping(
    storage, monkeypatch
):
    monkeypatch.setenv("ULTIMA_TASK_PAGE_SCAN_ENTRIES", "7")
    monkeypatch.setattr(
        storage, "get_total_task_count", AsyncMock(return_value=1_000_000)
    )
    visited = []

    async def window(job_id, *, offset, limit, reverse=False):
        visited.extend(range(offset, offset + limit))
        return [str(index) for index in range(offset, offset + limit)]

    async def tasks(job_id, ids):
        return [
            Task(
                task_id=key,
                user_id=int(key),
                task_type=TaskType.SCRAPE,
                state=TaskState.FAILED if key == "9" else TaskState.PENDING,
            )
            for key in ids
        ]

    monkeypatch.setattr(storage, "list_task_ids_window", window)
    monkeypatch.setattr(storage, "fetch_tasks_by_ids", tasks)
    first = await storage.fetch_task_page("million", limit=2, state="failed")
    assert first.tasks == [] and first.next_cursor == "7" and first.has_more
    assert visited == list(range(7))
    second = await storage.fetch_task_page(
        "million", cursor=first.next_cursor, limit=2, state="failed"
    )
    assert [task.task_id for task in second.tasks] == ["9"]
    assert second.next_cursor == "14" and second.has_more
    assert visited == list(range(14))


@pytest.mark.asyncio
async def test_page_budget_may_be_smaller_than_requested_page(storage, monkeypatch):
    monkeypatch.setenv("ULTIMA_TASK_PAGE_SCAN_ENTRIES", "1")
    monkeypatch.setattr(storage, "get_total_task_count", AsyncMock(return_value=100))
    window = AsyncMock(return_value=["task"])
    monkeypatch.setattr(storage, "list_task_ids_window", window)
    monkeypatch.setattr(storage, "fetch_tasks_by_ids", AsyncMock(return_value=[None]))
    page = await storage.fetch_task_page("job", limit=100)
    assert page.next_cursor == "1" and page.has_more and page.tasks == []
    window.assert_awaited_once_with("job", offset=0, limit=1, reverse=False)
