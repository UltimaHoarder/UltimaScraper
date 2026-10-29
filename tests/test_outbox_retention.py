from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from ultima_scraper_backend.database.outbox_retention import (
    purge_outbox,
    run_outbox_retention_cycle,
)

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def test_purge_old_delivered_events_while_execution_is_active_and_skip_locks(ledger):
    old = datetime.now(UTC) - timedelta(days=8)
    submit(ledger, [task()], identity="job-old")
    submit(ledger, [task()], identity="job-active")
    with ledger.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.execution_runs SET state='completed',completed_at=:old WHERE run_id='job-old'"
            ),
            {"old": old},
        )
        for event_id, run, delivered, age in [
            (100, "job-old", True, old),
            (101, "job-old", False, old),
            (102, "job-old", True, datetime.now(UTC)),
            (103, "job-active", True, old),
        ]:
            session.execute(
                text(
                    "INSERT INTO management.execution_outbox(event_id,run_id,payload_json,sequence,delivered,created_at) VALUES (:id,:run,'{}',:id,:delivered,:age)"
                ),
                {"id": event_id, "run": run, "delivered": delivered, "age": age},
            )
        session.commit()
    # A running job no longer pauses cleanup: old delivered events of any run
    # (including the active one) are purged; a locked row is skipped.
    with ledger.session_factory() as owner:
        owner.execute(
            text(
                "SELECT event_id FROM management.execution_outbox WHERE event_id=100 FOR UPDATE"
            )
        )
        result = purge_outbox(mode="idle", session_factory=ledger.session_factory)
        assert result.paused_reason is None and result.deleted == 1
    result = purge_outbox(mode="always", session_factory=ledger.session_factory)
    assert result.deleted == 1
    with ledger.session_factory() as session:
        # Undelivered (101) and recent (102) events stay.
        assert list(
            session.scalars(
                text(
                    "SELECT event_id FROM management.execution_outbox ORDER BY event_id"
                )
            )
        ) == [1, 2, 101, 102]


@pytest.mark.asyncio
async def test_pause_keeps_cursor_and_reports_status(monkeypatch):
    from ultima_scraper_backend.database import outbox_retention, threads

    monkeypatch.setattr(outbox_retention, "retention_mode", lambda: "paused")
    monkeypatch.setattr(
        outbox_retention, "pending_command_ids", AsyncMock(return_value=set())
    )
    client = SimpleNamespace(
        get=AsyncMock(return_value=b"(99,0)"),
        set=AsyncMock(),
        hset=AsyncMock(),
        expire=AsyncMock(),
    )
    runner = AsyncMock(side_effect=lambda fn, **kw: fn(**kw))
    monkeypatch.setattr(threads, "run_database_call", runner)
    assert await run_outbox_retention_cycle(SimpleNamespace(client=client)) == 0
    client.set.assert_not_awaited()
    assert (
        client.hset.await_args.kwargs["mapping"]["paused_reason"] == "operator_paused"
    )
