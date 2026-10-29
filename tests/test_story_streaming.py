"""Normal story/highlight scraping uses the bounded persistence path."""

from contextlib import aclosing
import gc
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import weakref

import pytest

from test_streaming_scrape import onlyfans_user

__all__ = ["onlyfans_user"]


def story(identifier):
    return {
        "id": identifier,
        "userId": 7,
        "canLike": True,
        "createdAt": "2026-09-07T00:00:00+00:00",
        "media": [],
    }


def album(identifier, stories=17):
    return {
        "id": identifier,
        "userId": 7,
        "title": f"Album {identifier}",
        "coverStoryId": identifier * 100,
        "cover": "",
        "storiesCount": stories,
        "createdAt": "2026-09-07T00:00:00+00:00",
    }


def install_highlights(user, *, albums=13, per_album=17):
    calls = []

    async def request(url):
        parsed = urlparse(url)
        calls.append(parsed)
        if parsed.path.endswith("/stories/highlights"):
            values = parse_qs(parsed.query)
            limit, offset = int(values["limit"][0]), int(values["offset"][0])
            end = min(albums, offset + limit)
            return {
                "list": [album(index, per_album) for index in range(offset, end)],
                "hasMore": end < albums,
            }
        identifier = int(parsed.path.rsplit("/", 1)[1])
        return {
            "stories": [story(identifier * 100 + index) for index in range(per_album)]
        }

    user.get_requester = lambda: SimpleNamespace(json_request=request)
    return calls


async def test_highlight_pages_release_models_and_honor_album_page_size(onlyfans_user):
    user = onlyfans_user
    calls = install_highlights(user)
    retained = weakref.WeakSet()
    identifiers = []
    async with aclosing(user.iter_highlight_stories(limit=4)) as source:
        async for value in source:
            assert value.expires_at is None
            retained.add(value)
            identifiers.append(value.id)
    gc.collect()
    assert identifiers == [
        group * 100 + index for group in range(13) for index in range(17)
    ]
    assert len(retained) == 1
    assert not user.scrape_manager.scraped.Stories
    assert not user.scrape_manager.scraped.Highlights
    pages = [
        parse_qs(call.query)
        for call in calls
        if call.path.endswith("/stories/highlights")
    ]
    assert [int(page["offset"][0]) for page in pages] == [0, 4, 8, 12]
    assert all(page["limit"] == ["4"] for page in pages)


async def test_highlight_story_limit_stops_before_later_album_requests(onlyfans_user):
    calls = install_highlights(onlyfans_user, albums=50, per_album=17)
    progress = []

    async def report(*values):
        progress.append(values)

    async with aclosing(
        onlyfans_user.iter_highlight_stories(limit=3, max_items=19, on_progress=report)
    ) as source:
        ids = [value.id async for value in source]
    assert ids == list(range(17)) + [100, 101]
    details = [call for call in calls if not call.path.endswith("/stories/highlights")]
    assert len(details) == 2
    assert progress[-1] == (2, 2, 19)


@pytest.mark.parametrize("kind", ["stories", "highlights"])
async def test_zero_selection_makes_no_request(onlyfans_user, kind):
    calls = install_highlights(onlyfans_user)
    iterator = (
        onlyfans_user.iter_stories
        if kind == "stories"
        else onlyfans_user.iter_highlight_stories
    )
    assert [item async for item in iterator(max_items=0)] == []
    assert not calls


async def test_repeated_highlight_page_fails_without_growing_a_seen_set(onlyfans_user):
    async def request(url):
        if urlparse(url).path.endswith("/stories/highlights"):
            return {"list": [album(1)], "hasMore": True}
        return {"stories": [story(100)]}

    onlyfans_user.get_requester = lambda: SimpleNamespace(json_request=request)
    async with aclosing(onlyfans_user.iter_highlight_stories(limit=1)) as source:
        assert (await anext(source)).id == 100
        with pytest.raises(RuntimeError, match="repeated"):
            await anext(source)


async def test_early_story_close_releases_the_owned_source(onlyfans_user, monkeypatch):
    closed = []

    async def values(*args, **kwargs):
        try:
            yield story(1)
            raise AssertionError("must not advance a closed story iterator")
        finally:
            closed.append(True)

    monkeypatch.setattr(onlyfans_user.scrape_manager, "iter_scrape", values)
    async with aclosing(onlyfans_user.iter_stories()) as source:
        assert (await anext(source)).id == 1
    assert closed == [True]
    assert not onlyfans_user.scrape_manager.scraped.Stories


@pytest.mark.parametrize("failure", ["album", "page"])
async def test_highlight_failure_retains_prior_batches_and_reports_error(
    onlyfans_user, monkeypatch, failure
):
    from ultima_scraper_api import ContentType
    from ultima_scraper_api.apis.onlyfans.classes.extras import ErrorDetails
    from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
    from ultima_scraper_backend.job_system.handlers.scrape import content as handler

    actions, saved_ids = [], []

    async def request(url):
        parsed = urlparse(url)
        if parsed.path.endswith("/stories/highlights"):
            if int(parse_qs(parsed.query)["offset"][0]) == 0:
                return {
                    "list": [album(1)] if failure == "page" else [album(1), album(2)],
                    "hasMore": failure == "page",
                }
        elif parsed.path.endswith("/1"):
            return {"stories": [story(index) for index in range(7)]}
        return ErrorDetails({"error": {"code": 500, "message": "request failed"}})

    async def submit(operation, payload, **kwargs):
        if operation == DatabaseWriteOperation.UPSERT_CONTENT_BATCH:
            saved_ids.extend(item["id"] for item in payload["items"])
            return {"items_saved": len(payload["items"]), "errors": []}
        assert operation == DatabaseWriteOperation.UPDATE_MEDIA_SELECTION
        actions.append(payload["action"])
        return {}

    monkeypatch.setenv("ULTIMA_CONTENT_BATCH_SIZE", "7")
    onlyfans_user.get_requester = lambda: SimpleNamespace(json_request=request)
    selection = dict(
        selection_id="failed-highlight",
        job_id="job",
        task_id="task",
        site="onlyfans",
        auth_id=99,
    )
    scraped, saved, errors, media = await handler.scrape_content_type(
        onlyfans_user,
        ContentType.HIGHLIGHTS,
        None,
        database_writes=SimpleNamespace(submit=submit),
        site="onlyfans",
        media_selection=selection,
    )
    assert scraped == saved == 7
    assert saved_ids == list(range(7))
    assert len(errors) == 1 and "request failed" in errors[0]
    assert actions == ["evidence", "seal"]
    assert selection["error_count"] == 1
    assert media == []
    assert not onlyfans_user.scrape_manager.scraped.Stories
    assert not onlyfans_user.scrape_manager.scraped.Highlights


async def test_public_collectors_keep_their_cache_and_error_contracts(
    onlyfans_user, monkeypatch
):
    from ultima_scraper_api.apis.onlyfans.classes.extras import ErrorDetails

    user = onlyfans_user
    install_highlights(user, albums=2, per_album=3)
    groups = await user.get_highlights()
    assert [group.id for group in groups] == [0, 1]
    assert set(user.scrape_manager.scraped.Highlights) == {0, 1}
    values = await user.get_highlights(hightlight_id="1")
    assert [value.id for value in values] == [100, 101, 102]
    assert set(user.scrape_manager.scraped.Stories) == {100, 101, 102}

    async def failed(_):
        return ErrorDetails({"error": {"code": 404, "message": "not found"}})

    user.get_requester = lambda: SimpleNamespace(json_request=failed)
    assert await user.get_highlights(hightlight_id="1") == []

    async def scrape(_):
        return [story(200), story(201)]

    monkeypatch.setattr(user.scrape_manager, "scrape", scrape)
    ordinary = await user.get_stories()
    assert [value.id for value in ordinary] == [200, 201]
    assert all(value.expires_at is not None for value in ordinary)
    assert {200, 201} <= set(user.scrape_manager.scraped.Stories)


@pytest.mark.parametrize("kind", ["Stories", "Highlights"])
async def test_normal_story_handler_persists_before_next_batch(
    onlyfans_user, monkeypatch, kind
):
    from ultima_scraper_api import ContentType
    from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
    from ultima_scraper_backend.job_system.handlers.scrape import content as handler
    from ultima_scraper_api.apis.onlyfans.classes.story_model import StoryModel

    user = onlyfans_user
    install_highlights(user, albums=20, per_album=17)
    written = built = 0
    calls = []
    original = StoryModel.__init__

    def construct(self, *args, **kwargs):
        nonlocal built
        assert built - written < 7
        original(self, *args, **kwargs)
        built += 1

    async def scrape(_):
        return [story(index) for index in range(340)]

    async def submit(operation, payload, **kwargs):
        nonlocal written
        if operation == DatabaseWriteOperation.UPSERT_CONTENT_BATCH:
            ids = [value["id"] for value in payload["items"]]
            assert len(ids) <= 7
            calls.extend(ids)
            written += len(ids)
            assert not user.scrape_manager.scraped.Stories
            assert not user.scrape_manager.scraped.Highlights
            return {"items_saved": len(ids), "errors": []}
        assert payload["action"] == "seal"
        return {"total": written}

    monkeypatch.setenv("ULTIMA_CONTENT_BATCH_SIZE", "7")
    monkeypatch.setattr(StoryModel, "__init__", construct)
    monkeypatch.setattr(user.scrape_manager, "scrape", scrape)
    selection = dict(
        selection_id="stories",
        job_id="job",
        task_id="task",
        site="onlyfans",
        auth_id=99,
    )
    result = await handler.scrape_content_type(
        user,
        ContentType(kind),
        19,
        database_writes=SimpleNamespace(submit=submit),
        site="onlyfans",
        auth_user_id=99,
        media_selection=selection,
    )
    expected = list(range(19)) if kind == "Stories" else list(range(17)) + [100, 101]
    assert calls == expected
    assert result == (19, 19, [], [])
    assert built == written == 19
