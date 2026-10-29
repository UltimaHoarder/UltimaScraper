"""Finished runs' outbox and mutation leaves retire; task history stays."""

import importlib.util
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from test_execution_ledger import (
    claim,
    finish,
    ledger,
    ledger_engine,
    postgres_engine,
    submit,
    task,
)
from ultima_scraper_backend.database import history_retirement, outbox_retention
from ultima_scraper_backend.database.job_partitions import partition_name
from ultima_scraper_backend.database.receipt_retention import ReceiptQueueSnapshot

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


@pytest.fixture(scope="module")
def partitioned(ledger_engine):
    path = (
        Path(__file__).resolve().parents[2]
        / "UltimaDatabases/UltimaScraperDBArchive/ultima_scraper_db_archive/migrations/alembic/versions/c92ea6407b31_partition_all_job_history.py"
    )
    spec = importlib.util.spec_from_file_location("history_retirement_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with (
        ledger_engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.upgrade()
    return ledger_engine


@pytest.fixture
def history(partitioned, ledger, monkeypatch):
    # The ledger fixture resets the event feed but not these migration-owned
    # directories; a retained leaf's rows would collide with new sequences.
    with partitioned.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE management.execution_outbox_identities, management.execution_attempt_identities, management.job_task_identities"
            )
        )
    monkeypatch.setattr(outbox_retention, "_plugin_event_floor", lambda session: None)
    return ledger


def _finished(ledger, run_id, *, deliver=True):
    submit(ledger, [task(f"{run_id}-task")], identity=run_id)
    assert ledger.tick() == run_id
    finish(ledger, claim(ledger))
    ledger.tick()
    assert ledger.job(run_id)["state"] == "completed"
    while deliver and ledger.relay(publish_many=lambda payloads: None):
        pass


def _leaves(engine, run_id):
    with engine.connect() as connection:
        return {
            table
            for table in (
                "execution_outbox",
                "execution_mutations",
                "execution_attempts",
                "job_tasks",
            )
            if connection.scalar(
                text("SELECT to_regclass(:name)"),
                {"name": "management." + partition_name(run_id, table)},
            )
        }


def _retire(ledger, **kwargs):
    return history_retirement.retire_finished_history(
        session_factory=ledger.session_factory, **{"grace_seconds": 0, **kwargs}
    )


def test_finished_run_retires_events_and_mutations_but_keeps_task_history(
    history, partitioned
):
    _finished(history, "job-retire")
    assert _leaves(partitioned, "job-retire") == {
        "execution_outbox",
        "execution_mutations",
        "execution_attempts",
        "job_tasks",
    }
    assert _retire(history) == {"retired": 2, "busy": 0, "waiting": 0}
    assert _leaves(partitioned, "job-retire") == {"execution_attempts", "job_tasks"}
    with partitioned.connect() as connection:
        # DROP fires no row triggers; the same cycle then purges the directory.
        assert not connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM management.execution_outbox_identities WHERE run_id='job-retire')"
            )
        )
    assert history.job("job-retire")["state"] == "completed"
    assert history.task("job-retire", "job-retire-task")["result"]["output"] == {
        "value": 7
    }
    # Parent-wide readers no longer see the run, and nothing remains to retire.
    assert history.events(after=0) == []
    assert _retire(history) == {"retired": 0, "busy": 0, "waiting": 0}


def test_retirement_waits_for_grace_delivery_floor_and_queued_writes(
    history, partitioned, monkeypatch
):
    _finished(history, "job-young")
    assert _retire(history, grace_seconds=3600)["retired"] == 0
    assert _leaves(partitioned, "job-young") >= {"execution_outbox", "execution_mutations"}

    assert _retire(history, protected_run_ids={"job-young"})["retired"] == 0
    assert _leaves(partitioned, "job-young") >= {"execution_outbox", "execution_mutations"}

    # A plugin that has not consumed the run's events keeps its outbox leaf.
    monkeypatch.setattr(outbox_retention, "_plugin_event_floor", lambda session: 0)
    assert _retire(history) == {"retired": 1, "busy": 0, "waiting": 1}
    assert "execution_outbox" in _leaves(partitioned, "job-young")
    assert "execution_mutations" not in _leaves(partitioned, "job-young")

    _finished(history, "job-undelivered", deliver=False)
    monkeypatch.setattr(outbox_retention, "_plugin_event_floor", lambda session: None)
    result = _retire(history)
    assert "execution_outbox" in _leaves(partitioned, "job-undelivered")
    assert "execution_outbox" not in _leaves(partitioned, "job-young")
    assert result["retired"] == 2 and result["waiting"] == 1

    # Once the relay delivers, the leaf follows.
    while history.relay(publish_many=lambda payloads: None):
        pass
    assert _retire(history)["retired"] == 1
    assert _leaves(partitioned, "job-undelivered") == {"execution_attempts", "job_tasks"}


def test_busy_parent_defers_retirement_without_blocking_readers(history, partitioned):
    _finished(history, "job-busy")
    with partitioned.connect() as blocker:
        blocker.execute(text("SELECT event_id FROM management.execution_outbox LIMIT 1"))
        blocker.execute(text("SELECT command_id FROM management.execution_mutations LIMIT 1"))
        assert _retire(history) == {"retired": 0, "busy": 2, "waiting": 0}
    assert _leaves(partitioned, "job-busy") >= {"execution_outbox", "execution_mutations"}
    assert _retire(history)["retired"] == 2


def test_control_on_retired_run_restores_its_event_leaf(history, partitioned):
    _finished(history, "job-renamed")
    assert _retire(history)["retired"] == 2
    history.control("job-renamed", "update", name="Renamed after retirement")
    assert _leaves(partitioned, "job-renamed") >= {
        "execution_outbox",
        "execution_mutations",
    }
    events = []
    while history.relay(publish_many=events.extend):
        pass
    assert events and {event["job_id"] for event in events} == {"job-renamed"}
    assert _retire(history)["retired"] == 2


def test_deletion_finishes_after_retirement(history, partitioned):
    _finished(history, "job-delete-retired")
    assert _retire(history)["retired"] == 2
    assert history.delete("job-delete-retired", receipt_queue=ReceiptQueueSnapshot()) is True
    assert history.job("job-delete-retired") is None
    assert _leaves(partitioned, "job-delete-retired") == set()


def test_reclaim_skips_a_leaf_retired_after_listing(history, partitioned, monkeypatch):
    _finished(history, "job-reclaim-race")
    leaf = partition_name("job-reclaim-race", "execution_outbox")
    listed = Event()
    original = history.session_factory

    # Retire between reclaim's listing transaction and its per-leaf lock.
    calls = []

    def factory():
        calls.append(1)
        if len(calls) == 2:
            assert _retire(history)["retired"] == 2
            listed.set()
        return original()

    reclaimed = outbox_retention.reclaim_empty_outbox_partitions(
        mode="always", session_factory=factory
    )
    assert listed.is_set()
    assert reclaimed == 0
    with partitioned.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass(:n)"), {"n": "management." + leaf}) is None


def test_mutation_leaves_retire_before_event_purges(history, partitioned):
    _finished(history, "job-order")
    assert _retire(history, limit=1)["retired"] == 1
    assert _leaves(partitioned, "job-order") >= {"execution_outbox"}
    assert "execution_mutations" not in _leaves(partitioned, "job-order")


def test_autogenerate_tolerates_leaves_retired_after_listing(
    history, partitioned, monkeypatch
):
    from alembic.autogenerate import compare_metadata
    from sqlalchemy import MetaData
    from sqlalchemy.engine.reflection import Inspector
    from sqlalchemy.exc import NoSuchTableError
    from ultima_scraper_db_archive.history_alembic import include_name

    listing = Inspector.get_table_names

    def retire_after_listing(self, schema=None, **kw):
        names = listing(self, schema=schema, **kw)
        if schema == "management":
            # Startup autogeneration races the reconciler's retirement cycle.
            assert _retire(history)["retired"] == 2
        return names

    monkeypatch.setattr(Inspector, "get_table_names", retire_after_listing)

    def compare(name_filter):
        with partitioned.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "include_schemas": True,
                    "include_name": lambda name, type_, parents: (
                        type_ != "schema" or name == "management"
                    )
                    and name_filter(name, type_, parents),
                },
            )
            return compare_metadata(context, MetaData())

    _finished(history, "job-autogen-unfiltered")
    with pytest.raises(NoSuchTableError):
        compare(lambda *args: True)

    _finished(history, "job-autogen-filtered")
    diffs = compare(include_name)
    assert not any(
        "_job_" in getattr(diff[1], "name", "") for diff in diffs if diff[0] == "remove_table"
    )


def test_outbox_sweep_defers_a_scan_timeout_but_raises_other_errors(
    history, monkeypatch
):
    import psycopg
    from sqlalchemy.exc import OperationalError

    def failing(error):
        def scan(*args, **kwargs):
            raise OperationalError("SELECT event_id ...", {}, error)

        return scan

    # Dead identity entries left by retirement can outlast the 5 s scan limit.
    monkeypatch.setattr(
        outbox_retention,
        "_purge_partitioned_outbox",
        failing(psycopg.errors.QueryCanceled("canceling statement due to statement timeout")),
    )
    result = outbox_retention.purge_outbox(
        cursor="event:0", mode="always", session_factory=history.session_factory
    )
    assert result.busy and result.deleted == 0 and result.next_cursor is None

    monkeypatch.setattr(
        outbox_retention,
        "_purge_partitioned_outbox",
        failing(psycopg.errors.AdminShutdown("terminating connection")),
    )
    with pytest.raises(OperationalError):
        outbox_retention.purge_outbox(
            cursor="event:0", mode="always", session_factory=history.session_factory
        )


def _directory_count(engine, run_id):
    with engine.connect() as connection:
        return connection.scalar(text(
            "SELECT count(*) FROM management.execution_outbox_identities WHERE run_id=:run"
        ), {"run": run_id})


def _defer_directory_cleanup(ledger, monkeypatch):
    with monkeypatch.context() as context:
        context.setattr(history_retirement, "_purge_event_identities", lambda *args: False)
        return _retire(ledger)


def test_consumed_leaf_is_released_before_directory_cleanup_and_resumes(
    history, partitioned, monkeypatch
):
    _finished(history, "job-release-first")
    before = _directory_count(partitioned, "job-release-first")
    assert before > 0
    assert _defer_directory_cleanup(history, monkeypatch) == {
        "retired": 2, "busy": 0, "waiting": 1
    }
    assert _leaves(partitioned, "job-release-first") == {"job_tasks", "execution_attempts"}
    assert _directory_count(partitioned, "job-release-first") == before
    # A new call discovers the committed missing leaf; it needs no in-memory
    # record from the call that released the files.
    assert _retire(history) == {"retired": 0, "busy": 0, "waiting": 0}
    assert _directory_count(partitioned, "job-release-first") == 0
    assert history.task("job-release-first", "job-release-first-task")["result"]["output"] == {"value": 7}


def test_queued_run_and_recreated_leaf_protect_deferred_directory_rows(
    history, partitioned, monkeypatch
):
    run = "job-protected-orphan"
    _finished(history, run)
    _defer_directory_cleanup(history, monkeypatch)
    before = _directory_count(partitioned, run)
    assert _retire(history, protected_run_ids={run}) == {"retired": 0, "busy": 0, "waiting": 0}
    assert _directory_count(partitioned, run) == before
    history.control(run, "update", name="A fresh undelivered event")
    recreated = _directory_count(partitioned, run)
    assert recreated > before
    _retire(history)
    assert "execution_outbox" in _leaves(partitioned, run)
    assert _directory_count(partitioned, run) == recreated
    while history.relay(publish_many=lambda payloads: None):
        pass
    assert _retire(history)["retired"] == 1
    assert _directory_count(partitioned, run) == 0


def test_directory_cursor_never_advances_past_an_uncommitted_page(
    history, partitioned, monkeypatch
):
    run = "job-orphan-rollback"
    _finished(history, run)
    _defer_directory_cleanup(history, monkeypatch)
    with partitioned.begin() as connection:
        connection.execute(text("""INSERT INTO management.execution_outbox_identities
            (event_id,run_id,sequence)
            SELECT 1000000+n,:run,1000000+n FROM generate_series(1,10001) AS n"""), {"run": run})
    before = _directory_count(partitioned, run)
    cursors = {}
    original = history_retirement.purge_identity_page
    calls = []

    def interrupted(session, *args, **kwargs):
        result = original(session, *args, **kwargs)
        calls.append((kwargs.get("after"), result[2]))
        if len(calls) == 2:
            def fail_commit():
                raise RuntimeError("simulated interruption before commit")
            session.commit = fail_commit
        return result

    with monkeypatch.context() as context:
        context.setattr(history_retirement, "purge_identity_page", interrupted)
        with pytest.raises(RuntimeError, match="interruption before commit"):
            _retire(history, identity_cursors=cursors)
    assert calls[0][0] is None and calls[1][0] == calls[0][1]
    assert cursors[run] == calls[0][1]
    assert _directory_count(partitioned, run) == before - history_retirement.IDENTITY_BATCH
    assert _retire(history, identity_cursors=cursors) == {"retired": 0, "busy": 0, "waiting": 0}
    assert not cursors and _directory_count(partitioned, run) == 0


@pytest.mark.asyncio
async def test_persisted_past_end_cursor_rewinds_and_bytes_keys_are_cleared(
    history, partitioned, monkeypatch
):
    from ultima_scraper_backend.database import receipt_retention

    run = "job-redis-cursor"
    _finished(history, run)
    _defer_directory_cleanup(history, monkeypatch)
    assert _directory_count(partitioned, run) > 0
    client = SimpleNamespace(
        hgetall=AsyncMock(return_value={run.encode(): b"9223372036854775807"}),
        hset=AsyncMock(return_value=1),
        hdel=AsyncMock(return_value=1),
    )
    monkeypatch.setattr(receipt_retention, "pending_run_ids", AsyncMock(return_value=frozenset()))
    monkeypatch.setattr(receipt_retention, "retention_mode", lambda: "idle")
    original = history_retirement.retire_finished_history

    def owned(**kwargs):
        return original(session_factory=history.session_factory, grace_seconds=0, **kwargs)

    monkeypatch.setattr(history_retirement, "retire_finished_history", owned)
    assert await history_retirement.run_history_retirement_cycle(SimpleNamespace(client=client)) == 0
    assert _directory_count(partitioned, run) == 0
    client.hdel.assert_awaited_once_with(history_retirement.CURSOR_KEY, run)


def test_orphan_lookup_seeks_owner_index_and_does_not_borrow_next_owner(
    history, partitioned, monkeypatch
):
    run = "job-owner-seek"
    _finished(history, run)
    _defer_directory_cleanup(history, monkeypatch)
    parameters = {"grace": 0, "protected": [], "limit": 64}
    with partitioned.begin() as connection:
        connection.execute(text("""INSERT INTO management.execution_outbox_identities
            (event_id,run_id,sequence)
            SELECT 2000000+n,'zzz-unrelated-owner',2000000+n
            FROM generate_series(1,20000) AS n"""))
        connection.execute(text("ANALYZE management.execution_outbox_identities"))
        plan = connection.scalar(
            text("EXPLAIN (FORMAT JSON) " + str(history_retirement._ORPHAN_CANDIDATES)),
            parameters,
        )[0]["Plan"]

        def nodes(node):
            yield node
            for child in node.get("Plans", []):
                yield from nodes(child)

        reads = [node for node in nodes(plan)
                 if node.get("Relation Name") == "execution_outbox_identities"]
        assert len(reads) == 1
        assert reads[0]["Index Name"] == "idx_execution_outbox_identities_run"
        assert "ROW" in reads[0]["Index Cond"]
        assert connection.scalars(history_retirement._ORPHAN_CANDIDATES, parameters).all() == [run]
        connection.execute(text(
            "DELETE FROM management.execution_outbox_identities WHERE run_id=:run"
        ), {"run": run})
        # The composite seek now lands on another owner's first key. It must
        # stop there without scanning the directory or selecting that owner.
        assert connection.scalars(history_retirement._ORPHAN_CANDIDATES, parameters).all() == []


def test_orphan_discovery_timeout_defers_cleanup_but_other_errors_raise(
    history, partitioned, monkeypatch
):
    import psycopg
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    run = "job-orphan-query-timeout"
    _finished(history, run)
    _defer_directory_cleanup(history, monkeypatch)
    before = _directory_count(partitioned, run)
    original = Session.scalars

    def failing(error):
        def query(session, statement, *args, **kwargs):
            if statement is history_retirement._ORPHAN_CANDIDATES:
                raise OperationalError(str(statement), {}, error)
            return original(session, statement, *args, **kwargs)
        return query

    with monkeypatch.context() as context:
        context.setattr(Session, "scalars", failing(psycopg.errors.QueryCanceled("timeout")))
        assert _retire(history) == {"retired": 0, "busy": 1, "waiting": 0}
    assert _directory_count(partitioned, run) == before
    with monkeypatch.context() as context:
        context.setattr(Session, "scalars", failing(psycopg.errors.AdminShutdown("shutdown")))
        with pytest.raises(OperationalError):
            _retire(history)
    assert _directory_count(partitioned, run) == before
