"""Receipt phase observations preserve SQL shape and distinguish missing coverage."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from test_database_write_queue import redis_manager
from test_execution_ledger import ledger, ledger_engine, postgres_engine
from test_ledger_writer_batch_fences import command, owned_batch
from ultima_scraper_backend.database.write_queue import WRITE_TIMING_KEY
from ultima_scraper_backend.database.write_receipts import receipt_batch
from ultima_scraper_backend.job_system.storage import JobStorage
from ultima_scraper_backend.workers.worker_pool import _TimedDatabaseWrites

__all__ = ["ledger", "ledger_engine", "postgres_engine", "redis_manager"]


def test_phase_measurement_adds_no_sql_statements(ledger, ledger_engine):
    commands = [command(claim) for claim in owned_batch(ledger, 4)]
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(ledger_engine, "before_cursor_execute", capture)
    phases = {}
    try:
        shapes = []
        for offset in (0, 2):
            statements.clear()
            with ledger.session_factory() as session:
                results = {}
                with receipt_batch(
                    session,
                    commands[offset : offset + 2],
                    results,
                    timing=phases if offset else None,
                ) as pending:
                    for item in pending:
                        results[item.command_id] = {"saved": True}
                session.commit()
            shapes.append(list(statements))
        assert shapes[0] == shapes[1]
        assert set(phases) == {"receipt_lock_ms", "receipt_read_ms", "write_fence_ms"}
        assert all(value >= 0 for value in phases.values())
    finally:
        event.remove(ledger_engine, "before_cursor_execute", capture)


@pytest.mark.asyncio
async def test_legacy_timings_do_not_dilute_receipt_phase_means(redis_manager):
    storage = JobStorage(redis_manager)
    for measured in (False, True):
        timing = {
            "writer_operation": "upsert_user",
            "writer_lane_domain": "user",
            "writer_total_ms": 10,
        }
        if measured:
            timing.update(
                receipt_phases_measured=True,
                receipt_lock_ms=2,
                receipt_read_ms=3,
                write_fence_ms=4,
            )
        timed = _TimedDatabaseWrites(
            SimpleNamespace(
                enqueue=AsyncMock(return_value=("command", {})),
                wait_for_result=AsyncMock(
                    return_value={"synced": True, WRITE_TIMING_KEY: timing}
                ),
            )
        )
        assert await timed.submit("upsert_user", {}) == {"synced": True}
        kwargs = timed.profile_telemetry_kwargs()
        await storage.record_task_runtime_telemetry(
            "receipt-phases", started_ms=1000, finished_ms=1010,
            queue_wait_ms=0, setup_ms=0, handler_ms=0, writer_ms=10, post_ms=0,
            release_ms=0, route_active_ms=0, route_attempts=0, success=True, **kwargs
        )
        raw = json.loads(kwargs["writer_operation_stats_json"])["upsert_user"]
        assert ("receipt_phases_count" in raw) == measured
    telemetry = await storage.get_job_runtime_telemetry("receipt-phases")
    stats = telemetry["writer_operation_stats"]["upsert_user"]
    assert stats["count"] == 2 and stats["receipt_phases_count"] == 1
    assert stats["mean_receipt_lock_ms"] == 2
    assert stats["mean_receipt_read_ms"] == 3
    assert stats["mean_write_fence_ms"] == 4
