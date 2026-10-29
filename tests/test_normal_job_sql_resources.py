"""Ordinary job SQL writes remain owned and consume bounded row batches."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import inspect
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

import test_mps_manifest as database_fixtures
from ultima_scraper_backend.database import threads as database_threads
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.api.routes import job_views
from ultima_scraper_backend.job_system import Job, Task, TaskType
from ultima_scraper_db_archive import global_db

postgres_engine = database_fixtures.postgres_engine


@pytest.fixture
async def detached_writes(monkeypatch):
    """Join the original implementation's detached writes after a failed probe."""
    pending = []
    create = asyncio.create_task

    def capture(coroutine, **kwargs):
        task = create(coroutine, **kwargs)
        if coroutine.cr_code.co_name == "_runner":
            pending.append(task)
        return task

    monkeypatch.setattr(jobs.asyncio, "create_task", capture)
    yield pending
    await asyncio.gather(*pending, return_exceptions=True)


def submission(tasks):
    return jobs._persist_central_job_submission(
        job_id="job-fixture", job_type="fixture", site="onlyfans",
        args_payload={}, tasks=tasks,
    )


def patch_sql_writer(monkeypatch, write):
    class Session:
        def get(self, *args):
            return None

        def add(self, *args):
            pass

        def execute(self, statement, rows):
            write(tasks=rows)

        def commit(self):
            pass

        def rollback(self):
            pass

    @contextmanager
    def session():
        yield Session()

    monkeypatch.setattr(global_db, "global_session", session)


@pytest.mark.parametrize("count", [1, 201])
async def test_submission_cancellation_owns_sql_until_cleanup(
    monkeypatch, detached_writes, count
):
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    def persist(**kwargs):
        entered.set()
        try:
            assert release.wait(5)
        finally:
            closed.set()

    patch_sql_writer(monkeypatch, persist)
    pending = asyncio.create_task(submission(fixture_job(count).tasks))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        pending.cancel()
        await asyncio.sleep(0.02)
        assert not pending.done(), "SQL outlived its cancelled submission"
        assert not closed.is_set()
    finally:
        release.set()
        result = await asyncio.gather(pending, return_exceptions=True)
        assert await asyncio.to_thread(closed.wait, 3)
    assert isinstance(result[0], asyncio.CancelledError)
    assert not detached_writes


async def test_concurrent_submissions_honor_interactive_sql_budget(
    monkeypatch, detached_writes
):
    monkeypatch.setenv("ULTIMA_INTERACTIVE_DB_CONCURRENCY", "2")
    release = threading.Event()
    started = []

    def persist(**kwargs):
        started.append(kwargs["tasks"])
        assert release.wait(5)

    patch_sql_writer(monkeypatch, persist)
    pending = [asyncio.create_task(submission(fixture_job(201).tasks)) for _ in range(8)]
    try:
        async with asyncio.timeout(3):
            while len(started) < 2:
                await asyncio.sleep(0.001)
        await asyncio.sleep(0.03)
        assert len(started) == 2
        assert database_threads.database_thread_limiter().borrowed_tokens == 2
        assert all(not task.done() for task in pending)
    finally:
        release.set()
        await asyncio.gather(*pending)
    assert not detached_writes
    assert len(started) == 8


async def test_large_submission_reports_task_write_failure(monkeypatch, detached_writes):
    def fail(**kwargs):
        raise RuntimeError("Fixture insert failed")

    patch_sql_writer(monkeypatch, fail)
    with pytest.raises(RuntimeError, match="Fixture insert failed"):
        await submission(fixture_job(201).tasks)
    assert not detached_writes


@pytest.fixture
def database(postgres_engine, monkeypatch):
    @contextmanager
    def session():
        with Session(postgres_engine, expire_on_commit=False) as value:
            yield value

    monkeypatch.setattr(global_db, "global_session", session)
    return postgres_engine


def fixture_job(count):
    return Job.create(
        name="Fixture", created_by="test",
        tasks=[
            Task(task_type=TaskType.DOWNLOAD, user_id=index + 1,
                 site_name="OnlyFans", user_username="person", auth_id=99)
            for index in range(count)
        ],
    )


def persist_job_sync(job, tasks=(), **kwargs):
    arguments = dict(
        job_id=job.job_id, job_type="fixture", status="pending",
        site="onlyfans", args_payload={"job_name": "Original"},
    )
    # This adapter lets the native before/after fixture exercise either source.
    if hasattr(jobs, "_persist_central_job_submission_sync"):
        jobs._persist_central_job_submission_sync(**arguments, tasks=tasks, **kwargs)
    else:
        jobs._persist_central_job_row_sync(**arguments)
        jobs._persist_central_task_rows_sync(job_id=job.job_id, tasks=tasks, **kwargs)


def persist_header(job):
    persist_job_sync(job)


@contextmanager
def insert_batches(engine):
    batches = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO management.job_tasks"):
            batches.append(len(context.compiled_parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield batches
    finally:
        event.remove(engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("explicit", [None, 4])
def test_submission_row_batches_preserve_explicit_settings(database, monkeypatch, explicit):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "3")
    job = fixture_job(7)
    persist_header(job)
    options = {} if explicit is None else {"batch_size": explicit}
    with insert_batches(database) as batches:
        persist_job_sync(job, tasks=job.tasks, **options)
    assert batches == ([3, 3, 1] if explicit is None else [4, 3])
    with database.connect() as connection:
        records = connection.execute(
            text("SELECT task_id, task_type, username, auth_id FROM management.job_tasks WHERE job_id=:job"),
            {"job": job.job_id},
        ).all()
    assert {row.task_id for row in records} == {task.task_id for task in job.tasks}
    assert all(row.task_type == "download" and row.username == "person" and row.auth_id == 99 for row in records)


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_invalid_batch_setting_precedes_session_creation(monkeypatch, value):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", value)

    def session():
        pytest.fail("Invalid batch setting opened a SQL session")

    monkeypatch.setattr(global_db, "global_session", session)
    with pytest.raises(ValueError, match="ULTIMA_JOB_TASK_INSERT_BATCH_SIZE"):
        job = fixture_job(1)
        persist_job_sync(job, tasks=job.tasks)


@pytest.mark.parametrize("invalid_last_batch", [False, True])
async def test_replacement_batches_preserve_one_sql_transaction(
    database, monkeypatch, invalid_last_batch
):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "3")
    job = fixture_job(7)
    persist_header(job)
    old_id = f"old-{uuid4().hex}"
    with Session(database) as session:
        session.add(global_db.CentralTaskModel(
            task_id=old_id, job_id=job.job_id, task_type="download", status="pending",
        ))
        session.commit()
    if invalid_last_batch:
        job.tasks[-1].task_id = job.tasks[0].task_id
    manager = SimpleNamespace(update_job_by_id=AsyncMock(return_value=job))
    monkeypatch.setattr(jobs, "JobManager", lambda redis: manager)
    monkeypatch.setattr(jobs, "_build_task_from_payload", AsyncMock(side_effect=job.tasks))
    request = jobs.UpdateJobRequest(
        job_name="Changed",
        tasks=[jobs.TaskPayload(task_type="download", params={}) for _ in job.tasks],
    )
    backend = SimpleNamespace(redis=SimpleNamespace(is_connected=True), distributed_mode=True)
    with insert_batches(database) as batches:
        response = await jobs.update_job(
            job.job_id, request, backend=backend, backend_manager=SimpleNamespace(),
        )
    assert response.task_count == 7
    assert batches == [3, 3, 1]
    with database.connect() as connection:
        ids = set(connection.scalars(
            text("SELECT task_id FROM management.job_tasks WHERE job_id=:job"),
            {"job": job.job_id},
        ))
        name = connection.scalar(
            text("SELECT args_json::json->>'job_name' FROM management.jobs WHERE job_id=:job"),
            {"job": job.job_id},
        )
    assert ids == ({old_id} if invalid_last_batch else {task.task_id for task in job.tasks})
    assert name == ("Original" if invalid_last_batch else "Changed")


async def test_cancelled_metadata_update_owns_sql_commit(database, monkeypatch):
    monkeypatch.setenv("ULTIMA_INTERACTIVE_DB_CONCURRENCY", "1")
    job = fixture_job(1)
    persist_header(job)
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    real_session = global_db.global_session

    @contextmanager
    def session():
        try:
            with real_session() as value:
                commit = value.commit

                def held_commit():
                    entered.set()
                    assert release.wait(5)
                    commit()

                value.commit = held_commit
                yield value
        finally:
            closed.set()

    monkeypatch.setattr(global_db, "global_session", session)
    manager = SimpleNamespace(update_job_by_id=AsyncMock(return_value=job))
    monkeypatch.setattr(jobs, "JobManager", lambda redis: manager)
    backend = SimpleNamespace(redis=SimpleNamespace(is_connected=True), distributed_mode=True)
    pending = asyncio.create_task(jobs.update_job(
        job.job_id, jobs.UpdateJobRequest(job_name="Committed"),
        backend=backend, backend_manager=SimpleNamespace(),
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        pending.cancel()
        await asyncio.sleep(0.02)
        assert not pending.done()
        assert not closed.is_set()
        assert database_threads.database_thread_limiter().borrowed_tokens == 1
    finally:
        release.set()
        result = await asyncio.gather(pending, return_exceptions=True)
        assert await asyncio.to_thread(closed.wait, 3)
    assert isinstance(result[0], asyncio.CancelledError)
    with database.connect() as connection:
        assert connection.scalar(
            text("SELECT args_json::json->>'job_name' FROM management.jobs WHERE job_id=:job"),
            {"job": job.job_id},
        ) == "Committed"


async def test_replacement_uses_canonical_paid_feed_label(database, monkeypatch):
    task = jobs.build_task(
        TaskType.SCRAPE, site_name="OnlyFans", user_id=99, auth_id=99,
        paid_content_feed=True,
    )
    job = Job.create(name="Paid feed", created_by="test", tasks=[task])
    persist_header(job)
    manager = SimpleNamespace(update_job_by_id=AsyncMock(return_value=job))
    monkeypatch.setattr(jobs, "JobManager", lambda redis: manager)
    monkeypatch.setattr(jobs, "_build_task_from_payload", AsyncMock(return_value=task))
    backend = SimpleNamespace(redis=SimpleNamespace(is_connected=True), distributed_mode=True)
    await jobs.update_job(
        job.job_id,
        jobs.UpdateJobRequest(tasks=[jobs.TaskPayload(task_type="scrape_paid_content", params={})]),
        backend=backend, backend_manager=SimpleNamespace(),
    )
    with database.connect() as connection:
        assert connection.scalar(
            text("SELECT task_type FROM management.job_tasks WHERE job_id=:job"),
            {"job": job.job_id},
        ) == "scrape_paid_content"


async def test_initial_header_and_rows_publish_together(database, monkeypatch, detached_writes):
    job = fixture_job(201)
    entered = threading.Event()
    release = threading.Event()

    def before_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO management.job_tasks") and not entered.is_set():
            entered.set()
            assert release.wait(5)

    event.listen(database, "before_cursor_execute", before_insert)
    pending = asyncio.create_task(jobs._persist_central_job_submission(
        job_id=job.job_id, job_type="fixture", site="onlyfans",
        args_payload={"task_count": len(job.tasks)}, tasks=job.tasks,
    ))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        with database.connect() as connection:
            assert connection.scalar(
                text("SELECT count(*) FROM management.jobs WHERE job_id=:job"),
                {"job": job.job_id},
            ) == 0, "An incomplete job became visible to recovery"
        assert not pending.done()
    finally:
        release.set()
        await pending
        await asyncio.gather(*detached_writes, return_exceptions=True)
        event.remove(database, "before_cursor_execute", before_insert)
    with database.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"),
            {"job": job.job_id},
        ) == 201
        assert connection.scalar(
            text("SELECT last_event_at FROM management.jobs WHERE job_id=:job"),
            {"job": job.job_id},
        ) is not None


async def test_failed_initial_batch_rolls_back_header_and_rows(database, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "3")
    job = fixture_job(7)
    job.tasks[-1].task_id = job.tasks[0].task_id
    with pytest.raises(IntegrityError, match="duplicate key"):
        await jobs._persist_central_job_submission(
            job_id=job.job_id, job_type="fixture", site="onlyfans",
            args_payload={"task_count": len(job.tasks)}, tasks=job.tasks,
        )
    with database.connect() as connection:
        for table in ("jobs", "job_tasks"):
            assert connection.scalar(
                text(f"SELECT count(*) FROM management.{table} WHERE job_id=:job"),
                {"job": job.job_id},
            ) == 0


@pytest.mark.parametrize("recent", [False, True])
def test_recovery_grace_uses_latest_sql_activity(recent):
    now = datetime.now(timezone.utc)
    stale = now - 2 * job_views.GHOST_JOB_GRACE_PERIOD
    activity = {}
    if "last_activity_at" in inspect.signature(jobs._is_stale_incomplete_active_job).parameters:
        activity["last_activity_at"] = now if recent else stale - timedelta(seconds=1)
    assert jobs._is_stale_incomplete_active_job(
        status="pending", created_at=stale, has_redis_artifact=False,
        has_canonical_artifacts=False, expected_task_count=201,
        **activity,
    ) is (not recent)
