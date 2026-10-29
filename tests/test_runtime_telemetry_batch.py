"""Batched runtime telemetry must aggregate exactly like the per-task script."""

import asyncio
import json
from typing import Any

import fakeredis.aioredis
import pytest

from ultima_scraper_backend.job_system import runtime_telemetry
from ultima_scraper_backend.job_system.storage import JobStorage

pytestmark = pytest.mark.asyncio

ROUTE_A = "route-" + "a" * 16
ROUTE_B = "route-" + "0123456789abcdef"


class _Manager:
    def __init__(self, client: Any) -> None:
        self.client = client


def _storage(monkeypatch: pytest.MonkeyPatch, batch_seconds: str) -> JobStorage:
    monkeypatch.setenv(runtime_telemetry.BATCH_SECONDS_ENV, batch_seconds)
    storage = JobStorage(_Manager(fakeredis.aioredis.FakeRedis()))
    storage._runtime_telemetry_batcher()  # bind the switch at construction
    return storage


def _task(index: int, worker: str, *, completed: int | None, total: int) -> dict[str, Any]:
    started = 1_000 + index * 250
    # Out-of-order finishes exercise the per-worker "only later" logic.
    finished = started + 1_000 + (index % 3) * 500 - (750 if index == 6 else 0)
    route = ROUTE_A if index % 2 else ROUTE_B
    return {
        "started_ms": started,
        "finished_ms": finished,
        "queue_wait_ms": 10.25 * index,
        "setup_ms": 2.5,
        "handler_ms": 500.5 + index,
        "writer_ms": 40.0,
        "post_ms": 3.75,
        "release_ms": 1.0,
        "route_active_ms": 300.5,
        "route_attempts": 1 + index % 2,
        "success": index % 4 != 3,
        "completed_count": completed,
        "total_tasks": total,
        "claim_wait_ms": 0.5 * index,
        "worker_id": worker,
        "expected_workers": 2 + index % 2,
        "effective_worker_concurrency": 100 + index,
        "writer_admission_ms": 1.5,
        "writer_queue_ms": 4.0,
        "writer_execution_ms": 6.25,
        "writer_timed_submits": 1,
        "writer_timing_coverage": index % 2,
        "writer_flush_ms": 0.75,
        "writer_queue_commands_sum": 30.0 + index,
        "writer_queue_commands_max": 30 + index * 7 % 11,
        "writer_configured_concurrency": 12,
        "writer_window_commands": 800 - index,
        "handler_guest_init_ms": 25.0 if index % 3 == 0 else 0.0,
        "handler_guest_init_count": 1 if index % 3 == 0 else 0,
        "handler_fallback_retry_ms": 12.5 if index == 4 else 0.0,
        "handler_fallback_retry_count": 1 if index == 4 else 0,
        "writer_batch_fill_ratio_sum": 0.25,
        "writer_result_cache_hits": index % 2,
        "writer_receipt_fallbacks": 1 - index % 2,
        "writer_authority_rows_examined": 2.0,
        "writer_operation_stats_json": json.dumps(
            {
                "upsert_user": {
                    "count": 1,
                    "batch_commands_sum": 30 + index,
                    "batch_wall_ms_sum": 12.5,
                    **(
                        {
                            "receipt_phases_count": 1,
                            "receipt_lock_ms_sum": 1.5,
                            "receipt_read_ms_sum": 0.5,
                            "write_fence_ms_sum": 0.25,
                        }
                        if index % 2
                        else {}
                    ),
                }
            }
        ),
        "writer_domain_stats_json": json.dumps(
            {"user": {"count": 1, "batch_commands_sum": 30, "batch_wall_ms_sum": 10}}
        ),
        "writer_split_missing_reasons_json": json.dumps(
            {"result_cache_miss": index % 2} if index % 2 else {}
        ),
        "setup_subphases_json": json.dumps(
            {"auth_load": {"ms": 1.25, "count": 1}, "residual": {"ms": 0.5, "count": 1}}
        ),
        "guest_auth_stats_json": json.dumps(
            {"lock_wait": {"ms": 3.0, "count": 2}} if index % 3 == 0 else {}
        ),
        "terminal_stats_json": json.dumps(
            {"counter_transition": {"ms": 3.75, "count": 1}}
        ),
        "ledger_stats_json": json.dumps(
            {"renew": {"ms": 2.5, "count": index % 3}, "finish": {"ms": 4.0, "count": 1}}
        ),
        "route_lookup_stats_json": json.dumps(
            {
                route: {
                    "primary_selected_count": 1,
                    "healthy_selected_count": 1,
                    "retry_selected_count": index % 2,
                    "route_attempts": 1,
                    "lookup_observations": 1,
                    "route_active_ms": 300.5,
                    "guest_init_ms": 25.0,
                    "lookup_ms": 250.25,
                    "lookup_found_count": 1 if index % 4 else 0,
                    "lookup_not_found_count": 0 if index % 4 else 1,
                },
                "not-a-route": {"route_attempts": 1},
            }
        ),
    }


# (worker, ready depth) per flush; a batch only ever holds one worker's tasks,
# as in production, where each worker process has its own batcher.
SEGMENTS = (("worker-1", 40, 4), ("worker-2", 0, 3), ("worker-1", 7, 3), ("worker-2", 9, 2))


async def _replay(storage: JobStorage, job_id: str, *, completed: bool) -> None:
    state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
    index = 0
    for worker, ready, count in SEGMENTS:
        await storage._client().hset(state_key, "ready_tasks", ready)
        for _ in range(count):
            await storage.record_task_runtime_telemetry(
                job_id,
                **_task(
                    index,
                    worker,
                    completed=index * 2 if completed else None,
                    total=12,
                ),
            )
            index += 1
        await storage.flush_runtime_telemetry()


def _decoded_hash(raw: dict[bytes, bytes]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in raw.items():
        name, text = key.decode(), value.decode()
        if name.endswith("_json"):
            result[name] = json.loads(text)
        else:
            try:
                result[name] = float(text)
            except ValueError:
                result[name] = text
    return result


@pytest.mark.parametrize("completed", [False, True])
async def test_batched_telemetry_matches_per_task_path(
    monkeypatch: pytest.MonkeyPatch, completed: bool
) -> None:
    job_id = "job-telemetry-batch"
    per_task = _storage(monkeypatch, "0")
    batched = _storage(monkeypatch, "3600")
    assert per_task._telemetry_batcher is None
    assert batched._telemetry_batcher is not None

    await _replay(per_task, job_id, completed=completed)
    await _replay(batched, job_id, completed=completed)

    expected = await per_task.get_job_runtime_telemetry(job_id)
    actual = await batched.get_job_runtime_telemetry(job_id)
    assert expected is not None and expected["task_count"] == 12
    assert expected["steady_task_count"] > 0
    assert expected["max_worker_completion_gap_ms"] > 0
    assert actual == expected

    for key in (per_task.JOB_RUNTIME_TELEMETRY_KEY, per_task.JOB_RUNTIME_WORKERS_KEY):
        name = key.format(job_id=job_id)
        assert _decoded_hash(await batched._client().hgetall(name)) == _decoded_hash(
            await per_task._client().hgetall(name)
        )
        assert await batched._client().ttl(name) > 0


async def test_batched_telemetry_flushes_on_its_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _storage(monkeypatch, "0.01")
    await storage.record_task_runtime_telemetry(
        "job-interval", **_task(0, "worker-1", completed=None, total=10)
    )
    # Nothing reaches Redis until the flush interval passes.
    assert await storage.get_job_runtime_telemetry("job-interval") is None
    for _ in range(100):
        await asyncio.sleep(0.01)
        telemetry = await storage.get_job_runtime_telemetry("job-interval")
        if telemetry is not None:
            break
    assert telemetry is not None and telemetry["task_count"] == 1
    # The flusher stops once nothing is pending.
    await asyncio.sleep(0.05)
    assert storage._telemetry_batcher._flusher.done()
