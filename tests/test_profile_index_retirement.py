"""Low-value profile index retirement (baa73c9d688e)."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

import test_mps_manifest as fixtures
from test_duplicate_index_migration import load_migration

postgres_engine = fixtures.postgres_engine

SITES = ("onlyfans", "fansly", "loyalfans")
REVISION = "baa73c9d688e"
PREVIOUS = "88dddeb4538e"


@pytest.fixture
def migration(monkeypatch):
    module = load_migration(f"{REVISION}_retire_low_value_profile_indexes.py")
    calls = []
    state = {"existing": {}}

    def execute(_statement, params):
        return SimpleNamespace(
            mappings=lambda: SimpleNamespace(
                one_or_none=lambda: state["existing"].get(params["name"])
            )
        )

    monkeypatch.setattr(
        module,
        "op",
        SimpleNamespace(
            get_context=lambda: SimpleNamespace(
                as_sql=False, autocommit_block=nullcontext
            ),
            get_bind=lambda: SimpleNamespace(execute=execute),
            create_index=lambda *args, **kwargs: calls.append(("create", args, kwargs)),
            drop_index=lambda *args, **kwargs: calls.append(("drop", args, kwargs)),
        ),
    )
    return module, state, calls


def catalog_row(spec, **overrides):
    return {
        "table_name": spec.table,
        "method": "btree",
        "valid": True,
        "ready": True,
        "unique_index": False,
        "constraint_backed": False,
        "key_count": len(spec.keys),
        "column_count": len(spec.keys),
        "predicate": f"({spec.predicate})" if spec.predicate else None,
        "keys": list(spec.keys),
        "options": [1 if spec.descending_nulls_last else 0] * len(spec.keys),
        **overrides,
    }


def spec_named(module, name, schema="onlyfans"):
    specs = (*module.REPLACEMENTS, *module.retired_indexes(schema))
    return next(spec for spec in specs if spec.name == name)


def test_upgrade_builds_replacements_before_any_drop(migration):
    module, state, calls = migration
    for spec in module.retired_indexes("onlyfans"):
        state["existing"][spec.name] = catalog_row(spec)
    module.upgrade()
    onlyfans = [call for call in calls if call[2]["schema"] == "onlyfans"]
    kinds = [call[0] for call in onlyfans]
    assert kinds == ["create"] * len(module.REPLACEMENTS) + ["drop"] * len(
        module.retired_indexes("onlyfans")
    )
    assert all(call[2]["postgresql_concurrently"] for call in calls)
    assert {call[1][0] for call in onlyfans if call[0] == "drop"} == {
        spec.name for spec in module.retired_indexes("onlyfans")
    }


def test_finished_replacements_and_absent_retirements_are_skipped(migration):
    module, state, calls = migration
    for spec in module.REPLACEMENTS:
        state["existing"][spec.name] = catalog_row(spec)
    module.upgrade()
    assert calls == []


def test_invalid_replacement_is_rebuilt_concurrently(migration):
    module, state, calls = migration
    spec = spec_named(module, "idx_users_username_lower")
    state["existing"][spec.name] = catalog_row(spec, valid=False)
    module._create("onlyfans", spec)
    assert [call[0] for call in calls] == ["drop", "create"]
    assert all(call[2]["postgresql_concurrently"] for call in calls)


@pytest.mark.parametrize(
    "overrides",
    [
        {"keys": ["username"]},
        {"unique_index": True},
        {"constraint_backed": True},
        {"predicate": None},
        {"options": [0]},
        {"column_count": 2},
    ],
)
def test_unexpected_replacement_definitions_abort_for_review(migration, overrides):
    module, state, calls = migration
    spec = spec_named(module, "idx_users_downloaded_at_present")
    state["existing"][spec.name] = catalog_row(spec, **overrides)
    with pytest.raises(RuntimeError, match="unexpected definition"):
        module._create("onlyfans", spec)
    assert calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"keys": ["updated_at"]},
        {"unique_index": True},
        {"constraint_backed": True},
        {"predicate": "(downloaded_at IS NOT NULL)"},
        {"options": [0]},
    ],
)
def test_unexpected_retired_definitions_are_preserved(migration, overrides):
    module, state, calls = migration
    spec = spec_named(module, "idx_users_downloaded_at")
    state["existing"][spec.name] = catalog_row(spec, **overrides)
    with pytest.raises(RuntimeError, match="unexpected definition"):
        module._drop("onlyfans", spec)
    assert calls == []


def test_predicate_normalization_accepts_catalog_casts(migration):
    module, state, calls = migration
    spec = spec_named(module, "idx_user_infos_price_paid")
    state["existing"][spec.name] = catalog_row(
        spec, predicate="(price > (0)::double precision)"
    )
    module._create("onlyfans", spec)
    assert calls == []


def test_model_declares_replacements_and_not_retired_indexes():
    from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates.postgres_site import (
        merged_metadata,
    )

    module = load_migration(f"{REVISION}_retire_low_value_profile_indexes.py")
    for schema in SITES:
        tables = {
            name: merged_metadata.tables[f"{schema}.{name}"]
            for name in ("users", "user_infos", "invalid_users", "user_aliases")
        }
        for spec in module.REPLACEMENTS:
            index = next(i for i in tables[spec.table].indexes if i.name == spec.name)
            predicate = index.dialect_options["postgresql"]["where"]
            assert (str(predicate) if predicate is not None else None) == spec.predicate
        for spec in module.retired_indexes(schema):
            assert spec.name not in {i.name for i in tables[spec.table].indexes}
        assert not any(column.index for column in tables["user_infos"].columns)


@pytest.fixture
def archive_url(postgres_engine):
    database = "usr_profile_index_retirement"
    host = postgres_engine.url.query["host"]
    with postgres_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    url = f"postgresql+psycopg://usr_test@/{database}?host={host}"
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
        connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))


def _migrate(url, action, target, monkeypatch):
    from alembic import command
    from ultima_scraper_db_archive.migration_cli import MIGRATION_BUNDLE

    monkeypatch.setenv("USR_SECRET_KEY", "profile-index-fixture-key")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            config = MIGRATION_BUNDLE.create_config(url)
            config.attributes["connection"] = connection
            getattr(command, action)(config, target)
            if connection.in_transaction():
                connection.commit()
    finally:
        engine.dispose()


def _inventory(engine):
    with engine.connect() as connection:
        return dict(
            connection.execute(
                text(
                    "SELECT schemaname || '.' || indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname IN ('onlyfans','fansly','loyalfans') AND "
                    "tablename IN ('users','user_infos','invalid_users','user_aliases')"
                )
            ).all()
        )


def _plan_indexes(connection, sql):
    plan = connection.execute(text(f"EXPLAIN (FORMAT JSON) {sql}")).scalar_one()[0]

    def walk(node):
        if "Index Name" in node:
            yield node["Index Name"]
        for child in node.get("Plans", []):
            yield from walk(child)

    return set(walk(plan["Plan"]))


def test_upgrade_downgrade_round_trip_and_lookup_plans(archive_url, monkeypatch):
    module = load_migration(f"{REVISION}_retire_low_value_profile_indexes.py")
    _migrate(archive_url, "upgrade", PREVIOUS, monkeypatch)
    engine = create_engine(archive_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO onlyfans.users(id, username, performer, active) "
                    "SELECT i, 'User' || i, i % 100 = 0, true "
                    "FROM generate_series(1, 50000) i"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO onlyfans.user_infos(user_id, price, sex) "
                    "SELECT i, CASE WHEN i % 100 = 0 THEN 9.99 ELSE 0 END, "
                    "CASE WHEN i % 500 = 0 THEN 1 END FROM generate_series(1, 50000) i"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO onlyfans.user_aliases(user_id, username) "
                    "SELECT i, 'Alias' || i FROM generate_series(1, 5000) i"
                )
            )
            connection.execute(text("ANALYZE onlyfans.users, onlyfans.user_infos, onlyfans.user_aliases"))
        before = _inventory(engine)

        _migrate(archive_url, "upgrade", REVISION, monkeypatch)
        after = _inventory(engine)
        retired = {
            f"{schema}.{spec.name}"
            for schema in SITES
            for spec in module.retired_indexes(schema)
        }
        added = {
            f"{schema}.{spec.name}" for schema in SITES for spec in module.REPLACEMENTS
        }
        assert before.keys() - after.keys() == retired
        assert after.keys() - before.keys() == added
        assert all(before[name] == after[name] for name in before.keys() & after.keys())

        with engine.connect() as connection:
            assert "idx_users_username_lower" in _plan_indexes(
                connection,
                "SELECT id FROM onlyfans.users WHERE lower(username) = lower('USER4242')",
            )
            assert "idx_user_aliases_username_lower" in _plan_indexes(
                connection,
                "SELECT user_id FROM onlyfans.user_aliases "
                "WHERE lower(username) = lower('alias42')",
            )
            assert "idx_users_username_lower" in _plan_indexes(
                connection,
                "SELECT id FROM onlyfans.users ORDER BY lower(username) LIMIT 50",
            )
            assert "idx_user_infos_price_paid" in _plan_indexes(
                connection, "SELECT user_id FROM onlyfans.user_infos WHERE price >= 5"
            )
            assert "idx_user_infos_sex" in _plan_indexes(
                connection,
                "SELECT user_id FROM onlyfans.user_infos WHERE sex IN (1, 2)",
            )

        _migrate(archive_url, "downgrade", PREVIOUS, monkeypatch)
        assert _inventory(engine) == before
        _migrate(archive_url, "upgrade", REVISION, monkeypatch)
        assert _inventory(engine) == after
    finally:
        engine.dispose()
