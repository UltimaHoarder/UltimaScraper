"""Dense identity cleanup visits bounded heap ranges and resumes safely."""

import json

import pytest
from sqlalchemy import event, text
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from test_job_identity_deletion import partitioned_engine, partitioned_ledger
from ultima_scraper_backend.database import job_partitions
from ultima_scraper_backend.database.receipt_retention import ReceiptQueueSnapshot
from ultima_scraper_backend.job_system.ledger import ExecutionLedger

__all__ = ["ledger", "ledger_engine", "postgres_engine", "partitioned_engine", "partitioned_ledger"]


def progress(ledger, run_id):
    with ledger.session_factory() as session:
        return json.loads(session.scalar(text(
            "SELECT config_json FROM management.execution_runs WHERE run_id=:run"
        ), {"run": run_id}))["metadata"]["deletion_progress"]


@pytest.mark.parametrize("table,directory,owner,key", [
    ("job_tasks", "job_task_identities", "job_id", "task_id"),
    ("execution_attempts", "execution_attempt_identities", "run_id", "token"),
    ("execution_outbox", "execution_outbox_identities", "run_id", "event_id"),
])
def test_physical_pages_rewind_for_locks_and_preserve_other_owners(
    partitioned_ledger, partitioned_engine, monkeypatch, table, directory, owner, key,
):
    ledger = partitioned_ledger
    monkeypatch.setattr(job_partitions, "IDENTITY_SWEEP_PAGES", 1)
    key_value = "n" if key == "event_id" else "md5(n::text)"
    extra_columns = ",task_id,number" if key == "token" else ""
    extra_values = ",'task',1" if key == "token" else ""
    with ledger.session_factory() as session:
        session.execute(text(f"""INSERT INTO management.{directory} ({owner},{key}{extra_columns})
            SELECT CASE WHEN n%2=0 THEN 'purge-me' ELSE 'keep-me' END,
                   {key_value}{extra_values} FROM generate_series(1,1000) n"""))
        locked = session.scalar(text(f"SELECT {key} FROM management.{directory} WHERE {owner}='purge-me' ORDER BY ctid LIMIT 1"))
        session.commit()
    cursor = "(0,0)"
    deleted = 0
    with partitioned_engine.connect() as blocker:
        blocker.execute(text(f"SELECT {key} FROM management.{directory} WHERE {key}=:key FOR UPDATE"), {"key": locked})
        for _ in range(1000):
            with ledger.session_factory() as session:
                count, remaining, cursor = job_partitions.purge_identity_sweep_page(
                    session, table, "purge-me", 31, after=cursor,
                )
                assert count <= 31 and remaining
                deleted += count
                session.commit()
            if cursor == "(0,0)":
                break
        else:
            pytest.fail("physical pass did not rewind for its skipped row")
        assert deleted == 499
    for _ in range(1000):
        with ledger.session_factory() as session:
            count, remaining, cursor = job_partitions.purge_identity_sweep_page(
                session, table, "purge-me", 31, after=cursor,
            )
            deleted += count
            session.commit()
        if not remaining:
            break
    else:
        pytest.fail("physical sweep failed to finish after the lock drained")
    assert deleted == 500 and cursor is None
    with ledger.session_factory() as session:
        assert session.scalar(text(f"SELECT count(*) FROM management.{directory} WHERE {owner}='keep-me'")) == 500


def test_dense_owners_choose_sweeps_while_sparse_owners_keep_key_seeks(partitioned_ledger, monkeypatch):
    monkeypatch.setattr(job_partitions, "IDENTITY_SWEEP_MIN_ROWS", 100)
    with partitioned_ledger.session_factory() as session:
        session.execute(text("""INSERT INTO management.job_task_identities (job_id,task_id)
            SELECT CASE WHEN n<=950 THEN 'dense' ELSE 'sparse' END,md5(n::text)
            FROM generate_series(1,1000) n"""))
        session.execute(text("ANALYZE management.job_task_identities"))
        assert job_partitions.identity_cleanup_uses_sweep(session, "job_tasks", "dense")
        assert not job_partitions.identity_cleanup_uses_sweep(session, "job_tasks", "sparse")
        assert not job_partitions.identity_cleanup_uses_sweep(session, "execution_work", "dense")


def test_empty_ranges_advance_and_an_obsolete_cursor_rewinds(partitioned_ledger, monkeypatch):
    monkeypatch.setattr(job_partitions, "IDENTITY_SWEEP_PAGES", 1)
    with partitioned_ledger.session_factory() as session:
        session.execute(text("""INSERT INTO management.job_task_identities (job_id,task_id)
            SELECT CASE WHEN n<=500 THEN 'other-job' ELSE 'purge-me' END,md5(n::text)
            FROM generate_series(1,600) n"""))
        session.commit()
        assert job_partitions.purge_identity_sweep_page(session, "job_tasks", "purge-me", 500) == (0, True, "(1,0)")
        session.commit()
        assert job_partitions.purge_identity_sweep_page(session, "job_tasks", "purge-me", 500, after="(999999,0)") == (0, True, "(0,0)")
        with pytest.raises(ValueError, match="cursor"):
            job_partitions.purge_identity_sweep_page(session, "job_tasks", "purge-me", 5, after="bad")
        with pytest.raises(ValueError, match="positive"):
            job_partitions.purge_identity_sweep_page(session, "job_tasks", "purge-me", 0)


def test_old_key_checkpoint_can_resume_as_a_physical_sweep(partitioned_ledger, partitioned_engine, monkeypatch):
    ledger = partitioned_ledger
    run = "job-physical"
    submit(ledger, [task()], identity=run)
    with ledger.session_factory() as session:
        session.execute(text("""INSERT INTO management.execution_attempt_identities
            (run_id,token,task_id,number) SELECT :run,md5(n::text),'task',1
            FROM generate_series(1,200) n"""), {"run": run})
        session.commit()

    def stop_at_key(table, rows):
        if table != "execution_attempts":
            return
        saved = progress(ledger, run)
        if saved.get("identity_cursor"):
            raise RuntimeError("old key checkpoint")

    with pytest.raises(RuntimeError, match="old key checkpoint"):
        ledger.delete(run, batch_size=3, progress=stop_at_key, receipt_queue=ReceiptQueueSnapshot())
    saved = progress(ledger, run)
    assert saved["completed_stages"] == 2 and saved["identity_cursor"]
    monkeypatch.setattr(job_partitions, "identity_cleanup_uses_sweep", lambda session, table, run_id: table == "execution_attempts")
    monkeypatch.setattr(job_partitions, "IDENTITY_SWEEP_PAGES", 1)
    fresh = ExecutionLedger(ledger.session_factory)
    with ledger.session_factory() as session:
        expected_cursor = session.scalar(text("""SELECT d.ctid::text
            FROM management.execution_attempt_identities d WHERE run_id=:run
            ORDER BY d.ctid OFFSET 16 LIMIT 1"""), {"run": run})
    assert fresh.delete(run, batch_size=17, time_budget=0, receipt_queue=ReceiptQueueSnapshot()) is None
    saved = progress(ledger, run)
    assert saved["identity_cursor"] is None and saved["identity_sweep_cursor"]
    assert saved["identity_sweep_cursor"] == expected_cursor
    first_cursor = saved["identity_sweep_cursor"]
    seeks = []

    def observe(_conn, _cursor, sql, params, _context, _many):
        if "ctid>CAST" in sql and "execution_attempt_identities" in sql:
            seeks.append(params["after"])

    event.listen(partitioned_engine, "before_cursor_execute", observe)
    try:
        for _ in range(100):
            if ExecutionLedger(ledger.session_factory).delete(run, batch_size=17, time_budget=0, receipt_queue=ReceiptQueueSnapshot()):
                break
        else:
            pytest.fail("replacement ledger did not finish the physical sweep")
    finally:
        event.remove(partitioned_engine, "before_cursor_execute", observe)
    assert seeks[0] == first_cursor
    assert ledger.job(run) is None
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.execution_attempt_identities WHERE run_id=:run"), {"run": run}) == 0


def test_physical_cursor_rolls_back_with_its_page(partitioned_ledger, monkeypatch):
    from psycopg.errors import SerializationFailure
    from sqlalchemy.exc import OperationalError

    ledger = partitioned_ledger
    submit(ledger, [task()])
    with ledger.session_factory() as session:
        session.execute(text("""INSERT INTO management.job_task_identities (job_id,task_id)
            SELECT 'job-test',md5(n::text) FROM generate_series(1,12) n"""))
        session.commit()
    monkeypatch.setattr(job_partitions, "identity_cleanup_uses_sweep", lambda session, table, run_id: table == "job_tasks")
    save = ledger._save_deletion_progress
    cursors = []

    def fail_once(run_id, value, **kwargs):
        if value.get("identity_sweep_cursor"):
            cursors.append(value["identity_sweep_cursor"])
            if len(cursors) == 1:
                raise OperationalError("checkpoint", {}, SerializationFailure("retry"))
        return save(run_id, value, **kwargs)

    monkeypatch.setattr(ledger, "_save_deletion_progress", fail_once)
    assert ledger.delete("job-test", batch_size=2, receipt_queue=ReceiptQueueSnapshot())
    assert cursors[0] == cursors[1]
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_task_identities")) == 0


def test_mixed_payload_and_final_identity_page_finish_the_stage(partitioned_ledger, monkeypatch):
    from sqlalchemy import insert
    from ultima_scraper_db_archive.global_db import CentralTaskModel

    ledger = partitioned_ledger
    submit(ledger, [task()])
    with ledger.session_factory() as session:
        session.execute(insert(CentralTaskModel), {
            "job_id": "job-test", "task_id": "history-task", "task_type": "scrape_user", "status": "completed",
        })
        session.execute(text("INSERT INTO management.job_task_identities (job_id,task_id) VALUES ('job-test','extra-identity')"))
        session.commit()
    # Exercise the legacy row-delete fallback: its one payload row removes its
    # own guard identity; one final identity makes the combined row count two.
    monkeypatch.setattr(job_partitions, "drop_history_partition", lambda *args, **kwargs: False)
    monkeypatch.setattr(job_partitions, "identity_cleanup_uses_sweep", lambda session, table, run_id: table == "job_tasks")
    assert ledger.delete("job-test", batch_size=2, receipt_queue=ReceiptQueueSnapshot())
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_task_identities")) == 0
