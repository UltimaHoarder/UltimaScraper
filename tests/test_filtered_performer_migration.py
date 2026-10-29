import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
import ultima_scraper_db_archive


@pytest.fixture
def migration(monkeypatch):
    path = (
        Path(ultima_scraper_db_archive.__file__).parent
        / "migrations/alembic/versions"
        / "e9a62c7138bf_cover_filtered_performer_queries.py"
    )
    spec = importlib.util.spec_from_file_location("filtered_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    state = {"existing": None}
    result = SimpleNamespace(
        mappings=lambda: SimpleNamespace(one_or_none=lambda: state["existing"])
    )
    monkeypatch.setattr(
        module,
        "op",
        SimpleNamespace(
            get_context=lambda: SimpleNamespace(
                as_sql=False, autocommit_block=nullcontext
            ),
            get_bind=lambda: SimpleNamespace(execute=lambda *args: result),
            create_index=lambda *args, **kwargs: calls.append(("create", args, kwargs)),
            drop_index=lambda *args, **kwargs: calls.append(("drop", args, kwargs)),
        ),
    )
    return module, state, calls


def existing_index(**overrides):
    return {
        "table_name": "users",
        "method": "btree",
        "valid": True,
        "ready": True,
        "unique_index": False,
        "key_count": 1,
        "predicate": "((active IS TRUE) AND (performer IS TRUE))",
        "columns": ["id", "active", "created_at"],
        **overrides,
    }


def ensure(module):
    module._ensure_index(
        "onlyfans",
        "idx_users_active_performer_cover",
        "users",
        ["id"],
        ["active", "created_at"],
        "active IS TRUE AND performer IS TRUE",
    )


def test_valid_existing_index_is_skipped(migration):
    module, state, calls = migration
    state["existing"] = existing_index()
    ensure(module)
    assert calls == []


def test_missing_index_is_created_concurrently(migration):
    module, _, calls = migration
    ensure(module)
    assert [call[0] for call in calls] == ["create"]
    assert calls[0][2]["postgresql_concurrently"] is True


def test_invalid_matching_index_is_rebuilt_concurrently(migration):
    module, state, calls = migration
    state["existing"] = existing_index(valid=False)
    ensure(module)
    assert [call[0] for call in calls] == ["drop", "create"]
    assert all(call[2]["postgresql_concurrently"] for call in calls)


@pytest.mark.parametrize(
    "overrides",
    [
        {"columns": ["id", "active"]},
        {"table_name": "user_infos"},
        {"unique_index": True},
        {"predicate": "active IS TRUE"},
    ],
)
def test_conflicting_definition_is_preserved(migration, overrides):
    module, state, calls = migration
    state["existing"] = existing_index(**overrides)
    with pytest.raises(RuntimeError, match="unexpected definition"):
        ensure(module)
    assert calls == []


def test_partial_upgrade_continues_to_other_indexes(migration):
    module, _, calls = migration
    module.upgrade()
    assert len(calls) == 6
    assert {call[2]["schema"] for call in calls} == {"onlyfans", "fansly", "loyalfans"}


def test_predicate_normalization_handles_postgres_numeric_casts(migration):
    module, _, _ = migration
    assert module._normalize_predicate(
        "((price > (0)::double precision) AND (video_count > 0))"
    ) == module._normalize_predicate("price > 0 AND video_count > 0")
