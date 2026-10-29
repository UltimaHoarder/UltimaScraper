"""Transaction-pool setup against a private PostgreSQL cluster, never deployment."""

from contextlib import contextmanager

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from test_mps_manifest import postgres_engine
from ultima_scraper_backend.database.managers import postgres_manager

__all__ = ["postgres_engine"]

SETTINGS_QUERY = """
SELECT current_setting('search_path'),
       current_setting('statement_timeout'),
       current_setting('lock_timeout'),
       current_setting('idle_in_transaction_session_timeout'),
       current_setting('transaction_read_only')
"""


@pytest.fixture
def manager_factory(postgres_engine, monkeypatch):
    # Exercise the real transaction begin hook against our private socket. This
    # fixture does not install or claim to benchmark a PgBouncer server.
    monkeypatch.setattr(
        postgres_manager,
        "runtime_env_value",
        lambda key: {
            "ULTIMA_USE_PGBOUNCER": "true",
            "ULTIMA_DATABASE_WRITER_CONCURRENCY": "8",
        }.get(key),
    )
    managers = []

    def create(*, role="writer", read_only=False, idle_ms=120_000, concurrency=1):
        manager = postgres_manager.PostgreSQLDatabaseManager(
            "onlyfans",
            postgres_engine.url.render_as_string(hide_password=False),
            pool_role=role,
            read_only=read_only,
            pool_size=concurrency,
            max_overflow=0,
        )
        manager.pool_size = concurrency
        manager.idle_in_transaction_timeout_ms = idle_ms
        manager.connect()
        managers.append(manager)
        return manager

    yield create
    for manager in managers:
        manager.close()


@contextmanager
def without_begin_hook(engine):
    # Raw DBAPI access observes the same pooled connection after transaction
    # end without silently reapplying the settings under test.
    raw = engine.raw_connection()
    old_autocommit = raw.driver_connection.autocommit
    raw.driver_connection.autocommit = True
    try:
        with raw.cursor() as cursor:
            yield cursor
    finally:
        raw.driver_connection.autocommit = old_autocommit
        raw.close()


@pytest.mark.parametrize("end", ["commit", "rollback"])
@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize("idle_ms", [0, 120_000])
def test_local_settings_and_read_only_reset_after_transaction(
    manager_factory, end, read_only, idle_ms
):
    manager = manager_factory(
        role="application" if read_only else "writer",
        read_only=read_only,
        idle_ms=idle_ms,
    )
    with without_begin_hook(manager.engine) as cursor:
        cursor.execute(SETTINGS_QUERY)
        baseline = cursor.fetchone()
        cursor.execute("SELECT pg_backend_pid()")
        backend_pid = cursor.fetchone()[0]
    setup_calls = []

    def executed(conn, cursor, statement, parameters, context, many):
        if statement.startswith("SET LOCAL search_path TO onlyfans, public"):
            setup_calls.append(statement)

    event.listen(manager.engine, "after_cursor_execute", executed)
    try:
        with manager.get_session() as session:
            current = session.execute(text(SETTINGS_QUERY)).one()
            assert tuple(current) == (
                "onlyfans, public",
                "90s",
                "10s",
                "2min" if idle_ms else baseline[3],
                "on" if read_only else "off",
            )
            assert session.execute(text("SELECT count(*) FROM users")).scalar_one() >= 0
            # An altered local setting must also disappear at transaction end.
            session.execute(text("SET LOCAL search_path TO public"))
            getattr(session, end)()
        assert len(setup_calls) == 1
    finally:
        event.remove(manager.engine, "after_cursor_execute", executed)
    with without_begin_hook(manager.engine) as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        after_pid = cursor.fetchone()[0]
        if read_only:
            # Application readers deliberately retain NullPool, so this is a
            # fresh server session in our direct PostgreSQL fixture.
            assert after_pid != backend_pid
        else:
            assert after_pid == backend_pid
        cursor.execute(SETTINGS_QUERY)
        assert cursor.fetchone() == baseline
    # Reuse after closing a multi-result setup cursor must configure a fresh
    # transaction and leave later parameterized statements working normally.
    with manager.get_session() as session:
        assert (
            session.execute(text("SELECT :value"), {"value": 123}).scalar_one() == 123
        )
        assert (
            session.execute(text("SHOW search_path")).scalar_one() == "onlyfans, public"
        )


@pytest.mark.parametrize("role", ["application", "worker_reader"])
def test_read_only_setup_rejects_mutation_and_recovers(manager_factory, role):
    manager = manager_factory(role=role, read_only=True)
    with manager.get_session() as session:
        with pytest.raises(DBAPIError) as error:
            session.execute(text("INSERT INTO users(id) VALUES (910001)"))
        assert error.value.orig.sqlstate == "25006"
        session.rollback()
        assert session.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        assert (
            session.execute(
                text("SELECT count(*) FROM users WHERE id=910001")
            ).scalar_one()
            == 0
        )


def test_batched_setup_preserves_statement_timeout(manager_factory):
    manager = manager_factory()
    manager.statement_timeout_ms = 25
    with manager.get_session() as session:
        with pytest.raises(DBAPIError) as error:
            session.execute(text("SELECT pg_sleep(0.2)"))
        assert error.value.orig.sqlstate == "57014"
        session.rollback()
        assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_batched_setup_preserves_lock_timeout(manager_factory, postgres_engine):
    manager = manager_factory()
    manager.lock_timeout_ms = 25
    manager.statement_timeout_ms = 1000
    with postgres_engine.begin() as connection:
        connection.execute(text("INSERT INTO onlyfans.users(id) VALUES (910002)"))
    with postgres_engine.connect() as blocker:
        blocker.execute(
            text("UPDATE onlyfans.users SET last_checked_at=now() WHERE id=910002")
        )
        with manager.get_session() as session:
            with pytest.raises(DBAPIError) as error:
                session.execute(
                    text("UPDATE users SET last_checked_at=now() WHERE id=910002")
                )
            assert error.value.orig.sqlstate == "55P03"
            session.rollback()
            assert session.execute(text("SELECT 1")).scalar_one() == 1
        blocker.rollback()
