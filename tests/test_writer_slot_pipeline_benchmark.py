"""Paired full writer/control pipeline on disposable PostgreSQL and Redis."""

import asyncio
import importlib.util
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from statistics import mean, median
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlmodel import Session
from test_content_write_resources import content_engine, postgres_engine
from test_database_write_queue import redis_manager
from test_execution_ledger import submit, task
from ultima_scraper_backend.database import write_queue
from ultima_scraper_backend.database.threads import run_owned_thread_call
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.job_system.ledger import ExecutionLedger, Limits
from ultima_scraper_backend.job_system.ledger_runtime import (
    FencedWriter,
    LedgerTaskStorage,
)
from ultima_scraper_backend.job_system.models import (
    Task,
    TaskResult,
    TaskState,
    TaskType,
)
from ultima_scraper_backend.workers.worker_pool import _TimedDatabaseWrites
from ultima_scraper_db_archive import global_db
from ultima_scraper_db_archive.execution_models import EXECUTION_MODELS

__all__ = ["content_engine", "postgres_engine", "redis_manager"]


@pytest.mark.skipif(
    os.environ.get("USR_BENCH_WRITER_SLOT_PIPELINE") != "1",
    reason="opt-in native queue/profile/checkpoint pipeline benchmark",
)
@pytest.mark.parametrize("order", ["before_after", "after_before"])
async def test_writer_slot_pipeline(
    content_engine, redis_manager, monkeypatch, tmp_path, order
):
    if type(redis_manager.client).__module__.startswith("fakeredis"):
        pytest.skip("pipeline timing uses the owned native Redis fixture")
    source = os.environ.get("USR_WRITER_SLOT_BASELINE_SOURCE")
    if not source or not Path(source).is_file():
        pytest.skip("pre-change writer source snapshot required")
    name = "ultima_scraper_backend.database._slot_pipeline_baseline"
    spec = importlib.util.spec_from_file_location(name, source)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[name] = baseline
    spec.loader.exec_module(baseline)
    monkeypatch.delenv("ULTIMA_JOB_ENGINE", raising=False)
    with content_engine.begin() as connection:
        for model in EXECUTION_MODELS:
            model.__table__.create(connection, checkfirst=True)
        connection.execute(
            text(
                "INSERT INTO management.execution_feed(feed_id,next_sequence) VALUES(1,1) ON CONFLICT DO NOTHING"
            )
        )
    engine_options = {
        "connect_args": {
            "options": "-c search_path=onlyfans,management,public -c statement_timeout=15000"
        },
        "max_overflow": 0,
    }
    writer_engine = create_engine(content_engine.url, pool_size=8, **engine_options)
    control_engines = [
        create_engine(content_engine.url, pool_size=3, **engine_options)
        for _ in range(7)
    ]

    def sessions(engine):
        @contextmanager
        def factory():
            with Session(engine) as session:
                yield session

        return factory

    monkeypatch.setattr(global_db, "global_session", sessions(control_engines[0]))
    ledgers = [
        ExecutionLedger(
            sessions(engine),
            limits=Limits(
                tasks=10000, global_tasks=10000, batch=128, lease_seconds=600
            ),
        )
        for engine in control_engines
    ]
    count = 2800
    observations = {}

    class Executor(PostgreSQLWriteExecutor):
        def __init__(self):
            self._site_manager = lambda site: SimpleNamespace(
                get_session=sessions(writer_engine)
            )
            self.batches = []

        async def execute_batch(self, commands):
            self.batches.append(len(commands))
            if commands[0].operation == write_queue.DatabaseWriteOperation.UPSERT_USER:
                return await run_owned_thread_call(
                    self._run_async_batch, self._upsert_users, commands, "onlyfans"
                )
            return await run_owned_thread_call(
                self._upsert_invalid_users, commands, "onlyfans"
            )

        async def close(self):
            pass

    try:
        for label in order.split("_"):
            with content_engine.begin() as connection:
                connection.execute(
                    text(
                        "TRUNCATE management.execution_mutations,management.execution_outbox,management.execution_resources,management.execution_attempts,management.execution_work,management.execution_runs,management.execution_definitions,management.mps_plans,management.mps_task_definitions,management.database_write_receipts,management.jobs,management.job_tasks,management.migration_source_identities,onlyfans.users,onlyfans.invalid_users CASCADE"
                    )
                )
            await redis_manager.client.flushdb()
            ledger = ledgers[0]
            submit(
                ledger,
                [
                    task(f"task-{i:05d}", kind=TaskType.API_COMMAND, user_id=i + 1000)
                    for i in range(count)
                ],
            )
            for _ in range((count + 127) // 128):
                ledger.tick()
            claims = []
            while len(claims) < count:
                index = (len(claims) // 128) % 7
                page = ledgers[index].claim_many(
                    owner=f"worker-{index}",
                    backend_id="backend-a",
                    capabilities=["onlyfans"],
                    count=128,
                )
                assert page
                claims.extend((index, owned) for owned in page)
            service_type = (
                baseline.DatabaseWriterService
                if label == "before"
                else write_queue.DatabaseWriterService
            )
            executor = Executor()
            service = service_type(
                redis_manager, executor, batch_size=100, concurrency=8, block_ms=5
            )
            client = write_queue.DatabaseWriteClient(
                redis_manager,
                max_queue_commands=800,
                max_queue_bytes=512 * 1024 * 1024,
                timeout_seconds=120,
            )
            slots = [asyncio.Semaphore(207) for _ in range(7)]
            durations, queue = [], []
            driver_calls = 0

            def sql_call(*args):
                nonlocal driver_calls
                driver_calls += 1

            for engine in [writer_engine, *control_engines]:
                event.listen(engine, "after_cursor_execute", sql_call)
            writer = asyncio.create_task(service.run())

            async def execute(
                index,
                owned,
                slots=slots,
                client=client,
                queue=queue,
                durations=durations,
            ):
                async with slots[index]:
                    started = time.monotonic()
                    item = Task.from_dict(owned.task)
                    storage = LedgerTaskStorage(
                        ledgers[index], owned, item, redis_manager
                    )
                    fenced = FencedWriter(client, ledgers[index], owned, storage)
                    # Fixed deterministic upstream staggering; no HTTP or live profiles.
                    await asyncio.sleep(0.7 + (item.user_id % 100) / 200)
                    if item.user_id % 100 < 17:
                        operation = (
                            write_queue.DatabaseWriteOperation.UPSERT_INVALID_USER
                        )
                        payload = {"user_id": item.user_id, "reason": "not_found"}
                    else:
                        operation = write_queue.DatabaseWriteOperation.UPSERT_USER
                        payload = {
                            "user": {
                                "id": item.user_id,
                                "username": f"fixture-{item.user_id}",
                                "name": "Fixture profile",
                                "about": "Fixture biography",
                                "avatar": f"https://fixture.invalid/{item.user_id}.jpg",
                                "website": "https://fixture.invalid/",
                                "postsCount": 10,
                                "is_performer": True,
                            }
                        }
                    timed = _TimedDatabaseWrites(fenced)
                    await timed.submit(operation, payload, site="onlyfans")
                    queue.append(timed.queue_ms)
                    item.state = TaskState.COMPLETED
                    item.result = TaskResult(success=True)
                    item.completed_at = item.result.completed_at
                    await run_owned_thread_call(ledgers[index].finish, owned, item)
                    durations.append(time.monotonic() - started)

            started = time.monotonic()
            try:
                async with asyncio.timeout(120):
                    if os.environ.get("USR_BENCH_WRITER_SLOT_PROCESSES") == "1":
                        processes = []
                        paths = []
                        go = tmp_path / f"{label}-go"
                        try:
                            for index in range(7):
                                config_path = tmp_path / f"{label}-{index}.json"
                                ready = tmp_path / f"{label}-{index}.ready"
                                result = tmp_path / f"{label}-{index}.result.json"
                                config_path.write_text(
                                    json.dumps(
                                        {
                                            "sql_url": content_engine.url.render_as_string(
                                                hide_password=False
                                            ),
                                            "redis_socket": redis_manager.client.connection_pool.connection_kwargs[
                                                "path"
                                            ],
                                            "claims": [
                                                asdict(owned)
                                                for worker, owned in claims
                                                if worker == index
                                            ],
                                            "go": str(go),
                                            "ready": str(ready),
                                            "result": str(result),
                                        }
                                    )
                                )
                                process = await asyncio.create_subprocess_exec(
                                    sys.executable,
                                    str(
                                        Path(__file__).with_name(
                                            "writer_pipeline_worker.py"
                                        )
                                    ),
                                    str(config_path),
                                    stdout=asyncio.subprocess.PIPE,
                                    stderr=asyncio.subprocess.PIPE,
                                )
                                processes.append(process)
                                paths.append((ready, result))
                            while not all(ready.is_file() for ready, _ in paths):
                                if any(
                                    process.returncode is not None
                                    for process in processes
                                ):
                                    raise AssertionError(
                                        [
                                            await process.communicate()
                                            for process in processes
                                        ]
                                    )
                                await asyncio.sleep(0.02)
                            started = time.monotonic()
                            go.touch()
                            outputs = await asyncio.gather(
                                *(process.communicate() for process in processes)
                            )
                            assert all(
                                process.returncode == 0 for process in processes
                            ), outputs
                            for _, path in paths:
                                values = json.loads(path.read_text())
                                durations.extend(values["durations"])
                                queue.extend(values["queue"])
                                driver_calls += values["driver_calls"]
                        finally:
                            for process in processes:
                                if process.returncode is None:
                                    process.terminate()
                            await asyncio.gather(
                                *(process.wait() for process in processes)
                            )
                    else:
                        async with asyncio.TaskGroup() as group:
                            for index, owned in claims:
                                group.create_task(execute(index, owned))
                elapsed = time.monotonic() - started
                async with asyncio.timeout(5):
                    while await redis_manager.client.xlen(client.STREAM_KEY):
                        await asyncio.sleep(0.005)
            finally:
                service.stop()
                await asyncio.wait_for(writer, timeout=10)
                for engine in [writer_engine, *control_engines]:
                    event.remove(engine, "after_cursor_execute", sql_call)
            assert ledger.stats("job-test")["completed"] == count
            with content_engine.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM management.database_write_receipts")
                    ).scalar_one()
                    == count
                )
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM management.execution_mutations")
                    ).scalar_one()
                    == count
                )
                assert (
                    connection.execute(
                        text(
                            "SELECT (SELECT count(*) FROM onlyfans.users)+(SELECT count(*) FROM onlyfans.invalid_users)"
                        )
                    ).scalar_one()
                    == count
                )
            assert not service._identity_tails and not service._open_lane_batches
            observations[label] = {
                "seconds": elapsed,
                "tasks_per_s": count / elapsed,
                "mean_task_seconds": mean(durations),
                "transactions": len(executor.batches),
                "true_mean_batch": mean(executor.batches),
                "median_batch": median(executor.batches),
                "max_batch": max(executor.batches),
                "SQL_driver_calls": driver_calls,
                "mean_writer_queue_ms": mean(queue),
            }
        print(
            "SLOT_PIPELINE",
            json.dumps(
                {
                    "order": order,
                    "tasks": count,
                    "worker_slots": 1449,
                    "writer_lanes": 8,
                    "writer_window": 800,
                    "worker_processes": 7
                    if os.environ.get("USR_BENCH_WRITER_SLOT_PROCESSES") == "1"
                    else 1,
                    "observations": observations,
                    "scope": "native Redis admission/cache/ACK, fenced profile/invalid writes and SQL prepare/finish; synthetic upstream, private fresh PostgreSQL with bounded client pools, without production PgBouncer/history",
                }
            ),
        )
    finally:
        for engine in [writer_engine, *control_engines]:
            engine.dispose()
