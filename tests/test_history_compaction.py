"""Finished job task-history compaction (history_compaction)."""

from __future__ import annotations

import json
import socket
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

import test_mps_manifest as fixtures
from test_profile_index_retirement import _migrate, archive_url
from ultima_scraper_backend.database import history_compaction as hc

postgres_engine = fixtures.postgres_engine
__all__ = ["archive_url", "postgres_engine"]


@pytest.mark.parametrize(("stored", "expected"), [(None, 3), (7, 7), (0, 0)])
def test_retention_days_reads_the_job_execution_setting(monkeypatch, stored, expected):
    from ultima_scraper_backend.job_system import resources

    monkeypatch.setattr(
        resources,
        "_persisted_job_execution_setting",
        lambda name, db_session=None: stored if name == hc.SETTING else None,
    )
    assert hc.retention_days(SimpleNamespace(begin_nested=nullcontext)) == expected


def test_unreadable_setting_falls_back_to_the_default(monkeypatch):
    from ultima_scraper_backend.job_system import resources

    def broken(name, db_session=None):
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(resources, "_persisted_job_execution_setting", broken)
    assert hc.retention_days(SimpleNamespace(begin_nested=nullcontext)) == 3


def test_setting_defaults_to_three_days_and_rejects_negative_values():
    from pydantic import ValidationError
    from ultima_scraper_backend.config import JobExecutionSettings

    assert JobExecutionSettings().task_history_retention_days == 3
    with pytest.raises(ValidationError):
        JobExecutionSettings(task_history_retention_days=-1)


def test_zero_days_disables_without_opening_a_session():
    def factory():
        raise AssertionError("disabled compaction must not query")

    assert hc.compact_finished_history(days=0, session_factory=factory) == {
        "compacted": 0, "removed_tasks": 0, "busy": 0, "identities_pending": 0,
    }


@pytest.fixture
def history_engine(archive_url, monkeypatch):
    _migrate(archive_url, "upgrade", "heads", monkeypatch)
    engine = create_engine(archive_url)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO management.execution_definitions (definition_id, revision, config_json) "
            "VALUES ('definition-fixture', 1, '{}')"
        ))
    yield engine
    engine.dispose()


def factory_for(engine):
    @contextmanager
    def factory():
        with Session(engine) as session:
            yield session

    return factory


def make_run(engine, run_id, *, tasks=200, age_days=10, job_type="mass_profile_scrape",
             metadata=None, producers=2):
    """A finished run with one attempt per task, every 20th failed, two producers."""

    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO management.execution_runs (run_id, definition_id, revision, state, "
            "config_json, completed_at) VALUES (:run, 'definition-fixture', 1, 'completed', "
            ":config, now() - make_interval(days => :age))"
        ), {"run": run_id, "config": json.dumps({"metadata": metadata or {}}), "age": age_days})
        connection.execute(text(
            "INSERT INTO management.jobs (job_id, job_type, site, status) "
            "VALUES (:run, :type, 'onlyfans', 'completed')"
        ), {"run": run_id, "type": job_type})
        tasks_leaf, attempts_leaf = hc._leaves(run_id)
        connection.execute(text(
            f"CREATE TABLE {tasks_leaf} PARTITION OF management.job_tasks "
            f"FOR VALUES IN ('{run_id}')"
        ))
        connection.execute(text(
            f"CREATE TABLE {attempts_leaf} PARTITION OF management.execution_attempts "
            f"FOR VALUES IN ('{run_id}')"
        ))
        connection.execute(text("""
            INSERT INTO management.job_tasks (task_id, job_id, task_type, status, error, result_json)
            SELECT CAST(:run AS text) || '-task-' || i, CAST(:run AS text), 'scrape',
                   CASE WHEN i % 20 = 0 THEN 'failed' ELSE 'completed' END,
                   CASE WHEN i % 20 = 0 THEN 'proxy timeout' END,
                   CASE WHEN i <= :producers THEN '{"new_tasks": [{"task_id": "child"}]}'
                        ELSE '{"new_tasks": [], "output": {"invalid_user": true}}' END
            FROM generate_series(1, :n) i
        """), {"run": run_id, "n": tasks, "producers": producers})
        connection.execute(text("""
            INSERT INTO management.execution_attempts (run_id, task_id, number, token, owner, state, timings_json)
            SELECT CAST(:run AS text), CAST(:run AS text) || '-task-' || i, 1, CAST(:run AS text) || '-token-' || i, 'worker', 'completed', '{}'
            FROM generate_series(1, :n) i
        """), {"run": run_id, "n": tasks})
        # A failed task's earlier attempt stays with it.
        connection.execute(text("""
            INSERT INTO management.execution_attempts (run_id, task_id, number, token, owner, state, timings_json)
            VALUES (CAST(:run AS text), CAST(:run AS text) || '-task-20', 2, CAST(:run AS text) || '-token-retry', 'worker', 'failed', '{}')
        """), {"run": run_id})


def history(engine, run_id):
    tasks_leaf, attempts_leaf = hc._leaves(run_id)
    with engine.connect() as connection:
        return {
            "tasks": connection.scalar(text(f"SELECT count(*) FROM {tasks_leaf}")),
            "attempts": connection.scalar(text(f"SELECT count(*) FROM {attempts_leaf}")),
            "task_ids": connection.scalar(text(
                "SELECT count(*) FROM management.job_task_identities WHERE job_id=:run"
            ), {"run": run_id}),
            "attempt_ids": connection.scalar(text(
                "SELECT count(*) FROM management.execution_attempt_identities WHERE run_id=:run"
            ), {"run": run_id}),
            "metadata": connection.scalar(text(
                "SELECT config_json::jsonb->'metadata'->'task_history_compaction' "
                "FROM management.execution_runs WHERE run_id=:run"
            ), {"run": run_id}),
        }


def test_compaction_keeps_failures_producers_and_their_attempts(history_engine):
    make_run(history_engine, "job-compact-a")
    counts = hc.compact_finished_history(session_factory=factory_for(history_engine), days=3)

    assert counts["compacted"] == 1 and counts["identities_pending"] == 0
    after = history(history_engine, "job-compact-a")
    # 10 failures, 2 completed producers; the retry attempt stays with its task.
    assert (after["tasks"], after["attempts"]) == (12, 13)
    assert (after["task_ids"], after["attempt_ids"]) == (12, 13)
    assert after["metadata"]["removed_tasks"] == 188
    assert after["metadata"]["removed_attempts"] == 188
    assert after["metadata"]["identities_pending"] is False
    with history_engine.connect() as connection:
        kept = connection.execute(text(
            "SELECT status, count(*) FROM management.job_tasks WHERE job_id='job-compact-a' "
            "GROUP BY status ORDER BY status"
        )).all()
    assert kept == [("completed", 2), ("failed", 10)]
    # Compacted runs are not selected again.
    assert hc.compact_finished_history(
        session_factory=factory_for(history_engine), days=3
    )["compacted"] == 0


def test_ineligible_runs_keep_their_full_history(history_engine):
    make_run(history_engine, "job-young", age_days=1)
    make_run(history_engine, "job-protected")
    make_run(history_engine, "job-deleting", metadata={"deletion_pending": "true"})
    for _ in range(4):
        hc.compact_finished_history(
            session_factory=factory_for(history_engine),
            days=3,
            protected_run_ids={"job-protected"},
        )
    for run_id in ("job-young", "job-protected", "job-deleting"):
        state = history(history_engine, run_id)
        assert (state["tasks"], state["attempts"], state["metadata"]) == (200, 201, None)


def test_lock_timeout_rolls_back_to_full_history_and_retries(history_engine, monkeypatch):
    monkeypatch.setattr(hc, "LOCK_TIMEOUT", "100ms")
    make_run(history_engine, "job-busy")
    tasks_leaf, _ = hc._leaves("job-busy")
    holder = history_engine.connect()
    transaction = holder.begin()
    holder.execute(text(f"SELECT count(*) FROM {tasks_leaf}"))  # ACCESS SHARE blocks TRUNCATE
    try:
        counts = hc.compact_finished_history(session_factory=factory_for(history_engine), days=3)
    finally:
        transaction.rollback()
        holder.close()
    assert counts["busy"] == 1 and counts["compacted"] == 0
    state = history(history_engine, "job-busy")
    assert (state["tasks"], state["attempts"], state["metadata"]) == (200, 201, None)

    counts = hc.compact_finished_history(session_factory=factory_for(history_engine), days=3)
    assert counts["compacted"] == 1
    assert history(history_engine, "job-busy")["tasks"] == 12


def test_identity_cleanup_resumes_in_pages_across_cycles(history_engine, monkeypatch):
    monkeypatch.setattr(hc, "IDENTITY_PAGE", 7)
    make_run(history_engine, "job-pages")
    counts = hc.compact_finished_history(
        session_factory=factory_for(history_engine), days=3, budget_seconds=0
    )
    assert counts["compacted"] == 1 and counts["identities_pending"] == 1
    state = history(history_engine, "job-pages")
    assert state["tasks"] == 12 and state["task_ids"] == 200
    assert state["metadata"]["identities_pending"] is True

    counts = hc.compact_finished_history(session_factory=factory_for(history_engine), days=3)
    assert counts["identities_pending"] == 0
    state = history(history_engine, "job-pages")
    assert (state["task_ids"], state["attempt_ids"]) == (12, 13)
    assert state["metadata"]["identities_pending"] is False


def test_compacted_leaf_accepts_new_rows_through_the_identity_trigger(history_engine):
    make_run(history_engine, "job-trigger")
    hc.compact_finished_history(session_factory=factory_for(history_engine), days=3)
    with history_engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO management.job_tasks (task_id, job_id, task_type, status) "
            "VALUES ('job-trigger-task-new', 'job-trigger', 'scrape', 'failed')"
        ))
    assert history(history_engine, "job-trigger")["task_ids"] == 13


def test_any_job_type_is_compacted(history_engine):
    make_run(history_engine, "job-ordinary", job_type="scrape")
    counts = hc.compact_finished_history(session_factory=factory_for(history_engine), days=3)
    assert counts["compacted"] == 1
    assert history(history_engine, "job-ordinary")["tasks"] == 12


def test_saved_setting_controls_the_retention_age(history_engine):
    make_run(history_engine, "job-setting", age_days=10)
    settings = {"settings": {"job_execution": {"task_history_retention_days": 20}}}
    with history_engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO management.settings (backend, key, value) VALUES (:backend, 'config', :value)"
        ), {"backend": socket.gethostname(), "value": json.dumps(settings)})
    factory = factory_for(history_engine)
    assert hc.compact_finished_history(session_factory=factory)["compacted"] == 0
    with history_engine.begin() as connection:
        connection.execute(text(
            "UPDATE management.settings SET value = :value WHERE key = 'config'"
        ), {"value": json.dumps({"settings": {"job_execution": {"task_history_retention_days": 5}}})})
    assert hc.compact_finished_history(session_factory=factory)["compacted"] == 1


@pytest.mark.asyncio
async def test_retry_of_a_compacted_job_without_failures_explains_why():
    from unittest.mock import AsyncMock

    from ultima_scraper_backend.job_system.manager import JobManager
    from ultima_scraper_backend.job_system.models import Job, JobState

    job = Job.create(name="Compacted Job", created_by="webui", tasks=[])
    job.state = JobState.COMPLETED
    job.metadata[hc.METADATA_KEY] = {"kept_tasks": 0, "removed_tasks": 40}
    manager = JobManager.__new__(JobManager)
    manager.storage = SimpleNamespace(fetch_job_with_tasks=AsyncMock(return_value=job))

    with pytest.raises(RuntimeError, match="task history retention"):
        await manager.prepare_retry_job("job-compacted")
