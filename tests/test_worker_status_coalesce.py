"""Coalesced worker status snapshots: one write per interval, newest state wins."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from ultima_scraper_backend.redis import worker_registry
from ultima_scraper_backend.redis.worker_registry import WorkerRegistry, WorkerStatus
from ultima_scraper_backend.workers.worker_pool import Worker

pytestmark = pytest.mark.asyncio


class _Redis:
    config = SimpleNamespace(host="localhost", port=6379, db=0, password=None)

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.sets = 0

    async def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        self.sets += 1
        self.values[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        for key in keys:
            self.values.pop(key, None)
        return len(keys)

    async def srem(self, name: str, *values: str) -> int:
        return 0


def _registry(monkeypatch: pytest.MonkeyPatch, seconds: str) -> tuple[WorkerRegistry, _Redis]:
    monkeypatch.setenv(worker_registry.STATUS_COALESCE_ENV, seconds)
    redis = _Redis()
    return WorkerRegistry(redis, "backend-1", worker_id="worker-1"), redis


async def test_status_writes_are_immediate_by_default(monkeypatch):
    registry, redis = _registry(monkeypatch, "0")
    await registry.start_task("task-1", "scrape")
    await registry.complete_task(task_id="task-1")
    assert redis.sets == 2


async def test_coalesced_status_writes_the_newest_snapshot_once(monkeypatch):
    registry, redis = _registry(monkeypatch, "0.02")
    for n in range(5):
        await registry.start_task(f"task-{n}", "scrape")
    await registry.complete_task(task_id="task-4")
    assert redis.sets == 0
    await asyncio.sleep(0.05)
    assert redis.sets == 1
    snapshot = json.loads(redis.values[registry._worker_key()])
    assert snapshot["status"] == WorkerStatus.BUSY.value
    assert snapshot["current_task"]["task_id"] == "task-3"
    for n in range(4):
        await registry.complete_task(task_id=f"task-{n}")
    await asyncio.sleep(0.05)
    assert redis.sets == 2
    assert json.loads(redis.values[registry._worker_key()])["status"] == WorkerStatus.IDLE.value


async def test_unregister_cancels_a_pending_snapshot(monkeypatch):
    registry, redis = _registry(monkeypatch, "0.02")
    await registry.start_task("task-1", "scrape")
    await registry.unregister()
    await asyncio.sleep(0.05)
    assert registry._worker_key() not in redis.values


async def test_repeated_worker_reports_are_throttled(monkeypatch):
    registry, _ = _registry(monkeypatch, "60")
    published: list[dict[str, Any]] = []

    async def publish(redis, payload):
        published.append(payload)

    monkeypatch.setattr("ultima_scraper_backend.workers.worker_pool.publish_ws_event", publish)
    worker = Worker.__new__(Worker)
    worker.redis = SimpleNamespace(client=None)
    worker.worker_registry = registry
    worker.worker_id = "worker-1"
    worker.backend_id = "backend-1"
    worker.supported_sites = ["onlyfans"]
    worker._collect_memory_telemetry = lambda: {}
    for _ in range(3):
        await worker._update_worker_status(status="busy", current_job="job-1")
    await worker._update_worker_status(status="busy", current_job="job-2")
    await worker._update_worker_status(status="idle")
    await worker._update_worker_status(status="idle", job_success=True)
    assert [(p["status"], p["current_job"]) for p in published] == [
        ("busy", "job-1"), ("busy", "job-2"), ("idle", None), ("idle", None)
    ]
