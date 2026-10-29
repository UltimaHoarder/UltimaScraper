from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
from ultima_scraper_backend.job_system.routing import BackendRouter
from ultima_scraper_backend.job_system.storage import JobStorage
from ultima_scraper_backend.workers.worker_pool import (
    CLAIM_BATCH_SIZE_ENV,
    DEFAULT_CLAIM_BATCH_SIZE,
    Worker,
)
import legacy_redis_runtime as legacy

# These exercise the Redis runtime; the SQL execution ledger holds no runs.
pytestmark = pytest.mark.usefixtures("no_ledger_runs")


class FakeRedisManager:
    def __init__(self, fake_redis: Any) -> None:
        self.fake_redis = fake_redis
        self.client = fake_redis
        self.is_connected = True

    async def get(self, key: str) -> Any:
        return await self.fake_redis.get(key)

    async def set(self, key: str, value: Any, ex: Any = None) -> Any:
        return await self.fake_redis.set(key, value, ex=ex)

    async def delete(self, *keys: str) -> Any:
        return await self.fake_redis.delete(*keys)


@pytest.mark.asyncio
async def test_claim_ready_tasks_reserves_until_state_transition() -> None:
    fake_redis = fakeredis.aioredis.FakeRedis()
    manager = FakeRedisManager(fake_redis)
    router = BackendRouter(manager)
    backend_id = "test-backend"

    # Enqueue 12 ready tasks with varying priorities
    items = [
        ("job-1", f"task-{i:02d}", i % 3)
        for i in range(12)
    ]
    await router.enqueue_ready_tasks(backend_id=backend_id, items=items)

    # Initial queue size should be 12
    queue_key = router._queue_key(backend_id)
    assert await fake_redis.zcard(queue_key) == 12

    # Reserve a batch without removing durable queue membership.
    first_batch = await router.claim_ready_tasks(
        backend_id, count=8, claimant_id="worker-a"
    )
    assert len(first_batch) == 8
    assert await fake_redis.zcard(queue_key) == 12

    # Another worker cannot reserve the same members.
    second_batch = await router.claim_ready_tasks(
        backend_id, count=8, claimant_id="worker-b"
    )
    assert len(second_batch) == 4
    assert await fake_redis.zcard(queue_key) == 12

    # All 12 tasks should have been popped with no duplicates
    all_reserved = first_batch + second_batch
    assert len(all_reserved) == 12
    assert len(set(all_reserved)) == 12

    empty_batch = await router.claim_ready_tasks(
        backend_id, count=8, claimant_id="worker-c"
    )
    assert empty_batch == []

    # A pre-start failure releases only its reservation, leaving the route.
    released_job, released_task = first_batch[0]
    await legacy.release_ready_claim(router, 
        backend_id,
        released_job,
        released_task,
        claimant_id="worker-a",
        task_is_ready=True,
    )
    assert await router.claim_ready_tasks(
        backend_id, count=1, claimant_id="worker-c"
    ) == [(released_job, released_task)]


@pytest.mark.asyncio
async def test_claim_ready_tasks_respects_count_bounds() -> None:
    fake_redis = fakeredis.aioredis.FakeRedis()
    manager = FakeRedisManager(fake_redis)
    router = BackendRouter(manager)
    backend_id = "test-bounds"

    await router.enqueue_ready_tasks(
        backend_id=backend_id,
        items=[("job-1", "task-1", 0), ("job-1", "task-2", 0)],
    )

    # Count <= 0 returns empty immediately
    assert await router.claim_ready_tasks(backend_id, count=0) == []
    assert await router.claim_ready_tasks(backend_id, count=-5) == []

    # Queue remains untouched
    queue_key = router._queue_key(backend_id)
    assert await fake_redis.zcard(queue_key) == 2


@pytest.mark.asyncio
async def test_claim_reservations_do_not_block_deeper_queue_members() -> None:
    fake_redis = fakeredis.aioredis.FakeRedis()
    manager = FakeRedisManager(fake_redis)
    router = BackendRouter(manager)
    backend_id = "test-deep-reservations"
    await router.enqueue_ready_tasks(
        backend_id=backend_id,
        items=[("job-1", f"task-{index:03d}", 0) for index in range(200)],
    )

    claims = []
    for worker_index in range(20):
        claims.extend(
            await router.claim_ready_tasks(
                backend_id,
                count=8,
                claimant_id=f"worker-{worker_index}",
            )
        )

    assert len(claims) == 160
    assert len(set(claims)) == 160


@pytest.mark.asyncio
async def test_routed_claim_dequeues_atomically_with_ready_to_inflight() -> None:
    fake_redis = fakeredis.aioredis.FakeRedis()
    manager = FakeRedisManager(fake_redis)
    router = BackendRouter(manager)
    storage = JobStorage(manager)
    backend_id = "test-atomic"
    job_id = "job-atomic"
    task_id = "task-atomic"
    ready_key = storage.TASKS_READY_KEY.format(job_id=job_id)
    inflight_key = storage.TASKS_INFLIGHT_KEY.format(job_id=job_id)

    await fake_redis.sadd(ready_key, task_id)
    await router.enqueue_ready_tasks(
        backend_id=backend_id,
        items=[(job_id, task_id, 0)],
    )
    assert await router.claim_ready_tasks(
        backend_id,
        count=1,
        claimant_id="worker-atomic",
    ) == [(job_id, task_id)]

    assert await legacy.mark_task_started(storage, 
        job_id,
        task_id,
        backend_id=backend_id,
        claim_owner="worker-atomic",
    )
    assert not await fake_redis.sismember(ready_key, task_id)
    assert await fake_redis.sismember(inflight_key, task_id)
    assert await fake_redis.zcard(router._queue_key(backend_id)) == 0
    reservations_key, owners_key = router._ready_claim_keys(backend_id)
    assert await fake_redis.zcard(reservations_key) == 0
    assert await fake_redis.hlen(owners_key) == 0


@pytest.mark.asyncio
async def test_mps_routed_claim_dequeues_with_guarded_state_transition() -> None:
    fake_redis = fakeredis.aioredis.FakeRedis()
    manager = FakeRedisManager(fake_redis)
    router = BackendRouter(manager)
    storage = JobStorage(manager)
    backend_id = "test-mps-atomic"
    job_id = "job-mps-atomic"
    task_id = "task-mps-atomic"
    state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
    ready_key = storage.TASKS_READY_KEY.format(job_id=job_id)
    inflight_key = storage.TASKS_INFLIGHT_KEY.format(job_id=job_id)
    await fake_redis.hset(
        state_key,
        mapping={
            "mps_manifest": 1,
            "mps_schedule_pending": 0,
            "status": "running",
        },
    )
    await fake_redis.zadd(
        storage.TASK_INDEX_KEY.format(job_id=job_id),
        {task_id: 1},
    )
    await fake_redis.sadd(ready_key, task_id)
    await router.enqueue_ready_tasks(
        backend_id=backend_id,
        items=[(job_id, task_id, 0)],
    )
    assert await router.claim_ready_tasks(
        backend_id,
        count=1,
        claimant_id="worker-mps-atomic",
    ) == [(job_id, task_id)]

    assert await legacy.mark_task_started(storage, 
        job_id,
        task_id,
        backend_id=backend_id,
        claim_owner="worker-mps-atomic",
    )
    assert not await fake_redis.sismember(ready_key, task_id)
    assert await fake_redis.sismember(inflight_key, task_id)
    assert await fake_redis.zcard(router._queue_key(backend_id)) == 0


def test_worker_compute_claim_batch_size_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ULTIMA_CLAIM_BATCH_SIZE", raising=False)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
    )
    worker = Worker(
        worker_id="test-w-batch",
        redis_url="redis://localhost",
        supported_sites=["onlyfans"],
        config=config,
    )

    assert DEFAULT_CLAIM_BATCH_SIZE == 8
    # When available slots exceed default batch size, returns default (8)
    assert worker.compute_claim_batch_size(available_slots=50) == 8
    assert worker.compute_claim_batch_size(available_slots=8) == 8


def test_worker_compute_claim_batch_size_clamping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ULTIMA_CLAIM_BATCH_SIZE", raising=False)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
    )
    worker = Worker(
        worker_id="test-w-clamp",
        redis_url="redis://localhost",
        supported_sites=["onlyfans"],
        config=config,
    )

    # When available slots are fewer than 8, clamps to available slots
    assert worker.compute_claim_batch_size(available_slots=5) == 5
    assert worker.compute_claim_batch_size(available_slots=1) == 1
    assert worker.compute_claim_batch_size(available_slots=0) == 1


def test_worker_compute_claim_batch_size_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CLAIM_BATCH_SIZE_ENV, "12")
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
    )
    worker = Worker(
        worker_id="test-w-env",
        redis_url="redis://localhost",
        supported_sites=["onlyfans"],
        config=config,
    )

    assert worker.compute_claim_batch_size(available_slots=50) == 12
    assert worker.compute_claim_batch_size(available_slots=6) == 6


@pytest.mark.skip(reason="Worker.run now uses the SQL execution ledger; this legacy router test would claim real work from the configured database and never finish")
@pytest.mark.asyncio
async def test_worker_run_dispatches_claimed_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ULTIMA_CLAIM_BATCH_SIZE", raising=False)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
    )
    worker = Worker(
        worker_id="test-w-dispatch",
        redis_url="redis://localhost",
        supported_sites=["onlyfans"],
        config=config,
        worker_count=1,
    )
    worker.apis = {"onlyfans": MagicMock()}
    worker.task_job_storage = MagicMock()
    worker.backend_router = MagicMock()

    batch = [("job-batch", f"task-{i}") for i in range(5)]
    executed_tasks: list[tuple[str, str]] = []
    claimed = False

    async def fake_claim_tasks(backend_id: str, count: int = 8) -> list[tuple[str, str]]:
        nonlocal claimed
        if not claimed:
            claimed = True
            return list(batch)
        # On subsequent iterations, stop the worker
        worker._shutdown_event.set()
        return []

    worker.backend_router.claim_ready_tasks = AsyncMock(side_effect=fake_claim_tasks)

    async def fake_execute(job_id: str, task_id: str) -> tuple[bool, bool, bool]:
        executed_tasks.append((job_id, task_id))
        return True, False, True

    worker._execute_ready_task = fake_execute

    await worker.run()

    # All 5 tasks from the batch should have been executed
    assert len(executed_tasks) == 5
    assert executed_tasks == batch


@pytest.mark.skip(reason="Worker.run now uses the SQL execution ledger; this legacy router test would claim real work from the configured database and never finish")
@pytest.mark.asyncio
async def test_worker_run_graceful_fallback_when_claim_ready_tasks_not_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
    )
    worker = Worker(
        worker_id="test-w-fallback",
        redis_url="redis://localhost",
        supported_sites=["onlyfans"],
        config=config,
        worker_count=1,
    )
    worker.apis = {"onlyfans": MagicMock()}
    worker.task_job_storage = MagicMock()
    worker.backend_router = MagicMock()

    # claim_ready_tasks is a non-awaitable MagicMock (simulating legacy mock fixture)
    # only claim_ready_task is configured as AsyncMock
    loop_count = 0

    async def fake_single_claim(backend_id: str, timeout: int = 5) -> tuple[str, str] | None:
        nonlocal loop_count
        loop_count += 1
        if loop_count == 1:
            return ("job-single", "task-single")
        worker._shutdown_event.set()
        return None

    worker.backend_router.claim_ready_task = AsyncMock(side_effect=fake_single_claim)

    executed: list[tuple[str, str]] = []

    async def fake_execute(job_id: str, task_id: str) -> tuple[bool, bool, bool]:
        executed.append((job_id, task_id))
        return True, False, True

    worker._execute_ready_task = fake_execute

    await worker.run()

    assert executed == [("job-single", "task-single")]
