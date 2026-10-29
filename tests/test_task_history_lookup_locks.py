"""Task reads and status writes lock only their job's history partition."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, event, select, text, update
from test_database_write_executor import _command
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from ultima_scraper_backend.database.job_partitions import ensure_history_partition
from ultima_scraper_backend.database.mps_definitions import MPSDefinitionBudgetExceeded
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
from ultima_scraper_db_archive.global_db import (
    CentralTaskModel,
    MPSPlanModel,
    MPSTaskDefinitionModel,
)

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def add_unrelated_partitions(engine):
    with engine.begin() as connection:
        for number in range(40):
            connection.execute(text(
                f"CREATE TABLE IF NOT EXISTS management.job_tasks_probe_{number} "
                f"PARTITION OF management.job_tasks FOR VALUES IN ('job-probe-{number}')"
            ))


@pytest.mark.parametrize("operation", ["read", "write", "missing", "wrong_job"])
def test_task_point_operations_do_not_lock_unrelated_job_partitions(
    ledger, ledger_engine, monkeypatch, operation
):
    from ultima_scraper_db_archive import global_db

    submit(ledger, [task("wanted")], identity="job-lookup")
    submit(ledger, [task("other-task")], identity="job-other")
    with ledger.session_factory() as session:
        manifests = {
            job_id: json.loads(selection).get("task_manifest_id") or ""
            for job_id, selection in session.execute(select(
                MPSPlanModel.job_id, MPSPlanModel.selection_json,
            )).all()
        }
        ensure_history_partition(session, "job-lookup", "job_tasks")
        history = task("wanted")
        history.job_id = "job-lookup"
        session.add(CentralTaskModel(
            task_id="wanted", job_id="job-lookup", task_type="scrape_user",
            status="pending", definition_json=json.dumps(history.to_dict()),
        ))
        session.commit()
    add_unrelated_partitions(ledger_engine)

    locked_leaves = []

    def measure(connection, _cursor, statement, _parameters, _context, _many):
        if "FROM management.job_tasks" not in statement:
            return
        locked_leaves.append(connection.scalar(text("""
            SELECT count(*) FROM pg_locks locks
            JOIN pg_inherits inheritance ON inheritance.inhrelid=locks.relation
            WHERE locks.pid=pg_backend_pid()
              AND inheritance.inhparent='management.job_tasks'::regclass
        """)))

    event.listen(ledger_engine, "after_cursor_execute", measure)
    try:
        if operation == "read":
            assert ledger.task("job-lookup", "wanted")["state"] == "pending"
        else:
            monkeypatch.setattr(global_db, "global_session", ledger.session_factory)
            requested_job = "job-other" if operation == "wrong_job" else "job-lookup"
            requested_task = "absent" if operation == "missing" else "wanted"
            command = _command(
                "point-status-" + operation, DatabaseWriteOperation.SYNC_TASK_STATUS,
                {"job_id": requested_job, "task_id": requested_task,
                 "mps_task_manifest": manifests[requested_job],
                 "status": "running", "event_time": datetime.now(UTC).isoformat()},
                site=None,
            )
            result = PostgreSQLWriteExecutor._sync_task_statuses([command])
            assert result[command.command_id]["synced"] is (operation == "write")
        assert locked_leaves and max(locked_leaves) <= 1
    finally:
        event.remove(ledger_engine, "after_cursor_execute", measure)
    with ledger.session_factory() as session:
        status = session.scalar(select(CentralTaskModel.status).where(
            CentralTaskModel.job_id == "job-lookup", CentralTaskModel.task_id == "wanted",
        ))
    assert status == ("running" if operation == "write" else "pending")


@pytest.mark.parametrize("separate_manifest", [True, False])
@pytest.mark.parametrize("dependency_status", ["completed", "failed", "pending", None])
def test_ready_page_prunes_history_for_archived_dependencies(
    ledger, ledger_engine, separate_manifest, dependency_status
):
    prerequisite = task("prerequisite")
    dependent = task("dependent", dependencies=[prerequisite.task_id])
    submit(ledger, [prerequisite, dependent], identity="job-dependency")
    with ledger.session_factory() as session:
        plan = session.get(MPSPlanModel, "job-dependency")
        manifest = json.loads(plan.selection_json)["task_manifest_id"]
        session.execute(delete(MPSTaskDefinitionModel).where(
            MPSTaskDefinitionModel.manifest_id == manifest,
            MPSTaskDefinitionModel.task_id == prerequisite.task_id,
        ))
        if not separate_manifest:
            session.execute(update(MPSTaskDefinitionModel).where(
                MPSTaskDefinitionModel.manifest_id == manifest,
            ).values(manifest_id=plan.job_id))
            manifest = plan.job_id
        ensure_history_partition(session, plan.job_id, "job_tasks")
        if dependency_status is not None:
            session.add(CentralTaskModel(
                task_id=prerequisite.task_id, job_id=plan.job_id,
                task_type="scrape_user", status=dependency_status,
            ))
        session.commit()
    add_unrelated_partitions(ledger_engine)

    with ledger.session_factory() as session:
        rows = ledger.manifests.definitions.ready_page(
            manifest, limit=1, byte_limit=65536, db_session=session,
        )
        if dependency_status in {"completed", "failed"}:
            assert [row["task_id"] for row in rows] == [dependent.task_id]
            assert rows[0]["dependency_failed"] is (dependency_status == "failed")
        else:
            assert rows == []
        locked = session.scalar(text("""
            SELECT count(*) FROM pg_locks locks
            JOIN pg_inherits inheritance ON inheritance.inhrelid=locks.relation
            WHERE locks.pid=pg_backend_pid()
              AND inheritance.inhparent='management.job_tasks'::regclass
        """))
        assert locked <= 1


def test_ready_page_keeps_byte_prefix_selection_and_missing_manifest_semantics(
    ledger, ledger_engine
):
    tasks = [task(f"page-{number}") for number in range(3)]
    submit(ledger, tasks, identity="job-page")
    add_unrelated_partitions(ledger_engine)
    with ledger.session_factory() as session:
        manifest = json.loads(session.get(MPSPlanModel, "job-page").selection_json)["task_manifest_id"]
        sizes = session.execute(text("""
            SELECT octet_length(task_json) FROM management.mps_task_definitions
            WHERE manifest_id=:manifest ORDER BY ordinal
        """), {"manifest": manifest}).scalars().all()
        ready = ledger.manifests.definitions.ready_page
        rows = ready(manifest, limit=3, byte_limit=sum(sizes[:2]), db_session=session)
        assert [row["task_id"] for row in rows] == [item.task_id for item in tasks[:2]]
        with pytest.raises(MPSDefinitionBudgetExceeded):
            ready(manifest, limit=3, byte_limit=sizes[0] - 1, db_session=session)
        rows = ready(
            manifest, limit=3, exclude_task_ids=[tasks[0].task_id],
            only_task_ids=[tasks[0].task_id, tasks[2].task_id], db_session=session,
        )
        assert [row["task_id"] for row in rows] == [tasks[2].task_id]
    with ledger.session_factory() as session:
        assert ready("missing-manifest", limit=3, db_session=session) == []
        assert session.scalar(text("""
            SELECT count(*) FROM pg_locks locks
            JOIN pg_inherits inheritance ON inheritance.inhrelid=locks.relation
            WHERE locks.pid=pg_backend_pid()
              AND inheritance.inhparent='management.job_tasks'::regclass
        """)) == 0
