import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from ultima_scraper_backend.database.job_partitions import partition_name
from ultima_scraper_backend.database.receipt_retention import ReceiptQueueSnapshot
from ultima_scraper_db_archive.execution_models import (
    ExecutionAttemptModel,
    ExecutionMutationModel,
    ExecutionOutboxModel,
)
from ultima_scraper_db_archive.global_db import CentralTaskModel, MPSPlanModel

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def test_all_history_repartition_preserves_keys_and_restart_deletion(
    ledger, ledger_engine, monkeypatch
):
    submit(ledger, [task()], identity="job-old")
    ledger.tick()
    claims = ledger.claim_many(
        owner="worker-a", backend_id="backend-a", capabilities=["onlyfans"], count=1
    )
    assert claims
    with ledger.session_factory() as session:
        session.execute(
            insert(ExecutionMutationModel),
            {
                "run_id": "job-old",
                "task_id": "task-a",
                "mutation_key": "saved",
                "command_id": "old-command",
            },
        )
        session.execute(
            insert(CentralTaskModel),
            {
                "task_id": "history-old",
                "job_id": "job-old",
                "task_type": "scrape_user",
                "status": "completed",
            },
        )
        old_counts = {
            table: session.scalar(text(f"SELECT count(*) FROM management.{table}"))
            for table in (
                "execution_mutations",
                "execution_attempts",
                "execution_outbox",
                "job_tasks",
            )
        }
        session.commit()
    path = (
        Path(__file__).resolve().parents[2]
        / "UltimaDatabases/UltimaScraperDBArchive/ultima_scraper_db_archive/migrations/alembic/versions/c92ea6407b31_partition_all_job_history.py"
    )
    spec = importlib.util.spec_from_file_location("all_history_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with (
        ledger_engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.upgrade()
    with ledger.session_factory() as session:
        for table, count in old_counts.items():
            assert (
                session.scalar(text(f"SELECT count(*) FROM management.{table}"))
                == count
            )
            assert session.scalar(
                text(f"SELECT tableoid::regclass::text FROM management.{table} LIMIT 1")
            ).split(".")[-1] == partition_name("job-old", table)
    submit(ledger, [task("task-new")], identity="job-new")
    with ledger.session_factory() as session:
        session.execute(
            insert(ExecutionAttemptModel),
            {
                "run_id": "job-new",
                "task_id": "task-new",
                "number": 77,
                "token": "new-token",
                "owner": "worker-b",
                "state": "running",
            },
        )
        session.execute(
            insert(CentralTaskModel),
            {
                "task_id": "history-new",
                "job_id": "job-new",
                "task_type": "scrape_user",
                "status": "completed",
            },
        )
        session.execute(
            insert(ExecutionMutationModel),
            {
                "run_id": "job-new",
                "task_id": "task-new",
                "mutation_key": "saved",
                "command_id": "new-command",
            },
        )
        session.commit()
        old_attempt = session.execute(
            select(ExecutionAttemptModel).where(
                ExecutionAttemptModel.run_id == "job-old"
            )
        ).scalar_one()
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                insert(ExecutionAttemptModel),
                {
                    "run_id": "job-new",
                    "task_id": "collision-task",
                    "number": 10,
                    "token": old_attempt.token,
                    "owner": "worker-b",
                    "state": "running",
                },
            )
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                insert(CentralTaskModel),
                {
                    "task_id": "history-old",
                    "job_id": "job-new",
                    "task_type": "scrape_user",
                    "status": "completed",
                },
            )
        old_event = session.execute(
            select(ExecutionOutboxModel)
            .where(ExecutionOutboxModel.run_id == "job-old")
            .limit(1)
        ).scalar_one()
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                insert(ExecutionOutboxModel),
                {
                    "event_id": old_event.event_id,
                    "run_id": "job-new",
                    "payload_json": "{}",
                },
            )
        # Sequence uniqueness survives partitioning and relay updates.
        session.execute(
            text(
                "UPDATE management.execution_outbox SET sequence=999,delivered=true WHERE event_id=:id"
            ),
            {"id": old_event.event_id},
        )
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                text(
                    "UPDATE management.execution_outbox SET sequence=999 WHERE run_id='job-new'"
                )
            )
        session.execute(
            text(
                "UPDATE management.execution_outbox SET sequence=NULL,delivered=false WHERE event_id=:id"
            ),
            {"id": old_event.event_id},
        )
        from ultima_scraper_backend.database.job_partitions import task_conflict_columns

        stmt = insert(CentralTaskModel).values(
            task_id="history-new",
            job_id="job-new",
            task_type="scrape_user",
            status="failed",
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=task_conflict_columns(session), set_={"status": "failed"}
            )
        )
        assert (
            session.scalar(
                text(
                    "SELECT status FROM management.job_tasks WHERE job_id='job-new' AND task_id='history-new'"
                )
            )
            == "failed"
        )
        session.commit()

    # A child cannot reuse another job's archived ID. The guarded global
    # directory checks this without scanning all historical task partitions.
    statements = []

    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(ledger_engine, "before_cursor_execute", observe)
    try:
        with ledger.session_factory() as session:
            with pytest.raises(ValueError, match="already belongs to another task"):
                ledger.manifests.definitions.append_spawned(
                    session.get(MPSPlanModel, "job-new"),
                    [{"task_id": "task-new", "status": "completed",
                      "result_json": json.dumps({"new_tasks": [task("history-old").to_dict()]})}],
                    session=session,
                )
            assert session.scalar(text("""
                SELECT count(*) FROM pg_locks locks
                JOIN pg_inherits inheritance ON inheritance.inhrelid=locks.relation
                WHERE locks.pid=pg_backend_pid()
                  AND inheritance.inhparent='management.job_tasks'::regclass
            """)) == 0
            # Catalog traversal must still reject a directory whose leaf guard
            # is disabled. Roll the fixture-only ALTER back immediately.
            from ultima_scraper_backend.database.job_partitions import task_identity_model

            session.execute(text(
                f"ALTER TABLE management.{partition_name('job-new', 'job_tasks')} "
                "DISABLE TRIGGER history_identity_guard"
            ))
            session.info.pop("task_identity_directory_guarded", None)
            assert task_identity_model(session) is CentralTaskModel
            session.rollback()
    finally:
        event.remove(ledger_engine, "before_cursor_execute", observe)
    assert any("FROM management.job_task_identities" in sql for sql in statements)
    assert not any("FROM management.job_tasks" in sql for sql in statements)

    def fail_publish(_):
        raise RuntimeError("publisher interrupted")

    with pytest.raises(RuntimeError, match="publisher interrupted"):
        ledger.relay(fail_publish)
    delivered = []
    assert ledger.relay(publish_many=delivered.extend) > 0
    assert len({item["sequence"] for item in delivered}) == len(delivered)
    assert ledger.events(run_id="job-new")
    assert ledger.begin_delete("job-old")
    assert ledger.delete("job-old", batch_size=1, time_budget=0, receipt_queue=ReceiptQueueSnapshot()) is None
    from ultima_scraper_backend.job_system.ledger import ExecutionLedger

    fresh = ExecutionLedger(ledger.session_factory, limits=ledger.limits)
    assert fresh.delete("job-old", batch_size=1, receipt_queue=ReceiptQueueSnapshot())
    with ledger.session_factory() as session:
        for table in old_counts:
            assert (
                session.scalar(
                    text("SELECT to_regclass(:name)"),
                    {"name": "management." + partition_name("job-old", table)},
                )
                is None
            )
            assert session.scalar(text(f"SELECT count(*) FROM management.{table}")) > 0
        for directory, owner in [
            ("execution_attempt_identities", "run_id"),
            ("execution_outbox_identities", "run_id"),
            ("job_task_identities", "job_id"),
        ]:
            assert (
                session.scalar(
                    text(
                        f"SELECT count(*) FROM management.{directory} WHERE {owner}='job-old'"
                    )
                )
                == 0
            )
        assert (
            session.scalar(
                text(
                    "SELECT command_id FROM management.execution_mutations WHERE run_id='job-new'"
                )
            )
            == "new-command"
        )

    # Normal claims and completion still archive into the migrated task parent.
    from test_execution_ledger import finish

    for _ in range(4):
        fresh.tick()
    owned = fresh.claim_many(
        owner="worker-c", backend_id="backend-a", capabilities=["onlyfans"], count=1
    )[0]
    assert owned.run_id == "job-new"
    finished_task = finish(fresh, owned)
    for _ in range(4):
        fresh.tick()
    assert fresh.task("job-new", finished_task.task_id)["state"] == "completed"

    # Retention must sweep leaf events through the global index, not parent ctid.
    old = datetime.now(UTC) - timedelta(days=8)
    with ledger.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.execution_runs SET state='completed',completed_at=:old WHERE run_id='job-new'"
            ),
            {"old": old},
        )
        for event_id, delivered, sequence, age in [
            (10000, True, 9000, old),
            (10001, False, None, old),
            (10002, True, 9001, datetime.now(UTC)),
            # A legacy task event the relay skipped: delivered, never sequenced.
            (10003, True, None, old),
        ]:
            session.execute(
                insert(ExecutionOutboxModel),
                {
                    "event_id": event_id,
                    "run_id": "job-new",
                    "payload_json": "{}",
                    "delivered": delivered,
                    "sequence": sequence,
                    "created_at": age,
                },
            )
        session.commit()
    from ultima_scraper_backend.database.outbox_retention import purge_outbox

    purged = purge_outbox(mode="always", session_factory=ledger.session_factory)
    assert purged.deleted == 2 and purged.next_cursor.startswith("event:")
    with ledger.session_factory() as session:
        assert list(
            session.scalars(
                text(
                    "SELECT event_id FROM management.execution_outbox WHERE event_id>=10000 ORDER BY event_id"
                )
            )
        ) == [10001, 10002]
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.execution_outbox_identities WHERE event_id=10000"
                )
            )
            == 0
        )

    # Previously deleted legacy jobs can have task history without any owner.
    from ultima_scraper_backend.api.routes import jobs
    from ultima_scraper_backend.database.job_partitions import (
        drop_history_partition,
        ensure_history_partition,
    )
    from ultima_scraper_db_archive import global_db

    with ledger.session_factory() as session:
        with pytest.raises(ValueError):
            drop_history_partition(session, "job-new", "job_tasks", allow_orphan=True)
        session.rollback()
        ensure_history_partition(session, "job-orphan", "job_tasks")
        session.execute(
            insert(CentralTaskModel),
            {
                "task_id": "orphan-task",
                "task_type": "scrape",
                "job_id": "job-orphan",
                "status": "completed",
            },
        )
        session.commit()
    monkeypatch.setattr(global_db, "global_session", ledger.session_factory)
    jobs._purge_job_tasks_sync("job-orphan", batch_size=1)
    with ledger.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT to_regclass(:leaf)"),
                {
                    "leaf": "management." + partition_name("job-orphan", "job_tasks"),
                },
            )
            is None
        )
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.job_task_identities WHERE job_id='job-orphan'"
                )
            )
            == 0
        )
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id='job-new'")
            )
            > 0
        )


@pytest.mark.parametrize("row, expected", [(('p', 'LIST (run_id)'), True), (('r', None), False), (None, False)])
def test_history_migration_preserves_existing_mutation_partition(row, expected):
    path = Path(__file__).resolve().parents[2] / "UltimaDatabases/UltimaScraperDBArchive/ultima_scraper_db_archive/migrations/alembic/versions/c92ea6407b31_partition_all_job_history.py"
    spec = importlib.util.spec_from_file_location("preserve_mutation_history", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class Connection:
        def execute(self, statement):
            assert "pg_get_partkeydef" in str(statement)
            return self

        def first(self):
            return row

    assert migration._preserve_partitioned_mutations(Connection()) is expected


def test_upgrade_does_not_copy_or_rename_existing_partitioned_mutations(monkeypatch):
    from sqlalchemy.dialects.postgresql import dialect as postgres_dialect
    from sqlalchemy.schema import Table

    path = Path(__file__).resolve().parents[2] / "UltimaDatabases/UltimaScraperDBArchive/ultima_scraper_db_archive/migrations/alembic/versions/c92ea6407b31_partition_all_job_history.py"
    spec = importlib.util.spec_from_file_location("no_mutation_rewrite", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []

    class Result:
        def first(self):
            return ('p', 'LIST (run_id)')

        def all(self):
            return []

    class Connection:
        dialect = postgres_dialect()

        def execute(self, statement, *_args):
            statements.append(str(statement))
            return Result()

        def scalar(self, statement, *_args):
            statements.append(str(statement))
            return False

        def scalars(self, statement, *_args):
            statements.append(str(statement))
            return []

        def exec_driver_sql(self, statement):
            statements.append(statement)

    monkeypatch.setattr(migration.op, "get_bind", lambda: Connection())
    monkeypatch.setattr(Table, "create", lambda *_args, **_kwargs: None)
    migration.upgrade()
    assert not any("execution_mutations_backup" in sql for sql in statements)
    assert not any("ALTER TABLE management.execution_mutations" in sql for sql in statements)
    assert not any("INSERT INTO management.execution_mutations" in sql for sql in statements)
    assert any("INSERT INTO management.job_tasks" in sql for sql in statements)
