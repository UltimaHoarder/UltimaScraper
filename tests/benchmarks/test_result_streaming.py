from __future__ import annotations

import json
import tracemalloc
from types import SimpleNamespace

import pytest

from ultima_scraper_backend.api.routes import jobs as jobs_module
from ultima_scraper_backend.job_system.storage import JobStorage

# These exercise the Redis runtime; the SQL execution ledger holds no runs.
pytestmark = pytest.mark.usefixtures("no_ledger_runs")

TOTAL_TASKS = 1_000_000
STREAM_BATCH_SIZE = 250
MAX_STREAM_STARTUP_PEAK_BYTES = 20 * 1024 * 1024


class SyntheticTaskIndexClient:
    def __init__(self, total_tasks: int) -> None:
        self.total_tasks = total_tasks
        self.zrange_calls: list[tuple[int, int]] = []

    async def zcard(self, _key: str) -> int:
        return self.total_tasks

    async def hget(self, _key: str, field: str) -> str | None:
        if field == "total_tasks":
            return str(self.total_tasks)
        return None

    async def zrange(self, _key: str, start: int, end: int) -> list[str]:
        self.zrange_calls.append((start, end))
        if start >= self.total_tasks:
            return []
        stop = min(end, self.total_tasks - 1)
        return [f"task-{index}" for index in range(start, stop + 1)]

    async def get(self, key: str) -> str:
        task_id = key.rsplit(":", 1)[-1]
        task_index = int(task_id.split("-")[-1])
        return json.dumps(
            {
                "task_id": task_id,
                "task_type": "api_command",
                "site_name": "onlyfans",
                "user_id": task_index + 1,
                "user_username": f"user-{task_index}",
                "content_type": None,
                "payload": {"index": task_index},
                "auth_id": None,
                "job_id": "job-stream",
                "capabilities": [],
                "ip_lock_key": None,
                "deferred_dedup_key": None,
                "state": "pending",
                "created_at": "2026-03-12T00:00:00+00:00",
                "updated_at": "2026-03-12T00:00:00+00:00",
                "started_at": None,
                "completed_at": None,
                "depends_on": [],
                "attempts": 0,
                "max_attempts": 3,
                "result": None,
                "parent_task_id": None,
                "subtasks": [],
            }
        )

    async def mget(self, keys: list[str]) -> list[str]:
        return [await self.get(key) for key in keys]


class SyntheticRedisManager:
    def __init__(self, client: SyntheticTaskIndexClient) -> None:
        self.client = client

    async def get(self, key: str) -> str:
        return await self.client.get(key)


@pytest.mark.asyncio
async def test_stream_startup_reads_only_the_first_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SyntheticTaskIndexClient(TOTAL_TASKS)
    storage = JobStorage(SyntheticRedisManager(client))

    monkeypatch.setattr(jobs_module, "JobStorage", lambda _redis: storage)
    monkeypatch.setattr(
        jobs_module,
        "_task_to_detail",
        lambda task: jobs_module.TaskDetail(
            task_id=task.task_id,
            task_type=task.task_type.value,
            status=task.state.value,
            site=task.site_name,
            username=task.user_username,
            content_type=task.content_type,
            payload=task.payload,
            started_at=task.started_at,
            completed_at=task.completed_at,
            progress=0.0,
            items_processed=0,
            items_total=None,
            error=None,
            result=None,
        ),
    )

    backend = SimpleNamespace(
        redis=SimpleNamespace(client=object()),
        distributed_mode=False,
    )

    response = await jobs_module.stream_job_tasks(
        "job-stream",
        batch_size=STREAM_BATCH_SIZE,
        backend=backend,
    )

    iterator = response.body_iterator.__aiter__()
    tracemalloc.start()
    try:
        first_chunk = await iterator.__anext__()
        second_chunk = await iterator.__anext__()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        if hasattr(iterator, "aclose"):
            await iterator.aclose()

    first_text = first_chunk if isinstance(first_chunk, str) else first_chunk.decode("utf-8")
    second_text = second_chunk if isinstance(second_chunk, str) else second_chunk.decode("utf-8")

    assert 'data: {"task_id":"task-0"' in first_text
    assert 'data: {"task_id":"task-1"' in second_text
    assert client.zrange_calls == [(0, 249)]
    assert peak < MAX_STREAM_STARTUP_PEAK_BYTES
