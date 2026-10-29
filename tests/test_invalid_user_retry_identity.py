"""A retried invalid-profile check replays its committed SQL mutation."""
# ruff: noqa: F811 - imported PostgreSQL fixtures are injected by pytest.

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from test_execution_ledger import (  # noqa: F401
    claim,
    finish,
    ledger,
    ledger_engine,
    postgres_engine,
    submit,
    task,
)
from ultima_scraper_backend.database.write_queue import DatabaseWriteCommand
from ultima_scraper_backend.database.write_receipts import receipt_batch
from ultima_scraper_backend.job_system.handlers.scrape import handler
from ultima_scraper_backend.job_system.ledger_runtime import FencedWriter


@pytest.mark.asyncio
async def test_expired_invalid_check_replays_but_new_task_refreshes(ledger, monkeypatch):
    checked = datetime.now(UTC)
    check_times = iter(checked + timedelta(seconds=i) for i in range(3))

    class CheckClock:
        @staticmethod
        def now(zone):
            return next(check_times)

    monkeypatch.setattr(handler, "datetime", CheckClock)
    commands = []
    applied = []

    class SQLWriter:
        async def submit(self, operation, payload, **kwargs):
            command = DatabaseWriteCommand(
                operation=operation,
                payload=payload,
                producer_id="test",
                created_at=datetime.now(UTC).isoformat(),
                version=2,
                **kwargs,
            )
            commands.append(command)
            results = {}
            with ledger.session_factory() as session:
                with receipt_batch(session, [command], results) as pending:
                    applied.append(len(pending))
                    for item in pending:
                        session.execute(
                            text("""
                                INSERT INTO onlyfans.invalid_users
                                    (site, user_id, last_checked_at)
                                VALUES (:site, :user_id, :checked_at)
                                ON CONFLICT (site, user_id) DO UPDATE
                                    SET last_checked_at=EXCLUDED.last_checked_at
                            """),
                            {"site": item.site, "user_id": item.payload["user_id"],
                             "checked_at": datetime.fromisoformat(item.payload["checked_at"])},
                        )
                        results[item.command_id] = {"checked_at": item.payload["checked_at"]}
                session.commit()
            return results[command.command_id]

    async def check(owned):
        context = SimpleNamespace(
            site="onlyfans", context={},
            database_writes=FencedWriter(
                SQLWriter(), ledger, owned,
                SimpleNamespace(checkpoint=AsyncMock()),
            ),
        )
        await handler._mark_user_invalid(
            task=task(owned.task_id), context=context, user_id=123,
        )

    submit(ledger, [task()])
    ledger.tick()
    old = claim(ledger)
    await check(old)
    with ledger.session_factory() as session:
        session.execute(text("""
            UPDATE management.execution_work
            SET lease_until=clock_timestamp()-interval '1 second'
        """))
        session.commit()
    assert ledger.recover_expired() == 1
    replacement = claim(ledger)
    await check(replacement)
    assert replacement.token != old.token
    assert commands[0].command_id != commands[1].command_id
    assert commands[0].execution_key == commands[1].execution_key
    assert commands[0].payload["checked_at"] != commands[1].payload["checked_at"]
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT last_checked_at FROM onlyfans.invalid_users")) == checked
        assert session.scalar(text("SELECT count(*) FROM management.execution_mutations")) == 1
        assert session.scalar(text("SELECT count(*) FROM management.database_write_receipts")) == 2

    finish(ledger, replacement)
    ledger.tick()
    submit(ledger, [task("new-check")], identity="job-new-check")
    ledger.tick()
    await check(claim(ledger))
    assert applied == [1, 0, 1]
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT last_checked_at FROM onlyfans.invalid_users")) == checked + timedelta(seconds=2)
        assert session.scalar(text("SELECT count(*) FROM management.execution_mutations")) == 2
