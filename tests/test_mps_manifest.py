"""Real PostgreSQL selection, checkpoint, and bounded-page regression tests.

Opt in with USR_TEST_WITH_POSTGRES=1. The fixture always starts its own empty
cluster and never accepts a deployment URL or mutates an existing database.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import test_database_write_queue as writer_fixtures
from ultima_scraper_backend.database.mps_manifest import MPSManifestStore, mps_task_id
from ultima_scraper_db_archive.execution_models import (
    ExecutionAttemptModel,
    ExecutionDefinitionModel,
    ExecutionFeedModel,
    ExecutionOutboxModel,
    ExecutionResourceModel,
    ExecutionRunModel,
    ExecutionWorkModel,
)
from ultima_scraper_db_archive.global_db import (
    CentralJobModel,
    CentralTaskModel,
    DatabaseWriteReceiptModel,
    MPSCandidateRangeModel,
    MPSPlanModel,
    MPSTaskDefinitionModel,
    MPSRetryTaskModel,
)
import legacy_redis_runtime as legacy

redis_manager = writer_fixtures.redis_manager


@pytest.fixture(scope="module")
def postgres_engine():
    if os.environ.get("USR_TEST_WITH_POSTGRES") != "1":
        pytest.skip("Set USR_TEST_WITH_POSTGRES=1 for an isolated PostgreSQL cluster")
    with tempfile.TemporaryDirectory(prefix="usr-mps-pg-") as directory:
        data = Path(directory) / "data"
        subprocess.run(
            [
                "initdb",
                "-D",
                str(data),
                "-U",
                "usr_test",
                "--auth-local=trust",
                "--auth-host=reject",
                "--no-locale",
                "-E",
                "UTF8",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        with (Path(directory) / "postgres.log").open("w+") as log:
            process = subprocess.Popen(
                [
                    "postgres",
                    "-D",
                    str(data),
                    "-k",
                    directory,
                    "-h",
                    "",
                    "-c",
                    "shared_buffers="
                    + os.environ.get("USR_TEST_POSTGRES_SHARED_BUFFERS", "16MB"),
                ],
                stdout=log,
                stderr=log,
            )
            engine = create_engine(
                f"postgresql+psycopg://usr_test@/postgres?host={directory}"
            )
            try:
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    try:
                        with engine.connect() as connection:
                            connection.execute(text("SELECT 1"))
                        break
                    except Exception:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.05)
                with engine.begin() as connection:
                    connection.execute(text("CREATE SCHEMA management"))
                    connection.execute(text("CREATE SCHEMA onlyfans"))
                    connection.execute(
                        text(
                            "CREATE TABLE onlyfans.users (id bigint PRIMARY KEY, last_checked_at timestamptz)"
                        )
                    )
                    connection.execute(
                        text(
                            "CREATE TABLE onlyfans.invalid_users (site text, user_id bigint, updated_at timestamptz, last_checked_at timestamptz, PRIMARY KEY (site, user_id))"
                        )
                    )
                    for model in (
                        MPSPlanModel,
                        MPSCandidateRangeModel,
                        MPSTaskDefinitionModel,
                        MPSRetryTaskModel,
                        CentralJobModel,
                        CentralTaskModel,
                        DatabaseWriteReceiptModel,
                        ExecutionDefinitionModel,
                        ExecutionRunModel,
                        ExecutionWorkModel,
                        ExecutionAttemptModel,
                        ExecutionResourceModel,
                        ExecutionOutboxModel,
                        ExecutionFeedModel,
                    ):
                        model.__table__.create(connection)
                from ultima_scraper_db_archive import global_db

                prev_postgres_engine = global_db._postgres_engine
                global_db._postgres_engine = engine
                try:
                    yield engine
                finally:
                    global_db._postgres_engine = prev_postgres_engine
            finally:
                engine.dispose()
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)


@pytest.fixture
def store(postgres_engine):
    @contextmanager
    def session_factory():
        with Session(postgres_engine) as session:
            session.execute(
                text("SET LOCAL search_path = onlyfans, management, public")
            )
            yield session

    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE onlyfans.users, onlyfans.invalid_users"))
        connection.execute(
            text(
                "TRUNCATE management.mps_retry_tasks, management.mps_task_definitions, management.mps_candidate_ranges, management.mps_plans, management.job_tasks, management.jobs, management.execution_runs, management.execution_definitions, management.execution_work, management.execution_attempts, management.execution_resources, management.execution_outbox CASCADE"
            )
        )
    return MPSManifestStore(session_factory)


def prepare(store, **selection):
    return store.create(
        job_id=uuid4().hex,
        site="onlyfans",
        job_config={"name": "Fixture"},
        selection={"start_id": 1, "end_id": 10, **selection},
        proxy_pool=[],
        site_session_factory=store.session_factory,
    )


def test_reviewable_writer_and_mps_migrations_upgrade_and_downgrade(
    postgres_engine, monkeypatch
):
    import importlib.util
    import ultima_scraper_db_archive
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = (
        Path(ultima_scraper_db_archive.__file__).parent
        / "migrations/alembic/versions/a0f7d3c6e921_add_durable_mps_manifests.py"
    )
    spec = importlib.util.spec_from_file_location("mps_migration_fixture", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    receipt_path = path.parent / "bd61e4a92f07_add_database_write_receipts.py"
    spec = importlib.util.spec_from_file_location(
        "receipt_migration_fixture", receipt_path
    )
    receipt_migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(receipt_migration)
    assert receipt_migration.down_revision == migration.revision
    definition_path = path.parent / "d613ac49e82b_add_mps_task_definitions.py"
    spec = importlib.util.spec_from_file_location("definition_migration_fixture", definition_path)
    definition_migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(definition_migration)
    database = "migration_" + uuid4().hex
    with postgres_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(text(f"CREATE DATABASE {database}"))
    engine = create_engine(postgres_engine.url.set(database=database))
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA management"))
            monkeypatch.setattr(
                migration, "op", Operations(MigrationContext.configure(connection))
            )
            migration.upgrade()
            monkeypatch.setattr(
                receipt_migration,
                "op",
                Operations(MigrationContext.configure(connection)),
            )
            receipt_migration.upgrade()
            monkeypatch.setattr(
                definition_migration, "op", Operations(MigrationContext.configure(connection))
            )
            definition_migration.upgrade()
            for model in (
                MPSPlanModel,
                MPSCandidateRangeModel,
                DatabaseWriteReceiptModel,
                MPSTaskDefinitionModel,
            ):
                columns = inspect(connection).get_columns(
                    model.__tablename__, schema="management"
                )
                assert {column["name"] for column in columns} == set(
                    model.__table__.columns.keys()
                )
            connection.execute(
                text(
                    "INSERT INTO management.mps_plans (job_id, site, job_config_json, selection_json, proxy_pool_json, total, summary_json) VALUES ('fixture', 'onlyfans', '{}', '{}', '[]', 1000000, '{}')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO management.mps_candidate_ranges VALUES ('fixture', 0, 1, 1000000)"
                )
            )
            connection.execute(
                text("DELETE FROM management.mps_plans WHERE job_id = 'fixture'")
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM management.mps_candidate_ranges")
                ).scalar_one()
                == 0
            )
            definition_migration.downgrade()
            receipt_migration.downgrade()
            migration.downgrade()
            assert inspect(connection).get_table_names(schema="management") == []
    finally:
        engine.dispose()


def test_manifest_freezes_selection_filters_offset_and_unlimited_count(store):
    with store.session_factory() as session:
        session.execute(
            text(
                "INSERT INTO users VALUES (2, NULL), (5, now()), (8, now() - interval '2 days')"
            )
        )
        session.execute(
            text(
                "INSERT INTO invalid_users VALUES ('onlyfans', 3, now() - interval '2 days', now()), ('onlyfans', 7, now(), NULL), ('onlyfans', 8, NULL, NULL), ('fansly', 9, NULL, NULL)"
            )
        )
        session.commit()
    plan = prepare(
        store,
        include_invalid=True,
        invalid_last_checked_older_than_hours=24,
        include_existing_users=True,
        existing_last_checked_older_than_hours=24,
        candidate_offset=1,
    )
    assert plan["summary"] == {
        "missing_count": 5,
        "invalid_eligible_count": 1,
        "existing_eligible_count": 2,
        "candidate_count": 8,
    }
    assert plan["total"] == 7
    assert store.candidate_page(plan["job_id"], offset=0, limit=100) == [
        2,
        3,
        4,
        6,
        8,
        9,
        10,
    ]
    with store.session_factory() as session:
        session.execute(text("INSERT INTO users VALUES (4, now())"))
        session.execute(text("DELETE FROM invalid_users"))
        session.commit()
    assert store.candidate_page(plan["job_id"], offset=1, limit=3) == [3, 4, 6]
    assert store.candidate_page(plan["job_id"], offset=7, limit=3) == []
    retry = store.create(
        job_id=plan["job_id"],
        site="onlyfans",
        job_config={},
        selection={"start_id": 1, "end_id": 1},
        proxy_pool=["changed"],
        site_session_factory=store.session_factory,
    )
    assert retry == plan


def test_million_candidates_are_one_durable_range_with_bounded_pages(store):
    plan = prepare(store, end_id=1_000_000)
    assert plan["total"] == 1_000_000
    assert store.candidate_page(plan["job_id"], offset=987_650, limit=7) == list(
        range(987_651, 987_658)
    )
    with store.session_factory() as session:
        assert (
            session.execute(
                text(
                    "SELECT count(*) FROM management.mps_candidate_ranges WHERE job_id = :id"
                ),
                {"id": plan["job_id"]},
            ).scalar_one()
            == 1
        )
    assert store.get(plan["job_id"])["cursor"] == 0


def test_sparse_selection_is_disk_backed_and_keyset_paged(store):
    with store.session_factory() as session:
        session.execute(
            text(
                "INSERT INTO users SELECT id, NULL FROM generate_series(1, 100000, 2) id"
            )
        )
        session.commit()
    plan = prepare(store, end_id=100_000, max_profiles=40_000, candidate_offset=5_000)
    assert plan["total"] == 40_000
    assert store.candidate_page(plan["job_id"], offset=30_000, limit=3) == [
        70_002,
        70_004,
        70_006,
    ]
    # Verify the actual two paging statements use the ordinal primary key at a
    # late offset. Row count and offset must not force a full range-table scan.
    from sqlalchemy import event

    statements = []
    with store.session_factory() as session:
        session.execute(text("ANALYZE management.mps_candidate_ranges"))
        connection = session.connection()

        def capture(_connection, _cursor, statement, parameters, _context, _many):
            statements.append((statement, parameters))

        event.listen(connection, "before_cursor_execute", capture)
        store.candidate_page(plan["job_id"], offset=30_000, limit=3, db_session=session)
        event.remove(connection, "before_cursor_execute", capture)
        assert len(statements) == 2
        for statement, parameters in statements:
            explained = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters
            ).scalar_one()[0]

            def nodes(node):
                yield node
                for child in node.get("Plans", []):
                    yield from nodes(child)

            scanned = [
                node
                for node in nodes(explained["Plan"])
                if node.get("Relation Name") == "mps_candidate_ranges"
            ]
            assert scanned and all("Index" in node["Node Type"] for node in scanned)
            assert sum(node["Actual Rows"] for node in scanned) <= 3


def test_invalid_only_and_empty_selection(store):
    with store.session_factory() as session:
        session.execute(
            text("INSERT INTO invalid_users VALUES ('onlyfans', 3, NULL, NULL)")
        )
        session.commit()
    plan = prepare(store, ignore_missing_ids=True, include_invalid=True)
    assert plan["total"] == 1
    assert store.candidate_page(plan["job_id"], offset=0, limit=1) == [3]
    with pytest.raises(ValueError, match="No profiles selected"):
        prepare(store, ignore_missing_ids=True)


def test_non_missing_invalid_and_existing_combinations_and_cutoffs(store):
    with store.session_factory() as session:
        session.execute(
            text(
                "INSERT INTO users VALUES "
                "(2, now()), "
                "(3, now() - interval '2 days'), "
                "(4, now() - interval '2 days'), "
                "(5, now() - interval '2 days')"
            )
        )
        session.execute(
            text(
                "INSERT INTO invalid_users VALUES "
                "('onlyfans', 6, now() - interval '2 days', NULL), "
                "('onlyfans', 7, now(), NULL), "
                "('onlyfans', 8, now() - interval '2 days', NULL), "
                "('onlyfans', 9, now() - interval '2 days', NULL)"
            )
        )
        session.commit()

    # 1. Existing only with cutoff (older than 24h)
    plan_existing = prepare(
        store,
        ignore_missing_ids=True,
        include_existing_users=True,
        existing_last_checked_older_than_hours=24,
    )
    assert plan_existing["total"] == 3
    assert plan_existing["summary"] == {
        "missing_count": 0,
        "invalid_eligible_count": 0,
        "existing_eligible_count": 3,
        "candidate_count": 3,
    }
    assert store.candidate_page(plan_existing["job_id"], offset=0, limit=10) == [3, 4, 5]
    with store.session_factory() as session:
        # 3, 4, 5 are contiguous so they coalesce into 1 range!
        ranges_count = session.execute(
            text("SELECT count(*) FROM management.mps_candidate_ranges WHERE job_id = :id"),
            {"id": plan_existing["job_id"]},
        ).scalar_one()
        assert ranges_count == 1

    # 2. Invalid only with cutoff (older than 24h)
    plan_invalid = prepare(
        store,
        ignore_missing_ids=True,
        include_invalid=True,
        invalid_last_checked_older_than_hours=24,
    )
    assert plan_invalid["total"] == 3
    assert plan_invalid["summary"] == {
        "missing_count": 0,
        "invalid_eligible_count": 3,
        "existing_eligible_count": 0,
        "candidate_count": 3,
    }
    assert store.candidate_page(plan_invalid["job_id"], offset=0, limit=10) == [6, 8, 9]
    with store.session_factory() as session:
        # 6 is one range, [8, 9] is second range -> 2 ranges!
        ranges_count = session.execute(
            text("SELECT count(*) FROM management.mps_candidate_ranges WHERE job_id = :id"),
            {"id": plan_invalid["job_id"]},
        ).scalar_one()
        assert ranges_count == 2

    # 3. Both existing and invalid combined with offset and limit
    plan_both = prepare(
        store,
        ignore_missing_ids=True,
        include_existing_users=True,
        existing_last_checked_older_than_hours=24,
        include_invalid=True,
        invalid_last_checked_older_than_hours=24,
        candidate_offset=1,
        max_profiles=4,
    )
    # Total candidates in range: [3, 4, 5, 6, 8, 9] = 6 candidates.
    # Offset 1 slices [4, 5, 6, 8] (4 candidates).
    assert plan_both["total"] == 4
    assert store.candidate_page(plan_both["job_id"], offset=0, limit=10) == [4, 5, 6, 8]
    assert store.candidate_page(plan_both["job_id"], offset=1, limit=2) == [5, 6]


def test_non_missing_finite_window_with_hint(store):
    with store.session_factory() as session:
        session.execute(
            text(
                "INSERT INTO invalid_users SELECT 'onlyfans', id, NULL, NULL FROM generate_series(1, 100) id"
            )
        )
        session.commit()

    plan = store.create(
        job_id=uuid4().hex,
        site="onlyfans",
        job_config={"name": "HintTest"},
        selection={"start_id": 1, "end_id": 100, "ignore_missing_ids": True, "include_invalid": True, "max_profiles": 10},
        proxy_pool=[],
        site_session_factory=store.session_factory,
        candidate_count_hint=100,
    )
    assert plan["total"] == 10
    assert plan["summary"]["candidate_count"] == 100
    assert plan["summary"]["candidate_count_exact"] is False
    assert plan["summary"]["invalid_eligible_count"] == 100
    assert store.candidate_page(plan["job_id"], offset=0, limit=10) == list(range(1, 11))
    with store.session_factory() as session:
        ranges_count = session.execute(
            text("SELECT count(*) FROM management.mps_candidate_ranges WHERE job_id = :id"),
            {"id": plan["job_id"]},
        ).scalar_one()
        assert ranges_count == 1



def test_archive_and_checkpoint_commit_together_and_replay_is_idempotent(store):
    plan = prepare(store)
    job_id = plan["job_id"]
    rows = [
        {
            "task_id": mps_task_id(job_id, i, i + 1),
            "job_id": job_id,
            "task_type": "scrape",
            "status": "completed" if i != 1 else "failed",
            "items_processed": 1,
        }
        for i in range(3)
    ]
    with pytest.raises(ValueError, match="incomplete"):
        store.archive_window(job_id, start=0, end=4, rows=rows)
    assert store.get(job_id)["cursor"] == 0
    saved = store.archive_window(job_id, start=0, end=3, rows=rows)
    assert (saved["cursor"], saved["completed"], saved["failed"]) == (3, 2, 1)
    assert store.archive_window(job_id, start=0, end=3, rows=rows) == saved
    with store.session_factory() as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id = :id"),
                {"id": job_id},
            ).scalar_one()
            == 3
        )


def test_active_manifest_registry_uses_bounded_pagination(store):
    plans = [prepare(store) for _ in range(3)]
    first = store.active_page(limit=2)
    assert len(first) == 2
    following = store.active_page(after_job_id=first[-1], limit=2)
    assert len(following) <= 2
    assert not set(first).intersection(following)
    store.terminate(plans[0]["job_id"], status="cancelled")
    assert store.get(plans[0]["job_id"])["status"] == "cancelled"


@pytest.fixture
async def window_runtime(store, monkeypatch, redis_manager):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ultima_scraper_backend.api.routes import mps, mps_history
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.database import mps_manifest
    from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
    from ultima_scraper_backend.database.write_queue import DatabaseWriteCommand
    from ultima_scraper_backend.job_system import JobManager
    from ultima_scraper_db_archive import global_db

    client = redis_manager.client

    class RedisManager:
        is_connected = True

        async def get(self, key):
            return await client.get(key)

        async def set(self, key, value, **kwargs):
            return await client.set(key, value, **kwargs)

        async def delete(self, key):
            return await client.delete(key)

    redis = RedisManager()
    redis.client = client
    redis.hget = client.hget
    redis.keys = client.keys
    redis.smembers = client.smembers
    redis.expire = client.expire
    redis.publish = client.publish
    monkeypatch.setattr(mps_durable, "MPSManifestStore", lambda: store)
    monkeypatch.setattr(mps_history, "MPSManifestStore", lambda: store)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "3")
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "100000")

    monkeypatch.setattr(mps_manifest, "MPSManifestStore", lambda: store)
    monkeypatch.setattr(global_db, "global_session", store.session_factory)
    from ultima_scraper_backend.api.routes import jobs as jobs_routes

    monkeypatch.setattr(jobs_routes, "publish_ws_event", AsyncMock())
    executor = PostgreSQLWriteExecutor.__new__(PostgreSQLWriteExecutor)
    executor.redis = redis
    executor._site_manager = lambda _site: SimpleNamespace(
        get_session=store.session_factory
    )

    class Writes:
        MAX_COMMAND_BYTES = 64 * 1024 * 1024

        def __init__(self, *args, **kwargs):
            self.max_command_bytes = self.MAX_COMMAND_BYTES
            self.max_queue_bytes = self.MAX_COMMAND_BYTES
            self.producer_id = kwargs.get("producer_id", "isolated-test")

        async def submit(self, operation, payload, **kwargs):
            command = DatabaseWriteCommand(
                command_id=kwargs.get("command_id") or uuid4().hex,
                operation=operation,
                site=kwargs.get("site"),
                payload=payload,
                producer_id=self.producer_id,
                created_at="2026-09-05T00:00:00+00:00",
            )
            # Exercise the production executor using the actual JSON wire
            # representation; transport admission/ACK has its own real Redis tests.
            command = DatabaseWriteCommand.from_json(command.to_bytes(max_bytes=min(self.max_command_bytes, self.max_queue_bytes)))
            return (await executor.execute_batch([command]))[command.command_id]

    from ultima_scraper_backend.api.routes import mps_durable as submissions

    monkeypatch.setattr(submissions, "DatabaseWriteClient", Writes)
    monkeypatch.setattr(mps_durable, "DatabaseWriteClient", Writes)
    monkeypatch.setattr(
        JobManager, "activate_materialized_job", AsyncMock(return_value=None)
    )
    try:
        yield SimpleNamespace(
            redis=redis,
            instance_id="test-backend",
            distributed_mode=True,
            writes=Writes(),
        )
    finally:
        await client.aclose()


def prepare_runtime_plan(store, total):
    from ultima_scraper_backend.job_system import Job

    job = Job.create(
        name="MPS fixture",
        created_by="tests",
        tasks=[],
        metadata={"site": "onlyfans", "source": "manual", "mps_manifest": True},
    )
    return store.create(
        job_id=job.job_id,
        site="onlyfans",
        job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": total},
        proxy_pool=[],
        site_session_factory=store.session_factory,
    )


async def complete_window(storage, job_id):
    from ultima_scraper_backend.job_system import TaskState, TaskResult

    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    for task in tasks:
        assert await legacy.mark_task_started(storage, job_id, task.task_id)
        task.state = TaskState.COMPLETED
        task.result = TaskResult(
            success=True, output={"items_processed": 1}, metrics={"items_processed": 1}
        )
        await legacy.persist_task_result(storage, job_id, task)
        await legacy.mark_task_completed(storage, job_id, task.task_id)
    return tasks


async def test_mps_execution_archives_each_window_and_keeps_total_counts(
    store, window_runtime
):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage

    plan = prepare_runtime_plan(store, 8)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await mps_durable.advance(window_runtime, job_id)
    assert (await storage.get_job_task_stats(job_id))["total"] == 8
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=job_id)) == 3
    previous_ids = set()
    for expected_cursor, expected_remaining in [(3, 3), (6, 2), (8, 0)]:
        tasks = await complete_window(storage, job_id)
        assert not previous_ids.intersection(task.task_id for task in tasks)
        previous_ids.update(task.task_id for task in tasks)
        if await mps_durable.advance(window_runtime, job_id):
            await mps_durable.advance(window_runtime, job_id)
        assert store.get(job_id)["cursor"] == expected_cursor
        assert (
            await client.zcard(storage.TASK_INDEX_KEY.format(job_id=job_id))
            == expected_remaining
        )
        stats = await storage.get_job_task_stats(job_id)
        assert stats["completed"] == expected_cursor
        assert stats["total"] == 8
        assert not any(
            [
                await client.exists(
                    storage.TASK_KEY.format(job_id=job_id, task_id=task_id)
                )
                for task_id in previous_ids
            ]
        )
    with store.session_factory() as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id = :id"),
                {"id": job_id},
            ).scalar_one()
            == 8
        )
    assert store.get(job_id)["status"] == "complete"


async def test_route_reserves_survive_materialization_and_obey_byte_budget(
    store, window_runtime, monkeypatch
):
    from ultima_scraper_backend.job_system import Job, JobStorage, durable, mps_tasks, mps_state

    pool = [f"http://us-{index}:8080/" + "x" * 180 for index in range(7)]
    pool += ["http://gb:8080", "http://de:8080"]
    geo = dict.fromkeys(pool[:7], "US") | {pool[7]: "GB", pool[8]: "DE"}
    monkeypatch.setattr(mps_tasks, "get_cached_proxy_geo_map", lambda: geo)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "3200")
    job = Job.create(name="Route reserve budget", created_by="tests", tasks=[],
        metadata={"site": "onlyfans", "source": "manual", "mps_manifest": True})
    plan = store.create(job_id=job.job_id, site="onlyfans", job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": 8, "max_route_hops": 3},
        proxy_pool=pool, site_session_factory=store.session_factory)
    storage = JobStorage(window_runtime.redis)
    await durable.advance(window_runtime, plan["job_id"])
    task_ids = await storage._client().zrange(storage.TASK_INDEX_KEY.format(job_id=job.job_id), 0, -1)
    assert len(task_ids) == 1
    task = await storage.fetch_task(job.job_id, task_ids[0].decode())
    assert task is not None
    assert len(task.payload.guest_fallback_proxy_urls) == 2
    assert len(task.payload.guest_proxy_alternatives[pool[0]]) == 3
    occupied = int(await storage._client().hget(mps_state.BUDGET_KEY, "bytes"))
    assert len(json.dumps(task.to_dict()).encode()) <= occupied <= 3200
    assert (await storage.get_job_task_stats(job.job_id))["total"] == 8


async def test_mps_restarts_after_sql_commit_before_redis_purge(
    store, window_runtime, monkeypatch
):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage

    plan = prepare_runtime_plan(store, 10)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job_id)
    original = await complete_window(storage, job_id)
    purge = mps_durable._purge_archived_window

    async def crash(*args, **kwargs):
        raise RuntimeError("crash after commit")

    monkeypatch.setattr(mps_durable, "_purge_archived_window", crash)
    with pytest.raises(RuntimeError, match="crash after commit"):
        await mps_durable.advance(window_runtime, job_id)
    assert store.get(job_id)["cursor"] == 3
    monkeypatch.setattr(mps_durable, "_purge_archived_window", purge)
    await mps_durable.advance(window_runtime, job_id)
    current = [task async for task in storage.fetch_tasks_stream(job_id)]
    assert len(current) == 3
    assert not {task.task_id for task in current}.intersection(
        task.task_id for task in original
    )
    assert (await storage.get_job_task_stats(job_id))["completed"] == 3


async def test_million_profile_job_only_materializes_configured_window(
    store, window_runtime
):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage

    plan = prepare_runtime_plan(store, 1_000_000)
    await mps_durable.advance(window_runtime, plan["job_id"])
    storage = JobStorage(window_runtime.redis)
    assert (
        await storage._client().zcard(
            storage.TASK_INDEX_KEY.format(job_id=plan["job_id"])
        )
        == 3
    )
    assert await storage._client().dbsize() < 25
    header = await storage._client().hgetall(
        mps_durable.mps_state.PLAN_KEY.format(job_id=plan["job_id"])
    )
    assert header[b"window_budget_key"] == mps_durable.mps_state.BUDGET_KEY.encode()
    assert b"target_user_ids" not in header and b"task_ids" not in header
    assert sum(len(key) + len(value) for key, value in header.items()) < 1024


async def test_multiple_jobs_share_the_global_window_and_wake_in_order(
    store, window_runtime
):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage, mps_state

    first = prepare_runtime_plan(store, 1_000_000)
    second = prepare_runtime_plan(store, 1_000_000)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await mps_durable.advance(window_runtime, first["job_id"])
    await mps_durable.advance(window_runtime, second["job_id"])
    assert await client.hget(mps_state.BUDGET_KEY, "tasks") == b"3"
    assert (
        await client.zcard(storage.TASK_INDEX_KEY.format(job_id=second["job_id"])) == 0
    )
    assert await client.lrange(mps_state.WAITING_KEY, 0, -1) == [
        second["job_id"].encode()
    ]
    await complete_window(storage, first["job_id"])
    await client.delete(mps_state.QUEUE_KEY, mps_state.SCHEDULED_KEY)
    assert await mps_durable.advance(
        window_runtime, first["job_id"], refill_after_archive=True
    ) is True
    assert await client.rpop(mps_state.QUEUE_KEY) == second["job_id"].encode()
    await mps_durable.advance(window_runtime, second["job_id"])
    assert (
        await client.zcard(storage.TASK_INDEX_KEY.format(job_id=second["job_id"])) == 3
    )
    assert await client.hget(mps_state.BUDGET_KEY, "tasks") == b"3"


async def test_terminal_state_keeps_cumulative_counts_after_runtime_release(
    store, window_runtime
):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage

    plan = prepare_runtime_plan(store, 10)
    storage = JobStorage(window_runtime.redis)
    job_id = plan["job_id"]
    await mps_durable.advance(window_runtime, job_id)
    await complete_window(storage, job_id)
    assert await mps_durable.advance(window_runtime, job_id) is True
    await mps_durable.advance(window_runtime, job_id)
    await complete_window(storage, job_id)
    await storage.mark_job_cancelled(job_id, reason="fixture")
    stats = await storage.get_job_task_stats(job_id)
    assert (stats["total"], stats["completed"]) == (10, 6)
    await mps_durable.advance(window_runtime, job_id)
    assert store.get(job_id)["cursor"] == 6
    stats = await storage.get_job_task_stats(job_id)
    assert (stats["total"], stats["completed"]) == (10, 6)


async def test_stale_purge_cannot_remove_a_new_window(store, window_runtime):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage, mps_state

    plan = prepare_runtime_plan(store, 10)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job_id)
    old = {"cursor": "0", "window_end": "3"}
    await complete_window(storage, job_id)
    assert await mps_durable.advance(window_runtime, job_id) is True
    await mps_durable.advance(window_runtime, job_id)
    tasks = [task.task_id async for task in storage.fetch_tasks_stream(job_id)]
    assert not await mps_durable._purge_archived_window(storage, store.get(job_id), old)
    assert [task.task_id async for task in storage.fetch_tasks_stream(job_id)] == tasks
    assert await storage._client().hget(mps_state.BUDGET_KEY, "tasks") == b"3"


async def test_lost_lock_cannot_publish_or_purge(store, window_runtime):
    from ultima_scraper_backend.api.routes import mps
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage, mps_state

    plan = prepare_runtime_plan(store, 10)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await client.set("test-lock", "new-owner")
    from ultima_scraper_backend.job_system import materializer

    with pytest.raises(materializer._MPSMaterializationLockLost):
        await mps_durable.advance(
            window_runtime, job_id, lock_key="test-lock", lock_owner="old-owner"
        )
    assert await client.hget(mps_state.BUDGET_KEY, "tasks") is None
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=job_id)) == 0


async def test_history_spans_archived_and_current_windows_with_bounded_sparse_filters(
    store, window_runtime, monkeypatch
):
    from ultima_scraper_backend.api.routes import jobs
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage

    plan = prepare_runtime_plan(store, 8)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job_id)
    for _ in range(2):
        await complete_window(storage, job_id)
        assert await mps_durable.advance(window_runtime, job_id) is True
        await mps_durable.advance(window_runtime, job_id)
    page = await jobs.get_job_tasks(job_id, offset=2, limit=5, backend=window_runtime)
    assert [detail.username for detail in page.tasks] == ["3", "4", "5", "6", "7"]
    assert [detail.status for detail in page.tasks] == ["completed"] * 4 + ["pending"]
    assert page.next_cursor == "7"
    monkeypatch.setenv("ULTIMA_MPS_TASK_PAGE_SCAN_MAX_TASKS", "2")
    empty = await jobs.get_job_tasks(
        job_id, offset=0, limit=3, state="completed", backend=window_runtime
    )
    assert empty.tasks == []
    assert empty.next_cursor == "2"
    following = await jobs.get_job_tasks(
        job_id,
        cursor=empty.next_cursor,
        limit=3,
        state="completed",
        backend=window_runtime,
    )
    assert [detail.username for detail in following.tasks] == ["6", "5"]
    response = await jobs.stream_job_tasks(
        job_id, batch_size=2, state="completed", backend=window_runtime
    )
    chunks = [chunk async for chunk in response.body_iterator]
    assert len(chunks) == 7
    assert chunks[-1] == "data: [DONE]\n\n"


async def test_durable_window_recovers_after_redis_runtime_loss(store, window_runtime):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage

    plan = prepare_runtime_plan(store, 10)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job_id)
    await complete_window(storage, job_id)
    assert await mps_durable.advance(window_runtime, job_id) is True
    await storage._client().flushall()
    await mps_durable.recover(window_runtime)
    await mps_durable.advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    assert [int(task.user_id) for task in tasks] == [4, 5, 6]
    assert (await storage.get_job_task_stats(job_id))["completed"] == 3


async def test_api_submission_commits_manifest_before_runtime_admission(
    store, window_runtime, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ultima_scraper_backend.api.routes import mps
    from ultima_scraper_backend.job_system import JobStorage

    monkeypatch.setattr(
        mps,
        "_resolve_analysis_scope",
        AsyncMock(
            return_value=SimpleNamespace(
                start_id=1,
                end_id=1_000_000,
                site_display="OnlyFans",
                site_key="onlyfans",
            )
        ),
    )
    monkeypatch.setattr(mps, "_resolve_proxy_pool", lambda **kwargs: [])
    response = await mps.create_mps_job(
        mps.MPSCreateJobRequest(start_id=1, end_id=1_000_000),
        backend=window_runtime,
        backend_manager=SimpleNamespace(),
        config=SimpleNamespace(
            settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
        ),
    )
    assert response.selected_profiles == 1_000_000
    plan = store.get(response.job.job_id)
    assert plan["total"] == 1_000_000
    assert "target_user_ids" not in plan["selection"]
    storage = JobStorage(window_runtime.redis)
    assert (
        await storage._client().zcard(
            storage.TASK_INDEX_KEY.format(job_id=response.job.job_id)
        )
        == 0
    )
    with store.session_factory() as session:
        row = session.get(CentralJobModel, response.job.job_id)
        assert row is not None


async def test_partial_cancellation_archives_without_replacing_prior_evidence_and_releases_capacity(
    store, window_runtime
):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
    from ultima_scraper_backend.job_system import JobStorage, mps_state

    plan = prepare_runtime_plan(store, 10)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job_id)
    await complete_window(storage, job_id)
    assert await mps_durable.advance(window_runtime, job_id) is True
    await mps_durable.advance(window_runtime, job_id)
    await storage.mark_job_cancelled(job_id, reason="fixture")
    await mps_durable.advance(window_runtime, job_id)
    generation = await storage._client().hget(
        storage.JOB_STATE_KEY.format(job_id=job_id), "completed_at"
    )
    result = await window_runtime.writes.submit(
        DatabaseWriteOperation.ARCHIVE_JOB_TASKS,
        {"job_id": job_id, "batch_size": 2, "generation": generation.decode()},
    )
    assert result["archived_tasks"] == 3
    with store.session_factory() as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id = :id"),
                {"id": job_id},
            ).scalar_one()
            == 6
        )
        assert (
            session.get(CentralTaskModel, (mps_task_id(job_id, 0, 1), job_id)).status
            == "completed"
        )
    assert await storage.purge_job_task_blobs(job_id, batch_pause=0) == 3
    assert await storage._client().hget(mps_state.BUDGET_KEY, "tasks") == b"0"
    assert await storage._client().hget(mps_state.BUDGET_KEY, "bytes") == b"0"
    await mps_state.release_budget(storage._client(), job_id)
    assert await storage._client().hget(mps_state.BUDGET_KEY, "tasks") == b"0"


async def test_aborted_publication_releases_only_unpublished_owned_reservations(
    store, window_runtime, monkeypatch
):
    from redis.exceptions import WatchError
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage

    plan = prepare_runtime_plan(store, 10)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    reserve = JobStorage.reserve_dedup_many
    seen = []

    async def invalidate(self, tasks, *args, **kwargs):
        result = await reserve(self, tasks, *args, **kwargs)
        seen.extend(tasks)
        await self._client().hset(
            self.JOB_STATE_KEY.format(job_id=job_id), "changed", 1
        )
        return result

    monkeypatch.setattr(JobStorage, "reserve_dedup_many", invalidate)
    with pytest.raises(WatchError):
        await mps_durable.advance(window_runtime, job_id)
    assert seen
    for task in seen:
        assert (
            await storage._client().get(storage.DEDUPE_KEY.format(dedup=task.dedup_key))
            is None
        )
        assert await storage.fetch_task(job_id, task.task_id) is None


async def test_window_and_deferred_indexes_publish_in_one_transaction(
    store, window_runtime, monkeypatch
):
    from unittest.mock import AsyncMock
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import (
        JobManager,
        JobStorage,
        TaskState,
        mps_state,
    )

    plan = prepare_runtime_plan(store, 10)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    monkeypatch.setattr(JobStorage, "reserve_dedup_many", AsyncMock(return_value=[]))
    activate = JobManager.activate_materialized_job
    activate.side_effect = RuntimeError("crash after publication")
    with pytest.raises(RuntimeError, match="crash after publication"):
        await mps_durable.advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    assert len(tasks) == 3
    for task in tasks:
        assert task.state == TaskState.DEFERRED
        assert await storage._client().sismember(
            storage.DEFERRED_TASKS_KEY.format(dedup_key=task.dedup_key),
            f"{job_id}:{task.task_id}",
        )
    assert (await storage.get_job_task_stats(job_id))["deferred"] == 3
    activate.side_effect = None
    await mps_durable.advance(window_runtime, job_id)
    assert await storage._client().hget(mps_state.BUDGET_KEY, "tasks") == b"3"


async def test_mps_restore_preserves_terminal_window_members_without_expiry(
    store, window_runtime
):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage, TaskState

    plan = prepare_runtime_plan(store, 8)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job_id)
    await complete_window(storage, job_id)
    assert await mps_durable.advance(window_runtime, job_id) is True
    await mps_durable.advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    for task, status in zip(
        tasks, [TaskState.COMPLETED, TaskState.FAILED, TaskState.RUNNING], strict=True
    ):
        await legacy.mark_task_started(storage, job_id, task.task_id)
        task.state = status
        await legacy.persist_task_result(storage, job_id, task)
        if status == TaskState.COMPLETED:
            await legacy.mark_task_completed(storage, job_id, task.task_id)
        elif status == TaskState.FAILED:
            await legacy.mark_task_failed(storage, job_id, task.task_id)
    job = await storage.fetch_job(job_id, include_tasks=False)
    assert await storage.restore_task_state(job, return_ready_task_ids=False) == []
    stats = await storage.get_job_task_stats(job_id)
    assert (stats["total"], stats["completed"], stats["failed"], stats["ready"]) == (
        8,
        4,
        1,
        1,
    )
    for key in (storage.TASKS_COMPLETED_KEY, storage.TASKS_READY_KEY):
        assert await storage._client().ttl(key.format(job_id=job_id)) == -1


async def test_mps_shared_deferred_index_survives_normal_job_ttl_refresh_and_cleans_up(
    store, window_runtime, monkeypatch
):
    from unittest.mock import AsyncMock
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage, mps_state

    plan = prepare_runtime_plan(store, 10)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    monkeypatch.setattr(JobStorage, "reserve_dedup_many", AsyncMock(return_value=[]))
    await mps_durable.advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    for task in tasks:
        key = storage.DEFERRED_TASKS_KEY.format(dedup_key=task.deferred_dedup_key)
        assert await storage._client().ttl(key) == -1
        await storage._client().sadd(key, "ordinary-job:ordinary-task")
        await mps_state.retain_deferred(storage, "ordinary-job", key)
        assert await storage._client().ttl(key) == -1
        await mps_state.remove_deferred(storage, key, f"{job_id}:{task.task_id}")
        assert await storage._client().exists(key) == 1
        await mps_state.remove_deferred(storage, key, "ordinary-job:ordinary-task")
        assert await storage._client().exists(key) == 0


async def test_materializer_refills_after_archive_without_requeue(store, window_runtime):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage, mps_state

    plan = prepare_runtime_plan(store, 10)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job_id)
    await complete_window(storage, job_id)
    assert await mps_durable.advance(
        window_runtime, job_id, refill_after_archive=True
    ) is False
    assert store.get(job_id)["cursor"] == 3
    assert await storage._client().scard(storage.TASKS_READY_KEY.format(job_id=job_id)) == 3
    assert await storage._client().hget(mps_state.BUDGET_KEY, "tasks") == b"3"
    assert await storage._client().hget(mps_state.PLAN_KEY.format(job_id=job_id), "window_end") == b"6"


async def test_same_pass_refill_preserves_running_task(store, window_runtime):
    from ultima_scraper_backend.job_system import durable as mps_durable
    from ultima_scraper_backend.job_system import JobStorage, TaskState, TaskResult

    job_id = prepare_runtime_plan(store, 10)["job_id"]
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job_id)
    tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
    for task in tasks:
        assert await legacy.mark_task_started(storage, job_id, task.task_id)
    for task in tasks[:2]:
        task.state = TaskState.COMPLETED
        task.result = TaskResult(success=True, output={"items_processed": 1})
        await legacy.persist_task_result(storage, job_id, task)
        await legacy.mark_task_completed(storage, job_id, task.task_id)
    assert await mps_durable.advance(
        window_runtime, job_id, refill_after_archive=True
    ) is False
    client = storage._client()
    assert await client.sismember(storage.TASKS_INFLIGHT_KEY.format(job_id=job_id), tasks[2].task_id)
    assert await client.scard(storage.TASKS_READY_KEY.format(job_id=job_id)) == 2
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=job_id)) == 3
    assert store.get(job_id)["cursor"] == 2
    from ultima_scraper_backend.api.routes.job_schemas import MPSRefillTraceEvent
    from ultima_scraper_backend.job_system import mps_state
    events = await mps_state.get_refill_trace(client, job_id)
    stages = [event["stage"] for event in events]
    for stage in ("runtime_controls", "cleanup_started", "cleanup_finished",
                  "manifest_read_started", "manifest_read_finished", "publication_started", "tasks_published"):
        assert stage in stages
    control = next(event for event in reversed(events) if event.get("controls"))
    parsed = MPSRefillTraceEvent.model_validate(control)
    assert parsed.controls["window_tasks"] == 3
    assert parsed.controls["same_pass_refill"] is True
    assert parsed.controls["materializer_version"] == "coalesced-refill-v4-chunked-archive"
    assert parsed.controls["archive_batch_tasks"] == 256


@pytest.mark.parametrize("offset,limit,expected", [(0, 2, [1, 4]), (1, 2, [4, 6]), (4, 10, [10])])
def test_missing_only_finite_page_preserves_exact_counts_and_overlap(store, offset, limit, expected):
    with store.session_factory() as session:
        session.execute(text("INSERT INTO users VALUES (2, NULL), (5, NULL), (8, NULL)"))
        session.execute(text("INSERT INTO invalid_users VALUES ('onlyfans', 3, NULL, NULL), ('onlyfans', 7, NULL, NULL), ('onlyfans', 8, NULL, NULL), ('fansly', 9, NULL, NULL)"))
        session.commit()
    plan = prepare(store, candidate_offset=offset, max_profiles=limit)
    assert plan["summary"]["missing_count"] == 5
    assert plan["summary"]["candidate_count"] == 5
    assert plan["total"] == len(expected)
    assert store.candidate_page(plan["job_id"], offset=0, limit=100) == expected


def test_missing_only_verified_prefix_seeks_without_transferring_known_ids(store, monkeypatch):
    with store.session_factory() as session:
        session.execute(text("INSERT INTO users SELECT id, NULL FROM generate_series(1, 100000) id"))
        session.execute(text("INSERT INTO invalid_users SELECT 'onlyfans', id, NULL, NULL FROM generate_series(100001, 200000) id"))
        session.commit()
    prepare(store, end_id=300000, max_profiles=11670)
    from ultima_scraper_backend.database import mps_manifest
    monkeypatch.setattr(mps_manifest, "_MPS_COVERAGE_ID_SPAN", 100000)
    original_execute = Session.execute
    starts = []
    def execute(session, statement, *args, **kwargs):
        if str(statement).lstrip().startswith("SELECT id AS user_id"):
            starts.append(args[0]["lower"])
        return original_execute(session, statement, *args, **kwargs)
    monkeypatch.setattr(Session, "execute", execute)
    plan = prepare(store, end_id=300000, max_profiles=11670)
    assert plan["total"] == 11670
    assert plan["summary"]["candidate_count"] == 100000
    assert starts == []  # Dense blocks are counted, and the empty tail needs no ID transfer.
    assert store.candidate_page(plan["job_id"], offset=0, limit=3) == [200001, 200002, 200003]


def test_missing_only_changed_prefix_does_not_reuse_stale_membership(store):
    with store.session_factory() as session:
        session.execute(text("INSERT INTO users SELECT id, NULL FROM generate_series(1, 20) id"))
        session.commit()
    prepare(store, end_id=30, max_profiles=3)
    with store.session_factory() as session:
        session.execute(text("DELETE FROM users WHERE id = 5"))
        session.commit()
    plan = prepare(store, end_id=30, max_profiles=3)
    assert plan["summary"]["candidate_count"] == 11
    assert store.candidate_page(plan["job_id"], offset=0, limit=3) == [5, 21, 22]


def test_missing_only_overlapping_maximum_bigint_does_not_overflow(store):
    maximum = 2**63 - 1
    with store.session_factory() as session:
        session.execute(text("INSERT INTO users VALUES (:maximum, NULL)"), {"maximum": maximum})
        session.execute(text("INSERT INTO invalid_users VALUES ('onlyfans', :maximum, NULL, NULL)"), {"maximum": maximum})
        session.commit()
    plan = prepare(store, start_id=maximum-2, end_id=maximum, max_profiles=2)
    assert plan["summary"]["missing_count"] == 2
    assert store.candidate_page(plan["job_id"], offset=0, limit=3) == [maximum-2, maximum-1]
