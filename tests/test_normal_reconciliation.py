"""Archive reconciliation uses bounded, independently committed writer pages."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlmodel import Session

import test_mps_manifest as fixtures
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteCommand,
    DatabaseWriteOperation,
)
from ultima_scraper_backend.job_system import JobStorage
from ultima_scraper_backend.workers.worker_pool import Worker
from ultima_scraper_db_archive import global_db

postgres_engine = fixtures.postgres_engine


@pytest.fixture
def database(postgres_engine, monkeypatch):
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE management.job_tasks, management.jobs"))

    @contextmanager
    def session():
        with Session(postgres_engine) as value:
            yield value

    monkeypatch.setattr(global_db, "global_session", session)
    return postgres_engine


def seed(database, count, *, job_id="job-fixture", status="completed", when=None):
    when = when or datetime(2026, 1, 1, tzinfo=timezone.utc)
    with database.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO management.jobs (job_id, job_type, site, status, completed_at) VALUES (:job, 'download', 'onlyfans', :status, :when)"
            ),
            {"job": job_id, "status": status, "when": when},
        )
        connection.execute(
            text(
                "INSERT INTO management.job_tasks (task_id, job_id, task_type, status) SELECT :job || '-' || lpad(i::text, 9, '0'), :job, 'download', 'pending' FROM generate_series(1, :count) i"
            ),
            {"job": job_id, "count": count},
        )


def pending_count(database):
    with database.connect() as connection:
        return connection.scalar(
            text("SELECT count(*) FROM management.job_tasks WHERE status='pending'")
        )


@pytest.mark.parametrize("count", [0, 1, 3, 4, 7])
def test_sql_pages_bound_mutations_and_preserve_every_task(database, count):
    seed(database, count)
    cursor, repaired, pages = None, 0, []
    while True:
        result = JobStorage._reconcile_database_jobs_sync(
            batch_size=3, after_task_id=cursor
        )
        assert 0 <= result["repaired_tasks"] <= 3
        repaired += result["repaired_tasks"]
        assert pending_count(database) == count - repaired
        pages.append(result)
        if result["next_task_id"] is None:
            break
        assert result["next_task_id"] != cursor
        cursor = result["next_task_id"]
    assert repaired == count
    assert len(pages) == count // 3 + 1
    with database.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(DISTINCT task_id) FROM management.job_tasks")
            )
            == count
        )


def test_reconciliation_keeps_each_jobs_own_timestamp(database):
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    seed(database, 2, job_id="a", when=first)
    seed(database, 2, job_id="b", when=first + timedelta(days=1))
    JobStorage._reconcile_database_jobs_sync()
    with database.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM management.job_tasks t JOIN management.jobs j USING (job_id) WHERE t.completed_at IS DISTINCT FROM j.completed_at"
                )
            )
            == 0
        )


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_only_unfinished_tasks_of_terminal_jobs_are_repaired(database, status):
    seed(database, 2, status=status)
    seed(database, 2, job_id="active", status="running")
    with database.begin() as connection:
        connection.execute(
            text(
                "UPDATE management.jobs SET result_error='retained error', result_completed_at=completed_at + interval '1 hour' WHERE job_id='job-fixture'"
            )
        )
        connection.execute(
            text(
                "UPDATE management.job_tasks SET status='failed', error='original task error' WHERE task_id='job-fixture-000000002'"
            )
        )
    result = JobStorage._reconcile_database_jobs_sync(batch_size=3)
    assert result == {"repaired_tasks": 1, "next_task_id": None}
    assert pending_count(database) == 2
    with database.connect() as connection:
        row = connection.execute(
            text(
                "SELECT t.status, t.error, t.last_event_at=j.result_completed_at AS event_matches, t.completed_at=j.result_completed_at AS completed_matches FROM management.job_tasks t JOIN management.jobs j USING (job_id) WHERE task_id='job-fixture-000000001'"
            )
        ).one()
        assert tuple(row) == (status, "retained error", True, True)
        assert (
            connection.scalar(
                text(
                    "SELECT error FROM management.job_tasks WHERE task_id='job-fixture-000000002'"
                )
            )
            == "original task error"
        )


@pytest.mark.parametrize("invalid", ["0", "-1", "invalid"])
def test_invalid_budget_precedes_sql_session(monkeypatch, invalid):
    monkeypatch.setenv("ULTIMA_JOB_RECONCILE_BATCH_SIZE", invalid)
    monkeypatch.setattr(
        global_db, "global_session", lambda: pytest.fail("Invalid budget opened SQL")
    )
    with pytest.raises(ValueError, match="ULTIMA_JOB_RECONCILE_BATCH_SIZE"):
        JobStorage._reconcile_database_jobs_sync()


def test_explicit_budget_overrides_environment(database, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_RECONCILE_BATCH_SIZE", "2")
    seed(database, 7)
    assert JobStorage._reconcile_database_jobs_sync()["repaired_tasks"] == 2
    assert JobStorage._reconcile_database_jobs_sync(batch_size=4)["repaired_tasks"] == 4
    assert pending_count(database) == 1


def command(*, cursor=None, batch_size=3):
    return DatabaseWriteCommand(
        command_id=f"reconcile-{uuid4().hex}",
        operation=DatabaseWriteOperation.RECONCILE_CENTRAL_JOBS,
        payload={"batch_size": batch_size, "after_task_id": cursor},
        site=None,
        producer_id="fixture",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def test_writer_receipt_commits_with_page_and_replays_cursor(database):
    seed(database, 7)
    item = command()
    result = PostgreSQLWriteExecutor._reconcile_central_jobs([item])[item.command_id]
    assert result == {"repaired_tasks": 3, "next_task_id": "job-fixture-000000003"}
    assert pending_count(database) == 4
    replayed = PostgreSQLWriteExecutor._reconcile_central_jobs([item])[item.command_id]
    assert replayed == result
    assert pending_count(database) == 4
    following = command(cursor=result["next_task_id"])
    result2 = PostgreSQLWriteExecutor._reconcile_central_jobs([following])[
        following.command_id
    ]
    assert result2 == {"repaired_tasks": 3, "next_task_id": "job-fixture-000000006"}
    assert pending_count(database) == 1


def test_failed_receipt_rolls_back_only_its_page_and_can_resume(database):
    seed(database, 7)
    first = command()
    previous = PostgreSQLWriteExecutor._reconcile_central_jobs([first])[
        first.command_id
    ]
    item = command(cursor=previous["next_task_id"])

    def fail_receipt(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO management.database_write_receipts"):
            raise RuntimeError("Injected receipt failure")

    event.listen(database, "before_cursor_execute", fail_receipt)
    try:
        with pytest.raises(RuntimeError, match="Injected receipt failure"):
            PostgreSQLWriteExecutor._reconcile_central_jobs([item])
    finally:
        event.remove(database, "before_cursor_execute", fail_receipt)
    assert pending_count(database) == 4
    resumed = PostgreSQLWriteExecutor._reconcile_central_jobs([item])[item.command_id]
    assert resumed["repaired_tasks"] == 3
    assert pending_count(database) == 1


def test_preexisting_queued_command_preserves_complete_sweep(database, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_RECONCILE_BATCH_SIZE", "3")
    seed(database, 7)
    item = command()
    item.payload.clear()
    result = PostgreSQLWriteExecutor._reconcile_central_jobs([item])[item.command_id]
    assert result == {"repaired_tasks": 7, "next_task_id": None}
    assert pending_count(database) == 0
    assert (
        PostgreSQLWriteExecutor._reconcile_central_jobs([item])[item.command_id]
        == result
    )


async def test_worker_restarts_from_committed_repairs(database, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_RECONCILE_BATCH_SIZE", "3")
    seed(database, 7)
    worker = Worker.__new__(Worker)
    worker.running = True
    calls = 0

    async def submit(operation, payload):
        nonlocal calls
        calls += 1
        item = command(
            cursor=payload["after_task_id"], batch_size=payload["batch_size"]
        )
        result = await asyncio.to_thread(
            PostgreSQLWriteExecutor._reconcile_central_jobs, [item]
        )
        if calls == 1:
            raise RuntimeError("Lost delivery after commit")
        return result[item.command_id]

    worker.database_writes = SimpleNamespace(submit=submit)
    with pytest.raises(RuntimeError, match="Lost delivery after commit"):
        await worker._reconcile_central_database_jobs()
    assert pending_count(database) == 4
    assert await worker._reconcile_central_database_jobs() == 4
    assert pending_count(database) == 0
