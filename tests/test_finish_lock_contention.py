"""Completion acquisition preserves retry backoff and ownership fences."""

import asyncio
from types import SimpleNamespace

import pytest
import test_database_write_queue as fixtures
from ultima_scraper_backend.job_system import JobStorage, mps_attempt

redis_manager = fixtures.redis_manager


async def finish_context(redis_manager):
    storage = JobStorage(redis_manager)
    job = SimpleNamespace(job_id="job-finish-contention", metadata={"mps_manifest": True})
    task = SimpleNamespace(mps_task_manifest="definition-one")
    await storage._client().hset(
        storage.JOB_STATE_KEY.format(job_id=job.job_id),
        mapping={"mps_manifest": 1, "mps_task_manifest": task.mps_task_manifest, "status": "running"},
    )
    return storage, job, task


@pytest.mark.parametrize("handoff", [False, True])
async def test_finish_backoff_remains_bounded_across_owner_handoffs(
    redis_manager, monkeypatch, handoff
):
    storage, job, task = await finish_context(redis_manager)
    client = storage._client()
    key = mps_attempt.lock_key(job.job_id)
    await client.set(key, "materializer:first", ex=90)
    sleeper = asyncio.sleep
    caller = asyncio.current_task()
    delays = []

    async def observed_sleep(delay):
        if asyncio.current_task() is not caller:
            return await sleeper(delay)
        delays.append(delay)
        if handoff and len(delays) == 3:
            await client.set(key, "materializer:second", ex=90)
        if len(delays) == 12:
            await client.delete(key)
        await sleeper(0)

    monkeypatch.setattr(asyncio, "sleep", observed_sleep)
    async with mps_attempt.finish_lock(storage, job, task):
        assert (await client.get(key)).startswith(b"mps-finish:")
    assert not await client.exists(key)
    assert delays[:3] == pytest.approx([.005, .0075, .01125])
    assert delays[3] == pytest.approx(.016875)
    assert max(delays) == pytest.approx(.05)


async def test_finishing_workers_can_complete_concurrently(redis_manager):
    storage, job, task = await finish_context(redis_manager)
    client = storage._client()
    key = mps_attempt.lock_key(job.job_id)
    first_entered, both_entered, release_first, release_second = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    inside_first = False
    inside_second = False

    async def first():
        nonlocal inside_first
        async with mps_attempt.finish_lock(storage, job, task):
            inside_first = True
            first_entered.set()
            await release_first.wait()
            inside_first = False

    async def second():
        nonlocal inside_second
        await first_entered.wait()
        async with mps_attempt.finish_lock(storage, job, task):
            # Second finisher must enter concurrently while first is still inside!
            assert inside_first is True
            inside_second = True
            both_entered.set()
            await release_second.wait()
            inside_second = False

    one, two = asyncio.create_task(first()), asyncio.create_task(second())
    try:
        await asyncio.wait_for(both_entered.wait(), 2)
        # Verify both are running inside finish_lock simultaneously!
        assert inside_first is True
        assert inside_second is True
        assert (await client.get(key)).startswith(b"mps-finish:")

        # Verify exclusive writer cannot acquire while finishers are active
        acquired = await client.set(key, "materializer:writer", nx=True)
        assert not acquired

        # First worker finishes and exits, second is still finishing
        release_first.set()
        await asyncio.sleep(0.01)
        assert not inside_first
        assert inside_second

        # Lock is STILL held by mps-finish:active because second worker is still inside!
        assert (await client.get(key)).startswith(b"mps-finish:")
        acquired_while_second_active = await client.set(key, "materializer:writer", nx=True)
        assert not acquired_while_second_active

        # Now release second worker
        release_second.set()
        await asyncio.wait_for(asyncio.gather(one, two), 2)

        # After both finishers exit, finish lock and finishers tracking keys are deleted
        assert not await client.exists(key)
        assert not await client.exists(f"{key}:finishers")

        # Exclusive writer can now acquire
        acquired_after_all_exit = await client.set(key, "materializer:writer", nx=True)
        assert acquired_after_all_exit
        await client.delete(key)
    finally:
        release_first.set()
        release_second.set()
        one.cancel()
        two.cancel()
        await asyncio.gather(one, two, return_exceptions=True)


@pytest.mark.parametrize("action", ["cancel", "replace"])
async def test_waiting_finisher_cannot_release_another_owner_or_enter_a_replacement(
    redis_manager, monkeypatch, action
):
    storage, job, task = await finish_context(redis_manager)
    client = storage._client()
    key = mps_attempt.lock_key(job.job_id)
    await client.set(key, "materializer:existing-owner", ex=90)
    waiting = asyncio.Event()
    sleeper = asyncio.sleep

    async def observed_sleep(delay):
        if asyncio.current_task() is execution:
            waiting.set()
        await sleeper(delay)

    async def contender():
        async with mps_attempt.finish_lock(storage, job, task):
            pytest.fail("A blocked or obsolete finisher entered the protected section")

    monkeypatch.setattr(asyncio, "sleep", observed_sleep)
    execution = asyncio.create_task(contender())
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        if action == "cancel":
            execution.cancel()
            with pytest.raises(asyncio.CancelledError):
                await execution
        else:
            await client.hset(storage.JOB_STATE_KEY.format(job_id=job.job_id), "mps_task_manifest", "definition-two")
            with pytest.raises(mps_attempt.StaleTaskDefinition):
                await asyncio.wait_for(execution, 2)
        assert await client.get(key) == b"materializer:existing-owner"
    finally:
        execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)
