"""The worker loop uses uvloop and retains cancellation and shutdown."""

import asyncio

import pytest
import uvloop
from ultima_scraper_backend.workers.worker_pool import _worker_loop_factory


def test_worker_loop_uses_uvloop():
    assert _worker_loop_factory() == uvloop.new_event_loop


def test_worker_loop_cancels_pending_tasks_and_closes():
    observed = []
    cleaned = []

    async def pending():
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.append(True)

    async def main():
        loop = asyncio.get_running_loop()
        observed.append(loop)
        task = asyncio.create_task(pending())
        await asyncio.sleep(0)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), timeout=0.001)
        assert not task.done()
        return loop.__class__.__module__

    module = asyncio.run(main(), loop_factory=_worker_loop_factory())
    assert module.startswith("uvloop")
    assert cleaned == [True]
    assert observed[0].is_closed()

