"""Ordinary archive batches must never mutate a replacement's SQL task rows."""

import asyncio
import copy
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

import test_normal_durable_inputs as inputs
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.api.routes import job_central_store
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteCommand,
    DatabaseWriteOperation,
)
from ultima_scraper_backend.job_system import JobManager, JobStorage, TaskResult
from ultima_scraper_backend.job_system import retention
from ultima_scraper_backend.job_system.models import JobState, TaskState
from ultima_scraper_backend.job_system.storage import _task_to_central_row
from ultima_scraper_db_archive import global_db
import legacy_redis_runtime as legacy

postgres_engine = inputs.postgres_engine
database = inputs.database
redis_manager = inputs.redis_manager


async def seed(redis_manager, *, count=5):
    storage = inputs.storage_for(redis_manager)
    job = inputs.fixture_job(count, width=30)
    inputs.persist(job)
    job.state = JobState.COMPLETED
    job.completed_at = datetime.now(timezone.utc).isoformat()
    for task in job.tasks:
        task.state = TaskState.COMPLETED
        task.result = TaskResult(success=True, output={"evidence": task.task_id})
    await storage.persist_job(job, persist_tasks=True)
    return storage, job


def command(job, **overrides):
    payload = {
        "job_id": job.job_id,
        "generation": job.completed_at,
        "task_definition_id": job.metadata.get("task_definition_id", job.job_id),
        "batch_size": 2,
        "max_bytes": 10000,
        **overrides,
    }
    return DatabaseWriteCommand(
        command_id=f"archive-generation-{uuid4().hex}",
        operation=DatabaseWriteOperation.ARCHIVE_JOB_TASKS,
        payload=payload,
        site=None,
        producer_id="fixture",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


async def execute(storage, item):
    result = await PostgreSQLWriteExecutor._archive_job_tasks(
        SimpleNamespace(redis=storage.redis), [item]
    )
    return result[item.command_id]


def replace_sql(database, job, *, identity="replacement-definition"):
    config = job.to_config(include_task_ids=False).to_dict()
    config["metadata"]["task_definition_id"] = identity
    replacement = inputs.task(99, width=10)
    replacement.task_id = "replacement-task"
    replacement.job_id = job.job_id
    with database.begin() as connection:
        connection.execute(
            text("SELECT job_id FROM management.jobs WHERE job_id=:job FOR UPDATE"),
            {"job": job.job_id},
        )
        connection.execute(
            text(
                "UPDATE management.jobs SET job_config_json=:config WHERE job_id=:job"
            ),
            {"config": json.dumps(config), "job": job.job_id},
        )
        connection.execute(
            text("DELETE FROM management.job_tasks WHERE job_id=:job"),
            {"job": job.job_id},
        )
        connection.execute(
            insert(global_db.CentralTaskModel),
            [job_central_store._task_to_central_row(job.job_id, replacement)],
        )
    return replacement


def assert_replacement_retained(database, job):
    with database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT task_id, status, definition_json FROM management.job_tasks WHERE job_id=:job"
            ),
            {"job": job.job_id},
        ).all()
    assert len(rows) == 1
    assert rows[0][:2] == ("replacement-task", "pending")
    assert json.loads(rows[0][2])["payload"]["args"]["user_id"] == 100


@pytest.mark.parametrize("field", ["generation", "task_definition_id"])
async def test_obsolete_command_is_discarded_before_any_archive_write(
    database, redis_manager, field
):
    storage, job = await seed(redis_manager)
    item = command(job, **{field: "previous-definition-or-execution"})
    result = await execute(storage, item)
    assert result == {"archived_tasks": 0, "stale": True}
    with database.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM management.job_tasks WHERE result_json IS NOT NULL"
                )
            )
            == 0
        )
    assert not await storage._client().exists(
        storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    )
    assert await execute(storage, item) == result  # The stale verdict is receipted.


@pytest.mark.parametrize("operation", ["delete", "insert", "count"])
async def test_each_sql_archive_boundary_rejects_replaced_inputs(
    database, redis_manager, operation
):
    storage, job = await seed(redis_manager)
    snapshot = await retention.capture_terminal(storage, job.job_id, "completed")
    replace_sql(database, job)
    callbacks = {
        "delete": lambda: storage._delete_central_tasks_sync(job.job_id),
        "insert": lambda: storage._insert_central_tasks_sync(
            [_task_to_central_row(job.tasks[0], job.job_id)]
        ),
        "count": lambda: storage._count_central_tasks_sync(job.job_id),
    }
    with retention.scope(snapshot), pytest.raises(retention.StaleRetirement):
        await asyncio.to_thread(callbacks[operation])
    assert_replacement_retained(database, job)


async def test_replacement_between_committed_batches_preserves_only_new_sql_rows(
    database, redis_manager, monkeypatch
):
    storage, job = await seed(redis_manager)
    original = JobStorage._insert_central_tasks_sync
    batches = []

    def insert_then_replace(rows):
        result = original(rows)
        batches.append(len(rows))
        if len(batches) == 1:
            replace_sql(database, job)
        return result

    monkeypatch.setattr(
        JobStorage, "_insert_central_tasks_sync", staticmethod(insert_then_replace)
    )
    assert await execute(storage, command(job)) == {"archived_tasks": 0, "stale": True}
    assert batches == [2]
    assert_replacement_retained(database, job)
    assert (
        await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id))
        == 5
    )
    assert not await storage._client().exists(
        storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    )


async def test_archive_row_lock_serializes_replacement_without_loading_task_rows(
    database, redis_manager
):
    storage, job = await seed(redis_manager)
    snapshot = await retention.capture_terminal(storage, job.job_id, "completed")
    with retention.scope(snapshot), Session(database) as session:
        retention.sql_assert_current(session, job.job_id)
        with database.connect() as connection:
            with pytest.raises(OperationalError) as failure:
                connection.execute(
                    text(
                        "SELECT job_id FROM management.jobs WHERE job_id=:job FOR UPDATE NOWAIT"
                    ),
                    {"job": job.job_id},
                )
            assert failure.value.orig.sqlstate == "55P03"
        session.rollback()
    replace_sql(database, job)
    assert_replacement_retained(database, job)


async def test_replacement_before_marker_publication_keeps_its_redis_header(
    database, redis_manager, monkeypatch
):
    storage, job = await seed(redis_manager)
    publish = JobStorage._publish_task_archive_marker
    replacement = copy.deepcopy(job)
    replacement.metadata["task_definition_id"] = "new-definition"
    replacement.state = JobState.PENDING
    replacement.name = "Replacement"

    async def replace_then_publish(self, job_id, count):
        await storage.persist_job(replacement, persist_tasks=True)
        await publish(self, job_id, count)

    monkeypatch.setattr(
        JobStorage, "_publish_task_archive_marker", replace_then_publish
    )
    assert await execute(storage, command(job)) == {"archived_tasks": 0, "stale": True}
    assert (
        await storage.fetch_job(job.job_id, include_tasks=False)
    ).name == "Replacement"
    assert not await storage._client().exists(
        storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    )


@pytest.mark.parametrize("kind", ["old-definition", "old-run", "legacy-count-only"])
async def test_old_marker_cannot_certify_equal_sized_current_archive(
    database, redis_manager, kind
):
    storage, job = await seed(redis_manager)
    marker = {"task_count": len(job.tasks), "archived_at": job.completed_at}
    if kind != "legacy-count-only":
        marker.update(generation=job.completed_at, task_definition_id=job.job_id)
        marker["generation" if kind == "old-run" else "task_definition_id"] = "old"
    await storage._client().set(
        storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id), json.dumps(marker)
    )
    assert await execute(storage, command(job)) == {"archived_tasks": len(job.tasks)}
    with database.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM management.job_tasks WHERE result_json IS NOT NULL"
            )
        ) == len(job.tasks)
    published = json.loads(
        await storage._client().get(
            storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
        )
    )
    assert published["generation"] == job.completed_at
    assert published["task_definition_id"] == job.job_id


@pytest.mark.parametrize(
    "marker",
    [
        None,
        {"task_count": 5},
        {"task_count": 5, "generation": "old", "task_definition_id": "old"},
    ],
)
async def test_missing_runtime_inputs_require_a_matching_verified_marker(
    database, redis_manager, marker
):
    storage, job = await seed(redis_manager)
    await storage._client().delete(storage.TASK_INDEX_KEY.format(job_id=job.job_id))
    if marker is not None:
        await storage._client().set(
            storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id),
            json.dumps(marker),
        )
    with pytest.raises(RuntimeError, match="no matching completion marker"):
        await execute(storage, command(job))
    with database.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM management.job_tasks")) == 5


async def test_matching_marker_survives_input_purge_but_rechecks_sql_definition(
    database, redis_manager
):
    storage, job = await seed(redis_manager)
    assert await execute(storage, command(job)) == {"archived_tasks": 5}
    # Model interruption midway through runtime purge: keep the verified marker.
    await storage._client().delete(storage.TASK_INDEX_KEY.format(job_id=job.job_id))
    assert await execute(storage, command(job)) == {"archived_tasks": 5}
    replace_sql(database, job)
    assert await execute(storage, command(job)) == {"archived_tasks": 0, "stale": True}
    assert_replacement_retained(database, job)


async def test_missing_durable_header_is_incomplete_not_a_successful_stale_receipt(
    database, redis_manager
):
    storage, job = await seed(redis_manager)
    with database.begin() as connection:
        connection.execute(text("DELETE FROM management.job_tasks"))
        connection.execute(text("DELETE FROM management.jobs"))
    with pytest.raises(RuntimeError, match="durable job header is missing"):
        await execute(storage, command(job))
    assert (
        await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id))
        == 5
    )
    assert not await storage._client().exists(
        storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    )


async def test_task_replacement_rotates_identity_and_metadata_edit_keeps_it(
    database, redis_manager, monkeypatch
):
    storage, job = await seed(redis_manager)
    manager = JobManager(storage.redis)
    monkeypatch.setattr(
        manager, "_resolve_backend_assignment", AsyncMock(return_value=None)
    )
    updated = await manager.update_job_by_id(
        job.job_id, tasks=[inputs.task(99)], route_immediate_job=False
    )
    first_identity = updated.metadata["task_definition_id"]
    assert first_identity != job.job_id
    renamed = await manager.update_job_by_id(
        job.job_id, name="Renamed", route_immediate_job=False
    )
    assert renamed.metadata["task_definition_id"] == first_identity
    replaced_again = await manager.update_job_by_id(
        job.job_id, tasks=[inputs.task(100)], route_immediate_job=False
    )
    assert replaced_again.metadata["task_definition_id"] not in {
        job.job_id,
        first_identity,
    }


async def test_archive_receipt_identity_changes_when_completion_time_is_reused(
    database, redis_manager
):
    storage, job = await seed(redis_manager)
    manager = JobManager(storage.redis)
    commands = []

    async def submit(operation, payload, **kwargs):
        commands.append((kwargs["command_id"], payload["task_definition_id"]))
        return {"stale": True, "archived_tasks": 0}

    manager.database_writes = SimpleNamespace(submit=submit)
    await legacy.finalize_job_completion(manager, job.job_id)
    job.metadata["task_definition_id"] = "new-definition"
    await storage.persist_job(job, persist_tasks=True)
    await legacy.finalize_job_completion(manager, job.job_id)
    assert len(commands) == 2
    assert commands[0][0] != commands[1][0]
    assert [identity for _, identity in commands] == [job.job_id, "new-definition"]


async def test_metadata_change_during_archive_can_retry_with_a_fresh_receipt(
    database, redis_manager, monkeypatch
):
    storage, job = await seed(redis_manager)
    manager = JobManager(storage.redis)
    publish = JobStorage._publish_task_archive_marker
    changed, commands = False, []

    async def rename_then_publish(self, job_id, count):
        nonlocal changed
        if not changed:
            changed = True
            renamed = copy.deepcopy(job)
            renamed.name = "Renamed during archive"
            await storage.persist_job(renamed)
        await publish(self, job_id, count)

    async def submit(operation, payload, **kwargs):
        item = command(job, **payload)
        item = replace(item, command_id=kwargs["command_id"])
        commands.append(item)
        return await execute(storage, item)

    monkeypatch.setattr(JobStorage, "_publish_task_archive_marker", rename_then_publish)
    manager.database_writes = SimpleNamespace(submit=submit)
    await legacy.finalize_job_completion(manager, job.job_id)
    assert (
        await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id))
        == 5
    )
    await legacy.finalize_job_completion(manager, job.job_id)
    assert (
        await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id))
        == 0
    )
    assert len(commands) == 2
    assert commands[0].command_id != commands[1].command_id
    assert (
        commands[0].payload["archive_signature"]
        != commands[1].payload["archive_signature"]
    )


async def test_archive_refuses_marker_if_sql_has_an_unexpected_extra_task(
    database, redis_manager, monkeypatch
):
    storage, job = await seed(redis_manager, count=1)
    insert_batch = JobStorage._insert_central_tasks_sync

    def with_extra_row(rows):
        result = insert_batch(rows)
        extra = inputs.task(99)
        extra.job_id = job.job_id
        with database.begin() as connection:
            connection.execute(
                insert(global_db.CentralTaskModel),
                [job_central_store._task_to_central_row(job.job_id, extra)],
            )
        return result

    monkeypatch.setattr(
        JobStorage, "_insert_central_tasks_sync", staticmethod(with_extra_row)
    )
    with pytest.raises(RuntimeError, match="database=2"):
        await execute(storage, command(job))
    assert not await storage._client().exists(
        storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    )
    assert (
        await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id))
        == 1
    )


async def test_actual_edit_transaction_locks_header_and_persists_identity(
    database, redis_manager, monkeypatch
):
    storage, job = await seed(redis_manager)
    monkeypatch.setattr(
        JobManager, "_resolve_backend_assignment", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        jobs, "_build_task_from_payload", AsyncMock(return_value=inputs.task(99))
    )
    statements = []
    from sqlalchemy import event

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(database, "before_cursor_execute", capture)
    try:
        await jobs._update_job(
            job.job_id,
            jobs.UpdateJobRequest(
                tasks=[jobs.TaskPayload(task_type="api_command", params={})]
            ),
            SimpleNamespace(
                redis=SimpleNamespace(**vars(storage.redis), is_connected=True),
                distributed_mode=False,
            ),
            SimpleNamespace(),
        )
    finally:
        event.remove(database, "before_cursor_execute", capture)
    lock_index = next(
        i
        for i, sql in enumerate(statements)
        if "FOR UPDATE" in sql and "management.jobs" in sql
    )
    delete_index = next(
        i
        for i, sql in enumerate(statements)
        if sql.startswith("DELETE FROM management.job_tasks")
    )
    assert lock_index < delete_index
    with database.connect() as connection:
        config = json.loads(
            connection.scalar(
                select(global_db.CentralJobModel.job_config_json).where(
                    global_db.CentralJobModel.job_id == job.job_id
                )
            )
        )
    header = await storage.fetch_job(job.job_id, include_tasks=False)
    assert (
        config["metadata"]["task_definition_id"]
        == header.metadata["task_definition_id"]
    )
