"""Counterexamples to resolve before wiring automatic runtime retention."""

import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import test_job_system as fixtures
from ultima_scraper_backend.job_system import mps_attempt, mps_state
from ultima_scraper_backend.job_system.models import Job, JobState, Task, TaskType
from ultima_scraper_backend.job_system.routing import BackendRouter
from ultima_scraper_backend.job_system.storage import JobStorage

pytestmark = pytest.mark.asyncio
fake_redis = fixtures.fake_redis
storage = fixtures.storage


async def test_retention_does_not_read_every_old_job_id(
    storage, fake_redis, monkeypatch
):
    monkeypatch.setenv("ULTIMA_RECOVERY_SCAN_COUNT", "4")
    now = time.time()
    await fake_redis.zadd(
        storage.JOB_INDEX_KEY, {f"old-job-{i:04d}": now - 86400 for i in range(1000)}
    )
    original = fake_redis.zrangebyscore
    original_rank = fake_redis.zrange
    reads = []

    async def bounded_reply(*args, **kwargs):
        rows = await original(*args, **kwargs)
        reads.append(len(rows))
        assert len(rows) <= 4, f"retention loaded {len(rows)} old job IDs at once"
        return rows

    async def bounded_rank(*args, **kwargs):
        rows = await original_rank(*args, **kwargs)
        reads.append(len(rows))
        assert len(rows) <= 4, f"retention loaded {len(rows)} old job IDs at once"
        return rows

    monkeypatch.setattr(fake_redis, "zrangebyscore", bounded_reply)
    monkeypatch.setattr(fake_redis, "zrange", bounded_rank)
    await storage.cleanup_completed_jobs(60)
    assert reads


async def test_retention_cannot_delete_an_ordinary_replacement_after_archive(
    storage, fake_redis
):
    old = Job.create(name="Old completed job", created_by="fixture", tasks=[])
    old.state = JobState.COMPLETED
    old.completed_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await storage.persist_job(old)
    await fake_redis.zadd(storage.JOB_INDEX_KEY, {old.job_id: time.time() - 86400})
    replacement = Job.create(
        name="Replacement",
        created_by="fixture",
        tasks=[],
        metadata={"fixture_replacement": True},
    )
    replacement.job_id = old.job_id

    async def archive_then_replace(*args, **kwargs):
        await storage.persist_job(replacement)
        return {"archived_tasks": 0}

    storage.database_writes = SimpleNamespace(max_command_bytes=64 * 1024 * 1024, 
        submit=AsyncMock(side_effect=archive_then_replace)
    )
    await storage.cleanup_completed_jobs(60)
    current = await storage.fetch_job(old.job_id, include_tasks=False)
    assert (
        current is not None
    ), "retention deleted a replacement published during archiving"
    assert current.name == "Replacement"
    assert current.state == JobState.PENDING
    assert current.metadata["fixture_replacement"] is True


async def seed_terminal(storage, fake_redis, job_id, *, status="completed"):
    job = Job.create(name=job_id, created_by="fixture", tasks=[])
    job.job_id = job_id
    job.state = JobState(status)
    job.completed_at = "2026-09-01T00:00:00+00:00"
    await storage.persist_job(job)
    await fake_redis.zadd(storage.JOB_INDEX_KEY, {job_id: time.time() - 86400})
    return job


async def test_scan_resumes_past_active_jobs_and_archive_failures(storage, fake_redis):
    calls = []

    async def archive(_operation, payload, **_kwargs):
        calls.append(payload["job_id"])
        if payload["job_id"] == "b-unavailable":
            raise RuntimeError("fixture archive unavailable")
        return {"archived_tasks": 0}

    writer = SimpleNamespace(max_command_bytes=64 * 1024 * 1024, submit=AsyncMock(side_effect=archive))
    for job_id, state in (
        ("a-active", "running"),
        ("b-unavailable", "failed"),
        ("c-completed", "completed"),
        ("d-cancelled", "cancelled"),
    ):
        await seed_terminal(storage, fake_redis, job_id, status=state)
    # Equal scores exercise stable tie ordering as well as a retained prefix.
    await fake_redis.zadd(
        storage.JOB_INDEX_KEY,
        {
            job_id: 1
            for job_id in ("a-active", "b-unavailable", "c-completed", "d-cancelled")
        },
    )
    storage.database_writes = writer
    assert await storage.cleanup_completed_jobs(60, batch_size=2) == 0
    restarted = JobStorage(storage.redis)
    restarted.database_writes = writer
    assert await restarted.cleanup_completed_jobs(60, batch_size=2) == 2
    assert await fake_redis.zrange(storage.JOB_INDEX_KEY, 0, -1) == [
        b"a-active",
        b"b-unavailable",
    ]
    assert calls == ["b-unavailable", "c-completed", "d-cancelled"]
    assert await restarted.cleanup_completed_jobs(60, batch_size=2) == 0
    assert calls[-1] == "b-unavailable"


async def test_removed_page_does_not_skip_the_next_old_jobs(storage, fake_redis):
    await fake_redis.zadd(storage.JOB_INDEX_KEY, {str(i): 1 for i in range(9)})
    counts = [await storage.cleanup_completed_jobs(60, batch_size=2) for _ in range(5)]
    assert counts == [2, 2, 2, 2, 1]
    assert await fake_redis.zcard(storage.JOB_INDEX_KEY) == 0


async def test_rank_scan_wraps_and_preserves_scores_outside_the_age_range(
    storage, fake_redis
):
    future = time.time() + 3600
    await fake_redis.zadd(
        storage.JOB_INDEX_KEY, {"negative": -1, "old": 1, "future": future}
    )
    await fake_redis.set(storage.RETENTION_CURSOR_KEY, 99)
    assert await storage.cleanup_completed_jobs(60, batch_size=2) == 1
    assert await storage.cleanup_completed_jobs(60, batch_size=2) == 0
    assert await fake_redis.get(storage.RETENTION_CURSOR_KEY) == b"0"
    assert await fake_redis.zrange(storage.JOB_INDEX_KEY, 0, -1) == [
        b"negative",
        b"future",
    ]


async def test_orphan_index_repair_is_not_removed_after_snapshot(
    storage, fake_redis, monkeypatch
):
    job_id = "repaired"
    await fake_redis.zadd(storage.JOB_INDEX_KEY, {job_id: 1})
    original = fake_redis.eval
    replacement = Job.create(name="Repaired header", created_by="fixture", tasks=[])
    replacement.job_id = job_id
    repaired = False

    async def repair_before_mutation(script, count, *args):
        nonlocal repaired
        if not repaired and "EXISTS" in script:
            repaired = True
            await storage.persist_job(replacement)
        return await original(script, count, *args)

    monkeypatch.setattr(fake_redis, "eval", repair_before_mutation)
    assert await storage.cleanup_completed_jobs(60) == 0
    assert repaired
    assert (
        await storage.fetch_job(job_id, include_tasks=False)
    ).name == "Repaired header"
    assert await fake_redis.zscore(storage.JOB_INDEX_KEY, job_id) is not None


async def test_partial_header_is_preserved(storage, fake_redis):
    await fake_redis.zadd(storage.JOB_INDEX_KEY, {"partial": 1})
    key = storage.JOB_CONFIG_KEY.format(job_id="partial")
    await fake_redis.set(key, "fixture partial header")
    assert await storage.cleanup_completed_jobs(60) == 0
    assert await fake_redis.zscore(storage.JOB_INDEX_KEY, "partial") == 1
    assert await fake_redis.get(key) == b"fixture partial header"


@pytest.mark.parametrize(
    "phase",
    [
        "routing",
        "assignment",
        "dedup",
        "task_state",
        "dependency",
        "deferred",
        "payload",
        "budget",
        "header",
    ],
)
async def test_replacement_survives_each_retirement_mutation(
    storage,
    fake_redis,
    monkeypatch,
    phase,
):
    old = await seed_terminal(storage, fake_redis, "racing-job")
    task = Task(user_id=7, task_type=TaskType.SCRAPE, site_name="OnlyFans")
    await storage.persist_task(old.job_id, task)
    router = BackendRouter(storage.redis)
    state_key = storage.JOB_STATE_KEY.format(job_id=old.job_id)
    config_key = storage.JOB_CONFIG_KEY.format(job_id=old.job_id)
    ready_key = storage.TASKS_READY_KEY.format(job_id=old.job_id)
    payload_key = storage.TASK_KEY.format(job_id=old.job_id, task_id=task.task_id)
    dependency_key = storage.TASK_DEPENDENTS_KEY.format(
        job_id=old.job_id, task_id=task.task_id
    )
    deferred_key = storage.DEFERRED_TASKS_KEY.format(dedup_key="fixture-deferred")
    dedup_key = storage.DEDUPE_KEY.format(dedup=task.dedup_key)
    envelope_key = router._job_envelope_key(old.job_id)
    claimed_key = router._claimed_jobs_key("stale-backend")
    active_key = router._backend_jobs_key("backend")
    completed_key = storage.TASKS_COMPLETED_KEY.format(job_id=old.job_id)
    output_key = storage.TASK_OUTPUTS_KEY.format(job_id=old.job_id)
    await fake_redis.hset(state_key, "backend_id", "backend")
    # Routing registered the stale backend's load when it claimed the job;
    # retirement repairs claims only for backends it can identify.
    await fake_redis.zadd(router.LOAD_KEY, {"stale-backend": 0})

    async def seed_runtime(label):
        await fake_redis.set(envelope_key, label)
        await fake_redis.lpush(claimed_key, old.job_id)
        await fake_redis.sadd(active_key, old.job_id)
        await fake_redis.set(dedup_key, task.task_id)
        await fake_redis.sadd(ready_key, task.task_id)
        await fake_redis.sadd(completed_key, task.task_id)
        await fake_redis.sadd(dependency_key, "child")
        await fake_redis.sadd(
            deferred_key, f"{old.job_id}:{task.task_id}", "unrelated:task"
        )
        await fake_redis.hset(output_key, task.task_id, label)

    await seed_runtime("old")
    target = {
        "routing": envelope_key,
        "assignment": claimed_key,
        "dedup": dedup_key,
        "task_state": ready_key,
        "dependency": dependency_key,
        "deferred": deferred_key,
        "payload": payload_key,
        "budget": mps_state.BUDGET_KEY,
        "header": config_key,
    }[phase]
    replaced = False
    watched = [
        state_key,
        config_key,
        ready_key,
        payload_key,
        dependency_key,
        deferred_key,
        dedup_key,
        envelope_key,
        claimed_key,
        active_key,
        completed_key,
        output_key,
    ]
    replacement_dump = {}

    async def replace_if_targeted(keys):
        nonlocal replaced
        keys = [key.decode() if isinstance(key, bytes) else key for key in keys]
        if replaced or target not in keys:
            return
        replaced = True
        task.payload = {"version": "replacement"}
        replacement = Job.create(name="Replacement", created_by="fixture", tasks=[task])
        replacement.job_id = old.job_id
        await storage.persist_job(replacement, persist_tasks=True)
        await seed_runtime("replacement")
        for key in watched:
            replacement_dump[key] = await fake_redis.dump(key)

    original_eval, original_delete = fake_redis.eval, fake_redis.delete

    async def racing_eval(script, count, *args):
        keys = list(args[:count])
        if "USR_STALE_RETIREMENT" in script:
            keys = keys[3:]
        await replace_if_targeted(keys)
        return await original_eval(script, count, *args)

    async def racing_delete(*keys):
        await replace_if_targeted(keys)
        return await original_delete(*keys)

    monkeypatch.setattr(fake_redis, "eval", racing_eval)
    monkeypatch.setattr(fake_redis, "delete", racing_delete)
    storage.database_writes = SimpleNamespace(max_command_bytes=64 * 1024 * 1024, 
        submit=AsyncMock(return_value={"archived_tasks": 1})
    )
    assert await storage.cleanup_completed_jobs(60) == 0
    assert replaced, f"fixture never reached the {phase} mutation"
    assert (
        await storage.fetch_job(old.job_id, include_tasks=False)
    ).name == "Replacement"
    for key, saved in replacement_dump.items():
        assert (
            await fake_redis.dump(key) == saved
        ), f"cleanup changed replacement key {key}"


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "updated_at",
        "completed_at",
        "config",
        "index",
        "mps_manifest",
        "mps_task_manifest",
        "backend_id",
    ],
)
async def test_changed_terminal_header_is_preserved(storage, fake_redis, field):
    old = await seed_terminal(storage, fake_redis, "changed")
    state_key = storage.JOB_STATE_KEY.format(job_id=old.job_id)
    if field == "updated_at":
        await fake_redis.hdel(state_key, "completed_at")

    async def archive_then_edit(*args, **kwargs):
        if field == "config":
            await fake_redis.set(
                storage.JOB_CONFIG_KEY.format(job_id=old.job_id), "edited config"
            )
        elif field == "index":
            await fake_redis.zadd(storage.JOB_INDEX_KEY, {old.job_id: time.time()})
        elif field == "mps_manifest":
            await fake_redis.hset(state_key, "mps_manifest", "1")
        elif field in {"mps_task_manifest", "backend_id"}:
            await fake_redis.hset(state_key, field, "replacement")
        else:
            await fake_redis.hset(
                state_key,
                field,
                "cancelled" if field == "status" else "2026-09-06T00:00:00Z",
            )
        return {"archived_tasks": 0}

    storage.database_writes = SimpleNamespace(max_command_bytes=64 * 1024 * 1024, 
        submit=AsyncMock(side_effect=archive_then_edit)
    )
    assert await storage.cleanup_completed_jobs(60) == 0
    assert await fake_redis.exists(state_key)


async def test_missing_completion_time_can_retire_using_update_time(
    storage, fake_redis
):
    old = await seed_terminal(storage, fake_redis, "no-completion", status="failed")
    await fake_redis.hdel(
        storage.JOB_STATE_KEY.format(job_id=old.job_id), "completed_at"
    )
    await fake_redis.hset(storage.JOB_STATE_KEY.format(job_id=old.job_id), "updated_at", old.completed_at)
    storage.database_writes = SimpleNamespace(max_command_bytes=64 * 1024 * 1024, 
        submit=AsyncMock(return_value={"archived_tasks": 0})
    )
    assert await storage.cleanup_completed_jobs(60) == 1
    assert await storage.fetch_job(old.job_id, include_tasks=False) is None


@pytest.mark.parametrize("changed", [False, True])
async def test_retirement_composes_with_mps_definition_guard(
    storage, fake_redis, changed
):
    old = await seed_terminal(storage, fake_redis, "mps")
    state_key = storage.JOB_STATE_KEY.format(job_id=old.job_id)
    await fake_redis.hset(
        state_key,
        mapping={
            "mps_manifest": 1,
            "mps_task_manifest": "original",
            "backend_id": "backend",
        },
    )
    router = BackendRouter(storage.redis)
    await fake_redis.lpush(router.UNCLAIMED_JOBS_KEY, old.job_id)
    await fake_redis.lpush(router._claimed_jobs_key("backend"), old.job_id)
    await fake_redis.sadd(router._backend_jobs_key("backend"), old.job_id)
    await fake_redis.zadd(router._queue_key("backend"), {f"{old.job_id}:task": 1})

    async def archive(*args, **kwargs):
        if changed:
            await fake_redis.hset(state_key, "mps_task_manifest", "replacement")
        return {"archived_tasks": 0}

    storage.database_writes = SimpleNamespace(max_command_bytes=64 * 1024 * 1024, submit=AsyncMock(side_effect=archive))
    assert await storage.cleanup_completed_jobs(60) == (0 if changed else 1)
    assert bool(await fake_redis.exists(state_key)) == changed
    assert (
        bool(
            await fake_redis.sismember(router._backend_jobs_key("backend"), old.job_id)
        )
        == changed
    )
    assert bool(await fake_redis.zcard(router._queue_key("backend"))) == changed
    assert mps_attempt.current() is None


async def test_ordinary_header_is_published_atomically(
    storage, fake_redis, monkeypatch
):
    old = await seed_terminal(storage, fake_redis, "atomic")
    replacement = Job.create(name="Replacement", created_by="fixture", tasks=[])
    replacement.job_id = old.job_id
    original_pipeline = fake_redis.pipeline
    original_set, original_hset = fake_redis.set, fake_redis.hset
    observed = []

    async def observe_header():
        state = await fake_redis.hget(
            storage.JOB_STATE_KEY.format(job_id=old.job_id), "status"
        )
        config = json.loads(
            await fake_redis.get(storage.JOB_CONFIG_KEY.format(job_id=old.job_id))
        )
        observed.append((state, config["name"]))

    async def observed_set(*args, **kwargs):
        result = await original_set(*args, **kwargs)
        await observe_header()
        return result

    async def observed_hset(*args, **kwargs):
        result = await original_hset(*args, **kwargs)
        await observe_header()
        return result

    def pipeline(*args, **kwargs):
        pipe = original_pipeline(*args, **kwargs)
        execute = pipe.execute

        async def observe_execute(*args, **kwargs):
            await observe_header()
            result = await execute(*args, **kwargs)
            await observe_header()
            return result

        pipe.execute = observe_execute
        return pipe

    monkeypatch.setattr(fake_redis, "pipeline", pipeline)
    monkeypatch.setattr(fake_redis, "set", observed_set)
    monkeypatch.setattr(fake_redis, "hset", observed_hset)
    original_eval = fake_redis.eval

    async def observed_eval(*args, **kwargs):
        await observe_header()
        result = await original_eval(*args, **kwargs)
        await observe_header()
        return result

    monkeypatch.setattr(fake_redis, "eval", observed_eval)
    await storage.persist_job(replacement)
    assert observed
    assert set(observed) <= {(b"completed", "atomic"), (b"pending", "Replacement")}
    current = await storage.fetch_job(old.job_id, include_tasks=False)
    assert current.name == "Replacement"
    assert current.state == JobState.PENDING


async def test_explicit_page_size_remains_authoritative(
    storage, fake_redis, monkeypatch
):
    monkeypatch.setenv("ULTIMA_RECOVERY_SCAN_COUNT", "1")
    await fake_redis.zadd(storage.JOB_INDEX_KEY, {str(i): 1 for i in range(6)})
    assert await storage.cleanup_completed_jobs(60, batch_size=3) == 3


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "4"])
async def test_invalid_page_size_fails_without_removing_work(
    storage, fake_redis, value
):
    await fake_redis.zadd(storage.JOB_INDEX_KEY, {"old": 1})
    with pytest.raises(ValueError, match="positive integer"):
        await storage.cleanup_completed_jobs(60, batch_size=value)
    assert await fake_redis.zcard(storage.JOB_INDEX_KEY) == 1


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
async def test_old_job_keeps_full_retention_after_finishing(storage, fake_redis, status):
    job = await seed_terminal(storage, fake_redis, "old-running-job", status=status)
    state_key = storage.JOB_STATE_KEY.format(job_id=job.job_id)
    await fake_redis.hset(state_key, "completed_at", datetime.now(timezone.utc).isoformat())
    storage.database_writes = SimpleNamespace(max_command_bytes=64 * 1024 * 1024,
        submit=AsyncMock(return_value={"archived_tasks": 0}))
    assert await storage.cleanup_completed_jobs(60) == 0
    storage.database_writes.submit.assert_not_awaited()
    assert await fake_redis.exists(state_key)


@pytest.mark.parametrize("value", ["not-a-date", "", "999999-01-01", "2026-02-30T12:00:00Z"])
async def test_unverifiable_completion_time_is_retained(storage, fake_redis, value):
    job = await seed_terminal(storage, fake_redis, "invalid-time")
    await fake_redis.hset(storage.JOB_STATE_KEY.format(job_id=job.job_id), mapping={"completed_at": value, "updated_at": value})
    storage.database_writes = SimpleNamespace(max_command_bytes=64 * 1024 * 1024, submit=AsyncMock())
    assert await storage.cleanup_completed_jobs(60) == 0
    storage.database_writes.submit.assert_not_awaited()


@pytest.mark.parametrize("value", [-1, True, 0.5, "60"])
async def test_invalid_retention_age_fails_without_access(storage, fake_redis, monkeypatch, value):
    called = AsyncMock(side_effect=AssertionError("Redis should not be accessed"))
    monkeypatch.setattr(fake_redis, "get", called)
    with pytest.raises(ValueError, match="non-negative integer"):
        await storage.cleanup_completed_jobs(value)
    called.assert_not_awaited()


@pytest.mark.parametrize("field", ["total_tasks", "completed_tasks", "failed_tasks", "started_at", "updated_at"])
async def test_final_counter_or_timestamp_change_keeps_header(storage, fake_redis, field):
    job = await seed_terminal(storage, fake_redis, "late-telemetry")
    async def archive(*args, **kwargs):
        await fake_redis.hset(storage.JOB_STATE_KEY.format(job_id=job.job_id), field, "987" if field.endswith("tasks") else "2026-09-08T00:00:00Z")
        return {"archived_tasks": 0}
    storage.database_writes = SimpleNamespace(max_command_bytes=64 * 1024 * 1024, submit=AsyncMock(side_effect=archive))
    assert await storage.cleanup_completed_jobs(0) == 0
    assert await fake_redis.exists(storage.JOB_STATE_KEY.format(job_id=job.job_id))
