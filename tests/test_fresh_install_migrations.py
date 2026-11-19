"""A fresh database must migrate through every revision to the model schema."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import create_engine, text

import test_mps_manifest as fixtures

postgres_engine = fixtures.postgres_engine

SITES = ("darkfans", "fansly", "loyalfans", "onlyfans", "privacy")


@pytest.fixture
def fresh_database_url(postgres_engine):
    host = postgres_engine.url.query["host"]
    with postgres_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(text('DROP DATABASE IF EXISTS "usr_fresh_install"'))
        connection.execute(text('CREATE DATABASE "usr_fresh_install"'))
    url = f"postgresql+psycopg://usr_test@/usr_fresh_install?host={host}"
    # Installation prepares the extension and schemas before running Alembic.
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        for schema in (*SITES, "management"):
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine.dispose()
    yield url
    with postgres_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(text('DROP DATABASE IF EXISTS "usr_fresh_install" WITH (FORCE)'))


def _upgrade(url: str) -> None:
    from alembic import command
    from ultima_scraper_db_archive.migration_cli import MIGRATION_BUNDLE

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            config = MIGRATION_BUNDLE.create_config(url)
            config.attributes["connection"] = connection
            command.upgrade(config, "heads")
            if connection.in_transaction():
                connection.commit()
    finally:
        engine.dispose()


def _schema_objects(connection, schema: str) -> set[tuple[str, str]]:
    """Columns, constraints, indexes and sequences, with the schema's own
    name written as SITE so two site schemas compare equal."""
    import re

    connection.execute(text("SET search_path TO pg_catalog"))
    rows = connection.execute(
        text(
            """
            SELECT 'col', c.relname || '.' || a.attname || ' ' || format_type(a.atttypid, a.atttypmod)
                   || ' ' || a.attnotnull || ' ' || coalesce(pg_get_expr(d.adbin, d.adrelid), '')
              FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
             WHERE n.nspname = :s AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
            UNION ALL
            SELECT 'con', t.relname || ' ' || c.conname || ' ' || pg_get_constraintdef(c.oid)
              FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = :s AND c.contype <> 'n'
            UNION ALL
            SELECT 'idx', pg_get_indexdef(i.indexrelid)
              FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = :s
            UNION ALL
            SELECT 'seq', c.relname || ' ' || format_type(q.seqtypid, NULL)
              FROM pg_sequence q JOIN pg_class c ON c.oid = q.seqrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = :s
            """
        ),
        {"s": schema},
    )
    word = re.compile(rf"(?<![A-Za-z0-9]){schema}(?![A-Za-z0-9])")
    return {(kind, word.sub("SITE", value)) for kind, value in rows}


def test_new_site_schemas_copy_loyalfans_and_start_cut_over(
    fresh_database_url, monkeypatch
):
    """b5e1c9d3a7f2 copies loyalfans for privacy and darkfans, sequences
    their own, and adds favourites partitions already cut over."""
    monkeypatch.setenv("USR_SECRET_KEY", "fresh-install-fixture-key")
    _upgrade(fresh_database_url)
    engine = create_engine(fresh_database_url)
    try:
        with engine.connect() as connection:
            template = _schema_objects(connection, "loyalfans")
            assert len(template) > 100
            for site in ("privacy", "darkfans"):
                assert _schema_objects(connection, site) == template
            connection.execute(text("SET search_path TO public"))
            # Each copy draws ids from its own sequences.
            shared = connection.execute(
                text(
                    "SELECT count(*) FROM pg_attrdef d JOIN pg_class c ON c.oid = d.adrelid"
                    " JOIN pg_namespace n ON n.oid = c.relnamespace"
                    " WHERE n.nspname IN ('privacy', 'darkfans')"
                    " AND pg_get_expr(d.adbin, d.adrelid) LIKE '%loyalfans%'"
                )
            ).scalar()
            assert shared == 0
            assert connection.execute(
                text(
                    "SELECT array_agg(site ORDER BY site) FROM management.favourites_migration"
                    " WHERE active AND site IN ('privacy', 'darkfans')"
                )
            ).scalar() == ["darkfans", "privacy"]
            partitions = connection.execute(
                text(
                    "SELECT count(*) FROM pg_class WHERE relkind IN ('r', 'p')"
                    " AND (relname LIKE 'favourites_privacy%' OR relname LIKE 'favourites_darkfans%')"
                )
            ).scalar()
            assert partitions == 10  # a site partition and four kinds, each
    finally:
        engine.dispose()


def test_job_account_ids_hold_fansly_ids(fresh_database_url, monkeypatch):
    """c7d2e4f6a8b1: an 18-digit Fansly account id fits a job and its tasks."""
    monkeypatch.setenv("USR_SECRET_KEY", "fresh-install-fixture-key")
    _upgrade(fresh_database_url)
    engine = create_engine(fresh_database_url)
    try:
        with engine.connect() as connection:
            types = dict(
                connection.execute(
                    text(
                        "SELECT c.relname || '.' || a.attname, format_type(a.atttypid, a.atttypmod)"
                        " FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
                        " JOIN pg_namespace n ON n.oid = c.relnamespace"
                        " WHERE n.nspname = 'management' AND a.attnum > 0"
                        " AND (c.relname, a.attname) IN"
                        " (('job_tasks', 'auth_id'), ('jobs', 'user_auth_id'))"
                    )
                ).all()
            )
            assert types == {"job_tasks.auth_id": "bigint", "jobs.user_auth_id": "bigint"}
    finally:
        engine.dispose()


def test_fresh_install_reaches_head_with_model_named_indexes(
    fresh_database_url, monkeypatch
):
    from alembic import command
    from ultima_scraper_db_archive.migration_cli import MIGRATION_BUNDLE

    monkeypatch.setenv("USR_SECRET_KEY", "fresh-install-fixture-key")
    # The API runs these migrations in-process; they must not reconfigure it.
    host_logger = logging.getLogger("ultima_scraper_backend.fresh_install_probe")
    root_handlers = list(logging.getLogger().handlers)
    assert root_handlers, "pytest installs root handlers like a configured host"
    engine = create_engine(fresh_database_url)
    try:
        with engine.connect() as connection:
            config = MIGRATION_BUNDLE.create_config(fresh_database_url)
            config.attributes["connection"] = connection
            command.upgrade(config, "heads")
            if connection.in_transaction():
                connection.commit()
        with engine.connect() as connection:
            indexes = {
                (schema, name)
                for schema, name in connection.execute(
                    text(
                        "SELECT schemaname, indexname FROM pg_indexes "
                        "WHERE tablename = 'websites' AND indexdef LIKE '%(user_id)'"
                    )
                )
            }
    finally:
        engine.dispose()
    assert not host_logger.disabled
    assert logging.getLogger().handlers == root_handlers
    # de82a96c410f keeps the model's named index and drops ix_* duplicates.
    assert indexes == {(site, "idx_websites_user_id") for site in SITES}
