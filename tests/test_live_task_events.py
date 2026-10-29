"""Per-task events are live-only; job-level events and progress stay durable."""

import json

from sqlalchemy import create_engine, insert, text
from sqlalchemy.orm import Session
from test_execution_ledger import claim, finish, ledger, ledger_engine, postgres_engine, submit, task
from ultima_scraper_backend.job_system import live_events
from ultima_scraper_backend.job_system.ledger import LEGACY_TASK_EVENT_PREFIX
from ultima_scraper_db_archive.execution_models import ExecutionOutboxModel

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def test_events_publish_only_after_their_transaction_commits(live_task_events):
    with Session(create_engine("sqlite://")) as session:
        session.execute(text("SELECT 1"))
        live_events.defer(session, {"event": "task_started"})
        session.rollback()
        assert live_task_events == []
        session.execute(text("SELECT 1"))
        live_events.defer(session, {"event": "task_completed"})
        assert live_task_events == []
        session.commit()
        assert live_task_events == [{"event": "task_completed"}]
        session.commit()  # A later empty transaction republishes nothing.
        assert live_task_events == [{"event": "task_completed"}]


def test_a_failing_publisher_never_fails_the_committed_write():
    def broken(_payloads):
        raise ConnectionError("redis down")

    live_events.set_publisher(broken)
    try:
        with Session(create_engine("sqlite://")) as session:
            session.execute(text("SELECT 1"))
            live_events.defer(session, {"event": "task_completed"})
            session.commit()
    finally:
        live_events.set_publisher(None)


def test_task_lifecycle_is_live_while_job_events_stay_in_the_outbox(ledger, live_task_events):
    submit(ledger, [task()])
    ledger.tick()
    owned = claim(ledger)
    finish(ledger, owned)
    assert [e["event"] for e in live_task_events] == ["task_started", "task_completed"]
    assert {e["job_id"] for e in live_task_events} == {"job-test"}
    assert live_task_events[0]["type"] == "job_event"  # WebSocket routing and wake hints.
    with ledger.session_factory() as session:
        stored = [json.loads(p)["event"] for p in session.scalars(text(
            "SELECT payload_json FROM management.execution_outbox ORDER BY event_id"))]
    assert stored and not [name for name in stored if name.startswith("task_")]
    assert "job_created" in stored


def test_relay_skips_a_legacy_task_backlog_without_delaying_job_events(ledger, monkeypatch):
    from ultima_scraper_backend.job_system import ledger as ledger_module

    submit(ledger, [task()])
    ledger.relay(publish_many=lambda _payloads: None)  # Deliver submission events.
    legacy = [LEGACY_TASK_EVENT_PREFIX + f'started","job_id":"job-test","n":{n}}}' for n in range(5)]
    with ledger.session_factory() as session:
        for payload in legacy[:3]:
            session.execute(insert(ExecutionOutboxModel), {"run_id": "job-test", "payload_json": payload})
        session.execute(insert(ExecutionOutboxModel), {
            "run_id": "job-test", "payload_json": json.dumps({"type": "job_event", "event": "job_paused"})})
        for payload in legacy[3:]:
            session.execute(insert(ExecutionOutboxModel), {"run_id": "job-test", "payload_json": payload})
        session.commit()
    monkeypatch.setattr(ledger_module, "LEGACY_SKIP_BATCH", 2)
    published, outcome, passes = [], [], 0
    ledger.relay(publish_many=published.extend, outcome=outcome)
    # A full legacy page passes no job event yet, so nothing is published.
    assert published == [] and outcome == ["backlog"]
    while outcome != ["idle"]:
        ledger.relay(publish_many=published.extend, outcome=outcome)
        passes += 1
        assert passes < 10
    # The job event follows its skipped neighbours; no legacy row is published.
    assert [p["event"] for p in published] == ["job_paused"]
    with ledger.session_factory() as session:
        rows = session.execute(text("""SELECT delivered, sequence FROM management.execution_outbox
            WHERE starts_with(payload_json, :prefix)"""), {"prefix": LEGACY_TASK_EVENT_PREFIX}).all()
    assert len(rows) == 5 and all(row.delivered and row.sequence is None for row in rows)
    # Skipped rows never reach replaying consumers.
    assert [e["event"] for e in ledger.events(after=0, limit=500)].count("job_paused") == 1
    assert not [e for e in ledger.events(after=0, limit=500) if e["event"].startswith("task_")]


def test_progress_summaries_are_durable_and_skip_unchanged_runs(ledger):
    submit(ledger, [task("task-a"), task("task-b")])
    ledger.tick()
    with ledger.session_factory() as session:
        session.execute(text("UPDATE management.execution_runs SET state='running' WHERE run_id='job-test'"))
        session.commit()

    def progress_events():
        with ledger.session_factory() as session:
            return [json.loads(p) for p in session.scalars(text(
                "SELECT payload_json FROM management.execution_outbox ORDER BY event_id"))
                if json.loads(p)["event"] == "job_progress"]

    counts = ledger.record_progress()
    assert len(progress_events()) == 1
    assert ledger.record_progress(previous=counts) == counts
    assert len(progress_events()) == 1  # Unchanged counts add nothing.
    finish(ledger, claim(ledger))
    ledger.record_progress(previous=counts)
    latest = progress_events()[-1]
    assert latest["completed_tasks"] == 1 and latest["total_tasks"] == 2
    # Remote job adapters read it from the plugin feed as a progress update.
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    normalized = PluginPlatform._normalize_local_job_event(None, latest)
    assert normalized["lifecycle_event"] == "progress"
