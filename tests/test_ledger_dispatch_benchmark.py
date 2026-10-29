"""Opt-in isolated SQL dispatch benchmark; never uses a deployment database."""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import event
from test_execution_ledger import ledger, ledger_engine, submit, task  # noqa: F401
from test_mps_manifest import postgres_engine  # noqa: F401


@pytest.mark.skipif(
    os.environ.get("USR_BENCH_LEDGER_DISPATCH") != "1", reason="Opt-in SQL benchmark"
)
@pytest.mark.parametrize("mode", ["before", "single", "batch"])
def test_dispatch_benchmark(ledger, ledger_engine, mode):  # noqa: F811 - imported fixtures
    ledger.limits = replace(ledger.limits, tasks=256, global_tasks=512, batch=128)
    submit(
        ledger, [task(f"task-{index:04d}", user_id=index + 1) for index in range(256)]
    )
    ledger.tick()
    ledger.tick()
    executor = ledger
    if mode == "before":
        path = Path("/tmp/ultima-ledger-before-throughput-fix.py")
        if not path.exists():
            pytest.skip("Pre-change source snapshot is unavailable")
        name = "ultima_scraper_backend.job_system._dispatch_baseline"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        executor = module.ExecutionLedger(ledger.session_factory, limits=ledger.limits)
    queries = 0

    def executed(*args):
        nonlocal queries
        queries += 1

    event.listen(ledger_engine, "after_cursor_execute", executed)
    started = time.perf_counter()
    claimed = []
    try:
        while len(claimed) < 256:
            kwargs = {
                "owner": "worker-bench",
                "backend_id": "backend-a",
                "capabilities": ["onlyfans"],
            }
            if mode == "batch":
                rows = executor.claim_many(**kwargs, count=min(100, 256 - len(claimed)))
            else:
                owned = executor.claim(**kwargs)
                rows = [owned] if owned else []
            assert rows, "Ready work stopped being claimable"
            claimed.extend(rows)
    finally:
        event.remove(ledger_engine, "after_cursor_execute", executed)
    elapsed = time.perf_counter() - started
    assert len({owned.task_id for owned in claimed}) == 256
    assert len({owned.token for owned in claimed}) == 256
    print(
        f"DISPATCH mode={mode} tasks=256 seconds={elapsed:.3f} tasks_per_second={256 / elapsed:.1f} SQL_statements={queries}"
    )
