from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from ultima_scraper_api import ContentType

import ultima_scraper_backend.job_system.handlers.scrape.handler as scrape_handler_module
from ultima_scraper_backend.job_system.models import (
    Job,
    Task,
    TaskRunContext,
    TaskType,
)
from ultima_scraper_backend.job_system.payloads import ScrapeTaskPayload


def _onlyfans_posts_task(*, max_items: int | None = None) -> Task:
    return Task(
        site_name="onlyfans",
        user_id=516734820,
        user_username="onlyfans",
        content_type=ContentType.POSTS,
        task_type=TaskType.SCRAPE,
        auth_id=9001,
        payload=ScrapeTaskPayload(
            user_username="onlyfans",
            max_items=max_items,
            download_media=False,
            rescrape_existing=False,
        ),
    )


def _onlyfans_posts_context(authed: object, task: Task) -> TaskRunContext:
    site_api = SimpleNamespace(
        find_auth=lambda auth_id: authed if auth_id == getattr(authed, "id", None) else None
    )
    job = Job(name="post scrape", created_by="pytest", tasks=[task])
    return TaskRunContext(
        job=job,
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": site_api,
            "db_managers": {
                "onlyfans": SimpleNamespace(
                    get_user_auth=lambda auth_id: SimpleNamespace(user_id=auth_id)
                )
            },
            "site": "onlyfans",
            "worker_id": "worker-posts",
            "database_writes": SimpleNamespace(submit=AsyncMock()),
        },
    )


@pytest.mark.asyncio
async def test_resolve_scrape_user_stops_after_authoritative_mps_id_miss() -> None:
    get_user = AsyncMock(return_value=None)
    search_chats = AsyncMock(side_effect=AssertionError("must not search chats"))
    get_chats = AsyncMock(side_effect=AssertionError("must not list chats"))
    authed = SimpleNamespace(
        find_user=lambda _identifier: None,
        get_user=get_user,
        search_chats=search_chats,
        get_chats=get_chats,
    )

    resolved = await scrape_handler_module._resolve_scrape_user(
        authed,
        user_id=1007,
        username="1007",
        worker_id="worker-mps",
    )

    assert resolved is None
    get_user.assert_awaited_once_with("1007")
    search_chats.assert_not_awaited()
    get_chats.assert_not_awaited()


@pytest.mark.asyncio
async def test_scrape_handler_resolves_message_user_via_chat_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved_user = SimpleNamespace(
        id=268927747,
        username="chat_target",
    )

    async def fake_get_user(_identifier: object) -> None:
        return None

    async def fake_search_chats(*, query: str, limit: int, offset: int) -> list[object]:
        assert query == "chat_target"
        assert limit == 50
        assert offset == 0
        return [SimpleNamespace(user=resolved_user)]

    authed = SimpleNamespace(
        id=41900816,
        username="buyer",
        find_user=lambda _identifier: None,
        get_user=fake_get_user,
        search_chats=fake_search_chats,
    )
    site_api = SimpleNamespace(find_auth=lambda auth_id: authed if auth_id == 41900816 else None)

    captured: dict[str, object] = {}

    async def fake_scrape_content_type(*args, **kwargs):
        user = args[0]
        content_type = args[1]
        captured["user"] = user
        captured["content_type"] = content_type
        return 3, 2, [], []

    monkeypatch.setattr(
        scrape_handler_module,
        "scrape_content_type",
        fake_scrape_content_type,
    )
    monkeypatch.setattr(
        scrape_handler_module,
        "publish_hook_event",
        AsyncMock(),
    )

    task = Task(
        site_name="onlyfans",
        user_id=268927747,
        user_username="chat_target",
        content_type=ContentType.MESSAGES,
        task_type=TaskType.SCRAPE,
        auth_id=41900816,
        payload=ScrapeTaskPayload(
            user_username="chat_target",
            max_items=25,
            download_media=False,
            rescrape_existing=False,
        ),
    )
    job = Job(name="message scrape", created_by="pytest", tasks=[task])
    storage = SimpleNamespace(persist_task=AsyncMock())
    context = TaskRunContext(
        job=job,
        storage=storage,
        previous_output=None,
        context={
            "site_api": site_api,
            "db_managers": {
                "onlyfans": SimpleNamespace(
                    get_user_auth=lambda auth_id: SimpleNamespace(user_id=auth_id)
                )
            },
            "site": "onlyfans",
            "worker_id": "worker-1",
            "database_writes": SimpleNamespace(submit=AsyncMock()),
        },
    )

    result = await scrape_handler_module.scrape_task_handler(task, context)

    assert result.success is True
    assert captured["user"] is resolved_user
    assert captured["content_type"] == ContentType.MESSAGES
    storage.persist_task.assert_awaited()


@pytest.mark.asyncio
async def test_scrape_handler_resolves_numeric_chat_identifier_via_chat_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved_user = SimpleNamespace(
        id=268927747,
        username="chat_target",
    )

    async def fake_get_user(_identifier: object) -> None:
        return None

    async def fake_get_chats(*, limit: int, offset: int) -> list[object]:
        assert limit == 100
        assert offset == 0
        return [SimpleNamespace(user=resolved_user)]

    authed = SimpleNamespace(
        id=41900816,
        username="buyer",
        find_user=lambda _identifier: None,
        get_user=fake_get_user,
        get_chats=fake_get_chats,
    )
    site_api = SimpleNamespace(find_auth=lambda auth_id: authed if auth_id == 41900816 else None)

    captured: dict[str, object] = {}

    async def fake_scrape_content_type(*args, **kwargs):
        user = args[0]
        content_type = args[1]
        captured["user"] = user
        captured["content_type"] = content_type
        return 3, 2, [], []

    monkeypatch.setattr(
        scrape_handler_module,
        "scrape_content_type",
        fake_scrape_content_type,
    )
    monkeypatch.setattr(
        scrape_handler_module,
        "publish_hook_event",
        AsyncMock(),
    )

    task = Task(
        site_name="onlyfans",
        user_id=0,
        user_username="268927747",
        content_type=ContentType.MESSAGES,
        task_type=TaskType.SCRAPE,
        auth_id=41900816,
        payload=ScrapeTaskPayload(
            user_username="268927747",
            max_items=25,
            download_media=False,
            rescrape_existing=False,
        ),
    )
    job = Job(name="message scrape", created_by="pytest", tasks=[task])
    storage = SimpleNamespace(persist_task=AsyncMock())
    context = TaskRunContext(
        job=job,
        storage=storage,
        previous_output=None,
        context={
            "site_api": site_api,
            "db_managers": {
                "onlyfans": SimpleNamespace(
                    get_user_auth=lambda auth_id: SimpleNamespace(user_id=auth_id)
                )
            },
            "site": "onlyfans",
            "worker_id": "worker-1",
            "database_writes": SimpleNamespace(submit=AsyncMock()),
        },
    )

    result = await scrape_handler_module.scrape_task_handler(task, context)

    assert result.success is True
    assert task.user_id == 268927747
    assert captured["user"] is resolved_user
    assert captured["content_type"] == ContentType.MESSAGES
    storage.persist_task.assert_awaited()


@pytest.mark.asyncio
async def test_scrape_handler_resolves_non_message_user_via_chat_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved_user = SimpleNamespace(
        id=268927747,
        username="chat_target",
    )

    async def fake_get_user(_identifier: object) -> None:
        return None

    async def fake_search_chats(*, query: str, limit: int, offset: int) -> list[object]:
        assert query == "chat_target"
        assert limit == 50
        assert offset == 0
        return [SimpleNamespace(user=resolved_user)]

    authed = SimpleNamespace(
        id=41900816,
        username="buyer",
        find_user=lambda _identifier: None,
        get_user=fake_get_user,
        search_chats=fake_search_chats,
    )
    site_api = SimpleNamespace(find_auth=lambda auth_id: authed if auth_id == 41900816 else None)

    captured: dict[str, object] = {}

    async def fake_scrape_content_type(*args, **kwargs):
        user = args[0]
        content_type = args[1]
        captured["user"] = user
        captured["content_type"] = content_type
        return 3, 2, [], []

    monkeypatch.setattr(
        scrape_handler_module,
        "scrape_content_type",
        fake_scrape_content_type,
    )
    monkeypatch.setattr(
        scrape_handler_module,
        "publish_hook_event",
        AsyncMock(),
    )

    task = Task(
        site_name="onlyfans",
        user_id=268927747,
        user_username="chat_target",
        content_type=ContentType.POSTS,
        task_type=TaskType.SCRAPE,
        auth_id=41900816,
        payload=ScrapeTaskPayload(
            user_username="chat_target",
            max_items=25,
            download_media=False,
            rescrape_existing=False,
        ),
    )
    job = Job(name="post scrape", created_by="pytest", tasks=[task])
    storage = SimpleNamespace(persist_task=AsyncMock())
    context = TaskRunContext(
        job=job,
        storage=storage,
        previous_output=None,
        context={
            "site_api": site_api,
            "db_managers": {
                "onlyfans": SimpleNamespace(
                    get_user_auth=lambda auth_id: SimpleNamespace(user_id=auth_id)
                )
            },
            "site": "onlyfans",
            "worker_id": "worker-1",
            "database_writes": SimpleNamespace(submit=AsyncMock()),
        },
    )

    result = await scrape_handler_module.scrape_task_handler(task, context)

    assert result.success is True
    assert captured["user"] is resolved_user
    assert captured["content_type"] == ContentType.POSTS
    storage.persist_task.assert_awaited()


@pytest.mark.asyncio
async def test_unbounded_onlyfans_posts_uses_hydrated_persisted_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(
        id=516734820,
        username="onlyfans",
        posts_count=554,
    )
    authed = SimpleNamespace(
        id=9001,
        username="u9001",
        find_user=lambda _identifier: user,
        get_user=AsyncMock(),
    )
    captured: dict[str, object] = {}

    async def fake_scrape_content_type(*args, **kwargs):
        captured["user"] = args[0]
        return 554, 554, [], []

    monkeypatch.setattr(
        scrape_handler_module,
        "scrape_content_type",
        fake_scrape_content_type,
    )
    monkeypatch.setattr(
        scrape_handler_module,
        "publish_hook_event",
        AsyncMock(),
    )

    task = _onlyfans_posts_task()
    result = await scrape_handler_module.scrape_task_handler(
        task,
        _onlyfans_posts_context(authed, task),
    )

    assert result.success is True
    assert captured["user"] is user
    authed.get_user.assert_not_awaited()
    assert result.output["items_total"] == 554
    assert result.metrics["items_total"] == 554
    assert result.metrics["worker_id"] == "worker-posts"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("site_name", "should_reject"),
    [("onlyfans", True), ("fansly", False)],
)
async def test_unbounded_posts_zero_result_guard_is_onlyfans(
    monkeypatch: pytest.MonkeyPatch,
    site_name: str,
    should_reject: bool,
) -> None:
    user = SimpleNamespace(
        id=516734820,
        username="onlyfans",
        posts_count=554,
    )
    authed = SimpleNamespace(
        id=9001,
        username="u9001",
        find_user=lambda _identifier: user,
        get_user=AsyncMock(),
    )

    monkeypatch.setattr(
        scrape_handler_module,
        "scrape_content_type",
        AsyncMock(return_value=(0, 0, [], [])),
    )
    monkeypatch.setattr(
        scrape_handler_module,
        "publish_hook_event",
        AsyncMock(),
    )

    task = _onlyfans_posts_task()
    task.site_name = site_name
    result = await scrape_handler_module.scrape_task_handler(
        task,
        _onlyfans_posts_context(authed, task),
    )

    assert result.success is (not should_reject)
    if should_reject:
        assert "profile reports 554 posts" in result.message.lower()


@pytest.mark.asyncio
async def test_unbounded_onlyfans_posts_refreshes_zero_cached_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached_user = SimpleNamespace(
        id=516734820,
        username="onlyfans",
        posts_count=0,
    )
    refreshed_user = SimpleNamespace(
        id=516734820,
        username="onlyfans",
        posts_count=3,
    )
    authed = SimpleNamespace(
        id=9001,
        username="u9001",
        find_user=lambda _identifier: cached_user,
        get_user=AsyncMock(return_value=refreshed_user),
    )
    captured: dict[str, object] = {}

    async def fake_scrape_content_type(*args, **kwargs):
        captured["user"] = args[0]
        return 3, 3, [], []

    monkeypatch.setattr(
        scrape_handler_module,
        "scrape_content_type",
        fake_scrape_content_type,
    )
    monkeypatch.setattr(
        scrape_handler_module,
        "publish_hook_event",
        AsyncMock(),
    )

    task = _onlyfans_posts_task()
    result = await scrape_handler_module.scrape_task_handler(
        task,
        _onlyfans_posts_context(authed, task),
    )

    assert result.success is True
    assert captured["user"] is refreshed_user
    authed.get_user.assert_awaited_once_with(516734820, refresh=True)
    assert result.output["items_total"] == 3
    assert result.metrics["items_total"] == 3


@pytest.mark.asyncio
async def test_unbounded_onlyfans_posts_allows_live_confirmed_empty_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cached_user = SimpleNamespace(
        id=516734820,
        username="onlyfans",
        posts_count=0,
    )
    refreshed_user = SimpleNamespace(
        id=516734820,
        username="onlyfans",
        posts_count=0,
    )
    authed = SimpleNamespace(
        id=9001,
        username="u9001",
        find_user=lambda _identifier: cached_user,
        get_user=AsyncMock(return_value=refreshed_user),
    )

    monkeypatch.setattr(
        scrape_handler_module,
        "scrape_content_type",
        AsyncMock(return_value=(0, 0, [], [])),
    )
    monkeypatch.setattr(
        scrape_handler_module,
        "publish_hook_event",
        AsyncMock(),
    )

    task = _onlyfans_posts_task()
    result = await scrape_handler_module.scrape_task_handler(
        task,
        _onlyfans_posts_context(authed, task),
    )

    assert result.success is True
    authed.get_user.assert_awaited_once_with(516734820, refresh=True)
    assert result.output["items_total"] == 0
    assert result.metrics["items_total"] == 0
