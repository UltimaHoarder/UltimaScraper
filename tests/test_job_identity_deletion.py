"""Large directory purges seek forward and never abandon skipped row locks."""

import importlib.util
import json
from pathlib import Path

import ultima_scraper_db_archive

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, text
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from ultima_scraper_backend.database.job_partitions import purge_identity_page
from ultima_scraper_backend.database.receipt_retention import ReceiptQueueSnapshot
from ultima_scraper_backend.job_system.ledger import ExecutionLedger

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


@pytest.fixture(scope="module")
def partitioned_engine(ledger_engine):
    path = (
        Path(ultima_scraper_db_archive.__file__).parent / "migrations/alembic/versions/c92ea6407b31_partition_all_job_history.py"
    )
    spec = importlib.util.spec_from_file_location("identity_deletion_history", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with ledger_engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    return ledger_engine


@pytest.fixture
def partitioned_ledger(ledger, partitioned_engine):
    with partitioned_engine.begin() as connection:
        connection.execute(text("""TRUNCATE management.job_task_identities,
            management.execution_attempt_identities, management.execution_outbox_identities"""))
    return ledger


@pytest.mark.parametrize("table,directory,owner,key", [
    ("job_tasks", "job_task_identities", "job_id", "task_id"),
    ("execution_attempts", "execution_attempt_identities", "run_id", "token"),
    ("execution_outbox", "execution_outbox_identities", "run_id", "event_id"),
])
def test_identity_cursor_revisits_locked_rows_and_preserves_other_jobs(
    partitioned_ledger, partitioned_engine, table, directory, owner, key,
):
    ledger = partitioned_ledger
    values = [1, 2, 3, 4] if key == "event_id" else ["a", "b", "c", "d"]
    with ledger.session_factory() as session:
        extra_columns = ",task_id,number" if key == "token" else ""
        extra_values = ",'task',1" if key == "token" else ""
        for value in values:
            session.execute(text(f"""INSERT INTO management.{directory}
                ({owner},{key}{extra_columns}) VALUES (:run,:key{extra_values})"""),
                {"run": "purge-me" if value != values[-1] else "keep-me", "key": value})
        session.commit()

    with partitioned_engine.connect() as blocker:
        blocker.execute(text(f"SELECT {key} FROM management.{directory} WHERE {key}=:key FOR UPDATE"),
                        {"key": values[0]})
        with ledger.session_factory() as session:
            assert purge_identity_page(session, table, "purge-me", 2) == (2, True, values[2])
            session.commit()
        with ledger.session_factory() as session:
            # A locked row before the cursor must force a rewind, never a
            # completed stage that would leave a global identity orphaned.
            assert purge_identity_page(session, table, "purge-me", 2, after=values[2]) == (0, True, None)
            session.commit()
    with ledger.session_factory() as session:
        assert purge_identity_page(session, table, "purge-me", 2) == (1, False, None)
        session.commit()
        assert list(session.scalars(text(f"SELECT {key} FROM management.{directory}"))) == [values[-1]]


def test_job_deletion_commits_and_resumes_the_identity_cursor(partitioned_ledger, partitioned_engine):
    ledger = partitioned_ledger
    submit(ledger, [task()], identity="job-seek")
    with ledger.session_factory() as session:
        session.execute(text("""INSERT INTO management.job_task_identities (job_id,task_id)
            SELECT 'job-seek','identity-' || lpad(n::text,6,'0') FROM generate_series(1,12) n"""))
        session.execute(text("""INSERT INTO management.job_task_identities (job_id,task_id)
            VALUES ('job-keep','keep-identity')"""))
        session.commit()

    def interrupt(table, rows):
        if table == "job_tasks":
            with ledger.session_factory() as session:
                checkpoint = json.loads(session.scalar(text(
                    "SELECT config_json FROM management.execution_runs WHERE run_id='job-seek'"
                )))["metadata"]["deletion_progress"]
            if checkpoint.get("identity_cursor") is not None:
                raise RuntimeError("stop after committed identity page")

    with pytest.raises(RuntimeError, match="committed identity page"):
        ledger.delete("job-seek", batch_size=3, progress=interrupt, receipt_queue=ReceiptQueueSnapshot())
    with ledger.session_factory() as session:
        saved = json.loads(session.scalar(text(
            "SELECT config_json FROM management.execution_runs WHERE run_id='job-seek'"
        )))["metadata"]["deletion_progress"]
    assert saved["identity_cursor"] == "identity-000003"
    assert saved["completed_stages"] == 5

    seeks = []
    prefix_checks = []

    def observe(_conn, _cursor, statement, parameters, _context, _many):
        if "SELECT ctid FROM management.job_task_identities" in statement:
            seeks.append(parameters.get("after"))
        if "SELECT EXISTS(SELECT 1 FROM management.job_task_identities" in statement:
            prefix_checks.append(statement)

    event.listen(partitioned_engine, "before_cursor_execute", observe)
    try:
        fresh = ExecutionLedger(ledger.session_factory)
        # Each pass yields after its committed batch, just like the service.
        for _ in range(20):
            if fresh.delete("job-seek", batch_size=3, time_budget=0, receipt_queue=ReceiptQueueSnapshot()):
                break
        else:
            pytest.fail("deletion failed to finish from the checkpoint")
    finally:
        event.remove(partitioned_engine, "before_cursor_execute", observe)
    assert seeks[:3] == ["identity-000003", "identity-000006", "identity-000009"]
    assert len(prefix_checks) == 1
    with ledger.session_factory() as session:
        assert list(session.scalars(text("SELECT task_id FROM management.job_task_identities"))) == ["keep-identity"]
        assert session.scalar(text("SELECT run_id FROM management.execution_runs WHERE run_id='job-seek'")) is None


def test_identity_cursor_rolls_back_with_a_failed_checkpoint(partitioned_ledger, monkeypatch):
    from psycopg.errors import SerializationFailure
    from sqlalchemy.exc import OperationalError

    ledger = partitioned_ledger
    submit(ledger, [task()], identity="job-rollback")
    with ledger.session_factory() as session:
        session.execute(text("""INSERT INTO management.job_task_identities (job_id,task_id)
            SELECT 'job-rollback','identity-' || n FROM generate_series(1,4) n"""))
        session.commit()
    save = ledger._save_deletion_progress
    checkpoints = []

    def fail_once(run_id, value, **kwargs):
        if value.get("table") == "job_tasks" and value.get("identity_cursor"):
            checkpoints.append(value["identity_cursor"])
            if len(checkpoints) == 1:
                raise OperationalError("checkpoint", {}, SerializationFailure("retry"))
        return save(run_id, value, **kwargs)

    monkeypatch.setattr(ledger, "_save_deletion_progress", fail_once)
    assert ledger.delete("job-rollback", batch_size=2, receipt_queue=ReceiptQueueSnapshot())
    assert checkpoints[:2] == ["identity-2", "identity-2"]
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_task_identities")) == 0
