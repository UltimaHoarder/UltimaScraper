"""Opt-in paired native SQL comparison; never uses deployment databases."""

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
from test_writer_invalid_user_batch import (
    invalid_command,
    invalid_runtime,
    postgres_engine,
)

__all__ = ["invalid_runtime", "postgres_engine"]


@pytest.mark.skipif(
    os.environ.get("USR_BENCH_INVALID_BATCH") != "1",
    reason="set USR_BENCH_INVALID_BATCH=1 for the native transaction comparison",
)
@pytest.mark.parametrize("order", ["before_after", "after_before"])
@pytest.mark.parametrize("row_state", ["insert", "update"])
def test_native_invalid_batch_comparison(invalid_runtime, order, row_state):
    set_source = os.environ.get("USR_INVALID_SET_BASELINE_SOURCE")
    source = set_source or os.environ.get("USR_INVALID_BASELINE_SOURCE")
    if not source or not Path(source).is_file():
        pytest.skip("a local pre-repair executor source snapshot is required")
    name = "ultima_scraper_backend.database._invalid_batch_benchmark_baseline"
    spec = importlib.util.spec_from_file_location(name, source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    baseline = module.PostgreSQLWriteExecutor.__new__(module.PostgreSQLWriteExecutor)
    baseline._site_manager = invalid_runtime.executor._site_manager
    executors = {"before": baseline, "after": invalid_runtime.executor}
    batch_size, concurrency, rounds = 30, 8, 3
    command_count = batch_size * concurrency * rounds
    observations = {}

    def execute(executor, commands):
        started = time.perf_counter()
        outcomes = executor._upsert_invalid_users(commands, "onlyfans")
        assert len(outcomes) == len(commands)
        assert all(outcome["upserted"] for outcome in outcomes.values())
        return (time.perf_counter() - started) * 1000.0

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        # Warm both statement paths before either timed window.
        for label, executor in executors.items():
            execute(executor, [invalid_command(f"warm-{label}", 999_999)])
        for label in order.split("_"):
            executor = executors[label]
            with invalid_runtime.session() as session:
                session.execute(
                    text("TRUNCATE invalid_users,management.database_write_receipts")
                )
                if row_state == "update":
                    session.execute(
                        text(
                            "INSERT INTO invalid_users(site,user_id,reason) "
                            "SELECT 'onlyfans',id,'old' FROM generate_series(1,:count) AS id"
                        ),
                        {"count": command_count},
                    )
                session.commit()

            mutation_calls = 0
            counter_lock = threading.Lock()

            def executed(
                conn, cursor, statement, parameters, context, many, lock=counter_lock
            ):
                nonlocal mutation_calls
                if "invalid_users" in statement:
                    with lock:
                        mutation_calls += 1

            event.listen(invalid_runtime.engine, "after_cursor_execute", executed)
            batch_times = []
            cpu_started = time.process_time()
            started = time.perf_counter()
            try:
                for trial in range(rounds):
                    batches = []
                    for slot in range(concurrency):
                        offset = (trial * concurrency + slot) * batch_size
                        commands = [
                            invalid_command(f"{label}-{offset + i}", offset + i + 1)
                            for i in range(batch_size)
                        ]
                        batches.append(pool.submit(execute, executor, commands))
                    batch_times.extend(batch.result(timeout=10) for batch in batches)
                window = time.perf_counter() - started
                process_cpu = time.process_time() - cpu_started
            finally:
                event.remove(invalid_runtime.engine, "after_cursor_execute", executed)
            with invalid_runtime.session() as session:
                assert (
                    session.execute(
                        text("SELECT count(*) FROM invalid_users")
                    ).scalar_one()
                    == command_count
                )
                assert (
                    session.execute(
                        text("SELECT count(*) FROM management.database_write_receipts")
                    ).scalar_one()
                    == command_count
                )
            observations[label] = {
                "mean_batch_ms": sum(batch_times) / len(batch_times),
                "window_seconds": window,
                "process_cpu_seconds": process_cpu,
                "invalid_user_sql_calls": mutation_calls,
            }
    expected_before_calls = concurrency * rounds if set_source else command_count * 2
    assert observations["before"]["invalid_user_sql_calls"] == expected_before_calls
    assert observations["after"]["invalid_user_sql_calls"] == concurrency * rounds
    print(
        json.dumps(
            {
                "order": order,
                "row_state": row_state,
                "commands": command_count,
                "batch_size": batch_size,
                "concurrency": concurrency,
                "observations": observations,
                "scope": "native SQL and committed receipts; no Redis, attempt fences or upstream",
            }
        )
    )
