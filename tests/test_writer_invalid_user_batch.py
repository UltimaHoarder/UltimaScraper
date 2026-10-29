"""Native invalid-user batch behavior in a disposable PostgreSQL schema."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import MetaData, event, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlmodel import Session
from test_database_write_executor import _command
from test_mps_manifest import postgres_engine
from ultima_scraper_backend.database import write_receipts
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.database.write_queue import (
    WRITE_TIMING_KEY,
    DatabaseWriteOperation,
)
from ultima_scraper_db_archive import InvalidUserModel

__all__ = ["postgres_engine"]


@pytest.fixture
def invalid_runtime(postgres_engine, monkeypatch):
    from ultima_scraper_db_archive import global_db

    with postgres_engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS writer_invalid_test"))
        InvalidUserModel.__table__.to_metadata(
            MetaData(), schema="writer_invalid_test"
        ).create(connection, checkfirst=True)
        connection.execute(text("TRUNCATE writer_invalid_test.invalid_users"))
        connection.execute(text("TRUNCATE management.database_write_receipts"))

    @contextmanager
    def session_factory():
        with Session(postgres_engine) as session:
            session.execute(text("SET LOCAL search_path=writer_invalid_test,public"))
            yield session

    monkeypatch.setattr(global_db, "global_session", session_factory)
    executor = PostgreSQLWriteExecutor.__new__(PostgreSQLWriteExecutor)
    executor._site_manager = lambda site: SimpleNamespace(get_session=session_factory)
    return SimpleNamespace(
        executor=executor, session=session_factory, engine=postgres_engine
    )


def invalid_command(command_id, user_id, *, reason="not_found", checked_at=None):
    return _command(
        command_id,
        DatabaseWriteOperation.UPSERT_INVALID_USER,
        {
            "user_id": user_id,
            "reason": reason,
            "checked_at": checked_at or "2026-10-04T03:00:00Z",
        },
    )


def test_invalid_batch_preserves_existing_and_new_row_timestamps(invalid_runtime):
    first_seen = datetime(2026, 1, 1, tzinfo=UTC)
    with invalid_runtime.session() as session:
        session.execute(
            text(
                "INSERT INTO invalid_users(site,user_id,reason,first_seen_at,last_checked_at) "
                "VALUES ('onlyfans',1,'old',:seen,:seen)"
            ),
            {"seen": first_seen},
        )
        original_id = session.execute(text("SELECT id FROM invalid_users")).scalar_one()
        session.commit()
    commands = [invalid_command("existing", 1), invalid_command("new", 2, reason="")]
    results = invalid_runtime.executor._upsert_invalid_users(commands, "onlyfans")
    assert all(results[command.command_id]["upserted"] for command in commands)
    assert all(
        results[command.command_id][WRITE_TIMING_KEY]["execution_measured"]
        for command in commands
    )
    assert all(
        results[command.command_id][WRITE_TIMING_KEY]["commit_measured"]
        for command in commands
    )
    with invalid_runtime.session() as session:
        rows = (
            session.execute(text("SELECT * FROM invalid_users ORDER BY user_id"))
            .mappings()
            .all()
        )
    assert rows[0]["id"] == original_id and rows[0]["first_seen_at"] == first_seen
    assert rows[0]["updated_at"] == rows[0]["last_checked_at"]
    assert rows[1]["updated_at"] is None
    assert [row["reason"] for row in rows] == ["not_found", "not_found"]


def test_duplicate_records_preserve_last_command_order_and_replay(invalid_runtime):
    commands = [
        invalid_command("first", 10, checked_at="2026-10-04T03:00:00Z"),
        invalid_command(
            "last", 10, reason="deleted", checked_at="2026-10-04T02:00:00Z"
        ),
    ]
    invalid_runtime.executor._upsert_invalid_users(commands, "onlyfans")
    with invalid_runtime.session() as session:
        before = dict(
            session.execute(text("SELECT * FROM invalid_users")).mappings().one()
        )
    assert before["reason"] == "deleted"
    assert before["last_checked_at"] == datetime(2026, 10, 4, 2, tzinfo=UTC)
    assert before["updated_at"] == before["last_checked_at"]
    invalid_runtime.executor._upsert_invalid_users(list(reversed(commands)), "onlyfans")
    with invalid_runtime.session() as session:
        after = dict(
            session.execute(text("SELECT * FROM invalid_users")).mappings().one()
        )
    assert after == before
    assert all(
        result.success for result in write_receipts.lookup(["first", "last"]).values()
    )


def test_invalid_row_failure_rolls_back_siblings_and_receipts(invalid_runtime):
    commands = [
        invalid_command("good", 20),
        invalid_command("bad", 21, reason="x" * 129),
    ]
    with pytest.raises(DataError):
        invalid_runtime.executor._upsert_invalid_users(commands, "onlyfans")
    with invalid_runtime.session() as session:
        assert (
            session.execute(text("SELECT count(*) FROM invalid_users")).scalar_one()
            == 0
        )
    assert write_receipts.lookup(["good", "bad"]) == {}


def test_later_duplicate_cannot_hide_an_invalid_earlier_mutation(invalid_runtime):
    commands = [
        invalid_command("bad-first", 25, reason="x" * 129),
        invalid_command("valid-last", 25),
    ]
    with pytest.raises(DataError):
        invalid_runtime.executor._upsert_invalid_users(commands, "onlyfans")
    with invalid_runtime.session() as session:
        assert (
            session.execute(text("SELECT count(*) FROM invalid_users")).scalar_one()
            == 0
        )
    assert write_receipts.lookup(["bad-first", "valid-last"]) == {}


def test_receipt_failure_rolls_back_already_executed_invalid_upsert(invalid_runtime):
    with invalid_runtime.engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE management.database_write_receipts ADD CONSTRAINT invalid_fixture_reject "
                "CHECK (command_id <> 'reject-receipt')"
            )
        )
    commands = [invalid_command("sibling", 30), invalid_command("reject-receipt", 31)]
    try:
        with pytest.raises(IntegrityError):
            invalid_runtime.executor._upsert_invalid_users(commands, "onlyfans")
        with invalid_runtime.session() as session:
            assert (
                session.execute(text("SELECT count(*) FROM invalid_users")).scalar_one()
                == 0
            )
        assert write_receipts.lookup(["sibling", "reject-receipt"]) == {}
    finally:
        with invalid_runtime.engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE management.database_write_receipts DROP CONSTRAINT invalid_fixture_reject"
                )
            )


@pytest.mark.parametrize("count", [1, 30, 100])
def test_invalid_batch_uses_one_mutation_statement(invalid_runtime, count):
    commands = [invalid_command(f"batch-{i}", 1_000 + i) for i in range(count)]
    statements = []

    def executed(conn, cursor, statement, parameters, context, many):
        if "invalid_users" in statement:
            statements.append(statement)

    event.listen(invalid_runtime.engine, "after_cursor_execute", executed)
    try:
        invalid_runtime.executor._upsert_invalid_users(commands, "onlyfans")
    finally:
        event.remove(invalid_runtime.engine, "after_cursor_execute", executed)
    assert len(statements) == 1
    assert "ON CONFLICT" in statements[0]

