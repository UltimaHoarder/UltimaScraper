from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ultima_scraper_backend.job_system.handlers.download import streaming
from ultima_scraper_backend.job_system.models import TaskResult
from ultima_scraper_backend.database.write_queue import DatabaseWriteError


@pytest.mark.asyncio
async def test_explicit_empty_scrape_selection_never_falls_back_to_whole_archive():
    calls = []

    async def submit(operation, payload, **kwargs):
        calls.append(payload["action"])
        assert payload["action"] == "adopt"
        return {"selection_id": "source", "total": 0}

    task = SimpleNamespace(
        depends_on=["scrape"],
        user_id=7,
        payload=SimpleNamespace(max_items=None, media_ids=None),
    )
    context = SimpleNamespace(
        database_writes=SimpleNamespace(submit=submit),
        job=SimpleNamespace(job_id="job"),
        storage=SimpleNamespace(
            get_task_output=AsyncMock(
                return_value={"media_selection": {"selection_id": "source"}}
            )
        ),
    )
    await streaming.prepare_download_selection(
        task,
        context,
        {"selection_id": "target", "site": "onlyfans"},
        content_type="posts",
        batch_size=3,
        max_bytes=4096,
    )
    assert calls == ["adopt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_evidence", [False, True])
@pytest.mark.parametrize("guest", [False, True])
async def test_download_batches_reuse_pool_and_keep_only_bounded_report_previews(
    monkeypatch,
    tmp_path,
    fail_evidence,
    guest,
):
    from test_download_pipeline import _build_config
    from ultima_scraper_backend.job_system.handlers.download import handler

    total = 1003
    pages = []
    evidence = {"files": 0, "download_results": 0}
    max_output = 0
    opened = closed = 0

    class Store:
        def __init__(self, session):
            pass

        def download_totals(self, selection_id, **kwargs):
            assert kwargs["auth_id"] == (None if guest else 99)
            return {"count": total, "bytes": total * 256, "drm": 0}

        def download_page(self, selection_id, *, after, limit, **kwargs):
            assert kwargs["auth_id"] == (None if guest else 99)
            pages.append((after, limit))
            assert limit == 7
            return [
                SimpleNamespace(medias=[SimpleNamespace(media_id=i)])
                for i in range(after + 1, min(after + limit, total) + 1)
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
        ids = [content.medias[0].media_id for content in kwargs["content_metadatas"]]
        failed = sum(identifier % 10 == 0 for identifier in ids)
        return TaskResult(
            success=True,
            output={
                "files": [{"path": f"/fixture/{i}", "bytes": 256} for i in ids],
                "download_results": [
                    {"media_id": i, "status": "failed" if i % 10 == 0 else "downloaded"}
                    for i in ids
                ],
                "failure_breakdown": {"network_error": failed},
            },
            metrics={
                "items_processed": len(ids),
                "valid_items": len(ids),
                "bytes_written": len(ids) * 256,
                "successful": len(ids) - failed,
                "downloads_completed": len(ids) - failed,
                "failed": failed,
                "progress_units": len(ids),
            },
        )

    async def submit(operation, payload, **kwargs):
        assert payload["action"] == "evidence"
        for category in payload["categories"]:
            assert len(category["values"]) <= 7
            assert category["offset"] == evidence[category["kind"]]
            if fail_evidence and category["offset"] >= 7:
                raise DatabaseWriteError("fixture unavailable")
            evidence[category["kind"]] += len(category["values"])
        return {"stored": True}

    async def persist_task(*, task, **kwargs):
        nonlocal max_output
        output = task.result.output
        count = len(output.get("files", [])) + len(output.get("download_results", []))
        max_output = max(count, max_output)
        assert count <= 4

    monkeypatch.setenv("ULTIMA_DOWNLOAD_BATCH_SIZE", "7")
    monkeypatch.setenv("ULTIMA_TASK_RESULT_PREVIEW_MAX_ENTRIES", "2")
    monkeypatch.setenv("ULTIMA_TASK_RESULT_PREVIEW_MAX_BYTES", "4096")
    monkeypatch.setattr(streaming, "MediaSelectionStore", Store)
    monkeypatch.setattr(streaming, "DownloadManager", Manager)
    monkeypatch.setattr(
        streaming,
        "prepare_download_selection",
        AsyncMock(return_value={"selection_id": "source"}),
    )
    monkeypatch.setattr(handler, "_resolve_proxy_url", lambda *args: None)
    monkeypatch.setattr(handler, "_download_content_batch", batch)
    monkeypatch.setattr(
        streaming,
        "select_user_destination",
        lambda **kwargs: SimpleNamespace(root=tmp_path, directory_format=tmp_path),
    )
    task = SimpleNamespace(
        task_id="task",
        site_name="onlyfans",
        payload=SimpleNamespace(ignore_space_requirements=False),
    )
    context = SimpleNamespace(
        job=SimpleNamespace(job_id="job"),
        user_manager=None,
        database_writes=SimpleNamespace(submit=submit),
        storage=SimpleNamespace(persist_task=persist_task),
    )
    user = SimpleNamespace(id=7, get_usernames=lambda: ["seven"])
    kwargs = dict(
        task=task,
        context=context,
        user=user,
        db_user=user,
        db_manager=SimpleNamespace(get_session=None),
        authed=SimpleNamespace(guest=guest),
        config=_build_config(),
        content_type="posts",
        resolved_auth_id=0 if guest else 99,
    )
    if fail_evidence:
        with pytest.raises(DatabaseWriteError, match="fixture unavailable"):
            await streaming.download_selected_media(**kwargs)
        assert len(pages) == 2
    else:
        result = await streaming.download_selected_media(**kwargs)
        assert result.metrics["items_processed"] == total
        assert result.metrics["successful"] == 903
        assert result.metrics["failed"] == 100
        assert result.output["download_results_total"] == total
        assert result.output["failure_breakdown"] == {"network_error": 100}
        assert len(result.output["download_results"]) == 2
        assert evidence == {"files": total, "download_results": total}
    assert opened == closed == 1
    assert streaming.prepare_download_selection.call_args.args[2]["auth_id"] == (
        None if guest else 99
    )
    assert max_output == 4


@pytest.mark.asyncio
async def test_real_batch_pipeline_finalizes_files_and_records_unusable_media(
    monkeypatch, tmp_path
):
    from datetime import datetime, timezone
    from test_download_pipeline import _build_api_user, _build_config
    from ultima_scraper_backend.job_system.handlers.download import handler
    from ultima_scraper_backend.job_system.metadata_models import (
        ContentMetadata,
        MediaMetadata,
    )
    from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation

    config = _build_config()
    user = _build_api_user(config)
    content = ContentMetadata(
        content_id=1,
        api_type="posts",
        user_id=user.id,
        created_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
    )
    for identifier, urls in [(1, ["https://fixture/one.jpg"]), (2, [])]:
        content.medias.append(
            MediaMetadata(
                media_id=identifier,
                media_type="images",
                urls=urls,
                content_id=1,
                user_id=user.id,
                created_at=content.created_at,
                size=3,
                content_metadata=content,
            )
        )

    class Manager:
        on_progress = []
        on_status = []
        on_downloaded = []
        resource_manager = SimpleNamespace(get_file_concurrency=lambda: 2)

        def release_workspace(self, item):
            pass

        async def bulk_download(self, items, **kwargs):
            for item in items:
                file = item.get_filepath()
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b"abc")
                item.downloaded_this_run = True
            return {"completed": len(items), "total": len(items), "success_rate": 100}

    submit = AsyncMock(return_value={"marked_downloaded": 1, "filepaths": 1})
    context = SimpleNamespace(
        job=SimpleNamespace(job_id="job"),
        worker_id="worker",
        database_writes=SimpleNamespace(submit=submit),
        storage=SimpleNamespace(persist_task=AsyncMock()),
    )
    task = SimpleNamespace(task_id="task", site_name="onlyfans")
    selection = SimpleNamespace(
        root=tmp_path,
        absolute_path=tmp_path,
        requires_full_directory_render=False,
        directory_format=tmp_path,
    )
    result = await handler._download_content_batch(
        task=task,
        context=context,
        user=user,
        db_user=SimpleNamespace(username="creator"),
        authed=user.get_authed(),
        config=config,
        content_metadatas=[content],
        content_type="posts",
        destination_selection=selection,
        download_manager=Manager(),
        aggregate={"total_items": 2, "expected_bytes": 6, "progress_total": 2},
        evidence_spec={"selection_id": "selection"},
    )
    assert result.metrics["items_processed"] == result.metrics["total_items"] == 2
    assert result.metrics["successful"] == 1
    assert result.output["failure_breakdown"] == {"no_url": 1}
    assert len(result.output["download_results"]) == 2
    assert submit.call_args.args[0] == DatabaseWriteOperation.FINALIZE_DOWNLOAD
    assert submit.call_args.args[1]["media_ids"] == [1]


async def test_progress_never_expects_fewer_bytes_than_the_task_has_written(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from test_download_pipeline import _build_api_user, _build_config
    from ultima_scraper_backend.job_system.handlers.download import handler
    from ultima_scraper_backend.job_system.metadata_models import ContentMetadata, MediaMetadata

    config = _build_config()
    user = _build_api_user(config)
    content = ContentMetadata(
        content_id=1, api_type="posts", user_id=user.id, created_at=datetime(2026, 9, 5, tzinfo=timezone.utc)
    )
    # The archive knew no size for this video, so the estimate counts it as 0.
    content.medias.append(
        MediaMetadata(
            media_id=1, media_type="videos", urls=["https://fixture/one.mp4"], content_id=1,
            user_id=user.id, created_at=content.created_at, size=None, content_metadata=content,
        )
    )
    published = []
    monkeypatch.setattr(handler, "publish_download_progress", AsyncMock(side_effect=published.append))

    class Manager:
        on_progress = []
        on_status = []
        on_downloaded = []
        resource_manager = SimpleNamespace(get_file_concurrency=lambda: 1)

        def release_workspace(self, item):
            pass

        async def bulk_download(self, items, **kwargs):
            item = items[0]
            event = {"status": "progress", "item": item, "bytes": 5_000, "processed_bytes": 5_000,
                     "expected_bytes": 8_000, "item_processed_bytes": 5_000, "item_expected_bytes": 8_000,
                     "completed": 0, "failed": 0, "total": 1,
                     "active_transfers": [{"media_id": 7, "path": "/dest/7.mp4", "processed_bytes": 5_000, "expected_bytes": 8_000}]}
            for callback in self.on_progress:
                await callback(event)
            file = item.get_filepath()
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"x")
            item.downloaded_this_run = True
            return {"completed": 1, "total": 1, "success_rate": 100}

    storage = SimpleNamespace(persist_task=AsyncMock())
    context = SimpleNamespace(
        job=SimpleNamespace(job_id="job"),
        worker_id="worker",
        database_writes=SimpleNamespace(submit=AsyncMock(return_value={})),
        storage=storage,
    )
    task = SimpleNamespace(task_id="task", site_name="onlyfans")
    selection = SimpleNamespace(
        root=tmp_path, absolute_path=tmp_path, requires_full_directory_render=False, directory_format=tmp_path
    )

    await handler._download_content_batch(
        task=task, context=context, user=user, db_user=SimpleNamespace(username="creator"),
        authed=user.get_authed(), config=config, content_metadatas=[content], content_type="posts",
        destination_selection=selection, download_manager=Manager(),
        # Earlier pages wrote 10 kB against an estimate of 3 kB.
        aggregate={"total_items": 100, "expected_bytes": 3_000, "progress_total": 100, "bytes_written": 10_000,
                   "progress_units": 40, "successful": 37, "skipped": 3},
        evidence_spec={"selection_id": "selection"},
    )

    [event] = published
    assert event["active_transfers"] == [
        {"media_id": 7, "path": "/dest/7.mp4", "processed_bytes": 5_000, "expected_bytes": 8_000}
    ]
    results = [call.kwargs["task"].result for call in storage.persist_task.call_args_list]
    # The whole task's position, not this batch's.
    assert results[-1].message == "Download in progress: 40/100"
    assert results[-1].metrics["skipped"] == 3
    assert event["processed_bytes"] == 15_000
    assert event["expected_bytes"] == 18_000  # written so far plus this file's real size
    # The file named by media_id: only its own bytes.
    assert (event["media_processed_bytes"], event["media_expected_bytes"]) == (5_000, 8_000)
    persisted = [call.kwargs["task"].result.metrics for call in storage.persist_task.call_args_list]
    assert any(metrics["total_bytes"] == 18_000 for metrics in persisted)
    assert all(metrics["total_bytes"] >= metrics["bytes_written"] for metrics in persisted)


@pytest.mark.asyncio
async def test_a_download_shows_its_proxy_before_the_selection_is_prepared(monkeypatch):
    from test_download_pipeline import _build_config
    from ultima_scraper_backend.job_system.handlers.download import handler

    proxy = "http://192.0.2.10:8022"
    persisted = []

    async def persist_task(*, task, **kwargs):
        persisted.append(task.result)

    async def prepare(*args, **kwargs):
        # Preparing can take minutes; the running panel reads the route meanwhile.
        assert [result.metrics["proxy_url"] for result in persisted] == [proxy]
        raise RuntimeError("stop after preparing")

    monkeypatch.setattr(handler, "_resolve_proxy_url", lambda *args: proxy)
    monkeypatch.setattr(streaming, "prepare_download_selection", prepare)
    task = SimpleNamespace(
        task_id="task",
        site_name="onlyfans",
        payload=SimpleNamespace(ignore_space_requirements=False),
    )
    context = SimpleNamespace(
        job=SimpleNamespace(job_id="job"),
        storage=SimpleNamespace(persist_task=persist_task),
    )
    user = SimpleNamespace(id=7, get_usernames=lambda: ["seven"])

    with pytest.raises(RuntimeError, match="stop after preparing"):
        await streaming.download_selected_media(
            task=task,
            context=context,
            user=user,
            db_user=user,
            db_manager=SimpleNamespace(get_session=None),
            authed=SimpleNamespace(guest=False),
            config=_build_config(),
            content_type="posts",
            resolved_auth_id=99,
        )

    [started] = persisted
    assert started.metrics["proxy_routes"] == [proxy]
    assert started.metrics["proxy_hop_used"] == 0


@pytest.mark.asyncio
async def test_download_progress_keeps_the_proxy_route(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from test_download_pipeline import _build_api_user, _build_config
    from ultima_scraper_backend.job_system.handlers.download import handler
    from ultima_scraper_backend.job_system.metadata_models import ContentMetadata, MediaMetadata

    proxy = "http://192.0.2.10:8022"
    config = _build_config()
    user = _build_api_user(config)
    content = ContentMetadata(
        content_id=1, api_type="posts", user_id=user.id, created_at=datetime(2026, 9, 5, tzinfo=timezone.utc)
    )
    content.medias.append(
        MediaMetadata(
            media_id=1, media_type="videos", urls=["https://fixture/one.mp4"], content_id=1,
            user_id=user.id, created_at=content.created_at, size=8_000, content_metadata=content,
        )
    )
    monkeypatch.setattr(handler, "publish_download_progress", AsyncMock())

    class Manager:
        on_progress = []
        on_status = []
        on_downloaded = []
        resource_manager = SimpleNamespace(get_file_concurrency=lambda: 1)

        def release_workspace(self, item):
            pass

        async def bulk_download(self, items, **kwargs):
            item = items[0]
            event = {"status": "progress", "item": item, "bytes": 5_000, "processed_bytes": 5_000,
                     "expected_bytes": 8_000, "item_processed_bytes": 5_000, "item_expected_bytes": 8_000,
                     "completed": 0, "failed": 0, "total": 1}
            for callback in self.on_progress:
                await callback(event)
            file = item.get_filepath()
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"x")
            item.downloaded_this_run = True
            return {"completed": 1, "total": 1, "success_rate": 100}

    storage = SimpleNamespace(persist_task=AsyncMock())
    context = SimpleNamespace(
        job=SimpleNamespace(job_id="job"),
        worker_id="worker",
        database_writes=SimpleNamespace(submit=AsyncMock(return_value={})),
        storage=storage,
    )
    selection = SimpleNamespace(
        root=tmp_path, absolute_path=tmp_path, requires_full_directory_render=False, directory_format=tmp_path
    )

    await handler._download_content_batch(
        task=SimpleNamespace(task_id="task", site_name="onlyfans"), context=context, user=user,
        db_user=SimpleNamespace(username="creator"), authed=user.get_authed(), config=config,
        content_metadatas=[content], content_type="posts", destination_selection=selection,
        download_manager=Manager(), aggregate={"total_items": 1, "expected_bytes": 8_000, "progress_total": 1},
        evidence_spec={"selection_id": "selection"}, proxy_url=proxy,
    )

    persisted = [call.kwargs["task"].result.metrics for call in storage.persist_task.call_args_list]
    assert persisted
    assert all(
        (metrics["proxy_url"], metrics["proxy_routes"], metrics["proxy_hop_used"]) == (proxy, [proxy], 0)
        for metrics in persisted
    )
