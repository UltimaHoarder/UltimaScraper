"""Explicit job deletion disposes of owned receipts after writer recovery drains."""

import asyncio
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import ultima_scraper_db_archive
from types import SimpleNamespace
from threading import Event
from unittest.mock import AsyncMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, insert, select, text
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from test_ledger_writer_batch_fences import command, owned_batch
from test_writer_receipt_lookup import receipt_row
from ultima_scraper_backend.database import write_receipts
from ultima_scraper_backend.database.job_receipts import purge_job_receipts
from ultima_scraper_backend.database.receipt_retention import ReceiptQueueSnapshot, pending_write_inventory
from ultima_scraper_backend.database.write_queue import DatabaseWriteResult
from ultima_scraper_backend.job_system.ledger import ExecutionLedger, StaleAttempt
from ultima_scraper_db_archive.execution_models import ExecutionMutationModel
from ultima_scraper_db_archive.global_db import DatabaseWriteReceiptModel

__all__ = ["ledger", "ledger_engine", "postgres_engine"]
EMPTY_QUEUE = ReceiptQueueSnapshot()


def seed_receipts(ledger, keys, run_id="job-test"):
    rows = []
    for key in keys:
        row = receipt_row(key, success=key != "failed")
        row.update(run_id=run_id, committed_at=datetime.now(UTC),
                   failed_command_json="{}" if key == "failed" else None)
        rows.append(row)
    with ledger.session_factory() as session:
        session.execute(insert(DatabaseWriteReceiptModel), rows)
        session.commit()


def checkpoint(ledger):
    with ledger.session_factory() as session:
        return json.loads(session.scalar(text(
            "SELECT config_json FROM management.execution_runs WHERE run_id='job-test'"
        )))["metadata"]["deletion_progress"]


def receipt_ids(ledger):
    with ledger.session_factory() as session:
        return set(session.scalars(select(DatabaseWriteReceiptModel.command_id)))


def test_delete_removes_recent_and_failed_owned_receipts_but_preserves_other_work(ledger):
    submit(ledger, [task()])
    submit(ledger, [task("other-task")], identity="other-job")
    seed_receipts(ledger, ["recent", "failed", "shared", "other-queued"])
    seed_receipts(ledger, ["other-owner"], run_id="other-job")
    seed_receipts(ledger, ["unknown-owner"], run_id=None)
    with ledger.session_factory() as session:
        session.execute(insert(ExecutionMutationModel), {
            "run_id": "other-job", "task_id": "other-task",
            "mutation_key": "shared-reference", "command_id": "shared",
        })
        session.commit()
    queue = ReceiptQueueSnapshot(frozenset({"other-queued"}), frozenset({"other-job"}))
    assert ledger.delete("job-test", batch_size=2, receipt_queue=queue)
    assert receipt_ids(ledger) == {"shared", "other-queued", "other-owner", "unknown-owner"}
    assert ledger.job("other-job") is not None


def test_queued_job_writes_replay_before_receipts_are_removed(ledger):
    item = command(owned_batch(ledger, 1)[0])
    with ledger.session_factory() as session:
        results = {}
        with write_receipts.receipt_batch(session, [item], results):
            results[item.command_id] = {"saved": True}
        session.commit()
    queue = ReceiptQueueSnapshot(frozenset({item.command_id}), frozenset({"job-test"}))
    assert ledger.delete("job-test", receipt_queue=queue) is None
    saved = checkpoint(ledger)
    assert saved["completed_stages"] == 0 and saved["total_stages"] == 10
    assert "queued database writes" in saved["error"]
    assert item.command_id in receipt_ids(ledger)
    alias = replace(item, command_id="queued-logical-retry")
    with ledger.session_factory() as session:
        results = {}
        with write_receipts.receipt_batch(session, [item, alias], results) as pending:
            assert pending == []
        assert results[item.command_id] == {"saved": True}
        assert results[alias.command_id] == {"saved": True}
    assert ledger.delete("job-test", receipt_queue=EMPTY_QUEUE)
    assert receipt_ids(ledger) == set()
    with ledger.session_factory() as session, pytest.raises(StaleAttempt):
        with write_receipts.receipt_batch(session, [item], {}):
            pytest.fail("deleted job admitted a repeated mutation")


def test_missing_queue_inventory_keeps_owned_receipts_and_the_job(ledger):
    submit(ledger, [task()])
    seed_receipts(ledger, ["retain-until-inventory"])
    assert ledger.delete("job-test") is None
    assert "queue inventory" in checkpoint(ledger)["error"]
    assert receipt_ids(ledger) == {"retain-until-inventory"}
    assert ledger.delete("job-test", receipt_queue=EMPTY_QUEUE)


def test_receipt_writer_and_row_locks_are_retried_without_losing_rows(ledger):
    submit(ledger, [task()])
    seed_receipts(ledger, ["a", "b", "c", "d"])
    with ledger.session_factory() as writer:
        write_receipts._lock(writer, ["a"])
        assert ledger.delete("job-test", batch_size=2, receipt_queue=EMPTY_QUEUE) is None
        assert checkpoint(ledger)["receipt_cursor"] is None
        assert receipt_ids(ledger) == {"a", "b", "c", "d"}
    with ledger.session_factory() as blocker:
        blocker.execute(text("SELECT command_id FROM management.database_write_receipts WHERE command_id='a' FOR UPDATE"))
        assert ledger.delete("job-test", batch_size=2, receipt_queue=EMPTY_QUEUE) is None
        assert receipt_ids(ledger) == {"a"}
        assert checkpoint(ledger)["completed_stages"] == 9
        assert checkpoint(ledger)["receipt_cursor"] is None
    assert ledger.delete("job-test", batch_size=2, receipt_queue=EMPTY_QUEUE)
    assert receipt_ids(ledger) == set()


def test_old_checkpoint_resumes_receipt_pages_in_a_new_ledger(ledger, ledger_engine):
    submit(ledger, [task()])
    seed_receipts(ledger, [f"receipt-{i:03d}" for i in range(7)])

    def interrupt_history(table, rows):
        if table == "task_media_plans":
            raise RuntimeError("old history checkpoint")

    with pytest.raises(RuntimeError, match="old history checkpoint"):
        ledger.delete("job-test", progress=interrupt_history, receipt_queue=EMPTY_QUEUE)
    saved = checkpoint(ledger)
    saved["total_stages"] = 9
    ledger._save_deletion_progress("job-test", saved)
    assert saved["completed_stages"] == 9
    fresh = ExecutionLedger(ledger.session_factory)
    assert fresh.delete("job-test", batch_size=2, time_budget=0, receipt_queue=EMPTY_QUEUE) is None
    saved = checkpoint(ledger)
    assert saved["receipt_cursor"] == "receipt-001"
    assert saved["rows"] >= 2 and saved["total_stages"] == 10
    seeks = []

    def observe(_conn, _cursor, sql, params, _context, _many):
        if "ORDER BY r.command_id LIMIT" in sql:
            seeks.append(params.get("after"))

    event.listen(ledger_engine, "before_cursor_execute", observe)
    try:
        for _ in range(10):
            if ExecutionLedger(ledger.session_factory).delete(
                "job-test", batch_size=2, time_budget=0, receipt_queue=EMPTY_QUEUE,
            ):
                break
        else:
            pytest.fail("receipt deletion did not finish")
    finally:
        event.remove(ledger_engine, "before_cursor_execute", observe)
    assert seeks == ["receipt-001", "receipt-003", "receipt-005"]
    assert receipt_ids(ledger) == set()


@pytest.mark.parametrize("deleted", [False, True])
def test_late_failure_does_not_recreate_receipts_for_deleting_or_deleted_jobs(ledger, monkeypatch, deleted):
    from ultima_scraper_db_archive import global_db

    item = command(owned_batch(ledger, 1)[0])
    monkeypatch.setattr(global_db, "global_session", ledger.session_factory)
    if deleted:
        assert ledger.delete("job-test", receipt_queue=EMPTY_QUEUE)
    else:
        assert ledger.begin_delete("job-test")
    result = DatabaseWriteResult(item.command_id, False, {}, "cancelled", datetime.now(UTC).isoformat())
    assert write_receipts.record_failure(item, result) == result
    assert receipt_ids(ledger) == set()


def test_replayed_alias_does_not_recreate_a_deleting_jobs_receipt(ledger):
    item = command(owned_batch(ledger, 1)[0])
    with ledger.session_factory() as session:
        results = {}
        with write_receipts.receipt_batch(session, [item], results):
            results[item.command_id] = {"saved": True}
        session.commit()
    ledger.begin_delete("job-test")
    alias = replace(item, command_id="late-alias")
    with ledger.session_factory() as session:
        results = {}
        with write_receipts.receipt_batch(session, [alias], results) as pending:
            assert pending == []
        session.commit()
    assert results[alias.command_id] == {"saved": True}
    assert receipt_ids(ledger) == {item.command_id}


def test_receipt_deletion_rolls_back_with_its_checkpoint(ledger, monkeypatch):
    submit(ledger, [task()])
    seed_receipts(ledger, ["a", "b", "c"])
    save = ledger._save_deletion_progress

    def fail(run_id, value, **kwargs):
        if value.get("receipt_cursor"):
            raise RuntimeError("checkpoint failed")
        return save(run_id, value, **kwargs)

    monkeypatch.setattr(ledger, "_save_deletion_progress", fail)
    with pytest.raises(RuntimeError, match="checkpoint failed"):
        ledger.delete("job-test", batch_size=2, receipt_queue=EMPTY_QUEUE)
    assert receipt_ids(ledger) == {"a", "b", "c"}
    monkeypatch.setattr(ledger, "_save_deletion_progress", save)
    assert ledger.delete("job-test", batch_size=2, receipt_queue=EMPTY_QUEUE)


def test_receipt_deletion_requires_fencing_and_bounds_writer_locks(ledger):
    submit(ledger, [task()])
    with ledger.session_factory() as session:
        with pytest.raises(ValueError, match="fenced run"):
            purge_job_receipts(session, "job-test", queue=EMPTY_QUEUE)
        with pytest.raises(ValueError, match="512"):
            purge_job_receipts(session, "job-test", limit=513, queue=EMPTY_QUEUE)


def test_large_history_batch_still_bounds_receipt_writer_locks(ledger):
    submit(ledger, [task()])
    seed_receipts(ledger, [f"receipt-{i:04d}" for i in range(600)])

    def stop(table, rows):
        if table == "database_write_receipts":
            raise RuntimeError("one receipt page")

    with pytest.raises(RuntimeError, match="one receipt page"):
        ledger.delete("job-test", batch_size=25000, progress=stop, receipt_queue=EMPTY_QUEUE)
    assert len(receipt_ids(ledger)) == 88
    assert checkpoint(ledger)["receipt_cursor"] == "receipt-0511"
    assert ledger.delete("job-test", receipt_queue=EMPTY_QUEUE)


def test_background_pass_continues_progress_but_backs_off_for_a_writer_lock(ledger, monkeypatch):
    from ultima_scraper_backend.services import job_deletion

    submit(ledger, [task()])
    seed_receipts(ledger, ["a", "b", "c"])

    def stop_after_history(table, _rows):
        if table == "task_media_plans":
            raise RuntimeError("history checkpoint")

    with pytest.raises(RuntimeError, match="history checkpoint"):
        ledger.delete("job-test", progress=stop_after_history, receipt_queue=EMPTY_QUEUE)
    delete = ledger.delete

    def one_page(run_id, *, time_budget, receipt_queue):
        return delete(run_id, batch_size=2, time_budget=0, receipt_queue=receipt_queue)

    monkeypatch.setattr(ledger, "delete", one_page)
    monkeypatch.setattr(job_deletion, "ExecutionLedger", lambda _: ledger)
    first = job_deletion._cleanup_pass(ledger.session_factory, receipt_queue=EMPTY_QUEUE)
    assert first.advanced and first.finished == ()
    assert checkpoint(ledger)["receipt_cursor"] == "b"
    with ledger.session_factory() as writer:
        write_receipts._lock(writer, ["c"])
        blocked = job_deletion._cleanup_pass(ledger.session_factory, receipt_queue=EMPTY_QUEUE)
        assert not blocked.advanced and blocked.finished == ()
        assert receipt_ids(ledger) == {"c"}
    finished = job_deletion._cleanup_pass(ledger.session_factory, receipt_queue=EMPTY_QUEUE)
    assert finished.advanced and finished.finished == ("job-test",)
    assert ledger.job("job-test") is None


def test_missing_receipt_index_keeps_a_resumable_checkpoint(ledger):
    submit(ledger, [task()])
    seed_receipts(ledger, ["keep-until-indexed"])
    with ledger.session_factory() as session:
        session.execute(text("ALTER INDEX management.idx_write_receipts_run_command RENAME TO receipt_index_unavailable"))
        session.commit()
    try:
        assert ledger.delete("job-test", receipt_queue=EMPTY_QUEUE) is None
        assert "6f4b2e9a17c0" in checkpoint(ledger)["error"]
        assert receipt_ids(ledger) == {"keep-until-indexed"}
    finally:
        with ledger.session_factory() as session:
            session.execute(text("ALTER INDEX management.receipt_index_unavailable RENAME TO idx_write_receipts_run_command"))
            session.commit()
    assert ledger.delete("job-test", receipt_queue=EMPTY_QUEUE)


def test_receipt_index_migration_is_resumable_and_reversible(ledger_engine):
    path = (Path(ultima_scraper_db_archive.__file__).parent / "migrations/alembic/versions/6f4b2e9a17c0_index_job_receipt_deletion.py")
    spec = importlib.util.spec_from_file_location("job_receipt_index", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with ledger_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            for action in (migration.downgrade, migration.upgrade, migration.upgrade):
                with context.begin_transaction():
                    action()
            assert connection.scalar(text("SELECT indisvalid FROM pg_index WHERE indexrelid='management.idx_write_receipts_run_command'::regclass"))
            assert connection.scalar(text("SELECT to_regclass('management.idx_write_receipts_run')")) is None


def test_receipt_page_uses_the_owner_and_command_index_seek(ledger, ledger_engine):
    submit(ledger, [task()])
    ledger.begin_delete("job-test")
    with ledger_engine.begin() as connection:
        connection.execute(text("""INSERT INTO management.database_write_receipts
            (command_id,run_id,operation,result_json)
            SELECT md5(n::text), CASE WHEN n%10=0 THEN 'job-test' ELSE 'other-job' END,
                   'upsert_user','{}' FROM generate_series(1,50000) n"""))
        connection.execute(text("ANALYZE management.database_write_receipts"))
    queries = []

    def observe(_conn, _cursor, sql, params, _context, _many):
        if "ORDER BY r.command_id LIMIT" in sql:
            queries.append((sql, params))

    event.listen(ledger_engine, "before_cursor_execute", observe)
    try:
        with ledger.session_factory() as session:
            page = purge_job_receipts(session, "job-test", after="8", queue=EMPTY_QUEUE)
            assert page.deleted == 512
            session.rollback()
    finally:
        event.remove(ledger_engine, "before_cursor_execute", observe)
    with ledger_engine.connect() as connection:
        sql, params = queries[0]
        plan = connection.exec_driver_sql("EXPLAIN (FORMAT JSON) " + sql, params).scalar()[0]["Plan"]

    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    scans = [node for node in nodes(plan) if node.get("Relation Name") == "database_write_receipts"]
    assert scans[0]["Index Name"] == "idx_write_receipts_run_command"
    assert "run_id" in scans[0]["Index Cond"] and "command_id" in scans[0]["Index Cond"]


def test_deletion_fence_waits_for_a_failure_receipt_transaction(ledger, ledger_engine, monkeypatch):
    from ultima_scraper_db_archive import global_db

    item = command(owned_batch(ledger, 1)[0])
    monkeypatch.setattr(global_db, "global_session", ledger.session_factory)
    inserted, release, deleting = Event(), Event(), Event()

    def observe(_conn, _cursor, sql, _params, _context, _many):
        if sql.startswith("INSERT INTO management.database_write_receipts"):
            inserted.set()
            assert release.wait(5)

    result = DatabaseWriteResult(item.command_id, False, {}, "failed", datetime.now(UTC).isoformat())
    event.listen(ledger_engine, "after_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            writer = executor.submit(write_receipts.record_failure, item, result)
            assert inserted.wait(5)

            def begin():
                deleting.set()
                return ledger.begin_delete("job-test")

            deletion = executor.submit(begin)
            try:
                assert deleting.wait(5)
                with pytest.raises(TimeoutError):
                    deletion.result(timeout=0.1)
            finally:
                release.set()
            assert writer.result(timeout=5) == result
            assert deletion.result(timeout=5)
    finally:
        release.set()
        event.remove(ledger_engine, "after_cursor_execute", observe)
    assert item.command_id in receipt_ids(ledger)
    assert ledger.delete("job-test", receipt_queue=EMPTY_QUEUE)
    assert receipt_ids(ledger) == set()


@pytest.mark.asyncio
async def test_pending_receipt_inventory_covers_both_streams_and_fails_closed(ledger):
    item = command(owned_batch(ledger, 1)[0])
    other = replace(item, command_id="priority-command")
    client = SimpleNamespace(get=AsyncMock(return_value=None), xrange=AsyncMock(side_effect=[
        [("1-0", {"command": item.to_json()})], [("2-0", {"command": other.to_json()})],
    ]))
    snapshot = await pending_write_inventory(SimpleNamespace(client=client))
    assert snapshot.command_ids == {item.command_id, other.command_id}
    assert snapshot.run_ids == {"job-test"}
    client.xrange.side_effect = None
    client.xrange.return_value = [("1-0", {})]
    with pytest.raises(ValueError):
        await pending_write_inventory(SimpleNamespace(client=client))


@pytest.mark.asyncio
async def test_deletion_worker_never_treats_inventory_failure_as_an_empty_queue(monkeypatch):
    from ultima_scraper_backend.services import job_deletion

    monkeypatch.setattr(job_deletion, "pending_write_inventory", AsyncMock(side_effect=ValueError("malformed queue")))
    runner = AsyncMock(return_value=job_deletion._DeletionPass())
    monkeypatch.setattr(job_deletion, "run_database_call", runner)

    async def stop(_delay):
        raise asyncio.CancelledError

    monkeypatch.setattr(job_deletion.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        await job_deletion.run_deletion_worker(SimpleNamespace())
    assert runner.await_args.kwargs["receipt_queue"] is None


@pytest.fixture
def force_sweep(monkeypatch):
    """Sweep even tiny owners, from a one-row sample, one heap block per page."""
    from ultima_scraper_backend.database import job_receipts

    monkeypatch.setattr(job_receipts, "RECEIPT_SWEEP_MIN_ROWS", 0)
    monkeypatch.setattr(job_receipts, "RECEIPT_SWEEP_SAMPLE", 1)
    monkeypatch.setattr(job_receipts, "RECEIPT_SWEEP_PAGES", 1)
    monkeypatch.setattr(job_receipts, "RECEIPT_SWEEP_MARGIN", 0)


def test_sweep_preserves_queued_shared_and_foreign_receipts(ledger, force_sweep):
    submit(ledger, [task()])
    submit(ledger, [task("other-task")], identity="other-job")
    seed_receipts(ledger, ["recent", "failed", "shared", "other-queued"])
    seed_receipts(ledger, ["other-owner"], run_id="other-job")
    seed_receipts(ledger, ["unknown-owner"], run_id=None)
    with ledger.session_factory() as session:
        session.execute(insert(ExecutionMutationModel), {
            "run_id": "other-job", "task_id": "other-task",
            "mutation_key": "shared-reference", "command_id": "shared",
        })
        session.commit()
    queue = ReceiptQueueSnapshot(frozenset({"other-queued"}), frozenset({"other-job"}))
    assert ledger.delete("job-test", batch_size=2, receipt_queue=queue)
    assert receipt_ids(ledger) == {"shared", "other-queued", "other-owner", "unknown-owner"}


def test_sweep_tail_removes_receipts_outside_the_sampled_range(ledger, force_sweep):
    submit(ledger, [task()])
    seed_receipts(ledger, [f"spread-{i:04d}" for i in range(400)])
    seed_receipts(ledger, [f"other-{i:04d}" for i in range(400)], run_id="other-job")
    with ledger.session_factory() as session:
        blocks = session.scalar(text("""SELECT count(DISTINCT (ctid::text::point)[0])
            FROM management.database_write_receipts WHERE run_id='job-test'"""))
    assert blocks > 3  # A one-row sample cannot cover them all.
    states = []
    ledger.delete("job-test", batch_size=64, receipt_queue=EMPTY_QUEUE,
                  progress=lambda table, _rows: table == "database_write_receipts"
                  and states.append(checkpoint(ledger).get("receipt_sweep")))
    assert ledger.job("job-test") is None
    assert {"tail": True} in states
    assert any(state and not state.get("tail") for state in states)
    assert receipt_ids(ledger) == {f"other-{i:04d}" for i in range(400)}


def test_sweep_retries_row_and_writer_locked_receipts(ledger, force_sweep):
    submit(ledger, [task()])
    seed_receipts(ledger, ["a", "b", "c", "d"])
    with ledger.session_factory() as writer:
        write_receipts._lock(writer, ["a"])
        assert ledger.delete("job-test", batch_size=2, receipt_queue=EMPTY_QUEUE) is None
        assert receipt_ids(ledger) >= {"a"}
    with ledger.session_factory() as blocker:
        blocker.execute(text("SELECT command_id FROM management.database_write_receipts WHERE command_id='a' FOR UPDATE"))
        assert ledger.delete("job-test", batch_size=2, receipt_queue=EMPTY_QUEUE) is None
        assert receipt_ids(ledger) == {"a"}
        assert checkpoint(ledger)["completed_stages"] == 9
    assert ledger.delete("job-test", batch_size=2, receipt_queue=EMPTY_QUEUE)
    assert receipt_ids(ledger) == set()


def test_command_cursor_checkpoint_resumes_as_a_sweep(ledger, monkeypatch):
    from ultima_scraper_backend.database import job_receipts

    submit(ledger, [task()])
    seed_receipts(ledger, [f"receipt-{i:04d}" for i in range(600)])

    def stop(table, rows):
        if table == "database_write_receipts":
            raise RuntimeError("one receipt page")

    with pytest.raises(RuntimeError, match="one receipt page"):
        ledger.delete("job-test", batch_size=25000, progress=stop, receipt_queue=EMPTY_QUEUE)
    saved = checkpoint(ledger)
    assert saved["receipt_cursor"] == "receipt-0511" and saved["receipt_sweep"] is False
    # A checkpoint written before sweeps existed has no strategy recorded.
    ledger._save_deletion_progress("job-test", {k: v for k, v in saved.items() if k != "receipt_sweep"})
    monkeypatch.setattr(job_receipts, "RECEIPT_SWEEP_MIN_ROWS", 1)
    assert ledger.delete("job-test", receipt_queue=EMPTY_QUEUE)
    assert receipt_ids(ledger) == set()


def test_sweep_window_reads_the_heap_in_physical_order(ledger, ledger_engine, force_sweep):
    from ultima_scraper_backend.database.job_receipts import purge_job_receipts_sweep

    submit(ledger, [task()])
    ledger.begin_delete("job-test")
    # A large owner, as in production: a run_id seek must look expensive.
    with ledger_engine.begin() as connection:
        connection.execute(text("""INSERT INTO management.database_write_receipts
            (command_id,run_id,operation,result_json)
            SELECT md5(n::text), 'job-test', 'upsert_user', '{}' FROM generate_series(1,20000) n"""))
        connection.execute(text("ANALYZE management.database_write_receipts"))
    queries = []

    def observe(_conn, _cursor, sql, params, _context, _many):
        if "ORDER BY r.ctid LIMIT" in sql or sql.lstrip().startswith("DELETE"):
            queries.append((sql, params))

    event.listen(ledger_engine, "before_cursor_execute", observe)
    try:
        with ledger.session_factory() as session:
            page = purge_job_receipts_sweep(session, "job-test", sweep={"cursor": "(0,0)", "end": 10},
                                            queue=EMPTY_QUEUE)
            assert page.deleted > 0
            session.rollback()
    finally:
        event.remove(ledger_engine, "before_cursor_execute", observe)

    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    window, delete = queries
    with ledger_engine.connect() as connection:
        connection.execute(text("SET enable_seqscan=off"))  # Tiny tables favour seq scans.
        plans = [connection.exec_driver_sql("EXPLAIN (FORMAT JSON) " + sql, params).scalar()[0]["Plan"]
                 for sql, params in (window, delete)]
    assert any(node["Node Type"] == "Tid Range Scan" for node in nodes(plans[0]))
    # The reference check runs only for the page's candidates, not the window.
    assert not any(node.get("Parent Relationship") == "SubPlan" for node in nodes(plans[0]))
    # Hashed command IDs must not route the delete through a random index seek.
    receipt_scans = [node for node in nodes(plans[1]) if node.get("Relation Name") == "database_write_receipts"
                     and node["Node Type"] != "ModifyTable"]
    assert [node["Node Type"] for node in receipt_scans] == ["Tid Scan"]
