"""A fresh database must migrate through every revision to the model schema."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import create_engine, text

import test_mps_manifest as fixtures

postgres_engine = fixtures.postgres_engine

SITES = ("fansly", "loyalfans", "onlyfans")


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
