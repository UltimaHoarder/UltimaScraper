"""Consolidated ownership transactions retain post-lock expiry and atomic events."""
# ruff: noqa: F811 - imported native PostgreSQL fixtures are injected by pytest.

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import pytest
from sqlalchemy import event, text
from test_execution_ledger import (  # noqa: F401
    claim,
    finish,
    ledger,
    ledger_engine,
    postgres_engine,
    submit,
    task,
)
from ultima_scraper_backend.job_system.ledger import StaleAttempt
from ultima_scraper_backend.job_system.models import Task, TaskResult, TaskState


def perform(ledger, owned, operation):
    if operation == "renew":
        return ledger.renew(owned)
    if operation == "progress":
        return ledger.progress(owned, owned.task)
    if operation == "prepare":
        return ledger.progress(owned, owned.task, persisting=True, renew=True)
    return finish(ledger, owned)


@pytest.mark.parametrize(
    # Finish: ownership read and the consolidated update. Its task event is
    # published live after commit, not inserted into the outbox.
    "operation,queries", [("renew", 1), ("progress", 1), ("prepare", 1), ("finish", 2)]
)
def test_checkpoint_and_finish_reduce_round_trips(
    ledger, ledger_engine, operation, queries
):
    submit(ledger, [task()])
    ledger.tick()
    owned = claim(ledger)
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        if not statement.startswith("SET LOCAL"):
            statements.append(statement)

    event.listen(ledger_engine, "after_cursor_execute", capture)
    try:
        perform(ledger, owned, operation)
    finally:
        event.remove(ledger_engine, "after_cursor_execute", capture)
    assert len(statements) == queries
    with ledger.session_factory() as session:
        row = session.execute(
            text("SELECT state,lease_until FROM management.execution_work")
        ).one()
        if operation == "finish":
            assert row.state == "completed" and row.lease_until is None
            assert (
                session.scalar(
                    text("SELECT count(*) FROM management.execution_resources")
                )
                == 0
            )
        else:
            assert row.state == ("persisting" if operation == "prepare" else "running")
            assert row.lease_until == session.scalar(
                text("SELECT lease_until FROM management.execution_resources")
            )


@pytest.mark.parametrize("operation", ["renew", "prepare", "finish"])
@pytest.mark.parametrize("blocked_table", ["execution_runs", "execution_work"])
def test_expiry_during_run_or_work_lock_wait_rejects_all_changes(
    ledger, operation, blocked_table
):
    submit(ledger, [task()])
    ledger.tick()
    owned = claim(ledger)
    with ledger.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.execution_work SET lease_until=clock_timestamp()+interval '250 milliseconds'"
            )
        )
        session.commit()
        before = session.execute(
            text("SELECT p.payload_json,w.lease_until FROM management.execution_work w JOIN management.execution_work_payloads p USING(run_id,task_id)")
        ).one()
        before_resource = session.scalar(
            text("SELECT lease_until FROM management.execution_resources")
        )
    entered = threading.Event()

    def operation_call():
        entered.set()
        perform(ledger, owned, operation)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with ledger.session_factory() as blocker:
            blocker.execute(
                text(f"SELECT run_id FROM management.{blocked_table} FOR UPDATE")
            )
            future = executor.submit(operation_call)
            assert entered.wait(2)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
            time.sleep(0.25)
            blocker.commit()
        with pytest.raises(StaleAttempt):
            future.result(timeout=3)
    with ledger.session_factory() as session:
        after = session.execute(
            text("SELECT w.state,p.payload_json,w.lease_until FROM management.execution_work w JOIN management.execution_work_payloads p USING(run_id,task_id)")
        ).one()
        assert after.state == "running"
        assert (after.payload_json, after.lease_until) == tuple(before)
        assert (
            session.scalar(
                text("SELECT lease_until FROM management.execution_resources")
            )
            == before_resource
        )
        assert (
            session.scalar(text("SELECT state FROM management.execution_attempts"))
            == "running"
        )
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.execution_outbox WHERE payload_json LIKE '%task_completed%'"
                )
            )
            == 0
        )


@pytest.mark.parametrize("operation", ["prepare", "finish"])
def test_cancel_waits_for_consolidated_attempt_transaction(ledger, operation):
    submit(ledger, [task()])
    ledger.tick()
    owned = claim(ledger)
    entered = threading.Event()

    def operation_call():
        entered.set()
        return perform(ledger, owned, operation)

    with ThreadPoolExecutor(max_workers=2) as executor:
        with ledger.session_factory() as blocker:
            blocker.execute(
                text("SELECT task_id FROM management.execution_work FOR UPDATE")
            )
            active = executor.submit(operation_call)
            assert entered.wait(2)
            with pytest.raises(TimeoutError):
                active.result(timeout=0.1)
            cancellation = executor.submit(ledger.control, owned.run_id, "cancel")
            with pytest.raises(TimeoutError):
                cancellation.result(timeout=0.1)
            blocker.commit()
        active.result(timeout=3)
        assert cancellation.result(timeout=3)
    stats = ledger.stats(owned.run_id)
    assert stats["completed"] == (1 if operation == "finish" else 0)


def test_failed_finish_rolls_back_resource_release_and_publishes_no_event(
    ledger, ledger_engine, live_task_events
):
    submit(ledger, [task()])
    ledger.tick()
    owned = claim(ledger)
    live_task_events.clear()

    def reject_finish(conn, cursor, statement, parameters, context, many):
        if "execution_attempts" in statement and not statement.lstrip().startswith("SELECT"):
            raise ConnectionError("Controlled finish failure")

    event.listen(ledger_engine, "before_cursor_execute", reject_finish)
    try:
        with pytest.raises(ConnectionError, match="Controlled"):
            finish(ledger, owned)
    finally:
        event.remove(ledger_engine, "before_cursor_execute", reject_finish)
    # Live task events are published only after their transaction commits.
    assert live_task_events == []
    with ledger.session_factory() as session:
        assert (
            session.scalar(text("SELECT state FROM management.execution_work"))
            == "running"
        )
        assert (
            session.scalar(text("SELECT state FROM management.execution_attempts"))
            == "running"
        )
        assert (
            session.scalar(text("SELECT token FROM management.execution_resources"))
            == owned.token
        )
    finish(ledger, owned)
    assert ledger.stats(owned.run_id)["completed"] == 1
    assert [e["event"] for e in live_task_events] == ["task_completed"]


def test_retry_keeps_exact_payload_backoff_attempt_and_event(ledger, live_task_events):
    submit(ledger, [task()])
    ledger.tick()
    owned = claim(ledger)
    item = Task.from_dict(owned.task)
    item.state = TaskState.FAILED
    item.max_attempts = 2
    item.result = TaskResult(success=False, message="Transient test failure")
    item.completed_at = item.result.completed_at
    ledger.finish(
        owned,
        item,
        retry=True,
        timings={"handler_ms": 17, "route_lookup_stats_json": '{"route-a": {}}'},
    )
    with ledger.session_factory() as session:
        work = session.execute(
            text(
                "SELECT w.state,p.payload_json,w.available_at,w.owner,w.token FROM management.execution_work w JOIN management.execution_work_payloads p USING(run_id,task_id)"
            )
        ).one()
        attempt = session.execute(
            text(
                "SELECT state,completed_at,timings_json FROM management.execution_attempts"
            )
        ).one()
        assert work.state == "queued" and work.owner is None and work.token is None
        payload = json.loads(work.payload_json)
        assert (
            payload["state"] == "pending"
            and payload["result"] is None
            and payload["completed_at"] is None
        )
        # Nested *_json maps go to Redis telemetry only, not attempt rows.
        assert attempt.state == "failed" and json.loads(attempt.timings_json) == {
            "handler_ms": 17
        }
        assert (work.available_at - attempt.completed_at).total_seconds() == 2
        assert not session.scalar(text(
            "SELECT count(*) FROM management.execution_outbox WHERE payload_json LIKE '%task_retry_scheduled%'"
        ))
        (queued,) = [e for e in live_task_events if e["event"] == "task_retry_scheduled"]
        assert queued["retry_at"] == work.available_at.isoformat()
        assert queued["error"] == "Transient test failure"
