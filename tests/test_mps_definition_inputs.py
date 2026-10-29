"""Stored task payloads must fit the read budget before entering Python."""

from __future__ import annotations

import tracemalloc

import pytest
from sqlalchemy import text

import test_mps_replacement_definitions as fixtures
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.job_system import JobStorage, Task, TaskType
from ultima_scraper_backend.job_system import mps_state
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


async def prepared_definitions(store, runtime):
    plan = fixtures.fixtures.prepare_runtime_plan(store, 1_000_000)
    tasks = [
        Task(
            task_type=TaskType.DOWNLOAD,
            site_name="OnlyFans",
            user_id=41 + i,
            payload={"media_ids": [i]},
        )
        for i in range(3)
    ]
    manifest_id = await fixtures.upload(runtime, plan["job_id"], tasks)
    await fixtures.commit(runtime, plan["job_id"], manifest_id, len(tasks))
    storage = JobStorage(runtime.redis)
    await mps_durable.ensure_plan(storage, store.get(plan["job_id"]))
    return plan["job_id"], manifest_id, storage, tasks


@pytest.mark.parametrize("oversized_index", [0, 1])
async def test_wide_download_definition_is_checked_before_transfer(
    store, window_runtime, monkeypatch, record_property, oversized_index
):
    job_id, manifest_id, storage, tasks = await prepared_definitions(
        store, window_runtime
    )
    # A supported download payload containing many explicit media IDs. Generate
    # the large value in SQL so setup allocations are outside the measurement.
    with store.session_factory() as session:
        session.execute(
            text("""
            UPDATE management.mps_task_definitions SET task_json=jsonb_set(
                task_json::jsonb, '{payload,media_ids}',
                (SELECT jsonb_agg(id) FROM generate_series(1,250000) AS ids(id))
            )::text WHERE manifest_id=:manifest AND task_id=:task
        """),
            {"manifest": manifest_id, "task": tasks[oversized_index].task_id},
        )
        session.commit()
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "32768")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", "32768")
    error = None
    tracemalloc.start()
    try:
        try:
            await mps_durable.advance(window_runtime, job_id)
        except ValueError as exc:
            error = exc
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    record_property("definition_admission_traced_peak_bytes", peak)
    assert (
        peak < 2 * 1024 * 1024
    ), f"Definition admission allocated {peak:,} bytes for a 32-KiB window"
    assert store.get(job_id)["status"] == "ready"
    assert store.get(job_id)["total"] == 3
    assert await legacy.list_tasks_for_job(storage, job_id) == [
        task.task_id for task in tasks[:oversized_index]
    ]
    assert (
        int(await storage._client().hget(mps_state.BUDGET_KEY, "bytes") or 0) <= 32768
    )
    if oversized_index == 0:
        assert error is not None and "byte budget" in str(error)
        # Raising explicit budgets permits the same durable task to execute;
        # there is no imposed media-count ceiling or task truncation.
        monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", str(32 * 1024 * 1024))
        monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", str(32 * 1024 * 1024))
        await mps_durable.advance(window_runtime, job_id)
        task = await storage.fetch_task(job_id, tasks[0].task_id)
        assert len(task.payload.media_ids) == 250000
        assert task.payload.media_ids[0] == 1 and task.payload.media_ids[-1] == 250000
    else:
        assert error is None


async def test_ready_page_preserves_exact_byte_prefix_and_retry_marker(
    store, window_runtime
):
    _job_id, manifest_id, _storage, tasks = await prepared_definitions(
        store, window_runtime
    )
    with store.session_factory() as session:
        session.execute(
            text("""
            UPDATE management.mps_task_definitions SET task_json=jsonb_set(
                task_json::jsonb, '{_mps_retry_waiting_for}', 'null'::jsonb
            )::text WHERE manifest_id=:manifest AND ordinal=0
        """),
            {"manifest": manifest_id},
        )
        session.commit()
        sizes = list(
            session.scalars(
                text(
                    "SELECT octet_length(task_json) FROM management.mps_task_definitions WHERE manifest_id=:manifest ORDER BY ordinal"
                ),
                {"manifest": manifest_id},
            )
        )
    rows = store.definitions.ready_page(manifest_id, limit=3, byte_limit=sum(sizes[:2]))
    assert [row["task_id"] for row in rows] == [task.task_id for task in tasks[:2]]
    assert rows[0]["retry_missing_child"] is True
    assert rows[0]["dependency_failed"] is True
    assert rows[1]["dependency_failed"] is False
    fewer = store.definitions.ready_page(
        manifest_id, limit=3, byte_limit=sum(sizes[:2]) - 1
    )
    assert [row["task_id"] for row in fewer] == [tasks[0].task_id]
    assert len(store.definitions.ready_page(manifest_id, limit=3)) == 3


async def test_definition_waits_for_shared_capacity_then_runs(
    store, window_runtime, monkeypatch
):
    first_id, first_manifest, storage, _first_tasks = await prepared_definitions(
        store, window_runtime
    )
    second_id, second_manifest, _storage, second_tasks = await prepared_definitions(
        store, window_runtime
    )
    with store.session_factory() as session:
        for manifest_id, count in ((first_manifest, 2000), (second_manifest, 4000)):
            session.execute(
                text("""
                UPDATE management.mps_task_definitions SET task_json=jsonb_set(
                    task_json::jsonb, '{payload,media_ids}',
                    (SELECT jsonb_agg(id) FROM generate_series(1,CAST(:count AS int)) AS ids(id))
                )::text WHERE manifest_id=:manifest
            """),
                {"manifest": manifest_id, "count": count},
            )
        session.commit()
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "6")
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "32768")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", "32768")
    await mps_durable.advance(window_runtime, first_id)
    used = int(await storage._client().hget(mps_state.BUDGET_KEY, "bytes"))
    assert 16000 < used <= 32768
    assert await mps_durable.advance(window_runtime, second_id) is False
    assert await legacy.list_tasks_for_job(storage, second_id) == []
    assert await storage._client().sismember(mps_state.WAITING_SET_KEY, second_id)
    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "bytes")) == used
    assert store.get(second_id)["status"] == "ready"
    await fixtures.fixtures.complete_window(storage, first_id)
    assert await mps_durable.advance(window_runtime, first_id)
    await mps_durable.advance(window_runtime, second_id)
    assert await legacy.list_tasks_for_job(storage, second_id) == [second_tasks[0].task_id]
    assert not await storage._client().sismember(mps_state.WAITING_SET_KEY, second_id)
    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "bytes")) <= 32768
