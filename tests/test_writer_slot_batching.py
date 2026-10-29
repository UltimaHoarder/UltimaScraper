"""Commands admitted during SQL saturation still join waiting batches."""

import asyncio

from test_database_write_queue import _RecordingExecutor, redis_manager
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteCommand,
    DatabaseWriteOperation,
    DatabaseWriterService,
)

__all__ = ["redis_manager"]


async def test_sql_slot_wait_does_not_freeze_an_underfilled_batch(redis_manager):
    executor = _RecordingExecutor()
    service = DatabaseWriterService(
        redis_manager, executor, batch_size=3, concurrency=1
    )
    service.batch_max_wait_seconds = 0.01
    await service._batch_slots.acquire()
    stopping = asyncio.Event()

    def admit(identifier):
        entry_id = f"{identifier}-0"
        command = DatabaseWriteCommand(
            str(identifier),
            DatabaseWriteOperation.UPSERT_USER,
            "onlyfans",
            {"user": {"id": identifier}},
            "fixture",
            "2026-10-04T00:00:00Z",
        )
        return service._start_lanes([(entry_id, command)], {entry_id: 10}, stopping)

    first = admit(1)
    task = next(iter(first))
    # Let the collection age expire while every SQL slot is busy.
    await asyncio.sleep(0.03)
    second = admit(2)
    third = admit(3)
    try:
        assert next(iter(second)) is task
        assert next(iter(third)) is task
        assert third[task] == (3, 30)
        assert executor.batches == []
    finally:
        service._batch_slots.release()
        await asyncio.wait_for(
            asyncio.gather(*set(first) | set(second) | set(third)), timeout=1
        )
    assert [
        [command.command_id for command in batch] for batch in executor.batches
    ] == [["1", "2", "3"]]
    assert not service._identity_tails and not service._open_lane_batches
