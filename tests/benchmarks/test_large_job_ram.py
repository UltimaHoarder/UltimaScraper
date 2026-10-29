from __future__ import annotations

import json
import tracemalloc
from types import SimpleNamespace
from typing import Any

import pytest

from ultima_scraper_backend.job_system.manager import JobManager
from ultima_scraper_backend.job_system.models import Job
from ultima_scraper_backend.job_system.storage import JobStorage

# These exercise the Redis runtime; the SQL execution ledger holds no runs.
pytestmark = pytest.mark.usefixtures("no_ledger_runs")

# The large index is virtual: only requested pages create task representations.
TOTAL_TASKS = 1_000_000
BENCHMARK_TASKS = 100
PAGE_LIMIT = 100
DISPATCH_BATCH_SIZE = 1_000
DISPATCH_SAMPLE_PAGE_SIZE = 10
MAX_PAGE_PEAK_BYTES = 16 * 1024 * 1024
MAX_DISPATCH_PEAK_BYTES = 8 * 1024 * 1024


class SyntheticTaskIndexClient:
    def __init__(self, total_tasks: int, *, completed_tasks: int = 0) -> None:
        self.total_tasks = total_tasks
        self.completed_tasks = completed_tasks
        self.zrange_calls: list[tuple[int, int]] = []
        self.zrevrange_calls: list[tuple[int, int]] = []
        self.mget_batch_sizes: list[int] = []

    async def zcard(self, _key: str) -> int:
        return self.total_tasks

    async def hget(self, _key: str, field: str) -> str | None:
        if field == "total_tasks":
            return str(self.total_tasks)
        return None

    async def zrange(self, _key: str, start: int, end: int) -> list[str]:
        assert 0 <= start <= end and end - start + 1 <= PAGE_LIMIT * 5
        self.zrange_calls.append((start, end))
        if start >= self.total_tasks:
            return []
        stop = min(end, self.total_tasks - 1)
        return [f"task-{index}" for index in range(start, stop + 1)]

    async def zrevrange(self, _key: str, start: int, end: int) -> list[str]:
        assert 0 <= start <= end and end - start + 1 <= PAGE_LIMIT * 5
        self.zrevrange_calls.append((start, end))
        if start >= self.total_tasks:
            return []
        stop = min(end, self.total_tasks - 1)
        return [
            f"task-{self.total_tasks - index - 1}" for index in range(start, stop + 1)
        ]

    async def get(self, key: str) -> str:
        task_id = key.rsplit(":", 1)[-1]
        task_index = int(task_id.split("-")[-1])
        task_state = (
            "completed"
            if task_index >= self.total_tasks - self.completed_tasks
            else "pending"
        )
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
                "job_id": "job-scale",
                "capabilities": [],
                "ip_lock_key": None,
                "deferred_dedup_key": None,
                "state": task_state,
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
        assert len(keys) <= PAGE_LIMIT * 5
        self.mget_batch_sizes.append(len(keys))
        return [await self.get(key) for key in keys]


class SyntheticRedisManager:
    def __init__(self, client: SyntheticTaskIndexClient) -> None:
        self.client = client

    async def get(self, key: str) -> str:
        return await self.client.get(key)


class SyntheticReadyStorage:
    def __init__(self, total_tasks: int, *, page_size: int) -> None:
        self.total_tasks = total_tasks
        self.page_size = page_size
        self.requested_batch_sizes: list[int] = []

    async def iter_ready_task_ids(
        self,
        _job_id: str,
        *,
        batch_size: int = DISPATCH_BATCH_SIZE,
    ):
        self.requested_batch_sizes.append(batch_size)
        # A streaming source may yield less than the requested maximum. Short
        # pages exercise repeated routing without enumerating the virtual index.
        size = min(batch_size, self.page_size)
        for start in range(0, self.total_tasks, size):
            stop = min(start + size, self.total_tasks)
            yield [f"task-{index}" for index in range(start, stop)]


class RecordingRouter:
    def __init__(self) -> None:
        self.enqueued_batch_sizes: list[int] = []
        self.enqueued_task_total = 0

    async def enqueue_ready_tasks(
        self,
        *,
        backend_id: str,
        items: list[tuple[str, str, int]],
    ) -> None:
        assert backend_id == "backend-scale"
        self.enqueued_batch_sizes.append(len(items))
        self.enqueued_task_total += len(items)


def _peak_bytes_for(coro: Any) -> tuple[Any, int]:
    async def _runner() -> tuple[Any, int]:
        tracemalloc.start()
        try:
            result = await coro
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        return result, peak

    return _runner()


@pytest.mark.asyncio
async def test_million_task_page_reads_stay_windowed(record_property) -> None:
    client = SyntheticTaskIndexClient(TOTAL_TASKS)
    storage = JobStorage(SyntheticRedisManager(client))

    first_page, first_peak = await _peak_bytes_for(
        storage.fetch_task_page("job-scale", limit=PAGE_LIMIT)
    )
    assert len(first_page.tasks) == PAGE_LIMIT
    assert first_page.tasks[0].task_id == "task-0"
    # Cursor must point at the first task not yet returned, otherwise the
    # client would skip tasks between the last returned item and the scan
    # window size.
    assert first_page.next_cursor == str(PAGE_LIMIT)
    assert first_page.scanned_count == PAGE_LIMIT
    assert client.zrange_calls == [(0, PAGE_LIMIT - 1)]
    assert client.mget_batch_sizes == [PAGE_LIMIT]
    assert first_peak < MAX_PAGE_PEAK_BYTES

    client.zrange_calls.clear()
    client.mget_batch_sizes.clear()
    deep_page, deep_peak = await _peak_bytes_for(
        storage.fetch_task_page(
            "job-scale",
            cursor=str(TOTAL_TASKS - PAGE_LIMIT),
            limit=PAGE_LIMIT,
        )
    )
    assert len(deep_page.tasks) == PAGE_LIMIT
    assert deep_page.tasks[0].task_id == f"task-{TOTAL_TASKS - PAGE_LIMIT}"
    assert deep_page.next_cursor is None
    assert deep_page.scanned_count == TOTAL_TASKS
    assert client.zrange_calls == [(TOTAL_TASKS - PAGE_LIMIT, TOTAL_TASKS - 1)]
    assert client.mget_batch_sizes == [PAGE_LIMIT]
    assert deep_peak < MAX_PAGE_PEAK_BYTES
    record_property("logical_tasks", TOTAL_TASKS)
    record_property("first_page_tasks", len(first_page.tasks))
    record_property("deep_page_tasks", len(deep_page.tasks))
    record_property("first_page_peak_bytes", first_peak)
    record_property("deep_page_peak_bytes", deep_peak)


@pytest.mark.asyncio
async def test_million_task_completed_filter_starts_at_recent_edge(record_property) -> None:
    client = SyntheticTaskIndexClient(TOTAL_TASKS, completed_tasks=17_581)
    storage = JobStorage(SyntheticRedisManager(client))

    page, peak = await _peak_bytes_for(
        storage.fetch_task_page("job-scale", limit=PAGE_LIMIT, state="completed")
    )

    assert len(page.tasks) == PAGE_LIMIT
    assert page.tasks[0].task_id == f"task-{TOTAL_TASKS - 1}"
    assert client.zrange_calls == []
    assert client.zrevrange_calls == [(0, 499)]
    assert client.mget_batch_sizes == [PAGE_LIMIT * JobStorage.TASK_PAGE_SCAN_MULTIPLIER]
    assert peak < MAX_PAGE_PEAK_BYTES
    record_property("logical_tasks", TOTAL_TASKS)
    record_property("returned_tasks", len(page.tasks))
    record_property("hydrated_tasks", sum(client.mget_batch_sizes))
    record_property("peak_bytes", peak)


@pytest.mark.parametrize("total", [100, 1_000_000])
@pytest.mark.parametrize("edge", ["first", "middle", "final", "sparse_filtered"])
async def test_virtual_history_matrix_materializes_only_requested_rows(total, edge, record_property):
    class SparseIndex(SyntheticTaskIndexClient):
        async def get(self, key):
            value = json.loads(await super().get(key))
            ordinal = int(value["task_id"].split("-")[-1])
            value["state"] = "completed" if ordinal % 20 == 0 else "pending"
            return json.dumps(value)

    client = SparseIndex(total)
    storage = JobStorage(SyntheticRedisManager(client))
    start = {"first": 0, "middle": total//2, "final": total-10, "sparse_filtered": 0}[edge]
    page, peak = await _peak_bytes_for(storage.fetch_task_page(
        "job-scale", limit=10, cursor=str(start),
        state="completed" if edge == "sparse_filtered" else None,
    ))
    if edge == "sparse_filtered":
        assert 0 < len(page.tasks) < 10
        assert client.zrevrange_calls == [(0, 49)]
        assert client.mget_batch_sizes == [50]
        assert page.next_cursor == "50"
    else:
        assert len(page.tasks) == 10
        assert client.zrange_calls == [(start, start+9)]
        assert client.mget_batch_sizes == [10]
        assert page.next_cursor == (None if edge == "final" else str(start+10))
    assert peak < MAX_PAGE_PEAK_BYTES
    record_property("history_sample", json.dumps({
        "logical_total": total, "class": edge, "cursor": start,
        "materialized_task_dictionaries": sum(client.mget_batch_sizes),
        "returned_rows": len(page.tasks), "peak_bytes": peak,
    }))


@pytest.mark.asyncio
async def test_dispatch_routes_100_sampled_tasks_in_bounded_pages(record_property) -> None:
    manager = JobManager(SimpleNamespace(client=None))
    synthetic_storage = SyntheticReadyStorage(
        BENCHMARK_TASKS, page_size=DISPATCH_SAMPLE_PAGE_SIZE
    )
    recording_router = RecordingRouter()
    manager.storage = synthetic_storage  # type: ignore[assignment]
    manager.router = recording_router  # type: ignore[assignment]

    job = Job.create(
        name="Scale Dispatch",
        created_by="benchmark",
        tasks=[],
    )

    _, peak = await _peak_bytes_for(
        manager._enqueue_ready_tasks_from_storage(
            job=job,
            backend_id="backend-scale",
            base_priority=0,
        )
    )

    assert synthetic_storage.requested_batch_sizes == [DISPATCH_BATCH_SIZE]
    assert recording_router.enqueued_task_total == BENCHMARK_TASKS
    assert (
        len(recording_router.enqueued_batch_sizes)
        == BENCHMARK_TASKS // DISPATCH_SAMPLE_PAGE_SIZE
    )
    assert max(recording_router.enqueued_batch_sizes) == DISPATCH_SAMPLE_PAGE_SIZE
    assert peak < MAX_DISPATCH_PEAK_BYTES
    record_property("sampled_tasks", recording_router.enqueued_task_total)
    record_property("routing_pages", len(recording_router.enqueued_batch_sizes))
    record_property("maximum_page_tasks", max(recording_router.enqueued_batch_sizes))
    record_property("peak_bytes", peak)
