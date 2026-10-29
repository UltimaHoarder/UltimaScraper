"""Normal retries avoid discarded histories and own bounded SQL work."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, event, text
from sqlalchemy.orm import registry
from sqlmodel import Session

import test_normal_job_sql_resources as sql_fixtures
import ultima_scraper_db_archive as archive
from ultima_scraper_backend.database import threads as database_threads
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.database import factory
from ultima_scraper_backend.job_system import Job, Task, TaskState, TaskType
from ultima_scraper_backend.job_system.manager import JobManager
from ultima_scraper_backend.job_system.models import TaskResult
from ultima_scraper_db_archive import global_db

postgres_engine = sql_fixtures.postgres_engine
database = sql_fixtures.database


def sample_job(count=7):
    return Job.create(
        name="Retry: Example",
        created_by="test",
        tasks=[
            Task(
                task_type=TaskType.DOWNLOAD,
                site_name="OnlyFans",
                user_id=i + 1,
                auth_id=i + 10,
                state=TaskState.FAILED,
            )
            for i in range(count)
        ],
    )


async def prepare(monkeypatch, source, auth_id=None):
    manager = JobManager(SimpleNamespace(client=AsyncMock()))
    monkeypatch.setattr(
        manager.storage, "fetch_job_with_tasks", AsyncMock(return_value=source)
    )
    return await manager.prepare_retry_job(source.job_id, auth_id=auth_id)


@pytest.mark.parametrize("failed", [False, True])
async def test_retry_does_not_serialize_discarded_history(monkeypatch, failed):
    source = sample_job(3)
    for task in source.tasks:
        task.state = TaskState.FAILED if failed else TaskState.COMPLETED
        task.result = TaskResult(success=False, output={"retained_history": "large"})
        task.subtasks = [Task(task_type=TaskType.API_COMMAND, user_id=1)]
        task.attempts = 4
        task.depends_on = ["previous"]
    snapshots = [(task.result, task.subtasks, task.task_id) for task in source.tasks]

    def discarded(*args):
        pytest.fail("Retry serialized result history that it discards")

    monkeypatch.setattr(TaskResult, "to_dict", discarded)
    original, retried = await prepare(monkeypatch, source, auth_id=99)
    assert original is source
    assert len(retried.tasks) == 3
    for task, (result, subtasks, old_id), original_task in zip(
        retried.tasks, snapshots, source.tasks
    ):
        assert task.task_id != old_id
        assert task.job_id == original_task.job_id
        assert task.result is None and task.subtasks == [] and task.depends_on == []
        assert task.state == TaskState.PENDING and task.attempts == 0
        assert task.auth_id == 99
        assert original_task.result is result and original_task.subtasks is subtasks
        assert original_task.auth_id != 99
    assert retried.name == "Retry: Example"


async def test_sparse_retry_never_normalizes_successful_payloads(monkeypatch):
    source = sample_job(100)
    failed_id = source.tasks[-1].task_id
    for task in source.tasks[:-1]:
        task.state = TaskState.COMPLETED
    serialize = Task.to_dict
    visited = []

    def capture(task):
        visited.append(task.user_id)
        return serialize(task)

    monkeypatch.setattr(Task, "to_dict", capture)
    _, retried = await prepare(monkeypatch, source)
    assert visited == [100]
    assert len(retried.tasks) == 1
    assert retried.tasks[0].task_id != failed_id
    assert retried.tasks[0].auth_id == source.tasks[-1].auth_id


@pytest.fixture
def route(monkeypatch):
    original = sample_job()
    retried = sample_job()
    retried.metadata = {"retry_of": original.job_id}
    for task in retried.tasks:
        task.state = TaskState.PENDING
    activate = AsyncMock(return_value=("fixture", []))
    manager = SimpleNamespace(
        prepare_retry_job=AsyncMock(return_value=(original, retried)),
        activate_retry_job=activate,
    )
    storage = SimpleNamespace(
        fetch_job=AsyncMock(return_value=original),
        get_job_task_stats=AsyncMock(return_value={}),
    )
    monkeypatch.setattr(jobs, "JobManager", lambda redis: manager)
    monkeypatch.setattr(jobs, "JobStorage", lambda redis: storage)
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    monkeypatch.setattr(
        factory,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(
            get_or_create_manager=lambda site: None,
        ),
    )
    backend = SimpleNamespace(
        redis=SimpleNamespace(is_connected=True),
        distributed_mode=True,
        instance_id="fixture",
    )

    async def call(auth_id=None):
        return await jobs.retry_job(
            original.job_id, jobs.RetryJobRequest(auth_id=auth_id), backend
        )

    return SimpleNamespace(
        original=original,
        retried=retried,
        activate=activate,
        call=call,
        manager=manager,
    )


@pytest.fixture
def auth_database(database, monkeypatch):
    """Native auth query fixture with the production query's public columns."""
    mapper = registry()
    table = Table(
        "retry_auth_fixture",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("user_id", Integer),
        Column("site", String),
        Column("active", Boolean),
        Column("credentials", String),
    )

    class Auth:
        pass

    mapper.map_imperatively(Auth, table)
    table.create(database)
    sessions = []

    def session():
        value = Session(database)
        sessions.append(value)
        return value

    monkeypatch.setattr(archive, "UserAuthModel", Auth)
    monkeypatch.setattr(
        factory,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(
            get_or_create_manager=lambda site: SimpleNamespace(get_session=session),
        ),
    )
    try:
        yield table
    finally:
        table.drop(database)
        mapper.dispose()


@pytest.mark.parametrize("override", [None, 99])
async def test_retry_batches_auth_ids_and_rows_independently(
    database, route, auth_database, monkeypatch, override
):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "3")
    monkeypatch.setenv("ULTIMA_JOB_AUTH_VALIDATION_BATCH_SIZE", "4")
    sql_fixtures.persist_header(route.original)
    if override is not None:
        for task in route.retried.tasks:
            task.auth_id = override
    with database.begin() as connection:
        connection.execute(
            auth_database.insert(),
            [
                {
                    "user_id": aid,
                    "active": True,
                    "site": "onlyfans",
                    "credentials": "fixture",
                }
                for aid in range(10, 17)
                if override is None
            ]
            or [
                {
                    "user_id": override,
                    "active": True,
                    "site": "onlyfans",
                    "credentials": "fixture",
                }
            ],
        )
    reads = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM retry_auth_fixture" in statement:
            reads.append((statement, parameters))

    event.listen(database, "before_cursor_execute", capture)
    try:
        with sql_fixtures.insert_batches(database) as writes:
            response = await route.call(override)
    finally:
        event.remove(database, "before_cursor_execute", capture)
    assert response.job_id == route.retried.job_id
    assert writes == [3, 3, 1]
    assert len(reads) == (2 if override is None else 1)
    assert all("credentials" not in query for query, _ in reads)
    assert all(len(params) <= 5 for _, params in reads)
    with database.connect() as connection:
        row = connection.execute(
            text("SELECT status, last_event_at FROM management.jobs WHERE job_id=:id"),
            {"id": route.original.job_id},
        ).one()
        assert row.status == "cancelled" and row.last_event_at is not None
        rows = connection.execute(
            text("SELECT task_id, auth_id FROM management.job_tasks WHERE job_id=:id"),
            {"id": route.retried.job_id},
        ).all()
    assert {row.task_id for row in rows} == {
        task.task_id for task in route.retried.tasks
    }
    assert {row.auth_id for row in rows} == ({99} if override else set(range(10, 17)))
    route.activate.assert_awaited_once()


async def test_retry_rejects_auth_active_on_another_site(
    database, route, auth_database
):
    for task in route.retried.tasks:
        task.auth_id = 12
    with database.begin() as connection:
        connection.execute(
            auth_database.insert(), {"user_id": 12, "site": "fansly", "active": True}
        )
    with pytest.raises(HTTPException) as error:
        await route.call()
    assert error.value.status_code == 400
    route.activate.assert_not_awaited()


@pytest.mark.parametrize("second_site_active", [False, True])
async def test_mixed_site_retry_validates_each_site_before_publication(
    database, route, auth_database, monkeypatch, second_site_active
):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "2")
    # Omitted auth budget derives from the explicitly configured insertion size.
    monkeypatch.delenv("ULTIMA_JOB_AUTH_VALIDATION_BATCH_SIZE", raising=False)
    sql_fixtures.persist_header(route.original)
    for task in route.retried.tasks:
        task.auth_id = 10
    route.retried.tasks[-1].site_name = "Fansly"
    with database.begin() as connection:
        connection.execute(
            auth_database.insert(),
            [
                {"user_id": 10, "site": "onlyfans", "active": True},
                {"user_id": 10, "site": "fansly", "active": second_site_active},
            ],
        )
    if second_site_active:
        await route.call()
        route.activate.assert_awaited_once()
    else:
        with pytest.raises(HTTPException) as error:
            await route.call()
        assert error.value.status_code == 400
        route.activate.assert_not_awaited()
        with database.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT status FROM management.jobs WHERE job_id=:id"),
                    {"id": route.original.job_id},
                )
                == "pending"
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM management.jobs WHERE job_id=:id"),
                    {"id": route.retried.job_id},
                )
                == 0
            )


async def test_failed_later_retry_batch_rolls_back_source_and_blocks_activation(
    database, route, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "3")
    sql_fixtures.persist_header(route.original)
    route.retried.tasks[-1].task_id = route.retried.tasks[0].task_id
    with pytest.raises(HTTPException) as error:
        await route.call()
    assert error.value.status_code == 503
    route.activate.assert_not_awaited()
    with database.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT status FROM management.jobs WHERE job_id=:id"),
                {"id": route.original.job_id},
            )
            == "pending"
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM management.jobs WHERE job_id=:id"),
                {"id": route.retried.job_id},
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id=:id"),
                {"id": route.retried.job_id},
            )
            == 0
        )


@pytest.mark.parametrize(
    "setting",
    ["ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "ULTIMA_JOB_AUTH_VALIDATION_BATCH_SIZE"],
)
@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
async def test_invalid_retry_budget_blocks_submission(
    monkeypatch, route, setting, value
):
    monkeypatch.setenv(setting, value)

    def forbidden():
        pytest.fail("Invalid setting opened a SQL session")

    monkeypatch.setattr(global_db, "global_session", forbidden)
    with pytest.raises(ValueError, match=setting):
        await route.call()
    route.activate.assert_not_awaited()
    route.manager.prepare_retry_job.assert_not_awaited()


def blocked_session(monkeypatch, entered, release, closed):
    class BlockingSession:
        def exec(self, statement):
            entered.append(threading.get_ident())
            assert release.wait(5)
            return SimpleNamespace(first=lambda: None)

        def add(self, value):
            pass

        def add_all(self, value):
            pass

        def execute(self, *args):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

    @contextmanager
    def session():
        try:
            yield BlockingSession()
        finally:
            closed.append(True)

    monkeypatch.setattr(global_db, "global_session", session)


async def test_retry_cancellation_owns_sql_session_cleanup(monkeypatch, route):
    entered, closed, release = [], [], threading.Event()
    blocked_session(monkeypatch, entered, release, closed)
    pending = asyncio.create_task(route.call())
    try:
        async with asyncio.timeout(3):
            while not entered:
                await asyncio.sleep(0.001)
        pending.cancel()
        await asyncio.sleep(0.02)
        assert not pending.done(), "Retry SQL outlived its cancelled request"
        assert not closed
    finally:
        release.set()
        result = await asyncio.gather(pending, return_exceptions=True)
        async with asyncio.timeout(3):
            while not closed:
                await asyncio.sleep(0.001)
    assert isinstance(result[0], asyncio.CancelledError)
    route.activate.assert_not_awaited()


async def test_retry_concurrency_uses_interactive_sql_admission(monkeypatch, route):
    monkeypatch.setenv("ULTIMA_INTERACTIVE_DB_CONCURRENCY", "2")
    entered, closed, release = [], [], threading.Event()
    blocked_session(monkeypatch, entered, release, closed)
    pending = [asyncio.create_task(route.call()) for _ in range(8)]
    try:
        async with asyncio.timeout(3):
            while len(entered) < 2:
                await asyncio.sleep(0.001)
        await asyncio.sleep(0.03)
        assert len(entered) == 2
        assert database_threads.database_thread_limiter().borrowed_tokens == 2
    finally:
        release.set()
        await asyncio.gather(*pending)
    assert len(closed) == 8
