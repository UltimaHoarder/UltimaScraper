"""Preserve full ordinary inputs while bounding new SQL write/read transfers."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect, select, text
from sqlmodel import Session

import test_normal_reconciliation as fixtures
import test_mps_manifest as service_fixtures
import test_normal_job_admission as admission_fixtures
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.api.routes import job_central_store
from ultima_scraper_backend.job_system import (
    Job,
    JobStorage,
    Task,
    TaskResult,
    TaskState,
    TaskType,
)
from ultima_scraper_backend.job_system.payloads import APICommandTaskPayload
from ultima_scraper_backend.job_system.storage import (
    ArchivedTaskInputsUnavailable,
    TaskPayloadBudgetExceeded,
)
from ultima_scraper_backend.job_system import storage as storage_module
from ultima_scraper_db_archive import global_db
import ultima_scraper_db_archive

# Job building must not open a site database; tasks pass through unexpanded.
pytestmark = pytest.mark.usefixtures("no_site_databases")

postgres_engine = fixtures.postgres_engine
database = fixtures.database
redis_manager = service_fixtures.redis_manager


def task(index=0, *, width=1000):
    return Task(
        task_id=f"task-{index:09}",
        task_type=TaskType.API_COMMAND,
        site_name="OnlyFans",
        user_id=index + 1,
        auth_id=19,
        payload=APICommandTaskPayload(
            command="get_user", args={"user_id": index + 1, "marker": "é" * width}
        ),
        capabilities=["onlyfans"],
        ip_lock_key="fixture-route",
        max_attempts=9,
    )


def fixture_job(count=7, *, width=1000):
    return Job.create(
        name="Durable inputs",
        created_by="fixture",
        tasks=[task(i, width=width) for i in range(count)],
        metadata={"priority": 17, "fixture": "kept"},
    )


def persist(job, **options):
    jobs._persist_central_job_submission_sync(
        job_id=job.job_id,
        job_type="fixture",
        status="pending",
        site="onlyfans",
        args_payload={"job_name": job.name},
        tasks=job.tasks,
        job_config=job.to_config(include_task_ids=False).to_dict(),
        **options,
    )


def storage_for(redis=None):
    if redis is None:
        return JobStorage(SimpleNamespace())
    client = redis.client
    return JobStorage(
        SimpleNamespace(
            client=client, get=client.get, set=client.set, delete=client.delete
        )
    )


def test_input_snapshot_excludes_results_without_visiting_them():
    value = task()
    child = task(1)
    output = SimpleNamespace(
        to_dict=lambda: pytest.fail("Input snapshot serialized execution output")
    )
    value.result = child.result = output
    value.subtasks.append(child)
    snapshot = value.to_dict(include_result=False)
    assert snapshot["result"] is None and snapshot["subtasks"][0]["result"] is None
    assert snapshot["payload"]["args"]["marker"] == "é" * 1000
    assert value.result is output and child.result is output


def test_light_job_config_does_not_iterate_task_membership():
    class Membership(list):
        def __iter__(self):
            pytest.fail("Light header iterated task membership")

    job = fixture_job(1)
    job.task_ids = Membership(["task-one"])
    job.tasks = Membership(job.tasks)
    assert job.to_config(include_task_ids=False).to_dict()["task_ids"] == []


def test_submission_preserves_canonical_inputs_and_uses_both_budgets(database):
    job = fixture_job()
    encoded = [job_central_store._task_to_central_row(job.job_id, value) for value in job.tasks]
    sizes = [
        sum(len(str(item).encode()) for item in row.values() if item is not None)
        for row in encoded
    ]
    budget = max(sizes) * 2
    batches = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO management.job_tasks"):
            values = context.compiled_parameters
            batches.append(len(values))
            assert len(values) <= 3
            assert (
                sum(
                    len(str(value).encode())
                    for row in values
                    for value in row.values()
                    if value is not None
                )
                <= budget
            )

    event.listen(database, "before_cursor_execute", capture)
    try:
        persist(job, batch_size=3, max_bytes=budget)
    finally:
        event.remove(database, "before_cursor_execute", capture)
    assert batches == [2, 2, 2, 1]
    with database.connect() as connection:
        config = json.loads(
            connection.scalar(
                text("SELECT job_config_json FROM management.jobs WHERE job_id=:job"),
                {"job": job.job_id},
            )
        )
        records = connection.execute(
            text(
                "SELECT task_id, definition_json FROM management.job_tasks WHERE job_id=:job ORDER BY task_id"
            ),
            {"job": job.job_id},
        ).all()
    assert config == job.to_config(include_task_ids=False).to_dict()
    assert [json.loads(raw) for _, raw in records] == [
        value.to_dict(include_result=False) for value in job.tasks
    ]


def test_new_columns_are_deferred_from_history_queries():
    task_sql = str(select(global_db.CentralTaskModel))
    job_sql = str(select(global_db.CentralJobModel))
    assert "definition_json" not in task_sql
    assert "job_config_json" not in job_sql


@pytest.mark.parametrize("manifest_id", ["", "definition-existing"])
def test_mps_inputs_keep_the_existing_durable_owner(manifest_id):
    value = task()
    value.mps_task_manifest = manifest_id
    assert storage_module._task_to_central_row(value, "job")["definition_json"] is None
    assert job_central_store._task_to_central_row("job", value)["definition_json"] is None


@pytest.mark.parametrize("explicit", [False, True])
def test_input_write_budget_override_ignores_invalid_parent_setting(
    monkeypatch, explicit
):
    monkeypatch.setenv("ULTIMA_DATABASE_WRITE_MAX_COMMAND_BYTES", "invalid")
    monkeypatch.setenv(
        "ULTIMA_JOB_TASK_INSERT_MAX_BYTES", "invalid" if explicit else "4321"
    )
    assert jobs._central_task_insert_max_bytes(4321 if explicit else None) == 4321


def test_oversized_input_rolls_back_prior_batches_and_header(database):
    job = fixture_job(3, width=10)
    job.tasks[-1].payload.args["marker"] = "x" * 100000
    with pytest.raises(TaskPayloadBudgetExceeded, match="SQL input insert"):
        persist(job, batch_size=1, max_bytes=10000)
    with database.connect() as connection:
        for table in ("jobs", "job_tasks"):
            assert (
                connection.scalar(
                    text(f"SELECT count(*) FROM management.{table} WHERE job_id=:job"),
                    {"job": job.job_id},
                )
                == 0
            )


@pytest.mark.parametrize("kind", ["ordinary", "template"])
async def test_input_budget_rejection_is_actionable_and_blocks_dispatch(
    monkeypatch, kind
):
    fixture = admission_fixtures.request_fixture(monkeypatch, kind)
    monkeypatch.setattr(
        jobs,
        "_persist_central_job_submission",
        AsyncMock(
            side_effect=TaskPayloadBudgetExceeded(
                "fixture", 200, 100, phase="SQL input insert"
            )
        ),
    )
    with pytest.raises(HTTPException) as error:
        await fixture.submit()
    assert error.value.status_code == 413
    assert "SQL input insert" in error.value.detail
    admission_fixtures.assert_not_activated(fixture)


@pytest.mark.parametrize("batch_size", [1, 3, 20])
async def test_input_pages_are_count_and_byte_bounded_and_lossless(
    database, batch_size
):
    job = fixture_job()
    persist(job)
    with database.connect() as connection:
        budget = connection.scalar(
            text(
                "SELECT max(octet_length(definition_json)) * 2 FROM management.job_tasks WHERE job_id=:job"
            ),
            {"job": job.job_id},
        )
        connection.execute(
            text(
                "UPDATE management.job_tasks SET result_json=repeat('x', 100000), status='failed' WHERE job_id=:job"
            ),
            {"job": job.job_id},
        )
        connection.commit()
    store = storage_for()
    cursor, recovered = None, []
    while True:
        page = await store.fetch_archived_task_page(
            job.job_id, after_task_id=cursor, batch_size=batch_size, max_bytes=budget
        )
        assert len(page.tasks) <= min(batch_size, 2)
        assert all(
            value.result is None and value.state == TaskState.FAILED
            for value in page.tasks
        )
        recovered.extend(page.tasks)
        if not page.has_more:
            break
        assert page.next_cursor and page.next_cursor != cursor
        cursor = page.next_cursor
    assert [value.task_id for value in recovered] == [
        value.task_id for value in job.tasks
    ]
    assert [value.payload.model_dump() for value in recovered] == [
        value.payload.model_dump() for value in job.tasks
    ]
    assert all(
        value.auth_id == 19 and value.max_attempts == 9 and value.job_id == job.job_id
        for value in recovered
    )


@pytest.mark.parametrize("raw", [None, "[]", "{}", "invalid"])
async def test_missing_or_invalid_historical_inputs_are_not_reconstructed(
    database, raw
):
    job = fixture_job(1)
    persist(job)
    with database.begin() as connection:
        connection.execute(
            text(
                "UPDATE management.job_tasks SET definition_json=:raw WHERE job_id=:job"
            ),
            {"raw": raw, "job": job.job_id},
        )
    with pytest.raises(ArchivedTaskInputsUnavailable):
        await storage_for().fetch_archived_task_page(job.job_id)


async def test_oversized_first_record_does_not_transfer_its_input(
    database, monkeypatch
):
    job = fixture_job(1, width=100000)
    persist(job)
    observed = []
    original = Session.execute

    def execute(session, statement, *args, **kwargs):
        result = original(session, statement, *args, **kwargs)
        if "metered_task_inputs" in str(statement):
            rows = result.all()
            observed.extend(rows)
            return SimpleNamespace(all=lambda: rows)
        return result

    monkeypatch.setattr(Session, "execute", execute)
    with pytest.raises(TaskPayloadBudgetExceeded, match="SQL input read"):
        await storage_for().fetch_archived_task_page(job.job_id, max_bytes=1000)
    assert len(observed) == 1 and observed[0][-1] is None


async def test_archive_preserves_inputs_and_separate_results(database, redis_manager):
    store = storage_for(redis_manager)
    job = fixture_job(3)
    persist(job)
    for value in job.tasks:
        value.state = TaskState.COMPLETED
        value.result = TaskResult(success=True, output={"evidence": "retained result"})
    await store.persist_job(job, persist_tasks=True)
    assert (
        await store._archive_job_tasks_to_db(job.job_id, batch_size=2, max_bytes=50000)
        == 3
    )
    await store.purge_job_task_blobs(job.job_id)
    page = await store.fetch_archived_task_page(job.job_id, max_bytes=50000)
    assert len(page.tasks) == 3 and all(value.result is None for value in page.tasks)
    with database.connect() as connection:
        results = connection.scalars(
            text("SELECT result_json FROM management.job_tasks WHERE job_id=:job"),
            {"job": job.job_id},
        ).all()
    assert all(
        json.loads(value)["output"]["evidence"] == "retained result"
        for value in results
    )


def test_reviewable_migration_preserves_rows_indexes_and_relation_files(
    postgres_engine, monkeypatch
):
    path = (
        Path(ultima_scraper_db_archive.__file__).parent
        / "migrations/alembic/versions/f17b9e204ca6_add_ordinary_job_inputs.py"
    )
    spec = importlib.util.spec_from_file_location("ordinary_input_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "e25ac8106df4"
    name = "input_migration_" + uuid4().hex
    with postgres_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(text(f"CREATE DATABASE {name}"))
    engine = create_engine(postgres_engine.url.set(database=name))
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA management"))
            connection.execute(
                text("CREATE TABLE management.jobs (job_id text PRIMARY KEY)")
            )
            connection.execute(
                text(
                    "CREATE TABLE management.job_tasks (task_id text PRIMARY KEY, job_id text)"
                )
            )
            connection.execute(
                text("CREATE INDEX retained_job_idx ON management.job_tasks(job_id)")
            )
            connection.execute(text("INSERT INTO management.jobs VALUES ('kept')"))
            connection.execute(
                text("INSERT INTO management.job_tasks VALUES ('task-kept', 'kept')")
            )
            files = tuple(
                connection.execute(
                    text(
                        "SELECT pg_relation_filenode('management.jobs'), pg_relation_filenode('management.job_tasks')"
                    )
                ).one()
            )
            monkeypatch.setattr(
                module, "op", Operations(MigrationContext.configure(connection))
            )
            module.upgrade()
            assert (
                tuple(
                    connection.execute(
                        text(
                            "SELECT pg_relation_filenode('management.jobs'), pg_relation_filenode('management.job_tasks')"
                        )
                    ).one()
                )
                == files
            )
            assert (
                connection.scalar(
                    text("SELECT definition_json FROM management.job_tasks")
                )
                is None
            )
            assert (
                connection.scalar(text("SELECT job_config_json FROM management.jobs"))
                is None
            )
            assert {
                row["name"]
                for row in inspect(connection).get_indexes(
                    "job_tasks", schema="management"
                )
            } == {"retained_job_idx"}
            module.downgrade()
            assert (
                connection.scalar(text("SELECT task_id FROM management.job_tasks"))
                == "task-kept"
            )
            assert {
                column["name"]
                for column in inspect(connection).get_columns(
                    "job_tasks", schema="management"
                )
            } == {"task_id", "job_id"}
    finally:
        engine.dispose()
