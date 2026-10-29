"""The opt-in pool watch reports long-held connections with their holder's stack."""

import logging
import threading
import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from ultima_scraper_db_archive import pool_watch
from ultima_scraper_db_archive.pool_watch import install_pool_watch, watch_threshold_seconds


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pool.db'}", poolclass=QueuePool, pool_size=2, max_overflow=0,
        connect_args={"check_same_thread": False},
    )
    yield engine
    engine.dispose()


def hold_connection_for_a_while(engine, started, release):
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        started.set()
        release.wait(5)


def test_watch_is_off_by_default_and_parses_its_switch(monkeypatch, engine):
    monkeypatch.delenv("ULTIMA_DB_POOL_WATCH_SECONDS", raising=False)
    assert watch_threshold_seconds() == 0.0
    assert install_pool_watch(engine) is None
    for raw, expected in (("2.5", 2.5), ("0", 0.0), ("-1", 0.0), ("soon", 0.0), ("", 0.0)):
        monkeypatch.setenv("ULTIMA_DB_POOL_WATCH_SECONDS", raw)
        assert watch_threshold_seconds() == expected


def test_long_hold_is_reported_once_with_the_holders_stack(engine, caplog):
    watch = install_pool_watch(engine, threshold=0.1)
    started, release = threading.Event(), threading.Event()
    holder = threading.Thread(target=hold_connection_for_a_while, args=(engine, started, release))
    caplog.set_level(logging.WARNING, logger=pool_watch.__name__)
    holder.start()
    try:
        assert started.wait(5)
        deadline = time.monotonic() + 5
        while "connection held" not in caplog.text and time.monotonic() < deadline:
            time.sleep(0.02)
        held = [r.getMessage() for r in caplog.records if "connection held" in r.getMessage()]
        assert len(held) == 1
        # The holder thread's current stack, not the watch thread's.
        assert "hold_connection_for_a_while" in held[0] and "release.wait" in held[0]
        assert "1 checked out" in held[0] and "Checked out connections: 1" in held[0]
        time.sleep(0.3)
        assert watch.scan() == 0  # Already reported.
    finally:
        release.set()
        holder.join(5)
    returned = [r.getMessage() for r in caplog.records if "returned after" in r.getMessage()]
    assert len(returned) == 1 and not watch.held and not watch.reported


def test_short_holds_stay_quiet(engine, caplog):
    watch = install_pool_watch(engine, threshold=5)
    caplog.set_level(logging.WARNING, logger=pool_watch.__name__)
    for _ in range(20):
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    assert watch.scan() == 0 and not watch.held
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_caller_names_the_first_project_frame():
    namespace = {"caller": pool_watch._caller}
    # Compiled under a project-like path, the way package code is.
    code = compile("def claim():\n    return listener()\ndef listener():\n    return caller()\n",
                   "/home/u/USV/UltimaBackends/ultima_scraper_backend/job_system/ledger.py", "exec")
    exec(code, namespace)
    # _caller skips its own frame and the pool listener's frame.
    assert namespace["claim"]() == "UltimaBackends/ultima_scraper_backend/job_system/ledger.py:2 claim"
