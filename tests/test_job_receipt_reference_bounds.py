"""Receipt cleanup probes mutation references without restarting legacy scans."""

import importlib.util
from pathlib import Path

import ultima_scraper_db_archive

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from ultima_scraper_backend.database.job_receipts import purge_job_receipts
from ultima_scraper_backend.database import job_receipts
from ultima_scraper_backend.database.receipt_retention import ReceiptQueueSnapshot

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from nodes(child)


@pytest.mark.parametrize("partitioned", [False, True])
def test_each_receipt_reference_check_uses_a_command_point_lookup(ledger, ledger_engine, partitioned):
    submit(ledger, [task()], identity="job-target")
    submit(ledger, [task("legacy-task")], identity="job-legacy")
    with ledger.session_factory() as session:
        session.execute(text("CREATE INDEX IF NOT EXISTS idx_execution_mutations_command ON management.execution_mutations(command_id)"))
        session.execute(text("""INSERT INTO management.execution_mutations
            (run_id,task_id,mutation_key,command_id)
            SELECT 'job-legacy','task-'||n,'save',md5('legacy-'||n)
            FROM generate_series(1,50000) n"""))
        session.execute(text("""INSERT INTO management.database_write_receipts
            (command_id,run_id,operation,result_json)
            SELECT md5('receipt-'||n),'job-target','upsert_user','{}'
            FROM generate_series(1,50000) n"""))
        session.execute(text("""INSERT INTO management.database_write_receipts
            (command_id,run_id,operation,result_json) VALUES
            (repeat('f',32),'job-target','upsert_user','{}'),
            (repeat('f',32)||'1','job-target','upsert_user','{}')"""))
        session.execute(text("""INSERT INTO management.execution_mutations
            (run_id,task_id,mutation_key,command_id)
            VALUES ('job-legacy','shared-task','shared',repeat('f',32))"""))
        session.commit()
    if partitioned:
        path = (Path(ultima_scraper_db_archive.__file__).parent / "migrations/alembic/versions/a84df9201c76_partition_execution_mutations_by_run.py")
        spec = importlib.util.spec_from_file_location("receipt_legacy_reference_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with ledger_engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
    with ledger_engine.begin() as connection:
        connection.execute(text("ANALYZE management.execution_mutations"))
        connection.execute(text("ANALYZE management.database_write_receipts"))
    ledger.begin_delete("job-target")
    statements = []

    def observe(_conn, _cursor, sql, params, _context, _many):
        if "execution_mutations m" in sql:
            statements.append((sql, params))

    event.listen(ledger_engine, "before_cursor_execute", observe)
    try:
        with ledger.session_factory() as session:
            page = purge_job_receipts(session, "job-target", after="8", queue=ReceiptQueueSnapshot())
            assert page.deleted == 512 and not page.finished
            session.rollback()
        with ledger.session_factory() as session:
            # The late cursor passes one shared receipt and deletes the next
            # unreferenced one; the owner-wide completion check also stays
            # correlated rather than restarting a mutation merge scan.
            page = purge_job_receipts(session, "job-target", after="f"*31+"e", queue=ReceiptQueueSnapshot())
            assert page.deleted == 1 and not page.finished
            assert session.scalar(text("SELECT command_id FROM management.database_write_receipts WHERE command_id=repeat('f',32)")) == "f"*32
            session.rollback()
    finally:
        event.remove(ledger_engine, "before_cursor_execute", observe)
    assert len(statements) == 5  # Two selections, two deletes, one completion check.
    with ledger_engine.connect() as connection:
        for sql, params in statements:
            plan = connection.exec_driver_sql("EXPLAIN (FORMAT JSON) " + sql, params).scalar()[0]["Plan"]
            all_nodes = list(nodes(plan))
            assert not any(node.get("Join Type") == "Anti" for node in all_nodes)
            probes = [node for node in all_nodes if node.get("Relation Name", "").startswith("execution_mutations")]
            assert probes
            for probe in probes:
                condition = probe.get("Index Cond", "")
                assert "command_id" in condition and "r.command_id" in condition


@pytest.mark.parametrize("fail", [False, True])
def test_completion_groups_heap_reads_and_restores_planner_settings(ledger, ledger_engine, fail):
    submit(ledger, [task()])
    ledger.begin_delete("job-test")
    with ledger_engine.begin() as connection:
        connection.execute(text("""INSERT INTO management.database_write_receipts
            (command_id,run_id,operation,result_json)
            VALUES ('a','job-test','upsert_user','{}')"""))
    plans = []

    def observe(conn, _cursor, sql, params, _context, _many):
        if sql.lstrip().startswith("SELECT EXISTS(SELECT 1") and "database_write_receipts r" in sql:
            plan = conn.exec_driver_sql("EXPLAIN (FORMAT JSON) " + sql, params).scalar()[0]["Plan"]
            plans.append(plan)
            if fail:
                conn.execute(text("SELECT 1/0"))

    with ledger.session_factory() as session:
        baseline = dict(session.execute(job_receipts._READ_PLANNER).mappings().one())
        # Preserve caller overrides as well as PostgreSQL's normal defaults.
        session.execute(text("SET LOCAL enable_bitmapscan=off"))
        original = dict(session.execute(job_receipts._READ_PLANNER).mappings().one())
        event.listen(ledger_engine, "before_cursor_execute", observe)
        try:
            if fail:
                with pytest.raises(DBAPIError):
                    purge_job_receipts(session, "job-test", queue=ReceiptQueueSnapshot())
                session.rollback()
                assert dict(session.execute(job_receipts._READ_PLANNER).mappings().one()) == baseline
                assert session.scalar(text("SELECT command_id FROM management.database_write_receipts")) == "a"
            else:
                page = purge_job_receipts(session, "job-test", after="z", queue=ReceiptQueueSnapshot())
                assert page.deleted == 0 and not page.finished and page.cursor is None
                assert dict(session.execute(job_receipts._READ_PLANNER).mappings().one()) == original
        finally:
            event.remove(ledger_engine, "before_cursor_execute", observe)
            session.rollback()
    assert len(plans) == 1
    receipt_scans = [node for node in nodes(plans[0])
                     if node.get("Relation Name") == "database_write_receipts"]
    assert len(receipt_scans) == 1
    assert receipt_scans[0]["Node Type"] == "Bitmap Heap Scan"
