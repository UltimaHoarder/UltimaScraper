from __future__ import annotations

import asyncio
import gc
import weakref
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from ultima_scraper_api import ContentType
from ultima_scraper_api.apis.auth_streamliner import Cache
from ultima_scraper_api.apis.onlyfans.classes.auth_model import OnlyFansAuthModel
from ultima_scraper_api.apis.onlyfans.classes.chat_model import ChatModel
from ultima_scraper_api.apis.onlyfans.classes.user_model import UserModel
from ultima_scraper_api.managers import redis

import ultima_scraper_backend.job_system.handlers.scrape.handler as handler
from ultima_scraper_backend.job_system.models import Job, Task, TaskRunContext, TaskType
from ultima_scraper_backend.job_system.payloads import ScrapeTaskPayload


@pytest.fixture
def auth(monkeypatch):
    class ContentCache:
        def __init__(self):
            for name in ("Posts", "Messages", "MassMessages", "Stories", "Highlights"):
                setattr(self, name, {})

    # Real auth/user/cache methods with only the network and bootstrap replaced.
    value = OnlyFansAuthModel.__new__(OnlyFansAuthModel)
    value.users = {}
    value.chats = []
    value.subscriptions = []
    value.cache = Cache()
    value.api = SimpleNamespace(CategorizedContent=ContentCache)
    value.authenticator = SimpleNamespace(api=value.api)
    value.auth_session = SimpleNamespace(
        json_request=AsyncMock(),
        session_manager=SimpleNamespace(max_threads=2),
    )
    value.user = UserModel({"id": 99, "username": "fixture-auth"}, value)
    value.id = 99
    value.username = "fixture-auth"
    value.guest = False
    monkeypatch.setattr(redis, "publish_custom_event", AsyncMock())
    return value


@pytest.mark.asyncio
async def test_normal_profile_lookups_do_not_accumulate_users_or_timers(auth):
    async def request(url):
        identifier = int(urlsplit(url).path.rsplit("/", 1)[1])
        return {"id": identifier, "username": f"fixture-{identifier}"}

    auth.auth_session.json_request = request
    live_users = weakref.WeakSet()
    for identifier in range(1000, 3000):
        user = await handler._resolve_scrape_user(
            auth, user_id=identifier, username=str(identifier), worker_id="fixture"
        )
        assert user.id == identifier
        live_users.add(user)
    del user
    gc.collect()
    assert len(live_users) == 0
    assert set(auth.users) == {99}
    assert auth.cache.data["users"] == {}


@pytest.mark.asyncio
async def test_existing_account_users_are_preserved(auth):
    cached = UserModel({"id": 7, "username": "seven"}, auth)
    auth.subscriptions.append(SimpleNamespace(user=cached))
    auth.cache.users(7).activate()
    resolved = await handler._resolve_scrape_user(
        auth, user_id=7, username="seven", worker_id="fixture"
    )
    assert resolved is cached
    assert auth.users[7] is cached
    assert auth.subscriptions[0].user is cached
    assert not auth.cache.users(7).is_released()
    auth.auth_session.json_request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", [ContentType.POSTS, ContentType.PROFILE])
async def test_normal_task_refresh_does_not_register_profile(
    auth, monkeypatch, content_type
):
    auth.auth_session.json_request.side_effect = [
        {"id": 7, "username": "seven", "postsCount": 0},
        {"id": 7, "username": "seven", "postsCount": 3},
    ] + ([[]] if content_type == ContentType.PROFILE else [])
    monkeypatch.setattr(handler, "publish_hook_event", AsyncMock())
    monkeypatch.setattr(handler, "publish_event", lambda _: None)
    monkeypatch.setattr(
        handler, "scrape_content_type", AsyncMock(return_value=(3, 3, [], []))
    )
    monkeypatch.setattr(
        handler, "serialize_user_write_payload", AsyncMock(return_value={"id": 7})
    )
    task = Task(
        site_name="onlyfans",
        user_id=7,
        user_username="seven",
        content_type=content_type,
        task_type=TaskType.SCRAPE,
        auth_id=99,
        payload=ScrapeTaskPayload(user_username="seven", download_media=False),
    )
    context = TaskRunContext(
        job=Job(name="lifetime", created_by="pytest", tasks=[task]),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(find_auth=lambda _: auth),
            "db_managers": {
                "onlyfans": SimpleNamespace(
                    get_user_auth=lambda _: SimpleNamespace(user_id=99)
                )
            },
            "site": "onlyfans",
            "worker_id": "fixture",
            "database_writes": SimpleNamespace(submit=AsyncMock()),
        },
    )
    result = await handler.scrape_task_handler(task, context)
    assert result.success, result.errors
    # Profiles also fetch socials after the two user lookups.
    assert auth.auth_session.json_request.await_count == (3 if content_type == ContentType.PROFILE else 2)
    assert set(auth.users) == {99}
    assert auth.cache.data["users"] == {}


def chat_data(identifier):
    return {
        "withUser": {"id": identifier, "username": f"fixture-{identifier}"},
        "lastMessage": {
            "id": identifier + 10000,
            "fromUser": {"id": identifier + 10000},
            "createdAt": "2026-09-07T00:00:00+00:00",
            "media": [],
        },
        "lastReadMessageId": 0,
        "hasPurchasedFeed": False,
        "countPinnedMessages": 0,
    }


@pytest.mark.asyncio
async def test_chat_lookup_stops_on_match_and_retains_no_previous_pages(auth):
    pages = []

    async def request(url):
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        if "query" in query:
            return {"list": [], "hasMore": False}
        offset = int(query["offset"][0])
        limit = int(query["limit"][0])
        pages.append((offset, limit))
        return {
            "list": [chat_data(1000 + i) for i in range(offset, offset + limit)],
            "hasMore": True,
        }

    auth.auth_session.json_request = request
    user = await handler._resolve_user_from_chats(
        auth, user_id=1250, username="fixture-1250", worker_id="fixture"
    )
    assert user.id == 1250
    assert pages == [(0, 100), (100, 100), (200, 100)]
    assert set(auth.users) == {99}
    assert auth.chats == []
    assert auth.cache.data["users"] == {}
    assert auth.user.scrape_manager.scraped.Messages == {}


@pytest.mark.asyncio
async def test_chat_stream_releases_models_and_respects_offset_and_limit(auth):
    pages = []
    chats = weakref.WeakSet()
    users = weakref.WeakSet()

    async def request(url):
        query = parse_qs(urlsplit(url).query)
        offset, limit = int(query["offset"][0]), int(query["limit"][0])
        pages.append((offset, limit))
        return {
            "list": [chat_data(1000 + i) for i in range(offset, offset + limit)],
            "hasMore": True,
        }

    auth.auth_session.json_request = request
    count = 0
    async with aclosing(auth.iter_chats(limit=1001, offset=500)) as stream:
        async for chat in stream:
            chats.add(chat)
            users.add(chat.user)
            users.add(chat.last_message.author)
            count += 1
    del chat
    gc.collect()
    assert count == 1001
    assert pages == [(offset, 100) for offset in range(500, 1600, 100)]
    assert len(chats) == len(users) == 0
    assert set(auth.users) == {99}
    assert auth.chats == []


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1])
async def test_chat_stream_validates_limits_before_request(auth, limit):
    if limit < 0:
        with pytest.raises(ValueError):
            await anext(auth.iter_chats(limit=limit))
    else:
        assert [chat async for chat in auth.iter_chats(limit=limit)] == []
    auth.auth_session.json_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_search_keeps_query_and_has_finite_result_budget(auth):
    auth.auth_session.json_request.return_value = {
        "list": [chat_data(i) for i in range(200, 300)],
        "hasMore": True,
    }
    values = [chat async for chat in auth.iter_chats(query="a b", limit=50, offset=12)]
    assert len(values) == 50
    assert auth.auth_session.json_request.await_count == 1
    query = parse_qs(urlsplit(auth.auth_session.json_request.call_args.args[0]).query)
    assert query["query"] == ["a b"]
    assert query["offset"] == ["12"]
    assert query["limit"] == ["50"]
    assert set(auth.users) == {99}


@pytest.mark.asyncio
async def test_chat_lookup_closes_stream_on_early_match(auth, monkeypatch):
    closed = []

    async def stream(**kwargs):
        try:
            yield ChatModel(chat_data(7), auth, cache=False)
            raise AssertionError("must stop at match")
        finally:
            closed.append(True)

    monkeypatch.setattr(auth, "iter_chats", stream)
    assert (
        await handler._resolve_user_from_chats(
            auth, user_id=7, username=None, worker_id="fixture"
        )
    ).id == 7
    assert closed == [True]


@pytest.mark.asyncio
async def test_chat_lookup_cancellation_closes_stream(auth, monkeypatch):
    entered, closed = asyncio.Event(), asyncio.Event()

    async def stream(**kwargs):
        try:
            entered.set()
            await asyncio.Event().wait()
            yield
        finally:
            closed.set()

    monkeypatch.setattr(auth, "iter_chats", stream)
    task = asyncio.create_task(
        handler._resolve_user_from_chats(
            auth, user_id=7, username=None, worker_id="fixture"
        )
    )
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


def test_chat_collector_default_still_caches_models(auth):
    chat = ChatModel(chat_data(7), auth)
    assert auth.users[7] is chat.user
    assert auth.users[10007] is chat.last_message.author
    assert auth.users[10007].scrape_manager.scraped.Messages[10007] is chat.last_message


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [0, 7])
@pytest.mark.parametrize("failed", [False, True])
async def test_download_lookup_does_not_retain_profile(
    auth, monkeypatch, user_id, failed
):
    from ultima_scraper_backend.job_system.handlers.download import handler as downloads
    from ultima_scraper_backend.job_system.handlers.download import streaming
    from ultima_scraper_backend.job_system.models import TaskResult
    from ultima_scraper_backend.job_system.payloads import DownloadTaskPayload

    auth.auth_session.json_request.return_value = {"id": 7, "username": "seven"}
    task = Task(
        site_name="onlyfans",
        user_id=user_id,
        user_username="seven",
        content_type=ContentType.POSTS,
        task_type=TaskType.DOWNLOAD,
        auth_id=99,
        payload=DownloadTaskPayload(),
    )
    context = SimpleNamespace(
        site_api=SimpleNamespace(find_auth=lambda _: auth),
        db_managers={
            "onlyfans": SimpleNamespace(
                get_user_auth=lambda _: SimpleNamespace(user_id=99)
            )
        },
        previous_output=None,
        user_manager=None,
        database_writes=object(),
    )

    async def load_user(_, *, user_id, **kwargs):
        return SimpleNamespace(id=7, username="seven", aliases=[]) if user_id else None

    async def download(**kwargs):
        assert kwargs["user"].id == 7
        assert set(auth.users) == {99}
        if failed:
            raise RuntimeError("fixture download failed")
        return TaskResult(success=True)

    monkeypatch.setattr(downloads, "ensure_config", lambda _: SimpleNamespace())
    monkeypatch.setattr(downloads, "_load_db_user", load_user)
    monkeypatch.setattr(streaming, "download_selected_media", download)
    if failed:
        with pytest.raises(RuntimeError, match="fixture download failed"):
            await downloads.download_task_handler(task, context)
    else:
        assert (await downloads.download_task_handler(task, context)).success
    assert task.user_id == 7
    assert set(auth.users) == {99}
    assert auth.cache.data["users"] == {}
    auth.auth_session.json_request.assert_awaited_once()
