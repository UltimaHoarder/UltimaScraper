"""Ordinary completion must retain bounded reads and preserve replacement work."""

import copy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import test_mps_manifest as fixtures
from ultima_scraper_backend.job_system import Job, JobManager, Task, TaskResult
from ultima_scraper_backend.job_system.models import JobState, TaskState, TaskType
from functools import partial

import legacy_redis_runtime as legacy

# These exercise the Redis runtime; the SQL execution ledger holds no runs.
pytestmark = pytest.mark.usefixtures("no_ledger_runs")

redis_manager = fixtures.redis_manager


def manager_for(redis_manager):
    client = redis_manager.client
    manager = JobManager(
        SimpleNamespace(
            client=client, get=client.get, set=client.set, delete=client.delete
        )
    )
    return manager


async def seed(manager, status="completed", count=3, width=10):
    tasks = [
        Task(
            task_type=TaskType.SCRAPE,
            site_name="OnlyFans",
            user_id=i + 1,
            state=TaskState.COMPLETED,
            result=TaskResult(success=True, output={"payload": "x" * width}),
        )
        for i in range(count)
    ]
    job = Job.create(name="Original", created_by="fixture", tasks=tasks)
    job.state = JobState(status)
    job.completed_at = datetime.now(timezone.utc).isoformat()
    job.completed_tasks_count = count
    await manager.storage.persist_job(job, persist_tasks=True)
    await manager.storage.reserve_dedup_many(tasks)
    return job


async def finish(manager, job):
    method = (
        partial(legacy.finalize_job_completion, manager)
        if job.state == JobState.COMPLETED
        else manager.finalize_job_cancellation
    )
    await method(job.job_id)


@pytest.mark.parametrize("status", ["completed", "cancelled"])
async def test_replacement_after_archive_keeps_new_tasks_and_reservations(
    redis_manager, status
):
    manager = manager_for(redis_manager)
    storage, client = manager.storage, redis_manager.client
    job = await seed(manager, status)
    replacement = copy.deepcopy(job)
    replacement.name = "Replacement"
    replacement.metadata["replacement"] = True
    replacement.state = JobState.PENDING
    replacement.completed_at = None
    for task in replacement.tasks:
        task.state = TaskState.PENDING
        task.result = None

    async def archive_then_replace(*args, **kwargs):
        await storage._publish_task_archive_marker(job.job_id, len(job.tasks))
        await storage.persist_job(replacement, persist_tasks=True)
        await storage.reserve_dedup_many(replacement.tasks)
        return {"archived_tasks": len(job.tasks)}

    manager.database_writes = SimpleNamespace(submit=archive_then_replace)
    await finish(manager, job)
    assert (
        await storage.fetch_job(job.job_id, include_tasks=False)
    ).name == "Replacement"
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id)) == len(
        replacement.tasks
    )
    for task in replacement.tasks:
        assert await client.exists(
            storage.TASK_KEY.format(job_id=job.job_id, task_id=task.task_id)
        )
        assert await client.get(storage.DEDUPE_KEY.format(dedup=task.dedup_key)) in (
            task.task_id,
            task.task_id.encode(),
        )


async def test_dedup_release_reads_obey_archive_byte_budget(redis_manager, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_TASK_ARCHIVE_MAX_BYTES", "25000")
    manager = manager_for(redis_manager)
    storage, client = manager.storage, redis_manager.client
    job = await seed(manager, count=21, width=10000)
    mget, evaluate = client.mget, client.eval
    reads = []

    def inspect(values):
        size = sum(len(v.encode() if isinstance(v, str) else v) for v in values if v)
        reads.append(size)
        assert size <= 25000, f"dedup release transferred {size} bytes"

    async def measured_mget(*args, **kwargs):
        values = await mget(*args, **kwargs)
        inspect(values)
        return values

    async def measured_eval(script, key_count, *args):
        value = await evaluate(script, key_count, *args)
        if "STRLEN" in script:
            inspect(value[2])
        return value

    monkeypatch.setattr(client, "mget", measured_mget)
    monkeypatch.setattr(client, "eval", measured_eval)
    await storage.release_dedup_for_job_id(job.job_id)
    assert reads
    for task in job.tasks:
        assert not await client.exists(storage.DEDUPE_KEY.format(dedup=task.dedup_key))
        assert await client.exists(
            storage.TASK_KEY.format(job_id=job.job_id, task_id=task.task_id)
        )


@pytest.mark.parametrize("status", ["completed", "cancelled"])
@pytest.mark.parametrize(
    "phase",
    ["dedup", "state", "dependency", "deferred", "stats", "payload", "index", "marker"],
)
async def test_replacement_survives_every_terminal_cleanup_mutation(
    redis_manager, monkeypatch, status, phase
):
    manager = manager_for(redis_manager)
    storage, client = manager.storage, redis_manager.client
    job = await seed(manager, status)
    task = job.tasks[0]
    keys = {
        "state": storage.TASKS_READY_KEY.format(job_id=job.job_id),
        "stats": storage.JOB_STATE_KEY.format(job_id=job.job_id),
        "config": storage.JOB_CONFIG_KEY.format(job_id=job.job_id),
        "dependency": storage.TASK_DEPENDENTS_KEY.format(
            job_id=job.job_id, task_id=task.task_id
        ),
        "deferred": storage.DEFERRED_TASKS_KEY.format(dedup_key="cleanup-fixture"),
        "payload": storage.TASK_KEY.format(job_id=job.job_id, task_id=task.task_id),
        "dedup": storage.DEDUPE_KEY.format(dedup=task.dedup_key),
        "index": storage.TASK_INDEX_KEY.format(job_id=job.job_id),
        "marker": storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id),
        "completed": storage.TASKS_COMPLETED_KEY.format(job_id=job.job_id),
        "output": storage.TASK_OUTPUTS_KEY.format(job_id=job.job_id),
    }

    async def seed_runtime(label):
        await client.sadd(keys["state"], task.task_id)
        await client.sadd(keys["completed"], *(t.task_id for t in job.tasks))
        await client.sadd(keys["dependency"], "child")
        await client.sadd(
            keys["deferred"], f"{job.job_id}:{task.task_id}", "unrelated:task"
        )
        await client.hset(keys["output"], task.task_id, label)
        await storage.reserve_dedup_many(job.tasks)

    await seed_runtime("original")

    async def archived(*args, **kwargs):
        await storage._publish_task_archive_marker(job.job_id, len(job.tasks))
        return {"archived_tasks": len(job.tasks)}

    manager.database_writes = SimpleNamespace(submit=archived)
    replaced, snapshots = False, {}

    async def replace_if_targeted(operation_keys):
        nonlocal replaced
        operation_keys = [
            v.decode() if isinstance(v, bytes) else v for v in operation_keys
        ]
        if replaced or keys[phase] not in operation_keys:
            return
        replaced = True
        replacement = copy.deepcopy(job)
        replacement.name = "Replacement"
        replacement.state = JobState.PENDING
        replacement.completed_at = None
        replacement.metadata["generation"] = "new"
        for next_task in replacement.tasks:
            next_task.state = TaskState.PENDING
            next_task.result = None
        await storage.persist_job(replacement, persist_tasks=True)
        await seed_runtime("replacement")
        for key in keys.values():
            snapshots[key] = await client.dump(key)

    evaluate, delete, hset, pipeline = (
        client.eval,
        client.delete,
        client.hset,
        client.pipeline,
    )

    async def racing_eval(script, count, *args):
        operation_keys = list(args[:count])
        if "USR_STALE_RETIREMENT" in script:
            operation_keys = operation_keys[3:]
        if any(word in script for word in ("'DEL'", "'ZREM'", "'SREM'", "'HSET'", "'SET'")):
            await replace_if_targeted(operation_keys)
        return await evaluate(script, count, *args)

    async def racing_delete(*args):
        await replace_if_targeted(args)
        return await delete(*args)

    async def racing_hset(key, *args, **kwargs):
        await replace_if_targeted([key])
        return await hset(key, *args, **kwargs)

    def racing_pipeline(*args, **kwargs):
        pipe = pipeline(*args, **kwargs)
        execute = pipe.execute

        async def racing_execute(*execute_args, **execute_kwargs):
            for command, _options in tuple(pipe.command_stack):
                name = (
                    command[0].decode() if isinstance(command[0], bytes) else command[0]
                )
                if name in {"DEL", "ZREM", "SREM", "HSET", "SET"}:
                    await replace_if_targeted(command[1:])
            return await execute(*execute_args, **execute_kwargs)

        pipe.execute = racing_execute
        return pipe

    monkeypatch.setattr(client, "eval", racing_eval)
    monkeypatch.setattr(client, "delete", racing_delete)
    monkeypatch.setattr(client, "hset", racing_hset)
    monkeypatch.setattr(client, "pipeline", racing_pipeline)
    await finish(manager, job)
    assert replaced, f"No injection at {phase}"
    assert (
        await storage.fetch_job(job.job_id, include_tasks=False)
    ).name == "Replacement"
    for key, snapshot in snapshots.items():
        assert (
            await client.dump(key) == snapshot
        ), f"Terminal cleanup changed replacement {key}"


@pytest.mark.parametrize("status", ["completed", "cancelled"])
async def test_terminal_cleanup_keeps_header_and_exact_completion_counts(
    redis_manager, status
):
    manager = manager_for(redis_manager)
    storage, client = manager.storage, redis_manager.client
    job = await seed(manager, status, count=7)
    await client.sadd(
        storage.TASKS_COMPLETED_KEY.format(job_id=job.job_id),
        *(task.task_id for task in job.tasks),
    )

    async def archived(*args, **kwargs):
        await storage._publish_task_archive_marker(job.job_id, len(job.tasks))
        return {"archived_tasks": len(job.tasks)}

    manager.database_writes = SimpleNamespace(submit=archived)
    await finish(manager, job)
    header = await storage.fetch_job(job.job_id, include_tasks=False)
    assert header.state == job.state
    assert header.completed_at == job.completed_at
    stats = await storage.get_job_task_stats(job.job_id)
    assert stats["total"] == stats["completed"] == 7
    assert (
        stats["ready"]
        == stats["blocked"]
        == stats["inflight"]
        == stats["deferred"]
        == 0
    )
    assert await client.zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id)) == 0
    assert await client.exists(
        storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    )
    for task in job.tasks:
        assert not await client.exists(storage.DEDUPE_KEY.format(dedup=task.dedup_key))


async def test_oversized_dedup_input_is_retained_then_released_with_explicit_budget(
    redis_manager, monkeypatch
):
    from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded

    manager = manager_for(redis_manager)
    storage, client = manager.storage, redis_manager.client
    job = await seed(manager, width=10000, count=1)
    monkeypatch.setenv("ULTIMA_JOB_TASK_ARCHIVE_MAX_BYTES", "2000")
    with pytest.raises(TaskPayloadBudgetExceeded):
        await storage.release_dedup_for_job_id(job.job_id)
    key = storage.DEDUPE_KEY.format(dedup=job.tasks[0].dedup_key)
    assert await client.exists(key)
    await storage.release_dedup_for_job_id(job.job_id, batch_size=1, max_bytes=30000)
    assert not await client.exists(key)
    assert await client.exists(
        storage.TASK_KEY.format(job_id=job.job_id, task_id=job.tasks[0].task_id)
    )
