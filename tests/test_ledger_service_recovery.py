"""SQL control services survive recovery without busy retries or lost shutdown."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import psycopg
import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError
from ultima_scraper_backend.job_system import ledger_runtime


def cached_recovery_error():
    return OperationalError(
        "SELECT clock_timestamp()",
        {},
        psycopg.errors.ProtocolViolation(
            "server login has been failing, cached error: "
            "the database system is in recovery mode (server_login_retry)"
        ),
    )


def pool_wait_error():
    return OperationalError(None, None, psycopg.errors.ProtocolViolation("query_wait_timeout"))


@pytest.mark.parametrize("error_factory", [cached_recovery_error, pool_wait_error])
@pytest.mark.asyncio
async def test_cached_recovery_backoff_is_bounded_and_logs_recovery(
    monkeypatch, caplog, error_factory
):
    sleeps = AsyncMock()
    clock = [0]
    monkeypatch.setattr(ledger_runtime.asyncio, "sleep", sleeps)
    monkeypatch.setattr(
        ledger_runtime, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    retry = ledger_runtime._ServiceRetry("planner")
    caplog.set_level(logging.INFO, logger=ledger_runtime.__name__)
    for _ in range(5):
        await retry.failed(error_factory())
    assert [call.args[0] for call in sleeps.await_args_list] == [15, 30, 30, 30, 30]
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is None
    clock[0] = 60
    await retry.failed(error_factory())
    assert len(caplog.records) == 2
    retry.succeeded()
    assert "database access restored" in caplog.records[-1].message
    await retry.failed(error_factory())
    assert sleeps.await_args.args == (15,)
    assert len(caplog.records) == 4


@pytest.mark.parametrize(
    "original",
    [
        psycopg.errors.CannotConnectNow("the database system is in recovery mode"),
        psycopg.errors.AdminShutdown("server is shutting down"),
        psycopg.errors.CrashShutdown("server crashed"),
        psycopg.errors.ConnectionFailure("connection lost"),
        psycopg.errors.ProtocolViolation("server conn crashed?"),
        psycopg.OperationalError("connection refused"),
    ],
)
@pytest.mark.asyncio
async def test_connection_failures_back_off_and_remain_visible(
    monkeypatch, caplog, original
):
    sleeps = AsyncMock()
    monkeypatch.setattr(ledger_runtime.asyncio, "sleep", sleeps)
    retry = ledger_runtime._ServiceRetry("archive")
    error = OperationalError(None, None, original)
    for _ in range(7):
        await retry.failed(error)
    assert [call.args[0] for call in sleeps.await_args_list] == [1, 2, 4, 8, 16, 30, 30]
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].exc_info is None


@pytest.mark.parametrize(
    "error",
    [
        ProgrammingError(None, None, psycopg.errors.UndefinedTable("missing table")),
        OperationalError(
            None, None, psycopg.errors.InvalidPassword("invalid password")
        ),
        OperationalError(None, None, psycopg.errors.ProtocolViolation("bad protocol")),
        OperationalError(None, None, psycopg.errors.DeadlockDetected("deadlock")),
        RuntimeError("planner implementation failure"),
        ConnectionError("Redis transport unavailable"),
    ],
)
@pytest.mark.asyncio
async def test_other_failures_keep_their_tracebacks(monkeypatch, caplog, error):
    sleeps = AsyncMock()
    monkeypatch.setattr(ledger_runtime.asyncio, "sleep", sleeps)
    retry = ledger_runtime._ServiceRetry("event relay")
    try:
        raise error
    except Exception as caught:
        await retry.failed(caught)
    assert retry.failures == 0
    assert sleeps.await_args.args == (1,)
    assert caplog.records[0].exc_info[1] is error


@pytest.mark.asyncio
async def test_shutdown_interrupts_recovery_backoff(monkeypatch):
    monkeypatch.setattr(
        ledger_runtime.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)
    )
    with pytest.raises(asyncio.CancelledError):
        await ledger_runtime._ServiceRetry("planner").failed(cached_recovery_error())


@pytest.mark.parametrize("original", [
    psycopg.errors.ProtocolViolation("server conn crashed?"),
    psycopg.errors.ProtocolViolation("query_wait_timeout"),
    psycopg.errors.ConnectionFailure("connection lost"),
])
def test_task_retries_recognized_database_outages_through_handler_wrapper(original):
    error = RuntimeError("task handler wrapper")
    error.__cause__ = OperationalError(None, None, original)
    assert ledger_runtime._transient(error)


@pytest.mark.parametrize("original", [
    psycopg.errors.ProtocolViolation("bad protocol"),
    psycopg.errors.InvalidPassword("invalid password"),
    psycopg.errors.DeadlockDetected("deadlock"),
])
def test_task_does_not_retry_unrecognized_database_errors(original):
    error = RuntimeError("task handler wrapper")
    error.__cause__ = OperationalError(None, None, original)
    assert not ledger_runtime._transient(error)


@pytest.mark.parametrize("operation", ["recover_expired", "archive_tick", "relay"])
@pytest.mark.asyncio
async def test_services_resume_fresh_passes_after_database_recovery(
    monkeypatch, caplog, operation
):
    ledger = SimpleNamespace(
        limits=SimpleNamespace(batch=8),
        recover_expired=Mock(),
        tick=Mock(),
        archive_tick=Mock(),
        relay=Mock(),
        record_progress=Mock(),
        reindex_bloated_queue_indexes=Mock(return_value=[]),
    )
    calls = 0
    sleeps = []
    resumed = asyncio.Event()
    blocked = asyncio.Event()
    from ultima_scraper_backend.job_system import idle

    monkeypatch.setattr(idle, "SchedulingLease", lambda redis: SimpleNamespace(
        allowed=True, wait=AsyncMock(), run=blocked.wait, close=AsyncMock(),
    ))
    monkeypatch.setattr(idle, "listen_for_wakeups", lambda *args: blocked.wait())

    async def idle_wait(self, event, **kwargs):
        sleeps.append(0.25)
        resumed.set()
        await blocked.wait()

    monkeypatch.setattr(idle.IdleDelay, "wait", idle_wait)

    async def database_call(function, *args, **kwargs):
        nonlocal calls
        if function is getattr(ledger, operation):
            calls += 1
            if calls <= 2:
                raise cached_recovery_error()
            return 0
        if function is ledger.tick and operation == "recover_expired":
            await blocked.wait()
        await blocked.wait()

    async def sleep(delay):
        sleeps.append(delay)
        if delay == (1 if operation == "recover_expired" else 0.25):
            resumed.set()
            await blocked.wait()

    monkeypatch.setattr(ledger_runtime, "ExecutionLedger", lambda: ledger)
    monkeypatch.setattr(ledger_runtime, "run_database_call", database_call)
    monkeypatch.setattr(ledger_runtime.asyncio, "sleep", sleep)
    caplog.set_level(logging.INFO, logger=ledger_runtime.__name__)
    service = asyncio.create_task(ledger_runtime.service(SimpleNamespace(redis=None)))
    try:
        await asyncio.wait_for(resumed.wait(), timeout=2)
        assert calls == 3
        assert sleeps == [15, 30, 1 if operation == "recover_expired" else 0.25]
        assert any(
            "database access restored" in record.message for record in caplog.records
        )
    finally:
        service.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(service, timeout=2)


def test_deletion_pool_timeout_does_not_open_checkpoint_sessions(monkeypatch):
    from contextlib import contextmanager

    from ultima_scraper_backend.services import job_deletion

    error = pool_wait_error()
    opened = []
    @contextmanager
    def factory():
        opened.append(True)
        assert len(opened) == 1
        yield SimpleNamespace(scalar=lambda _, *args: {} if args else True,
                              scalars=lambda *_: ["job-pending"])
    ledger = SimpleNamespace(delete=Mock(side_effect=error))
    monkeypatch.setattr(job_deletion, "ExecutionLedger", lambda _: ledger)
    with pytest.raises(OperationalError) as caught:
        job_deletion.cleanup_pending(factory)
    assert caught.value is error
    assert len(opened) == 1


def test_deletion_lease_stays_active_during_long_pass(monkeypatch):
    import threading
    from contextlib import contextmanager

    from ultima_scraper_backend.services import job_deletion

    # PgBouncer kills a transaction idle for longer than its timeout, which
    # releases the cluster lease while the pass is still deleting.
    heartbeats = threading.Event()
    lease = SimpleNamespace(scalar=lambda _, *args: {} if args else True,
                            scalars=lambda *_: ["job-pending"],
                            execute=lambda _: heartbeats.set())

    @contextmanager
    def factory():
        yield lease

    def long_pass(*_args, **_kwargs):
        assert heartbeats.wait(timeout=2)
        return True

    monkeypatch.setattr(job_deletion, "LEASE_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(job_deletion, "ExecutionLedger",
                        lambda _: SimpleNamespace(delete=long_pass))
    assert job_deletion.cleanup_pending(factory) == ["job-pending"]


@pytest.mark.asyncio
async def test_deletion_resumes_fresh_pass_after_pool_timeout(monkeypatch):
    from ultima_scraper_backend.services import job_deletion

    calls = []
    async def database_call(function, **kwargs):
        calls.append(function)
        if len(calls) == 1:
            raise pool_wait_error()
        return job_deletion._DeletionPass()
    delays = []
    async def sleep(delay):
        delays.append(delay)
        if delay == 2:
            raise asyncio.CancelledError
    monkeypatch.setattr(job_deletion, "run_database_call", database_call)
    monkeypatch.setattr(job_deletion.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await job_deletion.run_deletion_worker(None)
    assert delays == [15, 2]
    assert calls == [job_deletion._cleanup_pass, job_deletion._cleanup_pass]
