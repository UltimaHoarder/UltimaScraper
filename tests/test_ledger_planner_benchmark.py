"""Opt-in archive/refill comparison on an owned PostgreSQL cluster."""

import importlib.util
import json
import os
import statistics
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from test_execution_ledger import ledger, ledger_engine, postgres_engine
from ultima_scraper_backend.job_system import mps_tasks
from ultima_scraper_backend.job_system.ledger import ExecutionLedger, Limits, Work
from ultima_scraper_backend.job_system.models import Job, TaskResult, TaskState

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


@pytest.mark.skipif(
    os.environ.get("USR_BENCH_LEDGER_PLANNER") != "1",
    reason="set USR_BENCH_LEDGER_PLANNER=1 for the owned archive/refill comparison",
)
@pytest.mark.parametrize("order", ["before_first", "after_first"])
def test_native_planner_comparison(ledger, ledger_engine, monkeypatch, order):
    path = Path(os.environ.get("USR_LEDGER_PLANNER_BASELINE_SOURCE", ""))
    if not path.is_file():
        pytest.skip("a local pre-repair ledger source snapshot is required")
    name = "ultima_scraper_backend.job_system._planner_benchmark_baseline"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[name] = baseline
    spec.loader.exec_module(baseline)
    proxies = [f"http://route-{index}.invalid:8080" for index in range(1656)]
    geo = {
        proxy: ("US", "GB", "DE", "JP")[index % 4]
        for index, proxy in enumerate(proxies)
    }
    monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP", geo)
    monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP_AT", time.monotonic())
    job = Job.create(name="Owned planner benchmark", created_by="test", tasks=[])
    job.job_id = "job-planner-bench"
    ledger.manifests.create(
        job_id=job.job_id,
        site="onlyfans",
        job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": 100000, "max_profiles": None},
        proxy_pool=proxies,
        site_session_factory=ledger.session_factory,
    )
    tasks = mps_tasks._build_mps_task_batch(
        job_id=job.job_id,
        site_display="OnlyFans",
        target_user_ids=list(range(1, 5621)),
        proxy_pool=proxies,
        proxy_geo_map=geo,
        candidate_offset=0,
    )
    rows = []
    for ordinal, task in enumerate(tasks):
        task.state = TaskState.COMPLETED if ordinal < 4500 else TaskState.RUNNING
        if task.state == TaskState.COMPLETED:
            task.result = TaskResult(success=True, metrics={"items_saved": 1})
            task.completed_at = task.result.completed_at
        payload = json.dumps(task.to_dict(), separators=(",", ":"))
        rows.append(
            {
                "run_id": job.job_id,
                "task_id": task.task_id,
                "candidate": ordinal,
                "state": task.state.value,
                "site": "onlyfans",
                "lane": "scrape",
                "capabilities": ["onlyfans"],
                "dedup_key": task.dedup_key,
                "payload_json": payload,
                "payload_bytes": len(payload),
            }
        )
    with ledger.session_factory() as session:
        session.add_all(Work(**row) for row in rows)
        session.commit()
    output = {}
    labels = ["before128", "after128", "after512"]
    if order == "after_first":
        labels.reverse()
    for label in labels:
        observations, statements, samples, windows = [], [], [], []
        size = 512 if label == "after512" else 128
        limit = Limits(
            tasks=20000,
            global_tasks=20000,
            bytes=64 * 1024 * 1024,
            global_bytes=64 * 1024 * 1024,
            batch=128,
            planner_batch=size,
        )
        executor_type = (
            baseline.ExecutionLedger if label == "before128" else ExecutionLedger
        )
        for repeat in range(10):
            with ledger_engine.connect() as connection:
                outer = connection.begin()

                @contextmanager
                def sessions():
                    with Session(
                        connection, join_transaction_mode="create_savepoint"
                    ) as session:
                        yield session

                executor = executor_type(sessions, limits=limit)
                recorded = []

                def executed(
                    conn,
                    cursor,
                    statement,
                    parameters,
                    context,
                    many,
                    recorded=recorded,
                ):
                    recorded.append(statement)

                event.listen(connection, "after_cursor_execute", executed)
                started = time.perf_counter()
                try:
                    measurement = []
                    assert executor.tick(diagnostics=measurement) == job.job_id
                    elapsed = time.perf_counter() - started
                    assert measurement[-1]["admitted_tasks"] == size
                    assert measurement[-1]["archived_tasks"] == size
                finally:
                    event.remove(connection, "after_cursor_execute", executed)
                    outer.rollback()
                    window = time.perf_counter() - started
                if repeat >= 2:
                    observations.append(measurement[-1])
                    statements.append(len(recorded))
                    samples.append(elapsed)
                    windows.append(window)
        output[label] = {
            "tasks_per_pass": size,
            "measured_passes": len(samples),
            "mean_tick_ms": statistics.mean(samples) * 1000,
            "mean_window_ms_including_rollback": statistics.mean(windows) * 1000,
            "admission_capacity_per_second": size / statistics.mean(samples),
            "mean_driver_calls": statistics.mean(statements),
            "mean_archive_ms": statistics.mean(
                row["archive_ms"] for row in observations
            ),
            "mean_refill_ms": statistics.mean(row["refill_ms"] for row in observations),
        }
    print(
        json.dumps(
            {
                "order": order,
                "resident_tasks": 5620,
                "terminal_tasks": 4500,
                "route_pool_size": len(proxies),
                "window_tasks": 20000,
                "results": output,
                "scope": "native full planner transaction with archive and refill; rollback keeps identical evidence; no active workers, writer, upstream or historical production archive",
            }
        )
    )
