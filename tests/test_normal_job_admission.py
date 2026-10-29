"""A normal job may activate only after its SQL submission commits."""

import asyncio
from contextlib import contextmanager
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
import pytest
from sqlalchemy import event, text
from sqlmodel import Session

import test_mps_manifest as fixtures
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import Task, TaskType
from ultima_scraper_db_archive import global_db

# Job building must not open a site database; tasks pass through unexpanded.
pytestmark = pytest.mark.usefixtures("no_site_databases")

postgres_engine = fixtures.postgres_engine


@pytest.fixture
def database(postgres_engine, monkeypatch):
    @contextmanager
    def session():
        with Session(postgres_engine, expire_on_commit=False) as value:
            yield value

    monkeypatch.setattr(global_db, "global_session", session)
    return postgres_engine


def request_fixture(
    monkeypatch, kind, *, distributed=True, scheduled=False, local=False, count=7
):
    tasks = [
        Task(
            task_type=TaskType.DOWNLOAD, user_id=i + 1, site_name="OnlyFans", auth_id=7
        )
        for i in range(count)
    ]
    activation = AsyncMock(return_value=("fixture-backend", []))
    acknowledgement = AsyncMock()
    monkeypatch.setattr(
        jobs, "JobManager", lambda _redis: SimpleNamespace(activate_job=activation)
    )
    monkeypatch.setattr(jobs, "publish_ws_event", acknowledgement)
    backend = SimpleNamespace(
        redis=None if local else SimpleNamespace(is_connected=True),
        distributed_mode=distributed,
        instance_id="fixture-backend",
    )
    schedule = {"scheduled_for": "2099-01-01T00:00:00+00:00"} if scheduled else None
    if kind == "ordinary":
        monkeypatch.setattr(
            jobs, "_build_task_from_payload", AsyncMock(side_effect=tasks)
        )
        request = jobs.CreateJobRequest(
            job_name="Admission fixture",
            created_by="test",
            schedule=schedule,
            tasks=[jobs.TaskPayload(task_type="download", params={}) for _ in tasks],
        )

        async def submit():
            return await jobs.create_job(
                request, backend=backend, backend_manager=SimpleNamespace()
            )
    else:
        template = SimpleNamespace(
            name="Fixture",
            instantiate=lambda *args, **kwargs: SimpleNamespace(
                tasks=tasks, job_name="Template fixture", metadata={}
            ),
        )
        monkeypatch.setattr(
            jobs,
            "JobTemplateStore",
            lambda _redis: SimpleNamespace(
                get_template=AsyncMock(return_value=template)
            ),
        )
        monkeypatch.setattr(jobs, "resolve_user_identifier", AsyncMock(return_value=7))
        request = jobs.InstantiateTemplateRequest(
            created_by="test",
            parameter_values={"username": "fixture"},
            auth_id=7,
            schedule=schedule,
        )

        async def submit():
            return await jobs.instantiate_template(
                "fixture", request, backend=backend, backend_manager=SimpleNamespace()
            )

    return SimpleNamespace(
        submit=submit,
        activation=activation,
        acknowledgement=acknowledgement,
        tasks=tasks,
    )


def assert_not_activated(fixture):
    fixture.activation.assert_not_awaited()
    fixture.acknowledgement.assert_not_awaited()


@pytest.mark.parametrize("kind", ["ordinary", "template"])
@pytest.mark.parametrize("distributed", [False, True])
@pytest.mark.parametrize("scheduled", [False, True])
async def test_failed_sql_submission_cannot_activate_or_acknowledge(
    monkeypatch, kind, distributed, scheduled
):
    fixture = request_fixture(
        monkeypatch, kind, distributed=distributed, scheduled=scheduled
    )
    monkeypatch.setattr(
        jobs,
        "_persist_central_job_submission",
        AsyncMock(side_effect=RuntimeError("fixture private database details")),
    )
    with pytest.raises(HTTPException) as error:
        await fixture.submit()
    assert error.value.status_code == 503
    assert "fixture private" not in error.value.detail
    assert_not_activated(fixture)


async def test_local_fallback_also_requires_sql_commit(monkeypatch):
    fixture = request_fixture(monkeypatch, "ordinary", distributed=False, local=True)
    monkeypatch.setattr(
        jobs,
        "_persist_central_job_submission",
        AsyncMock(side_effect=RuntimeError("db down")),
    )
    with pytest.raises(HTTPException) as error:
        await fixture.submit()
    assert error.value.status_code == 503
    assert_not_activated(fixture)


def capture_submission(monkeypatch):
    identifiers = []
    persist = jobs._persist_central_job_submission_sync

    def capture(**kwargs):
        identifiers.append(kwargs["job_id"])
        return persist(**kwargs)

    monkeypatch.setattr(jobs, "_persist_central_job_submission_sync", capture)
    return identifiers


def sql_counts(database, job_id):
    with database.connect() as connection:
        return tuple(
            connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM management.jobs WHERE job_id=:job), (SELECT count(*) FROM management.mps_task_definitions d JOIN management.mps_plans p ON p.job_id=d.manifest_id WHERE p.parent_job_id=:job AND p.status='definition')"
                ),
                {"job": job_id},
            ).one()
        )


@pytest.mark.parametrize("kind", ["ordinary", "template"])
async def test_later_sql_batch_failure_rolls_back_and_blocks_activation(
    database, monkeypatch, kind
):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "3")
    fixture = request_fixture(monkeypatch, kind)
    identifiers = capture_submission(monkeypatch)
    batches = []

    def fail_second_batch(
        connection, cursor, statement, parameters, context, executemany
    ):
        if statement.startswith("INSERT INTO management.mps_task_definitions"):
            batches.append(len(context.compiled_parameters))
            if len(batches) == 2:
                raise RuntimeError("Fixture failure in second SQL batch")

    event.listen(database, "before_cursor_execute", fail_second_batch)
    try:
        with pytest.raises(HTTPException) as error:
            await fixture.submit()
        assert error.value.status_code == 503
    finally:
        event.remove(database, "before_cursor_execute", fail_second_batch)
    assert batches == [3, 3]
    assert len(identifiers) == 1
    assert sql_counts(database, identifiers[0]) == (0, 0)
    assert_not_activated(fixture)


@pytest.mark.parametrize("kind", ["ordinary", "template"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_activation_waits_for_commit_and_cancellation_owns_sql(
    database, monkeypatch, kind, cancel
):
    fixture = request_fixture(monkeypatch, kind)
    identifiers = capture_submission(monkeypatch)
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    session_factory = global_db.global_session

    @contextmanager
    def held_session():
        try:
            with session_factory() as session:
                commit = session.commit

                def held_commit():
                    entered.set()
                    assert release.wait(5)
                    commit()

                session.commit = held_commit
                yield session
        finally:
            closed.set()

    monkeypatch.setattr(global_db, "global_session", held_session)
    pending = asyncio.create_task(fixture.submit())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        assert sql_counts(database, identifiers[0]) == (0, 0)
        assert_not_activated(fixture)
        if cancel:
            pending.cancel()
            await asyncio.sleep(0.02)
            assert not pending.done()
            assert not closed.is_set()
    finally:
        release.set()
        (result,) = await asyncio.gather(pending, return_exceptions=True)
    assert closed.is_set()
    assert sql_counts(database, identifiers[0]) == (1, len(fixture.tasks))
    if cancel:
        assert isinstance(result, asyncio.CancelledError)
        assert_not_activated(fixture)
    else:
        assert not isinstance(result, BaseException), result
        fixture.activation.assert_awaited_once()
        fixture.acknowledgement.assert_awaited_once()
