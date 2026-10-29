"""Opt-in comparison of independent refill latency, never a deployment queue."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest
from test_database_write_queue import _RecordingExecutor, redis_manager
from ultima_scraper_backend.database import write_queue

__all__ = ["redis_manager"]


@pytest.mark.skipif(
    os.environ.get("USR_BENCH_WRITER_REFILL") != "1",
    reason="set USR_BENCH_WRITER_REFILL=1 for the isolated scheduling comparison",
)
@pytest.mark.parametrize("scheduler", ["before", "after"])
async def test_independent_writer_refill_latency(redis_manager, monkeypatch, scheduler):
    service_type = write_queue.DatabaseWriterService
    if scheduler == "before":
        source = os.environ.get("USR_WRITER_BASELINE_SOURCE")
        if not source or not Path(source).is_file():
            pytest.skip("a local pre-repair source snapshot is required")
        name = "ultima_scraper_backend.database._refill_benchmark_baseline"
        spec = importlib.util.spec_from_file_location(name, source)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        monkeypatch.setattr(
            module, "_lookup_write_receipt", write_queue._lookup_write_receipt
        )
        service_type = module.DatabaseWriterService

    class Executor(_RecordingExecutor):
        def __init__(self, slow_command):
            super().__init__()
            self.slow_command = slow_command
            self.running_batches = 0
            self.peak_batches = 0

        async def execute_batch(self, commands):
            self.running_batches += 1
            self.peak_batches = max(self.peak_batches, self.running_batches)
            try:
                await asyncio.sleep(
                    0.35 if commands[0].command_id == self.slow_command else 0.005
                )
                return await super().execute_batch(commands)
            finally:
                self.running_batches -= 1

    async def enqueue(client, identifier, command_id):
        await client.enqueue(
            write_queue.DatabaseWriteOperation.UPSERT_USER,
            {"user": {"id": identifier}},
            site="onlyfans",
            command_id=command_id,
        )

    async def await_cache(client, command_id):
        async with asyncio.timeout(3):
            while not await redis_manager.client.get(client.result_key(command_id)):
                await asyncio.sleep(0.001)

    observations = []
    for trial in range(3):
        prefix = f"{scheduler}-{trial}-"
        slow = prefix + "slow"
        quick = prefix + "quick"
        later = prefix + "later"
        executor = Executor(slow)
        service = service_type(
            redis_manager, executor, batch_size=2, concurrency=2, block_ms=5
        )
        client = write_queue.DatabaseWriteClient(redis_manager)

        await enqueue(client, 1, slow)
        await enqueue(client, 2, quick)
        writer = asyncio.create_task(service.run())
        try:
            await await_cache(client, quick)
            started = time.monotonic()
            # The rotating label wraps to the slow batch, despite a free SQL
            # slot and no earlier mutation of this third record.
            await enqueue(client, 3, later)
            await await_cache(client, later)
            observations.append((time.monotonic() - started) * 1000.0)
            await await_cache(client, slow)
        finally:
            service.stop()
            await asyncio.wait_for(writer, timeout=3)
        assert executor.peak_batches <= service.concurrency
        assert await redis_manager.client.xlen(client.STREAM_KEY) == 0
        assert not service._identity_tails and not service._lane_tails

    print(
        json.dumps(
            {
                "scheduler": scheduler,
                "transport": type(redis_manager.client).__name__,
                "independent_refill_latency_ms": observations,
                "mean_ms": sum(observations) / len(observations),
                "scope": "synthetic batch delays; no PostgreSQL or upstream work",
            }
        )
    )
