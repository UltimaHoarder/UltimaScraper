"""Task purge must leave proof for the later, separately receipted header archive."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import test_normal_archive_generation as fixtures
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteResult,
    DatabaseWriteRejected,
    stable_command_id,
)
from ultima_scraper_backend.database.write_receipts import lookup, record_failure
from ultima_scraper_backend.job_system import JobManager
from ultima_scraper_backend.job_system import retention
from ultima_scraper_backend.job_system.models import JobState
from functools import partial

import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
database = fixtures.database
redis_manager = fixtures.redis_manager


def writer_bridge(storage, job, *, poison_old_header=False):
    submitted = []
    old_header_ids = []

    async def submit(operation, payload, **options):
        item = replace(
            fixtures.command(job, **payload), command_id=options["command_id"]
        )
        assert item.operation == operation
        submitted.append(item)
        if poison_old_header and payload.get("archive_header"):
            old_id = stable_command_id(
                "archive-job-header-v1",
                job.job_id,
                payload["generation"],
                payload["batch_size"],
                payload["max_bytes"],
                payload["header_max_bytes"],
                payload["task_definition_id"],
                payload["archive_signature"],
            )
            old_header_ids.append(old_id)
            await asyncio.to_thread(
                record_failure,
                replace(item, command_id=old_id),
                DatabaseWriteResult(
                    old_id,
                    False,
                    {},
                    "Failed after 8 attempts: no matching completion marker or live task index",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return await fixtures.execute(storage, item)

    bridge = SimpleNamespace(
        submit=submit, max_command_bytes=storage.database_writes.max_command_bytes
    )
    storage.database_writes = bridge
    return bridge, submitted, old_header_ids


@pytest.mark.parametrize("status", [JobState.COMPLETED, JobState.CANCELLED])
async def test_finalize_then_header_retirement_preserves_task_results(
    database, redis_manager, status
):
    storage, job = await fixtures.seed(redis_manager)
    job.state = status
    await storage.persist_job(job)
    manager = JobManager(storage.redis)
    manager.database_writes, submitted, _ = writer_bridge(storage, job)
    finish = (
        partial(legacy.finalize_job_completion, manager)
        if status == JobState.COMPLETED
        else manager.finalize_job_cancellation
    )
    await finish(job.job_id)
    marker_key = storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    marker = json.loads(await storage._client().get(marker_key) or "null")
    assert marker and marker["task_count"] == len(job.tasks)
    assert marker["generation"] == job.completed_at
    assert not await storage._client().exists(
        storage.TASK_INDEX_KEY.format(job_id=job.job_id)
    )
    await finish(job.job_id)  # Replays the successful task archive receipt.
    assert await storage.cleanup_completed_jobs(0, batch_size=10) == 1
    assert len(submitted) == 3 and submitted[-1].payload["archive_header"]
    assert not await storage._client().exists(marker_key)
    assert await storage.fetch_job(job.job_id, include_tasks=False) is None
    with database.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT task_id, result_json FROM management.job_tasks WHERE job_id=:job"
            ),
            {"job": job.job_id},
        ).all()
        assert {task_id for task_id, _ in rows} == {task.task_id for task in job.tasks}
        assert all(
            json.loads(result)["output"]["evidence"] == task_id
            for task_id, result in rows
        )
        assert (
            connection.scalar(
                text("SELECT status FROM management.jobs WHERE job_id=:job"),
                {"job": job.job_id},
            )
            == status.value
        )


async def test_old_purged_job_recovers_from_exact_success_receipt_despite_failed_header_receipt(
    database, redis_manager
):
    storage, job = await fixtures.seed(redis_manager)
    manager = JobManager(storage.redis)
    manager.database_writes, submitted, old_ids = writer_bridge(
        storage, job, poison_old_header=True
    )
    await legacy.finalize_job_completion(manager, job.job_id)
    # Reproduce the old bug after the successful, receipted SQL task archive.
    await storage._client().delete(
        storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    )
    assert await storage.cleanup_completed_jobs(0, batch_size=10) == 1
    assert len(old_ids) == 1 and submitted[-1].command_id != old_ids[0]
    receipts = await asyncio.to_thread(lookup, [old_ids[0], submitted[-1].command_id])
    assert not receipts[old_ids[0]].success  # Preserve the original failure evidence.
    assert receipts[submitted[-1].command_id].success
    with database.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM management.job_tasks WHERE job_id=:job AND result_json IS NOT NULL"
            ),
            {"job": job.job_id},
        ) == len(job.tasks)


@pytest.mark.parametrize(
    "change", ["sql-count", "generation", "definition", "configuration"]
)
async def test_receipt_recovery_refuses_incomplete_or_changed_archive(
    database, redis_manager, change
):
    storage, job = await fixtures.seed(redis_manager)
    manager = JobManager(storage.redis)
    manager.database_writes, _, _ = writer_bridge(storage, job)
    await legacy.finalize_job_completion(manager, job.job_id)
    marker_key = storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    await storage._client().delete(marker_key)
    if change == "sql-count":
        with database.begin() as connection:
            connection.execute(
                text("DELETE FROM management.job_tasks WHERE task_id=:task"),
                {"task": job.tasks[0].task_id},
            )
    else:
        if change == "generation":
            job.completed_at = "2026-01-01T00:00:00+00:00"
        elif change == "definition":
            job.metadata["task_definition_id"] = "another-definition"
        else:
            job.name = "Changed configuration"
        await storage.persist_job(job)
    with pytest.raises(RuntimeError, match="incomplete|no matching completion marker"):
        await fixtures.execute(storage, fixtures.command(job))
    assert not await storage._client().exists(marker_key)
    assert await storage.fetch_job(job.job_id, include_tasks=False) is not None


async def test_zero_task_completion_proof_survives_finalization(
    database, redis_manager
):
    storage, job = await fixtures.seed(redis_manager, count=0)
    snapshot = await retention.capture_terminal(storage, job.job_id)
    with retention.scope(snapshot):
        await storage._publish_task_archive_marker(job.job_id, 0)
    manager = JobManager(storage.redis)
    manager.database_writes, _, _ = writer_bridge(storage, job)
    await legacy.finalize_job_completion(manager, job.job_id)
    assert await storage._client().exists(
        storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    )
    assert await storage.cleanup_completed_jobs(0, batch_size=10) == 1


async def test_legacy_sql_result_without_archive_proof_is_rejected_and_retained(
    database, redis_manager
):
    storage, job = await fixtures.seed(redis_manager, count=1)
    job.state = JobState.CANCELLED
    await storage.persist_job(job)
    # Legacy archiving predates the successful command receipt and removed
    # both proof and working set. A stored result alone is not archive proof.
    snapshot = await retention.capture_terminal(storage, job.job_id)
    with retention.scope(snapshot):
        await storage._archive_job_tasks_to_db(job.job_id)
        await storage.purge_job_task_blobs(job.job_id)
    marker_key = storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    await storage._client().delete(marker_key)
    with pytest.raises(DatabaseWriteRejected, match="retaining job and stored tasks"):
        await fixtures.execute(storage, fixtures.command(job))
    writer_bridge(storage, job)
    assert await storage.cleanup_completed_jobs(0, batch_size=10) == 0
    assert await storage.fetch_job(job.job_id, include_tasks=False) is not None
    assert not await storage._client().exists(marker_key)
    with database.connect() as connection:
        assert connection.scalar(text(
            "SELECT count(*) FROM management.job_tasks WHERE job_id=:job AND result_json IS NOT NULL"
        ), {"job": job.job_id}) == 1


@pytest.mark.parametrize(
    ("success", "payload"),
    [
        (False, {"archived_tasks": 0}),
        (True, {"archived_tasks": 0, "stale": True}),
        (True, {"archived_tasks": False}),
        (True, {"archived_tasks": -1}),
        (True, {}),
    ],
)
async def test_failed_stale_or_invalid_receipt_cannot_certify_empty_archive(
    database, redis_manager, success, payload
):
    storage, job = await fixtures.seed(redis_manager, count=0)
    snapshot = await retention.capture_terminal(storage, job.job_id)
    batch_size, max_bytes = storage.task_archive_limits()
    receipt_id = stable_command_id(
        "archive-job-tasks-v4",
        job.job_id,
        job.completed_at,
        batch_size,
        max_bytes,
        job.job_id,
        retention.archive_signature(snapshot),
    )
    item = replace(fixtures.command(job), command_id=receipt_id)
    await asyncio.to_thread(
        record_failure,
        item,
        DatabaseWriteResult(
            receipt_id,
            success,
            payload,
            None if success else "Archive failed",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    with pytest.raises(DatabaseWriteRejected, match="no matching completion marker"):
        await fixtures.execute(
            storage,
            fixtures.command(job, batch_size=batch_size, max_bytes=max_bytes),
        )
    assert not await storage._client().exists(
        storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    )
