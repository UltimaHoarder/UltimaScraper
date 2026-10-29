"""Aggregate dispatch capacity applies to every notification producer."""

import asyncio
from types import SimpleNamespace

import fakeredis.aioredis
import pytest

from ultima_scraper_backend.job_system import JobStorage, materializer, mps_state


QUEUES = (
    mps_state.QUEUE_KEY,
    mps_state.PROCESSING_KEY,
    mps_state.LEGACY_MPS_WAITING_KEY,
    mps_state.WAITING_KEY,
)


async def queue_totals(client):
    rows = [await client.lrange(key, 0, -1) for key in QUEUES]
    return sum(map(len, rows)), sum(len(value) for row in rows for value in row)


@pytest.mark.parametrize("logical_jobs", [100, 1_000_000])
@pytest.mark.parametrize("bound", ["count", "bytes"])
async def test_concurrent_publishers_share_the_aggregate_bound(monkeypatch, logical_jobs, bound):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", "3" if bound == "count" else "100")
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_BYTES", str((100 if bound == "count" else 3) * 512))
    # Sample the first, middle and final logical IDs. No logical-size array or
    # iteration is available to either producer or recovery.
    ids = [f"job-{i}" for start in (0, logical_jobs // 2, logical_jobs - 7) for i in range(start, start + 7)]
    async with fakeredis.aioredis.FakeRedis() as client:
        await asyncio.gather(*(mps_state.schedule(client, job_id) for job_id in ids))
        assert (await queue_totals(client))[0] == 3
        members = await client.smembers(mps_state.SCHEDULED_KEY)
        assert len(members) == 3
        assert set(await client.lrange(mps_state.QUEUE_KEY, 0, -1)) == members
        await asyncio.gather(*(mps_state.schedule(client, job_id) for job_id in ids))
        assert (await queue_totals(client))[0] == 3
        assert await client.scard(mps_state.SCHEDULED_KEY) == 3


async def test_maximum_utf8_identifiers_obey_the_byte_reservation(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", "100")
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_BYTES", "1536")
    async with fakeredis.aioredis.FakeRedis() as client:
        for index in range(10):
            await mps_state.schedule(client, chr(0x1F600 + index) * 64)
        assert await queue_totals(client) == (3, 768)
        assert sum(map(len, await client.smembers(mps_state.SCHEDULED_KEY))) == 768
        assert not await mps_state.schedule(client, "x" * 257)
        assert not await client.sismember(mps_state.SCHEDULED_KEY, "x" * 257)


async def test_processing_and_both_resource_scopes_share_capacity(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", "3")
    async with fakeredis.aioredis.FakeRedis() as client:
        await mps_state.schedule(client, "processing")
        await client.rpoplpush(mps_state.QUEUE_KEY, mps_state.PROCESSING_KEY)
        await client.srem(mps_state.SCHEDULED_KEY, "processing")
        for job_id, scope in (("ordinary", "ordinary"), ("generated", "mps")):
            await client.hset(mps_state.PLAN_KEY.format(job_id=job_id), "window_class", scope)
            await mps_state.wait_for_budget(client, job_id)
        assert (await queue_totals(client))[0] == 3
        await mps_state.wait_for_budget(client, "overflow")
        assert not await client.sismember(mps_state.LEGACY_MPS_WAITING_SET_KEY, "overflow")
        assert not await mps_state.schedule(client, "overflow")
        assert not await client.sismember(mps_state.SCHEDULED_KEY, "overflow")
        assert (await queue_totals(client))[0] == 3

        # Moving a stale processing entry does not create an admission slot.
        runtime = SimpleNamespace(redis=SimpleNamespace(client=client))
        await materializer._recover_stale_mps_materializations(runtime)
        assert (await queue_totals(client))[0] == 3
        assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [b"processing"]


async def test_completion_can_be_reoffered_after_notification_saturation(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", "1")
    async with fakeredis.aioredis.FakeRedis() as client:
        storage = JobStorage(SimpleNamespace(client=client))
        await client.hset(storage.JOB_STATE_KEY.format(job_id="done"), mapping={
            "mps_manifest": 1, "status": "running", "mps_window_end": 1,
        })
        await client.sadd(storage.TASKS_COMPLETED_KEY.format(job_id="done"), "task")
        await mps_state.schedule(client, "busy")
        await mps_state.notify_complete(storage, "done")
        assert not await client.sismember(mps_state.SCHEDULED_KEY, "done")
        await client.rpop(mps_state.QUEUE_KEY)
        await client.srem(mps_state.SCHEDULED_KEY, "busy")
        await mps_state.notify_complete(storage, "done")
        assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [b"done"]
        assert await client.sismember(mps_state.SCHEDULED_KEY, "done")


@pytest.mark.parametrize("capacity", [1, 3])
async def test_waiters_leave_capacity_for_durable_recovery(monkeypatch, capacity):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", str(capacity))
    async with fakeredis.aioredis.FakeRedis() as client:
        for index in range(20):
            await mps_state.wait_for_budget(client, f"waiting-{index}")
        assert (await queue_totals(client))[0] == capacity - 1
        assert await mps_state.schedule(client, "recovered")
        assert (await queue_totals(client))[0] == capacity


async def test_budget_release_moves_one_waiter_without_growing_aggregate_state(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", "2")
    async with fakeredis.aioredis.FakeRedis() as client:
        await mps_state.wait_for_budget(client, "next")
        await mps_state.schedule(client, "busy")
        await client.hset(mps_state.PLAN_KEY.format(job_id="owner"), mapping={
            "reserved_tasks": 1, "reserved_bytes": 100,
        })
        await client.hset(mps_state.LEGACY_MPS_BUDGET_KEY, mapping={"tasks": 1, "bytes": 100})
        await mps_state.release_budget(client, "owner")
        assert (await queue_totals(client))[0] == 2
        assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [b"next", b"busy"]
        assert not await client.sismember(mps_state.LEGACY_MPS_WAITING_SET_KEY, "next")
        assert await client.hmget(mps_state.LEGACY_MPS_BUDGET_KEY, "tasks", "bytes") == [b"0", b"0"]


async def test_recovery_rechecks_ownership_in_the_atomic_transfer(monkeypatch):
    async with fakeredis.aioredis.FakeRedis() as client:
        await client.lpush(mps_state.PROCESSING_KEY, "owned")
        original = client.exists

        async def acquired_after_read(key):
            before = await original(key)
            await client.set(key, "new-owner")
            return before

        monkeypatch.setattr(client, "exists", acquired_after_read)
        runtime = SimpleNamespace(redis=SimpleNamespace(client=client))
        await materializer._recover_stale_mps_materializations(runtime)
        assert await client.lrange(mps_state.PROCESSING_KEY, 0, -1) == [b"owned"]
        assert not await client.llen(mps_state.QUEUE_KEY)


async def test_acknowledgement_reuses_one_slot_and_is_idempotent(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", "1")
    async with fakeredis.aioredis.FakeRedis() as client:
        await mps_state.schedule(client, "continuing")
        await client.rpoplpush(mps_state.QUEUE_KEY, mps_state.PROCESSING_KEY)
        await client.srem(mps_state.SCHEDULED_KEY, "continuing")
        await mps_state.acknowledge(client, "continuing", again=True)
        assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [b"continuing"]
        assert (await queue_totals(client))[0] == 1
        await mps_state.acknowledge(client, "continuing", again=True)
        assert (await queue_totals(client))[0] == 1
        assert await client.scard(mps_state.SCHEDULED_KEY) == 1


async def test_acknowledgement_does_not_duplicate_an_existing_wakeup(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", "2")
    async with fakeredis.aioredis.FakeRedis() as client:
        await client.lpush(mps_state.PROCESSING_KEY, "continuing")
        await mps_state.schedule(client, "continuing")
        await mps_state.acknowledge(client, "continuing", again=True)
        assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [b"continuing"]
        assert (await queue_totals(client))[0] == 1


async def test_continuing_job_requeues_behind_the_older_budget_waiter(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", "2")
    async with fakeredis.aioredis.FakeRedis() as client:
        await client.lpush(mps_state.PROCESSING_KEY, "owner")
        await mps_state.wait_for_budget(client, "next")
        await client.hset(mps_state.PLAN_KEY.format(job_id="owner"), mapping={
            "reserved_tasks": 1, "reserved_bytes": 100,
        })
        await client.hset(mps_state.LEGACY_MPS_BUDGET_KEY, mapping={"tasks": 1, "bytes": 100})
        await mps_state.release_budget(client, "owner")
        await mps_state.acknowledge(client, "owner", again=True)
        assert (await queue_totals(client))[0] == 2
        assert await client.rpop(mps_state.QUEUE_KEY) == b"next"
        assert await client.rpop(mps_state.QUEUE_KEY) == b"owner"


async def test_notifications_during_lease_coalesce_and_acknowledgement_reoffers(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", "1")
    async with fakeredis.aioredis.FakeRedis() as client:
        job_id = "leased"
        plan = mps_state.PLAN_KEY.format(job_id=job_id)
        await client.hset(plan, "version", mps_state.PLAN_VERSION)
        assert await mps_state.schedule(client, job_id)
        await client.rpoplpush(mps_state.QUEUE_KEY, mps_state.PROCESSING_KEY)
        await client.srem(mps_state.SCHEDULED_KEY, job_id)
        await client.set(plan + ":lock", "owner", ex=60)
        results = await asyncio.gather(*(mps_state.schedule(client, job_id) for _ in range(100)))
        assert not any(results)
        assert await client.llen(mps_state.QUEUE_KEY) == 0
        assert await client.hget(plan, "notification_pending") == b"1"
        await client.delete(plan + ":lock")
        await mps_state.acknowledge(client, job_id)
        assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [b"leased"]
        assert await client.hget(plan, "notification_pending") is None
        await mps_state.acknowledge(client, job_id)
        assert await client.llen(mps_state.QUEUE_KEY) == 1


async def test_pending_notification_survives_busy_ack_and_owner_loss():
    async with fakeredis.aioredis.FakeRedis() as client:
        plan = mps_state.PLAN_KEY.format(job_id="crashed")
        await client.hset(plan, "version", mps_state.PLAN_VERSION)
        await client.set(plan + ":lock", "owner")
        await client.lpush(mps_state.PROCESSING_KEY, "crashed")
        assert not await mps_state.schedule(client, "crashed")
        await mps_state.acknowledge(client, "crashed")
        assert await client.llen(mps_state.QUEUE_KEY) == 0
        assert await client.hget(plan, "notification_pending") == b"1"
        await client.delete(plan + ":lock")  # Expired/crashed owner.
        assert await mps_state.schedule(client, "crashed")
        assert await client.hget(plan, "notification_pending") is None


async def test_terminal_job_drops_pending_wakeup_without_recreating_plan():
    async with fakeredis.aioredis.FakeRedis() as client:
        plan = mps_state.PLAN_KEY.format(job_id="finished")
        await client.hset(plan, "notification_pending", 1)
        await client.hset(JobStorage.JOB_STATE_KEY.format(job_id="finished"), "status", "completed")
        await client.lpush(mps_state.PROCESSING_KEY, "finished")
        await mps_state.acknowledge(client, "finished", again=True)
        assert await client.llen(mps_state.QUEUE_KEY) == 0
        await client.delete(plan)
        assert not await mps_state.schedule(client, "finished")
        assert not await client.exists(plan)


async def test_queue_pressure_retains_pending_notification_for_recovery(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_NOTIFICATION_MAX_COUNT", "1")
    async with fakeredis.aioredis.FakeRedis() as client:
        plan = mps_state.PLAN_KEY.format(job_id="pending")
        await client.hset(plan, "notification_pending", 1)
        await client.lpush(mps_state.PROCESSING_KEY, "pending")
        # Another producer fills the slot after the owner released its lease.
        await client.lpush(mps_state.QUEUE_KEY, "other")
        await mps_state.acknowledge(client, "pending")
        assert await client.hget(plan, "notification_pending") == b"1"
        assert await client.rpop(mps_state.QUEUE_KEY) == b"other"
        assert await mps_state.schedule(client, "pending")
        assert await client.hget(plan, "notification_pending") is None


async def test_worker_completion_notifications_do_not_create_cycles_during_lease():
    async with fakeredis.aioredis.FakeRedis() as client:
        storage = JobStorage(SimpleNamespace(client=client))
        job_id = "completions"
        plan = mps_state.PLAN_KEY.format(job_id=job_id)
        await client.hset(plan, "version", mps_state.PLAN_VERSION)
        await client.hset(storage.JOB_STATE_KEY.format(job_id=job_id), mapping={
            "mps_manifest": 1, "status": "running", "mps_window_end": 1,
        })
        await client.sadd(storage.TASKS_COMPLETED_KEY.format(job_id=job_id), "task")
        await client.set(plan + ":lock", "owner")
        await client.lpush(mps_state.PROCESSING_KEY, job_id)
        await asyncio.gather(*(mps_state.notify_complete(storage, job_id) for _ in range(100)))
        assert await client.llen(mps_state.QUEUE_KEY) == 0
        assert await client.hget(plan, "refill_cycle") is None
        assert await client.hget(plan, "notification_pending") == b"1"
        await client.delete(plan + ":lock")
        await mps_state.acknowledge(client, job_id)
        assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [job_id.encode()]


async def test_recovery_restores_membership_and_collapses_duplicate_processing():
    async with fakeredis.aioredis.FakeRedis() as client:
        plan = mps_state.PLAN_KEY.format(job_id="recover-once")
        await client.hset(plan, "version", mps_state.PLAN_VERSION)
        await client.lpush(mps_state.PROCESSING_KEY, "recover-once", "recover-once")
        runtime = SimpleNamespace(redis=SimpleNamespace(client=client))
        await materializer._recover_stale_mps_materializations(runtime)
        assert await client.llen(mps_state.PROCESSING_KEY) == 0
        assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [b"recover-once"]
        assert not await mps_state.schedule(client, "recover-once")
        await materializer._recover_stale_mps_materializations(runtime)
        assert await client.llen(mps_state.QUEUE_KEY) == 1


async def test_dequeued_notification_coalesces_before_lease_acquisition():
    async with fakeredis.aioredis.FakeRedis() as client:
        plan = mps_state.PLAN_KEY.format(job_id="acquiring")
        await client.hset(plan, "version", mps_state.PLAN_VERSION)
        await mps_state.schedule(client, "acquiring")
        await client.rpoplpush(mps_state.QUEUE_KEY, mps_state.PROCESSING_KEY)
        await client.srem(mps_state.SCHEDULED_KEY, "acquiring")
        assert not await mps_state.schedule(client, "acquiring")
        assert await client.llen(mps_state.QUEUE_KEY) == 0
        assert await client.hget(plan, "notification_pending") == b"1"
        await mps_state.acknowledge(client, "acquiring")
        assert await client.llen(mps_state.QUEUE_KEY) == 1
