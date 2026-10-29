"""Native ownership, read-only, admission and cleanup checks for index warming."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock, current_thread
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from test_mps_archive_identity_directory import (
    ledger,
    ledger_engine,
    postgres_engine,
    repartition,
)
from test_mps_archive_set_inserts import completed_range
from ultima_scraper_backend.database import archive_prefetch as prefetch

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def cold(monkeypatch):
    # The owned fixture is small; exercise the path selected by production's
    # larger-than-cache directory without manufacturing gigabytes of history.
    monkeypatch.setattr(prefetch, "_index_is_cold", lambda session: True)


def assert_archived(ledger, job, count):
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"), {"job": job}) == count
        assert session.scalar(text("SELECT count(*) FROM management.job_task_identities WHERE job_id=:job"), {"job": job}) == count
        assert session.scalar(text("SELECT count(*) FROM management.execution_work WHERE run_id=:job"), {"job": job}) == 0
        assert session.scalar(text("SELECT count(*) FROM management.execution_work_payloads WHERE run_id=:job"), {"job": job}) == 0
        assert session.scalar(text("SELECT cursor FROM management.mps_plans WHERE job_id=:job"), {"job": job}) == count


def test_three_owned_readers_preserve_exact_archive(ledger, ledger_engine, monkeypatch):
    job = completed_range(ledger, 2048)
    repartition(ledger_engine)
    cold(monkeypatch)
    original = prefetch._read
    barrier = Barrier(3)
    threads = set()
    lock = Lock()
    outcomes = []

    def reader(*args):
        with lock:
            threads.add(current_thread().ident)
        barrier.wait(timeout=5)
        result = original(*args)
        with lock:
            outcomes.append(result)
        return result

    monkeypatch.setattr(prefetch, "_read", reader)
    assert ledger.archive_tick() == job
    assert len(threads) == 3 and outcomes == [True] * 3
    assert_archived(ledger, job, 2048)


def test_disabled_prefetch_skips_readers_and_still_archives(ledger, ledger_engine, monkeypatch):
    job = completed_range(ledger, 2048)
    repartition(ledger_engine)
    cold(monkeypatch)
    monkeypatch.setenv("ULTIMA_ARCHIVE_PREFETCH", "0")
    reads = []
    monkeypatch.setattr(prefetch, "_read", lambda *args: reads.append(args) or True)
    assert ledger.archive_tick() == job
    assert reads == []
    assert_archived(ledger, job, 2048)


@pytest.mark.parametrize("value,enabled", [
    (None, True), ("1", True), ("on", True),
    ("0", False), ("false", False), (" OFF ", False), ("no", False),
])
def test_prefetch_switch_values(monkeypatch, value, enabled):
    if value is None:
        monkeypatch.delenv("ULTIMA_ARCHIVE_PREFETCH", raising=False)
    else:
        monkeypatch.setenv("ULTIMA_ARCHIVE_PREFETCH", value)
    assert prefetch.prefetch_enabled() is enabled


def test_reader_cannot_write_even_with_owner_credentials(ledger_engine):
    with ledger_engine.begin() as connection:
        connection.execute(text("CREATE TABLE public.archive_prefetch_canary(value integer)"))
    dialect = ledger_engine.dialect
    arguments, parameters = dialect.create_connect_args(ledger_engine.url)
    result = prefetch._read(
        dialect.loaded_dbapi, arguments, {**parameters, "connect_timeout": 3},
        "INSERT INTO public.archive_prefetch_canary "
        "SELECT cardinality(CAST(%(ids)s AS text[])) WHERE %(job)s IS NOT NULL",
        "job-canary", ["task-a"],
    )
    assert result is False
    with ledger_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM public.archive_prefetch_canary")) == 0


def test_slow_reader_is_cancelled_by_its_statement_timeout(ledger_engine):
    dialect = ledger_engine.dialect
    arguments, parameters = dialect.create_connect_args(ledger_engine.url)
    assert prefetch._read(
        dialect.loaded_dbapi, arguments, {**parameters, "connect_timeout": 3},
        "SELECT pg_sleep(4) WHERE %(job)s IS NOT NULL "
        "AND cardinality(CAST(%(ids)s AS text[]))>0",
        "job-timeout", ["task-a"],
    ) is False


def test_disabled_guard_retains_legacy_archive_without_readers(ledger, ledger_engine, monkeypatch):
    job = completed_range(ledger, 1024)
    repartition(ledger_engine)
    with ledger_engine.begin() as connection:
        connection.execute(text("ALTER TABLE management.job_tasks DISABLE TRIGGER history_identity_guard"))

    def unexpected(*args):
        pytest.fail("Legacy ownership validation must not use index prefetch")

    monkeypatch.setattr(prefetch, "prefetch_archive_keys", unexpected)
    assert ledger.archive_tick() == job
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"), {"job": job}) == 1024
        assert session.scalar(text("SELECT count(*) FROM management.execution_work WHERE run_id=:job"), {"job": job}) == 0


def test_input_generator_and_each_reader_remain_bounded(monkeypatch):
    cold(monkeypatch)
    lengths = []
    dialect = SimpleNamespace(
        name="postgresql", driver="psycopg", loaded_dbapi=None,
        create_connect_args=lambda url: ([], {}),
    )
    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=dialect, url=None), scalar=lambda query: True
    )

    def ids():
        for index in range(2048):
            yield f"task-{index}"
        pytest.fail("The optional read hint consumed more than one bounded batch")

    def reader(*args):
        lengths.append(len(args[-1]))
        return True

    monkeypatch.setattr(prefetch, "_read", reader)
    prefetch.prefetch_archive_keys(session, "job-a", ids())
    assert lengths == [2048] * 3


def test_failed_readers_fall_back_to_canonical_archive(ledger, ledger_engine, monkeypatch):
    job = completed_range(ledger, 1024)
    repartition(ledger_engine)
    cold(monkeypatch)
    outcomes = []

    def failed(*args):
        outcomes.append(False)
        return False

    monkeypatch.setattr(prefetch, "_read", failed)
    assert ledger.archive_tick() == job
    assert outcomes == [False] * 3
    assert_archived(ledger, job, 1024)


def test_hot_directory_keeps_existing_archive_path(ledger, ledger_engine, monkeypatch):
    job = completed_range(ledger, 1024)
    repartition(ledger_engine)

    def unexpected(*args):
        pytest.fail("A directory fitting in shared buffers should not open readers")

    monkeypatch.setattr(prefetch, "_read", unexpected)
    assert ledger.archive_tick() == job
    assert_archived(ledger, job, 1024)


def test_ownership_claim_after_prefetch_still_rolls_back(ledger, ledger_engine, monkeypatch):
    from ultima_scraper_backend.job_system.models import Job, Task
    from ultima_scraper_backend.job_system.storage import _task_to_central_row
    from ultima_scraper_db_archive.global_db import CentralTaskModel

    job = completed_range(ledger, 1024)
    other = Job.create(name="Prefetch race", created_by="test", tasks=[])
    ledger.manifests.create(job_id=other.job_id, site="onlyfans", job_config=other.to_dict(),
                            selection={"start_id": 2, "end_id": 2, "max_profiles": None},
                            proxy_pool=[], site_session_factory=ledger.session_factory)
    repartition(ledger_engine)
    cold(monkeypatch)
    original = prefetch.prefetch_archive_keys
    chosen = []

    def racing(session, job_id, task_ids, **options):
        ids = list(task_ids)
        original(session, job_id, iter(ids), **options)
        item = Task.from_dict(json.loads(session.scalar(text(
            "SELECT payload_json FROM management.execution_work_payloads WHERE run_id=:job AND task_id=:task"
        ), {"job": job, "task": ids[0]})))
        with ledger.session_factory() as competing:
            competing.execute(CentralTaskModel.__table__.insert(), _task_to_central_row(item, other.job_id))
            competing.commit()
        chosen.append(ids[0])

    monkeypatch.setattr(prefetch, "prefetch_archive_keys", racing)
    with pytest.raises(ValueError, match="Archived task belongs to another job"):
        ledger.archive_tick()
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT cursor FROM management.mps_plans WHERE job_id=:job"), {"job": job}) == 0
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"), {"job": job}) == 0
        assert session.scalar(text("SELECT count(*) FROM management.execution_work WHERE run_id=:job"), {"job": job}) == 1024
        assert session.scalar(text("SELECT job_id FROM management.job_task_identities WHERE task_id=:task"), {"task": chosen[0]}) == other.job_id


def test_global_budget_is_held_until_archive_transaction_ends(ledger, ledger_engine, monkeypatch):
    job = completed_range(ledger, 1)
    repartition(ledger_engine)
    cold(monkeypatch)
    readers_started = Barrier(4)
    release_readers = Event()
    reads_done = Event()
    release_transaction = Event()
    calls = []

    def reader(*args):
        calls.append(current_thread().ident)
        if len(calls) <= 3:
            readers_started.wait(timeout=5)
            assert release_readers.wait(5)
        return True

    monkeypatch.setattr(prefetch, "_read", reader)

    def owner():
        with ledger.session_factory() as session:
            prefetch.prefetch_archive_keys(session, job, iter(["task-a"] * 1024))
            reads_done.set()
            assert release_transaction.wait(5)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owner)
        try:
            readers_started.wait(timeout=5)
            with ledger.session_factory() as session:
                prefetch.prefetch_archive_keys(session, job, iter(["task-b"] * 1024))
                assert len(calls) == 3
                release_readers.set()
                assert reads_done.wait(5)
                prefetch.prefetch_archive_keys(session, job, iter(["task-b"] * 1024))
                assert len(calls) == 3
            release_transaction.set()
            future.result(timeout=5)
            with ledger.session_factory() as session:
                prefetch.prefetch_archive_keys(session, job, iter(["task-b"] * 1024))
            assert len(calls) == 6
        finally:
            release_readers.set()
            release_transaction.set()


def test_partial_submission_keeps_ownership_until_reader_closes(monkeypatch):
    cold(monkeypatch)
    entered = Event()
    release = Event()
    parameters = SimpleNamespace(
        name="postgresql", driver="psycopg", loaded_dbapi=None,
        create_connect_args=lambda url: ([], {}),
    )
    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=parameters, url=None), scalar=lambda query: True
    )
    with ThreadPoolExecutor(max_workers=1) as read_pool, ThreadPoolExecutor(max_workers=1) as caller:
        def slow_reader():
            entered.set()
            assert release.wait(5)

        class BrokenSubmit:
            calls = 0

            def submit(self, *args):
                self.calls += 1
                if self.calls == 1:
                    return read_pool.submit(slow_reader)
                raise RuntimeError("executor unavailable")

        monkeypatch.setattr(prefetch, "_readers", BrokenSubmit())
        result = caller.submit(prefetch.prefetch_archive_keys, session, "job-a", iter(["task-a"] * 1024))
        try:
            assert entered.wait(5)
            assert not result.done()
        finally:
            release.set()
        assert result.result(timeout=5) is None
