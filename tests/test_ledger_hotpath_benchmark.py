"""Opt-in concurrent checkpoint/finish comparison on disposable native SQL."""
# ruff: noqa: F811 - imported native PostgreSQL fixtures are injected by pytest.

import asyncio
import importlib.util
import json
import os
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import event
from test_execution_ledger import (  # noqa: F401
    ledger,
    ledger_engine,
    postgres_engine,
    submit,
    task,
)
from ultima_scraper_backend.job_system.ledger_runtime import ExecutionTelemetry
from ultima_scraper_backend.job_system.models import Task, TaskResult, TaskState


@pytest.mark.skipif(
    os.getenv("USR_BENCH_LEDGER_HOTPATH") != "1",
    reason="Opt-in native hot-path benchmark",
)
@pytest.mark.parametrize(
    "mode,pair", [("before", 1), ("after", 1), ("before", 2), ("after", 2)]
)
@pytest.mark.asyncio
async def test_checkpoint_finish_benchmark(ledger, ledger_engine, mode, pair):
    count, warmups = 400, 16
    ledger.limits = replace(
        ledger.limits, tasks=count + warmups, global_tasks=1000, batch=128
    )
    executor = ledger
    if mode == "before":
        path = Path("/tmp/mps-before-ledger-hotpath.py")
        if not path.exists():
            pytest.skip("Pre-change snapshot unavailable")
        name = "ultima_scraper_backend.job_system._hotpath_baseline"
        spec = importlib.util.spec_from_file_location(name, path)
        baseline = importlib.util.module_from_spec(spec)
        sys.modules[name] = baseline
        spec.loader.exec_module(baseline)
        executor = baseline.ExecutionLedger(
            ledger.session_factory, limits=ledger.limits
        )
    submit(
        ledger, [task(f"task-{i:04d}", user_id=i + 1) for i in range(count + warmups)]
    )
    for _ in range(4):
        ledger.tick()
    claims = []
    while len(claims) < count + warmups:
        batch = ledger.claim_many(
            owner="worker-bench",
            backend_id="backend-a",
            capabilities=["onlyfans"],
            count=128,
        )
        assert batch
        claims.extend(batch)
    slots = asyncio.Semaphore(200)

    async def execute(owned):
        async with slots:
            metrics = ExecutionTelemetry()
            started = time.monotonic()
            await metrics.database_call(
                executor.progress,
                owned,
                owned.task,
                persisting=True,
                renew=True,
                phase="writer_prepare",
            )
            item = Task.from_dict(owned.task)
            item.state = TaskState.COMPLETED
            item.result = TaskResult(success=True, metrics={"items_saved": 1})
            item.completed_at = item.result.completed_at
            await metrics.database_call(executor.finish, owned, item, phase="finish")
            return (time.monotonic() - started) * 1000, metrics.ledger

    await asyncio.gather(*(execute(owned) for owned in claims[:warmups]))
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        if not statement.startswith("SET LOCAL"):
            statements.append(statement)

    event.listen(ledger_engine, "after_cursor_execute", capture)
    started = time.monotonic()
    try:
        results = await asyncio.gather(*(execute(owned) for owned in claims[warmups:]))
    finally:
        elapsed = time.monotonic() - started
        event.remove(ledger_engine, "after_cursor_execute", capture)
    assert ledger.stats("job-test")["completed"] == count + warmups
    expected = 13 if mode == "before" else 4
    assert len(statements) == count * expected
    stats = {
        phase: round(sum(row[1][phase]["ms"] for row in results) / count, 3)
        for phase in results[0][1]
    }
    print(
        "LEDGER_HOTPATH",
        json.dumps(
            {
                "mode": mode,
                "pair": pair,
                "tasks": count,
                "slots": 200,
                "elapsed_s": round(elapsed, 3),
                "tasks_per_s": round(count / elapsed, 2),
                "mean_pair_ms": round(statistics.mean(row[0] for row in results), 3),
                "statements_per_task": expected,
                "timing": stats,
            }
        ),
    )
