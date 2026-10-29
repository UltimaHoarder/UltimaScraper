"""Pipeline admission and cancellation contracts for bounded iteration."""

from __future__ import annotations

import asyncio
from contextlib import aclosing

import pytest

from ultima_scraper_core.concurrency import map_unordered


@pytest.mark.asyncio
async def test_large_input_admission_and_tasks_are_bounded() -> None:
    gate = asyncio.Event()
    saturated = asyncio.Event()
    started: list[int] = []
    cancelled: list[int] = []

    async def work(item: int) -> int:
        started.append(item)
        if len(started) == 3:
            saturated.set()
        try:
            await gate.wait()
            return item
        finally:
            cancelled.append(item)

    async def consume() -> None:
        async with aclosing(map_unordered(work, range(1_000_000), limit=3)) as results:
            async for _ in results:
                pass

    consumer = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(saturated.wait(), timeout=1)
        assert started == [0, 1, 2]
    finally:
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
    assert sorted(cancelled) == [0, 1, 2]


@pytest.mark.asyncio
async def test_slow_input_does_not_hold_completed_output() -> None:
    source_closed = asyncio.Event()
    never = asyncio.Event()

    async def inputs():
        try:
            yield 42
            await never.wait()
        finally:
            source_closed.set()

    async def work(item: int) -> int:
        return item

    async with aclosing(map_unordered(work, inputs(), limit=2)) as results:
        assert await asyncio.wait_for(anext(results), timeout=1) == 42
    assert source_closed.is_set()


@pytest.mark.asyncio
async def test_consumer_backpressure_and_exact_completion() -> None:
    started: list[int] = []

    async def work(item: int) -> int:
        started.append(item)
        return item * 2

    async with aclosing(map_unordered(work, range(100), limit=4)) as results:
        first = await anext(results)
        assert len(started) <= 4
        output = [first] + [value async for value in results]
    assert sorted(output) == list(range(0, 200, 2))
    assert sorted(started) == list(range(100))


@pytest.mark.asyncio
async def test_early_close_releases_synchronous_generator_resources() -> None:
    closed = False

    def inputs():
        nonlocal closed
        try:
            yield from range(100)
        finally:
            closed = True

    async def work(value):
        return value

    source = inputs()
    async with aclosing(map_unordered(work, source, limit=2)) as results:
        await anext(results)
    assert closed


@pytest.mark.asyncio
async def test_failure_cancels_siblings_and_preserves_original_exception() -> None:
    second_started = asyncio.Event()
    second_cancelled = asyncio.Event()

    async def work(item: int) -> int:
        if item == 0:
            await second_started.wait()
            raise RuntimeError("original failure")
        second_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            second_cancelled.set()
        return item

    with pytest.raises(RuntimeError, match="original failure"):
        async with aclosing(map_unordered(work, range(100), limit=2)) as results:
            async for _ in results:
                pass
    assert second_cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
async def test_invalid_limit_is_rejected(limit) -> None:
    async def work(item: int) -> int:
        return item

    with pytest.raises(ValueError, match="positive integer"):
        await anext(map_unordered(work, [1], limit=limit))
