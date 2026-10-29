"""Durability and scaling tests for the canonical database write queue."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any

import fakeredis.aioredis
from fakeredis.commands_mixins.scripting_mixin import ScriptingCommandsMixin
import pytest
from redis.asyncio import Redis

from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteClient,
    DatabaseWriteCommand,
    DatabaseWriteOperation,
    DatabaseWriteRejected,
    DatabaseWriteResult,
    DatabaseWriteTimeout,
    DatabaseWriterService,
    WRITE_TIMING_KEY,
)
from ultima_scraper_backend.database import write_queue


class _RedisManager:
    def __init__(self, client=None) -> None:
        self.client = (
            client
            if client is not None
            else fakeredis.aioredis.FakeRedis(decode_responses=False)
        )


class _RecordingExecutor:
    receipts: dict[str, DatabaseWriteResult] = {}
    def __init__(self, *, failures: int = 0, delay: float = 0.0) -> None:
        self.failures = failures
        self.delay = delay
        self.batches: list[list[DatabaseWriteCommand]] = []
        self.active = 0
        self.max_active = 0
        self.closed = False

    async def execute_batch(
        self,
        commands: Sequence[DatabaseWriteCommand],
    ) -> Mapping[str, dict[str, Any]]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.batches.append(list(commands))
            if self.failures:
                self.failures -= 1
                raise RuntimeError("database unavailable")
            for command in commands:
                self.receipts.setdefault(command.command_id, DatabaseWriteResult(
                    command_id=command.command_id, success=True,
                    payload={"committed": True}, error=None, completed_at=write_queue._utc_now()))
            return {command.command_id: self.receipts[command.command_id].payload for command in commands}
        finally:
            self.active -= 1

    async def close(self) -> None:
        self.closed = True

    async def persist_outcome(self, command, result):
        return self.receipts.setdefault(command.command_id, result)

    async def persist_invalid(self, entry_id, fields, error):
        pass


@pytest.fixture(
    params=["fake", "real"]
    if os.environ.get("USR_TEST_WITH_REDIS") == "1"
    else ["fake"]
)
async def redis_manager(request, monkeypatch):
    # Transport tests own this in-memory receipt store. Native transaction and
    # combined transport tests provide a separate private PostgreSQL fixture.
    receipts = {}
    monkeypatch.setattr(_RecordingExecutor, 'receipts', receipts)
    monkeypatch.setattr(write_queue, '_lookup_write_receipt', lambda command_id: receipts.get(command_id))
    if request.param == "fake":
        # fakeredis 2.34 dispatches Lua calls without resolving subcommands.
        # Use its existing XINFO GROUPS implementation; production Lua stays
        # identical to the script exercised against the isolated real server.
        original = ScriptingCommandsMixin._lua_redis_call

        def dispatch(self, runtime, expected_globals, op, *args):
            if op.lower() == b"xinfo" and args and args[0].lower() == b"groups":
                return original(
                    self, runtime, expected_globals, b"xinfo groups", *args[1:]
                )
            return original(self, runtime, expected_globals, op, *args)

        monkeypatch.setattr(ScriptingCommandsMixin, "_lua_redis_call", dispatch)
        manager = _RedisManager()
        try:
            yield manager
        finally:
            await manager.client.aclose()
        return

    # Never connect these destructive fixture tests to an existing Redis.
    # Each test owns a new process, private socket and empty temporary data dir.
    with tempfile.TemporaryDirectory(prefix="usr-writer-test-") as directory:
        socket_path = f"{directory}/redis.sock"
        process = subprocess.Popen(
            [
                "redis-server",
                "--port",
                "0",
                "--unixsocket",
                socket_path,
                "--unixsocketperm",
                "700",
                "--dir",
                directory,
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        manager = _RedisManager(
            Redis(unix_socket_path=socket_path, decode_responses=False)
        )
        try:
            async with asyncio.timeout(3):
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(process.stderr.read().decode())
                    try:
                        await manager.client.ping()
                        break
                    except (ConnectionError, OSError, write_queue.RedisError):
                        await asyncio.sleep(0.01)
            yield manager
        finally:
            await manager.client.aclose()
            process.terminate()
            process.wait(timeout=3)
            if process.stderr is not None:
                process.stderr.close()


async def test_writer_result_exposes_configuration_and_pressure_timing(
    redis_manager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("ULTIMA_DATABASE_WRITE_QUEUE_MAX_COMMANDS", raising=False)
    monkeypatch.delenv("ULTIMA_DATABASE_WRITE_QUEUE_MAX_BYTES", raising=False)
    executor = _RecordingExecutor()
    service = DatabaseWriterService(
        redis_manager,
        executor,
        batch_size=5,
        concurrency=2,
        block_ms=1,
    )
    client = DatabaseWriteClient(redis_manager)
    await service._ensure_group()
    command_id = await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        {"job_id": "profiled", "status": "completed"},
    )

    await service._process_entries(await service._read_new_entries())
    result = await client.wait_for_result(
        command_id,
        timeout_seconds=1,
        include_timing=True,
    )

    timing = result[WRITE_TIMING_KEY]
    assert timing["writer_configured_concurrency"] == 2
    assert timing["writer_configured_batch_size"] == 5
    assert timing["writer_refill_min_commands_per_lane"] == 2
    assert timing["writer_refill_min_commands"] == 4
    assert timing["writer_window_commands"] == 10
    assert timing["writer_queue_max_commands"] == 10
    assert timing["writer_active_lanes"] == 1
    assert timing["writer_batch_commands"] == 1
    assert timing["writer_batch_fill_ratio"] == pytest.approx(0.2)
    assert timing["writer_lane_domain"] == "job"
    assert timing["writer_lane_shard"] >= 0
    assert timing["writer_lane_idle_ms"] >= 0
    assert timing["writer_lane_predecessor_wait_ms"] >= 0
    assert timing["writer_refill_wait_ms"] >= 0
    assert timing["writer_queue_commands_at_start"] >= 1
    assert timing["writer_queue_bytes_at_start"] > 0
    assert timing["writer_result_publish_started_at_ms"] > 0
    assert timing["writer_result_available_at_ms"] > 0
    assert timing["writer_result_observed_at_ms"] >= timing["writer_result_available_at_ms"]
    assert timing["writer_result_source"] == "cache"
    assert timing["writer_operation"] == "sync_job_status"
    assert timing["writer_batch_peer_work_ms"] >= 0
    assert timing["writer_batch_overhead_ms"] >= 0


async def test_profiled_enqueue_splits_capacity_redis_and_serialization_time(
    redis_manager,
):
    service = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(),
        batch_size=1,
        concurrency=1,
        block_ms=1,
    )
    client = DatabaseWriteClient(
        redis_manager,
        max_queue_commands=1,
        max_queue_bytes=64 * 1024 * 1024,
    )
    await service._ensure_group()
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        {"job_id": "first"},
        command_id="first",
    )
    blocked = asyncio.create_task(
        client.enqueue(
            DatabaseWriteOperation.SYNC_JOB_STATUS,
            {"job_id": "second"},
            command_id="second",
            _include_timing=True,
        )
    )
    await asyncio.sleep(0.08)
    await service._process_entries(await service._read_new_entries())
    command_id, timing = await asyncio.wait_for(blocked, timeout=1)

    assert command_id == "second"
    assert timing["producer_serialization_ms"] > 0
    assert timing["producer_capacity_wait_ms"] >= 40
    assert timing["producer_redis_enqueue_ms"] > 0
    assert timing["producer_admission_overhead_ms"] >= 0


async def test_evicted_results_remain_readable_and_cache_memory_is_bounded(redis_manager):
    from ultima_scraper_backend.database import write_result_cache

    executor = _RecordingExecutor()
    service = DatabaseWriterService(redis_manager, executor, batch_size=10,
        result_cache_max_entries=3, result_cache_max_bytes=400, block_ms=1)
    client = DatabaseWriteClient(redis_manager)
    await service._ensure_group()
    for index in range(100):
        await client.enqueue(DatabaseWriteOperation.SYNC_JOB_STATUS,
            {'job_id': str(index), 'status': 'completed'}, command_id=f'bounded-result-{index}')
        await service._process_entries(await service._read_new_entries())
        assert await redis_manager.client.zcard(write_result_cache.RESULT_INDEX) <= 3
        assert int(await redis_manager.client.get(write_result_cache.RESULT_BYTES)) <= 400
    assert await redis_manager.client.get(client.result_key('bounded-result-0')) is None
    assert await client.wait_for_result('bounded-result-0', timeout_seconds=1) == {'committed': True}
    assert await redis_manager.client.dbsize() < 20


async def test_result_that_cannot_fit_cache_is_delivered_from_durable_receipt(redis_manager):
    service = DatabaseWriterService(redis_manager, _RecordingExecutor(),
        result_cache_max_entries=1, result_cache_max_bytes=1, block_ms=1)
    client = DatabaseWriteClient(redis_manager)
    await service._ensure_group()
    command_id = await client.enqueue(DatabaseWriteOperation.SYNC_JOB_STATUS,
        {'job_id': 'too-large-result', 'status': 'completed'})
    await service._process_entries(await service._read_new_entries())
    assert await redis_manager.client.get(client.result_key(command_id)) is None
    result = await client.wait_for_result(
        command_id,
        timeout_seconds=1,
        include_timing=True,
    )
    assert result["committed"] is True
    assert result[WRITE_TIMING_KEY]["writer_result_source"] == "receipt"
    assert result[WRITE_TIMING_KEY]["writer_result_split_missing_reason"] == (
        "result_cache_miss"
    )
    # Production receipts are stored without writer timing; report none.
    _RecordingExecutor.receipts[command_id] = DatabaseWriteResult(
        command_id=command_id, success=True, payload={"committed": True},
        error=None, completed_at=write_queue._utc_now())
    result = await client.wait_for_result(
        command_id,
        timeout_seconds=1,
        include_timing=True,
    )
    assert result[WRITE_TIMING_KEY] == {
        "writer_timing_unavailable": True,
        "writer_result_source": "receipt",
        "writer_result_split_missing_reason": "result_cache_miss",
    }
    smaller_client = DatabaseWriteClient(redis_manager, max_command_bytes=1)
    assert await smaller_client.enqueue(DatabaseWriteOperation.SYNC_JOB_STATUS,
        {'job_id': 'too-large-result', 'status': 'completed'}, command_id=command_id) == command_id


async def test_dead_letter_cache_obeys_byte_and_count_budgets(redis_manager):
    from ultima_scraper_backend.database import write_result_cache

    executor = _RecordingExecutor(failures=20)
    service = DatabaseWriterService(redis_manager, executor, max_attempts=1,
        dead_letter_maxlen=2, dead_letter_max_bytes=1000, block_ms=1)
    client = DatabaseWriteClient(redis_manager)
    await service._ensure_group()
    for index in range(10):
        await client.enqueue(DatabaseWriteOperation.SYNC_JOB_STATUS,
            {'job_id': str(index)}, command_id=f'bounded-failure-{index}')
        await service._process_entries(await service._read_new_entries())
        assert await redis_manager.client.xlen(service.DEAD_LETTER_STREAM) <= 2
        assert int(await redis_manager.client.get(write_result_cache.DEAD_BYTES)) <= 1000
    assert len(executor.receipts) == 10
    assert all(not result.success for result in executor.receipts.values())


async def test_database_outage_cannot_ack_failed_input_before_its_receipt(redis_manager, monkeypatch):
    from unittest.mock import AsyncMock

    executor = _RecordingExecutor(failures=1)
    monkeypatch.setattr(executor, 'persist_outcome', AsyncMock(side_effect=RuntimeError('receipt database unavailable')))
    service = DatabaseWriterService(redis_manager, executor, max_attempts=1, block_ms=1)
    client = DatabaseWriteClient(redis_manager)
    await service._ensure_group()
    command_id = await client.enqueue(DatabaseWriteOperation.SYNC_JOB_STATUS, {'job_id': 'retained'})
    with pytest.raises(RuntimeError, match='receipt database unavailable'):
        await service._process_entries(await service._read_new_entries())
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 1
    assert await redis_manager.client.exists(client.submitted_key(command_id)) == 1
    assert await redis_manager.client.get(client.result_key(command_id)) is None
    assert await redis_manager.client.xlen(service.DEAD_LETTER_STREAM) == 0


async def test_legacy_dead_letters_drain_only_after_durable_archival(redis_manager, monkeypatch):
    from unittest.mock import AsyncMock
    from ultima_scraper_backend.database import write_result_cache

    executor = _RecordingExecutor()
    retain = AsyncMock()
    monkeypatch.setattr(executor, 'persist_invalid', retain)
    service = DatabaseWriterService(redis_manager, executor, batch_size=2, batch_max_bytes=1000)
    for index in range(5):
        await redis_manager.client.xadd(service.DEAD_LETTER_STREAM, {'command': f'legacy-{index}', 'error': 'old failure'})
    await service._archive_legacy_dead_letters()
    assert await redis_manager.client.xlen(service.DEAD_LETTER_STREAM) == 3
    assert retain.await_count == 2
    retain.side_effect = RuntimeError('archive unavailable')
    with pytest.raises(RuntimeError, match='archive unavailable'):
        await service._archive_legacy_dead_letters()
    assert await redis_manager.client.xlen(service.DEAD_LETTER_STREAM) == 3
    retain.side_effect = None
    await service._archive_legacy_dead_letters()
    await service._archive_legacy_dead_letters()
    assert await redis_manager.client.xlen(service.DEAD_LETTER_STREAM) == 0
    assert await redis_manager.client.get(write_result_cache.DEAD_BYTES) == b'0'


async def test_malformed_binary_entry_retains_exact_input_before_ack(redis_manager, monkeypatch):
    from unittest.mock import AsyncMock

    executor = _RecordingExecutor()
    retain = AsyncMock()
    monkeypatch.setattr(executor, 'persist_invalid', retain)
    service = DatabaseWriterService(redis_manager, executor, block_ms=1)
    await service._ensure_group()
    await redis_manager.client.xadd(DatabaseWriteClient.STREAM_KEY, {'command': b'\xff\x80'})
    await service._process_entries(await service._read_new_entries())
    fields = retain.await_args.args[1]
    assert fields['command'].encode('utf-8', errors='surrogateescape') == b'\xff\x80'
    assert await redis_manager.client.xlen(DatabaseWriteClient.STREAM_KEY) == 0


async def test_receipt_lookup_respects_the_explicit_wait_deadline(redis_manager, monkeypatch):
    async def delayed_lookup(function, *args, **kwargs):
        await asyncio.sleep(1)
        return None

    monkeypatch.setattr(asyncio, 'to_thread', delayed_lookup)
    client = DatabaseWriteClient(redis_manager)
    with pytest.raises(DatabaseWriteTimeout, match='durable receipt'):
        await client.wait_for_result('slow-receipt', timeout_seconds=0.02)


@pytest.mark.asyncio
async def test_submit_waits_for_committed_result(redis_manager: _RedisManager) -> None:
    executor = _RecordingExecutor()
    service = DatabaseWriterService(
        redis_manager,
        executor,
        consumer_name="writer-roundtrip",
        block_ms=10,
    )
    writer_task = asyncio.create_task(service.run())
    client = DatabaseWriteClient(redis_manager, producer_id="worker-1")

    result = await client.submit(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        {"job_id": "job-1", "status": "completed"},
        command_id="job-1-completed",
        timeout_seconds=2,
    )

    assert result == {"committed": True}
    assert [
        [command.command_id for command in batch] for batch in executor.batches
    ] == [["job-1-completed"]]
    assert await redis_manager.client.xlen(DatabaseWriteClient.STREAM_KEY) == 0
    assert (
        await redis_manager.client.get(
            DatabaseWriteClient.submitted_key("job-1-completed")
        )
        is None
    )
    assert (
        await redis_manager.client.ttl(
            DatabaseWriteClient.result_key("job-1-completed")
        )
        >= DatabaseWriteClient.RESULT_TTL_SECONDS - 1
    )

    service.stop()
    await asyncio.wait_for(writer_task, timeout=1)
    assert executor.closed is True


@pytest.mark.asyncio
async def test_concurrent_duplicate_submission_adds_one_stream_entry(
    redis_manager: _RedisManager,
) -> None:
    client = DatabaseWriteClient(redis_manager, producer_id="worker")

    command_ids = await asyncio.gather(
        *(
            client.enqueue(
                DatabaseWriteOperation.SYNC_JOB_STATUS,
                {"job_id": "job-deduplicated", "status": "running"},
                command_id="same-command",
            )
            for _ in range(100)
        )
    )

    assert set(command_ids) == {"same-command"}
    assert await redis_manager.client.xlen(DatabaseWriteClient.STREAM_KEY) == 1


@pytest.mark.asyncio
async def test_result_written_before_ack_prevents_duplicate_sql_after_crash(
    redis_manager: _RedisManager,
) -> None:
    client = DatabaseWriteClient(redis_manager)
    first_executor = _RecordingExecutor()
    first = DatabaseWriterService(
        redis_manager,
        first_executor,
        consumer_name="writer-before-crash",
        block_ms=1,
    )
    await first._ensure_group()
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        {"job_id": "job-crash", "status": "completed"},
        command_id="crash-safe-command",
    )
    entries = await first._read_new_entries()

    async def crash_before_ack(_entries: object) -> None:
        raise RuntimeError("writer process crashed")

    first._ack_and_delete_many = crash_before_ack  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="writer process crashed"):
        await first._process_entries(entries)

    assert len(first_executor.batches) == 1
    assert await redis_manager.client.get(
        DatabaseWriteClient.result_key("crash-safe-command")
    )
    assert (
        await redis_manager.client.get(
            DatabaseWriteClient.submitted_key("crash-safe-command")
        )
        is None
    )

    replacement_executor = _RecordingExecutor()
    replacement = DatabaseWriterService(
        redis_manager,
        replacement_executor,
        consumer_name="writer-after-crash",
        block_ms=1,
    )
    await replacement._process_entries(entries)

    assert replacement_executor.batches == []
    assert await redis_manager.client.xlen(DatabaseWriteClient.STREAM_KEY) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_completion_between_retry_lookup_and_enqueue_remains_terminal(
    redis_manager: _RedisManager,
    monkeypatch: pytest.MonkeyPatch,
    fails: bool,
) -> None:
    client = DatabaseWriteClient(redis_manager)
    executor = _RecordingExecutor(failures=int(fails))
    writer = DatabaseWriterService(
        redis_manager,
        executor,
        max_attempts=1,
        block_ms=1,
    )
    await writer._ensure_group()
    command_id = "completion-races-retry"
    payload = {"job_id": "job-race", "status": "completed"}
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        payload,
        command_id=command_id,
    )
    result_key = client.result_key(command_id)
    original_get = redis_manager.client.get
    raced = False

    async def complete_after_lookup(key: str) -> Any:
        nonlocal raced
        value = await original_get(key)
        if key == result_key and not raced:
            raced = True
            assert value is None
            await writer._process_entries(await writer._read_new_entries())
        return value

    monkeypatch.setattr(redis_manager.client, "get", complete_after_lookup)
    if fails:
        with pytest.raises(DatabaseWriteRejected, match="database unavailable"):
            await client.enqueue(
                DatabaseWriteOperation.SYNC_JOB_STATUS,
                payload,
                command_id=command_id,
            )
    else:
        assert (
            await client.enqueue(
                DatabaseWriteOperation.SYNC_JOB_STATUS,
                payload,
                command_id=command_id,
            )
            == command_id
        )

    assert raced
    assert len(executor.batches) == 1
    assert await redis_manager.client.xlen(DatabaseWriteClient.STREAM_KEY) == 0
    assert await original_get(client.submitted_key(command_id)) is None


@pytest.mark.asyncio
async def test_stale_pending_entry_is_reclaimed_and_retried(
    redis_manager: _RedisManager,
) -> None:
    client = DatabaseWriteClient(redis_manager)
    abandoned = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(),
        consumer_name="failed-writer",
        max_attempts=3,
        reclaim_idle_ms=1,
        block_ms=1,
    )
    await abandoned._ensure_group()
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        {"job_id": "job-retry", "status": "completed"},
        command_id="retry-command",
    )
    entries = await abandoned._read_new_entries()
    assert len(entries) == 1

    await asyncio.sleep(0.01)
    replacement_executor = _RecordingExecutor()
    replacement = DatabaseWriterService(
        redis_manager,
        replacement_executor,
        consumer_name="replacement-writer",
        max_attempts=3,
        reclaim_idle_ms=1,
        block_ms=1,
    )
    reclaimed = await replacement._claim_stale_entries()
    assert len(reclaimed) == 1

    await replacement._process_entries(reclaimed)
    assert await client.wait_for_result("retry-command", timeout_seconds=1) == {
        "committed": True
    }
    assert len(replacement_executor.batches) == 1
    assert await redis_manager.client.xlen(DatabaseWriteClient.STREAM_KEY) == 0


@pytest.mark.asyncio
async def test_replacement_writer_does_not_overtake_unreclaimable_pending_entry(
    redis_manager: _RedisManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DatabaseWriteClient(redis_manager)
    abandoned = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(),
        consumer_name="writer-that-crashed",
        reclaim_idle_ms=1_000,
        block_ms=1,
    )
    await abandoned._ensure_group()
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        {"job_id": "job-ordered", "sequence": 0},
        command_id="pending-first",
    )
    assert len(await abandoned._read_new_entries()) == 1
    await client.enqueue(
        DatabaseWriteOperation.ARCHIVE_JOB_TASKS,
        {"job_id": "job-ordered", "sequence": 1},
        command_id="newer-second",
    )

    replacement = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(),
        consumer_name="replacement-writer",
        reclaim_idle_ms=1_000,
        block_ms=1,
    )

    checked_recovery = asyncio.Event()
    claim = replacement._claim_stale_entries

    async def observe_recovery():
        entries = await claim()
        assert entries == []
        checked_recovery.set()
        return entries

    monkeypatch.setattr(replacement, "_claim_stale_entries", observe_recovery)
    running = asyncio.create_task(replacement.run())
    try:
        await asyncio.wait_for(checked_recovery.wait(), timeout=0.5)
        assert replacement.executor.batches == []
        assert await replacement._pending_entry_count() == 1
        assert await redis_manager.client.xlen(client.STREAM_KEY) == 2
    finally:
        replacement.stop()
        await asyncio.wait_for(running, timeout=1)


@pytest.mark.asyncio
async def test_permanent_failure_is_visible_and_dead_lettered(
    redis_manager: _RedisManager,
) -> None:
    client = DatabaseWriteClient(redis_manager)
    service = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(failures=1),
        consumer_name="rejecting-writer",
        max_attempts=1,
        block_ms=1,
    )
    await service._ensure_group()
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        {"job_id": "job-rejected", "status": "failed"},
        command_id="rejected-command",
    )
    await service._process_entries(await service._read_new_entries())

    with pytest.raises(DatabaseWriteRejected, match="database unavailable"):
        await client.wait_for_result("rejected-command", timeout_seconds=1)
    assert await redis_manager.client.xlen(service.DEAD_LETTER_STREAM) == 1
    assert await redis_manager.client.xlen(DatabaseWriteClient.STREAM_KEY) == 0
    assert (
        await redis_manager.client.get(
            DatabaseWriteClient.submitted_key("rejected-command")
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("with_neighbor", [False, True])
async def test_terminal_rejection_is_not_retried_or_applied_to_neighbor(
    redis_manager, caplog, with_neighbor
):
    class RejectingExecutor(_RecordingExecutor):
        async def execute_batch(self, commands):
            if any(command.command_id == "missing-archive-proof" for command in commands):
                self.batches.append(list(commands))
                raise DatabaseWriteRejected("Task archive proof is unavailable; retaining job")
            return await super().execute_batch(commands)

    client = DatabaseWriteClient(redis_manager)
    executor = RejectingExecutor()
    service = DatabaseWriterService(redis_manager, executor, max_attempts=8, block_ms=1)
    await service._ensure_group()
    for command_id in (["missing-archive-proof", "valid-neighbor"] if with_neighbor else ["missing-archive-proof"]):
        await client.enqueue(
            DatabaseWriteOperation.ARCHIVE_JOB_TASKS,
            {"job_id": "same-lane", "generation": "fixture"},
            command_id=command_id,
        )
    entries = await service._read_new_entries()
    pending = [service._parse_entry(entry) for entry in entries]
    assert await service._execute_and_ack_batch(pending) == []
    assert len(executor.batches) == (3 if with_neighbor else 1)
    with pytest.raises(DatabaseWriteRejected, match="proof is unavailable"):
        await client.wait_for_result("missing-archive-proof", timeout_seconds=1)
    if with_neighbor:
        assert await client.wait_for_result("valid-neighbor", timeout_seconds=1) == {"committed": True}
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 0
    assert await redis_manager.client.xlen(service.DEAD_LETTER_STREAM) == 1
    assert executor.receipts["missing-archive-proof"].success is False
    assert "failed after 8" not in executor.receipts["missing-archive-proof"].error
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.asyncio
async def test_rejection_batch_split_keeps_transient_sibling_ahead_of_later_work(
    redis_manager
):
    class MixedExecutor(_RecordingExecutor):
        async def execute_batch(self, commands):
            self.batches.append(list(commands))
            if len(commands) > 1 or commands[0].command_id == "rejected":
                raise DatabaseWriteRejected("Missing archive proof")
            if commands[0].command_id == "transient":
                raise RuntimeError("Database unavailable")
            pytest.fail("Later command overtook its transient predecessor")

    client = DatabaseWriteClient(redis_manager)
    executor = MixedExecutor()
    service = DatabaseWriterService(redis_manager, executor, max_attempts=8, block_ms=1)
    await service._ensure_group()
    for command_id in ("rejected", "transient", "later"):
        await client.enqueue(DatabaseWriteOperation.ARCHIVE_JOB_TASKS,
                             {"job_id": "same-lane", "generation": "fixture"}, command_id=command_id)
    pending = [service._parse_entry(entry) for entry in await service._read_new_entries()]
    assert await service._execute_and_ack_batch(pending) == pending[1:]
    assert len(executor.batches) == 3
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 2
    assert list(executor.receipts) == ["rejected"]


@pytest.mark.asyncio
async def test_rejected_command_is_retained_when_failure_receipt_cannot_commit(
    redis_manager
):
    class UnavailableReceiptExecutor(_RecordingExecutor):
        async def execute_batch(self, commands):
            raise DatabaseWriteRejected("Missing archive proof")

        async def persist_outcome(self, command, result):
            raise RuntimeError("Receipt database unavailable")

    client = DatabaseWriteClient(redis_manager)
    service = DatabaseWriterService(redis_manager, UnavailableReceiptExecutor(), block_ms=1)
    await service._ensure_group()
    await client.enqueue(DatabaseWriteOperation.ARCHIVE_JOB_TASKS,
                         {"job_id": "legacy", "generation": "fixture"}, command_id="unreceipted")
    pending = [service._parse_entry(entry) for entry in await service._read_new_entries()]
    with pytest.raises(RuntimeError, match="Receipt database unavailable"):
        await service._execute_and_ack_batch(pending)
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 1
    assert await service._pending_entry_count() == 1
    assert await redis_manager.client.xlen(service.DEAD_LETTER_STREAM) == 0


@pytest.mark.asyncio
async def test_unparseable_entry_is_dead_lettered_without_empty_mget(
    redis_manager: _RedisManager,
) -> None:
    service = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(),
        consumer_name="invalid-entry-writer",
        block_ms=1,
    )
    await service._ensure_group()
    await redis_manager.client.xadd(
        DatabaseWriteClient.STREAM_KEY,
        {"unexpected": "field"},
    )

    await service._process_entries(await service._read_new_entries())

    assert await redis_manager.client.xlen(service.DEAD_LETTER_STREAM) == 1
    assert await redis_manager.client.xlen(DatabaseWriteClient.STREAM_KEY) == 0


@pytest.mark.asyncio
async def test_writer_concurrency_is_fixed_for_many_producers(
    redis_manager: _RedisManager,
) -> None:
    client = DatabaseWriteClient(redis_manager)
    executor = _RecordingExecutor(delay=0.02)
    service = DatabaseWriterService(
        redis_manager,
        executor,
        consumer_name="bounded-writer",
        batch_size=200,
        concurrency=4,
        block_ms=1,
    )
    await service._ensure_group()

    await asyncio.gather(
        *(
            client.enqueue(
                DatabaseWriteOperation.UPSERT_USER,
                {
                    "user": {"id": index, "username": f"creator-{index}"},
                },
                command_id=f"command-{index}",
            )
            for index in range(100)
        )
    )
    await service._process_entries(await service._read_new_entries())

    assert sum(len(batch) for batch in executor.batches) == 100
    assert 1 < executor.max_active <= 4
    assert await redis_manager.client.xlen(DatabaseWriteClient.STREAM_KEY) == 0


@pytest.mark.asyncio
async def test_same_record_lane_preserves_cross_operation_order(
    redis_manager: _RedisManager,
) -> None:
    client = DatabaseWriteClient(redis_manager)
    executor = _RecordingExecutor()
    service = DatabaseWriterService(
        redis_manager,
        executor,
        consumer_name="ordered-writer",
        concurrency=4,
        block_ms=1,
    )
    await service._ensure_group()
    operations = (
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        DatabaseWriteOperation.FINALIZE_DOWNLOAD,
        DatabaseWriteOperation.SYNC_JOB_STATUS,
    )
    for index, operation in enumerate(operations):
        await client.enqueue(
            operation,
            {"user_id": 42, "sequence": index},
            command_id=f"ordered-{index}",
        )

    await service._process_entries(await service._read_new_entries())

    assert [command.command_id for batch in executor.batches for command in batch] == [
        "ordered-0",
        "ordered-1",
        "ordered-2",
    ]


@pytest.mark.asyncio
async def test_failed_mutation_cannot_be_overtaken_on_same_record_lane(
    redis_manager: _RedisManager,
) -> None:
    client = DatabaseWriteClient(redis_manager)
    executor = _RecordingExecutor(failures=1)
    service = DatabaseWriterService(
        redis_manager,
        executor,
        consumer_name="ordered-retry-writer",
        concurrency=4,
        max_attempts=3,
        retry_delay_seconds=0.001,
        block_ms=1,
    )
    await service._ensure_group()
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        {"user_id": 42, "sequence": 0},
        command_id="retry-first",
    )
    await client.enqueue(
        DatabaseWriteOperation.FINALIZE_DOWNLOAD,
        {"user_id": 42, "sequence": 1},
        command_id="must-stay-second",
    )

    await service._process_entries(await service._read_new_entries())

    assert [command.command_id for batch in executor.batches for command in batch] == [
        "retry-first",
        "retry-first",
        "must-stay-second",
    ]


@pytest.mark.asyncio
async def test_explicit_invalid_writer_setting_fails_closed(
    redis_manager: _RedisManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ULTIMA_DATABASE_WRITER_CONCURRENCY", "0")

    with pytest.raises(ValueError, match="positive integer"):
        DatabaseWriterService(redis_manager, _RecordingExecutor())


@pytest.mark.asyncio
async def test_command_budget_rejects_before_enqueue_and_preserves_json(
    redis_manager: _RedisManager,
) -> None:
    client = DatabaseWriteClient(redis_manager, max_command_bytes=512)
    payload = {"job_id": "small", "message": "caf\u00e9 \u2764"}
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        payload,
        command_id="within-budget",
    )
    entries = await redis_manager.client.xrange(client.STREAM_KEY)
    encoded = entries[0][1][b"command"]
    assert len(encoded) <= 512
    assert json.loads(encoded)["payload"] == payload

    with pytest.raises(DatabaseWriteRejected, match="512"):
        await client.enqueue(
            DatabaseWriteOperation.SYNC_JOB_STATUS,
            {"message": "\u2764" * 100},
            command_id="over-budget",
        )
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 1
    assert await redis_manager.client.get(client.submitted_key("over-budget")) is None


def test_oversized_command_does_not_allocate_a_second_encoded_copy(monkeypatch) -> None:
    class EncodedJSON(str):
        def encode(self, *args, **kwargs):
            raise AssertionError("allocated an encoded copy after exceeding budget")

    command = DatabaseWriteCommand(
        command_id="oversized",
        operation=DatabaseWriteOperation.SYNC_JOB_STATUS,
        site=None,
        payload={"a": "x" * 1_000},
        producer_id="test",
        created_at="2026-09-05T00:00:00+00:00",
    )
    monkeypatch.setattr(
        DatabaseWriteCommand, "to_json", lambda self: EncodedJSON("x" * 1000)
    )
    with pytest.raises(DatabaseWriteRejected, match="256"):
        command.to_bytes(max_bytes=256)


@pytest.mark.asyncio
async def test_queue_count_backpressure_retains_accepted_work_and_resumes(
    redis_manager,
):
    client = DatabaseWriteClient(
        redis_manager, max_queue_commands=2, enqueue_timeout_seconds=0.02
    )
    for index in range(2):
        await client.enqueue(
            DatabaseWriteOperation.SYNC_JOB_STATUS,
            {"job_id": index},
            command_id=str(index),
        )
    occupied = int(await redis_manager.client.get(client.QUEUED_BYTES_KEY))
    assert occupied > 0
    assert await redis_manager.client.ttl(client.submitted_key("0")) == -1
    assert await redis_manager.client.llen(client.NOTIFY_KEY) == 1
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS, {"job_id": 0}, command_id="0"
    )
    assert int(await redis_manager.client.get(client.QUEUED_BYTES_KEY)) == occupied
    with pytest.raises(DatabaseWriteTimeout, match="was not enqueued"):
        await client.enqueue(
            DatabaseWriteOperation.SYNC_JOB_STATUS, {"job_id": 2}, command_id="2"
        )
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 2
    assert await redis_manager.client.get(client.submitted_key("2")) is None
    writer = DatabaseWriterService(
        redis_manager, _RecordingExecutor(), batch_size=1, block_ms=1
    )
    await writer._ensure_group()
    entries = await writer._read_new_entries()
    await writer._process_entries(entries)
    released = int(await redis_manager.client.get(client.QUEUED_BYTES_KEY))
    assert 0 < released < occupied
    await writer._ack_and_delete_many([(write_queue._decode(entries[0][0]), "0")])
    assert int(await redis_manager.client.get(client.QUEUED_BYTES_KEY)) == released
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS, {"job_id": 2}, command_id="2"
    )
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 2


@pytest.mark.asyncio
async def test_concurrent_producers_cannot_exceed_queue_byte_budget(redis_manager):
    client = DatabaseWriteClient(
        redis_manager,
        max_queue_bytes=700,
        max_queue_commands=100,
        enqueue_timeout_seconds=0.02,
    )
    results = await asyncio.gather(
        *[
            client.enqueue(
                DatabaseWriteOperation.SYNC_JOB_STATUS,
                {"data": "x" * 50},
                command_id=f"bounded-{index}",
            )
            for index in range(20)
        ],
        return_exceptions=True,
    )
    entries = await redis_manager.client.xrange(client.STREAM_KEY)
    actual = sum(len(fields[b"command"]) for _, fields in entries)
    assert 0 < actual <= 700
    assert int(await redis_manager.client.get(client.QUEUED_BYTES_KEY)) == actual
    assert len(entries) == sum(isinstance(result, str) for result in results)
    assert all(isinstance(result, (str, DatabaseWriteTimeout)) for result in results)


@pytest.mark.asyncio
async def test_recovery_and_new_reads_obey_the_same_byte_budget(redis_manager):
    client = DatabaseWriteClient(redis_manager)
    for index in range(5):
        await client.enqueue(
            DatabaseWriteOperation.SYNC_JOB_STATUS,
            {"data": "x" * 100},
            command_id=f"bytes-{index}",
        )
    rows = await redis_manager.client.xrange(client.STREAM_KEY)
    one_size = sum(len(value) for value in rows[0][1].values())
    first = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(),
        batch_size=100,
        batch_max_bytes=one_size * 2,
        block_ms=1,
    )
    await first._ensure_group()
    entries = await first._read_new_entries()
    assert len(entries) == 2
    assert (
        sum(sum(len(value) for value in fields.values()) for _, fields in entries)
        <= one_size * 2
    )
    replacement = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(),
        batch_max_bytes=one_size,
        reclaim_idle_ms=1,
        block_ms=1,
    )
    await asyncio.sleep(0.01)
    reclaimed = await replacement._claim_stale_entries()
    assert len(reclaimed) == 1
    await replacement._process_entries(reclaimed)
    reclaimed_again = await replacement._claim_stale_entries()
    assert len(reclaimed_again) == 1
    await replacement._process_entries(reclaimed_again)
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 3


@pytest.mark.asyncio
async def test_legacy_queue_drains_before_byte_accounting_starts(redis_manager):
    writer = DatabaseWriterService(redis_manager, _RecordingExecutor(), block_ms=1)
    await writer._ensure_group()
    command = DatabaseWriteCommand(
        command_id="legacy",
        operation=DatabaseWriteOperation.SYNC_JOB_STATUS,
        site=None,
        payload={},
        producer_id="old",
        created_at="2026-09-05T00:00:00+00:00",
    )
    await redis_manager.client.xadd(
        DatabaseWriteClient.STREAM_KEY, {"command": command.to_json()}
    )
    client = DatabaseWriteClient(redis_manager, enqueue_timeout_seconds=0.01)
    with pytest.raises(DatabaseWriteTimeout, match="legacy"):
        await client.enqueue(
            DatabaseWriteOperation.SYNC_JOB_STATUS, {}, command_id="new"
        )
    assert await redis_manager.client.get(client.QUEUED_BYTES_KEY) is None
    await writer._process_entries(await writer._read_new_entries())
    await client.enqueue(DatabaseWriteOperation.SYNC_JOB_STATUS, {}, command_id="new")
    await writer._process_entries(await writer._read_new_entries())
    assert int(await redis_manager.client.get(client.QUEUED_BYTES_KEY)) == 0


@pytest.mark.asyncio
async def test_oversized_read_leaves_new_and_pending_commands_intact(redis_manager):
    client = DatabaseWriteClient(redis_manager)
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        {"data": "x" * 1000},
        command_id="large",
    )
    entries = await redis_manager.client.xrange(client.STREAM_KEY)
    writer = DatabaseWriterService(
        redis_manager, _RecordingExecutor(), batch_max_bytes=1, reclaim_idle_ms=1
    )
    await writer._ensure_group()
    with pytest.raises(write_queue.RedisError, match="command remains queued"):
        await writer._read_new_entries()
    assert await writer._pending_entry_count() == 0
    assert await redis_manager.client.xrange(client.STREAM_KEY) == entries
    writer.batch_max_bytes = 10_000
    assert await writer._read_new_entries() == entries
    writer.batch_max_bytes = 1
    await asyncio.sleep(0.01)
    with pytest.raises(write_queue.RedisError, match="command remains queued"):
        await writer._claim_stale_entries()
    assert await writer._pending_entry_count() == 1
    assert await redis_manager.client.xrange(client.STREAM_KEY) == entries


@pytest.mark.asyncio
async def test_cancelled_admission_does_not_drop_or_add_work(redis_manager):
    client = DatabaseWriteClient(redis_manager, max_queue_commands=1)
    await client.enqueue(DatabaseWriteOperation.SYNC_JOB_STATUS, {}, command_id="first")
    waiting = asyncio.create_task(
        client.enqueue(DatabaseWriteOperation.SYNC_JOB_STATUS, {}, command_id="second")
    )
    await asyncio.sleep(0.01)
    assert not waiting.done()
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 1
    assert await redis_manager.client.get(client.submitted_key("second")) is None


@pytest.mark.asyncio
async def test_explicit_submit_timeout_includes_admission(redis_manager, monkeypatch):
    client = DatabaseWriteClient(redis_manager)
    now = [10.0]
    monkeypatch.setattr(write_queue.time, "monotonic", lambda: now[0])

    async def enqueue(*args, **kwargs):
        assert kwargs["timeout_seconds"] == 10
        now[0] += 7
        return "admitted"

    async def wait_for_result(command_id, *, timeout_seconds):
        assert command_id == "admitted"
        assert timeout_seconds == 3
        return {"committed": True}

    monkeypatch.setattr(client, "enqueue", enqueue)
    monkeypatch.setattr(client, "wait_for_result", wait_for_result)
    assert await client.submit(
        DatabaseWriteOperation.SYNC_JOB_STATUS, {}, timeout_seconds=10
    ) == {"committed": True}


def test_explicit_transport_settings_override_environment(
    redis_manager: _RedisManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = {
        "ULTIMA_DATABASE_WRITE_MAX_COMMAND_BYTES": "1024",
        "ULTIMA_DATABASE_WRITE_TIMEOUT_SECONDS": "8",
        "ULTIMA_DATABASE_WRITER_CONCURRENCY": "7",
    }
    monkeypatch.setattr(write_queue, "runtime_env_value", configured.get)
    inferred = DatabaseWriteClient(redis_manager)
    assert inferred.max_command_bytes == 1024
    assert inferred.timeout_seconds == 8
    explicit = DatabaseWriteClient(
        redis_manager, max_command_bytes=2048, timeout_seconds=3
    )
    assert explicit.max_command_bytes == 2048
    assert explicit.timeout_seconds == 3
    service = DatabaseWriterService(redis_manager, _RecordingExecutor(), concurrency=2)
    assert service.concurrency == 2


def test_empty_optional_environment_budgets_use_configured_derivations(
    redis_manager, monkeypatch
):
    configured = {
        "ULTIMA_DATABASE_WRITER_CONCURRENCY": "7",
        "ULTIMA_DATABASE_WRITER_BATCH_SIZE": "11",
        "ULTIMA_DATABASE_WRITE_MAX_COMMAND_BYTES": "1024",
        "ULTIMA_DATABASE_WRITE_QUEUE_MAX_BYTES": "",
        "ULTIMA_DATABASE_WRITE_QUEUE_MAX_COMMANDS": "",
        "ULTIMA_DATABASE_WRITER_BATCH_MAX_BYTES": "",
        "ULTIMA_DATABASE_WRITE_ENQUEUE_TIMEOUT_SECONDS": "",
    }
    monkeypatch.setattr(write_queue, "runtime_env_value", configured.get)
    client = DatabaseWriteClient(redis_manager, timeout_seconds=3)
    assert client.max_queue_bytes == 7 * 1024
    assert client.max_queue_commands == 7 * 11
    assert client.enqueue_timeout_seconds == 3
    service = DatabaseWriterService(redis_manager, _RecordingExecutor(), concurrency=2)
    assert service.batch_max_bytes == 2 * 1024


@pytest.mark.asyncio
async def test_cached_result_is_read_even_after_admission_budget_is_reduced(
    redis_manager,
):
    writer = DatabaseWriterService(redis_manager, _RecordingExecutor(), block_ms=1)
    await writer._ensure_group()
    payload = {"data": "x" * 1000}
    await DatabaseWriteClient(redis_manager).enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS, payload, command_id="old-budget"
    )
    await writer._process_entries(await writer._read_new_entries())
    result = await DatabaseWriteClient(redis_manager, max_command_bytes=1).submit(
        DatabaseWriteOperation.SYNC_JOB_STATUS, payload, command_id="old-budget"
    )
    assert result == {"committed": True}
    assert (
        int(await redis_manager.client.get(DatabaseWriteClient.QUEUED_BYTES_KEY)) == 0
    )


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_invalid_explicit_integer_setting_is_not_replaced_by_default(
    redis_manager: _RedisManager, value: Any
) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        DatabaseWriterService(redis_manager, _RecordingExecutor(), concurrency=value)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True])
def test_invalid_explicit_timeout_is_not_replaced_by_default(
    redis_manager: _RedisManager, value: Any
) -> None:
    with pytest.raises(ValueError, match="positive finite number"):
        DatabaseWriteClient(redis_manager, timeout_seconds=value)


@pytest.mark.asyncio
async def test_receipt_busy_preserves_retry_budget_and_pending_input(redis_manager):
    from ultima_scraper_backend.database.write_receipts import DatabaseWriteReceiptBusy
    class BusyExecutor(_RecordingExecutor):
        async def execute_batch(self, commands):
            raise DatabaseWriteReceiptBusy("fixture owner")
    client = DatabaseWriteClient(redis_manager)
    service = DatabaseWriterService(redis_manager, BusyExecutor(), max_attempts=1, block_ms=1)
    await service._ensure_group()
    await client.enqueue(DatabaseWriteOperation.PREPARE_MPS_JOB, {"job_id":"busy"}, command_id="busy-receipt")
    # MPS submissions use the priority stream.
    pending = [
        service._parse_entry(entry)
        for entry in await service._read_stream_entries(client.PRIORITY_STREAM_KEY)
    ]
    assert pending
    for _ in range(3):
        assert await service._execute_and_ack_batch(pending) == pending
    assert await redis_manager.client.hget(service.ATTEMPTS_KEY, "busy-receipt") is None
    assert await redis_manager.client.xlen(client.PRIORITY_STREAM_KEY) == 1
    assert not service.executor.receipts


@pytest.mark.asyncio
async def test_dense_wave_compacts_invalid_users_without_fixed_shard_fragmentation(redis_manager):
    client = DatabaseWriteClient(redis_manager)
    executor = _RecordingExecutor(delay=0.01)
    service = DatabaseWriterService(redis_manager, executor, batch_size=100, concurrency=4, block_ms=1)
    await service._ensure_group()
    for index in range(100):
        operation = DatabaseWriteOperation.UPSERT_INVALID_USER if index < 20 else DatabaseWriteOperation.UPSERT_USER
        payload = {"user_id": index} if index < 20 else {"user":{"id":index,"username":str(index)}}
        await client.enqueue(operation, payload, command_id=f"dense-wave-{index}", site="onlyfans")
    await service._process_entries(await service._read_new_entries())
    invalid_batches = [batch for batch in executor.batches if batch[0].operation == DatabaseWriteOperation.UPSERT_INVALID_USER]
    assert [len(batch) for batch in invalid_batches] == [20]
    assert sum(len(batch) for batch in executor.batches) == 100
    assert 1 < executor.max_active <= 4


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_skipping_the_result_precheck_keeps_completed_commands_terminal(
    redis_manager: _RedisManager,
    monkeypatch: pytest.MonkeyPatch,
    fails: bool,
) -> None:
    client = DatabaseWriteClient(redis_manager)
    executor = _RecordingExecutor(failures=int(fails))
    writer = DatabaseWriterService(redis_manager, executor, max_attempts=1, block_ms=1)
    await writer._ensure_group()
    command_id = "precheck-skipped-retry"
    payload = {"job_id": "job-precheck", "status": "completed"}
    await client.enqueue(DatabaseWriteOperation.SYNC_JOB_STATUS, payload, command_id=command_id)
    await writer._process_entries(await writer._read_new_entries())

    monkeypatch.setenv("ULTIMA_DATABASE_ENQUEUE_SKIP_RESULT_PRECHECK", "1")
    reads = []
    original_get = redis_manager.client.get

    async def counted_get(key: str) -> Any:
        reads.append(key)
        return await original_get(key)

    monkeypatch.setattr(redis_manager.client, "get", counted_get)
    if fails:
        with pytest.raises(DatabaseWriteRejected, match="database unavailable"):
            await client.enqueue(DatabaseWriteOperation.SYNC_JOB_STATUS, payload, command_id=command_id)
    else:
        assert await client.enqueue(
            DatabaseWriteOperation.SYNC_JOB_STATUS, payload, command_id=command_id
        ) == command_id
    # The enqueue script returned the published result; no separate read ran.
    assert client.result_key(command_id) not in reads
    assert len(executor.batches) == 1
    assert await redis_manager.client.xlen(DatabaseWriteClient.STREAM_KEY) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped", [False, True])
async def test_stale_attempt_rejects_only_its_command_not_the_batch(redis_manager, wrapped):
    from ultima_scraper_backend.job_system.ledger import StaleAttempt

    class FencedExecutor(_RecordingExecutor):
        async def execute_batch(self, commands):
            if any(command.command_id == "replaced-attempt" for command in commands):
                self.batches.append(list(commands))
                stale = StaleAttempt("Database mutation belongs to an expired or cancelled attempt")
                if not wrapped:
                    raise stale
                raise RuntimeError("batch transaction failed") from stale
            return await super().execute_batch(commands)

    client = DatabaseWriteClient(redis_manager)
    executor = FencedExecutor()
    service = DatabaseWriterService(redis_manager, executor, max_attempts=8, block_ms=1)
    await service._ensure_group()
    for command_id in ("valid-before", "replaced-attempt", "valid-after"):
        await client.enqueue(
            DatabaseWriteOperation.SYNC_JOB_STATUS,
            {"job_id": "fenced", "status": "completed"},
            command_id=command_id,
        )
    pending = [service._parse_entry(entry) for entry in await service._read_new_entries()]
    # One pass: the batch splits instead of being retried as a whole.
    assert await service._execute_and_ack_batch(pending) == []
    for command_id in ("valid-before", "valid-after"):
        assert await client.wait_for_result(command_id, timeout_seconds=1) == {"committed": True}
    with pytest.raises(DatabaseWriteRejected, match="expired or cancelled attempt"):
        await client.wait_for_result("replaced-attempt", timeout_seconds=1)
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 0
    assert await redis_manager.client.xlen(service.DEAD_LETTER_STREAM) == 1
    assert "failed after" not in executor.receipts["replaced-attempt"].error
