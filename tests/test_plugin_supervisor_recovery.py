"""Supervisor failure visibility, interrupted SQL, and complete teardown."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import psycopg
import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError
from ultima_scraper_backend.plugin_system import supervisor
from ultima_scraper_backend.plugin_system.platform import PluginPlatform
from ultima_scraper_backend.plugin_system.recovery import (
    database_interrupted,
    error_summary,
)
from ultima_scraper_backend.plugin_system.runtime_owner import (
    PluginRuntimeCoordinator,
    PluginRuntimeOwnershipLost,
)


def database_error(state=None, *, programming=False):
    original = RuntimeError("database system is in recovery mode")
    original.sqlstate = state
    kind = ProgrammingError if programming else OperationalError
    return kind("SELECT :secret", {"secret": "private-credential"}, original)


def pool_wait_error():
    return OperationalError(
        "SELECT clock_timestamp()", {},
        psycopg.errors.ProtocolViolation("query_wait_timeout"),
    )


def test_pgbouncer_queue_timeout_is_retryable_but_bad_protocol_is_fatal():
    assert database_interrupted(pool_wait_error())
    assert not database_interrupted(OperationalError(
        None, None, psycopg.errors.ProtocolViolation("invalid message format"),
    ))


@pytest.mark.parametrize(
    "state", [None, "08006", "57P01", "57P02", "57P03", "40001", "40P01"]
)
def test_database_interruptions_are_retryable(state):
    assert database_interrupted(database_error(state))


@pytest.mark.parametrize("state", ["08P01", "42601", "42P01", "53100"])
def test_database_programming_and_disk_errors_are_fatal(state):
    assert not database_interrupted(database_error(state, programming=True))


def test_error_summary_excludes_sql_parameters():
    summary = error_summary(database_error("57P03"))
    assert "57P03" in summary
    assert "recovery mode" in summary
    assert "private-credential" not in summary
    assert "SELECT" not in summary


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [database_error("57P03"), PluginRuntimeOwnershipLost("lease was replaced"), pool_wait_error()]
)
async def test_supervisor_reinitializes_after_retryable_failure(monkeypatch, error):
    calls = []
    waits = []

    async def serve(stop):
        calls.append(stop)
        if len(calls) == 1:
            raise error
        stop.set()

    async def backoff(awaitable, timeout):
        awaitable.close()
        waits.append(timeout)
        raise TimeoutError

    monkeypatch.setattr(supervisor, "serve", serve)
    monkeypatch.setattr(supervisor.asyncio, "wait_for", backoff)
    await supervisor.supervise()
    assert len(calls) == 2
    assert calls[0] is calls[1]
    assert waits == ([15] if "query_wait_timeout" in str(error) else [1])


@pytest.mark.asyncio
async def test_supervisor_does_not_retry_programming_failure(monkeypatch):
    error = database_error("42P01", programming=True)

    async def serve(_stop):
        raise error

    monkeypatch.setattr(supervisor, "serve", serve)
    with pytest.raises(ProgrammingError) as caught:
        await supervisor.supervise()
    assert caught.value is error


@pytest.mark.asyncio
async def test_shutdown_during_backoff_does_not_restart(monkeypatch):
    calls = []

    async def serve(stop):
        calls.append(stop)
        stop.set()
        raise database_error("57P03")

    monkeypatch.setattr(supervisor, "serve", serve)
    await supervisor.supervise()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_failed_listener_cannot_prevent_remaining_runtime_teardown(tmp_path):
    platform = PluginPlatform(tmp_path)
    platform._runtime_started = True
    cancelled = asyncio.Event()

    async def failed():
        raise database_error("57P03")

    async def running():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    failed_task = asyncio.create_task(failed())
    running_task = asyncio.create_task(running())
    platform._configuration_task = failed_task
    platform._delivery_workers = [running_task]
    await asyncio.sleep(0)
    await platform.stop_runtime()
    assert cancelled.is_set()
    assert failed_task.done() and running_task.cancelled()
    assert platform.runtime_tasks() == []
    assert not platform._runtime_started


@pytest.mark.asyncio
async def test_shutdown_closes_all_websockets_even_when_session_persistence_fails(
    tmp_path,
):
    platform = PluginPlatform(tmp_path)
    platform._runtime_started = True
    closed = []

    class Socket:
        def __init__(self, name):
            self.name = name

        async def close(self):
            closed.append(self.name)

    def save(_record):
        raise database_error("57P03")

    platform._ws_live_sessions = {name: Socket(name) for name in ("first", "second")}
    platform.runtime_store = SimpleNamespace(
        get_session=lambda _name: SimpleNamespace(connected=True, last_error=None),
        save_session=save,
    )
    await platform.stop_runtime()
    assert set(closed) == {"first", "second"}
    assert platform._ws_live_sessions == {}


@pytest.mark.asyncio
async def test_ownership_sql_does_not_block_event_loop(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    started = asyncio.Event()
    stopped = asyncio.Event()

    def acquire(*_args, **_kwargs):
        entered.set()
        assert release.wait(5)
        return "lease-token"

    repository = SimpleNamespace(
        storage_kind="postgresql",
        acquire_lease=acquire,
        claim_runtime_owner=lambda *_args: None,
        heartbeat_runtime_owner=lambda *_args: True,
        release_runtime_owner=lambda *_args: None,
        release_lease=lambda *_args: None,
    )
    platform = SimpleNamespace(repository=repository, _runtime_started=False)

    async def start_runtime():
        platform._runtime_started = True
        started.set()

    async def stop_runtime():
        platform._runtime_started = False
        stopped.set()

    platform.start_runtime = start_runtime
    platform.stop_runtime = stop_runtime
    coordinator = PluginRuntimeCoordinator(platform, tmp_path, election_interval=0.01)
    coordinator.start()
    try:
        # This coroutine can keep scheduling while the SQL worker is blocked.
        async def wait_for_worker():
            while not entered.is_set():
                await asyncio.sleep(0.001)

        await asyncio.wait_for(wait_for_worker(), timeout=1)
        assert not started.is_set()
        release.set()
        await asyncio.wait_for(started.wait(), timeout=1)
    finally:
        release.set()
        await coordinator.stop()
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_primary_failure_survives_cleanup_and_backend_is_closed(
    monkeypatch, tmp_path
):
    from ultima_scraper_backend.api import dependencies
    from ultima_scraper_backend.plugin_system import (
        platform,
        postgres_repository,
        runtime_owner,
    )

    error = database_error("57P03")
    closed = []

    async def failed():
        raise error

    task = asyncio.create_task(failed())
    await asyncio.sleep(0)
    fake_platform = SimpleNamespace(
        load_all=lambda: None,
        attach_backend=lambda _backend: None,
        runtime_tasks=lambda: [task],
        _runtime_started=True,
    )

    class Coordinator:
        def __init__(self, *_args):
            self._task = None

        def start(self):
            pass

        async def stop(self):
            closed.append("coordinator")
            raise RuntimeError("cleanup must not hide primary failure")

    async def get_backend():
        return None

    async def shutdown_backend():
        closed.append("backend")

    monkeypatch.setenv("USR_PLUGINS_DIR", str(tmp_path))
    monkeypatch.setattr(
        postgres_repository, "PostgresPluginRepository", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        platform, "PluginPlatform", lambda *_args, **_kwargs: fake_platform
    )
    monkeypatch.setattr(runtime_owner, "PluginRuntimeCoordinator", Coordinator)
    monkeypatch.setattr(dependencies, "get_backend_instance", get_backend)
    monkeypatch.setattr(dependencies, "shutdown_backend", shutdown_backend)
    with pytest.raises(OperationalError) as caught:
        await supervisor.serve(asyncio.Event())
    assert caught.value is error
    assert closed == ["coordinator", "backend"]
