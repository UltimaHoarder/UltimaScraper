"""Frozen graph pages survive interruption without publishing partial retries."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import event, inspect, text

import test_mps_graph_retry as graphs
import test_mps_manifest as fixtures
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.api.routes import mps_durable as mps_submission
from ultima_scraper_backend.database.mps_definitions import MPSDefinitionBudgetExceeded
from ultima_scraper_backend.database.mps_retry import retry_task_id
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
from ultima_scraper_backend.job_system import JobStorage, Task
from ultima_scraper_backend.job_system.models import TaskType
from ultima_scraper_db_archive.global_db import MPSRetryTaskModel

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


def source_graph(store, count=5, *, wide=False):
    tasks = [Task(task_type=TaskType.DOWNLOAD, site_name="OnlyFans", user_id=1,
                  payload={"media_ids": list(range(4000))} if wide else {})
             for _ in range(count)]
    for previous, task in zip(tasks, tasks[1:]):
        task.depends_on = [previous.task_id]
    return graphs.explicit_plan(store, tasks), tasks


def advance(store, plan, *, commit=True, after=None):
    with store.session_factory() as session:
        result = store.advance_retry(
            plan["job_id"],
            after=plan["selection"]["retry_preparation"]["after"] if after is None else after,
            db_session=session,
        )
        if commit:
            session.commit()
    return result


def counts(store, job_id):
    with store.session_factory() as session:
        return tuple(session.execute(text("""
            SELECT (SELECT count(*) FROM management.mps_retry_tasks WHERE job_id=:job),
                   (SELECT count(*) FROM management.mps_task_definitions WHERE manifest_id=:job)
        """), {"job": job_id}).one())


@pytest.mark.parametrize("batch", [1, 2, 4])
def test_committed_pages_resume_with_original_intact_until_final_page(store, monkeypatch, batch):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", str(batch))
    source, tasks = source_graph(store)
    plan = graphs.clone(store, source, incremental=True)
    assert plan["status"] == "preparing"
    assert counts(store, plan["job_id"]) == (5, 0)
    assert plan["job_id"] in store.active_page(limit=100)
    saved = plan
    while plan["status"] == "preparing":
        before = counts(store, plan["job_id"])
        plan = advance(store, plan)
        after = counts(store, plan["job_id"])
        assert before[0] - after[0] == after[1] - before[1] <= batch
        assert sum(after) == 5
        assert store.get(source["job_id"])["status"] == (
            "cancelled" if plan["status"] == "ready" else "ready"
        )
        # Replaying an older checkpoint cannot copy another page.
        assert advance(store, saved, after=-1) == plan
    definitions = store.definitions.page(plan["job_id"], offset=0, limit=10)
    assert [row["task_id"] for row in definitions] == [retry_task_id(plan["job_id"], task.task_id) for task in tasks]
    assert plan["job_config"]["metadata"]["mps_task_type_counts"] == {"download": 5}
    assert counts(store, plan["job_id"]) == (0, 5)


@pytest.mark.parametrize("fail_final", [False, True])
def test_page_rollback_restores_inputs_definitions_checkpoint_and_source(store, monkeypatch, fail_final):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    source, _ = source_graph(store, 4)
    plan = graphs.clone(store, source, incremental=True)
    if fail_final:
        plan = advance(store, plan)
    before = counts(store, plan["job_id"])
    advance(store, plan, commit=False)
    assert store.get(plan["job_id"]) == plan
    assert counts(store, plan["job_id"]) == before
    assert store.get(source["job_id"])["status"] == "ready"
    assert advance(store, plan)["status"] == ("ready" if fail_final else "preparing")


def test_overlapping_writers_advance_the_same_checkpoint_once(store, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    source, _ = source_graph(store)
    plan = graphs.clone(store, source, incremental=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: advance(store, plan), range(2)))
    assert results[0] == results[1]
    assert counts(store, plan["job_id"]) == (3, 2)


def test_composite_cursor_does_not_copy_neighboring_jobs(store, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    source, _ = source_graph(store, 3)
    plans = sorted([graphs.clone(store, source, incremental=True) for _ in range(3)],
                   key=lambda plan: plan["job_id"])
    middle = advance(store, plans[1])
    assert counts(store, middle["job_id"]) == (1, 2)
    middle = advance(store, middle)
    assert middle["status"] == "ready"
    assert counts(store, plans[0]["job_id"]) == (3, 0)
    assert counts(store, plans[2]["job_id"]) == (3, 0)
    assert counts(store, middle["job_id"]) == (0, 3)


@pytest.mark.parametrize("change", ["delete", "replace", "recreate"])
def test_source_generation_change_cannot_be_retired_by_partial_retry(store, monkeypatch, change):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    source, _ = source_graph(store, 4)
    plan = advance(store, graphs.clone(store, source, incremental=True))
    with store.session_factory() as session:
        if change == "delete":
            session.execute(text("DELETE FROM management.mps_plans WHERE job_id=:id"), {"id": source["job_id"]})
        elif change == "replace":
            session.execute(text("UPDATE management.mps_plans SET selection_json=:selection WHERE job_id=:id"),
                            {"id": source["job_id"], "selection": json.dumps({"task_manifest_id": uuid4().hex})})
        else:
            session.execute(text("UPDATE management.mps_plans SET created_at=created_at + interval '1 second' WHERE job_id=:id"),
                            {"id": source["job_id"]})
        session.commit()
    with pytest.raises(ValueError, match="deleted or replaced"):
        advance(store, plan)
    assert counts(store, plan["job_id"]) == (2, 2)
    if change != "delete":
        assert store.get(source["job_id"])["status"] == "ready"


@pytest.mark.parametrize("terminal", ["cancelled", "failed", "deleted"])
def test_terminal_target_never_resumes_or_retires_its_source(store, monkeypatch, terminal):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    source, _ = source_graph(store)
    plan = advance(store, graphs.clone(store, source, incremental=True))
    if terminal == "deleted":
        with store.session_factory() as session:
            session.execute(text("DELETE FROM management.mps_plans WHERE job_id=:id"), {"id": plan["job_id"]})
            session.commit()
    else:
        store.terminate(plan["job_id"], status=terminal)
    assert counts(store, plan["job_id"])[0] == 0
    result = advance(store, plan)
    assert result == {"deleted": True} if terminal == "deleted" else result["status"] == terminal
    assert store.get(source["job_id"])["status"] == "ready"


def test_budget_failure_retains_checkpoint_and_explicit_increase_resumes(store, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    source, _ = source_graph(store, 3, wide=True)
    plan = graphs.clone(store, source, incremental=True)
    monkeypatch.setenv("ULTIMA_MPS_RETRY_BATCH_MAX_BYTES", "1000")
    with pytest.raises(MPSDefinitionBudgetExceeded):
        advance(store, plan)
    assert counts(store, plan["job_id"]) == (3, 0)
    assert store.get(plan["job_id"]) == plan
    monkeypatch.setenv("ULTIMA_MPS_RETRY_BATCH_MAX_BYTES", "1000000")
    assert advance(store, plan)["selection"]["retry_preparation"]["copied"] == 2


def test_preparing_graph_cannot_be_retried_or_replaced_as_complete_input(store):
    source, _ = source_graph(store)
    plan = graphs.clone(store, source, incremental=True)
    with pytest.raises(ValueError, match="preparation is still in progress"):
        graphs.clone(store, plan)
    with pytest.raises(ValueError, match="preparation is still in progress"):
        store.definitions.begin(plan["job_id"], uuid4().hex)


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("failed_only", [False, True])
async def test_spawned_child_ownership_survives_commits_between_every_node(
    store, window_runtime, monkeypatch, explicit, failed_only,
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    atomic_clone = graphs.clone

    def checkpointed_clone(store, source, **kwargs):
        plan = atomic_clone(store, source, incremental=True, **kwargs)
        while plan["status"] == "preparing":
            plan = advance(store, plan)
        return plan

    monkeypatch.setattr(graphs, "clone", checkpointed_clone)
    await graphs.test_generated_retry_refreshes_one_owned_child_and_uses_fresh_output(
        store, window_runtime, monkeypatch, explicit, failed_only,
    )


async def test_writer_process_exit_after_commit_replays_receipt_without_recopied_page(
    store, window_runtime, monkeypatch, tmp_path,
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    source, _ = source_graph(store, 5)
    plan = graphs.clone(store, source, incremental=True)
    with store.session_factory() as session:
        url = session.get_bind().url.render_as_string(hide_password=False)
    command_id = uuid4().hex
    worker = tmp_path / "retry_writer.py"
    worker.write_text(f'''import sys
sys.path[:0] = {sys.path!r}
import os
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from ultima_scraper_db_archive import global_db
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.database.write_queue import DatabaseWriteCommand, DatabaseWriteOperation
engine = create_engine({url!r})
@contextmanager
def session_factory():
    with Session(engine) as session:
        session.execute(text("SET LOCAL search_path = onlyfans, management, public"))
        yield session
global_db.global_session = session_factory
command = DatabaseWriteCommand({command_id!r}, DatabaseWriteOperation.ADVANCE_MPS_RETRY,
    None, {{"job_id": {plan['job_id']!r}, "after": -1}}, "crash-fixture", "2026-09-07T00:00:00+00:00")
PostgreSQLWriteExecutor._advance_mps_retries([command])
os._exit(73)
''')
    result = subprocess.run([sys.executable, str(worker)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 73, result.stderr
    assert counts(store, plan["job_id"]) == (3, 2)
    replayed = await window_runtime.writes.submit(
        DatabaseWriteOperation.ADVANCE_MPS_RETRY,
        {"job_id": plan["job_id"], "after": -1}, command_id=command_id,
    )
    assert replayed["selection"]["retry_preparation"]["copied"] == 2
    assert counts(store, plan["job_id"]) == (3, 2)
    assert store.get(source["job_id"])["status"] == "ready"


def test_target_name_and_schedule_edits_survive_final_copy(store, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    source, _ = source_graph(store, 3)
    plan = advance(store, graphs.clone(store, source, incremental=True))
    schedule = {"enabled": True, "scheduled_for": "2099-01-01T00:00:00+00:00"}
    edited = store.update_config(plan["job_id"], name="My pending retry", schedule=schedule)
    ready = advance(store, edited)
    assert ready["status"] == "ready"
    assert ready["job_config"]["name"] == "My pending retry"
    assert ready["job_config"]["schedule"]["scheduled_for"] == schedule["scheduled_for"]


async def test_materializer_resumes_after_redis_loss_without_exposing_partial_tasks(
    store, window_runtime, monkeypatch,
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    source, _ = source_graph(store, 5)
    response = await mps_submission.retry_job(source, request=SimpleNamespace(auth_id=None), backend=window_runtime)
    plan = store.get(response.job_id)
    assert plan["status"] == "preparing"
    assert counts(store, plan["job_id"]) == (3, 2)
    storage = JobStorage(window_runtime.redis)
    assert not [task async for task in storage.fetch_tasks_stream(plan["job_id"])]
    await storage._client().flushdb()  # This fixture owns its private Redis database.
    await mps_durable.recover(window_runtime)
    assert counts(store, plan["job_id"]) == (3, 2)
    assert await mps_durable.advance(window_runtime, plan["job_id"])
    assert not [task async for task in storage.fetch_tasks_stream(plan["job_id"])]
    assert store.get(source["job_id"])["status"] == "ready"
    assert await mps_durable.advance(window_runtime, plan["job_id"])
    assert store.get(source["job_id"])["status"] == "cancelled"
    await mps_durable.advance(window_runtime, plan["job_id"], activate=False)
    assert len([task async for task in storage.fetch_tasks_stream(plan["job_id"])]) <= 3
    assert counts(store, plan["job_id"]) == (0, 5)


async def test_copy_and_final_publication_share_the_writer_receipt(store, window_runtime, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    source, _ = source_graph(store, 2)
    plan = graphs.clone(store, source, incremental=True)
    command_id = uuid4().hex
    engine = window_runtime.writes
    def fail_receipt(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO management.database_write_receipts"):
            raise RuntimeError("receipt failure")
    with store.session_factory() as session:
        bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", fail_receipt)
    try:
        with pytest.raises(RuntimeError, match="receipt failure"):
            await engine.submit(DatabaseWriteOperation.ADVANCE_MPS_RETRY,
                                {"job_id": plan["job_id"], "after": -1}, command_id=command_id)
    finally:
        event.remove(bind, "before_cursor_execute", fail_receipt)
    assert counts(store, plan["job_id"]) == (2, 0)
    assert store.get(source["job_id"])["status"] == "ready"
    result = await engine.submit(DatabaseWriteOperation.ADVANCE_MPS_RETRY,
                                 {"job_id": plan["job_id"], "after": -1}, command_id=command_id)
    assert result["status"] == "ready"
    assert await engine.submit(DatabaseWriteOperation.ADVANCE_MPS_RETRY,
                               {"job_id": plan["job_id"], "after": -1}, command_id=command_id) == result
    assert counts(store, plan["job_id"]) == (0, 2)


def test_retry_table_migration_matches_model_and_cascades(postgres_engine, monkeypatch):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import ultima_scraper_db_archive

    path = Path(ultima_scraper_db_archive.__file__).parent / "migrations/alembic/versions/e25ac8106df4_add_mps_retry_checkpoints.py"
    spec = importlib.util.spec_from_file_location("retry_checkpoint_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with postgres_engine.begin() as connection:
        MPSRetryTaskModel.__table__.drop(connection)
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        assert {column["name"] for column in inspect(connection).get_columns("mps_retry_tasks", schema="management")} == set(MPSRetryTaskModel.__table__.columns.keys())
        assert inspect(connection).get_foreign_keys("mps_retry_tasks", schema="management")[0]["options"]["ondelete"] == "CASCADE"
        module.downgrade()
        MPSRetryTaskModel.__table__.create(connection)
