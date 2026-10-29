from __future__ import annotations

import asyncio
from contextlib import aclosing
from types import SimpleNamespace

import pytest

from ultima_scraper_api.managers.scrape_manager import ScrapeManager


def manager(limit: int = 2):
    return ScrapeManager(
        SimpleNamespace(
            auth_session=SimpleNamespace(
                session_manager=SimpleNamespace(max_threads=limit)
            ),
            api=SimpleNamespace(CategorizedContent=lambda: None),
        )
    )


@pytest.mark.asyncio
async def test_million_page_source_has_bounded_admission_and_cleans_up(monkeypatch):
    scraper = manager()
    admitted = []
    closed = []
    saturated = asyncio.Event()

    def urls():
        try:
            for index in range(1_000_000):
                yield str(index)
        finally:
            closed.append("source")

    async def scrape(url):
        admitted.append(url)
        if len(admitted) == 3:
            saturated.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(url)

    monkeypatch.setattr(scraper, "scrape", scrape)

    async def consume():
        async with aclosing(scraper.iter_scrape(urls(), concurrency=3)) as items:
            async for _ in items:
                pass

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(saturated.wait(), timeout=1)
        assert admitted == ["0", "1", "2"]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert set(closed) == {"0", "1", "2", "source"}


@pytest.mark.asyncio
async def test_bulk_preserves_flattening_failures_and_exact_progress(monkeypatch):
    scraper = manager()
    events = []

    async def scrape(url):
        if url == "failed":
            raise RuntimeError("request failed")
        return {"list": [1, 2], "object": {"id": 3}, "empty": []}[url]

    async def progress(completed, total, count):
        events.append((completed, total, count))

    monkeypatch.setattr(scraper, "scrape", scrape)
    values = await scraper.bulk_scrape(["list", "failed", "object", "empty"], progress)
    assert len(values) == 3
    assert 1 in values and 2 in values and {"id": 3} in values
    assert events[-1] == (4, 4, 3)
    assert [event[0] for event in events] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_stream_delivers_before_input_is_exhausted(monkeypatch):
    scraper = manager()
    source_closed = False

    async def urls():
        nonlocal source_closed
        try:
            yield "first"
            await asyncio.Event().wait()
        finally:
            source_closed = True

    async def scrape(url):
        return [{"url": url}]

    monkeypatch.setattr(scraper, "scrape", scrape)
    async with aclosing(scraper.iter_scrape(urls())) as values:
        assert await asyncio.wait_for(anext(values), timeout=1) == {"url": "first"}
    assert source_closed


def test_onlyfans_page_urls_are_lazy_at_large_archive_sizes():
    import tracemalloc
    from ultima_scraper_api.apis.onlyfans.classes.extras import endpoint_links

    endpoints = endpoint_links()
    url = "https://onlyfans.com/api2/v2/users/7/posts?limit=50&offset=0&order=publish_date_desc"
    tracemalloc.start()
    try:
        pages = endpoints.iter_links(url, max_items=1_000_000, pagination_limit=50)
        assert next(pages) == url
        assert next(pages) == url.replace("offset=0", "offset=50")
        _, peak = tracemalloc.get_traced_memory()
        assert peak < 32 * 1024
        pages.close()
    finally:
        tracemalloc.stop()
    assert endpoints.create_links(url, max_items=51, pagination_limit=50) == [
        url,
        url.replace("offset=0", "offset=50"),
    ]


@pytest.fixture
def onlyfans_user(monkeypatch):
    from ultima_scraper_api.apis.onlyfans.classes.auth_model import OnlyFansAuthModel
    from ultima_scraper_api.apis.onlyfans.classes.user_model import UserModel
    from ultima_scraper_api.managers import redis

    class ContentCache:
        def __init__(self):
            for name in ("Posts", "Messages", "MassMessages", "Stories", "Highlights"):
                setattr(self, name, {})

    class Auth:
        id = 99
        user = SimpleNamespace(id=99)

        def __init__(self):
            self.users = {}
            self.api = SimpleNamespace(CategorizedContent=ContentCache)
            self.auth_session = SimpleNamespace(
                session_manager=SimpleNamespace(max_threads=2)
            )

        def get_api(self):
            return self.api

        def find_user(self, identifier):
            return self.users.get(identifier)

        def add_user(self, user):
            self.users[user.id] = user

        resolve_user = OnlyFansAuthModel.resolve_user

    async def publish(_):
        pass

    monkeypatch.setattr(redis, "publish_custom_event", publish)
    return UserModel({"id": 7, "username": "seven", "postsCount": 1_000_000}, Auth())


def _post(identifier, **extra):
    return {
        "id": identifier,
        "responseType": "post",
        "price": 0,
        "postedAt": "2026-09-05T00:00:00+00:00",
        "postedAtPrecise": "0",
        "media": [],
        **extra,
    }


@pytest.mark.asyncio
async def test_posts_stream_does_not_retain_models_or_linked_authors(
    onlyfans_user, monkeypatch
):
    import weakref
    import gc

    refs = weakref.WeakSet()
    user = onlyfans_user

    async def scrape(url):
        from urllib.parse import parse_qs, urlparse

        offset = int(parse_qs(urlparse(url).query).get("offset", ["0"])[0])
        return [
            _post(
                offset + i,
                linkedUsers=[{"id": offset + i + 100_000}],
                linkedPosts=[
                    _post(offset + i + 200_000, author={"id": offset + i + 300_000})
                ],
            )
            for i in range(50)
        ]

    monkeypatch.setattr(user.scrape_manager, "scrape", scrape)
    count = 0
    async with aclosing(user.iter_posts(limit=1001)) as values:
        async for post in values:
            refs.add(post)
            count += 1
    gc.collect()
    assert count == 1001
    assert len(refs) == 1  # Only the loop variable remains live.
    assert not user.scrape_manager.scraped.Posts
    assert set(user.get_authed().users) == {user.id}


@pytest.mark.asyncio
async def test_posts_compatibility_cache_and_zero_limit(onlyfans_user, monkeypatch):
    user = onlyfans_user

    async def scrape(url):
        return [_post(1), _post(2)]

    monkeypatch.setattr(user.scrape_manager, "scrape", scrape)
    assert [value async for value in user.iter_posts(limit=0)] == []
    values = [value async for value in user.iter_posts(limit=1, cache=True)]
    assert [value.id for value in values] == [1]
    assert list(user.scrape_manager.scraped.Posts) == [1]


@pytest.mark.asyncio
async def test_messages_stream_bounds_pages_and_total_independently(onlyfans_user):
    from urllib.parse import parse_qs, urlparse

    user = onlyfans_user
    calls = []

    async def request(url):
        args = parse_qs(urlparse(url).query)
        calls.append(args)
        offset = int(args.get("id", ["100"])[0])
        return {
            "list": [
                dict(
                    id=offset - i - 1,
                    fromUser={"id": 7},
                    createdAt="2026-09-05T00:00:00+00:00",
                )
                for i in range(2)
            ],
            "hasMore": True,
        }

    user.get_requester().json_request = request
    messages = [value async for value in user.iter_messages(limit=2, max_items=3)]
    assert [message.id for message in messages] == [99, 98, 97]
    assert len(calls) == 2
    assert all(call["limit"] == ["2"] for call in calls)
    assert not user.scrape_manager.scraped.Messages


@pytest.mark.asyncio
async def test_message_bad_cursor_stops_without_recursion(onlyfans_user):
    user = onlyfans_user

    async def request(url):
        return {
            "list": [
                dict(id=5, fromUser={"id": 7}, createdAt="2026-09-05T00:00:00+00:00")
            ],
            "hasMore": True,
        }

    user.get_requester().json_request = request
    with pytest.raises(RuntimeError, match="did not advance"):
        async with aclosing(user.iter_messages()) as values:
            async for _ in values:
                pass


@pytest.mark.asyncio
async def test_incremental_recursion_compatibility_respects_remaining_limit():
    from ultima_scraper_api.apis.onlyfans.classes.user_model import recursion

    pages = iter(
        [
            {"list": [{"id": 1}, {"id": 2}], "hasMore": True},
            {"list": [{"id": 3}, {"id": 4}], "hasMore": True},
        ]
    )

    async def request(url):
        return next(pages)

    result = await recursion(
        "list_subscriptions",
        SimpleNamespace(json_request=request),
        3,
        query_type="active",
        limit=2,
    )
    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]


@pytest.mark.asyncio
async def test_posts_partial_page_is_exact_when_pages_finish_out_of_order(
    onlyfans_user, monkeypatch
):
    from urllib.parse import parse_qs, urlparse

    last_ready = asyncio.Event()

    async def scrape(url):
        args = parse_qs(urlparse(url).query)
        offset, limit = int(args["offset"][0]), int(args["limit"][0])
        if offset == 0:
            await last_ready.wait()
        else:
            last_ready.set()
        return [_post(offset + i) for i in range(limit)]

    monkeypatch.setattr(onlyfans_user.scrape_manager, "scrape", scrape)
    values = [post.id async for post in onlyfans_user.iter_posts(limit=51)]
    assert len(values) == 51
    assert set(values) == set(range(51))


@pytest.mark.asyncio
async def test_scrape_batches_persist_before_next_admission_and_bound_errors(
    onlyfans_user, monkeypatch
):
    from ultima_scraper_api import ContentType
    from ultima_scraper_backend.job_system.handlers.scrape import content as handler
    from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation

    user = onlyfans_user
    admitted = saved = 0
    sizes = []
    evidence_count = 0
    closed = False

    async def posts(**kwargs):
        nonlocal admitted, closed
        try:
            for i in range(1001):
                assert admitted - saved < 7
                admitted += 1
                yield SimpleNamespace(id=i)
        finally:
            closed = True

    async def submit(operation, payload, **kwargs):
        nonlocal saved, evidence_count
        if operation == DatabaseWriteOperation.UPSERT_CONTENT_BATCH:
            sizes.append(len(payload["items"]))
            saved += len(payload["items"])
            assert payload["error_offset"] == evidence_count
            errors = [f"fixture error {row['id']}" for row in payload["items"]]
            evidence_count += len(errors)
            assert payload["media_selection"]["selection_id"] == "selection"
            return {"items_saved": 0, "errors": errors}
        assert payload["action"] == "seal"
        return {"total": 0}

    monkeypatch.setenv("ULTIMA_CONTENT_BATCH_SIZE", "7")
    monkeypatch.setenv("ULTIMA_TASK_RESULT_PREVIEW_MAX_ENTRIES", "2")
    monkeypatch.setenv("ULTIMA_TASK_RESULT_PREVIEW_MAX_BYTES", "4096")
    monkeypatch.setattr(user, "iter_posts", posts)
    monkeypatch.setattr(
        handler, "serialize_content_write_item", lambda item, **kwargs: {"id": item.id}
    )
    selection = dict(
        selection_id="selection",
        job_id="job",
        task_id="task",
        site="onlyfans",
        auth_id=99,
    )
    result = await handler.scrape_content_type(
        user,
        ContentType.POSTS,
        None,
        database_writes=SimpleNamespace(submit=submit),
        site="onlyfans",
        auth_user_id=99,
        media_selection=selection,
    )
    assert result == (1001, 0, ["fixture error 0", "fixture error 1"], [])
    assert selection["error_count"] == 1001
    assert max(sizes) == 7
    assert closed


@pytest.mark.asyncio
async def test_uncached_mass_messages_keep_their_parent_for_writer_order(onlyfans_user):
    from ultima_scraper_api.apis.onlyfans.classes.message_model import MessageModel
    from ultima_scraper_backend.job_system.handlers.scrape.content import (
        _collect_mass_messages_for_items,
    )

    raw = dict(
        id=1,
        fromUser={"id": 7},
        isFromQueue=True,
        queueId=10,
        previews=[],
        changedAt="2026-09-05",
        mediaCount=0,
        createdAt="2026-09-05T00:00:00+00:00",
    )
    message = MessageModel(raw, onlyfans_user, cache=False)
    assert message.mass_message is not None
    assert _collect_mass_messages_for_items(onlyfans_user, [message]) == [
        message.mass_message
    ]
    assert message.mass_message.is_bought()
    assert not onlyfans_user.scrape_manager.scraped.Messages
    assert not onlyfans_user.scrape_manager.scraped.MassMessages
