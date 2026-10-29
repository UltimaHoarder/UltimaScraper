"""Profile database writes remain usable during a filesystem restoration."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from ultima_scraper_api import ContentType
from ultima_scraper_backend.job_system.models import (
    Job,
    Task,
    TaskCancelled,
    TaskRegistry,
    TaskResult,
    TaskType,
)
from ultima_scraper_backend.job_system.payloads import ScrapeTaskPayload
from ultima_scraper_backend.services import archive_write_guard as guard


@pytest.fixture
def archive_reservation(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "LOCK_ROOT", tmp_path / "locks")
    root = tmp_path / "archive"
    root.mkdir()
    config = SimpleNamespace(
        settings=SimpleNamespace(
            download_setup=SimpleNamespace(
                drives=[SimpleNamespace(directories=[str(root)])]
            )
        )
    )
    with guard.acquire([str(root)], exclusive=True):
        yield config


@pytest.mark.asyncio
@pytest.mark.parametrize("serialized", [False, True])
async def test_profile_database_write_finishes_during_restore(
    archive_reservation, monkeypatch, serialized
):
    writes = AsyncMock()

    async def profile_handler(task, context):
        await writes.submit("upsert_user", {"user_id": task.user_id})
        return TaskResult(success=True)

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, profile_handler)
    task = Task(
        user_id=1,
        task_type=TaskType.SCRAPE,
        content_type=ContentType.PROFILE,
        site_name="OnlyFans",
        payload=ScrapeTaskPayload(max_items=1, use_guest_auth=True),
    )
    if serialized:
        task = Task.from_dict(json.loads(json.dumps(task.to_dict())))
    job = Job(name="Profiles during restore", created_by="tests", tasks=[task])
    result = await asyncio.wait_for(
        task.run(
            job=job,
            storage=SimpleNamespace(persist_task=AsyncMock()),
            context={"config": archive_reservation},
        ),
        timeout=0.5,
    )
    assert result.success
    writes.submit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task_type,content_type,paid_feed",
    [
        (TaskType.SCRAPE, ContentType.POSTS, False),
        (TaskType.DOWNLOAD, ContentType.PROFILE, False),
        (TaskType.SCRAPE, ContentType.PROFILE, True),
    ],
)
async def test_archive_handlers_still_wait_and_cancel_cleanly(
    archive_reservation, monkeypatch, task_type, content_type, paid_feed
):
    handler = AsyncMock(return_value=TaskResult(success=True))
    monkeypatch.setitem(TaskRegistry._handlers, task_type, handler)
    task = Task(
        user_id=1,
        task_type=task_type,
        content_type=content_type,
        payload=ScrapeTaskPayload(max_items=1, paid_content_feed=paid_feed),
    )
    execution = asyncio.create_task(
        task.run(
            job=Job(name="Archive writer", created_by="tests", tasks=[task]),
            storage=SimpleNamespace(persist_task=AsyncMock()),
            context={"config": archive_reservation},
        )
    )
    try:
        await asyncio.sleep(0.02)
        handler.assert_not_awaited()
        execution.cancel()
        with pytest.raises(TaskCancelled):
            await execution
    finally:
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)


@pytest.mark.asyncio
async def test_profile_parent_does_not_bypass_download_subtask_reservation(
    archive_reservation, monkeypatch
):
    handler = AsyncMock(return_value=TaskResult(success=True))
    for task_type in (TaskType.SCRAPE, TaskType.DOWNLOAD):
        monkeypatch.setitem(TaskRegistry._handlers, task_type, handler)
    child = Task(user_id=1, task_type=TaskType.DOWNLOAD, content_type=ContentType.PROFILE)
    parent = Task(
        user_id=1,
        task_type=TaskType.SCRAPE,
        content_type=ContentType.PROFILE,
        subtasks=[child],
    )
    execution = asyncio.create_task(
        parent.run(
            job=Job(name="Profile with download", created_by="tests", tasks=[parent]),
            storage=SimpleNamespace(persist_task=AsyncMock()),
            context={"config": archive_reservation},
        )
    )
    try:
        await asyncio.sleep(0.02)
        handler.assert_not_awaited()
    finally:
        execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
