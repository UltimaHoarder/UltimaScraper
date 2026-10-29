"""Committed SQL outcomes survive Redis loss and overlapping writer owners.

Uses the opt-in disposable PostgreSQL fixture, never a deployment database.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session
from test_database_write_executor import _command
import test_mps_manifest as mps_fixtures
import test_database_write_queue as writer_fixtures
from ultima_scraper_backend.database import write_receipts
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteOperation,
    DatabaseWriteResult,
)

postgres_engine = mps_fixtures.postgres_engine
redis_manager = writer_fixtures.redis_manager


@pytest.fixture
def receipt_runtime(postgres_engine, monkeypatch):
    from ultima_scraper_db_archive import global_db

    @contextmanager
    def session_factory():
        with Session(postgres_engine) as session:
            yield session

    monkeypatch.setattr(global_db, "global_session", session_factory)
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS management.receipt_test_updates (id bigint PRIMARY KEY, writes bigint NOT NULL DEFAULT 0)"
            )
        )
        connection.execute(
            text(
                "TRUNCATE management.receipt_test_updates, management.database_write_receipts"
            )
        )
        connection.execute(
            text("INSERT INTO management.receipt_test_updates (id) VALUES (1), (2)")
        )

    class Manager:
        fail = False
        get_session = staticmethod(session_factory)

        def mark_media_downloaded(self, ids, *, session):
            return session.execute(
                text(
                    "UPDATE management.receipt_test_updates SET writes = writes + 1 WHERE id = ANY(:ids)"
                ),
                {"ids": ids},
            ).rowcount

        def batch_record_filepaths(self, rows, *, session):
            return len(rows)

        def update_media_sizes_bulk(self, sizes, *, session):
            if self.fail:
                raise RuntimeError("injected mutation failure")
            return len(sizes)

    manager = Manager()
    executor = PostgreSQLWriteExecutor.__new__(PostgreSQLWriteExecutor)
    executor._site_manager = lambda site: manager
    executor.redis = SimpleNamespace()

    def written():
        with session_factory() as session:
            return session.execute(
                text("SELECT sum(writes) FROM management.receipt_test_updates")
            ).scalar_one()

    return SimpleNamespace(
        session=session_factory, manager=manager, executor=executor, written=written
    )


def download_command(command_id=None, media_ids=None):
    return _command(
        command_id or uuid4().hex,
        DatabaseWriteOperation.FINALIZE_DOWNLOAD,
        {
            "user_id": 7,
            "media_ids": media_ids or [1],
            "filepaths": [],
            "media_sizes": {},
        },
    )


async def test_committed_batch_replay_returns_original_counts_without_repeating_mutations(
    receipt_runtime,
):
    commands = [download_command(media_ids=[1]), download_command(media_ids=[2])]
    first = await receipt_runtime.executor.execute_batch(commands)
    # Simulate a crash after SQL commit and before any Redis result publication.
    second = await receipt_runtime.executor.execute_batch(commands)
    assert first == second
    assert receipt_runtime.written() == 2
    receipts = write_receipts.lookup([command.command_id for command in commands])
    assert all(
        receipts[command.command_id].payload == first[command.command_id]
        for command in commands
    )


async def test_mutation_failure_rolls_back_both_side_effect_and_receipt(
    receipt_runtime,
):
    command = download_command()
    receipt_runtime.manager.fail = True
    with pytest.raises(RuntimeError, match="injected mutation failure"):
        await receipt_runtime.executor.execute_batch([command])
    assert receipt_runtime.written() == 0
    assert write_receipts.lookup([command.command_id]) == {}
    receipt_runtime.manager.fail = False
    await receipt_runtime.executor.execute_batch([command])
    assert receipt_runtime.written() == 1


async def test_receipt_insert_failure_rolls_back_the_already_executed_mutation(
    receipt_runtime,
):
    with receipt_runtime.session() as session:
        session.execute(
            text(
                "ALTER TABLE management.database_write_receipts ADD CONSTRAINT fixture_reject CHECK (command_id <> 'reject-receipt')"
            )
        )
        session.commit()
    command = download_command("reject-receipt")
    try:
        with pytest.raises(IntegrityError):
            await receipt_runtime.executor.execute_batch([command])
        assert receipt_runtime.written() == 0
        assert write_receipts.lookup([command.command_id]) == {}
    finally:
        with receipt_runtime.session() as session:
            session.execute(
                text(
                    "ALTER TABLE management.database_write_receipts DROP CONSTRAINT fixture_reject"
                )
            )
            session.commit()


def test_replacement_writer_cannot_run_same_command_during_original_transaction(
    receipt_runtime,
):
    command = download_command()
    with receipt_runtime.session() as original:
        results = {}
        with write_receipts.receipt_batch(original, [command], results) as pending:
            assert pending == [command]
            results[command.command_id] = {"updated": 1}
        with receipt_runtime.session() as replacement:
            replacement.execute(text("SET LOCAL lock_timeout = '50ms'"))
            with pytest.raises(write_receipts.DatabaseWriteReceiptBusy):
                with write_receipts.receipt_batch(replacement, [command], {}):
                    pytest.fail("overlapping command unexpectedly admitted")
        original.commit()
    with receipt_runtime.session() as replacement:
        results = {}
        with write_receipts.receipt_batch(replacement, [command], results) as pending:
            assert pending == []
        assert results == {command.command_id: {"updated": 1}}


async def test_late_failure_preserves_a_prior_successful_sql_commit(receipt_runtime):
    command = download_command()
    payload = (await receipt_runtime.executor.execute_batch([command]))[
        command.command_id
    ]
    failed = DatabaseWriteResult(
        command_id=command.command_id,
        success=False,
        payload={},
        error="late failure",
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    retained = write_receipts.record_failure(command, failed)
    assert retained.success is True
    assert retained.payload == payload


def test_failure_evidence_is_durable_and_rejects_later_reexecution(receipt_runtime):
    from ultima_scraper_backend.database.write_queue import DatabaseWriteRejected

    command = download_command()
    failure = DatabaseWriteResult(
        command_id=command.command_id,
        success=False,
        payload={},
        error="terminal failure",
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    write_receipts.record_failure(command, failure)
    assert write_receipts.lookup([command.command_id])[command.command_id] == failure
    with receipt_runtime.session() as session:
        assert (
            session.execute(
                text(
                    "SELECT failed_command_json FROM management.database_write_receipts WHERE command_id = :id"
                ),
                {"id": command.command_id},
            ).scalar_one()
            == command.to_json()
        )
        with pytest.raises(DatabaseWriteRejected, match="terminal failure"):
            with write_receipts.receipt_batch(session, [command], {}):
                pytest.fail("failed command unexpectedly admitted")


async def test_production_writer_delivers_uncached_result_from_postgresql(
    receipt_runtime, redis_manager, monkeypatch
):
    from ultima_scraper_backend.database import write_queue

    monkeypatch.setattr(
        write_queue,
        "_lookup_write_receipt",
        lambda command_id: write_receipts.lookup([command_id]).get(command_id),
    )
    service = write_queue.DatabaseWriterService(
        redis_manager, receipt_runtime.executor, result_cache_max_bytes=1, block_ms=1
    )
    client = write_queue.DatabaseWriteClient(redis_manager)
    command = download_command()
    await service._ensure_group()
    await client.enqueue(
        command.operation,
        command.payload,
        site=command.site,
        command_id=command.command_id,
    )
    await service._process_entries(await service._read_new_entries())
    assert await redis_manager.client.get(client.result_key(command.command_id)) is None
    assert (await client.wait_for_result(command.command_id, timeout_seconds=1))[
        "marked_downloaded"
    ] == 1
    # Retrying after cache eviction reuses the SQL receipt and leaves the write count unchanged.
    await client.enqueue(
        command.operation,
        command.payload,
        site=command.site,
        command_id=command.command_id,
    )
    await service._process_entries(await service._read_new_entries())
    assert receipt_runtime.written() == 1


def test_receipt_contention_defers_and_releases_partial_batch_locks(postgres_engine):
    first_id, busy_id = "a-" + str(uuid4()), "z-" + str(uuid4())
    with Session(postgres_engine) as owner:
        write_receipts._lock(owner, [busy_id])
        with Session(postgres_engine) as contender:
            contender.execute(text("SET LOCAL lock_timeout='50ms'"))
            with pytest.raises(write_receipts.DatabaseWriteReceiptBusy):
                write_receipts._lock(contender, [first_id,busy_id], defer_if_busy=True)
            contender.rollback()
        with Session(postgres_engine) as other:
            write_receipts._lock(other, [first_id], defer_if_busy=True)
            other.rollback()
        owner.rollback()
    with Session(postgres_engine) as retry:
        write_receipts._lock(retry, [busy_id], defer_if_busy=True)
        retry.rollback()


def test_stored_receipt_omits_writer_timing_only():
    from ultima_scraper_backend.database.write_queue import (
        WRITE_TIMING_KEY,
        DatabaseWriteResult,
    )

    timed = DatabaseWriteResult(
        command_id="receipt-timing",
        success=True,
        payload={"synced": True, WRITE_TIMING_KEY: {"execution_ms": 3.0}},
        error=None,
        completed_at="2026-10-15T00:00:00+00:00",
    )
    stored = DatabaseWriteResult.from_json(write_receipts._stored_result_json(timed))
    assert stored.payload == {"synced": True}
    assert (stored.command_id, stored.success, stored.completed_at) == (
        timed.command_id,
        timed.success,
        timed.completed_at,
    )
    # The live result keeps its timing for the Redis cache.
    assert WRITE_TIMING_KEY in timed.payload
    plain = DatabaseWriteResult(
        command_id="receipt-plain",
        success=False,
        payload={"error_code": "x"},
        error="rejected",
        completed_at="2026-10-15T00:00:00+00:00",
    )
    assert write_receipts._stored_result_json(plain) == plain.to_json()
