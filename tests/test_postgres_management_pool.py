"""Bounded management reuse on an owned PostgreSQL cluster, never production."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError
from sqlalchemy.pool import NullPool
from test_mps_manifest import postgres_engine
from ultima_scraper_db_archive import global_db

__all__ = ["postgres_engine"]


@pytest.fixture
def management_engine(postgres_engine, monkeypatch):
    previous = global_db._postgres_engine
    monkeypatch.setattr(
        global_db,
        "runtime_env_value",
        lambda key: {
            "ULTIMA_USE_PGBOUNCER": "true",
            "ULTIMA_PGBOUNCER_GLOBAL_POOL_MODE": "transaction",
            "ULTIMA_PGBOUNCER_GLOBAL_POOL_SIZE": "1",
        }.get(key),
    )
    global_db.set_postgres_url(
        postgres_engine.url.render_as_string(hide_password=False)
    )
    engine = global_db.get_postgres_engine()
    try:
        yield engine
    finally:
        engine.dispose()
        global_db._postgres_engine = previous


def test_reuse_rollback_local_state_and_bounded_checkout(management_engine):
    engine = management_engine
    with engine.connect() as connection:
        pid = connection.scalar(text("SELECT pg_backend_pid()"))
        connection.execute(text("SET LOCAL search_path TO management"))
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT pg_backend_pid()")) == pid
        assert connection.scalar(text("SHOW search_path")) != "management"
        connection.execute(text("SET LOCAL statement_timeout='1s'"))
        connection.commit()
    with engine.connect() as connection:
        assert connection.scalar(text("SHOW statement_timeout")) == "0"
        engine.pool._timeout = 0.05
        with ThreadPoolExecutor(1) as executor:
            future = executor.submit(engine.connect)
            with pytest.raises(TimeoutError):
                future.result(timeout=2)
        assert engine.pool.size() == 1
        assert engine.pool.overflow() == 0


def test_management_pool_reconnects_after_a_backend_disconnect(
    management_engine, postgres_engine
):
    engine = management_engine
    with engine.connect() as connection:
        pid = connection.scalar(text("SELECT pg_backend_pid()"))
    with postgres_engine.begin() as connection:
        assert connection.scalar(
            text("SELECT pg_terminate_backend(:pid)"), {"pid": pid}
        )
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT pg_backend_pid()")) != pid


def test_session_advisory_lock_keeps_its_dedicated_connection(
    management_engine, postgres_engine
):
    from ultima_scraper_db_archive.migration_cli import (
        LOCK_NAME,
        _acquire_lock,
        _release_lock,
    )

    dedicated = create_engine(postgres_engine.url, poolclass=NullPool)
    try:
        with dedicated.connect() as lock_connection:
            _acquire_lock(lock_connection)  # Commits, but deliberately retains the lock.
            for _ in range(2):
                with management_engine.connect() as ordinary:
                    assert not ordinary.scalar(
                        text("SELECT pg_try_advisory_xact_lock(hashtext(:name))"),
                        {"name": LOCK_NAME},
                    )
            _release_lock(lock_connection)
            with management_engine.connect() as ordinary:
                assert ordinary.scalar(
                    text("SELECT pg_try_advisory_xact_lock(hashtext(:name))"),
                    {"name": LOCK_NAME},
                )
        assert isinstance(dedicated.pool, NullPool)
    finally:
        dedicated.dispose()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork")
def test_child_reconnects_without_damaging_parent_socket(management_engine):
    engine = management_engine
    with engine.connect() as connection:
        parent_backend = connection.scalar(text("SELECT pg_backend_pid()"))
    parent_pool = engine.pool
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read_fd)
            assert engine.pool is not parent_pool
            with engine.connect() as connection:
                child_backend = connection.scalar(text("SELECT pg_backend_pid()"))
            os.write(write_fd, str(child_backend).encode())
            os._exit(0)
        except BaseException:  # noqa: BLE001 - a forked child must never run parent fixture cleanup
            os._exit(1)
    os.close(write_fd)
    try:
        payload = os.read(read_fd, 64)
        _, status = os.waitpid(pid, 0)
        assert status == 0 and payload
        child_backend = int(payload)
        assert child_backend != parent_backend
        assert engine.pool is parent_pool
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT pg_backend_pid()")) == parent_backend
    finally:
        os.close(read_fd)
