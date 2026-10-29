"""Several database-writer processes share the queue by identity partitions."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import fakeredis
import pytest

import main as runtime_main
from test_database_write_queue import _RecordingExecutor, redis_manager
from test_runtime_launcher import FakeProcess
from ultima_scraper_backend.database import writer_runtime
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteClient,
    DatabaseWriteCommand,
    DatabaseWriteOperation,
    DatabaseWriteTimeout,
    DatabaseWriterService,
)

__all__ = ["redis_manager"]

LAYOUT = DatabaseWriteClient.LAYOUT_KEY


def _command(operation, payload, command_id="probe", site="onlyfans"):
    return DatabaseWriteCommand(
        command_id=command_id, operation=operation, site=site, payload=payload,
        producer_id="test", created_at="2026-10-22T00:00:00+00:00",
    )


def _user_in_partition(partition: int, partitions: int = 2, start: int = 1) -> int:
    user_id = start
    while DatabaseWriteClient.command_partition(
        _command(DatabaseWriteOperation.UPSERT_USER, {"user": {"id": user_id}}), partitions
    ) != partition:
        user_id += 1
    return user_id


async def _stream_ids(client, partition: int) -> list[str]:
    stream = DatabaseWriteClient.partition_keys(partition)[0]
    return [entry[0].decode() for entry in await client.xrange(stream)]


async def test_one_process_layout_uses_only_the_original_stream_keys(redis_manager):
    client = DatabaseWriteClient(redis_manager)
    for user_id in range(20):
        await client.enqueue(
            DatabaseWriteOperation.UPSERT_USER, {"user": {"id": user_id}},
            site="onlyfans", command_id=f"user-{user_id}",
        )
    redis = redis_manager.client
    assert DatabaseWriteClient.partition_keys(0) == (
        DatabaseWriteClient.STREAM_KEY,
        DatabaseWriteClient.QUEUED_BYTES_KEY,
        DatabaseWriteClient.NOTIFY_KEY,
    )
    assert await redis.xlen(DatabaseWriteClient.STREAM_KEY) == 20
    assert await redis.get(LAYOUT) is None
    assert sorted(key.decode() for key in await redis.keys("*database:writes:p*")) == []
    assert DatabaseWriteClient.command_partition(
        _command(DatabaseWriteOperation.UPSERT_USER, {"user": {"id": 7}}), 1
    ) == 0


async def test_partitioned_enqueue_keeps_each_record_on_one_stream(redis_manager):
    redis = redis_manager.client
    await redis.set(LAYOUT, "3")
    client = DatabaseWriteClient(redis_manager)
    records = {}
    for user_id in range(30):
        for sequence, (operation, payload) in enumerate((
            (DatabaseWriteOperation.UPSERT_USER, {"user": {"id": user_id}}),
            (DatabaseWriteOperation.UPSERT_CONTENT_BATCH, {"user_id": user_id}),
            (DatabaseWriteOperation.UPSERT_SUBSCRIPTIONS, {"subscriber_id": user_id}),
        )):
            command_id = f"{user_id}-{sequence}"
            records[command_id] = user_id
            await client.enqueue(operation, payload, site="onlyfans", command_id=command_id)
    streams_by_user: dict[int, set[int]] = {}
    for partition in range(3):
        stream = DatabaseWriteClient.partition_keys(partition)[0]
        rows = await redis.xrange(stream)
        assert rows, f"partition {partition} received no work"
        for _, fields in rows:
            command = DatabaseWriteCommand.from_json(fields[b"command"])
            streams_by_user.setdefault(records[command.command_id], set()).add(partition)
    assert all(len(partitions) == 1 for partitions in streams_by_user.values())
    assert len(streams_by_user) == 30


async def test_producer_with_a_stale_layout_is_rerouted_atomically(redis_manager):
    redis = redis_manager.client
    client = DatabaseWriteClient(redis_manager)
    await client.enqueue(
        DatabaseWriteOperation.UPSERT_USER, {"user": {"id": 1}},
        site="onlyfans", command_id="before",
    )
    assert client._partitions == 1
    await redis.set(LAYOUT, "2")
    user_id = _user_in_partition(1)
    await client.enqueue(
        DatabaseWriteOperation.UPSERT_USER, {"user": {"id": user_id}},
        site="onlyfans", command_id="after",
    )
    assert client._partitions == 2
    assert len(await _stream_ids(redis, 1)) == 1
    assert await redis.xlen(DatabaseWriteClient.STREAM_KEY) == 1


async def test_bulk_producers_wait_while_the_layout_switches(redis_manager):
    redis = redis_manager.client
    await redis.set(LAYOUT, "1>2")
    client = DatabaseWriteClient(redis_manager, enqueue_timeout_seconds=0.05)
    with pytest.raises(DatabaseWriteTimeout, match="switching"):
        await client.enqueue(
            DatabaseWriteOperation.UPSERT_USER, {"user": {"id": 1}},
            site="onlyfans", command_id="blocked",
        )
    assert await redis.xlen(DatabaseWriteClient.STREAM_KEY) == 0
    # Priority commands are not partitioned and are still admitted.
    await client.enqueue(
        DatabaseWriteOperation.PREPARE_MPS_JOB, {"job_id": "job-new"},
        site="onlyfans", command_id="priority",
    )
    assert await redis.xlen(DatabaseWriteClient.PRIORITY_STREAM_KEY) == 1
    # Completing the switch admits the waiting producer's next attempt.
    await redis.set(LAYOUT, "2")
    await client.enqueue(
        DatabaseWriteOperation.UPSERT_USER, {"user": {"id": 1}},
        site="onlyfans", command_id="blocked",
    )
    assert client._partitions == 2


def test_partition_entry_ids_map_back_to_their_stream():
    stream, bytes_key, _ = DatabaseWriteClient.partition_keys(3)
    assert DatabaseWriteClient.entry_prefix(stream) == "p3:"
    assert DatabaseWriteClient.entry_stream("p3:1700-0") == (stream, bytes_key, "1700-0")
    assert DatabaseWriteClient.entry_stream("1700-0")[0] == DatabaseWriteClient.STREAM_KEY
    assert DatabaseWriteClient.entry_stream("priority:1700-0")[0] == (
        DatabaseWriteClient.PRIORITY_STREAM_KEY
    )


class _OrderedExecutor(_RecordingExecutor):
    def __init__(self, journal: list, **kwargs) -> None:
        super().__init__(**kwargs)
        self.journal = journal

    async def execute_batch(self, commands: Sequence[DatabaseWriteCommand]):
        result = await super().execute_batch(commands)
        self.journal.extend(
            (command.payload["record"], command.payload["sequence"]) for command in commands
        )
        return result


async def test_two_writer_processes_split_partitions_and_keep_record_order(redis_manager):
    redis = redis_manager.client
    await redis.set(LAYOUT, "2")
    journal: list[tuple[int, int]] = []
    executors = [_OrderedExecutor(journal, delay=0.001) for _ in range(2)]
    services = [
        DatabaseWriterService(
            redis_manager, executor, consumer_name=f"writer-{partition}",
            partitions=(partition,), batch_size=8, concurrency=3, block_ms=5,
        )
        for partition, executor in enumerate(executors)
    ]
    assert services[0].consume_priority and not services[1].consume_priority
    running = [asyncio.create_task(service.run()) for service in services]
    client = DatabaseWriteClient(redis_manager)
    operations = (
        DatabaseWriteOperation.UPSERT_USER,
        DatabaseWriteOperation.UPSERT_CONTENT_BATCH,
        DatabaseWriteOperation.UPDATE_MEDIA_SELECTION,
        DatabaseWriteOperation.UPSERT_SUBSCRIPTIONS,
    )
    command_ids = []
    try:
        for sequence, operation in enumerate(operations):
            for record in range(24):
                payload = {"user_id": record, "record": record, "sequence": sequence}
                command_id = f"{record}-{sequence}"
                command_ids.append(command_id)
                await client.enqueue(operation, payload, site="onlyfans", command_id=command_id)
        async with asyncio.timeout(10):
            for command_id in command_ids:
                assert await client.wait_for_result(command_id, timeout_seconds=10) == {
                    "committed": True
                }
    finally:
        for service in services:
            service.stop()
        await asyncio.wait_for(asyncio.gather(*running), timeout=5)

    for partition, executor in enumerate(executors):
        commands = [command for batch in executor.batches for command in batch]
        assert commands, f"writer {partition} did no work"
        assert all(
            DatabaseWriteClient.command_partition(command, 2) == partition
            for command in commands
        )
    for record in range(24):
        sequences = [sequence for item, sequence in journal if item == record]
        assert sequences == list(range(len(operations)))
    for partition in range(2):
        stream, bytes_key, _ = DatabaseWriteClient.partition_keys(partition)
        assert await redis.xlen(stream) == 0
        assert int(await redis.get(bytes_key) or 0) == 0
    assert all(executor.closed for executor in executors)


async def test_reclaim_leaves_a_live_peers_entries_alone(redis_manager):
    redis = redis_manager.client
    client = DatabaseWriteClient(redis_manager)
    live = DatabaseWriterService(
        redis_manager, _RecordingExecutor(), consumer_name="live-peer", reclaim_idle_ms=1
    )
    await live._ensure_group()
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS, {"job_id": "job-a"}, command_id="first"
    )
    assert len(await live._read_new_entries()) == 1
    await redis.set(live.READY_KEY.format(consumer_name="live-peer"), "now")

    crashed = DatabaseWriterService(
        redis_manager, _RecordingExecutor(), consumer_name="crashed", reclaim_idle_ms=1
    )
    await client.enqueue(
        DatabaseWriteOperation.SYNC_JOB_STATUS, {"job_id": "job-b"}, command_id="second"
    )
    assert len(await crashed._read_new_entries()) == 1

    await asyncio.sleep(0.01)
    replacement = DatabaseWriterService(
        redis_manager, _RecordingExecutor(), consumer_name="replacement", reclaim_idle_ms=1
    )
    # The live peer's older entry is idle but owned; it also keeps the dead
    # consumer's newer entry from overtaking it.
    assert await replacement._claim_stale_entries() == []

    await redis.delete(live.READY_KEY.format(consumer_name="live-peer"))
    replacement._last_reclaim_at = 0
    reclaimed = await replacement._claim_stale_entries()
    assert [replacement._parse_entry(entry)[1].command_id for entry in reclaimed] == [
        "first", "second",
    ]


async def test_writer_reclaims_only_its_own_partitions(redis_manager):
    redis = redis_manager.client
    await redis.set(LAYOUT, "2")
    client = DatabaseWriteClient(redis_manager)
    for partition in range(2):
        await client.enqueue(
            DatabaseWriteOperation.UPSERT_USER,
            {"user": {"id": _user_in_partition(partition)}},
            site="onlyfans", command_id=f"crashed-{partition}",
        )
    crashed = DatabaseWriterService(
        redis_manager, _RecordingExecutor(), consumer_name="crashed", partitions=(0, 1),
    )
    await crashed._ensure_group()
    assert len(await crashed._read_new_entries()) == 2
    await asyncio.sleep(0.01)
    owner = DatabaseWriterService(
        redis_manager, _RecordingExecutor(), consumer_name="owner-1",
        partitions=(1,), reclaim_idle_ms=1,
    )
    assert await owner._pending_entry_count() == 1
    reclaimed = await owner._claim_stale_entries()
    assert [entry[0] for entry in reclaimed] == [
        "p1:" + (await _stream_ids(redis, 1))[0]
    ]


async def test_receipt_retention_protects_commands_queued_in_any_partition(redis_manager):
    from ultima_scraper_backend.database.receipt_retention import pending_command_ids

    redis = redis_manager.client
    await redis.set(LAYOUT, "2")
    client = DatabaseWriteClient(redis_manager)
    for partition in range(2):
        await client.enqueue(
            DatabaseWriteOperation.UPSERT_USER,
            {"user": {"id": _user_in_partition(partition)}},
            site="onlyfans", command_id=f"queued-{partition}",
        )
    assert await pending_command_ids(redis_manager) == {"queued-0", "queued-1"}


async def test_partition_leases_split_the_layout_between_processes(redis_manager):
    redis = redis_manager.client
    ttl = 30
    assert await writer_runtime.acquire_partitions(redis, "a", ttl, 2) == (1, [0])
    assert await writer_runtime.acquire_partitions(redis, "b", ttl, 2) == (1, [])
    assert writer_runtime.partition_lease_key(0) == writer_runtime.WRITER_LEADER_KEY

    await redis.delete(writer_runtime.WRITER_LEADER_KEY)
    await redis.set(LAYOUT, "2")
    assert await writer_runtime.acquire_partitions(redis, "a", ttl, 2) == (2, [0])
    assert await writer_runtime.acquire_partitions(redis, "b", ttl, 2) == (2, [1])
    assert await writer_runtime.acquire_partitions(redis, "c", ttl, 2) == (2, [])

    # Fewer processes than partitions: one process drains several.
    await redis.delete(*(writer_runtime.partition_lease_key(p) for p in range(2)))
    assert await writer_runtime.acquire_partitions(redis, "a", ttl, 1) == (2, [0, 1])


def _sync_redis():
    return fakeredis.FakeRedis(decode_responses=True)


def test_layout_switch_waits_for_every_partition_to_drain():
    redis = _sync_redis()
    stream = DatabaseWriteClient.STREAM_KEY
    entry = redis.xadd(stream, {"command": "{}"})
    # Scale 1 -> 2: the partition-0 owner starts the switch and blocks producers.
    assert not writer_runtime.coordinate_partitions(redis, held=[0], layout=1, processes=2)
    assert redis.get(LAYOUT) == "1>2"
    assert not writer_runtime.coordinate_partitions(redis, held=[0], layout=1, processes=2)
    redis.xdel(stream, entry)
    assert writer_runtime.coordinate_partitions(redis, held=[0], layout=1, processes=2)
    assert redis.get(LAYOUT) == "2"
    # Every process then re-acquires under the new layout.
    assert writer_runtime.coordinate_partitions(redis, held=[1], layout=1, processes=2)

    # Scale 2 -> 1 drains partition 1 too, then restores the original state.
    p1 = DatabaseWriteClient.partition_keys(1)[0]
    entry = redis.xadd(p1, {"command": "{}"})
    assert not writer_runtime.coordinate_partitions(redis, held=[0, 1], layout=2, processes=1)
    assert redis.get(LAYOUT) == "2>1"
    redis.xdel(p1, entry)
    assert writer_runtime.coordinate_partitions(redis, held=[0, 1], layout=2, processes=1)
    assert redis.get(LAYOUT) is None


def test_only_the_partition_zero_owner_changes_the_layout():
    redis = _sync_redis()
    redis.set(LAYOUT, "2")
    redis.set(writer_runtime.partition_lease_key(0), "other")
    assert not writer_runtime.coordinate_partitions(redis, held=[1], layout=2, processes=3)
    assert redis.get(LAYOUT) == "2"
    # A stale switch toward another configuration is cancelled by the owner.
    redis.set(LAYOUT, "2>3")
    assert not writer_runtime.coordinate_partitions(redis, held=[0], layout=2, processes=2)
    assert redis.get(LAYOUT) == "2"


def test_writer_below_its_share_takes_an_unowned_partition():
    redis = _sync_redis()
    redis.set(LAYOUT, "3")
    redis.set(writer_runtime.partition_lease_key(0), "a")
    redis.set(writer_runtime.partition_lease_key(1), "a")
    assert not writer_runtime.coordinate_partitions(redis, held=[2], layout=3, processes=3)
    redis.delete(writer_runtime.partition_lease_key(1))
    # Quota is ceil(3/2) = 2; partition 1 has no owner.
    assert writer_runtime.coordinate_partitions(redis, held=[2], layout=3, processes=2)


def test_launcher_starts_and_stops_every_configured_writer(monkeypatch):
    terminated: list[str] = []

    class Started(FakeProcess):
        pid = 1

        def start(self) -> None:
            pass

    processes = {
        "database-writer-1": Started(),
        "database-writer-2": Started(),
        "worker-pool": Started(alive=False, exitcode=3),
        "plugin-supervisor": Started(),
    }
    monkeypatch.setenv("ULTIMA_DATABASE_WRITER_PROCESSES", "2")
    monkeypatch.setattr(runtime_main.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(runtime_main, "get_process_context", object)
    monkeypatch.setattr(runtime_main, "wait_for_first_time_setup", lambda _shutdown: True)
    monkeypatch.setattr(
        runtime_main, "create_process", lambda _context, _target, name: processes[name]
    )
    monkeypatch.setattr(
        runtime_main,
        "terminate_process",
        lambda _process, name, **_kwargs: terminated.append(name),
    )
    with pytest.raises(RuntimeError, match=r"worker pool exited"):
        runtime_main.run_worker_runtime()
    assert terminated == [
        "plugin supervisor", "worker pool", "database writer 1", "database writer 2",
    ]


@pytest.mark.parametrize("value", ["0", "-1", "two"])
def test_invalid_writer_process_count_fails_closed(monkeypatch, value):
    monkeypatch.setenv("ULTIMA_DATABASE_WRITER_PROCESSES", value)
    with pytest.raises(ValueError, match="ULTIMA_DATABASE_WRITER_PROCESSES"):
        runtime_main.database_writer_process_count()


# PostgreSQL: receipts keep duplicate delivery across processes idempotent.
from contextlib import contextmanager  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from sqlalchemy import create_engine, text  # noqa: E402
from sqlmodel import Session  # noqa: E402
from test_mps_manifest import postgres_engine  # noqa: E402
from test_writer_bulk_profiles import _create_schema, _profile  # noqa: E402
from ultima_scraper_backend.database.write_executor import (  # noqa: E402
    PostgreSQLWriteExecutor,
)

__all__ += ["postgres_engine"]


@contextmanager
def _pg_executors(engine, schema, count):
    scoped = create_engine(
        engine.url, connect_args={"options": f"-c search_path={schema},management"}
    )

    def executor():
        instance = PostgreSQLWriteExecutor.__new__(PostgreSQLWriteExecutor)
        instance._site_manager = lambda _site: SimpleNamespace(
            get_session=lambda: Session(scoped)
        )
        return instance

    try:
        yield [executor() for _ in range(count)]
    finally:
        scoped.dispose()


def _receipt_count(engine, command_ids):
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM management.database_write_receipts "
                 "WHERE command_id = ANY(:ids)"),
            {"ids": list(command_ids)},
        ).scalar()


@pytest.mark.asyncio
async def test_stale_consumer_and_reclaimer_apply_a_profile_once(
    postgres_engine, redis_manager
):
    schema = "w2_duplicate"
    _create_schema(postgres_engine, schema)
    with postgres_engine.begin() as connection:
        connection.execute(text("TRUNCATE management.database_write_receipts"))
    redis = redis_manager.client
    await redis.set(LAYOUT, "2")
    client = DatabaseWriteClient(redis_manager)
    user_id = _user_in_partition(1, start=40)
    partition = 1
    await client.enqueue(
        DatabaseWriteOperation.UPSERT_USER, _profile(user_id, username="dup", name="Dup"),
        site="onlyfans", command_id="duplicate",
    )
    with _pg_executors(postgres_engine, schema, 2) as (stale_executor, owner_executor):
        stale = DatabaseWriterService(
            redis_manager, stale_executor, consumer_name="stale", partitions=(partition,),
        )
        await stale._ensure_group()
        stale_entries = await stale._read_new_entries()
        assert len(stale_entries) == 1
        await asyncio.sleep(0.01)
        owner = DatabaseWriterService(
            redis_manager, owner_executor, consumer_name="owner",
            partitions=(partition,), reclaim_idle_ms=1,
        )
        reclaimed = await owner._claim_stale_entries()
        assert len(reclaimed) == 1
        # Both copies run at once, as a stalled process and its replacement would.
        pending = [stale._parse_entry(entry) for entry in stale_entries]
        retries = await asyncio.gather(
            stale._execute_and_ack_batch(pending),
            owner._execute_and_ack_batch([owner._parse_entry(reclaimed[0])]),
        )
        for service, retry in zip((stale, owner), retries, strict=True):
            if retry:  # receipt row locked by the other transaction
                assert await service._execute_and_ack_batch(retry) == []
        # The slower copy replays the committed receipt instead of writing again.
        assert await client.wait_for_result("duplicate", timeout_seconds=5) == {"synced": True}
    assert _receipt_count(postgres_engine, ["duplicate"]) == 1
    with postgres_engine.connect() as connection:
        assert connection.execute(text(
            f"SELECT count(*) FROM {schema}.users WHERE id=:id"), {"id": user_id}).scalar() == 1
        assert connection.execute(text(
            f"SELECT name FROM {schema}.user_infos WHERE user_id=:id"),
            {"id": user_id}).scalar() == "Dup"
    assert await redis.xlen(DatabaseWriteClient.partition_keys(partition)[0]) == 0


@pytest.mark.asyncio
async def test_partitioned_writers_commit_profiles_in_parallel(
    postgres_engine, redis_manager
):
    schema = "w2_parallel"
    _create_schema(postgres_engine, schema)
    redis = redis_manager.client
    await redis.set(LAYOUT, "2")
    client = DatabaseWriteClient(redis_manager)
    users = range(100, 160)
    with _pg_executors(postgres_engine, schema, 2) as executors:
        services = [
            DatabaseWriterService(
                redis_manager, executor, consumer_name=f"pg-writer-{partition}",
                partitions=(partition,), batch_size=10, concurrency=2, block_ms=5,
                # The fixture's receipt lookup is in memory; keep every result.
                result_cache_max_entries=len(users),
            )
            for partition, executor in enumerate(executors)
        ]
        # The real executor closes pools it does not own in this test.
        for executor in executors:
            executor.close = lambda: asyncio.sleep(0)
        running = [asyncio.create_task(service.run()) for service in services]
        try:
            for user_id in users:
                await client.enqueue(
                    DatabaseWriteOperation.UPSERT_USER,
                    _profile(user_id, username=f"user{user_id}", name=f"Name {user_id}"),
                    site="onlyfans", command_id=f"profile-{user_id}",
                )
            for user_id in users:
                assert (await client.wait_for_result(
                    f"profile-{user_id}", timeout_seconds=30))["synced"] is True
        finally:
            for service in services:
                service.stop()
            await asyncio.wait_for(asyncio.gather(*running), timeout=30)
    assert _receipt_count(postgres_engine, [f"profile-{u}" for u in users]) == len(users)
    with postgres_engine.connect() as connection:
        assert connection.execute(text(
            f"SELECT count(*) FROM {schema}.user_infos WHERE user_id >= 100")).scalar() == len(users)
