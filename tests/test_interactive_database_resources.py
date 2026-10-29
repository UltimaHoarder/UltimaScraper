"""SQL paging, bounded thread admission and cancellation against owned fixtures."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import inspect
import os
import threading
import time
from types import SimpleNamespace

from anyio import CancelScope, to_thread
import pytest
from sqlalchemy import event, text
from sqlmodel import Session

import test_content_write_resources as database_fixtures
from ultima_scraper_backend.database import threads as database_threads

postgres_engine = database_fixtures.postgres_engine
content_engine = database_fixtures.content_engine


@pytest.fixture(autouse=True)
def isolated_budget(monkeypatch):
    monkeypatch.setattr(
        database_threads, "runtime_env_value", lambda name: os.environ.get(name)
    )
    monkeypatch.delenv("ULTIMA_INTERACTIVE_DB_CONCURRENCY", raising=False)


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.asyncio
async def test_thread_admission_has_no_executor_backlog(monkeypatch):
    monkeypatch.setenv("ULTIMA_INTERACTIVE_DB_CONCURRENCY", "3")
    release = threading.Event()
    started = []
    finished = []
    loop_thread = threading.get_ident()

    def query(identifier):
        assert threading.get_ident() != loop_thread
        started.append(identifier)
        try:
            assert release.wait(3)
            return identifier * 2
        finally:
            finished.append(identifier)

    tasks = [
        asyncio.create_task(database_threads.run_database_call(query, index))
        for index in range(20)
    ]
    try:
        await eventually(lambda: len(started) == 3)
        await asyncio.sleep(0.02)
        assert len(started) == 3
        limiter = database_threads.database_thread_limiter()
        assert limiter.borrowed_tokens == 3
        assert limiter.statistics().tasks_waiting == 17
    finally:
        release.set()
        results = await asyncio.gather(*tasks)
    assert results == [index * 2 for index in range(20)]
    assert len(finished) == 20
    assert limiter.borrowed_tokens == 0


@pytest.mark.asyncio
async def test_cancellation_keeps_session_owned_and_waiters_do_not_execute(monkeypatch):
    monkeypatch.setenv("ULTIMA_INTERACTIVE_DB_CONCURRENCY", "1")
    release = threading.Event()
    started = threading.Event()
    closed = threading.Event()
    unexpected = threading.Event()

    def query():
        started.set()
        try:
            assert release.wait(3)
        finally:
            closed.set()

    active = asyncio.create_task(database_threads.run_database_call(query))
    waiting = None
    try:
        await eventually(started.is_set)
        active.cancel()
        await asyncio.sleep(0)
        active.cancel()
        waiting = asyncio.create_task(
            database_threads.run_database_call(unexpected.set)
        )
        await asyncio.sleep(0.02)
        assert not active.done()
        assert not closed.is_set()
        assert not unexpected.is_set()
        assert database_threads.database_thread_limiter().borrowed_tokens == 1
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await active
        assert closed.is_set()
        assert not unexpected.is_set()
        assert await database_threads.run_database_call(lambda: "next") == "next"
    finally:
        release.set()
        await asyncio.gather(
            *[task for task in (active, waiting) if task is not None],
            return_exceptions=True,
        )


@pytest.mark.asyncio
async def test_anyio_scope_cancellation_still_waits_for_cleanup(monkeypatch):
    monkeypatch.setenv("ULTIMA_INTERACTIVE_DB_CONCURRENCY", "1")
    release = threading.Event()
    started = threading.Event()
    closed = threading.Event()

    def query():
        started.set()
        try:
            assert release.wait(3)
        finally:
            closed.set()

    scopes = []

    async def request():
        with CancelScope() as scope:
            scopes.append(scope)
            await database_threads.run_database_call(query)
        assert closed.is_set()

    task = asyncio.create_task(request())
    try:
        await eventually(started.is_set)
        scopes[0].cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        assert database_threads.database_thread_limiter().borrowed_tokens == 1
    finally:
        release.set()
        await task
    assert database_threads.database_thread_limiter().borrowed_tokens == 0


@pytest.mark.asyncio
async def test_inherits_shared_limiter_and_never_clamps_explicit_budget(monkeypatch):
    shared = to_thread.current_default_thread_limiter()
    original = shared.total_tokens
    try:
        shared.total_tokens = 2
        assert database_threads.database_thread_limiter() is shared
        monkeypatch.setenv("ULTIMA_INTERACTIVE_DB_CONCURRENCY", "257")
        private = database_threads.database_thread_limiter()
        assert private is not shared
        assert private.total_tokens == 257
        assert shared.total_tokens == 2
        assert await database_threads.run_database_call(lambda: 9) == 9
    finally:
        shared.total_tokens = original


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["0", "-1", "true", "1.5", "broken"])
async def test_invalid_budget_fails_before_thread_admission(monkeypatch, value):
    monkeypatch.setenv("ULTIMA_INTERACTIVE_DB_CONCURRENCY", value)
    called = []
    with pytest.raises(ValueError, match="positive integer"):
        await database_threads.run_database_call(lambda: called.append(True))
    assert called == []


@pytest.mark.asyncio
async def test_query_exception_releases_admission(monkeypatch):
    monkeypatch.setenv("ULTIMA_INTERACTIVE_DB_CONCURRENCY", "1")

    def failed():
        raise LookupError("query failed")

    with pytest.raises(LookupError, match="query failed"):
        await database_threads.run_database_call(failed)
    assert database_threads.database_thread_limiter().borrowed_tokens == 0
    assert await database_threads.run_database_call(lambda: "usable") == "usable"


def isolated_site(monkeypatch, engine, *routes):
    loop_thread = threading.get_ident()
    lifecycle = []

    @contextmanager
    def get_session():
        owner = threading.get_ident()
        assert owner != loop_thread
        lifecycle.append(("open", owner))
        try:
            with Session(engine) as session:
                yield session
        finally:
            assert threading.get_ident() == owner
            lifecycle.append(("close", owner))

    manager = SimpleNamespace(get_session=get_session)
    for route in routes:
        monkeypatch.setattr(
            route,
            "MultiSiteDatabaseManager",
            lambda: SimpleNamespace(get_or_create_manager=lambda site: manager),
        )
    return lifecycle


@pytest.mark.asyncio
async def test_history_transfers_only_a_stable_page_from_100000_rows(
    content_engine, monkeypatch
):
    from ultima_scraper_backend.api.routes import database_browser
    from ultima_scraper_db_archive import HistoUserInfoModel, UserModel

    with content_engine.begin() as connection:
        connection.execute(text("UPDATE users SET username='fixture' WHERE id=7"))
        connection.execute(
            text(
                "INSERT INTO histo_user_infos (id,user_id,description,created_at) "
                "SELECT n,7,repeat('x',512),'2026-09-05'::timestamptz "
                "FROM generate_series(1,100000) n"
            )
        )

    lifecycle = isolated_site(monkeypatch, content_engine, database_browser)
    loaded = []
    returned = []
    queries = []

    def on_load(row, context):
        loaded.append(type(row))

    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)
        returned.append(cursor.rowcount)

    event.listen(HistoUserInfoModel, "load", on_load)
    event.listen(UserModel, "load", on_load)
    event.listen(content_engine, "after_cursor_execute", capture)
    try:
        response = await database_browser.get_user_history(
            7, site="onlyfans", page=1000, page_size=50
        )
        assert response.success, response.error
        assert response.total == 100000
        assert [row.id for row in response.snapshots] == list(range(50050, 50000, -1))
        assert all(row.username == "fixture" for row in response.snapshots)
        assert loaded == [HistoUserInfoModel] * 50
        assert returned == [1, 50]
        assert len(queries) == 2
        assert "LIMIT" in queries[-1] and "OFFSET" in queries[-1]
        assert len(lifecycle) == 2 and lifecycle[0][1] == lifecycle[1][1]
    finally:
        event.remove(HistoUserInfoModel, "load", on_load)
        event.remove(UserModel, "load", on_load)
        event.remove(content_engine, "after_cursor_execute", capture)

    empty = await database_browser.get_user_history(
        7, site="onlyfans", page=2001, page_size=50
    )
    assert empty.success and empty.total == 100000 and empty.snapshots == []
    missing = await database_browser.get_user_history(
        999999, site="onlyfans", page=1, page_size=50
    )
    assert missing.success and missing.total == 0 and missing.snapshots == []


@pytest.mark.asyncio
async def test_user_list_bounds_tied_media_and_remains_responsive(
    content_engine, monkeypatch
):
    from ultima_scraper_backend.api.routes import orders, users
    from ultima_scraper_db_archive import UserProfileMediaModel

    with content_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO user_profile_media(id,user_id,avatar_url,created_at) "
                "SELECT n,7,'avatar-' || n,'2026-09-05'::timestamptz "
                "FROM generate_series(1,10000) n"
            )
        )
    lifecycle = isolated_site(monkeypatch, content_engine, users)
    monkeypatch.setattr(
        orders, "create_orders_session", lambda: Session(content_engine)
    )
    loaded = []
    threads = []
    heartbeat = []

    def on_load(row, context):
        loaded.append(row.id)

    def slow_query(conn, cursor, statement, parameters, context, executemany):
        threads.append(threading.get_ident())
        time.sleep(0.025)

    async def pulse():
        while True:
            heartbeat.append(time.monotonic())
            await asyncio.sleep(0.005)

    arguments = {
        name: getattr(parameter.default, "default", parameter.default)
        for name, parameter in inspect.signature(users.list_users).parameters.items()
    }
    arguments.update(site="onlyfans", limit=2, offset=0)
    event.listen(UserProfileMediaModel, "load", on_load)
    event.listen(content_engine, "before_cursor_execute", slow_query)
    ticker = asyncio.create_task(pulse())
    try:
        response = await users.list_users(**arguments)
        assert response.success, response.error
        assert response.total == 2 and len(response.users) == 2
        assert loaded == [10000]
        assert (
            next(row for row in response.users if row.id == 7).avatar_url
            == "avatar-10000"
        )
        assert len(heartbeat) >= 10
        assert threads and threading.get_ident() not in threads
        assert [kind for kind, _ in lifecycle] == ["open", "close"]
    finally:
        event.remove(UserProfileMediaModel, "load", on_load)
        event.remove(content_engine, "before_cursor_execute", slow_query)
        ticker.cancel()
        await asyncio.gather(ticker, return_exceptions=True)


@pytest.mark.asyncio
async def test_profile_reads_and_size_aggregation_share_owned_session(
    content_engine, monkeypatch
):
    from ultima_scraper_backend.api.routes import users

    lifecycle = isolated_site(monkeypatch, content_engine, users)

    async def availability(*args, **kwargs):
        assert lifecycle[-1][0] == "close"
        return None

    monkeypatch.setattr(
        users.StatisticsService, "get_statistics_availability", availability
    )
    monkeypatch.setattr(users, "_ensure_profile_refresh_started", lambda *args: False)
    response = await users.get_user_profile(
        7, site="onlyfans", backend=SimpleNamespace(redis=None)
    )
    assert response.success, response.error
    assert response.user is not None
    assert response.user.size_source == "unknown"
    assert [kind for kind, _ in lifecycle] == ["open", "close", "open", "close"]
    assert len(response.user.profile_media_history) == 20
