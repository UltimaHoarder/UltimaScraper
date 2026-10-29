"""MPS admission must bound SQL payload transfers as well as Redis publication."""

from __future__ import annotations

import asyncio
import json
import tracemalloc

import pytest
from redis.exceptions import WatchError
from sqlalchemy import text

import test_mps_job_edits as fixtures
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.job_system import Job, JobStorage, Task, TaskType
from ultima_scraper_backend.job_system import mps_state
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


async def archived_parents(store, runtime, *, count=3):
    plan, storage, manager = await fixtures.prepared_window(
        store, runtime, archived=False
    )
    parents = [
        Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=i + 40)
        for i in range(count)
    ]
    children = [
        Task(
            task_type=TaskType.DOWNLOAD,
            site_name="OnlyFans",
            user_id=p.user_id,
            depends_on=[p.task_id],
        )
        for p in parents
    ]
    await manager.update_job_by_id(plan["job_id"], tasks=[*parents, *children])
    await fixtures.fixtures.complete_window(storage, plan["job_id"])
    assert await mps_durable.advance(runtime, plan["job_id"])
    return plan["job_id"], storage, parents, children


@pytest.mark.parametrize("large_field", ["output", "message"])
async def test_large_archived_fields_do_not_enter_python_before_admission(
    store, window_runtime, monkeypatch, record_property, large_field
):
    job_id, storage, _parents, children = await archived_parents(store, window_runtime)
    # Populate large archive records entirely inside this private SQL fixture.
    # Setup allocations do not contaminate the materializer measurement.
    with store.session_factory() as session:
        session.execute(
            text("""
            UPDATE management.job_tasks SET result_json=json_build_object(
                'success', true,
                'message', CASE WHEN :field='message' THEN repeat('x', :size) ELSE '' END,
                'output', json_build_object('data', CASE WHEN :field='output' THEN repeat('x', :size) ELSE 'small' END)
            )::text WHERE job_id=:job
        """),
            {"job": job_id, "field": large_field, "size": 8 * 1024 * 1024},
        )
        session.commit()
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "32768")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", "32768")
    tracemalloc.start()
    try:
        if large_field == "output":
            with pytest.raises(ValueError, match="dependency output"):
                await mps_durable.advance(window_runtime, job_id)
        else:
            await mps_durable.advance(window_runtime, job_id)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    record_property("materializer_traced_peak_bytes", peak)
    assert (
        peak < 2 * 1024 * 1024
    ), f"Admission allocated {peak:,} bytes for a 32-KiB window"
    assert (
        int(await storage._client().hget(mps_state.BUDGET_KEY, "bytes") or 0) <= 32768
    )
    ids = await legacy.list_tasks_for_job(storage, job_id)
    assert ids == (
        [] if large_field == "output" else [task.task_id for task in children]
    )


@pytest.mark.parametrize("limiting_budget", ["tasks", "bytes"])
async def test_simultaneous_jobs_cannot_overspend_shared_budget(
    store, window_runtime, monkeypatch, limiting_budget
):
    plans = []
    for start in (1, 1_000_001):
        job = Job.create(
            name="Concurrent admission",
            created_by="tests",
            tasks=[],
            metadata={"site": "onlyfans", "mps_manifest": True},
        )
        plans.append(
            store.create(
                job_id=job.job_id,
                site="onlyfans",
                job_config=job.to_dict(),
                selection={"start_id": start, "end_id": start + 999_999},
                proxy_pool=[],
                site_session_factory=store.session_factory,
            )
        )
    storage = JobStorage(window_runtime.redis)
    if limiting_budget == "bytes":
        # Derive this fixture's byte cap from a real admitted window. Two such
        # windows fit the task cap but cannot both fit 1.5 windows' bytes.
        await mps_durable.advance(window_runtime, plans[0]["job_id"])
        used = int(await storage._client().hget(mps_state.BUDGET_KEY, "bytes"))
        await storage.delete_job(plans[0]["job_id"])
        monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "6")
        monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", str(used * 3 // 2))
        byte_cap = used * 3 // 2
    else:
        byte_cap = 100_000
    reserve = JobStorage.reserve_dedup_many
    arrived = []
    ready = asyncio.Event()

    async def collide(self, tasks, *args, **kwargs):
        result = await reserve(self, tasks, *args, **kwargs)
        arrived.append(result)
        if len(arrived) == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 5)
        return result

    with monkeypatch.context() as competing:
        competing.setattr(JobStorage, "reserve_dedup_many", collide)
        results = await asyncio.wait_for(
            asyncio.gather(
                *(
                    mps_durable.advance(window_runtime, plan["job_id"])
                    for plan in plans
                ),
                return_exceptions=True,
            ),
            10,
        )
    assert sum(isinstance(result, WatchError) for result in results) == 1
    assert all(
        not isinstance(result, BaseException) or isinstance(result, WatchError)
        for result in results
    )
    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "tasks")) == 3

    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "bytes")) <= byte_cap
    counts = [
        await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=p["job_id"]))
        for p in plans
    ]
    assert sorted(counts) == [0, 3]
    winner, loser = (plans[counts.index(n)] for n in (3, 0))
    assert store.get(loser["job_id"])["status"] == "ready"
    await fixtures.fixtures.complete_window(storage, winner["job_id"])
    assert await mps_durable.advance(window_runtime, winner["job_id"])
    await mps_durable.advance(window_runtime, loser["job_id"])
    assert (
        await storage._client().zcard(
            storage.TASK_INDEX_KEY.format(job_id=loser["job_id"])
        )
        == 3
    )
    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "tasks")) == 3


async def test_dependency_transfer_checks_growth_after_preflight(
    store, window_runtime, monkeypatch
):
    job_id, storage, parents, _children = await archived_parents(store, window_runtime)
    sizes = store.archived_output_sizes

    def change_after_size_check(*args):
        result = sizes(*args)
        with store.session_factory() as session:
            session.execute(
                text("""
                UPDATE management.job_tasks SET result_json=json_build_object(
                    'output', repeat('x', 8388608)
                )::text WHERE task_id=:task
            """),
                {"task": parents[0].task_id},
            )
            session.commit()
        return result

    monkeypatch.setattr(store, "archived_output_sizes", change_after_size_check)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "32768")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", "32768")
    tracemalloc.start()
    try:
        with pytest.raises(RuntimeError, match="admission byte budget"):
            await mps_durable.advance(window_runtime, job_id)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2 * 1024 * 1024
    assert await legacy.list_tasks_for_job(storage, job_id) == []
    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "tasks") or 0) == 0


async def test_output_transfer_preserves_json_and_enforces_total_bytes(
    store, window_runtime
):
    job_id, _storage, parents, _children = await archived_parents(store, window_runtime)
    values = [None, "£🐈", {"nested": [1, True, "text"]}]
    with store.session_factory() as session:
        for parent, value in zip(parents, values, strict=True):
            session.execute(
                text(
                    "UPDATE management.job_tasks SET result_json=:result WHERE task_id=:task"
                ),
                {
                    "task": parent.task_id,
                    "result": json.dumps(
                        {"output": value, "message": "excluded"}, ensure_ascii=False
                    ),
                },
            )
        session.commit()
    ids = [parent.task_id for parent in parents]
    sizes = store.archived_output_sizes(job_id, ids)
    exact_limit = sum(len(key.encode()) + size for key, size in sizes.items())
    outputs = store.archived_outputs(job_id, ids, byte_limit=exact_limit)
    assert [json.loads(outputs[key]) for key in ids] == values
    assert (
        sum(len(key.encode()) + len(value.encode()) for key, value in outputs.items())
        == exact_limit
    )
    with pytest.raises(RuntimeError, match="admission byte budget"):
        store.archived_outputs(job_id, ids, byte_limit=exact_limit - 1)
    assert store.archived_outputs("unrelated-job", ids, byte_limit=exact_limit) == {}
    assert store.archived_outputs(job_id, [], byte_limit=0) == {}


async def test_only_retained_dependency_outputs_are_loaded(
    store, window_runtime, monkeypatch
):
    job_id, storage, parents, children = await archived_parents(store, window_runtime)
    with store.session_factory() as session:
        session.execute(
            text("""
            UPDATE management.job_tasks SET result_json=json_build_object(
                'output', repeat('x', 30000)
            )::text WHERE job_id=:job
        """),
            {"job": job_id},
        )
        session.commit()
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "32768")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", "32768")
    loaded = []
    fetch = store.archived_outputs

    def record(job, ids, **kwargs):
        loaded.extend(ids)
        return fetch(job, ids, **kwargs)

    monkeypatch.setattr(store, "archived_outputs", record)
    await mps_durable.advance(window_runtime, job_id)
    assert loaded == [parents[0].task_id]
    assert await legacy.list_tasks_for_job(storage, job_id) == [children[0].task_id]
    assert await storage.get_task_output(job_id, parents[0].task_id) == "x" * 30000
