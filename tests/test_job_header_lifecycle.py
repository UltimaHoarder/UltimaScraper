"""Owned SQL/Redis checks for bounded headers across competing job lifecycles.

Only sampled windows are executed by the fixture helper. SQL and Redis are real
for the native parameter; worker routing and writer transport use the existing
window fixture, so these checks are separate from creation-to-history timings.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text

import test_mps_manifest as fixtures
from test_normal_task_windows import admit
from test_normal_durable_inputs import task
from test_job_header_admission import assert_budget
from ultima_scraper_backend.job_system import (
    Job, JobManager, JobSchedule, JobState, JobStorage, durable, materializer,
    mps_state, runtime_admission,
)
from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


def generated(store, *, job_id="z-waiting", total=1_000_000):
    # Writer receipts outlive each fixture's plan rows. Distinct definitions
    # must also use distinct command identities across native/fake parameters.
    job_id = f"{job_id}-{uuid4().hex}"
    job = Job(name="Generated fixture", created_by="tests", job_id=job_id, tasks=[])
    return store.create(
        job_id=job_id, site="onlyfans", job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": total}, proxy_pool=[],
        site_session_factory=store.session_factory,
    )


async def finish_window(storage, job_id):
    tasks = await fixtures.complete_window(storage, job_id)
    for item in tasks:
        await storage.release_dedup(item)
    return tasks


@pytest.mark.parametrize("retirement", ["delete", "yield"])
async def test_header_retirement_reclaims_only_its_event_stream(
    store, window_runtime, monkeypatch, retirement,
):
    from ultima_scraper_backend.api.routes import jobs
    from ultima_scraper_backend.job_system.event_log import EventLog, EventType, JobEvent

    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "1")
    plan = generated(store)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await durable.advance(window_runtime, job_id)
    completed = await finish_window(storage, job_id)
    await durable.advance(window_runtime, job_id)
    plan = store.get(job_id)
    assert plan["cursor"] == 3
    log = EventLog(window_runtime.redis)
    await legacy.append_event(log, JobEvent(EventType.JOB_STARTED, job_id=job_id))
    await legacy.append_event(log, JobEvent(EventType.JOB_STARTED, job_id="unrelated-job"))
    own_stream = log._stream_key(job_id)
    assert await client.xlen(own_stream) == 1
    if retirement == "delete":
        await storage.delete_job(job_id)
    else:
        await client.set(runtime_admission.PRESSURE_KEY, "1")
        key = materializer._mps_materialization_lock_key(job_id)
        await client.set(key, "test-owner")
        assert await durable._yield_archived_header(storage, plan, lock_key=key, lock_owner="test-owner")
    assert not await client.exists(own_stream)
    assert await client.xlen(log._stream_key("unrelated-job")) == 1
    assert await client.xlen(log.GLOBAL_STREAM) == 2
    await assert_budget(client, storage, 0)
    page = await jobs.get_job_tasks(job_id, offset=0, limit=3, backend=window_runtime)
    assert {item.task_id for item in page.tasks} == {item.task_id for item in completed}
    assert all(item.status == "completed" for item in page.tasks)


async def test_one_header_rotates_between_ordinary_and_generated_jobs(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "1")
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    ordinary = await admit(window_runtime, tasks=[task(90+i, width=10) for i in range(4)])
    second = generated(store)
    assert ordinary.job_id < second["job_id"]  # ID order alone would starve the waiter.
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    waiting = await durable.publish(storage, second)
    assert waiting.total_tasks == 1_000_000 and not waiting.tasks
    await assert_budget(client, storage, 1)
    assert await storage.fetch_job(second["job_id"], include_tasks=False) is None

    started_at = "2026-09-12T01:02:03+00:00"
    current = await storage.fetch_job(ordinary.job_id, include_tasks=False)
    current.started_at, current.state = started_at, JobState.RUNNING
    await storage.persist_job(current)

    await materializer._materialize_mps_job(window_runtime, ordinary.job_id)
    first_ids = [item.task_id for item in await finish_window(storage, ordinary.job_id)]
    assert len(first_ids) == 2
    assert await materializer._materialize_mps_job(window_runtime, ordinary.job_id) is False
    assert store.get(ordinary.job_id)["cursor"] == 2
    await assert_budget(client, storage, 0)
    await durable.recover(window_runtime)
    assert await storage.fetch_job(ordinary.job_id, include_tasks=False) is None
    assert (await storage.fetch_job(second["job_id"], include_tasks=False)).total_tasks == 1_000_000
    await assert_budget(client, storage, 1)

    await materializer._materialize_mps_job(window_runtime, second["job_id"])
    assert len(await finish_window(storage, second["job_id"])) == 3
    await materializer._materialize_mps_job(window_runtime, second["job_id"])
    assert store.get(second["job_id"])["cursor"] == 3
    await assert_budget(client, storage, 0)
    await durable.recover(window_runtime)
    restored = await storage.fetch_job(ordinary.job_id, include_tasks=False)
    assert restored.completed_tasks_count == 2 and restored.total_tasks == 4
    assert restored.started_at == started_at and restored.state == JobState.RUNNING
    await materializer._materialize_mps_job(window_runtime, ordinary.job_id)
    last_ids = [item.task_id for item in await finish_window(storage, ordinary.job_id)]
    assert len(last_ids) == 2 and not set(first_ids).intersection(last_ids)
    await materializer._materialize_mps_job(window_runtime, ordinary.job_id)
    assert store.get(ordinary.job_id)["status"] == "complete"
    await assert_budget(client, storage, 0)
    await durable.recover(window_runtime)
    await assert_budget(client, storage, 1)
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 7
        assert session.scalar(text("SELECT count(*) FROM management.mps_task_definitions")) == 4
        assert session.scalar(text("SELECT count(*) FROM management.mps_candidate_ranges")) == 1


@pytest.mark.parametrize("guard", ["unarchived", "lost-owner", "replacement", "owner-changes-during-scan", "archived"])
async def test_header_yield_fences_queue_cleanup_before_any_removal(
    store, window_runtime, monkeypatch, guard
):
    from ultima_scraper_backend.job_system.event_log import EventLog
    plan = generated(store, total=6)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await durable.advance(window_runtime, job_id)
    if guard not in {"unarchived", "replacement"}:
        await finish_window(storage, job_id)
        assert await durable.advance(window_runtime, job_id) is True
        plan = store.get(job_id)
    await client.set(runtime_admission.PRESSURE_KEY, "1")
    key = materializer._mps_materialization_lock_key(job_id)
    event_key = EventLog.STREAM_KEY_FORMAT.format(job_id=job_id)
    await client.xadd(event_key, {"event": "retained until safe retirement"})
    await client.set(key, "other-owner" if guard == "lost-owner" else "test-owner")
    monkeypatch.setattr(JobManager, "_resolve_backend_assignment", AsyncMock(return_value="fixture"))
    queue = JobManager(window_runtime.redis).router._queue_key("fixture")
    member = f"{job_id}:old-reference"
    await client.zadd(queue, {member: 1, "another-job:ready": 2})
    if guard == "replacement":
        await client.hset(mps_state.PLAN_KEY.format(job_id=job_id), "task_manifest_id", "new-definition")
    if guard == "owner-changes-during-scan":
        original_scan = client.zscan

        async def interrupted(*args, **kwargs):
            result = await original_scan(*args, **kwargs)
            await client.set(key, "new-owner")
            await client.zadd(queue, {f"{job_id}:new-reference": 3})
            return result

        monkeypatch.setattr(client, "zscan", interrupted)
    if guard in {"lost-owner", "owner-changes-during-scan"}:
        with pytest.raises(materializer._MPSMaterializationLockLost):
            await durable._yield_archived_header(storage, plan, lock_key=key, lock_owner="test-owner")
    else:
        assert await durable._yield_archived_header(storage, plan, lock_key=key, lock_owner="test-owner") is (guard == "archived")
    assert await client.zscore(queue, "another-job:ready") == 2
    if guard == "archived":
        assert await client.zscore(queue, member) is None
        assert not await client.exists(event_key)
        await assert_budget(client, storage, 0)
    else:
        assert await client.zscore(queue, member) == 1
        assert await client.xlen(event_key) == 1
        await assert_budget(client, storage, 1)
    if guard == "owner-changes-during-scan":
        assert await client.zscore(queue, f"{job_id}:new-reference") == 3


async def test_rename_waits_for_bytes_while_current_window_can_finish(
    store, window_runtime, monkeypatch
):
    first = generated(store, job_id="a-running", total=6)
    second = generated(store, job_id="z-other", total=6)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await durable.publish(storage, first)
    await durable.publish(storage, second)
    await materializer._materialize_mps_job(window_runtime, first["job_id"])
    full_bytes = int(await client.hget(runtime_admission.LEDGER_KEY, "bytes"))
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_BYTES", str(full_bytes))
    manager = JobManager(window_runtime.redis)
    manager.database_writes = window_runtime.writes
    updated = await manager.update_job_by_id(first["job_id"], name="Renamed " + "é"*100)
    assert updated.name == "Renamed " + "é"*100
    assert store.get(first["job_id"])["job_config"]["name"] == updated.name
    cached = await storage.fetch_job(first["job_id"], include_tasks=False)
    assert cached.metadata["mps_config_pending"]
    await assert_budget(client, storage, 2, maximum=full_bytes)
    assert len(await finish_window(storage, first["job_id"])) == 3
    await materializer._materialize_mps_job(window_runtime, first["job_id"])
    assert store.get(first["job_id"])["cursor"] == 3
    assert await storage.fetch_job(first["job_id"], include_tasks=False) is None
    await assert_budget(client, storage, 1, maximum=full_bytes)
    # Once the other cache entry is retired, recovery publishes the committed
    # name and resumes after the archived prefix, with no repeated task IDs.
    await materializer._materialize_mps_job(window_runtime, second["job_id"])
    await finish_window(storage, second["job_id"])
    await materializer._materialize_mps_job(window_runtime, second["job_id"])
    await durable.recover(window_runtime)
    cached = await storage.fetch_job(first["job_id"], include_tasks=False)
    assert cached.name == updated.name and not cached.metadata.get("mps_config_pending")
    assert cached.completed_tasks_count == 3
    await assert_budget(client, storage, 1, maximum=full_bytes)


async def test_oversized_edit_is_rejected_before_durable_commit(
    store, window_runtime, monkeypatch
):
    plan = generated(store)
    storage = JobStorage(window_runtime.redis)
    await durable.publish(storage, plan)
    manager = JobManager(window_runtime.redis)
    manager.database_writes = window_runtime.writes
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_HEADER_MAX_BYTES", "6000")
    with pytest.raises(TaskPayloadBudgetExceeded):
        await manager.update_job_by_id(plan["job_id"], name="é" * 4000)
    assert store.get(plan["job_id"])["job_config"]["name"] == "Generated fixture"
    assert (await storage.fetch_job(plan["job_id"], include_tasks=False)).name == "Generated fixture"


async def test_future_sql_only_schedule_is_admitted_when_due(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "1")
    plan = generated(store)
    storage = JobStorage(window_runtime.redis)
    manager = JobManager(window_runtime.redis)
    manager.database_writes = window_runtime.writes
    job = durable.job_from_plan(plan)
    future = JobSchedule(scheduled_for=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    updated = await durable.update_job_config(manager, job, schedule=future)
    assert updated.schedule == future
    await durable.recover(window_runtime)
    await assert_budget(storage._client(), storage, 0)
    assert store.active_page(limit=1, due_only=True) == []
    past = JobSchedule(scheduled_for=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    await durable.update_job_config(manager, updated, schedule=past)
    assert store.active_page(limit=1, due_only=True) == [job.job_id]
    restored = await storage.fetch_job(job.job_id, include_tasks=False)
    assert restored.schedule == past and restored.metadata["mps_schedule_pending"]
    manager = JobManager(window_runtime.redis)
    manager.database_writes = window_runtime.writes
    started = await durable.start_scheduled_job(manager, restored)
    assert not started.metadata["mps_schedule_pending"]
    await materializer._materialize_mps_job(window_runtime, job.job_id)
    assert await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id)) == 3
    await assert_budget(storage._client(), storage, 1)


async def test_schedule_edit_under_byte_pressure_holds_claims_then_reactivates(
    store, window_runtime, monkeypatch
):
    first = generated(store, job_id="a-running")
    other = generated(store, job_id="z-other")
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await durable.publish(storage, first)
    await durable.publish(storage, other)
    await materializer._materialize_mps_job(window_runtime, first["job_id"])
    full_bytes = int(await client.hget(runtime_admission.LEDGER_KEY, "bytes"))
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_BYTES", str(full_bytes))
    manager = JobManager(window_runtime.redis)
    manager.database_writes = window_runtime.writes
    await manager.update_job_by_id(first["job_id"], name="A larger name " + "é"*100)
    future = JobSchedule(scheduled_for=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), cron="x"*100)
    await manager.update_job_by_id(first["job_id"], schedule=future)
    ids = await legacy.list_tasks_for_job(storage, first["job_id"])
    assert ids and not await legacy.mark_task_started(storage, first["job_id"], ids[0])
    state_key = storage.JOB_STATE_KEY.format(job_id=first["job_id"])
    assert len(await client.hget(state_key, "mps_pending_scheduled_for")) < 40
    past = JobSchedule(scheduled_for=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    await manager.update_job_by_id(first["job_id"], schedule=past)
    restored = await storage.fetch_job(first["job_id"], include_tasks=False)
    await durable.start_scheduled_job(manager, restored)
    calls = JobManager.activate_materialized_job.await_count
    await materializer._materialize_mps_job(window_runtime, first["job_id"])
    assert JobManager.activate_materialized_job.await_count == calls + 1
    assert await legacy.mark_task_started(storage, first["job_id"], ids[0])
    assert await legacy.list_tasks_for_job(storage, first["job_id"]) == ids
    assert store.get(first["job_id"])["cursor"] == 0
    await assert_budget(client, storage, 2, maximum=full_bytes)


@pytest.mark.parametrize("shape", ["ordinary", "generated"])
async def test_impossible_new_header_leaves_no_committed_preparation(
    store, window_runtime, monkeypatch, shape
):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_HEADER_MAX_BYTES", "4096")
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_METADATA_MAX_BYTES", "4096")
    with pytest.raises(TaskPayloadBudgetExceeded):
        if shape == "ordinary":
            await admit(window_runtime, count=2)
        else:
            generated(store)
    with store.session_factory() as session:
        for table in ("jobs", "mps_plans", "mps_task_definitions", "mps_candidate_ranges"):
            assert session.scalar(text(f"SELECT count(*) FROM management.{table}")) == 0
    storage = JobStorage(window_runtime.redis)
    await assert_budget(storage._client(), storage, 0)


async def test_committed_window_is_released_after_interrupted_cache_purge(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "1")
    first, second = generated(store, job_id="a-running"), generated(store)
    storage = JobStorage(window_runtime.redis)
    await durable.publish(storage, first)
    await durable.publish(storage, second)
    await materializer._materialize_mps_job(window_runtime, first["job_id"])
    completed = await finish_window(storage, first["job_id"])
    with monkeypatch.context() as interrupted:
        interrupted.setattr(durable, "_purge_archived_window", AsyncMock(side_effect=RuntimeError("interrupted after SQL commit")))
        with pytest.raises(RuntimeError, match="after SQL commit"):
            await materializer._materialize_mps_job(window_runtime, first["job_id"])
    assert store.get(first["job_id"])["cursor"] == 3
    assert await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=first["job_id"])) == 3
    await assert_budget(storage._client(), storage, 1)
    await materializer._materialize_mps_job(window_runtime, first["job_id"])
    await assert_budget(storage._client(), storage, 0)
    await durable.recover(window_runtime)
    assert await storage.fetch_job(second["job_id"], include_tasks=False) is not None
    with store.session_factory() as session:
        assert set(session.scalars(text("SELECT task_id FROM management.job_tasks"))) == {item.task_id for item in completed}


async def test_waiting_job_can_be_cancelled_without_admitting_its_header(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "1")
    first, second = generated(store, job_id="a-running"), generated(store)
    storage = JobStorage(window_runtime.redis)
    await durable.publish(storage, first)
    await durable.publish(storage, second)
    manager = JobManager(window_runtime.redis)
    manager.database_writes = window_runtime.writes
    cancelled = await manager.cancel_job_by_id(second["job_id"], reason="fixture cancellation")
    assert cancelled.state == JobState.CANCELLED and cancelled.total_tasks == 1_000_000
    assert store.get(second["job_id"])["status"] == "cancelled"
    with store.session_factory() as session:
        assert session.scalar(text("SELECT status FROM management.jobs WHERE job_id=:job"), {"job": second["job_id"]}) == "cancelled"
    await durable.recover(window_runtime)
    assert await storage.fetch_job(second["job_id"], include_tasks=False) is None
    await assert_budget(storage._client(), storage, 1)


async def test_pressure_retires_only_one_completed_header_before_admission(
    store, window_runtime, monkeypatch
):
    from ultima_scraper_backend.job_system import storage as storage_module

    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "3")
    monkeypatch.setattr(storage_module, "DatabaseWriteClient", type(window_runtime.writes))
    storage = JobStorage(window_runtime.redis)
    completed = []
    for _ in range(3):
        plan = generated(store, total=1)
        completed.append(plan["job_id"])
        await durable.publish(storage, plan)
        await materializer._materialize_mps_job(window_runtime, plan["job_id"])
        await finish_window(storage, plan["job_id"])
        await materializer._materialize_mps_job(window_runtime, plan["job_id"])
    await assert_budget(storage._client(), storage, 3)
    waiting = generated(store)
    await durable.publish(storage, waiting)
    await durable.recover(window_runtime)
    await assert_budget(storage._client(), storage, 3)
    assert await storage.fetch_job(waiting["job_id"], include_tasks=False) is not None
    assert sum([await storage._client().exists(storage.JOB_CONFIG_KEY.format(job_id=job_id)) for job_id in completed]) == 2
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 3


async def test_recovered_due_schedule_triggers_without_another_poll(
    store, window_runtime, monkeypatch
):
    plan = generated(store)
    schedule = JobSchedule(scheduled_for=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    store.update_config(plan["job_id"], schedule=schedule.to_dict())
    storage = JobStorage(window_runtime.redis)
    assert await storage.fetch_job(plan["job_id"], include_tasks=False) is None
    await durable.recover(window_runtime)
    current = await storage.fetch_job(plan["job_id"], include_tasks=False)
    assert current is not None and current.metadata["mps_schedule_pending"] is False
    assert await storage._client().zscore(storage.SCHEDULED_KEY, plan["job_id"]) is None
    await materializer._materialize_mps_job(window_runtime, plan["job_id"])
    assert await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=plan["job_id"])) == 3


async def test_future_replacement_releases_the_slot_with_its_old_header(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "1")
    first = generated(store)
    storage = JobStorage(window_runtime.redis)
    await durable.publish(storage, first)
    manager = JobManager(window_runtime.redis)
    manager.database_writes = window_runtime.writes
    schedule = JobSchedule(scheduled_for=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    replaced = await manager.update_job_by_id(first["job_id"], tasks=[task(99, width=10)], schedule=schedule)
    assert replaced.schedule == schedule
    await assert_budget(storage._client(), storage, 0)
    waiting = generated(store)
    await durable.publish(storage, waiting)
    assert await storage.fetch_job(waiting["job_id"], include_tasks=False) is not None
    await assert_budget(storage._client(), storage, 1)
