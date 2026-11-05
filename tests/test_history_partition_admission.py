"""Native PostgreSQL partition admission while backup readers hold locks."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import ultima_scraper_db_archive
from threading import Event

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, text
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from ultima_scraper_backend.database.job_partitions import (
    HISTORY_TABLES,
    _owned_partition,
    ensure_history_partition,
    partition_name,
)
from ultima_scraper_backend.database.mps_manifest import MPSManifestStore

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


@pytest.fixture(scope="module")
def partitioned_engine(ledger_engine):
    path = (
        Path(ultima_scraper_db_archive.__file__).parent / "migrations/alembic/versions/c92ea6407b31_partition_all_job_history.py"
    )
    spec = importlib.util.spec_from_file_location("admission_history_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with (
        ledger_engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.upgrade()
    return ledger_engine


def test_job_submission_coexists_with_backup_parent_locks(
    ledger, partitioned_engine, monkeypatch
):
    # pg_dump keeps ACCESS SHARE locks for its snapshot. Keep them open across
    # ordinary submission, using another connection and the normal DDL path.
    sessions = ledger.session_factory

    @contextmanager
    def bounded_sessions():
        with sessions() as session:
            session.execute(text("SET LOCAL lock_timeout='250ms'"))
            session.execute(text("SET LOCAL statement_timeout='3s'"))
            yield session

    monkeypatch.setattr(ledger, "session_factory", bounded_sessions)
    with partitioned_engine.begin() as backup:
        for table in HISTORY_TABLES:
            backup.execute(text(f"LOCK TABLE management.{table} IN ACCESS SHARE MODE"))
        submit(ledger, [task()], identity="job-during-backup")
        with ledger.session_factory() as session:
            for table in HISTORY_TABLES:
                assert _owned_partition(session, "job-during-backup", table)
                leaf = "management." + partition_name("job-during-backup", table)
                # ATTACH must retain the global identity guards and indexes.
                parent_indexes = session.scalar(
                    text(
                        "SELECT count(*) FROM pg_index WHERE indrelid=to_regclass(:parent)"
                    ),
                    {"parent": "management." + table},
                )
                attached_indexes = session.scalar(
                    text("""SELECT count(*) FROM pg_index i JOIN pg_inherits h ON h.inhrelid=i.indexrelid
                        WHERE i.indrelid=to_regclass(:leaf)"""),
                    {"leaf": leaf},
                )
                assert attached_indexes == parent_indexes
                if table != "execution_mutations":
                    assert (
                        session.scalar(
                            text("""SELECT count(*) FROM pg_trigger WHERE tgrelid=to_regclass(:leaf)
                            AND tgname='history_identity_guard' AND tgparentid<>0"""),
                            {"leaf": leaf},
                        )
                        == 1
                    )
            assert (
                session.scalar(
                    text("""SELECT count(*) FROM pg_constraint WHERE conrelid=to_regclass(:leaf)
                    AND contype='f' AND conparentid<>0"""),
                    {
                        "leaf": "management."
                        + partition_name("job-during-backup", "execution_mutations")
                    },
                )
                > 0
            )


def test_partition_create_and_attach_roll_back_together(ledger, partitioned_engine):
    identity = "job-partition-rollback"
    leaf = "management." + partition_name(identity)
    with ledger.session_factory() as session:
        assert ensure_history_partition(session, identity, "execution_mutations")
        assert _owned_partition(session, identity)
        session.rollback()
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT to_regclass(:leaf)"), {"leaf": leaf}) is None
        assert ensure_history_partition(session, identity, "execution_mutations")
        assert ensure_history_partition(session, identity, "execution_mutations")
        assert _owned_partition(session, identity)
        session.commit()


def test_failed_admission_rolls_back_partitions_and_run(
    ledger, partitioned_engine, monkeypatch
):
    from ultima_scraper_backend.job_system import ledger as ledger_module

    identity = "job-failed-partition-admission"

    def fail_event(*args, **kwargs):
        raise RuntimeError("Admission interrupted after run insert")

    with monkeypatch.context() as patch:
        patch.setattr(ledger_module, "_event", fail_event)
        with pytest.raises(RuntimeError, match="Admission interrupted"):
            submit(ledger, [task()], identity=identity)
    with ledger.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.execution_runs WHERE run_id=:run"
                ),
                {"run": identity},
            )
            == 0
        )
        for table in HISTORY_TABLES:
            assert (
                session.scalar(
                    text("SELECT to_regclass(:leaf)"),
                    {
                        "leaf": "management." + partition_name(identity, table),
                    },
                )
                is None
            )
    submit(ledger, [task()], identity=identity)
    with ledger.session_factory() as session:
        for table in HISTORY_TABLES:
            assert _owned_partition(session, identity, table)


@pytest.mark.parametrize(
    "first_kind,second_kind",
    [
        ("ordinary", "ordinary"),
        ("ordinary", "mps"),
        ("mps", "ordinary"),
        ("mps", "mps"),
    ],
)
def test_concurrent_admissions_take_ddl_fence_before_run_insert(
    ledger, partitioned_engine, first_kind, second_kind
):
    # Pause the DDL owner until a second admission reaches the same fence.
    # If the waiter has already inserted execution_runs, ATTACH's foreign-key
    # setup waits for its RowExclusiveLock and forms the reported deadlock.
    first_locked, second_waiting = Event(), Event()
    first_id = f"job-concurrent-{first_kind}-{second_kind}-first"
    second_id = f"job-concurrent-{first_kind}-{second_kind}-second"
    sessions = ledger.session_factory

    @contextmanager
    def bounded_sessions():
        with sessions() as session:
            session.execute(text("SET LOCAL lock_timeout='2s'"))
            session.execute(text("SET LOCAL statement_timeout='8s'"))
            yield session

    ledger.session_factory = bounded_sessions

    def before_execute(connection, cursor, statement, parameters, context, many):
        if (
            "pg_advisory_xact_lock(hashtextextended('mutation-partition-ddl'"
            in statement
        ):
            if first_locked.is_set():
                second_waiting.set()
            else:
                connection.info["first_admission_fence"] = True

    def after_execute(connection, cursor, statement, parameters, context, many):
        if (
            "pg_advisory_xact_lock(hashtextextended('mutation-partition-ddl'"
            in statement
        ) and connection.info.pop("first_admission_fence", False):
            first_locked.set()
            assert second_waiting.wait(5), "Second admission never reached DDL fence"

    def create(kind, identity):
        if kind == "ordinary":
            return submit(ledger, [task(identity + "-task")], identity=identity)
        return MPSManifestStore(ledger.session_factory).create(
            job_id=identity,
            site="onlyfans",
            job_config={"name": identity, "metadata": {}},
            selection={"start_id": 1, "end_id": 2},
            proxy_pool=[],
            site_session_factory=ledger.session_factory,
        )

    event.listen(partitioned_engine, "before_cursor_execute", before_execute)
    event.listen(partitioned_engine, "after_cursor_execute", after_execute)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(create, first_kind, first_id)
            assert first_locked.wait(5), "First admission never acquired DDL fence"
            second = pool.submit(create, second_kind, second_id)
            first.result(timeout=12)
            second.result(timeout=12)
    finally:
        event.remove(partitioned_engine, "before_cursor_execute", before_execute)
        event.remove(partitioned_engine, "after_cursor_execute", after_execute)
    with ledger.session_factory() as session:
        for identity in (first_id, second_id):
            assert (
                session.scalar(
                    text(
                        "SELECT count(*) FROM management.execution_runs WHERE run_id=:run"
                    ),
                    {"run": identity},
                )
                == 1
            )
            for table in HISTORY_TABLES:
                assert _owned_partition(session, identity, table)
