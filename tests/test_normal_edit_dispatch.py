"""Ordinary replacement commits before claims and survives interrupted publication."""

import asyncio
import copy
import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

import test_normal_durable_inputs as inputs
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteCommand,
    DatabaseWriteOperation,
)
from ultima_scraper_backend.job_system import JobManager, JobStorage
from ultima_scraper_backend.job_system import mps_attempt, ordinary_edit
from ultima_scraper_backend.job_system.models import JobState
import legacy_redis_runtime as legacy

postgres_engine = inputs.postgres_engine
database = inputs.database
redis_manager = inputs.redis_manager


async def fixture(monkeypatch, redis_manager, *, count=4):
    storage = inputs.storage_for(redis_manager)
    job = inputs.fixture_job(count, width=10)
    inputs.persist(job)
    await storage.persist_job(job, persist_tasks=True)
    await legacy.initialize_task_state(storage, job, return_ready_task_ids=False)
    monkeypatch.setattr(
        JobManager, "_resolve_backend_assignment", AsyncMock(return_value=None)
    )
    route = AsyncMock()
    monkeypatch.setattr(JobManager, "_route_pending_job", route)
    backend = SimpleNamespace(
        redis=SimpleNamespace(**vars(storage.redis), is_connected=True),
        distributed_mode=True,
    )
    manager = JobManager(backend.redis)
    manager.storage = storage
    return storage, job, backend, manager, route


async def edit(monkeypatch, backend, job, *, replacement=None, name="Replacement"):
    tasks = None
    if replacement is not None:
        tasks = [jobs.TaskPayload(task_type="api_command", params={})]
        monkeypatch.setattr(
            jobs, "_build_task_from_payload", AsyncMock(return_value=replacement)
        )
    return await jobs._update_job(
        job.job_id,
        jobs.UpdateJobRequest(job_name=name, tasks=tasks),
        backend,
        SimpleNamespace(),
    )


def sql_snapshot(database, job_id):
    with database.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, job_config_json, started_at, completed_at, last_event_at, "
                "result_success, result_error, result_completed_at FROM management.jobs WHERE job_id=:job"
            ),
            {"job": job_id},
        ).one()
        tasks = connection.execute(
            text(
                "SELECT task_id, status, definition_json FROM management.job_tasks WHERE job_id=:job ORDER BY task_id"
            ),
            {"job": job_id},
        ).all()
    return row, tasks


async def assert_no_edit(storage, job_id):
    client = storage._client()
    assert not await client.get(ordinary_edit.record_key(job_id))
    assert not await client.get(ordinary_edit.lock_key(job_id))
    assert not await client.hget(
        storage.JOB_STATE_KEY.format(job_id=job_id), "edit_pending"
    )
    assert await client.zscore(ordinary_edit.PENDING_KEY, job_id) is None


async def test_actual_api_keeps_original_inputs_and_blocks_claim_until_sql_commit(
    database, redis_manager, monkeypatch
):
    storage, job, backend, _, route = await fixture(monkeypatch, redis_manager)
    replacement = [inputs.task(99, width=30)]
    entered, release = threading.Event(), threading.Event()

    def pause(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE FROM management.job_tasks"):
            entered.set()
            assert release.wait(5), "test did not release owned SQL transaction"

    event.listen(database, "before_cursor_execute", pause)
    work = asyncio.create_task(edit(monkeypatch, backend, job, replacement=replacement))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        assert (
            await storage.fetch_job(job.job_id, include_tasks=False)
        ).name == job.name
        assert (await storage.fetch_task(job.job_id, job.tasks[0].task_id)) is not None
        assert (await storage.fetch_task(job.job_id, replacement[0].task_id)) is None
        assert (
            await legacy.mark_task_started(storage, job.job_id, job.tasks[0].task_id) is False
        )
        route.assert_not_awaited()
    finally:
        release.set()
        await asyncio.wait_for(work, 5)
        event.remove(database, "before_cursor_execute", pause)
    row, tasks = sql_snapshot(database, job.job_id)
    current = await storage.fetch_job(job.job_id, include_tasks=False)
    assert (
        json.loads(row[1])["metadata"]["task_definition_id"]
        == current.metadata["task_definition_id"]
    )
    assert [task[0] for task in tasks] == [replacement[0].task_id]
    assert current.total_tasks == 1
    assert await legacy.mark_task_started(storage, job.job_id, replacement[0].task_id)
    route.assert_awaited_once()
    await assert_no_edit(storage, job.job_id)


async def test_sql_failure_returns_503_preserves_original_and_never_routes_replacement(
    database, redis_manager, monkeypatch
):
    storage, job, backend, _, route = await fixture(monkeypatch, redis_manager)

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE FROM management.job_tasks"):
            raise RuntimeError("injected database failure")

    event.listen(database, "before_cursor_execute", fail)
    try:
        with pytest.raises(HTTPException) as error:
            await edit(monkeypatch, backend, job, replacement=[inputs.task(99)])
    finally:
        event.remove(database, "before_cursor_execute", fail)
    assert error.value.status_code == 503
    assert (await storage.fetch_job(job.job_id, include_tasks=False)).name == job.name
    assert [row[0] for row in sql_snapshot(database, job.job_id)[1]] == [
        task.task_id for task in job.tasks
    ]
    assert all(call.args[0].name == job.name for call in route.await_args_list)
    await assert_no_edit(storage, job.job_id)
    assert await legacy.mark_task_started(storage, job.job_id, job.tasks[0].task_id)


@pytest.mark.parametrize(
    "budget", ["ULTIMA_JOB_TASK_INSERT_MAX_BYTES", "ULTIMA_JOB_TASK_INPUT_MAX_BYTES"]
)
async def test_input_budget_failure_rolls_back_all_batches_and_keeps_old_job(
    database, redis_manager, monkeypatch, budget
):
    storage, job, backend, _, _ = await fixture(monkeypatch, redis_manager)
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "1")
    monkeypatch.setenv(budget, "1500")
    with pytest.raises(HTTPException) as error:
        await edit(
            monkeypatch,
            backend,
            job,
            replacement=[inputs.task(98, width=1), inputs.task(99, width=20000)],
        )
    assert error.value.status_code == 413
    assert "1500" in error.value.detail
    assert len(sql_snapshot(database, job.job_id)[1]) == len(job.tasks)
    assert (await storage.fetch_job(job.job_id, include_tasks=False)).name == job.name
    await assert_no_edit(storage, job.job_id)


async def test_recovery_replays_committed_inputs_in_bounded_pages_after_partial_publication(
    database, redis_manager, monkeypatch
):
    storage, job, backend, _, route = await fixture(monkeypatch, redis_manager)
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_BATCH_SIZE", "2")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_MAX_BYTES", "6000")
    replacement = [inputs.task(i, width=30) for i in range(50, 57)]
    original = JobStorage.persist_tasks
    pages = []

    async def partial(self, job_id, tasks):
        pages.append(len(tasks))
        if len(pages) == 2:
            raise RuntimeError("interrupted publication")
        await original(self, job_id, tasks)

    monkeypatch.setattr(JobStorage, "persist_tasks", partial)
    with pytest.raises(HTTPException) as error:
        await edit(monkeypatch, backend, job, replacement=replacement)
    assert error.value.status_code == 503 and "committed" in error.value.detail
    assert len(sql_snapshot(database, job.job_id)[1]) == 7
    route.assert_not_awaited()
    assert await legacy.mark_task_started(storage, job.job_id, replacement[0].task_id) is False
    monkeypatch.setattr(JobStorage, "persist_tasks", original)
    recovered_storage = inputs.storage_for(redis_manager)
    recovered_manager = JobManager(recovered_storage.redis)
    recovered_manager.storage = recovered_storage
    recovered = await ordinary_edit.recover(recovered_manager, job.job_id)
    assert recovered.name == "Replacement" and recovered.total_tasks == 7
    assert recovered.tasks == []
    assert pages == [2, 2]
    assert await storage.get_ready_task_count(job.job_id) == 7
    route.assert_awaited_once()
    await assert_no_edit(storage, job.job_id)


async def test_published_recovery_preserves_work_claimed_before_routing_failure(
    database, redis_manager, monkeypatch
):
    storage, job, backend, manager, route = await fixture(monkeypatch, redis_manager)
    replacement = [inputs.task(99, width=10)]

    async def fail_after_claim(job, **kwargs):
        assert await legacy.mark_task_started(storage, job.job_id, replacement[0].task_id)
        raise RuntimeError("route completion lost")

    route.side_effect = fail_after_claim
    with pytest.raises(HTTPException) as error:
        await edit(monkeypatch, backend, job, replacement=replacement)
    assert error.value.status_code == 503
    assert (
        json.loads(await storage._client().get(ordinary_edit.record_key(job.job_id)))[
            "phase"
        ]
        == "published"
    )
    route.side_effect = None
    await ordinary_edit.recover(manager, job.job_id)
    assert await storage._client().sismember(
        storage.TASKS_INFLIGHT_KEY.format(job_id=job.job_id), replacement[0].task_id
    )
    assert await storage.get_ready_task_count(job.job_id) == 0
    await assert_no_edit(storage, job.job_id)


async def test_request_cancellation_drains_sql_and_leaves_a_recoverable_committed_edit(
    database, redis_manager, monkeypatch
):
    storage, job, backend, manager, route = await fixture(monkeypatch, redis_manager)
    entered, release = threading.Event(), threading.Event()

    def pause(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE FROM management.job_tasks"):
            entered.set()
            assert release.wait(5)

    event.listen(database, "before_cursor_execute", pause)
    work = asyncio.create_task(
        edit(monkeypatch, backend, job, replacement=[inputs.task(99, width=10)])
    )
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        work.cancel()
        await asyncio.sleep(0)
        work.cancel()
        await asyncio.sleep(0)
        assert not work.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(work, 5)
        event.remove(database, "before_cursor_execute", pause)
    route.assert_not_awaited()
    assert not await storage._client().get(ordinary_edit.lock_key(job.job_id))
    assert await storage._client().get(ordinary_edit.record_key(job.job_id))
    assert len(sql_snapshot(database, job.job_id)[1]) == 1
    await ordinary_edit.recover(manager, job.job_id)
    assert (
        await storage.fetch_job(job.job_id, include_tasks=False)
    ).name == "Replacement"
    await assert_no_edit(storage, job.job_id)


async def test_claim_winner_blocks_replacement_without_touching_sql(
    database, redis_manager, monkeypatch
):
    storage, job, backend, _, route = await fixture(monkeypatch, redis_manager)
    assert await legacy.mark_task_started(storage, job.job_id, job.tasks[0].task_id)
    with pytest.raises(HTTPException) as error:
        await edit(monkeypatch, backend, job, replacement=[inputs.task(99)])
    assert error.value.status_code == 409
    assert len(sql_snapshot(database, job.job_id)[1]) == len(job.tasks)
    route.assert_not_awaited()
    await assert_no_edit(storage, job.job_id)


async def test_post_handler_finish_excludes_edit_after_inflight_membership_is_removed(
    database, redis_manager, monkeypatch
):
    storage, job, backend, _, _ = await fixture(monkeypatch, redis_manager)
    async with mps_attempt.finish_lock(storage, job, job.tasks[0]):
        with pytest.raises(HTTPException) as error:
            await edit(monkeypatch, backend, job, replacement=[inputs.task(99)])
        assert error.value.status_code == 409
    await edit(monkeypatch, backend, job, replacement=[inputs.task(99, width=10)])
    with pytest.raises(mps_attempt.StaleTaskDefinition):
        async with mps_attempt.finish_lock(storage, job, job.tasks[0]):
            pytest.fail("old task entered finish section")


async def test_worker_state_update_preserves_concurrent_rename_and_large_integer_metadata(
    database, redis_manager, monkeypatch
):
    storage, job, backend, _, _ = await fixture(monkeypatch, redis_manager)
    await edit(monkeypatch, backend, job, name="Renamed")
    current = await storage.fetch_job(job.job_id, include_tasks=False)
    current.metadata["large_id"] = 2**63 - 1
    await storage.persist_job(current)
    job.state = JobState.RUNNING
    await storage.persist_job(job, runtime_only=True)
    header = await storage.fetch_job(job.job_id, include_tasks=False)
    assert header.name == "Renamed" and header.state == JobState.RUNNING
    assert header.metadata["large_id"] == 2**63 - 1
    with pytest.raises(mps_attempt.StaleTaskDefinition):
        await storage.persist_job(job)


async def test_replacement_resets_sql_terminal_fields_and_rejects_old_runtime_header(
    database, redis_manager, monkeypatch
):
    storage, job, backend, _, _ = await fixture(monkeypatch, redis_manager)
    job.metadata.update(failure_reason="old failure", worker_id="old-worker")
    await storage.persist_job(job, runtime_only=True)
    with database.begin() as connection:
        connection.execute(
            text(
                "UPDATE management.jobs SET status='completed', started_at=now(), completed_at=now(), "
                "last_event_at=now(), result_success=true, result_error='old', result_completed_at=now() WHERE job_id=:job"
            ),
            {"job": job.job_id},
        )
    await edit(monkeypatch, backend, job, replacement=[inputs.task(99, width=10)])
    row, _ = sql_snapshot(database, job.job_id)
    assert row[0] == "pending" and list(row[2:]) == [None] * 6
    header = await storage.fetch_job(job.job_id, include_tasks=False)
    assert (
        "failure_reason" not in header.metadata and "worker_id" not in header.metadata
    )
    with pytest.raises(mps_attempt.StaleTaskDefinition):
        await storage.persist_job(job, runtime_only=True)


def command(operation, payload):
    return DatabaseWriteCommand(
        command_id=f"ordinary-edit-test-{uuid4().hex}",
        operation=operation,
        payload=payload,
        site=None,
        producer_id="fixture",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@pytest.mark.parametrize("kind", ["job", "task"])
async def test_delayed_status_cannot_overwrite_replacement_even_with_reused_task_id(
    database, redis_manager, monkeypatch, kind
):
    storage, job, backend, _, _ = await fixture(monkeypatch, redis_manager)
    replacement = copy.deepcopy(job.tasks[0])
    replacement.payload.args["marker"] = "new-input"
    await edit(monkeypatch, backend, job, replacement=[replacement])
    current = await storage.fetch_job(job.job_id, include_tasks=False)
    if kind == "job":
        execute = PostgreSQLWriteExecutor._sync_job_statuses
        payload = {
            "job_id": job.job_id,
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "job_snapshot": {
                "job_config": job.to_config(include_task_ids=False).to_dict()
            },
        }
        old = command(DatabaseWriteOperation.SYNC_JOB_STATUS, payload)
        payload = {
            **payload,
            "job_snapshot": {
                "job_config": current.to_config(include_task_ids=False).to_dict()
            },
        }
    else:
        execute = PostgreSQLWriteExecutor._sync_task_statuses
        payload = {
            "job_id": job.job_id,
            "task_id": replacement.task_id,
            "status": "completed",
            "event_time": datetime.now(timezone.utc).isoformat(),
        }
        old = command(DatabaseWriteOperation.SYNC_TASK_STATUS, payload)
        payload = {
            **payload,
            "task_definition_id": current.metadata["task_definition_id"],
        }
    assert await asyncio.to_thread(execute, [old]) == {
        old.command_id: {"synced": False, "stale": True}
    }
    assert sql_snapshot(database, job.job_id)[0][0] == "pending"
    assert sql_snapshot(database, job.job_id)[1][0][1] == "pending"
    latest = command(old.operation, payload)
    assert await asyncio.to_thread(execute, [latest]) == {
        latest.command_id: {"synced": True}
    }


async def test_lost_edit_owner_cannot_publish_over_recovered_inputs(
    database, redis_manager, monkeypatch
):
    storage, job, backend, manager, _ = await fixture(monkeypatch, redis_manager)
    original = ordinary_edit._publish
    lost_owner = None

    async def lose(self, owner, descriptor, config):
        nonlocal lost_owner
        lost_owner = owner
        await storage._client().delete(ordinary_edit.lock_key(job.job_id))
        raise RuntimeError("process lost its lease")

    monkeypatch.setattr(ordinary_edit, "_publish", lose)
    with pytest.raises(HTTPException):
        await edit(monkeypatch, backend, job, replacement=[inputs.task(99, width=10)])
    monkeypatch.setattr(ordinary_edit, "_publish", original)
    await ordinary_edit.recover(manager, job.job_id)
    with ordinary_edit.scope(lost_owner), pytest.raises(ordinary_edit.EditInProgress):
        await storage.persist_tasks(job.job_id, job.tasks)
    assert len(await storage.list_task_ids_window(job.job_id, offset=0, limit=20)) == 1
    await assert_no_edit(storage, job.job_id)


async def test_task_fetched_before_edit_cannot_claim_a_reused_id_after_publication(
    database, redis_manager, monkeypatch
):
    storage, job, backend, _, _ = await fixture(monkeypatch, redis_manager)
    task = job.tasks[0]
    await edit(monkeypatch, backend, job, replacement=[copy.deepcopy(task)])
    with mps_attempt.bind(job, task):
        assert not await legacy.mark_task_started(storage, job.job_id, task.task_id)
    assert await storage.get_ready_task_count(job.job_id) == 1
    current = await storage.fetch_job(job.job_id, include_tasks=False)
    with mps_attempt.bind(current, task):
        assert await legacy.mark_task_started(storage, job.job_id, task.task_id)


@pytest.mark.parametrize(
    "operation",
    [
        "result",
        "output",
        "complete",
        "fail",
        "defer",
        "clear",
        "spawn",
        "ready",
        "routing",
    ],
)
async def test_stale_post_handler_mutations_preserve_replacement_runtime(
    database, redis_manager, monkeypatch, operation
):
    storage, job, backend, manager, _ = await fixture(monkeypatch, redis_manager)
    task = job.tasks[0]
    replacement = copy.deepcopy(task)
    replacement.payload.args["marker"] = "new-input"
    await edit(monkeypatch, backend, job, replacement=[replacement])
    callbacks = {
        "result": lambda: legacy.persist_task_result(storage, job.job_id, task),
        "output": lambda: legacy.store_task_output(storage, 
            job.job_id, task.task_id, "old-output"
        ),
        "complete": lambda: legacy.mark_task_completed(storage, job.job_id, task.task_id),
        "fail": lambda: legacy.mark_task_failed(storage, job.job_id, task.task_id),
        "defer": lambda: legacy.mark_task_deferred(storage, 
            job.job_id, task.task_id, task.dedup_key
        ),
        "clear": lambda: storage.clear_task_state(job.job_id),
        "spawn": lambda: legacy.add_task_to_job(storage, job.job_id, inputs.task(99)),
        "ready": lambda: legacy.add_single_task_state(storage, job.job_id, inputs.task(99)),
        "routing": lambda: manager.router.clear_job_assignment(
            "test-backend", job.job_id
        ),
    }
    with mps_attempt.bind(job, task), pytest.raises(mps_attempt.StaleTaskDefinition):
        await callbacks[operation]()
    assert (await storage.fetch_task(job.job_id, task.task_id)).payload.args[
        "marker"
    ] == "new-input"
    assert await storage.get_ready_task_count(job.job_id) == 1
    assert (
        await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id))
        == 1
    )


async def test_lost_finish_lease_stops_cleanup_even_before_another_editor_runs(
    database, redis_manager, monkeypatch
):
    storage, job, _, _, _ = await fixture(monkeypatch, redis_manager)
    with mps_attempt.bind(job, job.tasks[0]):
        async with mps_attempt.finish_lock(storage, job, job.tasks[0]):
            await storage._client().delete(ordinary_edit.lock_key(job.job_id))
            with pytest.raises(mps_attempt.StaleTaskDefinition):
                await storage.clear_task_state(job.job_id)
    assert await storage.get_ready_task_count(job.job_id) == len(job.tasks)


async def test_stale_worker_release_preserves_replacement_dedup_and_exec_lock(
    database, redis_manager, monkeypatch
):
    storage, job, backend, _, _ = await fixture(monkeypatch, redis_manager)
    task = job.tasks[0]
    await edit(monkeypatch, backend, job, replacement=[copy.deepcopy(task)])
    current = await storage.fetch_job(job.job_id, include_tasks=False)
    assert await storage.reserve_dedup(task)
    assert await legacy.acquire_task_lock(storage, task.task_id, "same-worker-id")
    with mps_attempt.bind(job, task):
        await storage.release_dedup(task)
        assert not await legacy.release_task_lock(storage, task.task_id, "same-worker-id")
    assert (
        await storage._client().get(storage.DEDUPE_KEY.format(dedup=task.dedup_key))
        == task.task_id.encode()
    )
    assert (
        await storage._client().get(
            storage.TASK_EXEC_LOCK_KEY.format(task_id=task.task_id)
        )
        == b"same-worker-id"
    )
    with mps_attempt.bind(current, task):
        await storage.release_dedup(task)
        assert await legacy.release_task_lock(storage, task.task_id, "same-worker-id")
    assert not await storage._client().get(
        storage.DEDUPE_KEY.format(dedup=task.dedup_key)
    )


async def test_delayed_sql_call_cannot_commit_after_recovery_aborts_its_expired_edit(
    database, redis_manager, monkeypatch
):
    storage, job, backend, manager, route = await fixture(monkeypatch, redis_manager)
    entered, release = threading.Event(), threading.Event()
    commit = ordinary_edit._commit_sync

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return commit(*args)

    monkeypatch.setattr(ordinary_edit, "_commit_sync", delayed)
    work = asyncio.create_task(
        edit(monkeypatch, backend, job, replacement=[inputs.task(99, width=10)])
    )
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        await storage._client().delete(ordinary_edit.lock_key(job.job_id))
        assert await ordinary_edit.recover(manager, job.job_id) is None
        assert await legacy.mark_task_started(storage, job.job_id, job.tasks[0].task_id)
    finally:
        release.set()
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(work, 5)
    assert error.value.status_code == 409
    assert (await storage.fetch_job(job.job_id, include_tasks=False)).name == job.name
    assert len(sql_snapshot(database, job.job_id)[1]) == len(job.tasks)
    assert all(call.args[0].name == job.name for call in route.await_args_list)
    await assert_no_edit(storage, job.job_id)
