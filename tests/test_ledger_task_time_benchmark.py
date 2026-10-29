"""Opt-in task-path comparison on an owned empty PostgreSQL cluster."""
# ruff: noqa: F811 - imported pytest fixtures are injected into test functions.

import asyncio
import importlib.util
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_execution_ledger import (  # noqa: F401
    ledger,
    ledger_engine,
    pool,
    postgres_engine,
    submit,
    task,
)
from ultima_scraper_backend.database.threads import run_owned_thread_call
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
from ultima_scraper_backend.job_system import ledger_runtime
from ultima_scraper_backend.job_system.ledger import validate_write_attempt
from ultima_scraper_backend.job_system.models import TaskRegistry, TaskResult, TaskType


@pytest.mark.skipif(
    os.getenv("USR_BENCH_LEDGER_TASK_TIME") != "1", reason="Opt-in task-path benchmark"
)
@pytest.mark.parametrize(
    "mode,pair_number", [("before", 1), ("after", 1), ("before", 2), ("after", 2)]
)
@pytest.mark.asyncio
async def test_task_path_benchmark(
    ledger, ledger_engine, mode, pair_number, monkeypatch
):
    # Keep one-time worker/guard imports outside both measured paths.
    from ultima_scraper_backend.services import archive_write_guard  # noqa: F401
    from ultima_scraper_backend.workers.worker_pool import (
        _TimedDatabaseWrites,  # noqa: F401
    )

    runtime = ledger_runtime
    if mode == "before":
        path = Path("/tmp/mps-before-task-time-ledger-runtime.py")
        if not path.exists():
            pytest.skip("Pre-change runtime snapshot unavailable")
        name = "ultima_scraper_backend.job_system._task_time_baseline"
        spec = importlib.util.spec_from_file_location(name, path)
        runtime = importlib.util.module_from_spec(spec)
        sys.modules[name] = runtime
        spec.loader.exec_module(runtime)

    count = 400
    ledger.limits = replace(
        ledger.limits, tasks=count, global_tasks=count * 2, batch=128
    )
    submit(
        ledger,
        [
            task(f"task-{i:04d}", kind=TaskType.API_COMMAND, user_id=i + 1)
            for i in range(count)
        ],
    )
    for _ in range(4):
        ledger.tick()
    claims = []
    while len(claims) < count:
        batch = ledger.claim_many(
            owner="worker-bench",
            backend_id="backend-a",
            capabilities=["onlyfans"],
            count=128,
        )
        assert batch
        claims.extend(batch)

    ledger.progress = Mock(wraps=ledger.progress)
    worker = pool()
    writer_lanes = asyncio.Semaphore(8)
    pending = {}

    async def apply(identity):
        async with writer_lanes:

            def sql():
                with ledger.session_factory() as session:
                    validate_write_attempt(session, identity)
                    session.commit()

            await run_owned_thread_call(sql)
            await asyncio.sleep(0.015)
            return {"saved": True}

    async def enqueue(operation, payload, **kwargs):
        pending[kwargs["command_id"]] = asyncio.create_task(
            apply(kwargs["execution_attempt"])
        )
        return kwargs["command_id"], {}

    async def wait_for_result(command_id, **kwargs):
        return await pending[command_id]

    from types import SimpleNamespace

    worker.database_writes = SimpleNamespace(
        enqueue=enqueue, wait_for_result=wait_for_result
    )

    async def handler(item, context):
        # Fixed upstream latency, root progress callbacks and one fenced write
        # follow the profile handler's lifecycle. No deployment or HTTP access.
        await asyncio.sleep(0.4)
        item.result = TaskResult(success=True, message="Scrape started")
        await context.storage.persist_task(job_id=item.job_id, task=item)
        await context.database_writes.submit(
            DatabaseWriteOperation.UPSERT_USER, {"user_id": item.user_id}
        )
        item.result = TaskResult(success=True, metrics={"items_saved": 1})
        for _ in range(2):
            await context.storage.persist_task(job_id=item.job_id, task=item)
        return item.result

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, handler)
    slots = asyncio.Semaphore(200)
    durations = []

    async def execute(owned):
        async with slots:
            started = time.monotonic()
            assert await runtime.execute(worker, ledger, owned) == (True, False, None)
            durations.append(time.monotonic() - started)

    started = time.monotonic()
    await asyncio.gather(*(execute(owned) for owned in claims))
    elapsed = time.monotonic() - started
    assert ledger.stats("job-test")["completed"] == count
    print(
        "TASK_PATH",
        json.dumps(
            {
                "mode": mode,
                "pair": pair_number,
                "tasks": count,
                "slots": 200,
                "elapsed_s": round(elapsed, 3),
                "tasks_per_s": round(count / elapsed, 2),
                "mean_task_s": round(sum(durations) / count, 3),
                "progress_calls": ledger.progress.call_count,
            }
        ),
    )
