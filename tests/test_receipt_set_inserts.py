"""Native receipts keep transaction atomicity with set-oriented inserts."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import event, text
from test_execution_ledger import ledger, ledger_engine, postgres_engine
from test_ledger_writer_batch_fences import command, owned_batch
from ultima_scraper_backend.database.write_receipts import receipt_batch

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def test_receipt_insert_protocol(ledger):
    commands = [
        replace(command(c), created_at=datetime.now(UTC).isoformat())
        for c in owned_batch(ledger, 100)
    ]
    inserts = []
    with ledger.session_factory() as session:
        engine = session.get_bind()

    def capture(conn, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO management.") and (
            "database_write_receipts" in statement or "execution_mutations" in statement
        ):
            inserts.append(
                {
                    "table": "receipts"
                    if "database_write_receipts" in statement
                    else "mutations",
                    "executemany": many,
                    "parameter_sets": len(parameters) if many else 1,
                }
            )

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with ledger.session_factory() as session:
            results = {}
            with receipt_batch(session, commands, results) as pending:
                for item in pending:
                    results[item.command_id] = {"saved": True}
            session.commit()
        with ledger.session_factory() as session:
            assert (
                session.scalar(
                    text("SELECT count(*) FROM management.database_write_receipts")
                )
                == 100
            )
            assert (
                session.scalar(
                    text("SELECT count(*) FROM management.execution_mutations")
                )
                == 100
            )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    output = os.environ.get("USR_RECEIPT_PROTOCOL_REPORT")
    if output:
        Path(output).write_text(json.dumps(inserts, indent=2))
    assert {r["table"] for r in inserts} == {"receipts", "mutations"}
    assert len(inserts) == 2
    assert all(not row["executemany"] for row in inserts)


def test_receipt_transaction_rolls_back_all_rows(ledger):
    commands = [
        replace(command(c), created_at=datetime.now(UTC).isoformat())
        for c in owned_batch(ledger, 3)
    ]
    with ledger.session_factory() as session:
        results = {}
        with pytest.raises(RuntimeError, match="after receipt finalization"):
            with receipt_batch(session, commands, results) as pending:
                for item in pending:
                    results[item.command_id] = {"saved": True}
            raise RuntimeError("after receipt finalization")
        session.rollback()
    with ledger.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.database_write_receipts")
            )
            == 0
        )
        assert (
            session.scalar(text("SELECT count(*) FROM management.execution_mutations"))
            == 0
        )


def test_receipt_insert_pages_large_unfenced_batches(ledger):
    original = replace(
        command(owned_batch(ledger, 1)[0]),
        execution_attempt=None,
        execution_key=None,
        created_at=datetime.now(UTC).isoformat(),
    )
    commands = [replace(original, command_id=f"page-{i}") for i in range(1001)]
    statements = []
    with ledger.session_factory() as session:
        engine = session.get_bind()

    def capture(conn, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO management.database_write_receipts"):
            assert not many
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with ledger.session_factory() as session:
            results = {}
            with receipt_batch(session, commands, results) as pending:
                results.update({item.command_id: {"saved": True} for item in pending})
            session.commit()
        assert len(statements) == 2
        with ledger.session_factory() as session:
            assert (
                session.scalar(
                    text("SELECT count(*) FROM management.database_write_receipts")
                )
                == 1001
            )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
