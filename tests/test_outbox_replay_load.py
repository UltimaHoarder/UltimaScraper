"""Event replay stays cheap for far-behind clients; empty finished partitions are reclaimed."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

LEAF = "execution_outbox_job_" + "a" * 32
BUSY = "execution_outbox_job_" + "b" * 32
FULL = "execution_outbox_job_" + "c" * 32


@pytest.mark.asyncio
async def test_far_behind_replay_jumps_to_head_without_scanning(monkeypatch):
    import ultima_scraper_backend.job_system.ledger as ledger_module
    from ultima_scraper_backend.api.routes import jobs

    scanned = []
    ledger = SimpleNamespace(event_head=lambda: 90_000, events=lambda **kw: scanned.append(kw) or [])
    monkeypatch.setattr(ledger_module, "ExecutionLedger", lambda: ledger)

    page = await jobs.execution_events(after=90_000 - jobs.EXECUTION_REPLAY_MAX_LAG - 1, limit=100)

    assert page == {"enabled": True, "events": [], "next_cursor": 90_000, "has_more": False, "resync": True}
    assert scanned == []


@pytest.mark.asyncio
async def test_nearby_replay_still_pages_events(monkeypatch):
    import ultima_scraper_backend.job_system.ledger as ledger_module
    from ultima_scraper_backend.api.routes import jobs

    events = [{"sequence": 89_999}, {"sequence": 90_000}]
    ledger = SimpleNamespace(event_head=lambda: 90_000, events=lambda **kw: events)
    monkeypatch.setattr(ledger_module, "ExecutionLedger", lambda: ledger)

    page = await jobs.execution_events(after=89_998, limit=100)

    assert page["events"] == events and "resync" not in page


class FakeSession:
    def __init__(self, state):
        self.state = state
        self.leaf = None

    def scalar(self, statement):
        sql = str(statement)
        if "relkind='p'" in sql:
            return True
        if "pg_try_advisory_xact_lock" in sql:
            return True
        if "to_regprocedure" in sql:
            return False  # Schema before migration b7c41e9a2d58: plain TRUNCATE.
        if "NOT EXISTS(SELECT 1 FROM management." in sql:
            return self.leaf not in self.state["rows"]
        raise AssertionError(sql)

    def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM pg_inherits" in sql:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.state["leaves"]))
        if sql.startswith("LOCK TABLE"):
            self.leaf = sql.split("management.")[1].split()[0]
            if self.leaf in self.state["busy"]:
                raise OperationalError(sql, {}, Exception("lock timeout"))
        if sql.startswith("TRUNCATE"):
            self.state["truncated"].append(sql.split("management.")[1])
        return SimpleNamespace()

    def commit(self):
        pass

    def rollback(self):
        pass


def factory(state):
    @contextmanager
    def session():
        yield FakeSession(state)
    return session


def test_reclaims_only_empty_lockable_partitions():
    from ultima_scraper_backend.database.outbox_retention import reclaim_empty_outbox_partitions

    state = {"leaves": [LEAF, BUSY, FULL, "not_a_job_partition"], "busy": {BUSY}, "rows": {FULL}, "truncated": []}
    assert reclaim_empty_outbox_partitions(mode="always", session_factory=factory(state)) == 1
    assert state["truncated"] == [LEAF]


def test_paused_retention_reclaims_nothing():
    from ultima_scraper_backend.database.outbox_retention import reclaim_empty_outbox_partitions

    state = {"leaves": [LEAF], "busy": set(), "rows": set(), "truncated": []}
    assert reclaim_empty_outbox_partitions(mode="paused", session_factory=factory(state)) == 0
    assert state["truncated"] == []


class ScalarSession:
    def __init__(self, values):
        self.values = values

    def scalar(self, statement, params=None):
        sql = str(statement)
        for needle, value in self.values.items():
            if needle in sql:
                return value
        raise AssertionError(sql)


def test_plugin_floor_is_the_slowest_enabled_reader():
    from ultima_scraper_backend.database.outbox_retention import _plugin_event_floor

    assert _plugin_event_floor(ScalarSession({"to_regclass": False})) is None
    assert _plugin_event_floor(ScalarSession({"to_regclass": True, "min(c.sequence)": 167_517_162})) == 167_517_162


def test_retention_hours_come_from_settings(monkeypatch):
    from ultima_scraper_backend.database import outbox_retention
    from ultima_scraper_backend.job_system import resources

    from contextlib import nullcontext

    session = SimpleNamespace(begin_nested=nullcontext)
    monkeypatch.setattr(resources, "_persisted_job_execution_setting", lambda name, db_session=None: 24)
    assert outbox_retention._retention_hours(session) == 24
    monkeypatch.setattr(resources, "_persisted_job_execution_setting", lambda name, db_session=None: None)
    assert outbox_retention._retention_hours(session) == outbox_retention.DEFAULT_RETENTION_HOURS


def test_active_execution_shrinks_the_batch_instead_of_pausing(monkeypatch):
    from contextlib import contextmanager

    from ultima_scraper_backend.database import outbox_retention

    captured = {}

    def partitioned(session, after, cutoff, *, floor=None, batch=None):
        captured.update(after=after, floor=floor, batch=batch)
        return outbox_retention.ReceiptPurgeResult(0, 0, finished=True)

    monkeypatch.setattr(outbox_retention, "_purge_partitioned_outbox", partitioned)
    monkeypatch.setattr(outbox_retention, "_retention_hours", lambda session: 168)
    monkeypatch.setattr(outbox_retention, "_plugin_event_floor", lambda session: 42)

    class Session(ScalarSession):
        def execute(self, statement, params=None):
            return None

    @contextmanager
    def factory():
        yield Session({"pg_try_advisory_xact_lock": True, "EXISTS(": True, "relkind='p'": True,
                       "execution_outbox_identities": True})

    result = outbox_retention.purge_outbox(cursor="event:7", mode="idle", session_factory=factory)
    assert result.paused_reason is None
    assert captured == {"after": 7, "floor": 42, "batch": outbox_retention.EXECUTING_BATCH}
