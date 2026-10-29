"""Native direct/logical receipt lookup preserves replay and failure semantics."""

import json
from dataclasses import replace

import pytest
from sqlalchemy import event, insert, select, text
from test_execution_ledger import ledger, ledger_engine, postgres_engine
from test_history_partition_admission import partitioned_engine
from test_ledger_writer_batch_fences import command, owned_batch
from ultima_scraper_backend.database import write_receipts
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteRejected,
    DatabaseWriteResult,
)
from ultima_scraper_db_archive.execution_models import ExecutionMutationModel
from ultima_scraper_db_archive.global_db import DatabaseWriteReceiptModel

__all__ = ["ledger", "ledger_engine", "postgres_engine", "partitioned_engine"]


def receipt_row(
    command_id,
    *,
    payload=None,
    operation="upsert_user",
    site="onlyfans",
    post_commit=None,
    success=True,
):
    result = DatabaseWriteResult(
        command_id=command_id,
        success=success,
        payload=payload or {"saved": command_id},
        error=None if success else "retained failure",
        completed_at="2026-10-04T03:00:00+00:00",
    )
    return {
        "command_id": command_id,
        "operation": operation,
        "site": site,
        "result_json": result.to_json(),
        "post_commit_json": json.dumps(post_commit) if post_commit else None,
    }


@pytest.mark.parametrize("run_ids", [["job-test"], ["job-test", "job-second"]])
def test_receipt_lookup_locks_only_requested_mutation_partitions(ledger, partitioned_engine, run_ids):
    from test_execution_ledger import submit, task
    from ultima_scraper_backend.database.job_partitions import ensure_mutation_partition

    for run_id in run_ids:
        submit(ledger, [task(run_id + "-task")], identity=run_id)
    with ledger.session_factory() as session:
        for run_id in run_ids:
            ensure_mutation_partition(session, run_id)
        session.commit()
    with partitioned_engine.begin() as connection:
        for number in range(40):
            connection.execute(text(
                f"CREATE TABLE IF NOT EXISTS management.execution_mutations_probe_{number} "
                f"PARTITION OF management.execution_mutations FOR VALUES IN ('job-probe-{number}')"
            ))
    identities = {run_id: (run_id, run_id + "-task", "save") for run_id in run_ids}
    identities["unfenced"] = None
    with ledger.session_factory() as session:
        assert write_receipts._read_execution_receipts(session, list(identities), identities) == ({}, {})
        locked = session.scalar(text("""
            SELECT count(*) FROM pg_locks locks
            JOIN pg_inherits inheritance ON inheritance.inhrelid=locks.relation
            WHERE locks.pid=pg_backend_pid()
              AND inheritance.inhparent='management.execution_mutations'::regclass
        """))
        assert locked <= len(run_ids)


def test_lookup_retains_direct_logical_and_missing_receipts(ledger):
    owned_batch(ledger, 1)
    requested = ["direct", "alias", "both", "precedence", "missing", "new", "unfenced"]
    identities = {
        key: None if key == "unfenced" else ("job-test", key, "save")
        for key in requested
    }
    with ledger.session_factory() as session:
        session.execute(
            insert(DatabaseWriteReceiptModel),
            [
                receipt_row(key)
                for key in (
                    "direct",
                    "old",
                    "both",
                    "precedence",
                    "missing",
                    "unfenced",
                )
            ],
        )
        session.execute(
            insert(ExecutionMutationModel),
            [
                {
                    "run_id": "job-test",
                    "task_id": task_id,
                    "mutation_key": "save",
                    "command_id": command_id,
                }
                for task_id, command_id in (
                    ("alias", "old"),
                    ("both", "both"),
                    ("precedence", "old"),
                    ("missing", "absent-receipt"),
                )
            ],
        )
        session.commit()
    with ledger.session_factory() as session:
        committed, existing = write_receipts._read_execution_receipts(
            session, requested, identities
        )
    assert committed == {
        ("job-test", task_id, "save"): command_id
        for task_id, command_id in (
            ("alias", "old"),
            ("both", "both"),
            ("precedence", "old"),
            ("missing", "absent-receipt"),
        )
    }
    assert set(existing) == {
        "direct",
        "old",
        "both",
        "precedence",
        "missing",
        "unfenced",
    }
    for key, snapshot in existing.items():
        assert DatabaseWriteResult.from_json(snapshot.result_json).payload == {
            "saved": key
        }
    # The logical mapping keeps precedence even when its receipt is absent;
    # an unrelated direct receipt cannot silently replace that missing outcome.
    assert committed[identities["missing"]] not in existing


@pytest.mark.parametrize("count", [1, 25, 100])
def test_fenced_batch_uses_one_receipt_select_after_separate_lock(
    ledger, ledger_engine, count
):
    owned = owned_batch(ledger, count)
    commands = [command(item) for item in owned]
    statements = []

    def executed(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    with ledger.session_factory() as session:
        event.listen(ledger_engine, "after_cursor_execute", executed)
        try:
            with write_receipts.receipt_batch(session, commands, {}) as pending:
                assert pending == commands
                entry_statements = list(statements)
                # Only lookup/fencing is under test; roll back before results.
                raise RuntimeError("rollback fixture")
        except RuntimeError as error:
            assert str(error) == "rollback fixture"
        finally:
            event.remove(ledger_engine, "after_cursor_execute", executed)
    assert len(entry_statements) == 5
    assert "pg_try_advisory_xact_lock" in entry_statements[0]
    assert "execution_mutations" in entry_statements[1]
    assert "database_write_receipts" in entry_statements[1]
    assert (
        "FOR SHARE" in entry_statements[2] and "execution_runs" in entry_statements[2]
    )
    assert (
        "FOR SHARE" in entry_statements[3] and "execution_work" in entry_statements[3]
    )
    assert "clock_timestamp" in entry_statements[4]


@pytest.mark.parametrize(
    "field,value", [("operation", "finalize_download"), ("site", "fansly")]
)
def test_logical_replay_rejects_operation_or_site_reuse(ledger, field, value):
    item = command(owned_batch(ledger, 1)[0])
    with ledger.session_factory() as session:
        row = receipt_row("old")
        row[field] = value
        session.execute(insert(DatabaseWriteReceiptModel), [row])
        session.execute(
            insert(ExecutionMutationModel),
            [
                {
                    "run_id": item.execution_attempt["run_id"],
                    "task_id": item.execution_attempt["task_id"],
                    "mutation_key": item.execution_key,
                    "command_id": "old",
                }
            ],
        )
        session.commit()
    with (
        ledger.session_factory() as session,
        pytest.raises(ValueError, match="different operation or site"),
        write_receipts.receipt_batch(session, [item], {}),
    ):
        pytest.fail("invalid replay admitted")


def test_same_batch_logical_aliases_apply_once_and_replay(ledger):
    first = command(owned_batch(ledger, 1)[0])
    second = replace(first, command_id="same-batch-alias")
    with ledger.session_factory() as session:
        results = {}
        with write_receipts.receipt_batch(session, [first, second], results) as pending:
            assert pending == [first]
            results[first.command_id] = {"applied": 1}
        session.commit()
        assert (
            session.execute(select(ExecutionMutationModel)).scalars().one().command_id
            == first.command_id
        )
    assert results[second.command_id] == {"applied": 1}
    with ledger.session_factory() as session:
        results = {}
        with write_receipts.receipt_batch(session, [first, second], results) as pending:
            assert pending == []
    assert results == {
        first.command_id: {"applied": 1},
        second.command_id: {"applied": 1},
    }


def test_logical_receipt_preserves_retained_failure(ledger):
    item = command(owned_batch(ledger, 1)[0])
    with ledger.session_factory() as session:
        session.execute(
            insert(DatabaseWriteReceiptModel), [receipt_row("failed", success=False)]
        )
        session.execute(
            insert(ExecutionMutationModel),
            [
                {
                    "run_id": item.execution_attempt["run_id"],
                    "task_id": item.execution_attempt["task_id"],
                    "mutation_key": item.execution_key,
                    "command_id": "failed",
                }
            ],
        )
        session.commit()
    with (
        ledger.session_factory() as session,
        pytest.raises(DatabaseWriteRejected, match="retained failure"),
        write_receipts.receipt_batch(session, [item], {}),
    ):
        pytest.fail("retained failure was admitted")
