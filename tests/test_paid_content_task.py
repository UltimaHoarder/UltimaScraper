from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def test_task_definitions_include_paid_content_task() -> None:
    from ultima_scraper_backend.api.routes.tasks import TASK_DEFINITIONS

    definitions = {task.task_id: task for task in TASK_DEFINITIONS}

    assert "scrape_paid_content" in definitions
    assert "content_value" not in {
        param.name for param in definitions["scrape_user"].parameters
    }
    assert "content_value" not in {
        param.name for param in definitions["download_media"].parameters
    }

    paid_task_params = {
        param.name: param for param in definitions["scrape_paid_content"].parameters
    }
    assert set(paid_task_params) == {
        "site",
        "performer",
        "content_types",
        "download_media",
        "max_items",
    }


def test_build_task_supports_paid_content_feed_payload() -> None:
    from ultima_scraper_backend.job_system.job_builder import build_task
    from ultima_scraper_backend.job_system.models import TaskType

    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=777,
        user_username=None,
        content_type=None,
        auth_id=777,
        download_media=True,
        max_items=50,
        paid_content_feed=True,
        paid_content_performer="creator_name",
        paid_content_types=["Posts", "Messages"],
    )

    assert task.payload is not None
    assert task.payload.paid_content_feed is True
    assert task.payload.paid_content_performer == "creator_name"
    assert task.payload.paid_content_types == ["Posts", "Messages"]


def test_paid_content_feed_does_not_auto_spawn_generic_download_task() -> None:
    from ultima_scraper_backend.job_system.auth_expansion import (
        _should_create_download_task,
    )
    from ultima_scraper_backend.job_system.job_builder import build_task
    from ultima_scraper_backend.job_system.models import TaskType

    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=777,
        user_username=None,
        content_type=None,
        auth_id=777,
        download_media=True,
        paid_content_feed=True,
        paid_content_types=["Posts", "Messages"],
    )

    assert _should_create_download_task(task) is False


def test_paid_feed_helpers_normalize_types_and_detect_items() -> None:
    from ultima_scraper_api import ContentType

    from ultima_scraper_backend.job_system.handlers.scrape.content import (
        _detect_paid_content_type,
        _normalize_paid_content_types,
    )

    assert _normalize_paid_content_types(None) == {
        ContentType.POSTS,
        ContentType.MESSAGES,
    }
    assert _normalize_paid_content_types(["Posts"]) == {ContentType.POSTS}

    post_item = MagicMock()
    post_item.responseType = "post"
    message_item = MagicMock()
    message_item.responseType = "message"

    assert _detect_paid_content_type(post_item) == ContentType.POSTS
    assert _detect_paid_content_type(message_item) == ContentType.MESSAGES


def test_bought_content_model_has_content_link_columns() -> None:
    from ultima_scraper_db_archive import BoughtContentModel

    assert hasattr(BoughtContentModel, "post_id")
    assert hasattr(BoughtContentModel, "message_id")


def test_extract_bought_content_links_maps_post_and_message_only() -> None:
    from ultima_scraper_backend.manager import BackendManager

    class PaidPost:
        id = 101
        responseType = "post"

    class PaidMessage:
        id = 202
        responseType = "message"

    class PaidMassMessage:
        id = 303
        responseType = "message"

    assert BackendManager._extract_bought_content_links(PaidPost()) == (101, None)
    assert BackendManager._extract_bought_content_links(PaidMessage()) == (None, 202)
    # Mass-message style payloads are intentionally excluded from bought_content links.
    assert BackendManager._extract_bought_content_links(PaidMassMessage()) == (
        None,
        None,
    )


def test_extract_paid_status_uses_paid_scrape_and_open_signals() -> None:
    from ultima_scraper_backend.manager import BackendManager

    paid_feed_item = SimpleNamespace(price=19.99, media=[])
    assert (
        BackendManager._extract_paid_status(
            paid_feed_item,
            record_bought_content=True,
        )
        is True
    )

    opened_post = SimpleNamespace(
        price=14.99,
        isOpened=True,
        canViewMedia=False,
        media=[],
    )
    assert BackendManager._extract_paid_status(opened_post) is True

    opened_message = SimpleNamespace(
        price=11.0,
        media=[SimpleNamespace(canView=True), SimpleNamespace(canView=True)],
    )
    assert BackendManager._extract_paid_status(opened_message) is True

    locked_message = SimpleNamespace(
        price=11.0,
        media=[SimpleNamespace(canView=False), SimpleNamespace(canView=False)],
    )
    assert BackendManager._extract_paid_status(locked_message) is False

    free_post = SimpleNamespace(price=0.0, isOpened=True, media=[])
    assert BackendManager._extract_paid_status(free_post) is False


def test_merge_paid_status_keeps_true_sticky() -> None:
    from ultima_scraper_backend.manager import BackendManager

    assert BackendManager._merge_paid_status(True, False) is True
    assert BackendManager._merge_paid_status(True, None) is True
    assert BackendManager._merge_paid_status(False, True) is True
    assert BackendManager._merge_paid_status(None, False) is False


def test_summarize_auth_transport_masks_proxy_credentials() -> None:
    from ultima_scraper_backend.job_system.handlers.scrape.content import (
        _summarize_auth_transport,
    )

    class ProxyConnector:
        pass

    proxy_info = SimpleNamespace(host="10.0.0.5", port=1080)
    proxy_manager = SimpleNamespace(
        proxies=[proxy_info],
        get_current_proxy=lambda: proxy_info,
    )
    auth_session = SimpleNamespace(
        active_session=SimpleNamespace(
            connector=ProxyConnector(),
            closed=False,
        ),
        get_proxy_manager=lambda: proxy_manager,
    )
    authed = SimpleNamespace(
        id=777,
        username="proxy-user",
        guest=False,
        get_auth_details=lambda: SimpleNamespace(
            proxy_url="socks5://user:password@10.0.0.5:1080"
        ),
        auth_session=auth_session,
    )

    summary = _summarize_auth_transport(authed)

    assert "proxy_url=socks5://10.0.0.5:1080" in summary
    assert "user:password" not in summary
    assert "connector=ProxyConnector" in summary
    assert "current_proxy=10.0.0.5:1080" in summary


def test_purchased_content_filter_uses_buyer_scope_for_user_page(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    class FakeResult:
        def one(self):
            return 0

        def all(self):
            return []

    class FakeSession:
        def exec(self, statement):
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            captured_sql.append(compiled)
            return FakeResult()

        def close(self):
            return None

    class FakeSiteDB:
        def get_session(self):
            return FakeSession()

    class FakeMultiDB:
        def get_or_create_manager(self, site: str):
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_all_content(
        site="onlyfans",
        content_type="message",
        user_id=10001,
        search=None,
        sort_by="created_at",
        order="desc",
        include_flags="purchased",
        exclude_flags=None,
        page=1,
        page_size=30,
    )

    assert response.success is True
    message_sql = next(sql for sql in captured_sql if "JOIN x_messages" in sql)
    assert "bought_content.buyer_id = 10001" in message_sql
    assert "x_messages.user_id = 10001" not in message_sql


def test_purchased_keyword_search_drives_from_bought_content(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    class FakeResult:
        def one(self):
            return 0

        def all(self):
            return []

    class FakeSession:
        def exec(self, statement):
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            captured_sql.append(compiled)
            return FakeResult()

        def close(self):
            return None

    class FakeSiteDB:
        def get_session(self):
            return FakeSession()

    class FakeMultiDB:
        def get_or_create_manager(self, site: str):
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_all_content(
        site="onlyfans",
        content_type="message",
        user_id=10001,
        search="hello",
        sort_by="created_at",
        order="desc",
        include_flags="purchased",
        exclude_flags=None,
        page=1,
        page_size=30,
    )

    assert response.success is True
    message_sql = next(sql for sql in captured_sql if "JOIN x_messages" in sql)
    assert "FROM bought_content JOIN x_messages" in message_sql
    assert "bought_content.buyer_id = 10001" in message_sql
    assert "lower(x_messages.text) LIKE lower('%hello%')" in message_sql


def test_regular_content_filter_keeps_author_scope(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    class FakeResult:
        def one(self):
            return 0

        def all(self):
            return []

    class FakeSession:
        def exec(self, statement):
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            captured_sql.append(compiled)
            return FakeResult()

        def close(self):
            return None

    class FakeSiteDB:
        def get_session(self):
            return FakeSession()

    class FakeMultiDB:
        def get_or_create_manager(self, site: str):
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_all_content(
        site="onlyfans",
        content_type="message",
        user_id=10001,
        search=None,
        sort_by="created_at",
        order="desc",
        include_flags=None,
        exclude_flags=None,
        page=1,
        page_size=30,
    )

    assert response.success is True
    message_sql = next(sql for sql in captured_sql if "FROM x_messages" in sql)
    assert "x_messages.user_id = 10001" in message_sql


def test_content_search_uses_single_union_query_per_site(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    class FakeResult:
        def one(self):
            return 0

        def all(self):
            return []

    class FakeSession:
        def exec(self, statement):
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            captured_sql.append(compiled)
            return FakeResult()

        def close(self):
            return None

    class FakeSiteDB:
        def get_session(self):
            return FakeSession()

    class FakeMultiDB:
        def get_or_create_manager(self, site: str):
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_all_content(
        site="onlyfans",
        content_type=None,
        user_id=None,
        search="hello",
        sort_by="created_at",
        order="desc",
        include_flags=None,
        exclude_flags=None,
        page=1,
        page_size=30,
    )

    assert response.success is True
    assert len(captured_sql) == 1
    assert "UNION ALL" in captured_sql[0]
    assert "hello" in captured_sql[0]


async def test_scrape_paid_content_feed_resets_cache_and_reports_fetched_count(
    monkeypatch,
) -> None:
    from ultima_scraper_api import ContentType

    from ultima_scraper_backend.job_system.handlers.scrape import content

    saved_calls: list[tuple[int, ContentType, bool]] = []

    class FakePaidCache:
        def __init__(self) -> None:
            self.deactivated = False

        def deactivate(self) -> None:
            self.deactivated = True

    class FakeAuthor:
        def __init__(self) -> None:
            self.id = 2468
            self.username = "creator"

    class FakeItem:
        def __init__(self) -> None:
            self.id = 111
            self.responseType = "message"
            self.media = []

        def get_author(self):
            return FakeAuthor()

    async def fake_get_paid_content(**kwargs):
        return [FakeItem()]

    async def fake_save_content_to_db(
        content_items,
        user_id,
        content_type,
        worker_id="unknown",
        auth_user_id=None,
        record_bought_content=False,
        on_progress=None,
        *,
        database_writes,
        site,
        media_selection=None,
        error_offset=0,
    ):
        assert media_selection is None
        assert error_offset == 0
        saved_calls.append((user_id, content_type, record_bought_content))
        return len(content_items), []

    authed = SimpleNamespace(
        username="auth_user",
        cache=SimpleNamespace(paid_content=FakePaidCache()),
        paid_content=[object()],
        get_paid_content=fake_get_paid_content,
    )

    monkeypatch.setattr(content, "save_content_to_db", fake_save_content_to_db)

    (
        items_fetched,
        items_scraped,
        items_saved,
        errors,
        media_urls,
        download_targets,
    ) = await content.scrape_paid_content_feed(
        authed,
        max_items=None,
        performer_filter=None,
        paid_content_types=None,
        auth_user_id=10001,
        worker_id="worker-1",
        job_id=None,
        rescrape_existing=True,
        database_writes=MagicMock(),
        site="onlyfans",
    )

    assert authed.cache.paid_content.deactivated is True
    assert authed.paid_content == []
    assert items_fetched == 1
    assert items_scraped == 1
    assert items_saved == 1
    assert errors == []
    assert media_urls == []
    assert download_targets == [
        {
            "user_id": 2468,
            "username": "creator",
            "content_type": ContentType.MESSAGES,
        }
    ]
    assert saved_calls == [(2468, ContentType.MESSAGES, True)]


async def test_scrape_paid_content_feed_saves_mass_messages_before_messages(
    monkeypatch,
) -> None:
    from ultima_scraper_api import ContentType

    from ultima_scraper_backend.job_system.handlers.scrape import content

    saved_calls: list[tuple[int, ContentType, bool]] = []

    class FakePaidCache:
        def deactivate(self) -> None:
            return None

    class FakeMassMessage:
        def __init__(self) -> None:
            self.id = 333

    class FakeAuthor:
        def __init__(self) -> None:
            self.id = 2468
            self.username = "creator"
            self.scrape_manager = SimpleNamespace(
                scraped=SimpleNamespace(
                    MassMessages={333: FakeMassMessage()},
                )
            )

        def get_authed(self):
            return None

    class FakeItem:
        def __init__(self, author: FakeAuthor) -> None:
            self.id = 111
            self.responseType = "message"
            self.media = []
            self.isFromQueue = True
            self.queueId = 333
            self._author = author

        def get_author(self):
            return self._author

    author = FakeAuthor()

    async def fake_get_paid_content(**kwargs):
        return [FakeItem(author)]

    async def fake_save_content_to_db(
        content_items,
        user_id,
        content_type,
        worker_id="unknown",
        auth_user_id=None,
        record_bought_content=False,
        on_progress=None,
        *,
        database_writes,
        site,
        media_selection=None,
        error_offset=0,
    ):
        assert media_selection is None
        assert error_offset == 0
        saved_calls.append((user_id, content_type, record_bought_content))
        return len(content_items), []

    authed = SimpleNamespace(
        username="auth_user",
        cache=SimpleNamespace(paid_content=FakePaidCache()),
        paid_content=[],
        get_paid_content=fake_get_paid_content,
    )

    monkeypatch.setattr(content, "save_content_to_db", fake_save_content_to_db)

    (
        items_fetched,
        items_scraped,
        items_saved,
        errors,
        media_urls,
        download_targets,
    ) = await content.scrape_paid_content_feed(
        authed,
        max_items=None,
        performer_filter=None,
        paid_content_types=None,
        auth_user_id=10001,
        worker_id="worker-1",
        job_id=None,
        rescrape_existing=True,
        database_writes=MagicMock(),
        site="onlyfans",
    )

    assert items_fetched == 1
    assert items_scraped == 1
    assert items_saved == 2
    assert errors == []
    assert media_urls == []
    assert download_targets == [
        {
            "user_id": 2468,
            "username": "creator",
            "content_type": ContentType.MESSAGES,
        }
    ]
    assert saved_calls == [
        (2468, ContentType.MASS_MESSAGES, True),
        (2468, ContentType.MESSAGES, True),
    ]


async def test_scrape_content_type_saves_mass_messages_before_messages(
    monkeypatch,
) -> None:
    from ultima_scraper_api import ContentType
    from ultima_scraper_api.apis.user_streamliner import StreamlinedUser

    from ultima_scraper_backend.job_system.handlers.scrape import content

    saved_calls: list[tuple[int, ContentType, bool]] = []

    class FakeMassMessage:
        def __init__(self) -> None:
            self.id = 333

    class FakeMessageItem:
        def __init__(self) -> None:
            self.id = 111
            self.media = []
            self.isFromQueue = True
            self.queueId = 333

    fake_user = SimpleNamespace(
        id=2468,
        username="creator",
        scrape_manager=SimpleNamespace(
            scraped=SimpleNamespace(
                Posts={},
                Messages={},
                Stories={},
                Highlights={},
                MassMessages={333: FakeMassMessage()},
            )
        ),
    )
    fake_user.release_cached_content = lambda *names: (
        StreamlinedUser.release_cached_content(fake_user, *names)
    )

    async def fake_fetch_content_items(
        user,
        content_type,
        max_items,
        job_id,
        worker_id,
        on_progress=None,
    ):
        return [FakeMessageItem()]

    async def fake_save_content_to_db(
        content_items,
        user_id,
        content_type,
        worker_id="unknown",
        auth_user_id=None,
        record_bought_content=False,
        on_progress=None,
        *,
        database_writes,
        site,
        media_selection=None,
        error_offset=0,
    ):
        assert media_selection is None
        assert error_offset == 0
        saved_calls.append((user_id, content_type, record_bought_content))
        return len(content_items), []

    monkeypatch.setattr(content, "_fetch_content_items", fake_fetch_content_items)
    monkeypatch.setattr(content, "save_content_to_db", fake_save_content_to_db)

    items_scraped, items_saved, errors, media_urls = await content.scrape_content_type(
        fake_user,
        ContentType.MESSAGES,
        max_items=None,
        auth_name="auth_user",
        worker_id="worker-1",
        job_id=None,
        auth_user_id=10001,
        database_writes=MagicMock(),
        site="onlyfans",
    )

    assert items_scraped == 1
    assert items_saved == 2
    assert errors == []
    assert media_urls == []
    assert saved_calls == [
        (2468, ContentType.MASS_MESSAGES, False),
        (2468, ContentType.MESSAGES, False),
    ]
    assert fake_user.scrape_manager.scraped.MassMessages == {}


def test_create_or_update_subscription_never_downgrades_paid_content() -> None:
    from ultima_scraper_backend.database.base_manager import BaseDatabaseManager

    class DummyManager(BaseDatabaseManager):
        def connect(self) -> None:
            pass

        def disconnect(self) -> None:
            pass

        def get_session(self):
            raise NotImplementedError

    mgr = DummyManager("onlyfans")
    mgr.ensure_connected = lambda: None  # type: ignore[method-assign]
    mgr._commit_or_flush = lambda session, close_session: None  # type: ignore[method-assign]
    mgr._refresh_safe = lambda session, obj: None  # type: ignore[method-assign]
    mgr._rollback_if_owned = lambda session, close_session: None  # type: ignore[method-assign]

    existing_sub = SimpleNamespace(
        user_id=100,
        subscriber_id=200,
        paid_content=True,
        active=True,
        expires_at=None,
    )

    class FakeSession:
        def exec(self, _stmt):
            return SimpleNamespace(first=lambda: existing_sub)

        def add(self, _obj):
            pass

    sub, created = mgr.create_or_update_subscription(
        user_id=100,
        subscriber_id=200,
        data={"paid_content": False, "active": False},
        session=FakeSession(),  # type: ignore[arg-type]
    )
    assert created is False
    assert sub.paid_content is True
    assert sub.active is False
