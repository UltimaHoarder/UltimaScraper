"""Writer scheduling through disposable Redis, without a live archive."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteClient,
    DatabaseWriteCommand,
    DatabaseWriteOperation,
    DatabaseWriterService,
)

from test_database_write_queue import _RecordingExecutor, redis_manager
from test_database_write_receipts import (
    download_command,
    postgres_engine,
    receipt_runtime,
)

__all__ = ["redis_manager", "postgres_engine", "receipt_runtime"]


def other_shard(service, target):
    def command(identifier):
        return DatabaseWriteCommand(
            str(identifier),
            DatabaseWriteOperation.UPSERT_USER,
            "onlyfans",
            {"user": {"id": identifier}},
            "fixture",
            "2026-09-07T00:00:00Z",
        )

    first = service._command_shard(command(target))
    return next(
        value
        for value in range(target + 1, target + 100)
        if service._command_shard(command(value)) != first
    )


def same_shard(service, target):
    def command(identifier):
        return DatabaseWriteCommand(
            str(identifier),
            DatabaseWriteOperation.UPSERT_USER,
            "onlyfans",
            {"user": {"id": identifier}},
            "fixture",
            "2026-09-07T00:00:00Z",
        )

    first = service._command_shard(command(target))
    return next(
        value
        for value in range(target + 1, target + 100)
        if service._command_shard(command(value)) == first
    )


async def enqueue_user(client, identifier, command_id):
    return await client.enqueue(
        DatabaseWriteOperation.UPSERT_USER,
        {"user": {"id": identifier}},
        site="onlyfans",
        command_id=command_id,
    )


def test_writer_ordering_domains_keep_user_and_subscriber_mutations_together():
    user = DatabaseWriteCommand(
        "user",
        DatabaseWriteOperation.UPSERT_USER,
        "onlyfans",
        {"user": {"id": 42}},
        "fixture",
        "2026-09-07T00:00:00Z",
    )
    subscription = DatabaseWriteCommand(
        "subscription",
        DatabaseWriteOperation.UPSERT_SUBSCRIPTIONS,
        "onlyfans",
        {"subscriber_id": 42},
        "fixture",
        "2026-09-07T00:00:00Z",
    )

    assert DatabaseWriterService._command_identity(user) == ("user", 42)
    assert DatabaseWriterService._command_identity(subscription) == ("user", 42)


async def test_refill_merges_into_waiting_lane_successor(redis_manager):
    release_predecessor = asyncio.Event()
    executor = _RecordingExecutor()
    service = DatabaseWriterService(
        redis_manager,
        executor,
        batch_size=100,
        concurrency=1,
    )
    await service._ensure_group()

    async def wait_for_predecessor():
        await release_predecessor.wait()

    predecessor = asyncio.create_task(wait_for_predecessor())
    first = DatabaseWriteCommand(
        "first",
        DatabaseWriteOperation.UPSERT_USER,
        "onlyfans",
        {"user": {"id": 1}},
        "fixture",
        "2026-09-07T00:00:00Z",
    )
    second = DatabaseWriteCommand(
        "second",
        DatabaseWriteOperation.UPSERT_USER,
        "onlyfans",
        {"user": {"id": 2}},
        "fixture",
        "2026-09-07T00:00:00Z",
    )
    # The first record has real prior work; a rotating execution label alone
    # must not keep unrelated records waiting when a SQL slot is available.
    service._identity_tails[service._writer_identity_key(first)] = predecessor
    stopping = asyncio.Event()

    first_tasks = service._start_lanes(
        [("1-0", first)],
        {"1-0": 10},
        stopping,
    )
    second_tasks = service._start_lanes(
        [("2-0", second)],
        {"2-0": 20},
        stopping,
    )

    lane_task = next(iter(first_tasks))
    assert next(iter(second_tasks)) is lane_task
    assert second_tasks[lane_task] == (2, 30)
    release_predecessor.set()
    await lane_task

    assert [[command.command_id for command in batch] for batch in executor.batches] == [
        ["first", "second"]
    ]


async def test_open_lane_flushes_when_batch_target_is_reached(
    redis_manager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ULTIMA_DATABASE_WRITER_BATCH_MAX_WAIT_MS", "200")
    executor = _RecordingExecutor()
    service = DatabaseWriterService(
        redis_manager,
        executor,
        batch_size=2,
        concurrency=1,
    )
    stopping = asyncio.Event()
    commands = [
        DatabaseWriteCommand(
            command_id,
            DatabaseWriteOperation.UPSERT_USER,
            "onlyfans",
            {"user": {"id": index}},
            "fixture",
            "2026-09-07T00:00:00Z",
        )
        for index, command_id in enumerate(("first", "second"), start=1)
    ]

    first_tasks = service._start_lanes(
        [("1-0", commands[0])],
        {"1-0": 10},
        stopping,
    )
    lane_task = next(iter(first_tasks))
    await asyncio.sleep(0.01)
    assert executor.batches == []

    second_tasks = service._start_lanes(
        [("2-0", commands[1])],
        {"2-0": 10},
        stopping,
    )
    assert next(iter(second_tasks)) is lane_task
    await asyncio.wait_for(lane_task, timeout=0.1)

    assert [[command.command_id for command in batch] for batch in executor.batches] == [
        ["first", "second"]
    ]


async def test_open_lane_flushes_when_maximum_age_expires(
    redis_manager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ULTIMA_DATABASE_WRITER_BATCH_MAX_WAIT_MS", "10")
    executor = _RecordingExecutor()
    service = DatabaseWriterService(
        redis_manager,
        executor,
        batch_size=100,
        concurrency=1,
    )
    command = DatabaseWriteCommand(
        "single",
        DatabaseWriteOperation.UPSERT_USER,
        "onlyfans",
        {"user": {"id": 1}},
        "fixture",
        "2026-09-07T00:00:00Z",
    )
    started = time.monotonic()
    lane_task = next(
        iter(
            service._start_lanes(
                [("1-0", command)],
                {"1-0": 10},
                asyncio.Event(),
            )
        )
    )

    await asyncio.wait_for(lane_task, timeout=0.1)

    assert time.monotonic() - started >= 0.008
    assert [[item.command_id for item in batch] for batch in executor.batches] == [
        ["single"]
    ]


async def test_backlogged_users_form_multi_command_lane_batches(redis_manager):
    executor = _RecordingExecutor()
    service = DatabaseWriterService(
        redis_manager,
        executor,
        batch_size=100,
        concurrency=8,
        block_ms=5,
    )
    assert service.refill_min_commands_per_lane == 50
    assert service.refill_min_commands == 400
    assert service.window_commands == 800
    client = DatabaseWriteClient(
        redis_manager,
        max_queue_commands=1_000,
        max_queue_bytes=64 * 1024 * 1024,
    )
    for identifier in range(800):
        await enqueue_user(client, identifier, f"user-{identifier}")

    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(8):
            while await redis_manager.client.xlen(client.STREAM_KEY):
                await asyncio.sleep(0.005)
    finally:
        service.stop()
        await asyncio.wait_for(writer, timeout=3)

    batch_sizes = [len(batch) for batch in executor.batches]
    assert sum(batch_sizes) == 800
    assert max(batch_sizes) >= 90
    assert sum(batch_sizes) / len(batch_sizes) >= 50


async def test_large_writer_windows_refill_at_half_capacity(redis_manager):
    eight_lanes = DatabaseWriterService(
        redis_manager, _RecordingExecutor(), batch_size=100, concurrency=8
    )
    twelve_lanes = DatabaseWriterService(
        redis_manager, _RecordingExecutor(), batch_size=100, concurrency=12
    )

    assert eight_lanes.refill_min_commands_per_lane == 50
    assert eight_lanes.refill_min_commands == 400
    assert eight_lanes.window_commands == 800
    assert twelve_lanes.refill_min_commands_per_lane == 50
    assert twelve_lanes.refill_min_commands == 600
    assert twelve_lanes.window_commands == 1_200


async def test_explicit_writer_refill_threshold_remains_authoritative(
    redis_manager,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ULTIMA_DATABASE_WRITER_REFILL_MIN_COMMANDS", "75")
    service = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(),
        batch_size=100,
        concurrency=8,
    )

    assert service.refill_min_commands_per_lane == 75
    assert service.refill_min_commands == 600


async def test_mixed_operation_backlog_retains_dense_domain_batches(redis_manager):
    executor = _RecordingExecutor()
    service = DatabaseWriterService(
        redis_manager,
        executor,
        batch_size=100,
        concurrency=8,
        block_ms=5,
    )
    client = DatabaseWriteClient(
        redis_manager,
        max_queue_commands=1_000,
        max_queue_bytes=64 * 1024 * 1024,
    )
    for identifier in range(400):
        await enqueue_user(client, identifier, f"user-{identifier}")
        await client.enqueue(
            DatabaseWriteOperation.SYNC_TASK_STATUS,
            {"task_id": f"task-{identifier}", "job_id": "job-mixed"},
            command_id=f"status-{identifier}",
        )

    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(8):
            while await redis_manager.client.xlen(client.STREAM_KEY):
                await asyncio.sleep(0.005)
    finally:
        service.stop()
        await asyncio.wait_for(writer, timeout=3)

    user_batches = [
        len(batch)
        for batch in executor.batches
        if batch[0].operation == DatabaseWriteOperation.UPSERT_USER
    ]
    assert sum(user_batches) == 400
    assert max(user_batches) >= 40
    assert sum(user_batches) / len(user_batches) >= 35


async def test_interleaved_user_operations_compact_into_dense_batches(redis_manager):
    service = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(),
        batch_size=100,
        concurrency=1,
    )
    pending = []
    for identifier in range(50):
        for suffix, operation, payload in (
            (
                "valid",
                DatabaseWriteOperation.UPSERT_USER,
                {"user": {"id": identifier}},
            ),
            (
                "invalid",
                DatabaseWriteOperation.UPSERT_INVALID_USER,
                {"user_id": identifier + 1_000},
            ),
        ):
            entry_id = f"{identifier}-{suffix}"
            pending.append(
                (
                    entry_id,
                    DatabaseWriteCommand(
                        entry_id,
                        operation,
                        "onlyfans",
                        payload,
                        "fixture",
                        "2026-09-07T00:00:00Z",
                    ),
                )
            )

    batches = []
    while pending:
        batches.append(service._take_operation_batch(pending))

    assert [len(batch) for batch in batches] == [50, 50]
    assert all(len({command.operation for _, command in batch}) == 1 for batch in batches)


async def test_interleaved_user_operations_execute_as_dense_batches(redis_manager):
    executor = _RecordingExecutor()
    service = DatabaseWriterService(
        redis_manager,
        executor,
        batch_size=100,
        concurrency=8,
        block_ms=5,
    )
    client = DatabaseWriteClient(
        redis_manager,
        max_queue_commands=2_000,
        max_queue_bytes=64 * 1024 * 1024,
    )
    for identifier in range(800):
        await enqueue_user(client, identifier, f"valid-{identifier}")
        await client.enqueue(
            DatabaseWriteOperation.UPSERT_INVALID_USER,
            {"user_id": identifier + 10_000},
            site="onlyfans",
            command_id=f"invalid-{identifier}",
        )

    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(8):
            while await redis_manager.client.xlen(client.STREAM_KEY):
                await asyncio.sleep(0.005)
    finally:
        service.stop()
        await asyncio.wait_for(writer, timeout=3)

    operation_batches = {
        operation: [
            len(batch)
            for batch in executor.batches
            if batch[0].operation == operation
        ]
        for operation in (
            DatabaseWriteOperation.UPSERT_USER,
            DatabaseWriteOperation.UPSERT_INVALID_USER,
        )
    }
    assert all(len({command.operation for command in batch}) == 1 for batch in executor.batches)
    for batch_sizes in operation_batches.values():
        assert sum(batch_sizes) == 800
        assert max(batch_sizes) >= 40
        assert sum(batch_sizes) / len(batch_sizes) >= 30


async def test_operation_compaction_preserves_same_identity_order(redis_manager):
    service = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(),
        batch_size=100,
        concurrency=1,
    )

    def command(command_id, operation, identifier):
        payload = (
            {"user": {"id": identifier}}
            if operation == DatabaseWriteOperation.UPSERT_USER
            else {"user_id": identifier}
        )
        return (
            command_id,
            DatabaseWriteCommand(
                command_id,
                operation,
                "onlyfans",
                payload,
                "fixture",
                "2026-09-07T00:00:00Z",
            ),
        )

    pending = [command("same-first", DatabaseWriteOperation.UPSERT_USER, 1)]
    pending.extend(
        command(
            f"independent-{identifier}",
            DatabaseWriteOperation.UPSERT_INVALID_USER,
            identifier,
        )
        for identifier in range(2, 42)
    )
    pending.extend(
        [
            command("same-second", DatabaseWriteOperation.UPSERT_INVALID_USER, 1),
            command("same-third", DatabaseWriteOperation.UPSERT_USER, 1),
        ]
    )

    batches = []
    while pending:
        batches.append(service._take_operation_batch(pending))

    assert len(batches[0]) == 40
    same_identity_order = [
        command.command_id
        for batch in batches
        for _, command in batch
        if command.command_id.startswith("same-")
    ]
    assert same_identity_order == ["same-first", "same-second", "same-third"]
    assert all(len({command.operation for _, command in batch}) == 1 for batch in batches)


async def test_per_lane_sql_batch_never_exceeds_configured_target(redis_manager):
    executor = _RecordingExecutor()
    service = DatabaseWriterService(
        redis_manager,
        executor,
        batch_size=100,
        concurrency=8,
        block_ms=5,
    )
    client = DatabaseWriteClient(
        redis_manager,
        max_queue_commands=1_000,
        max_queue_bytes=64 * 1024 * 1024,
    )
    # Fill the 800-command execution window so its eight balanced batches
    # actually reach the configured ceiling, then exercise a rolling refill.
    for index in range(1_000):
        await enqueue_user(client, 1, f"same-user-{index}")

    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(8):
            while await redis_manager.client.xlen(client.STREAM_KEY):
                await asyncio.sleep(0.005)
    finally:
        service.stop()
        await asyncio.wait_for(writer, timeout=3)

    assert sum(len(batch) for batch in executor.batches) == 1_000
    assert max(len(batch) for batch in executor.batches) == 100


@pytest.mark.parametrize("later_record", ["quick", "unrelated"])
async def test_writer_refills_freed_capacity_while_another_lane_is_running(
    redis_manager,
    later_record,
):
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    quick_completed = asyncio.Event()
    later_completed = asyncio.Event()

    class Executor(_RecordingExecutor):
        async def execute_batch(self, commands):
            identifier = commands[0].command_id
            if identifier == "slow":
                slow_started.set()
                await release_slow.wait()
            result = await super().execute_batch(commands)
            if identifier == "quick":
                quick_completed.set()
            if identifier == "later":
                later_completed.set()
            return result

    executor = Executor()
    service = DatabaseWriterService(
        redis_manager, executor, batch_size=2, concurrency=2, block_ms=5
    )
    client = DatabaseWriteClient(redis_manager)
    quick_id = other_shard(service, 1)
    await enqueue_user(client, 1, "slow")
    await enqueue_user(client, quick_id, "quick")
    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(2):
            await slow_started.wait()
            await quick_completed.wait()
            later_id = quick_id if later_record == "quick" else quick_id + 1000
            await enqueue_user(client, later_id, "later")
            await later_completed.wait()
        assert not release_slow.is_set()
    finally:
        release_slow.set()
        service.stop()
        await asyncio.wait_for(writer, timeout=3)


async def test_unrelated_operations_on_one_shard_compete_independently(redis_manager):
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    independent_done = asyncio.Event()

    class Executor(_RecordingExecutor):
        async def execute_batch(self, commands):
            if commands[0].command_id == "slow-valid":
                slow_started.set()
                await release_slow.wait()
            result = await super().execute_batch(commands)
            if commands[0].command_id == "independent-invalid":
                independent_done.set()
            return result

    service = DatabaseWriterService(
        redis_manager,
        Executor(),
        batch_size=2,
        concurrency=2,
        block_ms=5,
    )
    client = DatabaseWriteClient(redis_manager)
    invalid_user_id = same_shard(service, 1)
    await enqueue_user(client, 1, "slow-valid")
    await client.enqueue(
        DatabaseWriteOperation.UPSERT_INVALID_USER,
        {"user_id": invalid_user_id},
        site="onlyfans",
        command_id="independent-invalid",
    )

    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(2):
            await slow_started.wait()
            await independent_done.wait()
        assert not release_slow.is_set()
    finally:
        release_slow.set()
        service.stop()
        await asyncio.wait_for(writer, timeout=3)


async def test_retry_releases_execution_slot_for_an_independent_lane(redis_manager):
    calls = []
    failed = asyncio.Event()
    control_completed = asyncio.Event()

    class Executor(_RecordingExecutor):
        async def execute_batch(self, commands):
            identifier = commands[0].command_id
            calls.append(identifier)
            if identifier == "retry" and calls.count("retry") == 1:
                failed.set()
                raise RuntimeError("fixture transient failure")
            result = await super().execute_batch(commands)
            if identifier == "control":
                control_completed.set()
            return result

    service = DatabaseWriterService(
        redis_manager,
        Executor(),
        concurrency=1,
        retry_delay_seconds=0.3,
        block_ms=5,
    )
    client = DatabaseWriteClient(redis_manager)
    await enqueue_user(client, 1, "retry")
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS,
        {"job_id": "control"},
        command_id="control",
    )
    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(2):
            await failed.wait()
            await control_completed.wait()
        assert calls[:2] == ["retry", "control"]
    finally:
        service.stop()
        await asyncio.wait_for(writer, timeout=3)


async def test_stop_during_backoff_keeps_unexecuted_work_durable(redis_manager):
    failed = asyncio.Event()
    stop_requested = asyncio.Event()
    calls = []

    class Executor(_RecordingExecutor):
        async def execute_batch(self, commands):
            calls.extend(command.command_id for command in commands)
            if len(calls) == 1:
                failed.set()
                raise RuntimeError("fixture transient failure")
            return await super().execute_batch(commands)

    service = DatabaseWriterService(
        redis_manager,
        Executor(),
        retry_delay_seconds=0.1,
        block_ms=5,
    )
    client = DatabaseWriteClient(redis_manager)
    await enqueue_user(client, 1, "first")
    await client.enqueue(
        DatabaseWriteOperation.FINALIZE_DOWNLOAD,
        {"user_id": 1},
        site="onlyfans",
        command_id="must-remain-pending",
    )
    writer = asyncio.create_task(service.run(stop_requested=stop_requested.is_set))
    try:
        async with asyncio.timeout(2):
            await failed.wait()
            stop_requested.set()
            await writer
        assert calls == ["first"]
        assert await redis_manager.client.xlen(client.STREAM_KEY) == 2
        assert await service._pending_entry_count() == 2
    finally:
        service.stop()
        await asyncio.wait_for(writer, timeout=3)


async def test_cancellation_waits_for_owned_database_thread_before_close(redis_manager):
    started = threading.Event()
    release = threading.Event()
    thread_finished = threading.Event()

    class Executor(_RecordingExecutor):
        async def execute_batch(self, commands):
            def database_work():
                started.set()
                assert release.wait(timeout=4)
                thread_finished.set()

            # This regression needs a real owned thread; the suite's Python
            # 3.14 compatibility hook replaces to_thread with an inline call.
            await asyncio.get_running_loop().run_in_executor(None, database_work)
            return await super().execute_batch(commands)

        async def close(self):
            assert thread_finished.is_set(), "closed while database thread was running"
            await super().close()

    executor = Executor()
    service = DatabaseWriterService(redis_manager, executor, block_ms=5)
    client = DatabaseWriteClient(redis_manager)
    await enqueue_user(client, 1, "native-thread")
    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(0.001)
        writer.cancel()
        await asyncio.sleep(0.02)
        assert not writer.done()
        assert not executor.closed
    finally:
        release.set()
        service.stop()
        with pytest.raises(asyncio.CancelledError):
            await writer
    assert thread_finished.is_set() and executor.closed


async def test_refilled_same_record_waits_for_its_predecessor(redis_manager):
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    later_started = asyncio.Event()
    independent_done = asyncio.Event()

    class Executor(_RecordingExecutor):
        async def execute_batch(self, commands):
            identifier = commands[0].command_id
            if identifier == "first":
                first_started.set()
                await release_first.wait()
            if identifier == "later":
                later_started.set()
            result = await super().execute_batch(commands)
            if identifier == "independent":
                independent_done.set()
            return result

    executor = Executor()
    service = DatabaseWriterService(
        redis_manager, executor, batch_size=4, concurrency=2, block_ms=5
    )
    client = DatabaseWriteClient(redis_manager)
    await enqueue_user(client, 1, "first")
    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(2):
            await first_started.wait()
            await client.enqueue(
                DatabaseWriteOperation.FINALIZE_DOWNLOAD,
                {"user_id": 1},
                site="onlyfans",
                command_id="later",
            )
            await enqueue_user(client, other_shard(service, 1), "independent")
            await independent_done.wait()
            assert not later_started.is_set()
            release_first.set()
            await later_started.wait()
    finally:
        release_first.set()
        service.stop()
        await asyncio.wait_for(writer, timeout=3)
    assert not service._lane_tails
    assert not service._identity_tails


@pytest.mark.parametrize("limiting_budget", ["count", "bytes"])
async def test_refill_keeps_aggregate_count_and_bytes_bounded(
    redis_manager, monkeypatch, limiting_budget
):
    client = DatabaseWriteClient(
        redis_manager, max_queue_commands=200, max_queue_bytes=1_000_000
    )
    for index in range(120):
        await client.enqueue(
            DatabaseWriteOperation.UPSERT_USER,
            {"user": {"id": index % 9}, "text": "é" * (index % 3 * 100)},
            site="onlyfans",
            command_id=f"bounded-{index}",
        )
    raw = await redis_manager.client.xrange(client.STREAM_KEY)
    largest = max(sum(len(value) for value in fields.values()) for _, fields in raw)
    service = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(delay=0.002),
        concurrency=3,
        batch_size=3 if limiting_budget == "count" else 20,
        batch_max_bytes=largest * (20 if limiting_budget == "count" else 2),
        block_ms=5,
    )
    owned = {}
    peak_count = peak_bytes = 0
    original_read = service._read_new_entries
    original_ack = service._ack_and_delete_many

    async def read(**kwargs):
        nonlocal peak_count, peak_bytes
        entries = await original_read(**kwargs)
        for identifier, fields in entries:
            owned[
                identifier.decode() if isinstance(identifier, bytes) else identifier
            ] = sum(len(value) for value in fields.values())
        peak_count = max(peak_count, len(owned))
        peak_bytes = max(peak_bytes, sum(owned.values()))
        assert len(owned) <= service.window_commands
        assert sum(owned.values()) <= service.batch_max_bytes
        return entries

    async def ack(entries):
        await original_ack(entries)
        for identifier, _ in entries:
            owned.pop(identifier)

    monkeypatch.setattr(service, "_read_new_entries", read)
    monkeypatch.setattr(service, "_ack_and_delete_many", ack)
    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(6):
            while await redis_manager.client.xlen(client.STREAM_KEY):
                await asyncio.sleep(0.005)
        assert peak_count > 1 and peak_bytes > largest
        assert sum(len(batch) for batch in service.executor.batches) == 120
        assert service.executor.max_active <= service.concurrency
    finally:
        service.stop()
        await asyncio.wait_for(writer, timeout=3)
    assert not owned and not service._lane_tails and not service._identity_tails


async def test_large_next_command_waits_for_full_byte_capacity(
    redis_manager, monkeypatch
):
    started = asyncio.Event()
    release = asyncio.Event()
    partial_read = asyncio.Event()
    large_done = asyncio.Event()

    class Executor(_RecordingExecutor):
        async def execute_batch(self, commands):
            if commands[0].command_id == "held":
                started.set()
                await release.wait()
            result = await super().execute_batch(commands)
            if commands[0].command_id == "large":
                large_done.set()
            return result

    service = DatabaseWriterService(
        redis_manager, Executor(), batch_size=3, concurrency=2, block_ms=5
    )
    client = DatabaseWriteClient(redis_manager)
    second = other_shard(service, 1)
    for name, identifier, size in (
        ("held", 1, 500),
        ("quick", second, 0),
        ("large", second, 900),
    ):
        await client.enqueue(
            DatabaseWriteOperation.UPSERT_USER,
            {"user": {"id": identifier}, "data": "x" * size},
            site="onlyfans",
            command_id=name,
        )
    entries = await redis_manager.client.xrange(client.STREAM_KEY)
    sizes = [sum(len(value) for value in fields.values()) for _, fields in entries]
    service.batch_max_bytes = max(sizes[0] + sizes[1], sizes[2])
    read = service._read_new_entries

    async def observe(**kwargs):
        result = await read(**kwargs)
        if (
            0 < kwargs.get("max_bytes", service.batch_max_bytes) < sizes[2]
            and not result
        ):
            partial_read.set()
        return result

    monkeypatch.setattr(service, "_read_new_entries", observe)
    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(2):
            await started.wait()
            await partial_read.wait()
            assert not writer.done() and not large_done.is_set()
            release.set()
            await large_done.wait()
    finally:
        release.set()
        service.stop()
        await asyncio.wait_for(writer, timeout=3)


async def test_recovery_never_skips_an_older_recently_claimed_entry(redis_manager):
    client = DatabaseWriteClient(redis_manager)
    abandoned = DatabaseWriterService(
        redis_manager, _RecordingExecutor(), consumer_name="old", block_ms=1
    )
    await abandoned._ensure_group()
    await enqueue_user(client, 1, "older")
    await enqueue_user(client, 1, "newer")
    entries = await abandoned._read_new_entries()
    ids = [entry[0] for entry in entries]
    await redis_manager.client.xclaim(
        client.STREAM_KEY, abandoned.CONSUMER_GROUP, "old", 0, ids, idle=100_001
    )
    await redis_manager.client.xclaim(
        client.STREAM_KEY, abandoned.CONSUMER_GROUP, "old", 0, ids[:1], idle=0
    )
    replacement = DatabaseWriterService(
        redis_manager,
        _RecordingExecutor(),
        consumer_name="replacement",
        reclaim_idle_ms=100_000,
        block_ms=1,
    )
    assert await replacement._claim_stale_entries() == []
    await redis_manager.client.xclaim(
        client.STREAM_KEY, abandoned.CONSUMER_GROUP, "old", 0, ids[:1], idle=100_001
    )
    replacement._last_reclaim_at = 0
    reclaimed = await replacement._claim_stale_entries()
    assert [entry[0] for entry in reclaimed] == ids
    await replacement._process_entries(reclaimed)
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 0


async def test_permanent_failure_persistence_respects_writer_concurrency(redis_manager):
    class Executor(_RecordingExecutor):
        persisting = 0
        peak_persisting = 0

        async def execute_batch(self, commands):
            raise RuntimeError("fixture rejected batch")

        async def persist_outcome(self, command, result):
            self.persisting += 1
            self.peak_persisting = max(self.peak_persisting, self.persisting)
            try:
                await asyncio.sleep(0.002)
                return await super().persist_outcome(command, result)
            finally:
                self.persisting -= 1

    executor = Executor()
    service = DatabaseWriterService(
        redis_manager, executor, concurrency=2, max_attempts=1, block_ms=1
    )
    client = DatabaseWriteClient(redis_manager)
    for index in range(20):
        await enqueue_user(client, index, f"failed-{index}")
    await service._ensure_group()
    await service._process_entries(await service._read_new_entries())
    assert 0 < executor.peak_persisting <= service.concurrency
    assert await redis_manager.client.xlen(client.STREAM_KEY) == 0


async def test_cancelled_writer_finishes_native_transaction_and_receipt(
    receipt_runtime, redis_manager, monkeypatch
):
    from ultima_scraper_backend.database import write_queue, write_receipts

    # Hold a genuine database thread across cancellation.
    started = threading.Event()
    release = threading.Event()
    closed = []
    original_mutation = receipt_runtime.manager.mark_media_downloaded

    def hold_transaction(ids, *, session):
        result = original_mutation(ids, session=session)
        started.set()
        assert release.wait(timeout=4)
        return result

    async def close():
        assert receipt_runtime.written() == 1
        closed.append(True)

    monkeypatch.setattr(
        receipt_runtime.manager, "mark_media_downloaded", hold_transaction
    )
    monkeypatch.setattr(receipt_runtime.executor, "close", close)
    monkeypatch.setattr(
        write_queue,
        "_lookup_write_receipt",
        lambda key: write_receipts.lookup([key]).get(key),
    )
    service = DatabaseWriterService(redis_manager, receipt_runtime.executor, block_ms=5)
    client = DatabaseWriteClient(redis_manager)
    command = download_command("cancelled-native-write")
    await client.enqueue(
        command.operation,
        command.payload,
        site=command.site,
        command_id=command.command_id,
    )
    writer = asyncio.create_task(service.run())
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(0.001)
        assert receipt_runtime.written() == 0
        writer.cancel()
        await asyncio.sleep(0.02)
        assert not writer.done() and not closed
        writer.cancel()  # Repeated cancellation must still retain ownership.
    finally:
        release.set()
        service.stop()
        with pytest.raises(asyncio.CancelledError):
            await writer
    assert closed == [True]
    assert write_receipts.lookup([command.command_id])[command.command_id].success
    await receipt_runtime.executor.execute_batch([command])
    assert receipt_runtime.written() == 1


async def test_notification_does_not_occupy_the_only_redis_connection(
    redis_manager, monkeypatch
):
    from redis.asyncio import BlockingConnectionPool, Redis

    original_client = redis_manager.client
    base_pool = original_client.connection_pool
    pool = BlockingConnectionPool(
        connection_class=base_pool.connection_class,
        max_connections=1,
        timeout=2,
        **base_pool.connection_kwargs,
    )
    constrained = Redis(connection_pool=pool)
    redis_manager.client = constrained
    service = DatabaseWriterService(
        redis_manager, _RecordingExecutor(delay=0.02), block_ms=1_000,
    )
    acknowledged = asyncio.Event()
    original_ack = service._ack_and_delete_many

    async def ack(entries):
        await original_ack(entries)
        acknowledged.set()

    monkeypatch.setattr(service, "_ack_and_delete_many", ack)
    writer = None
    try:
        await enqueue_user(DatabaseWriteClient(redis_manager), 1, "one-connection")
        writer = asyncio.create_task(service.run())
        async with asyncio.timeout(0.5):
            await acknowledged.wait()
    finally:
        service.stop()
        if writer is not None:
            await asyncio.wait_for(writer, timeout=3)
        redis_manager.client = original_client
        await constrained.aclose()
        await pool.disconnect()
