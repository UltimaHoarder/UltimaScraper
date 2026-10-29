"""The job detail API retains SQL-ledger refill evidence without legacy flags."""

import json
from types import SimpleNamespace

import fakeredis.aioredis
import pytest
import ultima_scraper_db_archive.global_db as gdb
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from test_job_system import FakeRedisManager
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import mps_state

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


@pytest.mark.asyncio
async def test_job_detail_includes_ledger_refill_and_timing_fields(
    ledger, ledger_engine, monkeypatch
):
    submit(ledger, [task()])
    ledger.tick()
    monkeypatch.setattr(gdb, "get_global_engine", lambda: ledger_engine)
    client = fakeredis.aioredis.FakeRedis()
    trace = {
        "stage": "ledger_refill",
        "timestamp_ms": 1000,
        "ready": 1,
        "inflight": 0,
        "archived_tasks": 0,
        "admitted_tasks": 1,
        "archive_ms": 4.5,
        "window_accounting_ms": 2.25,
        "refill_ms": 7.25,
        "pass_ms": 18.5,
        "controls": {"window_tasks": 4, "terminal_resident_tasks": 0},
    }
    try:
        await client.rpush(
            mps_state.REFILL_TRACE_KEY.format(job_id="job-test"), json.dumps(trace)
        )
        result = await jobs.get_job(
            "job-test",
            include_tasks=False,
            backend=SimpleNamespace(redis=FakeRedisManager(client)),
        )
        assert result.execution_engine == "ledger"
        assert len(result.mps_refill_trace) == 1
        exported = result.model_dump()["mps_refill_trace"][0]
        assert all(exported[name] == value for name, value in trace.items())
        assert result.task_stats.ready == 1
    finally:
        await client.aclose()
