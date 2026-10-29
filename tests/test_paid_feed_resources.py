from __future__ import annotations

import asyncio
import gc
import weakref
from contextlib import aclosing, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

import test_subscription_resources as subscription_fixtures
from ultima_scraper_api.apis.onlyfans.classes.auth_model import OnlyFansAuthModel
from ultima_scraper_backend.database.write_queue import DatabaseWriteError
from ultima_scraper_backend.job_system.handlers.scrape import content
from ultima_scraper_backend.job_system.handlers.download import streaming
from ultima_scraper_backend.job_system.models import TaskResult

subscription_auth = subscription_fixtures.subscription_auth


def paid_item(identifier, *, author_id=None, message=False):
    author_id = identifier + 1000 if author_id is None else author_id
    raw = {
        "id": identifier,
        "responseType": "message" if message else "post",
        "price": 2,
        "text": f"Paid item {identifier}",
        "media": [],
    }
    if message:
        raw.update(
            fromUser={"id": author_id, "username": f"u{author_id}"},
            createdAt="2026-09-06T00:00:00+00:00",
        )
    else:
        raw.update(
            author={"id": author_id, "username": f"u{author_id}"},
            postedAt="2026-09-06T00:00:00+00:00",
            postedAtPrecise="0",
        )
    return raw


@pytest.fixture
def paid_auth(subscription_auth):
    auth = subscription_auth
    auth.paid_content = []
    auth.total = 205
    auth.cache.paid_content = SimpleNamespace(
        is_released=lambda: True, activate=lambda: None
    )
    auth.iter_paid_content = OnlyFansAuthModel.iter_paid_content.__get__(auth)
    auth.get_paid_content = OnlyFansAuthModel.get_paid_content.__get__(auth)
    original = auth.auth_session.json_request
    auth.make_item = paid_item
    auth.pages = 0

    async def json_request(url, **kwargs):
        if "/posts/paid/all?" in url:
            query = parse_qs(urlparse(url).query)
            offset, size = int(query["offset"][0]), int(query["limit"][0])
            auth.pages += 1
            return {
                "list": [
                    auth.make_item(i)
                    for i in range(offset, min(offset + size, auth.total))
                ],
                "hasMore": offset + size < auth.total,
            }
        return await original(url, **kwargs)

    auth.auth_session.json_request = json_request
    return auth


@pytest.mark.asyncio
async def test_paid_stream_releases_feed_authors_and_preserves_existing_cache(
    paid_auth,
):
    auth = paid_auth
    auth.total = 2500
    sentinel = object()
    auth.paid_content.append(sentinel)
    refs = weakref.WeakSet()
    count = 0
    async with aclosing(auth.iter_paid_content()) as items:
        async for item in items:
            assert item.id == count
            refs.add(item.get_author())
            count += 1
            if count % 100 == 0:
                gc.collect()
                assert len(refs) <= 51
                assert auth.pages == count // 50
    del item
    gc.collect()
    assert not refs
    assert not auth.users and not auth.cache_activations
    assert auth.paid_content == [sentinel]
    assert count == auth.total


@pytest.mark.asyncio
async def test_paid_messages_reuse_hydration_only_within_current_page(paid_auth):
    paid_auth.total = 101
    paid_auth.make_item = lambda i: paid_item(i, author_id=7, message=True)
    async with aclosing(paid_auth.iter_paid_content()) as items:
        values = [item async for item in items]
    assert len(values) == 101
    assert paid_auth.hydrated == [7, 7, 7]
    assert all(item.get_author().about == "fresh" for item in values)
    assert not paid_auth.users and not paid_auth.paid_content


@pytest.mark.asyncio
async def test_paid_message_hydrates_after_a_post_from_the_same_author(paid_auth):
    paid_auth.total = 2
    paid_auth.make_item = lambda i: paid_item(i, author_id=7, message=bool(i))
    values = [item async for item in paid_auth.iter_paid_content()]
    assert values[-1].get_author().about == "fresh"
    assert paid_auth.hydrated == [7]


@pytest.mark.asyncio
async def test_paid_compatibility_collector_retains_requested_results(paid_auth):
    values = await paid_auth.get_paid_content(limit=3, offset=2)
    assert [item.id for item in values] == [2, 3, 4]
    assert values is paid_auth.paid_content
    assert len(paid_auth.users) == 3


@pytest.mark.asyncio
async def test_paid_upstream_failure_is_not_successful_end_of_feed(paid_auth):
    paid_auth.auth_session.json_request = AsyncMock(
        return_value={"error": {"message": "fixture failure"}}
    )
    with pytest.raises(RuntimeError, match="page request failed"):
        await anext(paid_auth.iter_paid_content())


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
async def test_paid_limit_is_explicit_and_validated_before_requests(paid_auth, limit):
    if limit == 0:
        assert [item async for item in paid_auth.iter_paid_content(limit=limit)] == []
    else:
        with pytest.raises(ValueError, match="limit"):
            await anext(paid_auth.iter_paid_content(limit=limit))
    assert paid_auth.pages == 0


@pytest.mark.asyncio
async def test_paid_producer_commits_bounded_groups_and_returns_only_sql_reference(
    paid_auth, monkeypatch
):
    monkeypatch.setenv("ULTIMA_CONTENT_BATCH_SIZE", "7")
    monkeypatch.setenv("ULTIMA_TASK_RESULT_PREVIEW_MAX_ENTRIES", "2")
    monkeypatch.setenv("ULTIMA_TASK_RESULT_PREVIEW_MAX_BYTES", "1024")
    committed = error_count = 0
    sealed = False
    plan = dict(
        selection_id="selected",
        job_id="job",
        task_id="task",
        site="onlyfans",
        auth_id=99,
    )

    async def submit(operation, payload, **kwargs):
        nonlocal committed, error_count, sealed
        if payload.get("action") == "seal":
            sealed = True
            assert committed == paid_auth.total
            return {"selection_id": "selected", "total": 0}
        rows = payload["items"]
        assert len(rows) <= 7
        # A batch may cross an upstream page; no subsequent batch is prefetched.
        assert (
            paid_auth.pages <= (min(committed // 7 * 7 + 7, paid_auth.total) + 49) // 50
        )
        assert payload["media_selection"] == plan
        assert payload["record_bought_content"]
        assert payload["error_offset"] == error_count
        committed += len(rows)
        failures = [f"fixture error {committed}"] if committed % 7 == 0 else []
        error_count += len(failures)
        await asyncio.sleep(0)
        return {"items_saved": len(rows), "errors": failures}

    result = await content.scrape_paid_content_feed(
        paid_auth,
        max_items=None,
        performer_filter=None,
        paid_content_types=None,
        auth_user_id=99,
        worker_id="fixture",
        job_id="job",
        database_writes=SimpleNamespace(submit=submit),
        site="onlyfans",
        media_selection=plan,
    )
    assert result[:3] == (205, 205, 205)
    assert len(result[3]) == 2
    assert result[4:] == ([], [])
    assert plan["error_count"] == 29
    assert sealed and not paid_auth.users and not paid_auth.paid_content


@pytest.mark.asyncio
async def test_paid_write_failure_closes_upstream_before_more_pages(
    paid_auth, monkeypatch
):
    monkeypatch.setenv("ULTIMA_CONTENT_BATCH_SIZE", "7")
    closed = []
    original = paid_auth.iter_paid_content

    async def source(**kwargs):
        try:
            async with aclosing(original(**kwargs)) as items:
                async for item in items:
                    yield item
        finally:
            closed.append(True)

    paid_auth.iter_paid_content = source
    with pytest.raises(DatabaseWriteError):
        await content.scrape_paid_content_feed(
            paid_auth,
            max_items=None,
            performer_filter=None,
            paid_content_types=None,
            auth_user_id=99,
            worker_id="fixture",
            job_id="job",
            site="onlyfans",
            media_selection=dict(selection_id="selection", site="onlyfans"),
            database_writes=SimpleNamespace(
                submit=AsyncMock(side_effect=DatabaseWriteError("stalled writer"))
            ),
        )
    assert paid_auth.pages == 1
    assert closed == [True]


@pytest.mark.asyncio
async def test_paid_scrape_creates_one_download_task_for_any_number_of_authors(
    monkeypatch,
):
    from test_scrape_handler import _onlyfans_posts_context
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    from ultima_scraper_backend.job_system.models import Task, TaskType
    from ultima_scraper_backend.job_system.payloads import (
        ScrapeTaskPayload,
        DownloadTaskPayload,
    )

    auth = SimpleNamespace(
        id=9001, username="buyer", iter_paid_content=lambda: None
    )
    task = Task(
        site_name="onlyfans",
        user_id=auth.id,
        auth_id=auth.id,
        content_type=None,
        task_type=TaskType.SCRAPE,
        payload=ScrapeTaskPayload(paid_content_feed=True, download_media=True),
    )
    context = _onlyfans_posts_context(auth, task)

    async def scrape(*args, **kwargs):
        kwargs["media_selection"]["error_count"] = 0
        return 1_000_000, 1_000_000, 1_000_000, [], [], []

    monkeypatch.setattr(handler, "scrape_paid_content_feed", scrape)
    monkeypatch.setattr(handler, "publish_hook_event", AsyncMock())
    result = await handler.scrape_task_handler(task, context)
    assert result.success
    assert len(result.new_tasks) == 1
    child = result.new_tasks[0]
    assert child.user_id == auth.id and child.auth_id == auth.id
    assert child.depends_on == [task.task_id]
    assert (
        isinstance(child.payload, DownloadTaskPayload)
        and child.payload.paid_content_feed
    )
    assert DownloadTaskPayload.model_validate(
        child.payload.model_dump()
    ).paid_content_feed
    assert "media_selection" in result.output
    assert "media_urls" not in result.output


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dependencies,output",
    [([], {}), (["one", "two"], {}), (["one"], {"media_urls": []})],
)
async def test_paid_download_requires_exact_durable_dependency(dependencies, output):
    writer = AsyncMock()
    context = SimpleNamespace(
        database_writes=SimpleNamespace(submit=writer),
        job=SimpleNamespace(job_id="job"),
        storage=SimpleNamespace(get_task_output=AsyncMock(return_value=output)),
    )
    with pytest.raises(ValueError):
        await streaming.prepare_paid_feed_selection(
            SimpleNamespace(depends_on=dependencies), context, {}
        )
    writer.assert_not_called()


@pytest.mark.asyncio
async def test_paid_downloader_pages_authors_reuses_pool_and_persists_complete_evidence(
    monkeypatch, tmp_path
):
    from test_download_pipeline import _build_config
    from ultima_scraper_backend.job_system.handlers.download import handler

    total_authors, files_each = 201, 5
    targets_seen = completed = opened = closed = 0
    written_evidence = {"files": 0, "download_results": 0}
    selected_aliases = []
    plan = {"selection_id": "source", "total": total_authors * files_each}

    class Store:
        def __init__(self, session):
            pass

        def feed_download_totals(self, selection_id):
            return {
                "count": total_authors * files_each,
                "bytes": total_authors * files_each * 10,
                "drm": 0,
            }

        def download_target_page(self, selection_id, *, after, limit):
            nonlocal targets_seen
            assert limit == 3  # Independent from file metadata batch budget.
            start = 1 if after is None else after[0] + 1
            assert completed == start - 1
            page = [
                (i, "posts" if i % 2 else "messages")
                for i in range(start, min(start + limit, total_authors + 1))
            ]
            targets_seen += len(page)
            return page

        def download_totals(self, selection_id, **kwargs):
            return {"count": files_each, "bytes": files_each * 10, "drm": 0}

        def download_page(
            self, selection_id, *, user_id, content_type, after, limit, **kwargs
        ):
            nonlocal completed
            assert user_id == completed + 1
            assert content_type == ("posts" if user_id % 2 else "messages")
            assert limit == 2
            if after == files_each:
                completed += 1
                return []
            return [
                SimpleNamespace(medias=[SimpleNamespace(media_id=i)])
                for i in range(after + 1, min(after + limit, files_each) + 1)
            ]

    class Manager:
        def __init__(self, **kwargs):
            pass

        @asynccontextmanager
        async def session_scope(self):
            nonlocal opened, closed
            opened += 1
            try:
                yield self
            finally:
                closed += 1

    async def batch(**kwargs):
        user = kwargs["user"]
        assert user.id == completed + 1
        assert kwargs["aggregate"]["items_processed"] == written_evidence["files"]
        values = [
            {"user_id": user.id, "media_id": item.medias[0].media_id}
            for item in kwargs["content_metadatas"]
        ]
        return TaskResult(
            success=True,
            output={"files": values, "download_results": values},
            metrics={
                "items_processed": len(values),
                "successful": len(values),
                "valid_items": len(values),
                "progress_units": len(values),
            },
        )

    async def write(operation, payload, **kwargs):
        if payload["action"] == "adopt":
            assert (
                payload["source_id"] == "source"
                and payload["source_task_id"] == "scrape"
            )
            return plan
        assert payload["action"] == "evidence"
        for category in payload["categories"]:
            assert category["offset"] == written_evidence[category["kind"]]
            assert len(category["values"]) <= 2
            written_evidence[category["kind"]] += len(category["values"])
        return {}

    async def persist_task(*, task, **kwargs):
        output = task.result.output
        assert len(output["files"]) <= 2 and len(output["download_results"]) <= 2

    def destination(**kwargs):
        assert kwargs["required_space"] == files_each * 10
        selected_aliases.append(kwargs["usernames"])
        return SimpleNamespace(root=tmp_path, directory_format=tmp_path)

    monkeypatch.setenv("ULTIMA_DOWNLOAD_BATCH_SIZE", "2")
    monkeypatch.setenv("ULTIMA_DOWNLOAD_TARGET_BATCH_SIZE", "3")
    monkeypatch.setenv("ULTIMA_TASK_RESULT_PREVIEW_MAX_ENTRIES", "2")
    monkeypatch.setenv("ULTIMA_TASK_RESULT_PREVIEW_MAX_BYTES", "4096")
    monkeypatch.setattr(streaming, "MediaSelectionStore", Store)
    monkeypatch.setattr(streaming, "DownloadManager", Manager)
    monkeypatch.setattr(streaming, "select_user_destination", destination)
    monkeypatch.setattr(handler, "_resolve_proxy_url", lambda *args: None)
    monkeypatch.setattr(handler, "_download_content_batch", batch)
    task = SimpleNamespace(
        task_id="download",
        site_name="onlyfans",
        depends_on=["scrape"],
        payload=SimpleNamespace(
            paid_content_feed=True, ignore_space_requirements=False
        ),
    )
    context = SimpleNamespace(
        job=SimpleNamespace(job_id="job"),
        user_manager=None,
        database_writes=SimpleNamespace(submit=write),
        storage=SimpleNamespace(
            persist_task=persist_task,
            get_task_output=AsyncMock(return_value={"media_selection": plan}),
        ),
    )
    db_manager = SimpleNamespace(
        get_session=None,
        get_user=lambda identifier: SimpleNamespace(
            id=identifier,
            username=f"u{identifier}",
            aliases=[SimpleNamespace(username=f"old_{identifier}")],
        ),
    )
    result = await streaming.download_selected_media(
        task=task,
        context=context,
        user=None,
        db_user=None,
        db_manager=db_manager,
        authed=SimpleNamespace(id=99),
        config=_build_config(),
        content_type="paid_content",
        resolved_auth_id=99,
    )
    assert (
        result.success
        and result.metrics["items_processed"] == total_authors * files_each
    )
    assert result.output["files_total"] == total_authors * files_each
    assert written_evidence == {"files": 1005, "download_results": 1005}
    assert targets_seen == completed == total_authors
    assert opened == closed == 1
    assert selected_aliases[0] == ["u1", "old_1", "1"]
    assert selected_aliases[-1] == ["u201", "old_201", "201"]
