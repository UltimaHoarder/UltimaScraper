"""Opt-in paired begin-hook timing on a private native PostgreSQL cluster."""

import importlib.util
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import event, text
from test_postgres_transaction_setup import manager_factory, postgres_engine
from ultima_scraper_backend.database.managers import postgres_manager

__all__ = ["manager_factory", "postgres_engine"]


@pytest.mark.skipif(
    os.environ.get("USR_BENCH_TRANSACTION_SETUP") != "1",
    reason="set USR_BENCH_TRANSACTION_SETUP=1 for the native setup comparison",
)
@pytest.mark.parametrize("order", ["before_after", "after_before"])
@pytest.mark.parametrize("read_only", [False, True])
def test_native_transaction_setup_comparison(
    manager_factory, monkeypatch, order, read_only
):
    source = os.environ.get("USR_TRANSACTION_SETUP_BASELINE_SOURCE")
    if not source or not Path(source).is_file():
        pytest.skip("a local pre-repair manager source snapshot is required")
    name = "ultima_scraper_backend.database.managers._transaction_setup_baseline"
    spec = importlib.util.spec_from_file_location(name, source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "runtime_env_value", postgres_manager.runtime_env_value)
    concurrency, per_worker = 8, 32
    role = "application" if read_only else "writer"
    after = manager_factory(role=role, read_only=read_only, concurrency=concurrency)
    with monkeypatch.context() as scoped:
        scoped.setattr(
            postgres_manager,
            "PostgreSQLDatabaseManager",
            module.PostgreSQLDatabaseManager,
        )
        before = manager_factory(
            role=role, read_only=read_only, concurrency=concurrency
        )
    managers = {"before": before, "after": after}
    observations = {}

    def run(manager, barrier, repetitions):
        samples = []
        barrier.wait(timeout=10)
        for _ in range(repetitions):
            started = time.perf_counter()
            with manager.get_session() as session:
                session.connection()
                checkout = (time.perf_counter() - started) * 1000.0
                result = session.execute(
                    text("SELECT :value, current_setting('transaction_read_only')"),
                    {"value": 123},
                ).one()
                assert tuple(result) == (123, "on" if read_only else "off")
                session.commit()
            samples.append((checkout, (time.perf_counter() - started) * 1000.0))
        return samples

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        # Populate the same bounded eight-connection pools before either window.
        for manager in managers.values():
            barrier = threading.Barrier(concurrency)
            futures = [
                pool.submit(run, manager, barrier, 2) for _ in range(concurrency)
            ]
            for future in futures:
                future.result(timeout=10)
        for label in order.split("_"):
            manager = managers[label]
            setup_calls = 0
            lock = threading.Lock()

            def executed(conn, cursor, statement, parameters, context, many, lock=lock):
                nonlocal setup_calls
                if statement.startswith("SET "):
                    with lock:
                        setup_calls += 1

            event.listen(manager.engine, "after_cursor_execute", executed)
            started = time.perf_counter()
            try:
                barrier = threading.Barrier(concurrency)
                futures = [
                    pool.submit(run, manager, barrier, per_worker)
                    for _ in range(concurrency)
                ]
                samples = [
                    sample for future in futures for sample in future.result(timeout=20)
                ]
                window = time.perf_counter() - started
            finally:
                event.remove(manager.engine, "after_cursor_execute", executed)
            observations[label] = {
                "mean_checkout_ms": sum(sample[0] for sample in samples) / len(samples),
                "mean_transaction_ms": sum(sample[1] for sample in samples)
                / len(samples),
                "window_seconds": window,
                "setup_driver_calls": setup_calls,
            }
    count = concurrency * per_worker
    assert observations["before"]["setup_driver_calls"] == count * (
        5 if read_only else 4
    )
    assert observations["after"]["setup_driver_calls"] == count
    print(
        json.dumps(
            {
                "order": order,
                "read_only": read_only,
                "transactions_per_window": count,
                "concurrency": concurrency,
                "observations": observations,
                "scope": "native pooled transaction setup, parameterized SELECT and commit; excludes PgBouncer, writer operations, receipts, queue and upstream",
            }
        )
    )
