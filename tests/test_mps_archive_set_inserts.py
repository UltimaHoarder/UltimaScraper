"""Archive pages retain exact evidence and atomic checkpoint recovery."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import event, text
from test_execution_ledger import ledger, ledger_engine, postgres_engine
from ultima_scraper_backend.job_system.ledger_batches import completion_request
from ultima_scraper_backend.job_system.models import Job, Task, TaskResult, TaskState

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def completed_range(ledger, count=1001):
    ledger.limits = replace(
        ledger.limits, tasks=count, global_tasks=count, batch=count,
        planner_batch=count, archive_batch=count,
    )
    job = Job.create(name="Archive pages", created_by="test", tasks=[])
    job.job_id = "archive-pages"
    ledger.manifests.create(
        job_id=job.job_id, site="onlyfans", job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": count, "max_profiles": None},
        proxy_pool=[], site_session_factory=ledger.session_factory,
    )
    assert ledger.tick() == job.job_id
    owned = ledger.claim_many(
        owner="archive-worker", backend_id="test", capabilities=["onlyfans"],
        count=count,
    )
    assert len(owned) == count
    requests = []
    for index, claim in enumerate(owned):
        item = Task.from_dict(claim.task)
        success = index % 3 != 0
        item.state = TaskState.COMPLETED if success else TaskState.FAILED
        item.result = TaskResult(
            success=success, output={"ordinal": index},
            errors=[] if success else ["inconclusive test lookup"],
        )
        item.completed_at = item.result.completed_at
        requests.append(completion_request(ledger, claim, item))
    for offset in range(0, len(requests), 512):
        page = requests[offset:offset + 512]
        assert ledger.finish_batch(page) == [None] * len(page)
    return job.job_id


def test_archive_pages_commit_exact_mixed_outcomes_without_per_row_inserts(
    ledger, ledger_engine,
):
    job_id = completed_range(ledger)
    inserts = []

    def capture(conn, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO management.job_tasks"):
            inserts.append({"executemany": many, "parameter_count": len(parameters),
                            "statement": statement})

    event.listen(ledger_engine, "before_cursor_execute", capture)
    try:
        assert ledger.archive_tick() == job_id
    finally:
        event.remove(ledger_engine, "before_cursor_execute", capture)
    output = os.environ.get("USR_ARCHIVE_PROTOCOL_REPORT")
    if output:
        Path(output).write_text(json.dumps(inserts, indent=2) + "\n")
    with ledger.session_factory() as session:
        counts = dict(session.execute(text(
            "SELECT status,count(*) FROM management.job_tasks GROUP BY status"
        )).all())
        assert counts == {"completed": 667, "failed": 334}
        assert session.scalar(text(
            "SELECT count(DISTINCT user_id) FROM management.job_tasks"
        )) == 1001
        assert session.scalar(text(
            "SELECT count(*) FROM management.job_tasks "
            "WHERE result_json IS NULL OR definition_json IS NULL"
        )) == 0
        assert session.scalar(text("SELECT count(*) FROM management.execution_work")) == 0
        assert session.scalar(text("SELECT cursor FROM management.mps_plans")) == 1001
    assert len(inserts) == 2
    assert all(not item["executemany"] for item in inserts)
    assert all(item["parameter_count"] == 19 for item in inserts)
    assert inserts[0]["statement"] == inserts[1]["statement"]
    assert ledger.archive_tick() is None


def test_archive_rejects_task_identity_already_owned_by_another_job(ledger):
    from sqlalchemy import select
    from ultima_scraper_backend.job_system.storage import _task_to_central_row
    from ultima_scraper_db_archive.execution_models import ExecutionWorkModel
    from ultima_scraper_db_archive.global_db import CentralTaskModel

    job_id = completed_range(ledger, count=1)
    other = Job.create(name="Other archive owner", created_by="test", tasks=[])
    ledger.manifests.create(
        job_id=other.job_id, site="onlyfans", job_config=other.to_dict(),
        selection={"start_id": 2, "end_id": 2, "max_profiles": None},
        proxy_pool=[], site_session_factory=ledger.session_factory,
    )
    with ledger.session_factory() as session:
        work = session.execute(select(ExecutionWorkModel).where(
            ExecutionWorkModel.run_id == job_id,
        )).scalar_one()
        item = Task.from_dict(json.loads(work.payload_json))
        session.execute(CentralTaskModel.__table__.insert(),
                        _task_to_central_row(item, other.job_id))
        session.commit()

    with pytest.raises(ValueError, match="Archived task belongs to another job"):
        ledger.archive_tick()

    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT cursor FROM management.mps_plans WHERE job_id=:job"), {"job": job_id}) == 0
        assert session.scalar(text("SELECT count(*) FROM management.execution_work WHERE run_id=:job"), {"job": job_id}) == 1
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"), {"job": job_id}) == 0


def test_archive_second_page_failure_rolls_back_evidence_and_checkpoint(
    ledger, ledger_engine,
):
    job_id = completed_range(ledger)
    pages = 0

    def fail_second_page(conn, cursor, statement, parameters, context, many):
        nonlocal pages
        if statement.startswith("INSERT INTO management.job_tasks"):
            pages += 1
            if pages == 2:
                raise RuntimeError("second archive page failed")

    event.listen(ledger_engine, "before_cursor_execute", fail_second_page)
    try:
        with pytest.raises(RuntimeError, match="second archive page failed"):
            ledger.archive_tick()
    finally:
        event.remove(ledger_engine, "before_cursor_execute", fail_second_page)
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 0
        assert session.scalar(text("SELECT cursor FROM management.mps_plans")) == 0
        assert session.scalar(text("SELECT count(*) FROM management.execution_work")) == 1001
    assert ledger.archive_tick() == job_id
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 1001
        assert session.scalar(text("SELECT cursor FROM management.mps_plans")) == 1001


def test_archive_preserves_omitted_defaults_and_nullable_evidence(ledger):
    job_id = completed_range(ledger, 4)
    with ledger.session_factory() as session:
        tasks = [Task.from_dict(json.loads(value)) for value in session.execute(text(
            "SELECT p.payload_json FROM management.execution_work w JOIN management.execution_work_payloads p USING(run_id,task_id) ORDER BY candidate"
        )).scalars()]
    rows = [
        {"task_id": task.task_id, "job_id": job_id, "task_type": "scrape",
         "status": task.state.value, "user_id": int(task.user_id)}
        for task in tasks
    ]
    created = datetime(2026, 1, 1, tzinfo=UTC)
    rows[1].update(created_at=created, items_processed=7, message="preserved")
    rows[2].update(created_at=None, items_processed=None, message=None)
    result = ledger.manifests.archive_window(job_id, start=0, end=4, rows=rows)
    assert result["cursor"] == 4
    with ledger.session_factory() as session:
        archived = session.execute(text(
            "SELECT user_id,created_at,items_processed,message FROM management.job_tasks "
            "ORDER BY user_id"
        )).mappings().all()
        assert [row["items_processed"] for row in archived] == [0, 7, 0, 0]
        assert all(row["created_at"] is not None for row in archived)
        assert archived[1]["created_at"] == created
        assert [row["message"] for row in archived] == [None, "preserved", None, None]
