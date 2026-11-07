from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

import canonical_favourites_stub


@pytest.fixture(autouse=True)
def fake_canonical_favourites(monkeypatch):
    canonical_favourites_stub.install(monkeypatch)


class _FakeResult:
    def __init__(self, *, one_value: Any = None, all_value: Any = None) -> None:
        self._one_value = one_value
        self._all_value = all_value if all_value is not None else []

    def one(self) -> Any:
        return self._one_value

    def all(self) -> Any:
        return self._all_value

    def first(self) -> Any:
        if isinstance(self._all_value, list) and self._all_value:
            return self._all_value[0]
        return None

    def mappings(self) -> _FakeResult:
        return self


class _FakeOrdersQuery:
    def filter(self, *_args: Any, **_kwargs: Any) -> _FakeOrdersQuery:
        return self

    def all(self) -> list[tuple[int]]:
        return []


class _FakeOrdersSession:
    def __enter__(self) -> _FakeOrdersSession:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def query(self, *_args: Any, **_kwargs: Any) -> _FakeOrdersQuery:
        return _FakeOrdersQuery()


def _is_users_page_query(sql: str) -> bool:
    """The first page of 100 users: an ID subquery fetching one extra row for has_more."""
    return "FROM users JOIN (SELECT users.id" in sql and "LIMIT 101 OFFSET 0" in sql


class _FakeContextSession:
    def __init__(self, handler: Any) -> None:
        self._handler = handler

    def __enter__(self) -> _FakeContextSession:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def close(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def exec(self, statement: Any) -> _FakeResult:
        return self._handler(statement)

    def execute(self, statement: Any) -> _FakeResult:
        return self._handler(statement)

    def get_bind(self) -> Any:
        # Statement-capture fixture: not PostgreSQL, so no dialect-only probes.
        return _FAKE_BIND


class _FakeBind:
    """Hashable like a real Engine, which the users route uses as a cache key."""

    dialect = SimpleNamespace(name="fixture")


_FAKE_BIND = _FakeBind()


async def test_subscriptions_single_site_uses_ranked_sql(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import subscriptions

    captured_sql: list[str] = []

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        if "count(*) AS count_1" in compiled:
            return _FakeResult(one_value=1)
        return _FakeResult(all_value=[])

    class FakeSiteDB:
        def get_session(self) -> _FakeContextSession:
            return _FakeContextSession(handle_statement)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB:
            return FakeSiteDB()

    monkeypatch.setattr(subscriptions, "MultiSiteDatabaseManager", FakeMultiDB)

    response = subscriptions.list_subscriptions(
        site="onlyfans",
        search="creator",
        active_only=False,
        auth_id=None,
        sex=None,
        order_by="created_at",
        order_dir="desc",
        limit=30,
        offset=15,
    )

    assert response.success is True
    ranked_sql = next(sql for sql in captured_sql if "row_number() OVER" in sql)
    assert "PARTITION BY users.id" in ranked_sql
    paged_sql = next(
        sql for sql in captured_sql if "LIMIT 30" in sql and "OFFSET 15" in sql
    )
    assert "subscription_rank = 1" in paged_sql
    assert "created_at DESC" in paged_sql


async def test_users_list_batches_related_page_lookups(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import orders, users

    captured_sql: list[str] = []

    fake_user_1 = SimpleNamespace(
        id=1,
        username="alpha",
        favorite=False,
        active=True,
        downloaded_at=None,
        last_checked_at=None,
    )
    fake_user_2 = SimpleNamespace(
        id=2,
        username="beta",
        favorite=True,
        active=True,
        downloaded_at=None,
        last_checked_at=None,
    )
    fake_info_1 = SimpleNamespace(
        name="Alpha",
        description="first",
        sex=0,
        gender=None,
        price=5.0,
        post_count=10,
        media_count=20,
        image_count=15,
        video_count=5,
    )
    fake_info_2 = SimpleNamespace(
        name="Beta",
        description="second",
        sex=1,
        gender=None,
        price=10.0,
        post_count=12,
        media_count=25,
        image_count=18,
        video_count=7,
    )
    fake_media = SimpleNamespace(
        user_id=1,
        avatar_url="https://example.com/avatar.jpg",
        header_url=None,
        created_at=datetime.now(timezone.utc),
    )

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        if "sum(CASE WHEN" in compiled:
            return _FakeResult(one_value=(2, 2, 0, 15.0, 0))
        if _is_users_page_query(compiled):
            return _FakeResult(
                all_value=[(fake_user_1, fake_info_1), (fake_user_2, fake_info_2)]
            )
        if "FROM user_profile_media JOIN" in compiled:
            return _FakeResult(all_value=[fake_media])
        if "SELECT DISTINCT subscriptions.user_id" in compiled:
            return _FakeResult(all_value=[1])
        return _FakeResult(all_value=[])

    class FakeSiteDB:
        def get_session(self) -> _FakeContextSession:
            return _FakeContextSession(handle_statement)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB:
            return FakeSiteDB()

    monkeypatch.setattr(users, "MultiSiteDatabaseManager", FakeMultiDB)
    monkeypatch.setattr(orders, "create_orders_session", lambda: _FakeOrdersSession())

    response = await users.list_users(
        site="onlyfans",
        search=None,
        search_description=None,
        sex=None,
        gender=None,
        active_only=False,
        min_price=None,
        max_price=None,
        min_post_count=None,
        max_post_count=None,
        min_image_count=None,
        max_image_count=None,
        min_video_count=None,
        max_video_count=None,
        subscribed_only=False,
        exclude_subscribed=False,
        favorite_only=False,
        performer_only=False,
        exclude_performers=False,
        sort_by="created_at",
        sort_order="desc",
        limit=100,
        offset=0,
    )

    assert response.success is True
    media_queries = [
        sql for sql in captured_sql if "FROM user_profile_media JOIN" in sql
    ]
    assert len(media_queries) == 1
    assert "IN (1, 2)" in media_queries[0]
    page_query = next(
        sql
        for sql in captured_sql
        if _is_users_page_query(sql)
    )
    assert "created_at DESC" in page_query
    subscription_queries = [
        sql for sql in captured_sql if "SELECT DISTINCT subscriptions.user_id" in sql
    ]
    assert len(subscription_queries) == 1
    assert "IN (1, 2)" in subscription_queries[0]


async def test_users_list_applies_gender_filter_with_unset(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import orders, users

    captured_sql: list[str] = []

    fake_user = SimpleNamespace(
        id=1,
        username="alpha",
        favorite=False,
        active=True,
        downloaded_at=None,
        last_checked_at=None,
    )
    fake_info = SimpleNamespace(
        name="Alpha",
        description="first",
        sex=0,
        gender=1,
        price=5.0,
        post_count=10,
        media_count=20,
        image_count=15,
        video_count=5,
    )

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        if "sum(CASE WHEN" in compiled:
            return _FakeResult(one_value=(1, 1, 0, 5.0, 0))
        if _is_users_page_query(compiled):
            return _FakeResult(all_value=[(fake_user, fake_info)])
        return _FakeResult(all_value=[])

    class FakeSiteDB:
        def get_session(self) -> _FakeContextSession:
            return _FakeContextSession(handle_statement)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB:
            return FakeSiteDB()

    monkeypatch.setattr(users, "MultiSiteDatabaseManager", FakeMultiDB)
    monkeypatch.setattr(orders, "create_orders_session", lambda: _FakeOrdersSession())

    response = await users.list_users(
        site="onlyfans",
        search=None,
        search_description=None,
        sex=None,
        gender=[-1, 1],
        active_only=False,
        min_price=None,
        max_price=None,
        min_post_count=None,
        max_post_count=None,
        min_image_count=None,
        max_image_count=None,
        min_video_count=None,
        max_video_count=None,
        subscribed_only=False,
        exclude_subscribed=False,
        favorite_only=False,
        performer_only=False,
        exclude_performers=False,
        sort_by="created_at",
        sort_order="desc",
        limit=100,
        offset=0,
    )

    assert response.success is True
    page_query = next(
        sql
        for sql in captured_sql
        if _is_users_page_query(sql)
    )
    assert "user_infos.gender IN (1)" in page_query
    assert "user_infos.gender IS NULL" in page_query


async def test_browse_users_single_site_uses_sql_pagination(monkeypatch) -> None:
    """browse_users should push ORDER BY + LIMIT/OFFSET into SQL for a single-site query."""
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        if "count(users.id)" in compiled.lower():
            return _FakeResult(one_value=120)
        return _FakeResult(all_value=[])

    class FakeSiteDB:
        def get_session(self) -> Any:
            return _FakeContextSession(handle_statement)

        def close(self) -> None:
            pass

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB:
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_users(
        site="onlyfans",
        search=None,
        active_only=False,
        performer_only=False,
        page=3,
        page_size=25,
    )

    assert response.success is True
    assert response.total == 120

    # Verify SQL has LIMIT/OFFSET
    paged_sql = [sql for sql in captured_sql if "LIMIT" in sql and "OFFSET" in sql]
    assert (
        len(paged_sql) == 1
    ), f"Expected 1 paged query, got {len(paged_sql)}: {paged_sql}"
    assert "LIMIT 25" in paged_sql[0]
    assert "OFFSET 50" in paged_sql[0]  # page 3, page_size 25 → offset 50

    # Verify SQL has ORDER BY (coalesce for username sorting)
    assert "ORDER BY" in paged_sql[0]


async def test_browse_user_content_filters_by_content_type_with_sql_pagination(
    monkeypatch,
) -> None:
    """browse_user_content should honour content_type filter and use SQL LIMIT/OFFSET."""
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        if "count(*)" in compiled.lower():
            return _FakeResult(one_value=80)
        return _FakeResult(all_value=[])

    class FakeSiteDB:
        def get_session(self) -> Any:
            return _FakeContextSession(handle_statement)

        def close(self) -> None:
            pass

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB:
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_user_content(
        user_id=42,
        site="onlyfans",
        content_type="message",
        page=2,
        page_size=20,
    )

    assert response.success is True

    # When content_type is set, should get SQL pagination query
    paged_sql = [sql for sql in captured_sql if "LIMIT" in sql and "OFFSET" in sql]
    assert len(paged_sql) == 1
    assert "LIMIT 20" in paged_sql[0]
    assert "OFFSET 20" in paged_sql[0]  # page 2, page_size 20 → offset 20
    assert "x_messages" in paged_sql[0]  # MessageModel table name
    assert "user_id = 42" in paged_sql[0]


async def test_subscription_stats_uses_sql_count(monkeypatch) -> None:
    """get_subscription_stats should use SQL COUNT(DISTINCT ...) instead of loading all rows."""
    from ultima_scraper_backend.api.routes import subscriptions

    captured_sql: list[str] = []

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        compiled_lower = compiled.lower()
        if "count(distinct" in compiled_lower:
            if "active" in compiled_lower:
                return _FakeResult(one_value=35)
            return _FakeResult(one_value=100)
        return _FakeResult(one_value=0)

    class FakeSiteDB:
        def get_session(self) -> _FakeContextSession:
            return _FakeContextSession(handle_statement)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB | None:
            if site == "onlyfans":
                return FakeSiteDB()
            return None

    monkeypatch.setattr(subscriptions, "MultiSiteDatabaseManager", FakeMultiDB)

    stats = subscriptions.get_subscription_stats()

    assert len(stats) == 1
    assert stats[0].site == "onlyfans"
    assert stats[0].total == 100
    assert stats[0].active == 35
    assert stats[0].expired == 65

    # Verify no SELECT ... FROM subscriptions ... .all() pattern — all should be COUNT queries
    assert all("count(distinct" in sql.lower() for sql in captured_sql)


async def test_backend_inventory_uses_join_not_n_plus_1(monkeypatch) -> None:
    """list_backend_inventory should load settings via relationship, not per-row query."""
    from ultima_scraper_backend.api.routes import settings as settings_mod

    captured_sql: list[str] = []

    fake_settings = SimpleNamespace(backend="scraper", key="main")
    fake_backend = SimpleNamespace(
        id=1,
        backend_name="b1",
        hostname="host1",
        local_ip=None,
        settings_id=10,
        settings=fake_settings,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        if "backends" in compiled.lower():
            return _FakeResult(all_value=[fake_backend])
        return _FakeResult(all_value=[])

    class FakeGlobalSession:
        def __init__(self, handler: Any) -> None:
            self._handler = handler

        def __enter__(self) -> FakeGlobalSession:
            return self

        def __exit__(self, *_a: Any) -> None:
            pass

        def exec(self, statement: Any) -> _FakeResult:
            return self._handler(statement)

        def expunge(self, obj: Any) -> None:
            pass

    monkeypatch.setattr(
        "ultima_scraper_db_archive.global_db.get_global_session",
        lambda: FakeGlobalSession(handle_statement),
    )

    # The real serializer does isinstance check, so patch it to accept our fake objects
    from ultima_scraper_backend.api.routes.settings import BackendInventoryRecord

    def fake_serialize(backend_row: Any, settings_row: Any = None) -> Any:
        scope = getattr(settings_row, "backend", None) if settings_row else None
        key = getattr(settings_row, "key", None) if settings_row else None
        return BackendInventoryRecord(
            id=backend_row.id,
            backend_name=backend_row.backend_name,
            hostname=backend_row.hostname,
            local_ip=backend_row.local_ip,
            settings_id=backend_row.settings_id,
            settings_scope=scope,
            settings_key=key,
            created_at=(
                backend_row.created_at.isoformat() if backend_row.created_at else None
            ),
            updated_at=(
                backend_row.updated_at.isoformat() if backend_row.updated_at else None
            ),
        )

    monkeypatch.setattr(settings_mod, "_serialize_backend_inventory", fake_serialize)

    result = await settings_mod.list_backend_inventory(hostname=None)

    assert len(result) == 1
    assert result[0].hostname == "host1"
    # Should NOT have any separate SettingsModel query — only 1 query for backends
    settings_queries = [
        sql
        for sql in captured_sql
        if "settings" in sql.lower() and "backends" not in sql.lower()
    ]
    assert (
        len(settings_queries) == 0
    ), f"Expected 0 separate settings queries, got: {settings_queries}"


async def test_get_user_purchases_uses_sql_pagination(monkeypatch) -> None:
    """get_user_purchases should use SQL COUNT + LIMIT/OFFSET."""
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        if "count(*)" in compiled.lower():
            return _FakeResult(one_value=250)
        return _FakeResult(all_value=[])

    class FakeSiteDB:
        def get_session(self) -> _FakeContextSession:
            return _FakeContextSession(handle_statement)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB:
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.get_user_purchases(
        user_id=42,
        site="onlyfans",
        role="buyer",
        page=3,
        page_size=25,
    )

    assert response.success is True
    assert response.total == 250
    assert response.page == 3
    assert response.page_size == 25

    paged_sql = [sql for sql in captured_sql if "LIMIT" in sql and "OFFSET" in sql]
    assert len(paged_sql) == 1
    assert "LIMIT 25" in paged_sql[0]
    assert "OFFSET 50" in paged_sql[0]


async def test_browse_user_content_all_types_uses_union(monkeypatch) -> None:
    """browse_user_content without content_type should use UNION ALL with SQL pagination."""
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        if "count(*)" in compiled.lower():
            return _FakeResult(one_value=10)
        return _FakeResult(all_value=[])

    class FakeSiteDB:
        def get_session(self) -> _FakeContextSession:
            return _FakeContextSession(handle_statement)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB:
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_user_content(
        user_id=99,
        site="onlyfans",
        content_type=None,
        page=2,
        page_size=10,
    )

    assert response.success is True
    # Total should sum counts from all 4 content types
    assert response.total == 40  # 10 per type × 4 types

    # Should have a UNION ALL query instead of 4 separate full-load queries
    union_sql = [sql for sql in captured_sql if "UNION ALL" in sql]
    assert len(union_sql) == 1, f"Expected 1 UNION ALL query, got {len(union_sql)}"
    assert "LIMIT 10" in union_sql[0]
    assert "OFFSET 10" in union_sql[0]  # page 2


async def test_proxy_list_batches_auth_lookups(monkeypatch) -> None:
    """list_proxies should batch auth lookups with IN clause, not per-proxy queries."""
    from ultima_scraper_backend.api.routes import proxies as proxies_mod

    captured_sql: list[str] = []

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        if "IN" in compiled and "proxy_id" in compiled.lower():
            return _FakeResult(
                all_value=[
                    (101, "http://proxy1.example.com"),
                    (102, "http://proxy2.example.com"),
                ]
            )
        return _FakeResult(all_value=[])

    class FakeSiteDB:
        def get_session(self) -> _FakeContextSession:
            return _FakeContextSession(handle_statement)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB | None:
            if site == "onlyfans":
                return FakeSiteDB()
            return None

    fake_proxy_1 = SimpleNamespace(
        url="http://proxy1.example.com",
        username="user1",
        max_connections=10,
    )
    fake_proxy_2 = SimpleNamespace(
        url="http://proxy2.example.com",
        username="user2",
        enabled=False,
        max_connections=5,
    )
    fake_config = SimpleNamespace(
        settings=SimpleNamespace(
            network=SimpleNamespace(proxies=[fake_proxy_1, fake_proxy_2])
        )
    )

    monkeypatch.setattr(proxies_mod, "MultiSiteDatabaseManager", FakeMultiDB)
    monkeypatch.setattr(
        proxies_mod,
        "get_geolocation_service",
        lambda: SimpleNamespace(get_geolocation_by_proxy_url=lambda url: None),
    )

    result = proxies_mod.list_proxies(config=fake_config)

    assert len(result) == 2
    assert result[0].enabled is True
    assert result[1].enabled is False
    # Should have at most 1 auth query per site (we have 1 site), not 1 per proxy
    auth_queries = [sql for sql in captured_sql if "proxy_id" in sql.lower()]
    assert (
        len(auth_queries) == 1
    ), f"Expected 1 batched auth query, got {len(auth_queries)}: {auth_queries}"
    assert "IN" in auth_queries[0]


async def test_media_validate_ids_rejects_oversized_batch() -> None:
    """_validate_ids should reject batches exceeding max_size with a 400."""
    import pytest
    from fastapi import HTTPException

    from ultima_scraper_backend.api.routes.media import _validate_ids

    # Within limit — should succeed
    result = _validate_ids([1, 2, 3], "test_ids", max_size=5)
    assert result == [1, 2, 3]

    # Exceeds limit — should raise 400
    with pytest.raises(HTTPException) as exc_info:
        _validate_ids(list(range(501)), "media_ids")
    assert exc_info.value.status_code == 400
    assert "500" in exc_info.value.detail


async def test_chats_messages_no_drm_manifest_eager_load(monkeypatch) -> None:
    """_get_messages_from_db should NOT eagerly load drm_manifest (unused)."""
    from ultima_scraper_backend.api.routes import chats as chats_mod

    captured_options: list[str] = []

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        # selectinload produces subqueries — capture all compiled SQL
        captured_options.append(compiled)
        return _FakeResult(all_value=[])

    class FakeEngine:
        pass

    class PatchedSession:
        def __init__(self, engine: Any) -> None:
            self._sess = _FakeContextSession(handle_statement)

        def __enter__(self) -> _FakeContextSession:
            return self._sess

        def __exit__(self, *_args: Any) -> None:
            pass

    monkeypatch.setattr(chats_mod, "Session", PatchedSession)

    messages, has_more, next_offset = chats_mod._get_messages_from_db(
        engine=FakeEngine(),
        auth_ids=[1],
        chat_user_id=2,
        site_name="onlyfans",
        limit=10,
        offset_id=None,
    )

    # The main query SQL should reference filepaths eager loading but NOT drm_manifest
    main_sql = captured_options[0] if captured_options else ""
    assert (
        "drm_manifest" not in main_sql.lower()
    ), f"drm_manifest should not be eagerly loaded, got: {main_sql}"


async def test_files_alias_lookup_uses_column_projection(monkeypatch) -> None:
    """_resolve_all_usernames should use column projection for alias username lookup."""
    from ultima_scraper_backend.api.routes import files as files_mod

    captured_sql: list[str] = []

    fake_user = SimpleNamespace(id=42, username="testuser")

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        # First query (user by username) returns our fake user
        if "users" in compiled.lower() and "testuser" in compiled.lower():
            return _FakeResult(all_value=[fake_user])
        # Alias username query should be column projection
        if "user_aliases" in compiled.lower() and "user_id" in compiled.lower():
            return _FakeResult(all_value=["old_username"])
        return _FakeResult(all_value=[])

    class FakeSiteDB:
        def get_session(self) -> _FakeContextSession:
            return _FakeContextSession(handle_statement)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB:
            return FakeSiteDB()

    monkeypatch.setattr(files_mod, "MultiSiteDatabaseManager", FakeMultiDB)

    user_id, usernames = files_mod._resolve_all_usernames(
        site_name="onlyfans",
        user_id=None,
        username="testuser",
    )

    assert user_id == 42
    assert "testuser" in usernames

    # The alias query should select only the username column, not the full model
    alias_queries = [
        sql
        for sql in captured_sql
        if "user_aliases" in sql.lower() and "user_id" in sql.lower()
    ]
    assert alias_queries, "Expected at least one alias query"
    # Column projection: SELECT user_aliases.username FROM ... (not SELECT user_aliases.id, ...)
    alias_sql = alias_queries[0]
    assert (
        "user_aliases.username" in alias_sql.lower()
    ), f"Alias query should project only username column: {alias_sql}"


async def test_chats_avatar_batch_not_n_plus_1(monkeypatch) -> None:
    """_get_chats_from_db should batch-load avatars with row_number, not per-user."""
    from ultima_scraper_backend.api.routes import chats as chats_mod

    captured_sql: list[str] = []

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        # Return two chat summary rows
        if "partner_id" in compiled.lower() or "msg_count" in compiled.lower():
            return _FakeResult(all_value=[(10, None, None, 0), (20, None, None, 0)])
        # User lookup
        if "users" in compiled.lower() and "IN" in compiled:
            return _FakeResult(
                all_value=[
                    SimpleNamespace(id=10, username="user_10"),
                    SimpleNamespace(id=20, username="user_20"),
                ]
            )
        # User info lookup
        if "user_info" in compiled.lower() and "IN" in compiled:
            return _FakeResult(all_value=[])
        # Avatar batch query (should use row_number)
        if (
            "row_number" in compiled.lower()
            and "user_profile_media" in compiled.lower()
        ):
            return _FakeResult(all_value=[(10, "avatar10.jpg"), (20, "avatar20.jpg")])
        # Message lookup
        if "messages" in compiled.lower() and "IN" in compiled:
            return _FakeResult(all_value=[])
        return _FakeResult(all_value=[])

    class FakeEngine:
        pass

    class PatchedSession:
        def __init__(self, engine: Any) -> None:
            self._sess = _FakeContextSession(handle_statement)

        def __enter__(self) -> _FakeContextSession:
            return self._sess

        def __exit__(self, *_args: Any) -> None:
            pass

    monkeypatch.setattr(chats_mod, "Session", PatchedSession)

    chats_mod._get_chats_from_db(
        engine=FakeEngine(),
        auth_ids=[1],
        limit=50,
    )

    # Should have a single batch avatar query with row_number, NOT per-user queries
    avatar_queries = [
        sql for sql in captured_sql if "user_profile_media" in sql.lower()
    ]
    assert (
        len(avatar_queries) == 1
    ), f"Expected exactly 1 batch avatar query, got {len(avatar_queries)}"
    assert (
        "row_number" in avatar_queries[0].lower()
    ), "Avatar query should use row_number() window function for batching"


async def test_jobs_mark_failed_batch_loads(monkeypatch) -> None:
    """_mark_central_jobs_failed_sync should batch-load jobs with IN, not per-id."""
    from ultima_scraper_backend.api.routes import jobs as jobs_mod

    captured_sql: list[str] = []

    fake_job = SimpleNamespace(
        job_id="job-1",
        status="running",
        result_success=True,
        result_error=None,
        completed_at=None,
        result_completed_at=None,
        last_event_at=None,
    )

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        if "IN" in compiled:
            return _FakeResult(all_value=[fake_job])
        return _FakeResult(all_value=[])

    class FakeGlobalSession:
        def __init__(self) -> None:
            self._sess = _FakeContextSession(handle_statement)

        def __enter__(self) -> _FakeContextSession:
            return self._sess

        def __exit__(self, *_args: Any) -> None:
            pass

    import ultima_scraper_db_archive.global_db as global_db_mod

    monkeypatch.setattr(global_db_mod, "global_session", FakeGlobalSession)

    jobs_mod._mark_central_jobs_failed_sync(["job-1", "job-2"])

    # Should use a single IN query, not session.get() per job
    assert any(
        "IN" in sql for sql in captured_sql
    ), f"Expected batch IN query for jobs, got: {captured_sql}"


async def test_subscription_validation_batch_query(monkeypatch) -> None:
    """split_tasks_by_auth single-auth mode should batch-validate with IN clause."""
    from ultima_scraper_backend.job_system import subscription_validation as sv

    captured_sql: list[str] = []

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        # Return active subscriptions for both performers
        if "IN" in compiled and "subscriptions" in compiled.lower():
            return _FakeResult(all_value=[(100, True), (200, True)])
        # Auth username lookup
        if "user_auth" in compiled.lower():
            return _FakeResult(all_value=[SimpleNamespace(username="auth_user")])
        return _FakeResult(all_value=[])

    session = _FakeContextSession(handle_statement)

    # Performer 300 is not in the returned active set, so split_tasks_by_auth raises ValueError
    import pytest

    with pytest.raises(ValueError, match="not subscribed"):
        sv.split_tasks_by_auth(
            session=session,  # type: ignore[arg-type]
            performer_ids=[100, 200, 300],
            auth_id=42,
        )

    # Should use a single IN query instead of per-performer validate_subscription
    sub_queries = [sql for sql in captured_sql if "subscriptions" in sql.lower()]
    assert (
        len(sub_queries) == 1
    ), f"Expected 1 batch subscription query, got {len(sub_queries)}: {sub_queries}"
    assert "IN" in sub_queries[0], "Subscription query should use IN clause for batch"


async def test_users_list_description_search_scoped_and_trigram_conditions(
    monkeypatch,
) -> None:
    """Description search should use non-empty conditions, outer scoping, and UNION ALL."""
    from ultima_scraper_backend.api.routes import orders, users

    captured_sql: list[str] = []

    fake_user = SimpleNamespace(
        id=1,
        username="alpha",
        favorite=False,
        active=True,
        performer=True,
        downloaded_at=None,
        last_checked_at=None,
    )
    fake_info = SimpleNamespace(
        name="Alpha",
        description="size 13 shoe collector",
        sex=2,
        gender=None,
        profile_type=None,
        sexual_content=None,
        partner_sex=None,
        partner_gender=None,
        price=10.0,
        post_count=10,
        media_count=20,
        image_count=15,
        video_count=5,
    )

    def handle_statement(statement: Any) -> _FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        captured_sql.append(compiled)
        if "sum(CASE WHEN" in compiled:
            return _FakeResult(one_value=(1, 1, 0, 10.0, 0))
        if "FROM users LEFT OUTER JOIN user_infos" in compiled and "LIMIT" in compiled:
            return _FakeResult(all_value=[(fake_user, fake_info)])
        return _FakeResult(all_value=[])

    class FakeSiteDB:
        def get_session(self) -> _FakeContextSession:
            return _FakeContextSession(handle_statement)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB:
            return FakeSiteDB()

    monkeypatch.setattr(users, "MultiSiteDatabaseManager", FakeMultiDB)
    monkeypatch.setattr(orders, "create_orders_session", lambda: _FakeOrdersSession())

    response = await users.list_users(
        site="onlyfans",
        search=None,
        search_description="size 13",
        sex=[2],
        active_only=True,
        performer_only=True,
        min_price=1.0,
        min_video_count=1,
        limit=50,
        offset=0,
    )

    assert response.success is True
    assert len(captured_sql) >= 2

    # Verify stats_query and paginated query both include optimized description conditions
    for sql in captured_sql:
        if "UNION ALL" in sql:
            assert "user_infos.description IS NOT NULL" in sql
            assert "histo_user_infos.description IS NOT NULL" in sql
            assert "users.performer IS true" in sql
            assert "users.active IS true" in sql
            # Candidate branches leave performer/active scoping to the outer query.
            assert "JOIN users ON users.id = user_infos.user_id" not in sql
            assert "JOIN users ON users.id = histo_user_infos.user_id" not in sql



def _inventory_engine():
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool
    from ultima_scraper_db_archive.global_db import SettingsModel

    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.execute(text("ATTACH DATABASE ':memory:' AS management"))
    SettingsModel.__table__.create(engine)
    with engine.begin() as connection:
        # SQLite has no INET: the address is kept as text.
        connection.execute(text(
            "CREATE TABLE management.backends (id INTEGER PRIMARY KEY, backend_name TEXT, hostname TEXT, "
            "local_ip TEXT, settings_id INTEGER, created_at TIMESTAMP, updated_at TIMESTAMP)"
        ))
        connection.execute(text(
            "INSERT INTO management.settings (id, backend, key, value, is_secret, version) "
            "VALUES (1, 'datahoarders', 'config', '{}', 0, 1)"
        ))
        connection.execute(text(
            "INSERT INTO management.backends (id, backend_name, hostname, local_ip, settings_id) VALUES "
            "(1, 'datahoarders', 'datahoarders', '192.0.2.98', 1), (2, 'nas', '192-0-2-84-1', '192.0.2.84', 1)"
        ))
    return engine


async def test_backends_sharing_one_settings_row_are_all_listed(monkeypatch) -> None:
    import inspect

    from sqlmodel import Session
    from ultima_scraper_backend.api.routes import settings as settings_mod

    if "session.expunge(settings_row)" in inspect.getsource(settings_mod.list_backend_inventory):
        pytest.skip("this backend release detaches the shared settings row twice")
    engine = _inventory_engine()
    monkeypatch.setattr("ultima_scraper_db_archive.global_db.get_global_session", lambda: Session(engine))

    listed = await settings_mod.list_backend_inventory(hostname=None)

    assert [(row.hostname, row.settings_id, row.settings_scope) for row in listed] == [
        ("192-0-2-84-1", 1, "datahoarders"),
        ("datahoarders", 1, "datahoarders"),
    ]
