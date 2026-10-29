"""Opt-in full planner comparison; only the owned PostgreSQL fixture is used."""

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
    os.environ.get("USR_BENCH_LEDGER_WINDOW_AGGREGATE") != "1",
    reason="set USR_BENCH_LEDGER_WINDOW_AGGREGATE=1 for the private planner comparison",
)
@pytest.mark.parametrize("order", ["before_first", "after_first"])
def test_full_window_accounting_comparison(ledger, ledger_engine, monkeypatch, order):
    path = Path(os.environ.get("USR_LEDGER_WINDOW_BASELINE_SOURCE", ""))
    if not path.is_file():
        pytest.skip("a pre-repair ledger source snapshot is required")
    name = "ultima_scraper_backend.job_system._window_benchmark_baseline"
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
    job = Job.create(name="Owned archive benchmark", created_by="test", tasks=[])
    job.job_id = "job-archive-bench"
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
        target_user_ids=list(range(1, 20001)),
        proxy_pool=proxies,
        proxy_geo_map=geo,
        candidate_offset=0,
    )
    rows = []
    for ordinal, task in enumerate(tasks):
        task.state = TaskState.COMPLETED if ordinal < 19100 else TaskState.RUNNING
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
    labels = ["before", "after"] if order == "before_first" else ["after", "before"]
    for label in labels:
        observations, samples, accounting_rows = [], [], []
        for repeat in range(8):
            with ledger_engine.connect() as connection:
                outer = connection.begin()

                @contextmanager
                def sessions():
                    with Session(
                        connection, join_transaction_mode="create_savepoint"
                    ) as session:
                        yield session

                executor_type = (
                    baseline.ExecutionLedger if label == "before" else ExecutionLedger
                )
                executor = executor_type(
                    sessions,
                    limits=Limits(
                        tasks=20000,
                        global_tasks=20000,
                        bytes=64 * 1024 * 1024,
                        global_bytes=64 * 1024 * 1024,
                        batch=128,
                        planner_batch=512,
                    ),
                )
                sql = []

                def executed(
                    conn, cursor, statement, parameters, context, many, sql=sql
                ):
                    if (
                        statement.startswith("SELECT")
                        and "execution_work.payload_bytes" in statement
                        and "FOR UPDATE" not in statement
                    ):
                        sql.append(cursor.rowcount)

                event.listen(connection, "after_cursor_execute", executed)
                start = time.perf_counter()
                try:
                    diagnostic = []
                    assert executor.tick(diagnostics=diagnostic) == job.job_id
                    elapsed = time.perf_counter() - start
                    assert diagnostic[-1]["archived_tasks"] == 512
                    assert diagnostic[-1]["admitted_tasks"] == 512
                    assert diagnostic[-1]["controls"]["resident_tasks"] == 20000
                    if label == "after":
                        assert (
                            diagnostic[-1]["controls"]["terminal_resident_tasks"]
                            == 18588
                        )
                    assert sql == ([19488, 1] if label == "before" else [1])
                finally:
                    event.remove(connection, "after_cursor_execute", executed)
                    outer.rollback()
                if repeat >= 2:
                    samples.append(elapsed)
                    observations.append(diagnostic[-1])
                    accounting_rows.append(sum(sql))
        output[label] = {
            "measured_passes": len(samples),
            "mean_tick_ms": statistics.mean(samples) * 1000,
            "mean_archive_ms": statistics.mean(
                row["archive_ms"] for row in observations
            ),
            "mean_refill_ms": statistics.mean(row["refill_ms"] for row in observations),
            "admissions_per_second": 512 / statistics.mean(samples),
            "window_rows_transferred_per_pass": statistics.mean(accounting_rows),
        }
    print(
        json.dumps(
            {
                "order": order,
                "resident_tasks": 20000,
                "terminal_tasks": 19100,
                "page_tasks": 512,
                "routes": 1656,
                "results": output,
                "scope": "native full archive/refill transaction; identical rollback windows; no active workers, upstream, writer or production archive history",
            }
        )
    )
