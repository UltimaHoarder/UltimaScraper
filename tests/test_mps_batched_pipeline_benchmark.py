"""Paired native pipeline benchmark, including live claims/refill/archive."""

import asyncio
import importlib.util
import json
import os
import sys
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from statistics import mean
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlmodel import Session
from test_content_write_resources import content_engine, postgres_engine
from test_database_write_queue import redis_manager
from ultima_scraper_backend.database import write_queue
from ultima_scraper_backend.database.threads import (
    run_database_call,
    run_owned_thread_call,
)
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.job_system.ledger import ExecutionLedger, Limits
from ultima_scraper_backend.job_system.ledger_batches import completion_request
from ultima_scraper_backend.job_system.ledger_runtime import (
    FencedWriter,
    LedgerTaskStorage,
    wait_for_worker_capacity,
    worker_claim_capacity,
)
from ultima_scraper_backend.job_system.lifecycle_batcher import LifecycleBatcher
from ultima_scraper_backend.job_system.models import (
    Job,
    Task,
    TaskResult,
    TaskState,
)
from ultima_scraper_db_archive import global_db
from ultima_scraper_db_archive.execution_models import EXECUTION_MODELS

__all__ = ["content_engine", "postgres_engine", "redis_manager"]


def read_phase_samples(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream]


@pytest.mark.skipif(
    os.environ.get("USR_BENCH_MPS_BATCHED_PIPELINE") != "1"
    and os.environ.get("USR_BENCH_MPS_RECEIPT_CLEANUP") != "1",
    reason="opt-in owned PostgreSQL/Redis benchmark",
)
@pytest.mark.parametrize("order", ["before_after", "after_before"])
async def test_batched_pipeline(
    content_engine, redis_manager, monkeypatch, tmp_path, order
):
    if type(redis_manager.client).__module__.startswith("fakeredis"):
        pytest.skip("native Redis fixture required")
    cleanup_comparison = os.environ.get("USR_BENCH_MPS_RECEIPT_CLEANUP") == "1"
    capacity = os.environ.get("USR_MPS_PIPELINE_CAPACITY") == "1"
    ledger_comparison = capacity and bool(
        os.environ.get("USR_MPS_PIPELINE_LEDGER_BASELINE_SOURCE")
    )
    single_arm = capacity and os.environ.get("USR_MPS_PIPELINE_SINGLE_ARM") == "1"
    separate_writer = (
        capacity and os.environ.get("USR_MPS_PIPELINE_WRITER_PROCESS") == "1"
    )
    if single_arm and order != "before_after":
        pytest.skip("confirmation runs the current implementation once")
    timeout = int(
        os.environ.get("USR_MPS_PIPELINE_TIMEOUT", "1200" if capacity else "180")
    )
    from ultima_scraper_backend.job_system import ledger as current_ledger

    source = Path(
        os.environ.get("USR_MPS_PIPELINE_LEDGER_BASELINE_SOURCE")
        or current_ledger.__file__
        if cleanup_comparison or capacity
        else os.environ.get("USR_MPS_PIPELINE_BASELINE_SOURCE", "")
    )
    if not source.is_file():
        pytest.skip("pre-change ledger snapshot required")
    name = "ultima_scraper_backend.job_system._pipeline_baseline"
    spec = importlib.util.spec_from_file_location(name, source)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[name] = baseline
    spec.loader.exec_module(baseline)
    phase_source = (
        None
        if cleanup_comparison
        else os.environ.get("USR_MPS_PIPELINE_PHASE_BASELINE_SOURCE")
    )
    transport_source = (
        None
        if cleanup_comparison
        else os.environ.get("USR_MPS_PIPELINE_TRANSPORT_BASELINE_SOURCE")
    )

    def load_snapshot(path, name):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    phase_baseline = (
        load_snapshot(phase_source, "ultima_scraper_backend.job_system._phase_baseline")
        if phase_source
        else None
    )
    transport_baseline = (
        load_snapshot(
            transport_source, "ultima_scraper_backend.database._result_baseline"
        )
        if transport_source
        else None
    )
    from ultima_scraper_backend.database import write_receipts

    current_receipt_batch = write_receipts.receipt_batch
    receipt_source = os.environ.get("USR_MPS_PIPELINE_RECEIPTS_BASELINE_SOURCE")
    receipt_baseline = (
        load_snapshot(
            receipt_source, "ultima_scraper_backend.database._capacity_receipt_baseline"
        )
        if receipt_source
        else None
    )
    executor_source = os.environ.get("USR_MPS_PIPELINE_EXECUTOR_BASELINE_SOURCE")
    executor_baseline = (
        load_snapshot(executor_source, "ultima_scraper_backend.database._capacity_executor_baseline")
        if executor_source else None
    )
    monkeypatch.delenv("ULTIMA_JOB_ENGINE", raising=False)
    with content_engine.begin() as connection:
        postgres_settings = dict(
            connection.execute(
                text(
                    "SELECT name, current_setting(name) FROM pg_settings WHERE name IN ('server_version','shared_buffers','work_mem','io_method','max_connections')"
                )
            ).all()
        )
        for model in EXECUTION_MODELS:
            model.__table__.create(connection, checkfirst=True)
        from ultima_scraper_backend.database.job_partitions import (
            ensure_history_partition,
        )

        with Session(bind=connection) as session:
            ensure_history_partition(session, "fixture-history", "job_tasks")
        connection.execute(
            text(
                "INSERT INTO management.execution_feed(feed_id,next_sequence) VALUES(1,1) ON CONFLICT DO NOTHING"
            )
        )
    options = {
        "connect_args": {
            "options": "-c search_path=onlyfans,management,public -c statement_timeout=15000"
        },
        "max_overflow": 0,
    }
    writer_engine = create_engine(content_engine.url, pool_size=8, **options)
    cleanup_engine = create_engine(content_engine.url, pool_size=1, **options)
    engines = [
        create_engine(content_engine.url, pool_size=3, **options) for _ in range(7)
    ]

    @contextmanager
    def sessions_for(engine):
        with Session(engine) as session:
            yield session

    def sessions(engine):
        return lambda: sessions_for(engine)

    monkeypatch.setattr(global_db, "global_session", sessions(engines[0]))

    class Executor(PostgreSQLWriteExecutor):
        def __init__(self):
            self._site_manager = lambda site: SimpleNamespace(
                get_session=sessions(writer_engine)
            )
            self.batches = []
            self.batch_spans = []
            self.profile_taken = False

        def profile_invalid(self, commands, site):
            import cProfile
            import io
            import pstats

            profile = cProfile.Profile()
            result = profile.runcall(self._upsert_invalid_users, commands, site)
            output = io.StringIO()
            pstats.Stats(profile, stream=output).sort_stats("cumulative").print_stats(
                45
            )
            Path(os.environ["USR_MPS_PROFILE_WRITER"]).write_text(output.getvalue())
            return result

        async def execute_batch(self, commands):
            self.batches.append(len(commands))
            started = time.monotonic()
            if commands[0].operation == write_queue.DatabaseWriteOperation.UPSERT_USER:
                result = await run_owned_thread_call(
                    self._run_async_batch, self._upsert_users, commands, "onlyfans"
                )
            else:
                method = self._upsert_invalid_users
                if (
                    os.environ.get("USR_MPS_PROFILE_WRITER")
                    and not self.profile_taken
                    and len(commands) >= 40
                ):
                    self.profile_taken = True
                    method = self.profile_invalid
                result = await run_owned_thread_call(method, commands, "onlyfans")
            self.batch_spans.append((started, time.monotonic(), len(commands)))
            return result

        async def close(self):
            pass

    count = int(os.environ.get("USR_MPS_PIPELINE_TASKS", "28000"))
    window = int(os.environ.get("USR_MPS_PIPELINE_WINDOW", "20000"))
    history = int(os.environ.get("USR_MPS_PIPELINE_HISTORY", "200000"))
    fetch_slots = int(os.environ.get(
        "USR_MPS_PIPELINE_FETCH_SLOTS",
        "358" if capacity and os.environ.get("USR_MPS_PIPELINE_PROCESSES") == "1" else "207",
    ))
    assert fetch_slots > 0, "Benchmark fetch slots must be positive"
    observations = {}
    receipt_history = (
        int(os.environ.get("USR_MPS_CLEANUP_RECEIPTS", "250000"))
        if cleanup_comparison
        else 0
    )
    try:
        for label in ["after"] if single_arm else order.split("_"):
            monkeypatch.setattr(
                write_receipts,
                "receipt_batch",
                receipt_baseline.receipt_batch
                if label == "before" and receipt_baseline
                else current_receipt_batch,
            )
            after = (
                capacity
                or cleanup_comparison
                or label == "after"
                or phase_baseline is not None
            )
            with content_engine.begin() as connection:
                connection.execute(
                    text(
                        "TRUNCATE management.execution_mutations,management.execution_outbox,management.execution_resources,management.execution_attempts,management.execution_work,management.execution_runs,management.execution_definitions,management.mps_plans,management.mps_task_definitions,management.database_write_receipts,management.jobs,management.job_tasks,management.migration_source_identities,onlyfans.users,onlyfans.invalid_users CASCADE"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO management.job_tasks(task_id,job_id,task_type,status,result_json) SELECT 'history-'||n,'fixture-history','scrape','completed',repeat('x',256) FROM generate_series(1,:count) n"
                    ),
                    {"count": history},
                )
                if cleanup_comparison:
                    connection.execute(
                        text("""INSERT INTO management.database_write_receipts(command_id,operation,site,result_json,committed_at)
                        SELECT 'expired-'||n,'upsert_user','onlyfans',:result_json,now()-interval '8 days'
                      FROM generate_series(1,:count) n"""),
                        {
                            "count": receipt_history,
                            "result_json": json.dumps(
                                {"success": True, "payload": {"synced": True}}
                            ),
                        },
                    )
            await redis_manager.client.flushdb()
            baseline_ledger = (ledger_comparison and label == "before") or not after
            ledger_type = baseline.ExecutionLedger if baseline_ledger else ExecutionLedger
            limit_type = baseline.Limits if baseline_ledger else Limits
            limits = limit_type(
                tasks=window,
                global_tasks=window,
                batch=128,
                planner_batch=512,
                lease_seconds=600,
            )
            if capacity:
                from dataclasses import replace

                limits = replace(limits, bytes=64 * 1024 * 1024, batch=100)
            if after:
                from dataclasses import replace

                limits = replace(limits, archive_batch=2048, terminal_tasks=2 * window)
            ledgers = [
                ledger_type(sessions(engine), limits=limits) for engine in engines
            ]
            ledger = ledgers[0]
            job = Job.create(name="Owned MPS pipeline", created_by="test", tasks=[])
            job.job_id = "job-test"
            ledger.manifests.create(
                job_id=job.job_id,
                site="onlyfans",
                job_config=job.to_dict(),
                selection={
                    "start_id": 1000,
                    "end_id": 999 + count,
                    "max_profiles": None,
                },
                proxy_pool=[],
                site_session_factory=ledger.session_factory,
            )
            executor = Executor()
            if label == "before" and executor_baseline:
                executor._upsert_invalid_users = executor_baseline.PostgreSQLWriteExecutor._upsert_invalid_users.__get__(executor)
            service = write_queue.DatabaseWriterService(
                redis_manager, executor, batch_size=100, concurrency=8, block_ms=5
            )
            client_type = (
                transport_baseline.DatabaseWriteClient
                if label == "before" and transport_baseline
                else write_queue.DatabaseWriteClient
            )
            client = client_type(
                redis_manager,
                max_queue_commands=800,
                max_queue_bytes=64 * 1024 * 1024,
                timeout_seconds=120,
            )
            pools = [SimpleNamespace(_ledger_persisting_tasks=set()) for _ in engines]
            batchers = (
                [
                    (
                        phase_baseline.LifecycleBatcher
                        if label == "before" and phase_baseline
                        else LifecycleBatcher
                    )(item)
                    for item in ledgers
                ]
                if after
                else [None] * 7
            )
            finished, durations, refills, archives = [], [], [], []
            lifecycle_sums, writer_sums = {}, {}
            phase_samples, occupancy, cleanup_samples = [], [], []
            worker_observations, planner_loops, redis_samples = [], [], []
            host_samples = []
            writer_runtime = []
            writer_transactions = []
            writer_pool_events = []
            writer_checked_out = 0

            def writer_committed(*args, writer_transactions=writer_transactions):
                writer_transactions.append(time.monotonic())

            def writer_checkout(*args, writer_pool_events=writer_pool_events):
                nonlocal writer_checked_out
                writer_checked_out += 1
                writer_pool_events.append((time.monotonic(), writer_checked_out))

            def writer_checkin(*args, writer_pool_events=writer_pool_events):
                nonlocal writer_checked_out
                writer_checked_out -= 1
                writer_pool_events.append((time.monotonic(), writer_checked_out))

            if capacity:
                event.listen(writer_engine, "commit", writer_committed)
                event.listen(writer_engine, "checkout", writer_checkout)
                event.listen(writer_engine, "checkin", writer_checkin)
            benchmark_started = asyncio.Event()
            cleanup_stopping = asyncio.Event()
            transactions = driver_calls = 0

            def committed(*args):
                nonlocal transactions
                transactions += 1

            def executed(*args):
                nonlocal driver_calls
                driver_calls += 1

            for engine in [writer_engine, *engines]:
                event.listen(engine, "commit", committed)
                event.listen(engine, "after_cursor_execute", executed)

            async def execute(
                index,
                owned,
                stage_changed,
                ledgers=ledgers,
                batchers=batchers,
                client=client,
                after=after,
                pools=pools,
                durations=durations,
                finished=finished,
            ):
                started = time.monotonic()
                item = Task.from_dict(owned.task)
                storage = LedgerTaskStorage(
                    ledgers[index], owned, item, redis_manager, batcher=batchers[index]
                )
                fenced = FencedWriter(client, ledgers[index], owned, storage)
                await asyncio.sleep(0.65 + (item.user_id % 100) / 800)
                if after:
                    pools[index]._ledger_persisting_tasks.add(owned.task_id)
                    stage_changed.set()
                try:
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
                                "name": "Fixture",
                                "about": "Fixture biography",
                                "avatar": f"https://fixture.invalid/{item.user_id}.jpg",
                                "website": "https://fixture.invalid/",
                                "postsCount": 10,
                                "is_performer": True,
                            }
                        }
                    await fenced.submit(operation, payload, site="onlyfans")
                    item.state = TaskState.COMPLETED
                    item.result = TaskResult(success=True)
                    item.completed_at = item.result.completed_at
                    if after:
                        await batchers[index].submit(
                            "finish", completion_request(ledgers[index], owned, item)
                        )
                    else:
                        await run_database_call(ledgers[index].finish, owned, item)
                    durations.append(time.monotonic() - started)
                    finished.append(time.monotonic())
                finally:
                    pools[index]._ledger_persisting_tasks.discard(owned.task_id)

            async def dispatch(
                index,
                finished=finished,
                after=after,
                pools=pools,
                ledgers=ledgers,
                execute=execute,
            ):
                active = set()
                buffered = deque()
                stage_changed = asyncio.Event()
                while len(finished) < count:
                    for result in list(active):
                        if result.done():
                            active.remove(result)
                            result.result()
                    stage_changed.clear()
                    available = (
                        fetch_slots - len(active)
                        if not after
                        else worker_claim_capacity(pools[index], len(active), fetch_slots, 128)[
                            0
                        ]
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
                        buffered.extend(
                            await run_database_call(
                                ledgers[index].claim_many,
                                owner=f"worker-{index}",
                                backend_id="backend-a",
                                capabilities=["onlyfans"],
                                count=128 if after else min(available, 128),
                            )
                        )
                    claims = [
                        buffered.popleft() for _ in range(min(available, len(buffered)))
                    ]
                    for owned in claims:
                        active.add(
                            asyncio.create_task(execute(index, owned, stage_changed))
                        )
                    if not claims:
                        await asyncio.sleep(0.05)
                await asyncio.gather(*active)

            async def planner(
                refills=refills, after=after, ledger=ledger, planner_loops=planner_loops
            ):
                while True:
                    loop_started = time.monotonic()
                    if capacity:
                        await run_database_call(ledger.recover_expired)
                    for _ in range(8):
                        kwargs = {"diagnostics": refills}
                        if after:
                            kwargs["refill_only"] = True
                        if await run_database_call(ledger.tick, **kwargs) is None:
                            break
                    planner_loops.append((loop_started, time.monotonic()))
                    await asyncio.sleep(0.25)

            async def archiver(ledger=ledger, archives=archives):
                while True:
                    archived = await run_database_call(
                        ledger.archive_tick, diagnostics=archives
                    )
                    await asyncio.sleep(0 if archived else 0.25)

            async def relay_events(ledger=ledger):
                from anyio import from_thread

                async def publish(payloads):
                    pipeline = redis_manager.client.pipeline(transaction=False)
                    for payload in payloads:
                        pipeline.publish("fixture:ledger-events", json.dumps(payload))
                    await pipeline.execute()

                def publish_many(payloads):
                    from_thread.run(publish, payloads)

                while True:
                    delivered = await run_database_call(
                        ledger.relay, publish_many=publish_many
                    )
                    await asyncio.sleep(0 if delivered == ledger.limits.batch else 0.25)

            async def sample_occupancy(
                benchmark_started=benchmark_started, occupancy=occupancy
            ):
                def resident_counts():
                    with sessions_for(engines[0]) as session:
                        return dict(
                            session.execute(
                                text(
                                    "SELECT state,count(*) FROM management.execution_work WHERE run_id='job-test' GROUP BY state"
                                )
                            ).all()
                        )

                await benchmark_started.wait()
                while True:
                    sample = await run_database_call(resident_counts)
                    occupancy.append(
                        {
                            "at": time.monotonic(),
                            "ready": sample.get("queued", 0),
                            "inflight": sample.get("running", 0)
                            + sample.get("persisting", 0),
                            "resident_execution": sum(
                                sample.get(k, 0)
                                for k in ("queued", "running", "persisting")
                            ),
                            "resident_terminal": sample.get("completed", 0)
                            + sample.get("failed", 0),
                            "resident": sum(sample.values()),
                        }
                    )
                    await asyncio.sleep(0.1 if capacity else 1)

            async def sample_redis(
                benchmark_started=benchmark_started, redis_samples=redis_samples
            ):
                await benchmark_started.wait()
                while True:
                    sample_started = time.monotonic()
                    info = await redis_manager.client.info("commandstats")
                    redis_samples.append(
                        {
                            "at": time.monotonic(),
                            "latency_ms": (time.monotonic() - sample_started) * 1000,
                            "commands": info,
                            "queue": await redis_manager.client.xlen(
                                write_queue.DatabaseWriteClient.STREAM_KEY
                            ),
                        }
                    )
                    await asyncio.sleep(0.1)

            async def sample_host(
                host_samples=host_samples, benchmark_started=benchmark_started
            ):
                import psutil

                process = psutil.Process()
                await benchmark_started.wait()
                while True:
                    host_samples.append(
                        {
                            "at": time.monotonic(),
                            "cpu": psutil.cpu_times()._asdict(),
                            "available_memory_mib": psutil.virtual_memory().available
                            / 2**20,
                            "observer_rss_mib": process.memory_info().rss / 2**20,
                            "observer_cpu_seconds": sum(process.cpu_times()[:2]),
                        }
                    )
                    await asyncio.sleep(1)

            async def cleanup_receipts(
                benchmark_started=benchmark_started,
                cleanup_stopping=cleanup_stopping,
                cleanup_samples=cleanup_samples,
            ):
                from ultima_scraper_backend.database.receipt_retention import (
                    pending_command_ids,
                    purge_receipts,
                )

                cursor = "(0,0)"
                await benchmark_started.wait()
                while not cleanup_stopping.is_set():
                    protected = await pending_command_ids(redis_manager)
                    batch_started = time.monotonic()
                    result = await run_database_call(
                        purge_receipts,
                        protected_ids=protected,
                        session_factory=sessions(cleanup_engine),
                        cursor=cursor,
                        mode="always",
                    )
                    cleanup_samples.append(
                        {
                            "started": batch_started,
                            "finished": time.monotonic(),
                            "deleted": result.deleted,
                            "busy": result.busy,
                        }
                    )
                    if result.finished:
                        return
                    if not result.busy:
                        cursor = result.next_cursor
                    await asyncio.sleep(0.005 if not result.busy else 0.05)

            writer_stop = tmp_path / f"{label}-writer.stop"
            writer_ready = tmp_path / f"{label}-writer.ready"
            writer_output = tmp_path / f"{label}-writer.result.json"

            async def run_writer_process(
                writer_stop=writer_stop,
                writer_ready=writer_ready,
                writer_output=writer_output,
                label=label,
                executor=executor,
                writer_transactions=writer_transactions,
                writer_pool_events=writer_pool_events,
                writer_runtime=writer_runtime,
            ):
                nonlocal transactions, driver_calls
                config_path = writer_output.with_suffix(".config.json")
                config_path.write_text(
                    json.dumps(
                        {
                            "sql_url": content_engine.url.render_as_string(
                                hide_password=False
                            ),
                            "redis_socket": redis_manager.client.connection_pool.connection_kwargs[
                                "path"
                            ],
                            "receipt_baseline": receipt_source
                            if label == "before"
                            else None,
                            "executor_baseline": executor_source if label == "before" else None,
                            "ready": str(writer_ready),
                            "stop": str(writer_stop),
                            "result": str(writer_output),
                        }
                    )
                )
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(Path(__file__).with_name("mps_pipeline_writer.py")),
                    str(config_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    output = await process.communicate()
                    assert process.returncode == 0, output
                    values = json.loads(writer_output.read_text())
                    executor.batches = values["batch_sizes"]
                    executor.invalid_upsert_source = values["invalid_upsert_source"]
                    executor.invalid_upsert_sha256 = values["invalid_upsert_sha256"]
                    executor.batch_spans = values["writer_batches"]
                    writer_transactions.extend(values["writer_transactions"])
                    writer_pool_events.extend(values["writer_pool"])
                    writer_runtime.extend(values["writer_runtime"])
                    transactions += len(values["writer_transactions"])
                    driver_calls += values["SQL_driver_calls"]
                finally:
                    if process.returncode is None:
                        process.terminate()
                    await process.wait()

            writer = asyncio.create_task(
                run_writer_process() if separate_writer else service.run()
            )
            if separate_writer:
                try:
                    async with asyncio.timeout(30):
                        while not writer_ready.is_file():
                            if writer.done():
                                await writer
                                raise AssertionError("Writer stopped before readiness")
                            await asyncio.sleep(0.02)
                except BaseException:
                    writer.cancel()
                    await asyncio.gather(writer, return_exceptions=True)
                    raise
            cleanup_task = None
            controls = [asyncio.create_task(planner())]
            if after:
                controls.append(asyncio.create_task(archiver()))
            if os.environ.get("USR_MPS_PIPELINE_NATIVE_WORKER") == "1":
                controls.append(asyncio.create_task(relay_events()))
            if cleanup_comparison or capacity:
                controls.append(asyncio.create_task(sample_occupancy()))
                if capacity:
                    controls.append(asyncio.create_task(sample_redis()))
                    controls.append(asyncio.create_task(sample_host()))
                if label == "after" and cleanup_comparison:
                    cleanup_task = asyncio.create_task(cleanup_receipts())
            started = time.monotonic()
            try:
                async with asyncio.timeout(timeout):
                    if os.environ.get("USR_MPS_PIPELINE_PROCESSES") == "1":
                        processes, paths = [], []
                        go = tmp_path / f"{label}-go"
                        try:
                            for index in range(7):
                                ready = tmp_path / f"{label}-{index}.ready"
                                result = tmp_path / f"{label}-{index}.result.json"
                                config_path = tmp_path / f"{label}-{index}.json"
                                config_path.write_text(
                                    json.dumps(
                                        {
                                            "label": "after" if after else "before",
                                            "phase_baseline": phase_source
                                            if label == "before"
                                            else None,
                                            "transport_baseline": transport_source
                                            if label == "before"
                                            else None,
                                            "index": index,
                                            "count": count,
                                            "window": window,
                                            "baseline": str(source),
                                            "ledger_baseline": str(source)
                                            if ledger_comparison and label == "before"
                                            else None,
                                            "sql_url": content_engine.url.render_as_string(
                                                hide_password=False
                                            ),
                                            "redis_socket": redis_manager.client.connection_pool.connection_kwargs[
                                                "path"
                                            ],
                                            "ready": str(ready),
                                            "result": str(result),
                                            "go": str(go),
                                            "cleanup_comparison": cleanup_comparison,
                                            "capacity": capacity,
                                            "native_worker_loop": os.environ.get(
                                                "USR_MPS_PIPELINE_NATIVE_WORKER"
                                            )
                                            == "1",
                                            "timeout": timeout,
                                            "fetch_slots": fetch_slots,
                                            "claim_batch": 100 if capacity else 128,
                                        }
                                    )
                                )
                                processes.append(
                                    await asyncio.create_subprocess_exec(
                                        sys.executable,
                                        str(
                                            Path(__file__).with_name(
                                                "mps_pipeline_dispatch_worker.py"
                                            )
                                        ),
                                        str(config_path),
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=asyncio.subprocess.PIPE,
                                    )
                                )
                                paths.append((ready, result))
                            while not all(ready.is_file() for ready, _ in paths):
                                if any(p.returncode is not None for p in processes):
                                    raise AssertionError(
                                        [await p.communicate() for p in processes]
                                    )
                                await asyncio.sleep(0.02)
                            started = time.monotonic()
                            benchmark_started.set()
                            go.touch()

                            async def checked_worker(process):
                                output = await process.communicate()
                                assert process.returncode == 0, {
                                    "pid": process.pid,
                                    "returncode": process.returncode,
                                    "output": output,
                                }
                                return output

                            outputs = await asyncio.gather(
                                *(checked_worker(p) for p in processes)
                            )
                            assert all(p.returncode == 0 for p in processes), outputs
                            for _, path in paths:
                                values = json.loads(path.read_text())
                                if values.get("phase_sample_path"):
                                    values["phase_samples"] = await asyncio.to_thread(
                                        read_phase_samples, values["phase_sample_path"]
                                    )
                                worker_observations.append(values)
                                finished.extend(values["finished"])
                                durations.extend(values["durations"])
                                phase_samples.extend(values.get("phase_samples", []))
                                transactions += values["SQL_transactions"]
                                driver_calls += values["SQL_driver_calls"]
                                for name, value in values.get(
                                    "lifecycle_sums_ms", {}
                                ).items():
                                    lifecycle_sums[name] = (
                                        lifecycle_sums.get(name, 0) + value
                                    )
                                for name, value in values.get(
                                    "writer_sums_ms", {}
                                ).items():
                                    writer_sums[name] = writer_sums.get(name, 0) + value
                        finally:
                            for process in processes:
                                if process.returncode is None:
                                    process.terminate()
                            await asyncio.gather(*(p.wait() for p in processes))
                    else:
                        benchmark_started.set()
                        async with asyncio.TaskGroup() as group:
                            for index in range(7):
                                group.create_task(dispatch(index))
                    while (await run_database_call(ledger.stats, "job-test"))[
                        "state"
                    ] != "completed":
                        await asyncio.sleep(0.01)
                ended = time.monotonic()
                elapsed = ended - started
            finally:
                cleanup_stopping.set()
                if cleanup_task is not None:
                    await cleanup_task
                for control in controls:
                    control.cancel()
                control_results = await asyncio.gather(
                    *controls, return_exceptions=True
                )
                for batcher in batchers:
                    if batcher is not None:
                        await batcher.close()
                service.stop()
                if separate_writer:
                    writer_stop.touch()
                await asyncio.wait_for(writer, 10)
                for engine in [writer_engine, *engines]:
                    event.remove(engine, "commit", committed)
                    event.remove(engine, "after_cursor_execute", executed)
                if capacity:
                    event.remove(writer_engine, "commit", writer_committed)
                    event.remove(writer_engine, "checkout", writer_checkout)
                    event.remove(writer_engine, "checkin", writer_checkin)
                assert all(
                    isinstance(result, asyncio.CancelledError)
                    for result in control_results
                ), control_results
            assert ledger.stats("job-test")["completed"] == count
            with content_engine.connect() as connection:
                for table in (
                    "database_write_receipts",
                    "execution_mutations",
                    "job_tasks",
                ):
                    assert connection.scalar(
                        text(
                            f"SELECT count(*) FROM management.{table}"
                            + (
                                " WHERE job_id='job-test'"
                                if table == "job_tasks"
                                else ""
                            )
                        )
                    ) == count + (
                        receipt_history - sum(s["deleted"] for s in cleanup_samples)
                        if table == "database_write_receipts"
                        else 0
                    )
                assert (
                    connection.scalar(
                        text(
                            "SELECT (SELECT count(*) FROM onlyfans.users)+(SELECT count(*) FROM onlyfans.invalid_users)"
                        )
                    )
                    == count
                )
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM management.execution_work")
                    )
                    == 0
                )
                if cleanup_comparison:
                    assert (
                        connection.scalar(
                            text(
                                "SELECT count(*) FROM management.database_write_receipts WHERE run_id='job-test'"
                            )
                        )
                        == count
                    )
            times = sorted(finished)
            with content_engine.connect() as connection:
                assert (
                    connection.scalar(
                        text(
                            "SELECT count(*) FROM management.job_tasks WHERE job_id='fixture-history'"
                        )
                    )
                    == history
                )
            lo, hi = int(count * 0.1), int(count * 0.9)
            observations[label] = {
                "invalid_upsert_source": getattr(executor, "invalid_upsert_source", executor._upsert_invalid_users.__code__.co_filename),
                "invalid_upsert_sha256": getattr(executor, "invalid_upsert_sha256", None),
                "receipt_source": write_receipts.receipt_batch.__code__.co_filename,
                "worker_dispatch": "Worker.run"
                if os.environ.get("USR_MPS_PIPELINE_NATIVE_WORKER") == "1"
                else "fixture",
                "writer_process": "dedicated" if separate_writer else "coordinator",
                "seconds": elapsed,
                "tasks_per_s": count / elapsed,
                "steady_10_90_tasks_per_s": (hi - lo) / (times[hi] - times[lo]),
                "mean_task_seconds": mean(durations),
                "mean_lifecycle_ms": {
                    name: value / count for name, value in lifecycle_sums.items()
                },
                "mean_writer_ms": {
                    name: value / count for name, value in writer_sums.items()
                },
                "SQL_transactions": transactions,
                "SQL_driver_calls": driver_calls,
                "writer_mean_batch": mean(executor.batches),
                "refill_passes": len(refills),
                "archive_passes": len(archives),
                "mean_refill_ms": mean(r["pass_ms"] for r in refills)
                if refills
                else None,
            }
            if capacity:
                from mps_capacity_metrics import capacity_report

                observations[label]["capacity"] = capacity_report(
                    started=started,
                    ended=ended,
                    workers=worker_observations,
                    occupancy=occupancy,
                    refills=refills,
                    archives=archives,
                    writer_batches=executor.batch_spans,
                    writer_transactions=writer_transactions,
                    writer_pool=writer_pool_events,
                    planner_loops=planner_loops,
                    redis=redis_samples,
                    host=host_samples,
                    writer_runtime=writer_runtime,
                )
                output = os.environ.get("USR_MPS_PIPELINE_RESULT_DIR")
                if output:
                    Path(output).mkdir(parents=True, exist_ok=True)
                    Path(output, f"raw-{order}-{label}.json").write_text(
                        json.dumps(
                            {
                                "started": started,
                                "ended": ended,
                                "workers": worker_observations,
                                "occupancy": occupancy,
                                "refills": refills,
                                "archives": archives,
                                "writer_batches": executor.batch_spans,
                                "writer_transactions": writer_transactions,
                                "writer_pool": writer_pool_events,
                                "planner_loops": planner_loops,
                                "redis": redis_samples,
                                "host": host_samples,
                                "writer_runtime": writer_runtime,
                            }
                        )
                    )
            if cleanup_comparison:
                assert phase_samples, (
                    "Native worker processes are required for phase measurements"
                )
                samples = sorted(phase_samples, key=lambda s: s["finished"])
                steady = samples[lo:hi]
                steady_start, steady_end = times[lo], times[hi]
                aligned = [
                    s for s in occupancy if steady_start <= s["at"] <= steady_end
                ]
                observations[label].update(
                    {
                        "cleanup_mode": "enabled" if label == "after" else "paused",
                        "final_drain_seconds": max(0.0, ended - times[-1]),
                        "steady_mean_handler_ms": mean(s["handler_ms"] for s in steady),
                        "steady_mean_writer_ms": {
                            name: mean(s["writer"][name] for s in steady)
                            for name in steady[0]["writer"]
                        },
                        "steady_mean_lifecycle_ms": {
                            name: mean(s["lifecycle"].get(name, 0.0) for s in steady)
                            for name in sorted(
                                {name for s in steady for name in s["lifecycle"]}
                            )
                        },
                        "steady_occupancy_samples": aligned,
                        "cleanup_batches": len(cleanup_samples),
                        "cleanup_deleted": sum(s["deleted"] for s in cleanup_samples),
                        "cleanup_steady_batches": sum(
                            steady_start <= s["finished"] <= steady_end
                            for s in cleanup_samples
                        ),
                        "cleanup_mean_batch_ms": mean(
                            (s["finished"] - s["started"]) * 1000
                            for s in cleanup_samples
                        )
                        if cleanup_samples
                        else None,
                        "mean_archive_ms": mean(r["archive_ms"] for r in archives)
                        if archives
                        else None,
                    }
                )
                if label == "after":
                    assert observations[label]["cleanup_steady_batches"] > 0, (
                        "Cleanup did not overlap the matched steady window; increase receipt history"
                    )
        result = {
            "order": order,
            "tasks": count,
            "execution_window": window,
            "historical_archive_rows": history,
            "configured_fetch_slots_per_worker": fetch_slots,
            "observations": observations,
            "worker_processes": 7
            if os.environ.get("USR_MPS_PIPELINE_PROCESSES") == "1"
            else 1,
            "scope": "native PostgreSQL/Redis; seven worker dispatchers, live range claims/refill/archive, receipts and exact content; synthetic upstream, bounded local client pools, seeded archive history, no production PgBouncer",
            "python": sys.version,
            "postgres_settings": postgres_settings,
        }
        if cleanup_comparison:
            paused, enabled = observations["before"], observations["after"]
            result.update(
                {
                    "comparison": "receipt cleanup paused versus continuous enabled; current writer and ledger in both arms",
                    "expired_receipts_seeded": receipt_history,
                    "steady_throughput_delta_percent": 100
                    * (
                        enabled["steady_10_90_tasks_per_s"]
                        / paused["steady_10_90_tasks_per_s"]
                        - 1
                    ),
                    "mean_task_time_delta_percent": 100
                    * (enabled["mean_task_seconds"] / paused["mean_task_seconds"] - 1),
                    "production_throughput_verified": False,
                }
            )
        print("BATCHED_PIPELINE", json.dumps(result))
        output = os.environ.get("USR_MPS_PIPELINE_RESULT_DIR")
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            Path(output, f"pipeline-{order}.json").write_text(
                json.dumps(result, indent=2)
            )
    finally:
        for engine in [writer_engine, *engines]:
            engine.dispose()
        cleanup_engine.dispose()
