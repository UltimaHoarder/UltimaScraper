"""Bounded batch fences retain transactional cancellation and expiry safety."""
# ruff: noqa: F811 - imported PostgreSQL fixtures are injected by pytest.

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, text
from test_execution_ledger import (  # noqa: F401
    claim,
    ledger,
    ledger_engine,
    postgres_engine,
    submit,
    task,
)
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteCommand,
    DatabaseWriteOperation,
)
from ultima_scraper_backend.database.write_receipts import receipt_batch
from ultima_scraper_backend.job_system.ledger import (
    StaleAttempt,
    validate_write_attempts,
)


def owned_batch(ledger, count=2, *, run_id="job-test", user_offset=0):
    ledger.limits = replace(ledger.limits, tasks=256, global_tasks=512, batch=128)
    submit(
        ledger,
        [
            task(f"{run_id}-task-{i:03d}", user_id=user_offset + i + 1)
            for i in range(count)
        ],
        identity=run_id,
    )
    for _ in range(4):
        ledger.tick()
    claims = ledger.claim_many(
        owner="worker-batch",
        backend_id="backend-a",
        capabilities=["onlyfans"],
        count=count,
    )
    assert len(claims) == count
    return claims


def identity(owned):
    return {key: getattr(owned, key) for key in ("run_id", "task_id", "token", "owner")}


def command(owned):
    return DatabaseWriteCommand(
        command_id=f"writer-{owned.token}",
        operation=DatabaseWriteOperation.UPSERT_USER,
        site="onlyfans",
        payload={},
        producer_id="test",
        created_at=datetime.now(UTC).isoformat(),
        version=2,
        execution_attempt=identity(owned),
        execution_key="profile-save",
    )


@pytest.mark.parametrize("count", [1, 25, 100])
def test_batch_uses_three_skinny_fence_reads(ledger, ledger_engine, count):
    owned = owned_batch(ledger, count)
    statements = []
    with ledger.session_factory() as session:

        def executed(conn, cursor, statement, parameters, context, many):
            statements.append(statement)

        event.listen(ledger_engine, "after_cursor_execute", executed)
        try:
            validate_write_attempts(
                session, [identity(item) for item in reversed(owned)]
            )
        finally:
            event.remove(ledger_engine, "after_cursor_execute", executed)
    assert len(statements) == 3
    assert all(
        "payload_json" not in statement and "config_json" not in statement
        for statement in statements
    )
    assert "execution_runs" in statements[0] and "FOR SHARE" in statements[0]
    assert "execution_work" in statements[1] and "FOR SHARE" in statements[1]
    assert "clock_timestamp" in statements[2]


@pytest.mark.parametrize(
    "invalid", ["token", "owner", "missing_run", "missing_task", "expired", "cancelled"]
)
def test_one_invalid_fence_rejects_batch_before_any_mutation(ledger, invalid):
    owned = owned_batch(ledger)
    commands = [command(item) for item in owned]
    bad = dict(commands[-1].execution_attempt)
    if invalid in {"token", "owner"}:
        bad[invalid] = "replacement"
    elif invalid == "missing_run":
        bad["run_id"] = "missing-run"
    elif invalid == "missing_task":
        bad["task_id"] = "missing-task"
    elif invalid == "cancelled":
        ledger.control("job-test", "cancel")
    else:
        with ledger.session_factory() as session:
            session.execute(
                text(
                    "UPDATE management.execution_work SET lease_until=clock_timestamp()-interval '1 second' WHERE task_id=:task"
                ),
                {"task": owned[-1].task_id},
            )
            session.commit()
    commands[-1] = replace(commands[-1], execution_attempt=bad)
    with (
        ledger.session_factory() as session,
        pytest.raises(StaleAttempt),
        receipt_batch(session, commands, {}),
    ):
        session.execute(text("INSERT INTO onlyfans.users (id) VALUES (800)"))
        pytest.fail("Rejected batch reached mutation")
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM onlyfans.users")) == 0
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.database_write_receipts")
            )
            == 0
        )


def test_cancel_waits_for_all_batch_mutations_and_receipts(ledger):
    owned = owned_batch(ledger)
    commands = [command(item) for item in owned]
    entered = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with ledger.session_factory() as session:
            results = {}
            with receipt_batch(session, commands, results):

                def cancel():
                    entered.set()
                    return ledger.control("job-test", "cancel")

                future = executor.submit(cancel)
                assert entered.wait(2)
                with pytest.raises(TimeoutError):
                    future.result(timeout=0.1)
                session.execute(
                    text("INSERT INTO onlyfans.users (id) VALUES (801), (802)")
                )
                for item in commands:
                    results[item.command_id] = {"saved": True}
            session.commit()
        assert future.result(timeout=3)
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM onlyfans.users")) == 2
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.database_write_receipts")
            )
            == 2
        )
        with receipt_batch(session, commands, {}) as pending:
            assert pending == []  # Committed outcomes replay after cancellation.


def test_database_clock_is_read_after_blocking_work_locks(ledger):
    owned = owned_batch(ledger)
    with ledger.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.execution_work SET lease_until=clock_timestamp()+interval '200 milliseconds'"
            )
        )
        session.commit()
    entered = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with ledger.session_factory() as blocker:
            blocker.execute(
                text(
                    "SELECT task_id FROM management.execution_work ORDER BY task_id FOR UPDATE"
                )
            )

            def validate():
                with ledger.session_factory() as session:
                    session.execute(text("SET LOCAL lock_timeout='2s'"))
                    entered.set()
                    validate_write_attempts(session, [identity(item) for item in owned])

            future = executor.submit(validate)
            assert entered.wait(2)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
            time.sleep(0.2)
            blocker.commit()
        with pytest.raises(StaleAttempt):
            future.result(timeout=3)


def test_batch_checks_each_run_and_duplicate_identity_tokens(ledger):
    first = owned_batch(ledger, 1, run_id="job-a")
    second = owned_batch(ledger, 1, run_id="job-b", user_offset=10)
    identities = [identity(second[0]), identity(first[0]), identity(first[0])]
    ledger.control("job-a", "pause")  # In-flight writes may finish when paused.
    with ledger.session_factory() as session:
        validate_write_attempts(session, identities)
    identities[-1] = {**identities[-1], "token": "obsolete-token"}
    with ledger.session_factory() as session, pytest.raises(StaleAttempt):
        validate_write_attempts(session, identities)


@pytest.mark.parametrize(
    "kind,workers,expected",
    # Worker zero is interactive-first but also takes batch work, so bulk
    # telemetry counts every worker.
    [("scrape", 8, 8), ("download", 8, 8), ("api_command", 8, 8), ("scrape", 1, 1)],
)
@pytest.mark.asyncio
async def test_bulk_telemetry_counts_every_worker(
    ledger, monkeypatch, kind, workers, expected
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from test_execution_ledger import pool
    from ultima_scraper_backend.job_system.ledger_runtime import execute
    from ultima_scraper_backend.job_system.models import (
        TaskRegistry,
        TaskResult,
        TaskType,
    )

    task_type = TaskType(kind)
    worker = pool()
    worker.worker_count = workers
    worker.task_job_storage = SimpleNamespace(record_task_runtime_telemetry=AsyncMock())
    monkeypatch.setitem(
        TaskRegistry._handlers,
        task_type,
        AsyncMock(return_value=TaskResult(success=True)),
    )
    submit(ledger, [task(kind=task_type)])
    ledger.tick()
    await execute(worker, ledger, claim(ledger))
    assert (
        worker.task_job_storage.record_task_runtime_telemetry.await_args.kwargs[
            "expected_workers"
        ]
        == expected
    )
