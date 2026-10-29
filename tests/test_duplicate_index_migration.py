"""Verify index removal against historical DDL in an owned PostgreSQL cluster."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, text

import test_mps_manifest as postgres_fixtures

postgres_engine = postgres_fixtures.postgres_engine


def load_migration(filename):
    import ultima_scraper_db_archive

    path = (
        Path(ultima_scraper_db_archive.__file__).parent
        / "migrations/alembic/versions"
        / filename
    )
    spec = importlib.util.spec_from_file_location("index_fixture_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def index_engine(postgres_engine):
    database = "indexes_" + uuid4().hex
    with postgres_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(text(f"CREATE DATABASE {database}"))
    engine = create_engine(postgres_engine.url.set(database=database))
    try:
        with engine.begin() as connection:
            for schema in ("onlyfans", "fansly", "loyalfans", "management"):
                connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text("CREATE EXTENSION pg_trgm WITH SCHEMA public"))
            # Run the actual historical definitions, without loading env.py or
            # any configured database URL. No copied migration logic in tests.
            for filename in (
                "d4518195deef_initial_migration.py",
                "21a95ba68935_add_orders_to_management_2.py",
                "f2c4e8a1b9d7_add_websites_table_to_site_schemas.py",
            ):
                migration = load_migration(filename)
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
            connection.execute(
                text("INSERT INTO onlyfans.users(id) SELECT generate_series(1, 1000)")
            )
            connection.execute(
                text(
                    "INSERT INTO onlyfans.media(id,user_id,category,created_at) "
                    "SELECT i, (i % 1000)+1, 'image', now() FROM generate_series(1,100000) i"
                )
            )
            connection.execute(text("ANALYZE onlyfans.media"))
        yield engine
    finally:
        engine.dispose()
        with postgres_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.execute(text(f"DROP DATABASE {database}"))


@pytest.fixture
def migration_connection(index_engine):
    migration = load_migration("de82a96c410f_remove_verified_duplicate_indexes.py")
    with index_engine.connect() as connection:
        transaction = connection.begin()
        try:
            migration.op = Operations(MigrationContext.configure(connection))
            yield migration, connection
        finally:
            transaction.rollback()


def inventory(connection):
    return dict(
        connection.execute(
            text(
                "SELECT schemaname || '.' || indexname, indexdef FROM pg_indexes "
                "WHERE schemaname IN ('onlyfans','fansly','loyalfans','management')"
            )
        ).all()
    )


def plan_nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from plan_nodes(child)


def media_plan(connection):
    return connection.execute(
        text(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
            "SELECT id FROM onlyfans.media WHERE user_id=999"
        )
    ).scalar_one()[0]["Plan"]


def test_historical_indexes_upgrade_downgrade_and_query_plan(migration_connection):
    migration, connection = migration_connection
    before = inventory(connection)
    selected = {
        f"{schema}.{drop}"
        for schema, _, _, _, drop in migration.candidate_pairs()
        if f"{schema}.{drop}" in before
    }
    # These historical revisions have no generated websites/invalid_users
    # duplicates. They exist in the later model-generated layout.
    assert len(selected) == 85
    before_plan = media_plan(connection)
    assert before_plan["Actual Rows"] == 100
    migration.upgrade()
    after = inventory(connection)
    assert before.keys() - after.keys() == selected
    assert all(before[key] == value for key, value in after.items())
    after_plan = media_plan(connection)
    scans = [node for node in plan_nodes(after_plan) if "Index" in node["Node Type"]]
    assert scans and all(
        f"onlyfans.{node['Index Name']}" in after for node in scans
    ), after_plan
    assert after_plan["Actual Rows"] == 100
    assert all(node["Actual Rows"] <= 100 for node in scans), after_plan
    migration.upgrade()  # Previously absent candidates remain absent.
    migration.downgrade()
    restored = inventory(connection)
    assert before.items() <= restored.items()
    migration.downgrade()
    assert inventory(connection) == restored


@pytest.mark.parametrize(
    "definition",
    [
        "(user_id DESC)",
        "(user_id) INCLUDE (id)",
        "(user_id) WHERE user_id > 0",
        "((user_id + 0))",
        "(user_id) WITH (fillfactor=80)",
    ],
)
def test_nonidentical_indexes_abort_and_rollback_prior_drops(
    migration_connection, definition
):
    migration, connection = migration_connection
    connection.execute(text("DROP INDEX onlyfans.ix_onlyfans_media_user_id"))
    connection.execute(
        text(f"CREATE INDEX ix_onlyfans_media_user_id ON onlyfans.media {definition}")
    )
    before = inventory(connection)
    with pytest.raises(RuntimeError, match="definition or dependencies require review"):
        with connection.begin_nested():
            migration.upgrade()
    assert inventory(connection) == before


def test_extension_dependency_prevents_removal(migration_connection):
    migration, connection = migration_connection
    connection.execute(
        text("ALTER INDEX onlyfans.ix_onlyfans_media_user_id DEPENDS ON EXTENSION pg_trgm")
    )
    before = inventory(connection)
    with pytest.raises(RuntimeError, match="dependencies require review"):
        with connection.begin_nested():
            migration.upgrade()
    assert inventory(connection) == before


def test_missing_retained_index_aborts(migration_connection):
    migration, connection = migration_connection
    connection.execute(text("DROP INDEX onlyfans.idx_media_user_id"))
    before = inventory(connection)
    with pytest.raises(RuntimeError, match="cannot verify retained"):
        with connection.begin_nested():
            migration.upgrade()
    assert inventory(connection) == before


def test_direct_create_all_alias_and_unlisted_indexes(migration_connection):
    migration, connection = migration_connection
    connection.execute(
        text(
            "ALTER INDEX onlyfans.ix_onlyfans_media_user_id RENAME TO ix_media_user_id"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX operator_media_lookup ON onlyfans.media(user_id) INCLUDE (id)"
        )
    )
    migration.upgrade()
    current = inventory(connection)
    assert "onlyfans.ix_media_user_id" not in current
    assert "onlyfans.operator_media_lookup" in current
    assert "management.idx_sites_name" in current
    assert "management.ix_management_sites_name" in current


def test_model_retains_named_indexes_and_removes_only_duplicate_column_flags():
    from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates.postgres_site import (
        merged_metadata,
    )

    migration = load_migration("de82a96c410f_remove_verified_duplicate_indexes.py")
    # baa73c9d688e later retires some retained indexes as low-value.
    retirement = load_migration("baa73c9d688e_retire_low_value_profile_indexes.py")
    for schema, table, column, keep, drop in migration.candidate_pairs():
        model_table = merged_metadata.tables[f"{schema}.{table}"]
        names = {index.name for index in model_table.indexes}
        if schema in retirement.SCHEMAS and keep in {
            spec.name for spec in retirement.retired_indexes(schema)
        }:
            assert keep not in names
        else:
            assert keep in names
        assert drop not in names
        assert not model_table.c[column].index
