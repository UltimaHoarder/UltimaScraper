"""Plugin transactions do not need another server connection to read time."""

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from ultima_scraper_backend.plugin_system.postgres_repository import (
    PostgresPluginRepository,
)


def make_repository(*, fail_setup=False):
    opened = []
    active = []
    finished = []
    now = datetime(2026, 10, 14, tzinfo=UTC)

    class Session:
        def execute(self, _statement):
            if fail_setup:
                raise RuntimeError("pool unavailable")

        def scalar(self, statement):
            assert str(statement) == "SELECT clock_timestamp()"
            return now

        def connection(self, **_kwargs):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

    @contextmanager
    def factory():
        # Emulate a pool with one available connection.
        assert not active, "a transaction attempted to acquire a second connection"
        session = Session()
        opened.append(session)
        active.append(session)
        try:
            yield session
        finally:
            active.remove(session)
            finished.append(session)

    repository = PostgresPluginRepository.__new__(PostgresPluginRepository)
    repository.session_factory = factory
    return repository, opened, active, finished, now


@pytest.mark.parametrize("transaction", [True, False])
def test_database_clock_reuses_active_plugin_transaction(transaction):
    repository, opened, active, finished, now = make_repository()
    if transaction:
        assert repository._transaction(lambda _connection: repository.now()) == now
    else:
        with repository._connect():
            assert repository.now() == now
    assert len(opened) == len(finished) == 1
    assert not active
    # The completed operation must not leave a session in the current context.
    assert repository.now() == now
    assert len(opened) == len(finished) == 2


def test_failed_transaction_setup_closes_owned_session():
    repository, opened, active, finished, _now = make_repository(fail_setup=True)
    with pytest.raises(RuntimeError, match="pool unavailable"):
        repository._connect()
    assert not active
    assert opened == finished


def test_failed_callback_clears_transaction_context():
    repository, opened, active, finished, now = make_repository()

    def fail(_connection):
        assert repository.now() == now
        raise ValueError("callback failed")

    with pytest.raises(ValueError, match="callback failed"):
        repository._transaction(fail)
    assert not active
    assert opened == finished
    assert repository.now() == now
    assert len(opened) == len(finished) == 2


def test_nested_repositories_restore_the_previous_transaction_context():
    first, first_opened, _active, first_finished, now = make_repository()
    second, second_opened, _active, second_finished, _now = make_repository()
    with first._connect():
        with second._connect():
            assert second.now() == now
        assert first.now() == now
    assert len(first_opened) == len(first_finished) == 1
    assert len(second_opened) == len(second_finished) == 1
