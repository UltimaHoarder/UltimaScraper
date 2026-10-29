import asyncio
import gc
import logging

import pytest

from ultima_scraper_backend.helpers import background_tasks
from ultima_scraper_backend.helpers.background_tasks import spawn_background_task


async def test_background_task_survives_garbage_collection_and_is_released() -> None:
    finished = asyncio.Event()

    async def work() -> str:
        await asyncio.sleep(0)
        gc.collect()
        finished.set()
        return "done"

    task = spawn_background_task(work(), name="gc-probe")
    task_id = id(task)
    del task
    gc.collect()

    await asyncio.wait_for(finished.wait(), timeout=1)
    await asyncio.sleep(0)

    assert all(id(t) != task_id for t in background_tasks._background_tasks)


async def test_background_task_failure_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fail() -> None:
        raise RuntimeError("boom")

    caplog.set_level(logging.ERROR, logger=background_tasks.__name__)
    task = spawn_background_task(fail(), name="failing-probe")
    with pytest.raises(RuntimeError):
        await task
    await asyncio.sleep(0)

    assert "Background task failing-probe failed" in caplog.text
    assert task not in background_tasks._background_tasks


async def test_cancelled_background_task_is_released_quietly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger=background_tasks.__name__)
    task = spawn_background_task(asyncio.sleep(60), name="cancel-probe")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)

    assert task not in background_tasks._background_tasks
    assert caplog.text == ""
