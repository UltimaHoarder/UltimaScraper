"""Cached statement reuse keeps SQL defaults, fresh values and atomic pages."""

import json
from uuid import uuid4

from sqlalchemy import text
from sqlmodel import Session
from test_mps_manifest import postgres_engine
from ultima_scraper_backend.database import write_receipts
from ultima_scraper_db_archive.global_db import DatabaseWriteReceiptModel

__all__ = ["postgres_engine"]


def test_receipt_pages_rebind_values_preserve_defaults_and_roll_back_together(postgres_engine):
    prefix = uuid4().hex

    def rows(label):
        return [
            {
                "command_id": f"{prefix}-{label}-{index}",
                "run_id": None,
                "operation": "upsert_user",
                "site": "onlyfans" if index % 2 else None,
                "result_json": json.dumps({"index": index, "label": label, "name": "Mañana"}),
                "post_commit_json": None,
            }
            for index in range(1001)
        ]

    table = DatabaseWriteReceiptModel.__table__
    first, second, aborted = rows("first"), rows("second"), rows("aborted")
    with Session(postgres_engine) as session:
        write_receipts._insert_receipt_rows(session, table, first)
        session.commit()
        write_receipts._insert_receipt_rows(session, table, second)
        session.commit()
        # Both the full page and the tail remain in this caller's transaction.
        write_receipts._insert_receipt_rows(session, table, aborted)
        session.rollback()
    with postgres_engine.connect() as connection:
        actual = connection.execute(
            text("SELECT command_id, run_id, site, result_json, committed_at "
                 "FROM management.database_write_receipts WHERE command_id LIKE :prefix"),
            {"prefix": f"{prefix}-%"},
        ).mappings().all()
    assert len(actual) == 2002
    expected = {row["command_id"]: row for row in first + second}
    for row in actual:
        original = expected[row["command_id"]]
        assert row["run_id"] is None and row["site"] == original["site"]
        assert json.loads(row["result_json"]) == json.loads(original["result_json"])
        assert row["committed_at"] is not None


def _multi_row_insert(session, table, records):
    """The previous VALUES insert, kept here as the equality reference."""
    from sqlalchemy import bindparam, insert

    connection = session.connection()
    columns = tuple(records[0])
    compiled = insert(table).values([
        {
            column: bindparam(f"receipt_{index}_{column}", type_=table.c[column].type)
            for column in columns
        }
        for index in range(len(records))
    ]).compile(dialect=connection.dialect)
    connection.execute(compiled, {
        f"receipt_{index}_{column}": row[column]
        for index, row in enumerate(records)
        for column in columns
    })


def test_unnest_receipt_insert_matches_multi_row_values(postgres_engine):
    import pytest
    from sqlalchemy.exc import DBAPIError

    prefix = uuid4().hex
    values = [None, "", "Mañana", "emoji 🎉", "quote ' and \\ backslash", "x" * 70_000]

    def rows(label):
        return [
            {
                "command_id": f"{prefix}-{label}-{index}",
                "run_id": None if index % 3 else f"run-{index}",
                "operation": "upsert_user",
                "site": values[index % 4],
                "result_json": values[1:][index % 5],
                "post_commit_json": values[index % 6],
            }
            for index in range(1500)
        ]

    table = DatabaseWriteReceiptModel.__table__
    with Session(postgres_engine) as session:
        _multi_row_insert(session, table, rows("old"))
        write_receipts._insert_receipt_rows(session, table, rows("new"))
        session.commit()
    with postgres_engine.connect() as connection:
        stored = connection.execute(
            text("SELECT * FROM management.database_write_receipts WHERE command_id LIKE :prefix"),
            {"prefix": f"{prefix}-%"},
        ).mappings().all()
    by_label = {"old": {}, "new": {}}
    for row in stored:
        _, label, index = row["command_id"].rsplit("-", 2)
        by_label[label][int(index)] = {
            key: value for key, value in row.items() if key not in {"command_id", "committed_at"}
        }
        assert row["committed_at"] is not None
    assert len(by_label["new"]) == 1500
    assert by_label["new"] == by_label["old"]

    # Overlong values still fail on the column, not by silent truncation.
    overlong = [{**rows("long")[0], "site": "s" * 65}]
    for insert_rows in (_multi_row_insert, write_receipts._insert_receipt_rows):
        with Session(postgres_engine) as session, pytest.raises(DBAPIError, match="too long"):
            insert_rows(session, table, overlong)
