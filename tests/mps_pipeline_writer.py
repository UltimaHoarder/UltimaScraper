"""Dedicated writer for the owned capacity fixture; no production connections."""

import asyncio
import hashlib
import importlib.util
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import psutil
from redis.asyncio import Redis
from sqlalchemy import create_engine, event
from sqlmodel import Session
from ultima_scraper_backend.database import write_queue, write_receipts
from ultima_scraper_backend.database.threads import run_owned_thread_call
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor


async def main(config):
    assert config["redis_socket"].startswith("/tmp/")
    engine = create_engine(
        config["sql_url"],
        pool_size=8,
        max_overflow=0,
        connect_args={
            "options": "-c search_path=onlyfans,management,public -c statement_timeout=15000"
        },
    )
    assert str(engine.url.query.get("host", "")).startswith("/tmp/usr-mps-pg-")
    if config.get("receipt_baseline"):
        name = "ultima_scraper_backend.database._capacity_receipt_baseline"
        spec = importlib.util.spec_from_file_location(name, config["receipt_baseline"])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        write_receipts.receipt_batch = module.receipt_batch

    executor_type = PostgreSQLWriteExecutor
    if config.get("executor_baseline"):
        name = "ultima_scraper_backend.database._capacity_executor_baseline"
        spec = importlib.util.spec_from_file_location(name, config["executor_baseline"])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        executor_type = module.PostgreSQLWriteExecutor

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    class Executor(executor_type):
        def __init__(self):
            self._site_manager = lambda site: SimpleNamespace(get_session=sessions)
            self.batches = []
            self.batch_spans = []

        async def execute_batch(self, commands):
            self.batches.append(len(commands))
            started = time.monotonic()
            if commands[0].operation == write_queue.DatabaseWriteOperation.UPSERT_USER:
                result = await run_owned_thread_call(
                    self._run_async_batch, self._upsert_users, commands, "onlyfans"
                )
            else:
                result = await run_owned_thread_call(
                    self._upsert_invalid_users, commands, "onlyfans"
                )
            self.batch_spans.append((started, time.monotonic(), len(commands)))
            return result

        async def close(self):
            pass

    commits, pool, runtime = [], [], []
    checked_out = calls = 0

    def committed(*args):
        commits.append(time.monotonic())

    def checkout(*args):
        nonlocal checked_out
        checked_out += 1
        pool.append((time.monotonic(), checked_out))

    def checkin(*args):
        nonlocal checked_out
        checked_out -= 1
        pool.append((time.monotonic(), checked_out))

    def executed(*args):
        nonlocal calls
        calls += 1

    for name, callback in (
        ("commit", committed),
        ("checkout", checkout),
        ("checkin", checkin),
        ("after_cursor_execute", executed),
    ):
        event.listen(engine, name, callback)

    async def sample_runtime():
        process = psutil.Process()
        previous = time.monotonic()
        while True:
            now = time.monotonic()
            cpu = process.cpu_times()
            runtime.append(
                {
                    "at": now,
                    "rss_mib": process.memory_info().rss / 2**20,
                    "cpu_seconds": cpu.user + cpu.system,
                    "loop_lag_ms": max(0, now - previous - 0.05) * 1000,
                }
            )
            previous = now
            await asyncio.sleep(0.05)

    redis = SimpleNamespace(
        client=Redis(unix_socket_path=config["redis_socket"]), is_connected=True
    )
    executor = Executor()
    service = write_queue.DatabaseWriterService(
        redis, executor, batch_size=100, concurrency=8, block_ms=5
    )
    stop = Path(config["stop"])
    writer = asyncio.create_task(service.run(stop_requested=stop.exists))
    sampler = asyncio.create_task(sample_runtime())
    try:
        ready_key = service.READY_KEY.format(consumer_name=service.consumer_name)
        async with asyncio.timeout(30):
            while not await redis.client.exists(ready_key):
                if writer.done():
                    await writer
                    raise AssertionError("Writer exited before readiness")
                await asyncio.sleep(0.02)
        Path(config["ready"]).touch()
        await writer
        Path(config["result"]).write_text(
            json.dumps(
                {
                    "invalid_upsert_source": executor._upsert_invalid_users.__code__.co_filename,
                    "invalid_upsert_sha256": hashlib.sha256(Path(executor._upsert_invalid_users.__code__.co_filename).read_bytes()).hexdigest(),
                    "writer_batches": executor.batch_spans,
                    "batch_sizes": executor.batches,
                    "writer_transactions": commits,
                    "writer_pool": pool,
                    "writer_runtime": runtime,
                    "SQL_driver_calls": calls,
                }
            )
        )
    finally:
        sampler.cancel()
        await asyncio.gather(sampler, return_exceptions=True)
        service.stop()
        await writer
        await redis.client.aclose()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(json.loads(Path(sys.argv[1]).read_text())))
