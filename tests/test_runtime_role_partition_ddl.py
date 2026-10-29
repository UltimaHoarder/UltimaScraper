"""A DML-only runtime role manages job partitions through owner functions."""

import importlib.util
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from test_execution_ledger import _churn_queue, ledger, ledger_engine, postgres_engine
from test_history_partition_admission import partitioned_engine
from ultima_scraper_backend.database.history_compaction import _truncate_function
from ultima_scraper_backend.database.job_partitions import (
    HISTORY_TABLES,
    _drop_partition,
    _owned_partition,
    ensure_history_partitions,
    partition_name,
)
from ultima_scraper_backend.job_system import ledger as ledger_module
from ultima_scraper_backend.job_system.ledger import ExecutionLedger, Limits

__all__ = ["ledger", "ledger_engine", "partitioned_engine", "postgres_engine"]

VERSIONS = (
    Path(__file__).resolve().parents[2]
    / "UltimaDatabases/UltimaScraperDBArchive/ultima_scraper_db_archive/migrations/alembic/versions"
)
MIGRATIONS = (
    VERSIONS / "b7c41e9a2d58_runtime_role_partition_ddl.py",
    VERSIONS / "c8a3e5f71d26_runtime_role_history_truncate.py",
)


@pytest.fixture(scope="module")
def runtime_engine(partitioned_engine):
    with partitioned_engine.begin() as connection:
        connection.execute(text("""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'usr_runtime') THEN
                CREATE ROLE usr_runtime LOGIN;
              END IF;
            END $$;
            GRANT USAGE ON SCHEMA management, onlyfans TO usr_runtime;
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA management, onlyfans TO usr_runtime;
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA management, onlyfans TO usr_runtime;
            ALTER DEFAULT PRIVILEGES IN SCHEMA management GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO usr_runtime;
        """))
        for path in MIGRATIONS:
            spec = importlib.util.spec_from_file_location("runtime_role_" + path.stem, path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
    engine = create_engine(
        partitioned_engine.url.set(username="usr_runtime"),
        connect_args={"options": "-c search_path=onlyfans,management,public"},
    )
    yield engine
    engine.dispose()


def test_the_runtime_role_cannot_run_partition_ddl_itself(runtime_engine):
    with runtime_engine.connect() as connection, pytest.raises(ProgrammingError, match="permission denied"):
        connection.execute(text("CREATE TABLE management.usr_runtime_probe (id int)"))


def test_partitions_attach_drop_and_roll_back_through_owner_functions(runtime_engine):
    run = "job-runtime-role"
    with Session(runtime_engine) as session:
        ensure_history_partitions(session, run)
        session.rollback()  # Atomic with the caller's transaction.
    with Session(runtime_engine) as session:
        for table in HISTORY_TABLES:
            assert not _owned_partition(session, run, table)
        ensure_history_partitions(session, run)
        session.commit()
    with Session(runtime_engine) as session:
        for table in HISTORY_TABLES:
            assert _owned_partition(session, run, table)
            leaf = "management." + partition_name(run, table)
            # The owner creates the leaf; default privileges let the runtime role use it.
            assert session.scalar(
                text("SELECT has_table_privilege('usr_runtime', :leaf, 'INSERT')"), {"leaf": leaf}
            )
        for table in HISTORY_TABLES:
            assert _drop_partition(session, run, table)
        session.commit()
    with Session(runtime_engine) as session:
        assert not any(_owned_partition(session, run, table) for table in HISTORY_TABLES)


def test_owner_functions_accept_only_their_own_partitions(runtime_engine, partitioned_engine):
    with partitioned_engine.begin() as owner:
        owner.execute(text("CREATE TABLE IF NOT EXISTS management.usr_not_a_partition (id int)"))
    with Session(runtime_engine) as session:
        for statement in (
            "SELECT management.usr_attach_history_partition('users', 'job-x')",
            "SELECT management.usr_attach_history_partition('job_tasks', '')",
            "SELECT management.usr_truncate_outbox_partition('usr_not_a_partition')",
            "SELECT management.usr_truncate_outbox_partition('execution_outbox_job_'"
            " || repeat('0', 32))",
        ):
            with pytest.raises(Exception, match="Unknown history table|run ID|Not an execution_outbox"):
                session.execute(text(statement))
            session.rollback()
        # Dropping a run without its own leaf is refused, not an error.
        assert session.scalar(text("SELECT management.usr_drop_history_partition('job_tasks', 'job-none')")) is False
    with partitioned_engine.connect() as owner:
        assert owner.scalar(text("SELECT to_regclass('management.usr_not_a_partition')")) is not None


def test_empty_outbox_partitions_are_truncated_by_the_runtime_role(runtime_engine):
    run = "job-runtime-outbox"
    with Session(runtime_engine) as session:
        ensure_history_partitions(session, run)
        session.commit()
        leaf = partition_name(run, "execution_outbox")
        session.execute(text("SELECT management.usr_truncate_outbox_partition(:leaf)"), {"leaf": leaf})
        session.commit()
        for table in HISTORY_TABLES:
            _drop_partition(session, run, table)
        session.commit()


def test_history_leaves_are_truncated_by_the_runtime_role(runtime_engine):
    run = "job-runtime-compaction"
    tasks_leaf = "management." + partition_name(run, "job_tasks")
    attempts_leaf = "management." + partition_name(run, "execution_attempts")
    with Session(runtime_engine) as session:
        ensure_history_partitions(session, run)
        session.commit()
        with pytest.raises(ProgrammingError, match="permission denied"):
            session.execute(text(f"TRUNCATE {attempts_leaf}, {tasks_leaf}"))
        session.rollback()
        assert _truncate_function(session)
        session.execute(text("SELECT management.usr_truncate_history_partitions(:run)"), {"run": run})
        session.commit()
        # A run without its own leaves is refused.
        with pytest.raises(Exception, match="does not own its history partitions"):
            session.execute(text("SELECT management.usr_truncate_history_partitions('job-none')"))
        session.rollback()
        for table in HISTORY_TABLES:
            _drop_partition(session, run, table)
        session.commit()


def test_queue_reindex_uses_the_owner_url(runtime_engine, partitioned_engine, ledger, monkeypatch):
    _churn_queue(ledger)

    @contextmanager
    def runtime_sessions():
        with Session(runtime_engine) as session:
            yield session

    runtime_ledger = ExecutionLedger(runtime_sessions, limits=Limits(tasks=4, global_tasks=8, batch=4))
    monkeypatch.delenv("ULTIMA_ARCHIVE_OWNER_DATABASE_URL", raising=False)
    # As the runtime role REINDEX fails (it is not the owner), leaving nothing rebuilt.
    assert runtime_ledger.reindex_bloated_queue_indexes(threshold_bytes=256 * 1024, limit=1) == []
    monkeypatch.setenv(
        "ULTIMA_ARCHIVE_OWNER_DATABASE_URL",
        partitioned_engine.url.render_as_string(hide_password=False),
    )
    ledger_module._OWNER_ENGINES.clear()
    rebuilt = runtime_ledger.reindex_bloated_queue_indexes(threshold_bytes=256 * 1024, limit=1)
    assert len(rebuilt) == 1 and rebuilt[0]["after_bytes"] < rebuilt[0]["before_bytes"]


def test_site_sessions_scope_search_path_to_each_transaction(partitioned_engine):
    from types import SimpleNamespace

    from ultima_scraper_backend.manager import BackendManager

    owner = SimpleNamespace(engine=partitioned_engine)
    with partitioned_engine.connect() as connection:
        default = connection.scalar(text("SHOW search_path"))
    session_cm = BackendManager._site_session(owner, "onlyfans")
    with session_cm as session:
        assert session.scalar(text("SHOW search_path")) == "onlyfans, public"
        session.commit()
        # A later transaction (another server link under transaction pooling).
        assert session.scalar(text("SHOW search_path")) == "onlyfans, public"
        session.rollback()
    # Nothing leaks to the pooled connection the session used.
    with partitioned_engine.connect() as connection:
        assert connection.scalar(text("SHOW search_path")) == default
