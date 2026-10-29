"""Opt-in paired receipt entry timing, with native locks and attempt fences."""

import importlib.util
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, insert
from sqlmodel import Session
from test_writer_receipt_lookup import (
    command,
    ledger,
    ledger_engine,
    owned_batch,
    postgres_engine,
    receipt_row,
)
from ultima_scraper_backend.database import write_receipts
from ultima_scraper_db_archive.execution_models import ExecutionMutationModel
from ultima_scraper_db_archive.global_db import DatabaseWriteReceiptModel

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


@pytest.mark.skipif(
    os.environ.get("USR_BENCH_RECEIPT_LOOKUP") != "1",
    reason="set USR_BENCH_RECEIPT_LOOKUP=1 for native receipt comparisons",
)
@pytest.mark.parametrize("order", ["before_after", "after_before"])
@pytest.mark.parametrize("state", ["fresh", "mixed", "replay"])
def test_native_receipt_lookup_comparison(ledger, ledger_engine, order, state):
    source = os.environ.get("USR_RECEIPT_LOOKUP_BASELINE_SOURCE")
    if not source or not Path(source).is_file():
        pytest.skip("a local pre-repair receipt source snapshot is required")
    name = "ultima_scraper_backend.database._receipt_lookup_benchmark_baseline"
    spec = importlib.util.spec_from_file_location(name, source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    concurrency, batch_size, repetitions = 8, 32, 16
    owned = owned_batch(ledger, batch_size)
    batches = [
        [
            replace(
                command(item),
                command_id=f"lookup-{slot}-{index}",
                execution_key=f"save-{slot}",
            )
            for index, item in enumerate(owned)
        ]
        for slot in range(concurrency)
    ]
    mutations, receipts = [], []
    for batch in batches:
        for index, item in enumerate(batch):
            if state == "fresh" or (state == "mixed" and index % 2):
                continue
            old_id = f"old-{item.command_id}"
            mutations.append(
                {
                    "run_id": item.execution_attempt["run_id"],
                    "task_id": item.execution_attempt["task_id"],
                    "mutation_key": item.execution_key,
                    "command_id": old_id,
                }
            )
            receipts.append(receipt_row(old_id, payload={"saved": True}))
    if mutations:
        with ledger.session_factory() as session:
            session.execute(insert(DatabaseWriteReceiptModel), receipts)
            session.execute(insert(ExecutionMutationModel), mutations)
            session.commit()
    # Give both paths the same fixed eight-connection SQL budget.
    engine = create_engine(ledger_engine.url, pool_size=concurrency, max_overflow=0)
    paths = {"before": module.receipt_batch, "after": write_receipts.receipt_batch}
    samples_by_path = {}
    local = threading.local()

    def run(path, batch, barrier, count):
        samples = []
        barrier.wait(timeout=10)
        for _ in range(count):
            with Session(engine) as session:
                # Pool/dialect initialization is outside the lookup span.
                session.connection()
                results = {}
                local.lookup = True
                started = time.perf_counter()
                try:
                    with path(session, batch, results) as pending:
                        elapsed = (time.perf_counter() - started) * 1000.0
                        local.lookup = False
                        expected = (
                            batch
                            if state == "fresh"
                            else ([] if state == "replay" else batch[1::2])
                        )
                        assert pending == expected
                        for item in pending:
                            results[item.command_id] = {"saved": True}
                    assert results == {
                        item.command_id: {"saved": True} for item in batch
                    }
                    samples.append(elapsed)
                finally:
                    local.lookup = False
                    # Exercise receipt staging, but retain only the seeded
                    # history between repeats so both orders see identical data.
                    session.rollback()
        return samples

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for path in paths.values():
                barrier = threading.Barrier(concurrency)
                futures = [
                    pool.submit(run, path, batch, barrier, 1) for batch in batches
                ]
                for future in futures:
                    future.result(timeout=20)
            for label in order.split("_"):
                lookup_calls = 0
                lock = threading.Lock()

                def executed(
                    conn, cursor, statement, parameters, context, many, lock=lock
                ):
                    nonlocal lookup_calls
                    if getattr(local, "lookup", False):
                        with lock:
                            lookup_calls += 1

                event.listen(engine, "after_cursor_execute", executed)
                started = time.perf_counter()
                try:
                    barrier = threading.Barrier(concurrency)
                    futures = [
                        pool.submit(run, paths[label], batch, barrier, repetitions)
                        for batch in batches
                    ]
                    samples = [
                        sample
                        for future in futures
                        for sample in future.result(timeout=30)
                    ]
                    window = time.perf_counter() - started
                finally:
                    event.remove(engine, "after_cursor_execute", executed)
                samples_by_path[label] = {
                    "mean_receipt_entry_ms": sum(samples) / len(samples),
                    "window_seconds": window,
                    "receipt_entry_driver_calls": lookup_calls,
                }
    finally:
        engine.dispose()
    batch_count = concurrency * repetitions
    before_calls = 3 if state == "replay" else 6
    assert (
        samples_by_path["before"]["receipt_entry_driver_calls"]
        == batch_count * before_calls
    )
    assert samples_by_path["after"]["receipt_entry_driver_calls"] == batch_count * (
        before_calls - 1
    )
    print(
        json.dumps(
            {
                "order": order,
                "state": state,
                "batch_size": batch_size,
                "batches_per_window": batch_count,
                "concurrency": concurrency,
                "observations": samples_by_path,
                "scope": "native receipt lookup entry with advisory locks and attempt fences; window also includes staged receipts and rollback, no writer mutation, Redis or upstream",
            }
        )
    )
