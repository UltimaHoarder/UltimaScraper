"""Normal task admission uses durable definitions and bounded Redis windows."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, text

import test_mps_manifest as fixtures
import test_normal_durable_inputs as inputs
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.job_system import Job, JobManager, JobStorage, mps_state

activate_materialized_job = JobManager.activate_materialized_job

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


async def admit(runtime, *, count=8, tasks=None, metadata=None):
    source = Job.create(
        name="Ordinary fixture",
        created_by="fixture",
        tasks=tasks
        if tasks is not None
        else [inputs.task(i, width=10) for i in range(count)],
        metadata=metadata or {},
    )
    config = await jobs._persist_central_job_submission(
        job_id=source.job_id,
        job_type="ordinary_fixture",
        site="onlyfans",
        args_payload={"job_name": source.name, "created_by": source.created_by},
        tasks=source.tasks,
        job_config=source.to_config(include_task_ids=False).to_dict(),
        windowed=True,
    )
    job = Job.from_dict(config)
    await JobManager(runtime.redis).activate_job(job, distributed_mode=True)
    return job


@pytest.mark.parametrize("count", [8, 1000])
async def test_admission_keeps_total_inputs_in_sql_and_only_a_window_in_redis(
    store, window_runtime, monkeypatch, count
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "2")
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "100000")
    job = await admit(window_runtime, count=count)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    assert job.total_tasks == count and job.tasks == [] and job.task_ids == []
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id)) == 0
    with store.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.mps_task_definitions WHERE manifest_id=:manifest"
                ),
                {"manifest": job.metadata["mps_task_manifest"]},
            )
            == count
        )
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"),
                {"job": job.job_id},
            )
            == 0
        )
    await mps_durable.advance(window_runtime, job.job_id)
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id)) == 2
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 2
    assert not await client.exists(mps_state.LEGACY_MPS_BUDGET_KEY)
    # Loss of ephemeral state replays the uncommitted window from SQL, still bounded.
    await client.flushdb()
    await mps_durable.advance(window_runtime, job.job_id)
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id)) == 2
    assert (
        await storage.fetch_job(job.job_id, include_tasks=False)
    ).total_tasks == count


async def test_normal_and_mps_windows_share_capacity_and_release_it_on_completion(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "2")
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "100000")
    first = await admit(window_runtime, count=7)
    second = await admit(window_runtime, tasks=[inputs.task(99, width=10)])
    mps = fixtures.prepare_runtime_plan(store, 5)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await mps_durable.advance(window_runtime, first.job_id)
    await mps_durable.advance(window_runtime, second.job_id)
    assert await client.sismember(mps_state.WAITING_SET_KEY, second.job_id)
    await mps_durable.advance(window_runtime, mps["job_id"])
    assert await client.sismember(mps_state.WAITING_SET_KEY, mps["job_id"])
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=mps["job_id"])) == 0
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 2
    await fixtures.complete_window(storage, first.job_id)
    await mps_durable.advance(window_runtime, first.job_id)
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 0
    assert not await client.sismember(mps_state.WAITING_SET_KEY, second.job_id)
    await mps_durable.advance(window_runtime, second.job_id)
    await mps_durable.advance(window_runtime, mps["job_id"])
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=second.job_id)) == 1
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=mps["job_id"])) == 1
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 2
    await fixtures.complete_window(storage, second.job_id)
    await mps_durable.advance(window_runtime, second.job_id)
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 1
    await fixtures.complete_window(storage, mps["job_id"])
    await mps_durable.advance(window_runtime, mps["job_id"])
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 0
    while store.get(first.job_id)["cursor"] < 7:
        await mps_durable.advance(window_runtime, first.job_id)
        assert (
            await client.zcard(storage.TASK_INDEX_KEY.format(job_id=first.job_id)) <= 2
        )
        await fixtures.complete_window(storage, first.job_id)
        await mps_durable.advance(window_runtime, first.job_id)
    current = await storage.fetch_job(first.job_id, include_tasks=False)
    assert current.state.value == "completed" and current.total_tasks == 7
    assert current.completed_tasks_count == 7
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=first.job_id)) == 0
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 0
    with store.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.job_tasks WHERE job_id=:job AND status='completed'"
                ),
                {"job": first.job_id},
            )
            == 7
        )


async def test_mps_and_normal_windows_share_the_global_byte_budget(
    store, window_runtime, monkeypatch
):
    mps = fixtures.prepare_runtime_plan(store, 5)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await mps_durable.advance(window_runtime, mps["job_id"])
    occupied = int(await client.hget(mps_state.BUDGET_KEY, "bytes"))
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "100")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", str(occupied))
    ordinary = await admit(window_runtime, count=1)
    await mps_durable.advance(window_runtime, ordinary.job_id)
    assert await client.sismember(mps_state.WAITING_SET_KEY, ordinary.job_id)
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=ordinary.job_id)) == 0
    assert int(await client.hget(mps_state.BUDGET_KEY, "bytes")) == occupied
    await fixtures.complete_window(storage, mps["job_id"])
    await mps_durable.advance(window_runtime, mps["job_id"])
    await mps_durable.advance(window_runtime, ordinary.job_id)
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=ordinary.job_id)) == 1
    assert int(await client.hget(mps_state.BUDGET_KEY, "bytes")) <= occupied


@pytest.mark.parametrize("explicit_keys", [False, True])
@pytest.mark.parametrize("bound", ["tasks", "bytes"])
async def test_existing_mps_reservations_drain_before_switching_to_shared_capacity(
    store, window_runtime, monkeypatch, explicit_keys, bound
):
    legacy = fixtures.prepare_runtime_plan(store, 5)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    await mps_durable.advance(window_runtime, legacy["job_id"])
    plan_key = mps_state.PLAN_KEY.format(job_id=legacy["job_id"])
    occupied = int(await client.hget(mps_state.BUDGET_KEY, "bytes"))
    # Reproduce a window reserved by the old producer-specific materializer.
    await client.rename(mps_state.BUDGET_KEY, mps_state.LEGACY_MPS_BUDGET_KEY)
    if explicit_keys:
        await client.hset(plan_key, mapping={
            "window_budget_key": mps_state.LEGACY_MPS_BUDGET_KEY,
            "window_waiting_key": mps_state.LEGACY_MPS_WAITING_KEY,
            "window_waiting_set_key": mps_state.LEGACY_MPS_WAITING_SET_KEY,
        })
    else:
        await client.hdel(
            plan_key, "window_budget_key", "window_waiting_key", "window_waiting_set_key"
        )
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "3" if bound == "tasks" else "100")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", str(occupied) if bound == "bytes" else "100000")
    await mps_durable.advance(window_runtime, legacy["job_id"])
    assert await client.hget(plan_key, "window_budget_key") == mps_state.LEGACY_MPS_BUDGET_KEY.encode()
    ordinary = await admit(window_runtime, count=1)
    await mps_durable.advance(window_runtime, ordinary.job_id)
    assert await client.sismember(mps_state.WAITING_SET_KEY, ordinary.job_id)
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=ordinary.job_id)) == 0
    assert await client.hmget(mps_state.LEGACY_MPS_BUDGET_KEY, "tasks", "bytes") == [b"3", str(occupied).encode()]

    await fixtures.complete_window(storage, legacy["job_id"])
    await mps_durable.advance(window_runtime, legacy["job_id"])
    assert await client.hmget(mps_state.LEGACY_MPS_BUDGET_KEY, "tasks", "bytes") == [b"0", b"0"]
    assert await client.hget(plan_key, "window_budget_key") == mps_state.BUDGET_KEY.encode()
    assert not await client.sismember(mps_state.WAITING_SET_KEY, ordinary.job_id)
    await mps_durable.advance(window_runtime, ordinary.job_id)
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=ordinary.job_id)) == 1
    await fixtures.complete_window(storage, ordinary.job_id)
    await mps_durable.advance(window_runtime, ordinary.job_id)
    await mps_durable.advance(window_runtime, legacy["job_id"])
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 2
    await fixtures.complete_window(storage, legacy["job_id"])
    await mps_durable.advance(window_runtime, legacy["job_id"])
    assert await client.hmget(mps_state.BUDGET_KEY, "tasks", "bytes") == [b"0", b"0"]
    assert store.get(legacy["job_id"])["cursor"] == 5


async def test_dependencies_receive_archived_outputs_across_normal_windows(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    parent, child = inputs.task(1, width=10), inputs.task(2, width=10)
    child.depends_on = [parent.task_id]
    job = await admit(window_runtime, tasks=[child, parent])
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job.job_id)
    tasks = await fixtures.complete_window(storage, job.job_id)
    assert [task.task_id for task in tasks] == [parent.task_id]
    await mps_durable.advance(window_runtime, job.job_id)
    await mps_durable.advance(window_runtime, job.job_id)
    loaded = [task async for task in storage.fetch_tasks_stream(job.job_id)]
    assert [task.task_id for task in loaded] == [child.task_id]
    assert loaded[0].depends_on == [parent.task_id]
    output = await storage._client().hget(
        storage.TASK_OUTPUTS_KEY.format(job_id=job.job_id), parent.task_id
    )
    assert json.loads(output)["items_processed"] == 1


@pytest.mark.parametrize("kind", ["missing", "cycle"])
async def test_invalid_normal_graph_never_becomes_runnable(store, window_runtime, kind):
    one, two = inputs.task(1), inputs.task(2)
    one.depends_on = [two.task_id if kind == "cycle" else "absent"]
    two.depends_on = [one.task_id]
    with pytest.raises(ValueError, match="missing|cycle"):
        await admit(window_runtime, tasks=[one, two])
    assert store.active_page(limit=10) == []
    assert not await window_runtime.redis.client.exists(mps_state.QUEUE_KEY)


async def test_later_admission_batch_failure_rolls_back_plan_and_definitions(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "2")
    batches = []
    with store.session_factory() as session:
        engine = session.get_bind()

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO management.mps_task_definitions"):
            batches.append(len(context.compiled_parameters))
            if len(batches) == 2:
                raise RuntimeError("Fixture admission failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="admission failure"):
            await admit(window_runtime, count=7)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert batches == [2, 2]
    with store.session_factory() as session:
        for table in ("jobs", "mps_plans", "mps_task_definitions"):
            assert session.scalar(text(f"SELECT count(*) FROM management.{table}")) == 0
    assert not await window_runtime.redis.client.exists(mps_state.QUEUE_KEY)


async def test_actual_creation_admits_expanded_tasks_and_preserves_local_target(
    store, window_runtime, monkeypatch
):
    source = inputs.task(0)
    expanded = [inputs.task(i + 10, width=10) for i in range(5)]
    monkeypatch.setattr(
        jobs, "_build_task_from_payload", AsyncMock(return_value=source)
    )
    from ultima_scraper_backend.job_system import job_builder

    monkeypatch.setattr(job_builder, "iter_expanded_tasks", lambda tasks: iter(expanded))
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    window_runtime.distributed_mode = False
    response = await jobs.create_job(
        jobs.CreateJobRequest(
            job_name="Expanded",
            created_by="fixture",
            tasks=[jobs.TaskPayload(task_type="scrape_user", params={})],
        ),
        backend=window_runtime,
        backend_manager=SimpleNamespace(),
    )
    assert response.task_count == response.task_stats.total == 5
    plan = store.get(response.job_id)
    assert plan["total"] == 5
    with store.session_factory() as session:
        ids = (
            session.execute(
                text(
                    "SELECT task_id FROM management.mps_task_definitions WHERE manifest_id=:manifest ORDER BY ordinal"
                ),
                {"manifest": plan["selection"]["task_manifest_id"]},
            )
            .scalars()
            .all()
        )
    assert ids == [task.task_id for task in expanded] and source.task_id not in ids
    await mps_durable.advance(window_runtime, response.job_id)
    JobManager.activate_materialized_job.assert_awaited_once()
    assert JobManager.activate_materialized_job.await_args.kwargs == {
        "distributed_mode": False,
        "backend_id": "test-backend",
    }


async def test_cancelling_a_waiting_normal_job_removes_its_admission_entry(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "1")
    first = await admit(window_runtime, count=2)
    waiting = await admit(window_runtime, tasks=[inputs.task(99, width=10)])
    client = window_runtime.redis.client
    await mps_durable.advance(window_runtime, first.job_id)
    await mps_durable.advance(window_runtime, waiting.job_id)
    assert await client.sismember(mps_state.WAITING_SET_KEY, waiting.job_id)
    manager = JobManager(window_runtime.redis)
    manager.database_writes = window_runtime.writes
    scheduled = []
    monkeypatch.setattr(jobs, "JobManager", lambda _redis: manager)
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    monkeypatch.setattr(
        jobs,
        "_schedule_cancel_cleanup",
        lambda _redis, job_id: scheduled.append(job_id),
    )
    response = await jobs.cancel_job(waiting.job_id, backend=window_runtime)
    assert response["status"] == "cancelled" and scheduled == [waiting.job_id]
    await manager.finalize_job_cancellation(waiting.job_id)
    assert not await client.sismember(
        mps_state.WAITING_SET_KEY, waiting.job_id
    )
    assert waiting.job_id.encode() not in await client.lrange(
        mps_state.WAITING_KEY, 0, -1
    )
    assert int(await client.hget(mps_state.BUDGET_KEY, "tasks")) == 1
    assert store.get(waiting.job_id)["status"] == "cancelled"


@pytest.mark.parametrize(
    "budget", ["ULTIMA_JOB_TASK_INSERT_MAX_BYTES", "ULTIMA_JOB_TASK_INPUT_MAX_BYTES"]
)
async def test_explicit_normal_input_limits_apply_before_plan_publication(
    store, window_runtime, monkeypatch, budget
):
    from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded

    monkeypatch.setenv(budget, "1500")
    with pytest.raises(TaskPayloadBudgetExceeded, match="1500"):
        await admit(window_runtime, tasks=[inputs.task(1, width=10000)])
    assert store.active_page(limit=10) == []
    assert not await window_runtime.redis.client.exists(mps_state.QUEUE_KEY)


async def test_normal_read_rows_can_be_lower_than_the_execution_window(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "5")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_BATCH_SIZE", "2")
    job = await admit(window_runtime, count=7)
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job.job_id)
    assert (
        await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id))
        == 2
    )


async def test_normal_edit_uses_ordinary_input_limits_and_keeps_the_old_definition(
    store, window_runtime, monkeypatch
):
    from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded

    job = await admit(window_runtime)
    manager = JobManager(window_runtime.redis)
    manager.database_writes = window_runtime.writes
    before = store.get(job.job_id)
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_MAX_BYTES", "1500")
    with pytest.raises(TaskPayloadBudgetExceeded, match="1500"):
        await manager.update_job_by_id(job.job_id, tasks=[inputs.task(99, width=10000)])
    after = store.get(job.job_id)
    assert (
        after["selection"] == before["selection"] and after["total"] == before["total"]
    )
    assert (
        await manager.storage.fetch_job(job.job_id, include_tasks=False)
    ).total_tasks == 8


async def test_light_normal_header_preserves_full_job_routing_requirements(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    first, second = inputs.task(1, width=10), inputs.task(2, width=10)
    first.capabilities = ["onlyfans"]
    second.capabilities = ["fansly"]
    first.ip_lock_key = "required-route"
    job = await admit(window_runtime, tasks=[first, second])
    await mps_durable.advance(window_runtime, job.job_id, activate=False)
    manager = JobManager(window_runtime.redis)
    manager.router.enqueue = AsyncMock(return_value="fixture-backend")
    monkeypatch.setattr(
        JobManager, "activate_materialized_job", activate_materialized_job
    )
    await manager.activate_materialized_job(
        job, distributed_mode=False, backend_id="fixture-backend"
    )
    envelope = manager.router.enqueue.await_args.args[0]
    assert envelope.capabilities == ["fansly", "onlyfans"]
    assert envelope.ip_lock_key == "required-route"
    assert job.tasks == [] and job.total_tasks == 2
