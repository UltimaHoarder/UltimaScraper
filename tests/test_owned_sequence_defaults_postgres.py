"""Opt-in real PostgreSQL validation of the archive's owned-sequence default check.

Uses FAVOURITES_TEST_DATABASE_URL (an isolated database); never the live one.
"""

import os

import pytest
from sqlalchemy import BigInteger, Column, MetaData, Sequence, Table, create_engine, text

from ultima_scraper_db_archive.favourites_alembic import compare_owned_sequence_default

SEQ = "management.job_media_access_seq"


@pytest.fixture()
def conn():
    url = os.environ.get("FAVOURITES_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set FAVOURITES_TEST_DATABASE_URL for the isolated PostgreSQL suite")
    engine = create_engine(url)
    with engine.connect() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS management"))
        connection.execute(text(f"CREATE SEQUENCE {SEQ}"))
        # As the archive has it: the default draws from a sequence the column owns.
        connection.execute(text(
            f"CREATE TABLE management.job_media_access (id BIGINT PRIMARY KEY, seq BIGINT NOT NULL DEFAULT nextval('{SEQ}'))"
        ))
        connection.execute(text(f"ALTER SEQUENCE {SEQ} OWNED BY management.job_media_access.seq"))
        yield connection
        connection.rollback()
    engine.dispose()


def _metadata() -> MetaData:
    metadata = MetaData()
    sequence = Sequence("job_media_access_seq", schema="management")
    Table(
        "job_media_access", metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=False),
        Column("seq", BigInteger, sequence, nullable=False, server_default=sequence.next_value()),
        schema="management",
    )
    return metadata


def _diff(conn):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    context = MigrationContext.configure(conn, opts={
        "include_schemas": True,
        "compare_server_default": compare_owned_sequence_default,
        "include_object": lambda obj, name, kind, reflected, compare: kind != "table"
            or (obj.schema == "management" and name == "job_media_access"),
    })
    return [op for group in compare_metadata(context, _metadata()) for op in (group if isinstance(group, list) else [group])]


def _default_changes(ops):
    return [op for op in ops if op[0] == "modify_default" and op[2:4] == ("job_media_access", "seq")]


def test_job_media_access_seq_default_is_not_offered_again(conn):
    before = conn.execute(text(f"SELECT last_value,is_called FROM {SEQ}")).one()
    assert _default_changes(_diff(conn)) == []
    assert conn.execute(text(f"SELECT last_value,is_called FROM {SEQ}")).one() == before  # nextval never called


def test_a_missing_or_wrong_default_is_still_a_change(conn):
    conn.execute(text("ALTER TABLE management.job_media_access ALTER COLUMN seq DROP DEFAULT"))
    assert _default_changes(_diff(conn))
    conn.execute(text("CREATE SEQUENCE management.other_seq"))
    conn.execute(text("ALTER TABLE management.job_media_access ALTER COLUMN seq SET DEFAULT nextval('management.other_seq')"))
    assert _default_changes(_diff(conn))
