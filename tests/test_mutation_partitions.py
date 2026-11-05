import importlib.util
from pathlib import Path

import ultima_scraper_db_archive

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from ultima_scraper_backend.database.job_partitions import (
    drop_mutation_partition,
    partition_name,
)
from ultima_scraper_backend.database.receipt_retention import ReceiptQueueSnapshot

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def test_partition_migration_keeps_legacy_and_drops_only_requested_job(
    ledger, ledger_engine
):
    submit(ledger, [task()], identity="job-legacy")
    with ledger.session_factory() as session:
        session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_execution_mutations_command ON management.execution_mutations(command_id)"
            )
        )
        session.execute(
            text(
                "INSERT INTO management.execution_mutations VALUES ('job-legacy','task-a','saved','legacy-command')"
            )
        )
        session.commit()
    path = (
        Path(ultima_scraper_db_archive.__file__).parent / "migrations/alembic/versions/a84df9201c76_partition_execution_mutations_by_run.py"
    )
    spec = importlib.util.spec_from_file_location("partition_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with (
        ledger_engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.upgrade()
    submit(ledger, [task("task-new")], identity="job-new")
    submit(ledger, [task("task-other")], identity="job-other")
    with ledger.session_factory() as session:
        session.execute(
            text(
                "INSERT INTO management.execution_mutations VALUES ('job-new','task-new','saved','new-command'),('job-other','task-other','saved','other-command')"
            )
        )
        session.commit()
        assert session.scalar(
            text(
                "SELECT tableoid::regclass::text FROM management.execution_mutations WHERE run_id='job-new'"
            )
        ) == "management." + partition_name("job-new")
        try:
            drop_mutation_partition(session, "job-new")
        except ValueError as exc:
            assert "fenced" in str(exc)
        else:
            raise AssertionError("active job partition must not be dropped")
    assert ledger.delete("job-new", batch_size=1, receipt_queue=ReceiptQueueSnapshot())
    with ledger.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT to_regclass(:name)"),
                {"name": "management." + partition_name("job-new")},
            )
            is None
        )
        assert list(
            session.scalars(
                text(
                    "SELECT command_id FROM management.execution_mutations ORDER BY command_id"
                )
            )
        ) == ["legacy-command", "other-command"]
    assert ledger.delete("job-legacy", batch_size=1, receipt_queue=ReceiptQueueSnapshot())
    with ledger.session_factory() as session:
        assert list(
            session.scalars(
                text("SELECT command_id FROM management.execution_mutations")
            )
        ) == ["other-command"]
