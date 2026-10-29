"""Redis task transitions that production no longer performs.

Since the SQL execution ledger took over dispatch (backend commit c8c8862),
workers no longer mark Redis tasks started/completed or route Redis windows.
Tests that still drive the Redis runtime (window refill, materialization,
retention) use these verbatim copies of the removed JobStorage, BackendRouter,
EventLog, JobManager and Task methods to seed and advance that state.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, cast

from ultima_scraper_backend.job_system import mps_attempt, ordinary_edit
from ultima_scraper_backend.job_system.event_log import JobEvent
from ultima_scraper_backend.job_system.models import Job, JobState, Task, TaskState, _utc_now_iso
from ultima_scraper_backend.job_system.mps_state import (
    DEFERRED_RETENTION_MEMBER,
    retain_deferred,
    retain_task_state,
)
from ultima_scraper_backend.redis_channels import JOB_EVENTS_CHANNEL

logger = logging.getLogger(__name__)


async def persist_task_result(storage, job_id: str, task: Task) -> None:
    """Re-serialize an in-memory task blob in place.

    Unlike :meth:`persist_task`, this does *not* touch the task index
    zset, so it is safe to call on task completion without reordering
    the Pipeline tab. Used by workers so that `task.result` (and the
    updated `started_at`/`completed_at` timestamps) survive retention
    and end up in `management.job_tasks.result_json`.
    """

    task_key = storage.TASK_KEY.format(job_id=job_id, task_id=task.task_id)
    try:
        payload = json.dumps(task.to_dict(), default=str)
    except (TypeError, ValueError) as exc:  # noqa: BLE001
        logger.debug(
            "Failed to serialize task result for persistence (job=%s task=%s): %s",
            job_id,
            task.task_id,
            exc,
        )
        return
    if task.mps_task_manifest is not None:
        from ultima_scraper_backend.job_system.mps_attempt import mutate

        await mutate(storage, job_id, task.mps_task_manifest, """
            if not redis.call('ZSCORE', KEYS[3], ARGV[2]) then return -1 end
            redis.call('SET', KEYS[4], ARGV[3], 'XX', 'KEEPTTL')
            return 1
        """, [storage.TASK_INDEX_KEY.format(job_id=job_id), task_key], [task.task_id, payload])
        return
    # Retention may already have removed this task while its worker was
    # finishing. Updating a result must not resurrect an unindexed blob.
    await ordinary_edit.control_mutation(storage, job_id, "return redis.call('SET',KEYS[1],ARGV[1],'XX','KEEPTTL')", [task_key], [payload])


async def list_tasks_for_job(storage, job_id: str) -> list[str]:
    raw_tasks = await storage._client().zrange(
        storage.TASK_INDEX_KEY.format(job_id=job_id), 0, -1
    )
    tasks = cast(Sequence[Any], raw_tasks)
    normalized_task_ids: list[str] = []
    for item in tasks:
        if isinstance(item, bytes):
            normalized_task_ids.append(item.decode())
        else:
            normalized_task_ids.append(str(item))
    return normalized_task_ids


async def add_task_to_job(storage, job_id: str, task: Task) -> None:
    """Add a new task to an existing job.

    This method allows dynamic task creation after a job has been dispatched.
    Useful for multi-phase jobs where initial tasks discover work for subsequent tasks.

    Args:
        job_id: ID of the job to add the task to
        task: Task instance to add

    Raises:
        ValueError: If job doesn't exist
    """
    config_key = storage.JOB_CONFIG_KEY.format(job_id=job_id)
    if not await storage.redis.get(config_key):
        raise ValueError(f"Job {job_id} not found")

    # Persist the new task
    await storage.persist_task(job_id, task)
    await storage._index_task_dependencies(job_id, task)
    await storage._apply_task_stat_deltas(
        job_id,
        total_delta=1,
        task_type_deltas={task.task_type.value: 1},
    )

    logger.info("Added task %s to job %s", task.task_id, job_id)


async def add_single_task_state(storage, job_id: str, task: Task) -> bool:
    """Add a single task to the appropriate state set (ready or blocked).

    Returns True if the task was added to the ready set, False if blocked.
    Used when dynamically adding tasks after job initialization.
    """
    ready_key = storage.TASKS_READY_KEY.format(job_id=job_id)
    blocked_key = storage.TASKS_BLOCKED_KEY.format(job_id=job_id)

    await storage._index_task_dependencies(job_id, task)

    if task.depends_on:
        await mps_attempt.control_mutation(storage, job_id, "return redis.call('SADD',KEYS[1],ARGV[1])", [blocked_key], [task.task_id])
        await retain_task_state(storage, job_id, blocked_key)
        await storage._apply_task_stat_deltas(job_id, blocked_delta=1)
        return False
    else:
        await mps_attempt.control_mutation(storage, job_id, "return redis.call('SADD',KEYS[1],ARGV[1])", [ready_key], [task.task_id])
        await retain_task_state(storage, job_id, ready_key)
        await storage._apply_task_stat_deltas(job_id, ready_delta=1)
        return True


async def mark_task_started(
    storage,
    job_id: str,
    task_id: str,
    *,
    backend_id: str | None = None,
    claim_owner: str = "",
) -> bool:
    """Move a task from ready → in-flight. Returns True if claimed.

    MPS membership and counters move in one guarded script. Ordinary jobs
    update cached counters after their successful membership transition.
    """

    ready_key = storage.TASKS_READY_KEY.format(job_id=job_id)
    inflight_key = storage.TASKS_INFLIGHT_KEY.format(job_id=job_id)
    route_queue_key: str | None = None
    route_reservations_key: str | None = None
    route_owners_key: str | None = None
    route_member = ""
    if backend_id:
        from ultima_scraper_backend.job_system.routing import BackendRouter

        router = BackendRouter(storage.redis)
        route_queue_key = router._queue_key(backend_id)
        route_reservations_key, route_owners_key = router._ready_claim_keys(
            backend_id
        )
        route_member = router._encode_ready_member(job_id, task_id)

    client = storage._client()
    # Worker attempts already carry the MPS identity in a ContextVar. Use
    # it to avoid a Redis read on every MPS claim; retain the state lookup
    # for callers that enter this method outside an attempt context.
    is_mps_attempt = mps_attempt.current(job_id) is not None
    if not is_mps_attempt:
        is_mps_attempt = await client.hget(
            storage.JOB_STATE_KEY.format(job_id=job_id), "mps_manifest"
        ) in (b"1", "1")
    if is_mps_attempt:
        from ultima_scraper_backend.job_system.mps_state import claim_task

        if not await claim_task(
            storage,
            job_id,
            task_id,
            route_queue_key=route_queue_key,
            route_reservations_key=route_reservations_key,
            route_owners_key=route_owners_key,
            route_member=route_member,
            route_owner=claim_owner,
        ):
            return False
        return True

    # Claim membership and reject an edit in one Redis operation. An
    # editor cannot observe a task between its ready and in-flight sets.
    claimed = await client.eval("""
if redis.call('HGET',KEYS[1],'edit_pending') then return 0 end
if ARGV[3] ~= '' then
local raw = redis.call('GET',KEYS[4])
if not raw then return 0 end
local config = cjson.decode(raw)
if ((config.metadata or {}).task_definition_id or config.job_id) ~= ARGV[3] then return 0 end
end
if redis.call('SREM',KEYS[2],ARGV[1]) == 0 then return 0 end
redis.call('SADD',KEYS[3],ARGV[1])
redis.call('EXPIRE',KEYS[3],ARGV[2])
if #KEYS >= 7 then
redis.call('ZREM',KEYS[6],ARGV[4])
if redis.call('HGET',KEYS[7],ARGV[4]) == ARGV[5] then
    redis.call('HDEL',KEYS[7],ARGV[4])
    redis.call('ZREM',KEYS[5],ARGV[4])
end
end
return 1
""", 7 if route_queue_key else 4,
        storage.JOB_STATE_KEY.format(job_id=job_id), ready_key, inflight_key,
        storage.JOB_CONFIG_KEY.format(job_id=job_id),
        *(
            (route_reservations_key, route_queue_key, route_owners_key)
            if route_queue_key and route_reservations_key and route_owners_key
            else ()
        ),
        task_id, storage.task_state_ttl,
        ordinary_edit.task_command_identity(job_id).get("task_definition_id", ""),
        route_member, claim_owner)
    if not claimed:
        return False

    await storage._apply_task_stat_deltas(
        job_id,
        ready_delta=-1,
        inflight_delta=1,
    )
    return True


async def mark_task_completed(
    storage, job_id: str, task_id: str
) -> tuple[list[str], int]:
    """Mark task as completed and return newly unblocked task IDs plus counter."""

    completed_key = storage.TASKS_COMPLETED_KEY.format(job_id=job_id)
    inflight_key = storage.TASKS_INFLIGHT_KEY.format(job_id=job_id)

    client = storage._client()
    if await client.hget(storage.JOB_STATE_KEY.format(job_id=job_id), "mps_manifest") in (b"1", "1"):
        from ultima_scraper_backend.job_system.mps_state import terminal_task

        return [], await terminal_task(storage, job_id, task_id, success=True)
    if await client.sismember(completed_key, task_id):
        task_stats = await storage.get_job_task_stats(job_id)
        return [], int(task_stats["completed"])

    await ordinary_edit.control_mutation(storage, job_id, """
redis.call('SREM',KEYS[1],ARGV[1])
redis.call('SADD',KEYS[2],ARGV[1])
return 1
""", [inflight_key, completed_key], [task_id])
    await retain_task_state(storage, job_id, completed_key)

    completed_at = datetime.now(timezone.utc).isoformat()
    await storage._set_task_state(
        job_id,
        task_id,
        TaskState.COMPLETED.value,
        completed_at=completed_at,
        deferred_dedup_key=None,
    )

    newly_ready: list[str] = []
    dependents_key = storage.TASK_DEPENDENTS_KEY.format(job_id=job_id, task_id=task_id)
    async for dependent_ids in storage._iter_set_members(dependents_key):
        for dependent_task_id in dependent_ids:
            if await client.sismember(
                storage.TASKS_BLOCKED_KEY.format(job_id=job_id),
                dependent_task_id,
            ) and await _dependencies_satisfied(storage, job_id, dependent_task_id):
                newly_ready.append(dependent_task_id)

    if newly_ready:
        ready_key = storage.TASKS_READY_KEY.format(job_id=job_id)
        blocked_key = storage.TASKS_BLOCKED_KEY.format(job_id=job_id)
        await ordinary_edit.control_mutation(storage, job_id, """
for i=1,#ARGV do
redis.call('SADD',KEYS[1],ARGV[i])
redis.call('SREM',KEYS[2],ARGV[i])
end
return #ARGV
""", [ready_key, blocked_key], newly_ready)
        await retain_task_state(storage, job_id, ready_key)

    task_stats = await storage._apply_task_stat_deltas(
        job_id,
        ready_delta=len(newly_ready),
        blocked_delta=-len(newly_ready),
        inflight_delta=-1,
        completed_delta=1,
    )

    if task_stats.get('mps_manifest'):
        from ultima_scraper_backend.job_system.mps_state import notify_complete

        await notify_complete(storage, job_id)
    return newly_ready, int(task_stats["completed"])


async def mark_task_failed(storage, job_id: str, task_id: str) -> None:
    if await storage._client().hget(storage.JOB_STATE_KEY.format(job_id=job_id), "mps_manifest") in (b"1", "1"):
        from ultima_scraper_backend.job_system.mps_state import terminal_task

        await terminal_task(storage, job_id, task_id, success=False)
        return
    inflight_key = storage.TASKS_INFLIGHT_KEY.format(job_id=job_id)
    removed = await ordinary_edit.control_mutation(storage, job_id, "return redis.call('SREM',KEYS[1],ARGV[1])", [inflight_key], [task_id])
    if removed:
        if await storage._client().hget(storage.JOB_STATE_KEY.format(job_id=job_id), 'mps_manifest') in (b'1', '1'):
            from ultima_scraper_backend.job_system.mps_state import FAILED_KEY

            await storage._client().sadd(FAILED_KEY.format(job_id=job_id), task_id)
        stats = await storage._apply_task_stat_deltas(
            job_id,
            inflight_delta=-1,
            failed_delta=1,
        )
        if stats.get('mps_manifest'):
            from ultima_scraper_backend.job_system.mps_state import notify_complete

            await notify_complete(storage, job_id)


async def remove_task_from_inflight(storage, job_id: str, task_id: str) -> None:
    """Remove a task from the inflight set without marking it failed."""

    from ultima_scraper_backend.job_system.mps_attempt import current, mutate

    identity = current(job_id)
    if identity is not None:
        await mutate(storage, job_id, identity.manifest_id, """
            redis.call('SREM', KEYS[3], ARGV[2])
            redis.call('HSET', KEYS[1], 'inflight_tasks', redis.call('SCARD', KEYS[3]))
            return 1
        """, [storage.TASKS_INFLIGHT_KEY.format(job_id=job_id)], [task_id])
        return
    removed = await ordinary_edit.control_mutation(storage, job_id, "return redis.call('SREM',KEYS[1],ARGV[1])", [storage.TASKS_INFLIGHT_KEY.format(job_id=job_id)], [task_id])
    if removed:
        await storage._apply_task_stat_deltas(job_id, inflight_delta=-1)


async def store_task_output(storage, job_id: str, task_id: str, output: Any) -> None:
    outputs_key = storage.TASK_OUTPUTS_KEY.format(job_id=job_id)
    try:
        payload = json.dumps(output, default=str)
    except TypeError:
        payload = json.dumps(str(output))

    from ultima_scraper_backend.job_system.mps_attempt import current, mutate

    attempt = current(job_id)
    if attempt is not None:
        await mutate(storage, job_id, attempt.manifest_id, """
            if not redis.call('ZSCORE', KEYS[3], ARGV[2]) then return -1 end
            redis.call('HSET', KEYS[4], ARGV[2], ARGV[3])
            return 1
        """, [storage.TASK_INDEX_KEY.format(job_id=job_id), outputs_key], [task_id, payload])
        return
    await ordinary_edit.control_mutation(storage, job_id, "return redis.call('HSET',KEYS[1],ARGV[1],ARGV[2])", [outputs_key], [task_id, payload])
    await retain_task_state(storage, job_id, outputs_key)


async def release_task_lock(storage, task_id: str, worker_id: str) -> bool:
    return await ordinary_edit.release_reservation(storage, storage.TASK_EXEC_LOCK_KEY.format(task_id=task_id), worker_id)


async def acquire_task_lock(
    storage, task_id: str, worker_id: str, ttl: int | None = None
) -> bool:
    lock_key = storage.TASK_EXEC_LOCK_KEY.format(task_id=task_id)
    lock_ttl = ttl or storage.TASK_EXEC_LOCK_TTL
    result = await storage._client().set(lock_key, worker_id, nx=True, ex=lock_ttl)
    return bool(result)


async def _dependencies_satisfied(storage, job_id: str, task_id: str) -> bool:
    task = await storage.fetch_task(job_id, task_id)
    if not task:
        return False
    if not task.depends_on:
        return True

    completed_key = storage.TASKS_COMPLETED_KEY.format(job_id=job_id)
    for dep in task.depends_on:
        if await storage._client().sismember(completed_key, dep):
            continue
        dep_task = await storage.fetch_task(job_id, dep)
        if dep_task is None:
            continue
        return False
    return True


async def mark_task_deferred(
    storage,
    job_id: str,
    task_id: str,
    dedup_key: str,
) -> None:
    """Mark a task as blocked due to an active dedupe collision."""

    ready_key = storage.TASKS_READY_KEY.format(job_id=job_id)
    blocked_key = storage.TASKS_BLOCKED_KEY.format(job_id=job_id)
    outputs_key = storage.TASK_OUTPUTS_KEY.format(job_id=job_id)
    deferred_key = storage.DEFERRED_TASKS_KEY.format(dedup_key=dedup_key)
    member = f"{job_id}:{task_id}"
    from ultima_scraper_backend.job_system.mps_attempt import current, mutate

    identity = current(job_id)
    if identity is not None:
        await storage._set_task_state(job_id, task_id, TaskState.DEFERRED.value, deferred_dedup_key=dedup_key)
        await mutate(storage, job_id, identity.manifest_id, """
            if not redis.call('ZSCORE', KEYS[3], ARGV[2]) then return -1 end
            redis.call('SREM', KEYS[4], ARGV[2])
            redis.call('SREM', KEYS[5], ARGV[2])
            redis.call('SREM', KEYS[6], ARGV[2])
            if redis.call('SADD', KEYS[7], ARGV[3]) == 1 then
                redis.call('HINCRBY', KEYS[1], 'deferred_tasks', 1)
            end
            redis.call('HSET', KEYS[8], ARGV[2], ARGV[4])
            redis.call('SADD', KEYS[7], ARGV[5])
            redis.call('PERSIST', KEYS[7])
            redis.call('HSET', KEYS[1], 'ready_tasks', redis.call('SCARD', KEYS[4]),
                'inflight_tasks', redis.call('SCARD', KEYS[6]))
            return 1
        """, [storage.TASK_INDEX_KEY.format(job_id=job_id), ready_key, blocked_key,
            storage.TASKS_INFLIGHT_KEY.format(job_id=job_id), deferred_key, outputs_key],
            [task_id, member, json.dumps({"state": "deferred", "reason": "dedup_conflict", "dedup_key": dedup_key}), DEFERRED_RETENTION_MEMBER])
        return
    removed_from_ready, removed_from_inflight = await ordinary_edit.control_mutation(storage, job_id, """
local ready = redis.call('SREM',KEYS[1],ARGV[1])
local inflight = redis.call('SREM',KEYS[2],ARGV[1])
redis.call('SREM',KEYS[3],ARGV[1])
redis.call('SADD',KEYS[4],ARGV[2])
redis.call('HSET',KEYS[5],ARGV[1],ARGV[3])
return {ready,inflight}
""", [ready_key, storage.TASKS_INFLIGHT_KEY.format(job_id=job_id), blocked_key, deferred_key, outputs_key],
        [task_id, member, json.dumps({"state": "deferred", "reason": "dedup_conflict", "dedup_key": dedup_key})])
    await retain_task_state(storage, job_id, blocked_key)
    await retain_task_state(storage, job_id, outputs_key)
    await retain_deferred(storage, job_id, deferred_key)
    await storage._set_task_state(
        job_id,
        task_id,
        TaskState.DEFERRED.value,
        deferred_dedup_key=dedup_key,
    )
    await storage._apply_task_stat_deltas(
        job_id,
        ready_delta=-1 if removed_from_ready else 0,
        inflight_delta=-1 if removed_from_inflight else 0,
        deferred_delta=1,
    )


async def initialize_task_state(
    storage,
    job: Job,
    *,
    return_ready_task_ids: bool = True,
) -> list[str]:
    """Initialize ready and blocked task sets for a newly queued job."""

    ready_key = storage.TASKS_READY_KEY.format(job_id=job.job_id)
    blocked_key = storage.TASKS_BLOCKED_KEY.format(job_id=job.job_id)
    completed_key = storage.TASKS_COMPLETED_KEY.format(job_id=job.job_id)
    inflight_key = storage.TASKS_INFLIGHT_KEY.format(job_id=job.job_id)
    outputs_key = storage.TASK_OUTPUTS_KEY.format(job_id=job.job_id)

    client = storage._client()
    await client.delete(
        ready_key, blocked_key, completed_key, inflight_key, outputs_key
    )
    await storage._clear_dependency_index(job.job_id)

    ready_tasks: list[str] = []
    ready_batch: list[str] = []
    blocked_batch: list[str] = []
    ready_count = 0
    blocked_count = 0
    task_type_counts: dict[str, int] = {}

    for task in job.tasks:
        await storage._index_task_dependencies(job.job_id, task)
        task_type_counts[task.task_type.value] = (
            task_type_counts.get(task.task_type.value, 0) + 1
        )
        if task.depends_on:
            blocked_count += 1
            blocked_batch.append(task.task_id)
            if len(blocked_batch) >= 1000:
                await client.sadd(blocked_key, *blocked_batch)
                blocked_batch.clear()
        else:
            ready_count += 1
            ready_batch.append(task.task_id)
            if return_ready_task_ids:
                ready_tasks.append(task.task_id)
            if len(ready_batch) >= 1000:
                await client.sadd(ready_key, *ready_batch)
                ready_batch.clear()

    if ready_batch:
        await client.sadd(ready_key, *ready_batch)
    if blocked_batch:
        await client.sadd(blocked_key, *blocked_batch)

    for key in (ready_key, blocked_key, completed_key, inflight_key, outputs_key):
        await retain_task_state(storage, job.job_id, key)

    await storage._write_task_stats(
        job.job_id,
        total=len(job.tasks),
        ready=ready_count,
        blocked=blocked_count,
        inflight=0,
        deferred=0,
        completed=0,
        failed=0,
        task_type_counts=task_type_counts,
    )

    return ready_tasks


async def release_ready_claim(
    router,
    backend_id: str,
    job_id: str,
    task_id: str,
    *,
    claimant_id: str,
    task_is_ready: bool,
) -> None:
    """Release a pre-start reservation, retaining only still-ready routes."""

    member = router._encode_ready_member(job_id, task_id)
    reservations_key, owners_key = router._ready_claim_keys(backend_id)
    await router._client().eval(
        """
if redis.call('HGET', KEYS[3], ARGV[1]) == ARGV[2] then
  redis.call('HDEL', KEYS[3], ARGV[1])
  redis.call('ZREM', KEYS[2], ARGV[1])
end
if ARGV[3] == '0' then redis.call('ZREM', KEYS[1], ARGV[1]) end
return 1
""",
        3,
        router._queue_key(backend_id),
        reservations_key,
        owners_key,
        member,
        claimant_id,
        int(task_is_ready),
    )


async def route_job_tasks_to_backend(
    router,
    *,
    job_id: str,
    backend_id: str,
    task_items: Sequence[tuple[str, str, int]],
) -> None:
    await router._client().sadd(router._backend_jobs_key(backend_id), job_id)
    await router.enqueue_ready_tasks(backend_id=backend_id, items=task_items)


async def append_event(event_log, event: JobEvent) -> str:
    """Append an event to the job's event stream.

    This is the ONLY way to record state changes. All mutations must
    go through events to maintain consistency and auditability.

    Args:
        event: Event to append

    Returns:
        Redis Stream ID (format: timestamp-sequence)

    Raises:
        Exception: If Redis append fails
    """
    from ultima_scraper_backend.job_system.mps_attempt import current, mutate
    from ultima_scraper_backend.job_system.storage import JobStorage

    stream_key = event_log._stream_key(event.job_id)
    identity = current(event.job_id)
    if identity is not None:
        event.data["mps_task_manifest"] = identity.manifest_id
    event_dict = event.to_dict()
    if "mps_task_manifest" in event.data:
        storage = JobStorage(event_log.redis)
        published = {"event": event.event_type.value, "job_id": event.job_id,
            "task_id": event.task_id, "worker_id": event.worker_id,
            "timestamp": event.timestamp, **event.data}
        fields = [part for item in event_dict.items() for part in item]
        result = await mutate(storage, event.job_id, event.data["mps_task_manifest"], """
            if ARGV[5] ~= '' and not redis.call('ZSCORE', KEYS[6], ARGV[5]) then return 0 end
            local id = redis.call('XADD', KEYS[3], 'MAXLEN', '~', ARGV[3], '*', unpack(ARGV,6))
            redis.call('EXPIRE', KEYS[3], ARGV[2])
            redis.call('XADD', KEYS[4], 'MAXLEN', '~', 100000, '*', 'stream_key', KEYS[3], unpack(ARGV,6))
            redis.call('PUBLISH', KEYS[5], ARGV[4])
            return id
        """, [stream_key, event_log.GLOBAL_STREAM, JOB_EVENTS_CHANNEL,
            storage.TASK_INDEX_KEY.format(job_id=event.job_id)],
            [event_log.STREAM_TTL, event_log.MAX_EVENTS_PER_JOB, json.dumps(published), event.task_id or '', *fields])
        return result.decode() if isinstance(result, bytes) else str(result or '')

    try:
        # XADD returns the stream ID: "timestamp-sequence"
        # Use * to let Redis auto-generate ID based on current time
        redis_client: Any = event_log.redis.client
        event_id = await redis_client.xadd(
            stream_key,
            cast(Any, event_dict),
            maxlen=event_log.MAX_EVENTS_PER_JOB,
            approximate=True,  # Use ~ for performance (approximate trimming)
        )

        # Decode event_id if bytes
        if isinstance(event_id, bytes):
            event_id_str = event_id.decode("utf-8")
        else:
            event_id_str = str(event_id)

        # Set TTL on the stream (refresh on each append)
        await event_log.redis.expire(stream_key, event_log.STREAM_TTL)

        # Also append to global stream for system-wide monitoring
        try:
            await redis_client.xadd(
                event_log.GLOBAL_STREAM,
                cast(Any, {**event_dict, "stream_key": stream_key}),
                maxlen=100000,  # Keep more events globally
                approximate=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Failed to append to global stream: {exc}")

        # Publish to pub/sub channel for real-time WebSocket updates
        try:
            pubsub_event = {
                "event": event.event_type.value,
                "job_id": event.job_id,
                "task_id": event.task_id,
                "worker_id": event.worker_id,
                "timestamp": event.timestamp,
                **event.data,
            }
            await event_log.redis.publish(JOB_EVENTS_CHANNEL, json.dumps(pubsub_event))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Failed to publish event to pub/sub: {exc}")

        logger.debug(
            f"Event appended: {event.event_type.value} "
            f"job={event.job_id} task={event.task_id} id={event_id_str}"
        )

        return event_id_str

    except Exception as exc:
        logger.error(
            f"Failed to append event {event.event_type.value} "
            f"for job {event.job_id}: {exc}"
        )
        raise


async def finalize_job_completion(manager, job_id: str) -> None:
    """Release remaining resources for a completed job once DB sync is durable."""

    await manager._finalize_terminal_job_cleanup(
        job_id,
        terminal_state=JobState.COMPLETED,
    )


def add_subtask(parent, subtask: Task) -> None:
    """Add a subtask to this task."""
    subtask.parent_task_id = parent.task_id
    parent.subtasks.append(subtask)
    parent.updated_at = _utc_now_iso()
