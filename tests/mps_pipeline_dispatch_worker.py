"""Owned benchmark dispatcher; endpoints are supplied by disposable fixtures."""

import asyncio
import importlib.util
import json
import sys
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from redis.asyncio import Redis
from sqlalchemy import create_engine, event
from sqlmodel import Session
from ultima_scraper_backend.database.threads import run_database_call
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteClient,
    DatabaseWriteOperation,
)
from ultima_scraper_backend.job_system.ledger import ExecutionLedger, Limits
from ultima_scraper_backend.job_system.ledger_batches import completion_request
from ultima_scraper_backend.job_system.ledger_runtime import (
    ExecutionTelemetry,
    FencedWriter,
    LedgerTaskStorage,
    wait_for_worker_capacity,
    worker_claim_capacity,
)
from ultima_scraper_backend.job_system.lifecycle_batcher import LifecycleBatcher
from ultima_scraper_backend.job_system.models import Task, TaskResult, TaskState
from ultima_scraper_backend.workers.worker_pool import _TimedDatabaseWrites
from ultima_scraper_db_archive import global_db


async def main(path):
    config = json.loads(Path(path).read_text())
    capacity = config.get("capacity", False)
    native_worker_loop = config.get("native_worker_loop", False)
    fetch_slots = config.get("fetch_slots", 207)
    claim_batch = config.get("claim_batch", 128)
    after = config["label"] == "after"
    engine = create_engine(
        config["sql_url"],
        pool_size=3,
        max_overflow=0,
        connect_args={
            "options": "-c search_path=onlyfans,management,public -c statement_timeout=15000"
        },
    )

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    global_db.global_session = sessions
    ledger_type, limits_type = ExecutionLedger, Limits
    if not after or config.get("ledger_baseline"):
        name = "ultima_scraper_backend.job_system._dispatch_baseline"
        spec = importlib.util.spec_from_file_location(
            name, config.get("ledger_baseline") or config["baseline"]
        )
        baseline = importlib.util.module_from_spec(spec)
        sys.modules[name] = baseline
        spec.loader.exec_module(baseline)
        ledger_type, limits_type = baseline.ExecutionLedger, baseline.Limits
    ledger = ledger_type(
        sessions,
        limits=limits_type(
            tasks=config["window"],
            global_tasks=config["window"],
            batch=claim_batch,
            planner_batch=512,
            lease_seconds=600,
        ),
    )
    redis = SimpleNamespace(
        client=Redis(unix_socket_path=config["redis_socket"]), is_connected=True
    )

    def load_snapshot(path, name):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    client_type = DatabaseWriteClient
    if config.get("transport_baseline"):
        client_type = load_snapshot(
            config["transport_baseline"],
            "ultima_scraper_backend.database._result_baseline",
        ).DatabaseWriteClient
    client = client_type(
        redis,
        max_queue_commands=800,
        max_queue_bytes=64 * 1024 * 1024,
        timeout_seconds=120,
    )
    batcher_type = LifecycleBatcher
    if config.get("phase_baseline"):
        batcher_type = load_snapshot(
            config["phase_baseline"],
            "ultima_scraper_backend.job_system._phase_baseline",
        ).LifecycleBatcher
    batcher = batcher_type(ledger) if after else None
    pool = SimpleNamespace(_ledger_persisting_tasks=set())
    active, buffered = set(), deque()
    stage_changed = asyncio.Event()
    finished, durations = [], []
    lifecycle_sums, writer_sums = {}, {}
    samples = []
    # Keep detailed per-task observations off the worker heap in long runs.
    # The coordinator reads them only after execution has completed.
    phase_path = Path(config["result"]).with_suffix(".phases.jsonl")
    phase_file = phase_path.open("w", buffering=1024 * 1024) if capacity else None
    runtime_samples, finish_batches, claim_spans, status_spans = [], [], [], []
    claim_details = []
    claim_context = threading.local()
    pool_events = []
    checked_out = 0
    transactions = calls = 0

    def checkout(*args):
        nonlocal checked_out
        checked_out += 1
        pool_events.append((time.monotonic(), checked_out))

    def checkin(*args):
        nonlocal checked_out
        checked_out -= 1
        pool_events.append((time.monotonic(), checked_out))

    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    original_finish = ledger.finish_batch

    def finish_batch(requests):
        started = time.monotonic()
        result = original_finish(requests)
        finish_batches.append((started, time.monotonic(), len(requests)))
        return result

    if capacity:
        ledger.finish_batch = finish_batch

    async def sample_runtime():
        import psutil

        process = psutil.Process()
        previous = time.monotonic()
        while True:
            now = time.monotonic()
            runtime_samples.append(
                {
                    "at": now,
                    "active": sum(not t.done() for t in active),
                    "buffered": len(buffered),
                    "persisting": len(pool._ledger_persisting_tasks),
                    "loop_lag_ms": max(0, now - previous - 0.05) * 1000,
                    "rss_kib": process.memory_info().rss / 1024,
                    "cpu_seconds": sum(process.cpu_times()[:2]),
                }
            )
            previous = now
            await asyncio.sleep(0.05)

    def committed(*args):
        nonlocal transactions
        transactions += 1

    def executed(*args):
        nonlocal calls
        calls += 1

    def query_started(conn, cursor, statement, parameters, context, executemany):
        detail = getattr(claim_context, "detail", None)
        if detail is None:
            return
        operation = statement.lstrip().split(None, 1)[0].lower()
        table = next(
            (name for name in (
                "execution_work", "execution_resources", "execution_runs",
                "execution_attempts", "execution_outbox", "mps_plans", "jobs",
            ) if f"management.{name}" in statement),
            "other",
        )
        if operation == "select" and "management.execution_runs" in statement:
            table = "run_lock" if "FOR " in statement else "run_discovery"
        elif operation == "select" and "FOR UPDATE" in statement:
            table = "work_candidates"
        context.claim_station_started = time.monotonic()
        context.claim_station = f"{operation}:{table}"
        if (operation == "select" and table == "work_candidates"
                and "FOR UPDATE" in statement and config["index"] == 0
                and len(claim_details) in (10, 50)):
            # Explain the same owned-fixture query without executing it or
            # acquiring extra work locks. Never retain SQL parameters.
            began = time.monotonic()
            with cursor.connection.cursor() as probe:
                probe.execute("EXPLAIN (FORMAT JSON) " + statement, parameters)
                detail["candidate_plan"] = probe.fetchone()[0]
            detail["explain_seconds"] = time.monotonic() - began
            context.claim_station_started = time.monotonic()

    def query_finished(conn, cursor, statement, parameters, context, executemany):
        detail = getattr(claim_context, "detail", None)
        if detail is None or not hasattr(context, "claim_station_started"):
            return
        station = detail["queries"].setdefault(
            context.claim_station, {"calls": 0, "seconds": 0.0}
        )
        station["calls"] += 1
        station["seconds"] += time.monotonic() - context.claim_station_started

    event.listen(engine, "commit", committed)
    event.listen(engine, "after_cursor_execute", executed)
    if capacity:
        event.listen(engine, "before_cursor_execute", query_started)
        event.listen(engine, "after_cursor_execute", query_finished)

    async def execute(owned):
        if native_worker_loop:
            active.add(asyncio.current_task())
        started = time.monotonic()
        item = Task.from_dict(owned.task)
        metrics = ExecutionTelemetry()
        storage = LedgerTaskStorage(
            ledger, owned, item, redis, metrics=metrics, batcher=batcher
        )
        fenced = FencedWriter(client, ledger, owned, storage)
        timed = _TimedDatabaseWrites(fenced)
        handler_started = time.monotonic()
        if capacity:
            # Deterministic delay distribution with 1.724 s mean, matching the
            # report's exclusive handler mean. This is NOT a network simulation.
            bucket = item.user_id % 100
            await asyncio.sleep(
                0.8
                if bucket < 70
                else 2.2
                if bucket < 90
                else 6
                if bucket < 99
                else 18.4
            )
        else:
            await asyncio.sleep(0.65 + (item.user_id % 100) / 800)
        handler_ms = (time.monotonic() - handler_started) * 1000.0
        if after:
            pool._ledger_persisting_tasks.add(owned.task_id)
            stage_changed.set()
        try:
            invalid = (
                item.user_id % 10000 >= 158 if capacity else item.user_id % 100 < 17
            )
            if invalid:
                operation = DatabaseWriteOperation.UPSERT_INVALID_USER
                payload = {"user_id": item.user_id, "reason": "not_found"}
            else:
                operation = DatabaseWriteOperation.UPSERT_USER
                payload = {
                    "user": {
                        "id": item.user_id,
                        "username": f"fixture-{item.user_id}",
                        "name": "Fixture",
                        "about": "Fixture biography",
                        "avatar": f"https://fixture.invalid/{item.user_id}.jpg",
                        "website": "https://fixture.invalid/",
                        "postsCount": 10,
                        "is_performer": True,
                    }
                }
            writer_submitted = time.monotonic()
            await timed.submit(operation, payload, site="onlyfans")
            writer_observed = time.monotonic()
            item.state = TaskState.COMPLETED
            item.result = TaskResult(success=True)
            item.completed_at = item.result.completed_at
            if after:
                await batcher.submit(
                    "finish",
                    completion_request(ledger, owned, item),
                    metrics=metrics,
                    phase="finish",
                )
            else:
                await run_database_call(ledger.finish, owned, item)
            durations.append(time.monotonic() - started)
            finished.append(time.monotonic())
            if config.get("cleanup_comparison") or capacity:
                sample = {
                    "started": started,
                    "finished": finished[-1],
                    "duration_s": durations[-1],
                    "handler_ms": handler_ms,
                    "writer_submitted": writer_submitted,
                    "writer_observed": writer_observed,
                    "writer": {
                        name: getattr(timed, name)
                        for name in (
                            "admission_ms",
                            "queue_ms",
                            "execution_ms",
                            "commit_ms",
                            "receipt_lookup_ms",
                            "receipt_finalize_ms",
                            "receipt_lock_ms",
                            "receipt_read_ms",
                            "write_fence_ms",
                            "result_publication_ms",
                            "result_observation_ms",
                            "elapsed_ms",
                        )
                    },
                    "lifecycle": {
                        name: values["ms"] for name, values in metrics.ledger.items()
                    },
                }
                if phase_file is not None:
                    phase_file.write(json.dumps(sample) + "\n")
                else:
                    samples.append(sample)
            for name, values in metrics.ledger.items():
                lifecycle_sums[name] = lifecycle_sums.get(name, 0) + values["ms"]
            for name in (
                "admission_ms",
                "queue_ms",
                "result_observation_ms",
                "elapsed_ms",
            ):
                writer_sums[name] = writer_sums.get(name, 0) + getattr(timed, name)
        finally:
            pool._ledger_persisting_tasks.discard(owned.task_id)
            if native_worker_loop:
                active.discard(asyncio.current_task())

    async def run_native_worker():
        nonlocal pool, stage_changed
        from ultima_scraper_backend.job_system import ledger_runtime
        from ultima_scraper_backend.redis.worker_registry import WorkerRegistry
        from ultima_scraper_backend.workers.worker_pool import Worker

        # Inject only owned connections, configured limits and the synthetic
        # handler. Dispatch, buffered claims, renewal and status publication use
        # the production Worker.run and LedgerRouterAdapter implementations.
        ledger_runtime.ExecutionLedger = lambda: ledger
        worker = Worker.__new__(Worker)
        worker.worker_id = f"worker-{config['index']}"
        worker.backend_id = "backend-a"
        worker.worker_index = config["index"] + 1
        worker.worker_count = (
            8  # The reserved interactive process is not a scrape worker.
        )
        worker.supported_sites = ["onlyfans"]
        worker.apis = {"onlyfans": SimpleNamespace(auths={})}
        worker.task_job_storage = object()
        worker.redis = redis
        worker.ultima_scraper_api = None
        worker.worker_registry = WorkerRegistry(
            redis.client, worker.backend_id, worker.worker_id
        )
        worker._claim_runtime_context = {}
        worker._shutdown_event = asyncio.Event()
        worker._ledger_persisting_tasks = pool._ledger_persisting_tasks
        worker._ledger_lifecycle_batcher = batcher
        worker.compute_dynamic_concurrency = lambda: fetch_slots
        pool = worker
        update_status = worker._update_worker_status

        async def status(**kwargs):
            began = time.monotonic()
            await update_status(**kwargs)
            status_spans.append((began, time.monotonic()))

        worker._update_worker_status = status

        async def execute_ready(job_id, task_id, **kwargs):
            nonlocal stage_changed
            stage_changed = worker._ledger_stage_changed
            _, owned = worker._ledger_claims.pop((job_id, task_id))
            await execute(owned)
            return None, True, None

        worker._execute_ready_task = execute_ready
        claim_many = ledger.claim_many

        def claim(**kwargs):
            began = time.monotonic()
            cpu_began = time.thread_time()
            detail = {"started": began, "queries": {}}
            claim_context.detail = detail
            try:
                claimed = claim_many(**kwargs)
                ended = time.monotonic()
                detail.update(finished=ended, tasks=len(claimed),
                              thread_cpu_seconds=time.thread_time() - cpu_began)
                claim_spans.append((began, ended, len(claimed)))
                claim_details.append(detail)
                return claimed
            finally:
                claim_context.detail = None

        ledger.claim_many = claim

        async def stop_when_complete():
            while True:
                if (await run_database_call(ledger.stats, "job-test"))[
                    "state"
                ] == "completed":
                    worker.running = False
                    worker._shutdown_event.set()
                    worker._ledger_stage_changed.set()
                    return
                await asyncio.sleep(0.25)

        watcher = asyncio.create_task(stop_when_complete())
        try:
            await worker.run()
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    try:
        Path(config["ready"]).touch()
        while not Path(config["go"]).is_file():
            await asyncio.sleep(0.01)
        sampler = asyncio.create_task(sample_runtime()) if capacity else None
        async with asyncio.timeout(config.get("timeout", 180)):
            if native_worker_loop:
                await run_native_worker()
            while not native_worker_loop:
                for result in list(active):
                    if result.done():
                        active.remove(result)
                        result.result()
                stage_changed.clear()
                available = (
                    worker_claim_capacity(pool, len(active), fetch_slots, claim_batch)[
                        0
                    ]
                    if after
                    else fetch_slots - len(active)
                )
                if available <= 0:
                    if after:
                        await wait_for_worker_capacity(active, stage_changed)
                    else:
                        await asyncio.wait(
                            active, return_when=asyncio.FIRST_COMPLETED, timeout=1
                        )
                    continue
                if not buffered:
                    claim_started = time.monotonic()
                    buffered.extend(
                        await run_database_call(
                            ledger.claim_many,
                            owner=f"worker-{config['index']}",
                            backend_id="backend-a",
                            capabilities=["onlyfans"],
                            count=claim_batch if after else min(available, claim_batch),
                        )
                    )
                    if capacity:
                        claim_spans.append(
                            (claim_started, time.monotonic(), len(buffered))
                        )
                if not buffered:
                    stats = await run_database_call(ledger.stats, "job-test")
                    if stats["completed"] == config["count"]:
                        break
                    await asyncio.sleep(0.05)
                    continue
                for _ in range(min(available, len(buffered))):
                    active.add(asyncio.create_task(execute(buffered.popleft())))
            await asyncio.gather(*active)
        if phase_file is not None:
            phase_file.flush()
        Path(config["result"]).write_text(
            json.dumps(
                {
                    "configured_fetch_slots": fetch_slots,
                    "configured_persistence_slots": min(fetch_slots, claim_batch) if after else 0,
                    "durations": durations,
                    "finished": finished,
                    "SQL_transactions": transactions,
                    "SQL_driver_calls": calls,
                    "lifecycle_sums_ms": lifecycle_sums,
                    "writer_sums_ms": writer_sums,
                    "phase_samples": samples,
                    "phase_sample_path": str(phase_path) if phase_file else None,
                    "runtime_samples": runtime_samples,
                    "finish_batches": finish_batches,
                    "claim_spans": claim_spans,
                    "claim_details": claim_details,
                    "pool_events": pool_events,
                    "status_spans": status_spans,
                }
            )
        )
    finally:
        if "sampler" in locals() and sampler is not None:
            sampler.cancel()
            await asyncio.gather(sampler, return_exceptions=True)
        for pending in active:
            pending.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        if phase_file is not None:
            phase_file.close()
        if batcher is not None:
            await batcher.close()
        await redis.client.aclose()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
