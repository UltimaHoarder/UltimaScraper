"""Deletion leases must not retain relation locks across partition DDL."""

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from ultima_scraper_backend.services import job_deletion
from ultima_scraper_backend.database.receipt_retention import ReceiptQueueSnapshot

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def test_background_lease_does_not_block_partition_disposal(
    ledger, ledger_engine, monkeypatch
):
    submit(ledger, [task()], identity="job-delete-lock")
    path = (
        Path(__file__).resolve().parents[2]
        / "UltimaDatabases/UltimaScraperDBArchive/ultima_scraper_db_archive/migrations/alembic/versions/c92ea6407b31_partition_all_job_history.py"
    )
    spec = importlib.util.spec_from_file_location("history_lock_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with (
        ledger_engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.upgrade()
    ledger.begin_delete("job-delete-lock")
    monkeypatch.setattr(job_deletion, "ExecutionLedger", lambda factory: ledger)
    # A persistent global outbox reader blocks partition DDL. Keep its
    # transaction open across a cleanup pass to exercise the real timeout.
    with ledger_engine.connect() as blocker:
        blocker.execute(
            text("SELECT event_id FROM management.execution_outbox LIMIT 1")
        )
        assert job_deletion.cleanup_pending(ledger.session_factory, receipt_queue=ReceiptQueueSnapshot()) == []
        with ledger.session_factory() as session:
            config = json.loads(
                session.scalar(
                    text(
                        "SELECT config_json FROM management.execution_runs WHERE run_id='job-delete-lock'"
                    )
                )
            )
            checkpoint = config["metadata"]["deletion_progress"]
            assert checkpoint["completed_stages"] == 0
            assert checkpoint["partitions_dropped"] == 0
            assert (
                checkpoint["error"]
                == "Waiting for database lock on execution_outbox; retrying automatically."
            )
            assert config["metadata"]["deletion_pending"] is True
    assert job_deletion.cleanup_pending(ledger.session_factory, receipt_queue=ReceiptQueueSnapshot()) == ["job-delete-lock"]

    # A reader lasting longer than the former 250 ms allowance should drain
    # within one pass instead of forcing another worker cycle.
    submit(ledger, [task("task-short")], identity="job-short-reader")
    ledger.begin_delete("job-short-reader")
    ready = Event()

    def short_reader():
        with ledger_engine.connect() as connection:
            connection.execute(
                text("SELECT event_id FROM management.execution_outbox LIMIT 1")
            )
            ready.set()
            Event().wait(0.6)

    with ThreadPoolExecutor(max_workers=1) as executor:
        reader = executor.submit(short_reader)
        assert ready.wait(5)
        assert job_deletion.cleanup_pending(ledger.session_factory, receipt_queue=ReceiptQueueSnapshot()) == [
            "job-short-reader"
        ]
        reader.result(timeout=5)
