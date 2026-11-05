"""Proven MPS candidate rows may skip the global task directory; nothing else may."""

import importlib.util
import json
import os
from dataclasses import replace
from pathlib import Path

import ultima_scraper_db_archive

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from test_execution_ledger import finish
from test_mps_archive_identity_directory import (
    ledger,
    ledger_engine,
    postgres_engine,
    repartition,
)
from test_mps_archive_set_inserts import completed_range
from ultima_scraper_backend.database import archive_prefetch as prefetch
from ultima_scraper_backend.database.mps_manifest import trusted_mps_identity_enabled
from ultima_scraper_backend.job_system.models import Job, Task, TaskType

__all__ = ["ledger", "ledger_engine", "postgres_engine"]
SWITCH = "ULTIMA_ARCHIVE_TRUSTED_MPS_IDENTITY"


def trust_migration(ledger_engine, direction="upgrade"):
    path = (Path(ultima_scraper_db_archive.__file__).parent
            / "migrations/alembic/versions/d5e1a7c39b42_trusted_mps_task_identity.py")
    spec = importlib.util.spec_from_file_location("trusted_identity_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with ledger_engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        getattr(module, direction)()


def guarded(ledger_engine):
    repartition(ledger_engine)
    trust_migration(ledger_engine)


def counts(ledger, job="archive-pages"):
    with ledger.session_factory() as session:
        return {
            "history": session.scalar(text(
                "SELECT count(*) FROM management.job_tasks WHERE job_id=:job"), {"job": job}),
            "directory": session.scalar(text(
                "SELECT count(*) FROM management.job_task_identities WHERE job_id=:job"), {"job": job}),
            "work": session.scalar(text(
                "SELECT count(*) FROM management.execution_work WHERE run_id=:job"), {"job": job}),
            "cursor": session.scalar(text(
                "SELECT cursor FROM management.mps_plans WHERE job_id=:job"), {"job": job}),
        }


@pytest.mark.parametrize("value,enabled", [
    (None, False), ("0", False), ("off", False), ("", False),
    ("1", True), ("true", True), (" ON ", True), ("yes", True),
])
def test_switch_is_off_unless_explicitly_enabled(monkeypatch, value, enabled):
    if value is None:
        monkeypatch.delenv(SWITCH, raising=False)
    else:
        monkeypatch.setenv(SWITCH, value)
    assert trusted_mps_identity_enabled() is enabled


def test_trusted_candidates_keep_history_and_skip_directory(ledger, ledger_engine, monkeypatch):
    job = completed_range(ledger, 6)
    guarded(ledger_engine)
    monkeypatch.setenv(SWITCH, "1")
    assert ledger.archive_tick() == job
    assert counts(ledger) == {"history": 6, "directory": 0, "work": 0, "cursor": 6}


def test_switch_off_keeps_directory_with_migration_applied(ledger, ledger_engine, monkeypatch):
    job = completed_range(ledger, 6)
    guarded(ledger_engine)
    monkeypatch.delenv(SWITCH, raising=False)
    assert ledger.archive_tick() == job
    assert counts(ledger) == {"history": 6, "directory": 6, "work": 0, "cursor": 6}


def test_mixed_batch_trusts_only_candidate_rows(ledger, ledger_engine, monkeypatch):
    # A spawned child is explicit work: archived beside candidates in one
    # batch, it must still be written to the directory.
    ledger.limits = replace(ledger.limits, tasks=8, global_tasks=8, batch=8,
                            planner_batch=8, archive_batch=8)
    job = Job.create(name="Mixed archive", created_by="test", tasks=[])
    job.job_id = "archive-mixed"
    ledger.manifests.create(
        job_id=job.job_id, site="onlyfans", job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": 3, "max_profiles": None},
        proxy_pool=[], site_session_factory=ledger.session_factory,
    )
    guarded(ledger_engine)
    monkeypatch.setenv(SWITCH, "1")
    assert ledger.tick() == job.job_id
    owned = ledger.claim_many(owner="w", backend_id="test", capabilities=["onlyfans"], count=3)
    assert len(owned) == 3
    child = Task(task_id="task-child00001", user_id=99, task_type=TaskType.SCRAPE,
                 site_name="onlyfans", capabilities=["onlyfans"])
    finish(ledger, owned[0], children=[child])
    assert ledger.archive_tick() == job.job_id  # parent archived, child defined
    ledger.tick()
    spawned = ledger.claim_many(owner="w", backend_id="test", capabilities=["onlyfans"], count=3)
    assert [claim.task_id for claim in spawned] == ["task-child00001"]
    for claim in [*owned[1:], *spawned]:
        finish(ledger, claim)
    observations = []
    assert ledger.archive_tick(diagnostics=observations) == job.job_id
    assert observations[-1]["archived_tasks"] == 3  # two candidates + the child, one pass
    with ledger.session_factory() as session:
        history = set(session.scalars(text(
            "SELECT task_id FROM management.job_tasks WHERE job_id='archive-mixed'")))
        directory = set(session.scalars(text(
            "SELECT task_id FROM management.job_task_identities WHERE job_id='archive-mixed'")))
    assert len(history) == 4 and "task-child00001" in history
    assert directory == {"task-child00001"}


def test_forged_candidate_is_rejected_before_any_insert(ledger, ledger_engine, monkeypatch):
    job = completed_range(ledger, 6)
    guarded(ledger_engine)
    monkeypatch.setenv(SWITCH, "1")
    with ledger.session_factory() as session:
        # Point one task at another candidate's ordinal: its ID no longer
        # matches mps_task_id(job, ordinal, user), so it is not proven.
        session.execute(text("""
            UPDATE management.execution_work SET candidate = candidate + 1
            WHERE run_id=:job AND task_id=(SELECT min(task_id) FROM management.execution_work WHERE run_id=:job)
        """), {"job": job})
        session.commit()
    with pytest.raises(ValueError, match="differs from its selected candidate"):
        ledger.archive_tick()
    assert counts(ledger) == {"history": 0, "directory": 0, "work": 6, "cursor": 0}


def test_flag_never_relaxes_delete_update_or_attempt_identities(ledger, ledger_engine):
    job = completed_range(ledger, 3)
    guarded(ledger_engine)
    assert ledger.archive_tick() == job  # switch off: directory rows exist
    with ledger_engine.begin() as connection:
        connection.execute(text("SELECT set_config('ultima.trusted_mps_identity','on',true)"))
        task_id = connection.scalar(text(
            "SELECT min(task_id) FROM management.job_tasks WHERE job_id=:job"), {"job": job})
        with pytest.raises(Exception, match="Task identity is immutable"):
            with connection.begin_nested():
                connection.execute(text(
                    "UPDATE management.job_tasks SET task_id=task_id || 'x' WHERE job_id=:job AND task_id=:task"),
                    {"job": job, "task": task_id})
        connection.execute(text(
            "DELETE FROM management.job_tasks WHERE job_id=:job AND task_id=:task"), {"job": job, "task": task_id})
        assert connection.scalar(text(
            "SELECT count(*) FROM management.job_task_identities WHERE task_id=:task"), {"task": task_id}) == 0
        before = connection.scalar(text(
            "SELECT count(*) FROM management.execution_attempt_identities WHERE run_id=:job"), {"job": job})
        connection.execute(text("""
            INSERT INTO management.execution_attempts(run_id,task_id,number,token,owner,state,timings_json)
            VALUES (:job, :task, 99, 'trusted-flag-token', 'test', 'completed', '{}')
        """), {"job": job, "task": task_id})
        after = connection.scalar(text(
            "SELECT count(*) FROM management.execution_attempt_identities WHERE run_id=:job"), {"job": job})
        assert after == before + 1


def test_retirement_tolerates_runs_without_directory_rows(ledger, ledger_engine, monkeypatch):
    from ultima_scraper_backend.database.history_compaction import purge_identity_page

    job = completed_range(ledger, 3)
    guarded(ledger_engine)
    monkeypatch.setenv(SWITCH, "1")
    assert ledger.archive_tick() == job
    with ledger.session_factory() as session:
        assert purge_identity_page(session, job, "task", "") == (0, None)


def test_trusted_batch_prefetches_only_run_history(ledger, ledger_engine, monkeypatch):
    job = completed_range(ledger, 2048)
    guarded(ledger_engine)
    monkeypatch.setenv(SWITCH, "1")
    monkeypatch.setattr(prefetch, "_index_is_cold", lambda session: True)
    queries = []
    monkeypatch.setattr(prefetch, "_read", lambda dbapi, args, params, query, *rest: queries.append(query) or True)
    assert ledger.archive_tick() == job
    assert queries == [prefetch._READS[2]]
    assert counts(ledger)["directory"] == 0


def test_downgrade_restores_unconditional_directory(ledger, ledger_engine, monkeypatch):
    job = completed_range(ledger, 3)
    guarded(ledger_engine)
    trust_migration(ledger_engine, "downgrade")
    monkeypatch.setenv(SWITCH, "1")
    assert ledger.archive_tick() == job
    assert counts(ledger)["directory"] == 3


def test_parallel_passes_keep_trusted_archive_exact(ledger, ledger_engine, monkeypatch):
    from test_mps_parallel_archive import drain, state

    job = completed_range(ledger, 600)
    ledger.limits = replace(ledger.limits, archive_batch=64)
    guarded(ledger_engine)
    monkeypatch.setenv(SWITCH, "1")
    monkeypatch.setenv("ULTIMA_ARCHIVE_PARALLEL_PASSES", "3")
    drain(ledger, 3)
    assert counts(ledger) == {"history": 600, "directory": 0, "work": 0, "cursor": 600}
    final = state(ledger, job)
    assert final["plan"] == (600, 600, 400, 200, "complete")
    assert final["checkpoint"] == {"next": 600, "pending": []}
    assert final["run"] == "completed"


@pytest.mark.skipif(not os.getenv("USR_BENCH_ARCHIVE_PARALLEL"), reason="opt-in archive benchmark")
@pytest.mark.parametrize("passes", [1, 2, 3])
def test_parallel_archive_benchmark(ledger, ledger_engine, monkeypatch, passes):
    """Archive throughput of N passes over one run, on the guarded, trusted schema."""
    import time

    from test_mps_parallel_archive import drain

    size = int(os.getenv("USR_BENCH_ARCHIVE_PARALLEL_TASKS", "12288"))
    ledger.limits = replace(ledger.limits, bytes=256 * 1024 * 1024,
                            global_bytes=256 * 1024 * 1024, result_bytes=256 * 1024 * 1024)
    job = completed_range(ledger, size)
    ledger.limits = replace(ledger.limits, archive_batch=2048)
    guarded(ledger_engine)
    monkeypatch.setenv(SWITCH, "1")
    monkeypatch.setenv("ULTIMA_ARCHIVE_PARALLEL_PASSES", str(passes))
    original = ledger.archive_tick
    observations = []
    monkeypatch.setattr(ledger, "archive_tick", lambda: original(diagnostics=observations))
    started = time.perf_counter()
    drain(ledger, passes)
    seconds = time.perf_counter() - started
    assert counts(ledger, job)["cursor"] == size
    phases = {}
    batches = [entry for entry in observations if entry["archived_tasks"]]
    for entry in batches:
        for phase, ms in entry["phases_ms"].items():
            phases[phase] = phases.get(phase, 0) + ms
    report = {
        "passes": passes, "tasks": size, "seconds": round(seconds, 3),
        "tasks_per_second": round(size / seconds), "batches": len(batches),
        "median_batch_ms": sorted(entry["archive_ms"] for entry in batches)[len(batches) // 2],
        "mean_phase_ms": {key: round(value / len(batches), 1) for key, value in sorted(phases.items())},
    }
    print("ARCHIVE_PARALLEL_BENCH", json.dumps(report))
    output = os.getenv("USR_BENCH_ARCHIVE_PARALLEL")
    if output not in ("1", "true"):
        with open(output, "a") as handle:
            handle.write(json.dumps(report) + "\n")
