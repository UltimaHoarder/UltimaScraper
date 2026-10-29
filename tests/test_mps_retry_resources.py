from __future__ import annotations

import importlib.util
import tracemalloc
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text

import test_mps_manifest as fixtures
from ultima_scraper_backend.database.mps_manifest import mps_task_id
from ultima_scraper_backend.job_system import Job, JobState, JobStorage, TaskState
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.api.routes import mps_durable as mps_submission

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


def retry_config(source, **metadata):
    return Job.create(
        name="Retry: fixture",
        created_by="tests",
        tasks=[],
        metadata={
            "mps_manifest": True,
            "site": "onlyfans",
            "retry_of": source["job_id"],
            **metadata,
        },
    ).to_dict()


def clone(store, source, *, live=(), auth_id=None, config=None, commit=True):
    config = config or retry_config(source)
    with store.session_factory() as session:
        result = store.clone_for_retry(
            source_job_id=source["job_id"],
            job_id=config["job_id"],
            job_config=config,
            site=source["site"],
            live_failed_user_ids=live,
            auth_id=auth_id,
            db_session=session,
        )
        if commit:
            session.commit()
    return result


def test_retry_copies_million_candidate_selection_without_expanding_it(store):
    source = fixtures.prepare_runtime_plan(store, 1_000_000)
    retried = clone(store, source)
    assert retried["total"] == 1_000_000 and retried["cursor"] == 0
    assert store.candidate_page(retried["job_id"], offset=999_995, limit=9) == list(
        range(999_996, 1_000_001)
    )
    with store.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.mps_candidate_ranges WHERE job_id=:job"
                ),
                {"job": retried["job_id"]},
            )
            == 1
        )
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 0
    assert store.get(source["job_id"])["status"] == "cancelled"


def test_retry_combines_archived_and_live_failures_using_identity_not_username(store):
    source = fixtures.prepare_runtime_plan(store, 20)
    rows = [
        {
            "task_id": mps_task_id(source["job_id"], i, i + 1),
            "job_id": source["job_id"],
            "task_type": "scrape",
            "username": "a renamed profile",
            "status": "failed" if i in (1, 3) else "completed",
        }
        for i in range(5)
    ]
    store.archive_window(source["job_id"], start=0, end=5, rows=rows)
    retried = clone(store, source, live=[4, 7, 6, 7], auth_id=101)
    assert retried["total"] == 4
    assert retried["selection"]["retry_auth_id"] == 101
    assert store.candidate_page(retried["job_id"], offset=0, limit=20) == [2, 4, 6, 7]
    assert store.get(source["job_id"])["cursor"] == 5
    with store.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"),
                {"job": source["job_id"]},
            )
            == 5
        )


def test_sparse_failed_retry_keeps_large_selection_in_database(store):
    source = fixtures.prepare_runtime_plan(store, 1_000_000)
    with store.session_factory() as session:
        session.execute(
            text("""
            INSERT INTO management.job_tasks(task_id,job_id,task_type,status,user_id,username)
            SELECT 'retry-fixture-' || i, :source, 'scrape', 'failed', i, 'renamed'
            FROM generate_series(1,40000) i
        """),
            {"source": source["job_id"]},
        )
        session.execute(
            text(
                "UPDATE management.mps_plans SET cursor=40000,failed=40000 WHERE job_id=:source"
            ),
            {"source": source["job_id"]},
        )
        session.commit()
    tracemalloc.start()
    try:
        retried = clone(store, source)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 3 * 1024 * 1024
    assert retried["total"] == 40_000
    assert store.candidate_page(retried["job_id"], offset=39_997, limit=7) == [
        39_998,
        39_999,
        40_000,
    ]


def test_retry_commit_and_retirement_are_atomic_and_replay_keeps_same_selection(store):
    source = fixtures.prepare_runtime_plan(store, 100)
    config = retry_config(source)
    rolled_back = clone(store, source, config=config, commit=False)
    assert store.get(rolled_back["job_id"]) is None
    assert store.get(source["job_id"])["status"] == "ready"
    first = clone(store, source, live=[3, 9], config=config)
    second = clone(store, source, live=[7], auth_id=42, config=config)
    assert second == first
    assert store.candidate_page(first["job_id"], offset=0, limit=10) == [3, 9]


def test_mps_archive_rejects_profile_identity_mismatch(store):
    source = fixtures.prepare_runtime_plan(store, 10)
    with pytest.raises(ValueError, match="identity"):
        store.archive_window(
            source["job_id"],
            start=0,
            end=1,
            rows=[
                {
                    "task_id": mps_task_id(source["job_id"], 0, 1),
                    "job_id": source["job_id"],
                    "task_type": "scrape",
                    "status": "failed",
                    "user_id": 2,
                }
            ],
        )
    assert store.get(source["job_id"])["cursor"] == 0


def test_retry_refuses_incomplete_canonical_failure_evidence(store):
    source = fixtures.prepare_runtime_plan(store, 10)
    with store.session_factory() as session:
        session.execute(
            text("UPDATE management.mps_plans SET failed=1,cursor=1 WHERE job_id=:job"),
            {"job": source["job_id"]},
        )
        session.commit()
    with pytest.raises(ValueError, match="canonical profile identity"):
        clone(store, source)
    assert store.get(source["job_id"])["status"] == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["cancelled", "failed"])
async def test_terminal_sql_manifest_cannot_be_restarted_by_stale_redis_notification(
    store, window_runtime, status
):
    source = fixtures.prepare_runtime_plan(store, 1_000_000)
    store.terminate(source["job_id"], status=status)
    assert not await mps_durable.advance(window_runtime, source["job_id"])
    storage = JobStorage(window_runtime.redis)
    assert await storage.fetch_job(source["job_id"], include_tasks=False) is None
    assert not await storage._client().exists(
        storage.TASK_INDEX_KEY.format(job_id=source["job_id"])
    )
    assert store.get(source["job_id"])["status"] == status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,state", [("cancelled", JobState.CANCELLED), ("failed", JobState.FAILED)]
)
async def test_terminal_header_restoration_preserves_sql_authority(
    store, window_runtime, status, state
):
    source = fixtures.prepare_runtime_plan(store, 10)
    store.terminate(source["job_id"], status=status)
    storage = JobStorage(window_runtime.redis)
    job = await mps_durable.ensure_job(storage, store.get(source["job_id"]))
    assert job.state == state
    assert job.completed_at is not None


@pytest.mark.asyncio
async def test_retry_materialization_honors_auth_and_retires_source_before_activation(
    store, window_runtime, monkeypatch
):
    source = fixtures.prepare_runtime_plan(store, 1_000_000)
    retried = clone(store, source, live=[7, 17, 27, 37], auth_id=101)
    events = []

    async def retire(storage, plan):
        assert plan["job_config"]["metadata"]["retry_of"] == source["job_id"]
        assert not await storage._client().exists(
            storage.TASK_INDEX_KEY.format(job_id=retried["job_id"])
        )
        events.append("retired")

    monkeypatch.setattr(mps_durable, "_retire_retry_source", retire)
    assert not await mps_durable.advance(window_runtime, retried["job_id"])
    storage = JobStorage(window_runtime.redis)
    tasks = [task async for task in storage.fetch_tasks_stream(retried["job_id"])]
    assert events == ["retired"]
    assert [task.user_id for task in tasks] == [7, 17, 27]
    assert all(
        task.auth_id == 101 and not task.payload.use_guest_auth for task in tasks
    )
    assert store.get(retried["job_id"])["total"] == 4


@pytest.mark.asyncio
async def test_retry_route_uses_bounded_live_window_and_durable_failed_history(
    store, window_runtime, monkeypatch
):
    from ultima_scraper_backend.api.routes import jobs

    source = fixtures.prepare_runtime_plan(store, 1_000_000)
    store.archive_window(
        source["job_id"],
        start=0,
        end=1,
        rows=[
            {
                "task_id": mps_task_id(source["job_id"], 0, 1),
                "job_id": source["job_id"],
                "task_type": "scrape",
                "status": "failed",
                "username": "renamed",
            }
        ],
    )
    # An old archived job has no Redis payloads. No task list is reconstructed.
    retire = AsyncMock()
    monkeypatch.setattr(mps_durable, "_retire_retry_source", retire)
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    monkeypatch.setattr(
        JobStorage,
        "fetch_job_with_tasks",
        AsyncMock(side_effect=AssertionError("whole job load")),
    )
    result = await jobs.retry_job(source["job_id"], request=jobs.RetryJobRequest(), backend=window_runtime)
    assert result.task_count == 1
    retried = store.get(result.job_id)
    assert store.candidate_page(retried["job_id"], offset=0, limit=10) == [1]
    assert retire.await_count == 1
    storage = JobStorage(window_runtime.redis)
    assert (
        await storage._client().zcard(
            storage.TASK_INDEX_KEY.format(job_id=result.job_id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_retry_collects_only_failed_tasks_in_the_current_window(
    store, window_runtime, monkeypatch
):
    from ultima_scraper_backend.api.routes import jobs

    source = fixtures.prepare_runtime_plan(store, 1_000_000)
    await mps_durable.advance(window_runtime, source["job_id"])
    storage = JobStorage(window_runtime.redis)
    tasks = [task async for task in storage.fetch_tasks_stream(source["job_id"])]
    tasks[1].state = TaskState.FAILED
    await storage.persist_task(job_id=source["job_id"], task=tasks[1])
    monkeypatch.setattr(mps_durable, "_retire_retry_source", AsyncMock())
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    result = await mps_submission.retry_job(
        source, request=SimpleNamespace(auth_id=None), backend=window_runtime
    )
    assert result.task_count == 1
    assert store.candidate_page(result.job_id, offset=0, limit=10) == [2]


@pytest.mark.asyncio
async def test_retry_writer_receipt_replay_and_auth_validation_are_atomic(
    store, window_runtime
):
    from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation

    with store.session_factory() as session:
        session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS user_auths(id bigserial PRIMARY KEY, user_id bigint, active boolean)"
            )
        )
        session.execute(
            text(
                "INSERT INTO user_auths(user_id,active) VALUES (101,true),(101,true),(102,false)"
            )
        )
        session.commit()
    source = fixtures.prepare_runtime_plan(store, 100)
    config = retry_config(source)
    payload = {
        "source_job_id": source["job_id"],
        "job_id": config["job_id"],
        "job_config": config,
        "live_failed_user_ids": [8, 18],
        "auth_id": 101,
    }
    command_id = uuid4().hex
    first = await window_runtime.writes.submit(
        DatabaseWriteOperation.RETRY_MPS_JOB,
        payload,
        site="onlyfans",
        command_id=command_id,
    )
    replayed = await window_runtime.writes.submit(
        DatabaseWriteOperation.RETRY_MPS_JOB,
        {**payload, "live_failed_user_ids": [28]},
        site="onlyfans",
        command_id=command_id,
    )
    assert replayed == first
    assert store.candidate_page(first["job_id"], offset=0, limit=10) == [8, 18]
    source = fixtures.prepare_runtime_plan(store, 100)
    config = retry_config(source)
    with pytest.raises(ValueError, match="not active"):
        await window_runtime.writes.submit(
            DatabaseWriteOperation.RETRY_MPS_JOB,
            {
                **payload,
                "source_job_id": source["job_id"],
                "job_id": config["job_id"],
                "job_config": config,
                "auth_id": 102,
            },
            site="onlyfans",
            command_id=uuid4().hex,
        )
    assert store.get(config["job_id"]) is None
    assert store.get(source["job_id"])["status"] == "ready"


@pytest.mark.asyncio
async def test_source_retirement_cancels_routing_before_cleanup(
    store, window_runtime, monkeypatch
):
    source = fixtures.prepare_runtime_plan(store, 10)
    await mps_durable.advance(window_runtime, source["job_id"])
    retried = clone(store, source)
    storage = JobStorage(window_runtime.redis)
    events = []

    async def clear(**kwargs):
        assert (
            await storage.fetch_job(source["job_id"], include_tasks=False)
        ).state == JobState.CANCELLED
        events.append("routing")

    async def cleanup(job_id):
        assert events == ["routing"]
        assert job_id == source["job_id"]
        events.append("cleanup")

    manager = SimpleNamespace(
        _resolve_backend_assignment=AsyncMock(return_value="backend"),
        router=SimpleNamespace(clear_job_routing=clear),
        finalize_job_cancellation=cleanup,
    )
    monkeypatch.setattr(mps_durable, "JobManager", lambda _: manager)
    await mps_durable._retire_retry_source(storage, retried)
    assert events == ["routing", "cleanup"]


def test_reviewable_task_identity_migration_preserves_legacy_unknowns_and_roundtrips(
    postgres_engine, monkeypatch
):
    import ultima_scraper_db_archive
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(ultima_scraper_db_archive.__file__).parent
        / "migrations/alembic/versions/f14c08a932de_add_canonical_task_user_id.py"
    )
    spec = importlib.util.spec_from_file_location(
        "task_identity_migration_fixture", path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "de82a96c410f"
    # DDL is transactional; rollback restores the module fixture's table.
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text("ALTER TABLE management.job_tasks DROP COLUMN user_id")
            )
            identifier = uuid4().hex
            connection.execute(
                text(
                    "INSERT INTO management.job_tasks(task_id,job_id,task_type,username) VALUES (:id,:id,'scrape','12345')"
                ),
                {"id": identifier},
            )
            monkeypatch.setattr(
                migration, "op", Operations(MigrationContext.configure(connection))
            )
            migration.upgrade()
            assert (
                connection.scalar(
                    text("SELECT user_id FROM management.job_tasks WHERE task_id=:id"),
                    {"id": identifier},
                )
                is None
            )
            connection.execute(
                text(
                    "UPDATE management.job_tasks SET user_id=9007199254740993 WHERE task_id=:id"
                ),
                {"id": identifier},
            )
            assert (
                connection.scalar(
                    text("SELECT user_id FROM management.job_tasks WHERE task_id=:id"),
                    {"id": identifier},
                )
                == 9007199254740993
            )
            migration.downgrade()
            assert (
                connection.scalar(
                    text("SELECT username FROM management.job_tasks WHERE task_id=:id"),
                    {"id": identifier},
                )
                == "12345"
            )
        finally:
            transaction.rollback()
