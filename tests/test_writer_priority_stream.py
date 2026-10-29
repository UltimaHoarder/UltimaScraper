"""Interactive MPS submissions bypass the bulk writer backlog."""

import asyncio

import pytest

from test_database_write_queue import _RecordingExecutor, redis_manager
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteClient,
    DatabaseWriteOperation,
    DatabaseWriterService,
    _WriterSlots,
)

__all__ = ["redis_manager"]


async def test_priority_waiter_takes_the_next_slot_before_earlier_bulk_waiters():
    slots = _WriterSlots(1)
    await slots.acquire()
    order = []

    async def take(name, priority):
        await slots.acquire(priority=priority)
        order.append(name)
        slots.release()

    bulk = asyncio.create_task(take("bulk", False))
    await asyncio.sleep(0)
    urgent = asyncio.create_task(take("priority", True))
    await asyncio.sleep(0)
    slots.release()
    await asyncio.wait_for(asyncio.gather(bulk, urgent), timeout=1)
    assert order == ["priority", "bulk"]
    assert slots._value == 1


async def test_cancelled_slot_waiter_does_not_leak_a_slot():
    slots = _WriterSlots(1)
    await slots.acquire()
    waiter = asyncio.create_task(slots.acquire(priority=True))
    await asyncio.sleep(0)
    # Hand over the slot and cancel before the waiter resumes.
    slots.release()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert slots._value == 1
    assert not slots.locked()


async def test_mps_submission_is_admitted_while_the_bulk_queue_is_full(redis_manager):
    client = DatabaseWriteClient(
        redis_manager, max_queue_commands=1, enqueue_timeout_seconds=0.02
    )
    await client.enqueue(
        DatabaseWriteOperation.UPSERT_USER,
        {"user": {"id": 1}},
        site="onlyfans",
        command_id="bulk",
    )
    await client.enqueue(
        DatabaseWriteOperation.PREPARE_MPS_JOB,
        {"job_id": "job-1"},
        site="onlyfans",
        command_id="prepare",
    )
    redis = redis_manager.client
    assert await redis.xlen(client.STREAM_KEY) == 1
    assert await redis.xlen(client.PRIORITY_STREAM_KEY) == 1
    assert int(await redis.get(client.PRIORITY_QUEUED_BYTES_KEY)) > 0

    service = DatabaseWriterService(redis_manager, _RecordingExecutor(), block_ms=1)
    await service._ensure_group()
    entries = await service._read_stream_entries(client.PRIORITY_STREAM_KEY)
    pending, _ = await service._prepare_entries(entries)
    assert [entry_id.startswith("priority:") for entry_id, _ in pending] == [True]
    assert await service._execute_and_ack_batch(pending) == []
    assert await redis.xlen(client.PRIORITY_STREAM_KEY) == 0
    assert int(await redis.get(client.PRIORITY_QUEUED_BYTES_KEY)) == 0
    # The bulk stream and its byte budget are untouched.
    assert await redis.xlen(client.STREAM_KEY) == 1
    assert int(await redis.get(client.QUEUED_BYTES_KEY)) > 0


async def test_running_writer_executes_submission_ahead_of_bulk_backlog(redis_manager):
    first_started = asyncio.Event()
    release = asyncio.Event()

    class Executor(_RecordingExecutor):
        async def execute_batch(self, commands):
            if commands[0].command_id == "bulk-0":
                first_started.set()
                await release.wait()
            return await super().execute_batch(commands)

    client = DatabaseWriteClient(redis_manager)
    service = DatabaseWriterService(
        redis_manager, Executor(), batch_size=1, concurrency=1, block_ms=5
    )
    for index in range(4):
        await client.enqueue(
            DatabaseWriteOperation.UPSERT_USER,
            {"user": {"id": index}},
            site="onlyfans",
            command_id=f"bulk-{index}",
        )
    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(3):
            await first_started.wait()
            await client.enqueue(
                DatabaseWriteOperation.PREPARE_MPS_JOB,
                {"job_id": "job-1"},
                site="onlyfans",
                command_id="prepare",
            )
            # Let the writer read the submission while the slot is held.
            await asyncio.sleep(0.05)
            release.set()
            while await redis_manager.client.xlen(client.STREAM_KEY) or (
                await redis_manager.client.xlen(client.PRIORITY_STREAM_KEY)
            ):
                await asyncio.sleep(0.005)
    finally:
        service.stop()
        await asyncio.wait_for(writer, timeout=3)
    order = [batch[0].command_id for batch in service.executor.batches]
    assert order[:2] == ["bulk-0", "prepare"]
    assert sorted(order) == ["bulk-0", "bulk-1", "bulk-2", "bulk-3", "prepare"]
