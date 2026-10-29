"""Avoid duplicate SQL checkpoints without bypassing attempt fences or writer ACKs."""
# ruff: noqa: F811 - imported pytest fixtures are injected into test functions.

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_execution_ledger import (  # noqa: F401
    claim,
    ledger,
    ledger_engine,
    pool,
    postgres_engine,
    submit,
    task,
)
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
from ultima_scraper_backend.job_system import ledger_runtime
from ultima_scraper_backend.job_system.ledger import (
    StaleAttempt,
    validate_write_attempt,
)
from ultima_scraper_backend.job_system.models import (
    Task,
    TaskRegistry,
    TaskResult,
    TaskType,
)


def test_claim_commits_visible_start_without_startup_checkpoint(ledger):
    submit(ledger, [task()])
    ledger.tick()
    owned = claim(ledger)
    stored = ledger.task(owned.run_id, owned.task_id)
    assert stored["state"] == "running"
    assert stored["worker_id"] == owned.owner
    assert stored["attempts"] == owned.number == 1
    assert stored["started_at"] == ledger.attempts(owned.run_id)[0]["started_at"]
    assert owned.task["attempts"] == 0  # Task.run increments its local attempt.


@pytest.mark.asyncio
async def test_database_timing_separates_thread_wait_from_event_loop_resume(
    monkeypatch,
):
    clock = [10.0]
    monkeypatch.setattr(
        ledger_runtime,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0], time=time.time),
    )

    async def delayed_call(function):
        clock[0] += 0.007
        result = function()
        clock[0] += 0.006
        return result

    def sql():
        clock[0] += 0.005
        return "committed"

    monkeypatch.setattr(ledger_runtime, "run_database_call", delayed_call)
    metrics = ledger_runtime.ExecutionTelemetry()
    assert await metrics.database_call(sql, phase="finish") == "committed"
    for name, expected in {
        "finish": 18,
        "finish_execution": 5,
        "finish_admission": 13,
        "finish_thread_wait_admission": 7,
        "finish_resume_admission": 6,
    }.items():
        assert metrics.ledger[name] == {"ms": pytest.approx(expected), "count": 1}


@pytest.mark.asyncio
async def test_slow_checkpoint_and_concurrent_callbacks_coalesce(monkeypatch):
    clock = [10.0]
    entered, release = asyncio.Event(), asyncio.Event()

    async def database_call(function, *args, **kwargs):
        entered.set()
        await release.wait()
        function(*args, **kwargs)
        clock[0] += 3  # A long SQL wait must not consume the next interval.

    fake = SimpleNamespace(progress=Mock())
    item = task()
    owned = SimpleNamespace(run_id="job-test", task_id=item.task_id, task={})
    monkeypatch.setattr(
        ledger_runtime,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0], time=time.time),
    )
    monkeypatch.setattr(ledger_runtime, "run_database_call", database_call)
    storage = ledger_runtime.LedgerTaskStorage(fake, owned, item, None)
    await storage.persist_task(job_id="job-test", task=item)
    fake.progress.assert_not_called()
    clock[0] += 2
    first = asyncio.create_task(storage.persist_task(job_id="job-test", task=item))
    await asyncio.wait_for(entered.wait(), 2)
    second = asyncio.create_task(storage.persist_task(job_id="job-test", task=item))
    release.set()
    await asyncio.gather(first, second)
    await storage.persist_task(job_id="job-test", task=item)
    assert fake.progress.call_count == 1
    clock[0] += 1.01
    await storage.persist_task(job_id="job-test", task=item)
    assert fake.progress.call_count == 2


@pytest.mark.asyncio
async def test_failed_writer_checkpoint_does_not_suppress_retry():
    fake = SimpleNamespace(
        progress=Mock(side_effect=[ConnectionError("SQL unavailable"), None])
    )
    item = task()
    owned = SimpleNamespace(run_id="job-test", task_id=item.task_id, task={})
    storage = ledger_runtime.LedgerTaskStorage(fake, owned, item, None)
    with pytest.raises(ConnectionError):
        await storage.checkpoint(persisting=True, renew=True)
    await storage.checkpoint(persisting=True, renew=True)
    await storage.checkpoint(persisting=True, renew=True)
    assert fake.progress.call_count == 2
    assert fake.progress.call_args.kwargs == {"persisting": True, "renew": True}


@pytest.mark.asyncio
async def test_short_profile_lifecycle_has_one_checkpoint_and_waits_for_ack(
    ledger, monkeypatch
):
    worker = pool()
    worker.task_job_storage = SimpleNamespace(record_task_runtime_telemetry=Mock())
    # Capture asynchronous publication without replacing ownership SQL.
    from unittest.mock import AsyncMock

    worker.task_job_storage.record_task_runtime_telemetry = AsyncMock()
    accepted, acknowledge = asyncio.Event(), asyncio.Event()
    identities = {}
    ledger.progress = Mock(wraps=ledger.progress)
    ledger.checkpoint_batch = Mock(wraps=ledger.checkpoint_batch)

    async def enqueue(operation, payload, **kwargs):
        identities[kwargs["command_id"]] = kwargs["execution_attempt"]
        assert ledger.task(owned.run_id, owned.task_id)["state"] == "saving_db"
        accepted.set()
        return kwargs["command_id"], {}

    async def wait_for_result(command_id, **kwargs):
        await acknowledge.wait()
        with ledger.session_factory() as session:
            validate_write_attempt(session, identities[command_id])
        return {"saved": True}

    worker.database_writes = SimpleNamespace(
        enqueue=enqueue, wait_for_result=wait_for_result
    )

    async def handler(item, context):
        item.result = TaskResult(success=True, message="Scrape started")
        await context.storage.persist_task(job_id=owned.run_id, task=item)
        await context.database_writes.submit(
            DatabaseWriteOperation.UPSERT_USER, {"user_id": 1}
        )
        item.result = TaskResult(success=True, metrics={"items_saved": 1})
        for _ in range(2):
            await context.storage.persist_task(job_id=owned.run_id, task=item)
        return item.result

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, handler)
    submit(ledger, [task(kind=TaskType.API_COMMAND)])
    ledger.tick()
    owned = claim(ledger)
    execution = asyncio.create_task(ledger_runtime.execute(worker, ledger, owned))
    await asyncio.wait_for(accepted.wait(), 2)
    assert ledger.stats(owned.run_id)["completed"] == 0
    acknowledge.set()
    assert await asyncio.wait_for(execution, 3) == (True, False, None)
    assert ledger.progress.call_count == 0
    assert ledger.checkpoint_batch.call_count == 1
    assert (
        ledger.task(owned.run_id, owned.task_id)["result"]["metrics"]["items_saved"]
        == 1
    )
    import json

    metrics = json.loads(
        worker.task_job_storage.record_task_runtime_telemetry.await_args.kwargs[
            "ledger_stats_json"
        ]
    )
    assert metrics["writer_prepare"]["count"] == metrics["finish"]["count"] == 1
    assert "progress" not in metrics
    assert metrics["writer_prepare"]["ms"] == pytest.approx(
        metrics["writer_prepare_execution"]["ms"]
        + metrics["writer_prepare_admission"]["ms"]
    )


@pytest.mark.asyncio
async def test_coalesced_writer_call_still_rejects_revoked_attempt(ledger):
    submit(ledger, [task()])
    ledger.tick()
    owned = claim(ledger)
    storage = ledger_runtime.LedgerTaskStorage(
        ledger, owned, Task.from_dict(owned.task), None
    )
    admitted = []

    async def enqueue(operation, payload, **kwargs):
        with ledger.session_factory() as session:
            validate_write_attempt(session, kwargs["execution_attempt"])
        admitted.append(kwargs)
        return kwargs["command_id"], {}

    writer = ledger_runtime.FencedWriter(
        SimpleNamespace(enqueue=enqueue), ledger, owned, storage
    )
    await writer.enqueue(DatabaseWriteOperation.UPSERT_USER, {"user_id": 1})
    ledger.control(owned.run_id, "cancel")
    with pytest.raises(StaleAttempt):
        await writer.enqueue(DatabaseWriteOperation.UPSERT_USER, {"user_id": 2})
    assert len(admitted) == 1
    assert ledger.stats(owned.run_id)["completed"] == 0
