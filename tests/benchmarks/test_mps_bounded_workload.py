"""100-profile lifecycle benchmark with simulated work and owned SQL/Redis.

This measures durable planning, task-state transitions, archival and window
reclamation. Profile execution and routing are substituted by the shared fixture;
it is not a network/scraping throughput or whole-deployment memory benchmark.
Numbers below are fixture inputs, never runtime defaults or job-size limits.
"""

from __future__ import annotations

import time
import tracemalloc

from sqlalchemy import text

from test_mps_manifest import (
    complete_window,
    postgres_engine,
    prepare_runtime_plan,
    redis_manager,
    store,
    window_runtime,
)
from ultima_scraper_api import ContentType
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.job_system import JobStorage, TaskType

__all__ = ["postgres_engine", "redis_manager", "store", "window_runtime"]

PROFILE_COUNT = 100
WINDOW_TASKS = 10
WINDOW_BYTES = 65_536


async def test_100_profiles_complete_in_reclaimed_windows(
    store, window_runtime, monkeypatch, request, record_property
):
    for name, value in {
        "ULTIMA_JOB_WINDOW_MAX_TASKS": WINDOW_TASKS,
        "ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS": WINDOW_TASKS,
        "ULTIMA_JOB_WINDOW_MAX_BYTES": WINDOW_BYTES,
        "ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES": WINDOW_BYTES,
    }.items():
        monkeypatch.setenv(name, str(value))

    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    native_redis = request.node.callspec.params["redis_manager"] == "real"
    maximum_live_tasks = 0
    maximum_redis_bytes = 0
    maximum_redis_keys = 0
    completed_ids = set()
    windows = 0
    started = time.perf_counter()
    tracemalloc.start()
    try:
        plan = prepare_runtime_plan(store, PROFILE_COUNT)
        job_id = plan["job_id"]
        index_key = storage.TASK_INDEX_KEY.format(job_id=job_id)
        await mps_durable.advance(window_runtime, job_id)
        while len(completed_ids) < PROFILE_COUNT:
            live = await client.zcard(index_key)
            assert 0 < live <= WINDOW_TASKS
            maximum_live_tasks = max(maximum_live_tasks, live)
            maximum_redis_keys = max(maximum_redis_keys, await client.dbsize())
            if native_redis:
                memory = await client.info("memory")
                maximum_redis_bytes = max(maximum_redis_bytes, memory["used_memory"])

            tasks = await complete_window(storage, job_id)
            assert len(tasks) == live
            assert all(
                task.task_type == TaskType.SCRAPE
                and task.content_type == ContentType.PROFILE
                for task in tasks
            )
            profile_ids = {task.user_id for task in tasks}
            assert len(profile_ids) == len(tasks)
            assert not completed_ids.intersection(profile_ids)
            completed_ids.update(profile_ids)
            windows += 1

            if await mps_durable.advance(window_runtime, job_id):
                await mps_durable.advance(window_runtime, job_id)
            assert store.get(job_id)["cursor"] == len(completed_ids)
            stats = await storage.get_job_task_stats(job_id)
            assert stats["completed"] == len(completed_ids)
            assert stats["total"] == PROFILE_COUNT
            for task in tasks:
                assert not await client.exists(
                    storage.TASK_KEY.format(job_id=job_id, task_id=task.task_id)
                )

        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert completed_ids == set(range(1, PROFILE_COUNT + 1))
    assert windows == PROFILE_COUNT // WINDOW_TASKS
    assert store.get(job_id)["status"] == "complete"
    assert await client.zcard(index_key) == 0
    with store.session_factory() as session:
        archived = session.execute(
            text("SELECT count(*) FROM management.job_tasks WHERE job_id = :id"),
            {"id": job_id},
        ).scalar_one()
        ranges = session.execute(
            text(
                "SELECT count(*) FROM management.mps_candidate_ranges WHERE job_id = :id"
            ),
            {"id": job_id},
        ).scalar_one()
    assert archived == PROFILE_COUNT
    assert ranges == 1

    for name, value in {
        "logical_profiles": PROFILE_COUNT,
        "verified_profiles": len(completed_ids),
        "archived_tasks": archived,
        "durable_range_rows": ranges,
        "windows": windows,
        "maximum_live_tasks": maximum_live_tasks,
        "final_live_tasks": await client.zcard(index_key),
        "maximum_sampled_redis_keys": maximum_redis_keys,
        "maximum_sampled_redis_bytes": maximum_redis_bytes if native_redis else "unmeasured",
        "python_traced_peak_bytes": peak,
        "instrumented_lifecycle_seconds": elapsed,
        "profile_execution": "simulated successful results",
        "writer_transport": "direct production executor with serialized commands",
        "redis": "native" if native_redis else "fake",
    }.items():
        record_property(name, value)
