"""Receipt expiry preserves queued work, job ownership, and recovery authority."""

import importlib.util
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import insert, select, text
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from test_ledger_writer_batch_fences import command, owned_batch
from test_writer_receipt_lookup import receipt_row
from ultima_scraper_backend.database.receipt_retention import (
    pending_command_ids,
    purge_receipts,
)
from ultima_scraper_backend.database.write_receipts import receipt_batch
from ultima_scraper_db_archive.execution_models import ExecutionMutationModel
from ultima_scraper_db_archive.global_db import DatabaseWriteReceiptModel

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def test_purge_preserves_recovery_and_retained_ownership(ledger):
    submit(ledger, [task()], identity="job-retained")
    old = datetime.now(UTC) - timedelta(days=8)
    rows = []
    for key in (
        "expired",
        "queued",
        "recent",
        "failure",
        "authority",
        "migration",
        "retained",
        "referenced",
        "deleted-owner",
    ):
        row = receipt_row(key)
        row.update(
            committed_at=old,
            run_id=None,
            failed_command_json=None,
            post_commit_json=None,
        )
        if key == "recent":
            row["committed_at"] = datetime.now(UTC)
        if key == "failure":
            row["failed_command_json"] = "{}"
        if key == "authority":
            row["post_commit_json"] = "{}"
        if key == "migration":
            row["operation"] = "migration_import_outcome"
        if key == "retained":
            row["run_id"] = "job-retained"
        if key == "deleted-owner":
            row["run_id"] = "job-gone"
        rows.append(row)
    with ledger.session_factory() as session:
        session.execute(insert(DatabaseWriteReceiptModel), rows)
        session.execute(
            insert(ExecutionMutationModel),
            {
                "run_id": "job-retained",
                "task_id": "task-a",
                "mutation_key": "saved",
                "command_id": "referenced",
            },
        )
        session.commit()
    inspected = purge_receipts(
        protected_ids={"queued"}, dry_run=True, session_factory=ledger.session_factory
    )
    # Receipts that carried migration authority payloads now expire too.
    assert inspected.selected == 3 and inspected.deleted == 0
    result = purge_receipts(
        protected_ids={"queued"}, batch_size=1, session_factory=ledger.session_factory
    )
    assert result.deleted == 1
    result = purge_receipts(
        protected_ids={"queued"}, session_factory=ledger.session_factory
    )
    assert result.deleted == 2
    with ledger.session_factory() as session:
        remaining = set(session.scalars(select(DatabaseWriteReceiptModel.command_id)))
    assert remaining == {
        "queued",
        "recent",
        "failure",
        "migration",
        "retained",
        "referenced",
    }


def test_purge_defers_writer_overlap(ledger):
    row = receipt_row("busy")
    row["committed_at"] = datetime.now(UTC) - timedelta(days=8)
    with ledger.session_factory() as session:
        session.execute(insert(DatabaseWriteReceiptModel), row)
        session.commit()
    with ledger.session_factory() as owner:
        owner.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended('database-write:busy',0))"
            )
        )
        result = purge_receipts(
            protected_ids=set(), session_factory=ledger.session_factory
        )
        assert result.busy and result.deleted == 0
    assert (
        purge_receipts(
            protected_ids=set(), session_factory=ledger.session_factory
        ).deleted
        == 1
    )


@pytest.mark.parametrize(
    "state,draining",
    [("pending", False), ("running", False), ("running", True), ("paused", False)],
)
def test_idle_cleanup_yields_during_job_ramp_and_drain(ledger, state, draining):
    submit(ledger, [task()], identity="job-active")
    if state == "paused":
        ledger.tick()
        # Pausing lets claimed tasks finish; they still execute.
        with ledger.session_factory() as session:
            session.execute(text(
                "UPDATE management.execution_work SET state='running' WHERE run_id='job-active'"
            ))
            session.commit()
    row = receipt_row("old-unowned")
    row["committed_at"] = datetime.now(UTC) - timedelta(days=8)
    with ledger.session_factory() as session:
        session.execute(insert(DatabaseWriteReceiptModel), row)
        session.execute(
            text(
                "UPDATE management.execution_runs SET state=:state WHERE run_id='job-active'"
            ),
            {"state": state},
        )
        if draining:
            session.execute(
                text("DELETE FROM management.execution_work WHERE run_id='job-active'")
            )
        session.commit()
    blocked = purge_receipts(
        protected_ids=set(),
        mode="idle",
        cursor="(0,0)",
        session_factory=ledger.session_factory,
    )
    assert (
        blocked.paused_reason == "execution_active"
        and blocked.deleted == 0
        and blocked.next_cursor is None
    )
    ledger.control("job-active", "cancel")
    assert (
        purge_receipts(
            protected_ids=set(), mode="idle", session_factory=ledger.session_factory
        ).deleted
        == 1
    )


def test_idle_cleanup_waits_for_writer_queue_without_sql():
    def forbidden():
        pytest.fail("queued writes must pause cleanup before SQL admission")

    result = purge_receipts(
        protected_ids={"accepted"}, mode="idle", session_factory=forbidden
    )
    assert result.paused_reason == "write_queue_active"
    assert (
        purge_receipts(
            protected_ids=set(), mode="paused", session_factory=forbidden
        ).paused_reason
        == "operator_paused"
    )


def test_cutoff_cannot_shorten_recovery_window():
    with pytest.raises(ValueError, match="recovery window"):
        purge_receipts(protected_ids=set(), cutoff=datetime.now(UTC))


def test_sweep_cursor_purges_all_eligible_rows_in_bounded_batches(ledger):
    rows = []
    for i in range(5):
        row = receipt_row(f"sweep-{i}")
        row["committed_at"] = datetime.now(UTC) - timedelta(days=8)
        rows.append(row)
    with ledger.session_factory() as session:
        session.execute(insert(DatabaseWriteReceiptModel), rows)
        session.commit()
    cursor = "(0,0)"
    total = 0
    for _ in range(10):
        result = purge_receipts(
            protected_ids={"sweep-1"},
            batch_size=2,
            cursor=cursor,
            session_factory=ledger.session_factory,
        )
        total += result.deleted
        cursor = result.next_cursor
        if result.finished:
            break
    assert total == 4 and result.finished
    with ledger.session_factory() as session:
        assert list(session.scalars(select(DatabaseWriteReceiptModel.command_id))) == [
            "sweep-1"
        ]
    empty = purge_receipts(
        protected_ids={"sweep-1"},
        cursor="(0,0)",
        session_factory=ledger.session_factory,
    )
    assert empty.finished and empty.deleted == 0


def test_writer_keeps_owner_and_replays_old_receipts(ledger):
    item = replace(
        command(owned_batch(ledger, 1)[0]), created_at=datetime.now(UTC).isoformat()
    )
    with ledger.session_factory() as session:
        results = {}
        with receipt_batch(session, [item], results) as pending:
            assert pending == [item]
            results[item.command_id] = {"saved": True}
        session.commit()
        assert (
            session.get(DatabaseWriteReceiptModel, item.command_id).run_id == "job-test"
        )
    expired = replace(
        item, created_at=(datetime.now(UTC) - timedelta(days=8)).isoformat()
    )
    with (
        ledger.session_factory() as session,
        receipt_batch(session, [expired], {}) as pending,
    ):
        assert pending == []
    # Without a receipt an old idempotent upsert simply runs again.
    fresh_old = replace(
        expired, command_id="new-old", execution_attempt=None, execution_key=None
    )
    results = {}
    with (
        ledger.session_factory() as session,
        receipt_batch(session, [fresh_old], results) as pending,
    ):
        assert pending == [fresh_old]
        results[fresh_old.command_id] = {"saved": True}


@pytest.mark.asyncio
async def test_queue_inventory_fails_closed():
    manager = SimpleNamespace(
        client=SimpleNamespace(
            get=AsyncMock(return_value=None),
            xrange=AsyncMock(return_value=[("one", {}), ("two", {})]),
        )
    )
    with pytest.raises(RuntimeError, match="safety budget"):
        await pending_command_ids(manager, max_entries=1)
    manager.client.xrange.return_value = [("broken", {})]
    with pytest.raises(ValueError, match="no command field"):
        await pending_command_ids(manager)


@pytest.mark.asyncio
async def test_retention_cycle_pause_preserves_cursor_and_reports_status(monkeypatch):
    from ultima_scraper_backend.database import receipt_retention, threads

    monkeypatch.setattr(receipt_retention, "retention_mode", lambda: "idle")
    monkeypatch.setattr(
        receipt_retention, "pending_command_ids", AsyncMock(return_value=set())
    )
    runner = AsyncMock(
        return_value=receipt_retention.ReceiptPurgeResult(
            0, 0, paused_reason="execution_active"
        )
    )
    monkeypatch.setattr(threads, "run_database_call", runner)
    client = SimpleNamespace(
        get=AsyncMock(return_value=b"(99,0)"),
        set=AsyncMock(),
        hset=AsyncMock(),
        expire=AsyncMock(),
    )
    assert (
        await receipt_retention.run_retention_cycle(SimpleNamespace(client=client)) == 0
    )
    assert runner.await_args.kwargs["cursor"] == "(99,0)"
    client.set.assert_not_awaited()
    status = client.hset.await_args.kwargs["mapping"]
    assert (
        status["status"] == "paused" and status["paused_reason"] == "execution_active"
    )
    assert status["deleted"] == status["batches"] == 0


def test_retention_migration_roundtrip(ledger_engine):
    path = (
        Path(__file__).resolve().parents[2]
        / "UltimaDatabases/UltimaScraperDBArchive/ultima_scraper_db_archive/migrations/alembic/versions/e761bc24a908_add_write_receipt_retention.py"
    )
    spec = importlib.util.spec_from_file_location("receipt_retention_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with ledger_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            with context.begin_transaction():
                migration.downgrade()
            with context.begin_transaction():
                migration.upgrade()
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_index WHERE indexrelid IN ('management.idx_execution_mutations_command'::regclass,'management.idx_write_receipts_age'::regclass,'management.idx_write_receipts_run'::regclass) AND indisvalid"
                    )
                )
                == 3
            )


def test_idle_cleanup_runs_while_a_paused_run_has_nothing_in_flight(ledger):
    submit(ledger, [task()], identity="job-paused")
    ledger.tick()
    row = receipt_row("old-unowned")
    row["committed_at"] = datetime.now(UTC) - timedelta(days=8)
    with ledger.session_factory() as session:
        session.execute(insert(DatabaseWriteReceiptModel), row)
        session.execute(text(
            "UPDATE management.execution_runs SET state='paused' WHERE run_id='job-paused'"
        ))
        session.commit()
        assert session.scalar(text(
            "SELECT count(*) FROM management.execution_work "
            "WHERE run_id='job-paused' AND state='queued'"
        )) == 1
    result = purge_receipts(
        protected_ids=set(), mode="idle", session_factory=ledger.session_factory
    )
    assert result.paused_reason is None and result.deleted == 1
