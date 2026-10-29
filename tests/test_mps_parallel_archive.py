"""Parallel archive passes (ULTIMA_ARCHIVE_PARALLEL_PASSES) match one serial pass."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from sqlalchemy import text
from test_execution_ledger import finish, ledger, ledger_engine, postgres_engine
from test_mps_archive_set_inserts import completed_range
from ultima_scraper_backend.job_system.ledger import archive_parallel_passes
from ultima_scraper_backend.job_system.models import Job, Task, TaskType

__all__ = ["ledger", "ledger_engine", "postgres_engine"]
SWITCH = "ULTIMA_ARCHIVE_PARALLEL_PASSES"
JOB = "archive-pages"
# Every column except per-attempt clocks: two executions of one job differ
# only in when each task ran.
_VOLATILE = {"created_at", "started_at", "completed_at", "updated_at", "result_json",
             "result_completed_at", "definition_json", "last_event_at"}


def reset(ledger_engine):
    with ledger_engine.begin() as connection:
        connection.execute(text(
            "TRUNCATE management.execution_outbox, management.execution_resources, "
            "management.execution_attempts, management.execution_work, management.execution_runs, "
            "management.execution_definitions, management.mps_retry_tasks, "
            "management.mps_task_definitions, management.mps_candidate_ranges, management.mps_plans, "
            "management.job_tasks, management.jobs, management.database_write_receipts CASCADE"
        ))
        connection.execute(text("UPDATE management.execution_feed SET next_sequence=1"))
        connection.execute(text("TRUNCATE onlyfans.users, onlyfans.invalid_users"))


def state(ledger, job=JOB):
    with ledger.session_factory() as session:
        columns = [
            name for name in session.scalars(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='management' AND table_name='job_tasks' ORDER BY column_name
            """)) if name not in _VOLATILE
        ]
        history = [tuple(row) for row in session.execute(text(
            f"SELECT {', '.join(columns)} FROM management.job_tasks "
            "WHERE job_id=:job ORDER BY task_id"), {"job": job})]
        outputs = [
            json.loads(value)["output"] for value in session.scalars(text(
                "SELECT result_json FROM management.job_tasks WHERE job_id=:job ORDER BY task_id"
            ), {"job": job})
        ]
        plan = session.execute(text(
            "SELECT cursor, total, completed, failed, status, selection_json "
            "FROM management.mps_plans WHERE job_id=:job"), {"job": job}).one()
        run = session.scalar(text(
            "SELECT state FROM management.execution_runs WHERE run_id=:job"), {"job": job})
        work = session.scalar(text(
            "SELECT count(*) FROM management.execution_work WHERE run_id=:job"), {"job": job})
    selection = json.loads(plan.selection_json)
    return {
        "history": history, "outputs": outputs, "work": work, "run": run,
        "plan": (plan.cursor, plan.total, plan.completed, plan.failed, plan.status),
        "checkpoint": selection.get("candidate_checkpoint"),
    }


def drain(ledger, passes):
    """Run ``passes`` archivers until none archives anything."""
    errors = []

    def worker():
        try:
            idle = 0
            while idle < 3:
                idle = 0 if ledger.archive_tick() else idle + 1
        except Exception as error:  # noqa: BLE001 - surfaced below
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(passes)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []


def small_batches(ledger, size=64):
    ledger.limits = replace(ledger.limits, archive_batch=size)


@pytest.mark.parametrize("value,passes", [
    (None, 1), ("", 1), ("1", 1), ("0", 1), ("-3", 1), ("x", 1),
    ("2", 2), (" 3 ", 3), ("64", 8),
])
def test_switch_defaults_to_one_pass(monkeypatch, value, passes):
    if value is None:
        monkeypatch.delenv(SWITCH, raising=False)
    else:
        monkeypatch.setenv(SWITCH, value)
    assert archive_parallel_passes() == passes


def test_parallel_passes_equal_one_serial_pass(ledger, ledger_engine, monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    completed_range(ledger)
    small_batches(ledger)
    drain(ledger, 1)
    serial = state(ledger)
    assert serial["plan"] == (1001, 1001, 667, 334, "complete")
    assert serial["work"] == 0 and serial["run"] == "completed"
    assert len(serial["history"]) == 1001

    reset(ledger_engine)
    monkeypatch.setenv(SWITCH, "3")
    completed_range(ledger)
    small_batches(ledger)
    drain(ledger, 3)
    assert state(ledger) == serial


def test_two_passes_insert_one_run_at_once(ledger, monkeypatch):
    """Both passes are inside the unlocked insert phase together, on disjoint rows."""
    monkeypatch.setenv(SWITCH, "2")
    completed_range(ledger, 200)
    small_batches(ledger, 50)
    barrier = threading.Barrier(2, timeout=30)
    batches = []
    original = ledger.manifests.archive_concurrent

    def meet(job_id, **kwargs):
        if len(batches) < 2:
            batches.append({row["task_id"] for row in kwargs["rows"]})
            barrier.wait()
        return original(job_id, **kwargs)

    monkeypatch.setattr(ledger.manifests, "archive_concurrent", meet)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: ledger.archive_tick(), range(2)))
    assert results == [JOB, JOB]
    assert len(batches) == 2 and not batches[0] & batches[1]
    drain(ledger, 2)
    final = state(ledger)
    assert final["plan"] == (200, 200, 133, 67, "complete")
    assert final["checkpoint"] == {"next": 200, "pending": []}
    assert final["work"] == 0 and len(final["history"]) == 200


def test_serial_mode_does_not_overlap_passes(ledger, monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    completed_range(ledger, 20)
    called = []
    monkeypatch.setattr(ledger.manifests, "archive_concurrent",
                        lambda *args, **kwargs: called.append(1))
    assert ledger.archive_tick() == JOB
    assert called == []
    assert state(ledger)["plan"][0] == 20


def test_parallel_passes_with_planner_archive_tick(ledger, monkeypatch):
    """The non-refill tick holds the plan; it must not deadlock with passes."""
    monkeypatch.setenv(SWITCH, "3")
    completed_range(ledger, 600)
    small_batches(ledger, 32)
    errors = []

    def ticks():
        try:
            for _ in range(40):
                ledger.tick()
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    planner = threading.Thread(target=ticks)
    planner.start()
    drain(ledger, 3)
    planner.join(120)
    assert errors == []
    final = state(ledger)
    assert final["plan"] == (600, 600, 400, 200, "complete")
    assert final["work"] == 0 and len(final["history"]) == 600


def test_cancel_waits_for_a_running_parallel_pass(ledger, monkeypatch):
    monkeypatch.setenv(SWITCH, "2")
    completed_range(ledger, 100)
    small_batches(ledger, 40)
    inside, release = threading.Event(), threading.Event()
    original = ledger.manifests.archive_checkpoint

    def hold(*args, **kwargs):
        if not inside.is_set():
            inside.set()
            assert release.wait(30)
        return original(*args, **kwargs)

    monkeypatch.setattr(ledger.manifests, "archive_checkpoint", hold)
    with ThreadPoolExecutor(2) as pool:
        archive = pool.submit(ledger.archive_tick)
        assert inside.wait(30)
        cancel = pool.submit(ledger.control, JOB, "cancel")
        # The control's exclusive run lock waits for the pass's shared lock.
        with pytest.raises(TimeoutError):
            cancel.result(timeout=1)
        release.set()
        assert archive.result(timeout=30) == JOB
        cancel.result(timeout=30)
    final = state(ledger)
    cursor, _, completed, failed, _ = final["plan"]
    assert cursor == completed + failed == len(final["history"])
    assert final["run"] == "cancelled"


def test_mixed_batch_takes_serial_path_in_parallel_mode(ledger, monkeypatch):
    monkeypatch.setenv(SWITCH, "2")
    ledger.limits = replace(ledger.limits, tasks=8, global_tasks=8, batch=8,
                            planner_batch=8, archive_batch=8)
    job = Job.create(name="Mixed archive", created_by="test", tasks=[])
    job.job_id = "archive-mixed"
    ledger.manifests.create(
        job_id=job.job_id, site="onlyfans", job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": 3, "max_profiles": None},
        proxy_pool=[], site_session_factory=ledger.session_factory,
    )
    assert ledger.tick() == job.job_id
    owned = ledger.claim_many(owner="w", backend_id="test", capabilities=["onlyfans"], count=3)
    child = Task(task_id="task-child00001", user_id=99, task_type=TaskType.SCRAPE,
                 site_name="onlyfans", capabilities=["onlyfans"])
    finish(ledger, owned[0], children=[child])
    assert ledger.archive_tick() == job.job_id  # candidate-only: parallel path
    ledger.tick()
    spawned = ledger.claim_many(owner="w", backend_id="test", capabilities=["onlyfans"], count=3)
    assert [claim.task_id for claim in spawned] == ["task-child00001"]
    for claim in [*owned[1:], *spawned]:
        finish(ledger, claim)
    concurrent = []
    original = ledger.manifests.archive_concurrent
    monkeypatch.setattr(ledger.manifests, "archive_concurrent",
                        lambda *a, **k: concurrent.append(1) or original(*a, **k))
    assert ledger.archive_tick() == job.job_id  # mixed: plan locked first
    assert concurrent == []
    final = state(ledger, job.job_id)
    assert final["plan"][:4] == (4, 4, 4, 0)
    assert len(final["history"]) == 4 and final["work"] == 0
