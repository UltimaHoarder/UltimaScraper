"""Single-machine queue and event-bus contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from ultima_scraper_backend.config import ExecutionMode
from ultima_scraper_backend.job_system.models import Job, JobStatus
from ultima_scraper_backend.models.backend import BackendInstance
from ultima_scraper_backend.models.queue import RedisQueue


async def _build_local_backend() -> BackendInstance:
    backend = BackendInstance(
        instance_id="test-single-machine",
        redis=None,
        execution_mode=ExecutionMode.LOCAL,
    )
    backend._sync_backend_inventory = AsyncMock(return_value=None)
    await backend.initialize()
    return backend


@pytest.fixture
async def local_backend():
    backend = await _build_local_backend()
    try:
        yield backend
    finally:
        await backend.close()


def _build_job(job_id: str, name: str) -> Job:
    return Job(
        job_id=job_id,
        name=name,
        state=JobStatus.PENDING,
        created_by="test",
        created_at=datetime.now(timezone.utc).isoformat(),
        tasks=[],
        task_ids=[],
        metadata={},
    )


async def test_local_queue_enqueue_dequeue(local_backend: BackendInstance) -> None:
    assert not local_backend.distributed_mode
    assert local_backend.active_queue is local_backend._local_queue

    job = _build_job("test-job-1", "Test Job")
    await local_backend.active_queue.enqueue(job)
    assert await local_backend.active_queue.size() == 1

    dequeued_job = await local_backend.active_queue.dequeue()
    assert dequeued_job is not None
    assert dequeued_job.job_id == job.job_id
    assert await local_backend.active_queue.size() == 0


async def test_redis_queue_round_trips_the_canonical_job_model() -> None:
    redis = AsyncMock()
    queue = RedisQueue(redis)
    original = _build_job("redis-job-1", "Redis Job")

    await queue.enqueue(original)
    serialized = redis.lpush.await_args.args[1]
    redis.brpop.return_value = ("ultimascraper:jobs", serialized)

    restored = await queue.dequeue()

    assert restored is not None
    assert restored.to_dict() == original.to_dict()


async def test_local_event_bus(local_backend: BackendInstance) -> None:
    received_events: list[dict[str, object]] = []

    async def event_handler(event_data: dict[str, object]) -> None:
        received_events.append(event_data)

    channel = "test:events"
    event = {"type": "test", "message": "Hello from local event bus"}
    await local_backend.active_event_bus.subscribe(channel, event_handler)
    await local_backend.active_event_bus.publish(channel, event)

    assert received_events == [event]


async def test_multiple_jobs_fifo(local_backend: BackendInstance) -> None:
    expected_ids = []
    for index in range(5):
        job = _build_job(f"test-job-{index}", f"Test Job {index}")
        await local_backend.active_queue.enqueue(job)
        expected_ids.append(job.job_id)

    actual_ids = []
    for _ in range(5):
        job = await local_backend.active_queue.dequeue()
        assert job is not None
        actual_ids.append(job.job_id)

    assert actual_ids == expected_ids


async def test_queue_stats(local_backend: BackendInstance) -> None:
    stats = await local_backend.get_queue_stats()
    assert stats["distributed_mode"] is False
    assert stats["local_queue_size"] == 0
    assert stats["redis_queue_size"] == 0

    for index in range(3):
        await local_backend.active_queue.enqueue(
            _build_job(f"stats-job-{index}", f"Stats Job {index}")
        )

    stats = await local_backend.get_queue_stats()
    assert stats["local_queue_size"] == 3
    assert stats["active_queue_type"] == "memory"
