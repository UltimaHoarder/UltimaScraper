"""Opt-in paired archive probe with a populated global identity directory."""

import json
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select, text
from test_mps_archive_identity_directory import (
    ledger,
    ledger_engine,
    optimized_guard_migration,
    postgres_engine,
    repartition,
)
from test_mps_archive_set_inserts import completed_range
from ultima_scraper_backend.database.job_partitions import task_identity_model

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


@pytest.mark.skipif(not os.getenv("USR_BENCH_ARCHIVE_IDENTITIES"), reason="opt-in archive benchmark")
@pytest.mark.parametrize("order", ["before_after_after_before", "after_before_before_after"])
@pytest.mark.parametrize("after_batch", [2048, 512])
def test_archive_identity_paired_benchmark(ledger, ledger_engine, order, after_batch):
    ledger.limits = replace(ledger.limits, bytes=64 * 1024 * 1024,
                            global_bytes=64 * 1024 * 1024, result_bytes=64 * 1024 * 1024)
    job = completed_range(ledger, 8192)
    repartition(ledger_engine)
    migration = optimized_guard_migration()
    ledger.limits = replace(ledger.limits, archive_batch=2048)
    with ledger_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO management.job_tasks(task_id,job_id,task_type,status,site)
            SELECT 'seed-'||md5(i::text),:job,'scrape','completed','onlyfans'
            FROM generate_series(1,100000) AS i
        """), {"job": job})
    original = ledger.manifests._rolling_archive_evidence

    def preflight(session, plan, rows, candidate_ordinals):
        identity = task_identity_model(session)
        owners = session.execute(select(identity.task_id, identity.job_id).where(
            identity.task_id.in_([row["task_id"] for row in rows])
        )).all()
        assert not owners
        return original(session, plan, rows, candidate_ordinals)

    results = []
    try:
        for arm in order.split("_"):
            with ledger_engine.begin() as connection:
                connection.execute(text(migration.PREVIOUS_GUARD if arm == "before" else migration.OPTIMIZED_GUARD))
            ledger.manifests._rolling_archive_evidence = preflight if arm == "before" else original
            batch = 2048 if arm == "before" else after_batch
            ledger.limits = replace(ledger.limits, archive_batch=batch)
            transactions = []
            started = time.perf_counter()
            for _ in range(2048 // batch):
                transaction_started = time.perf_counter()
                assert ledger.archive_tick() == job
                transactions.append(time.perf_counter() - transaction_started)
            results.append({"arm": arm, "seconds": time.perf_counter() - started,
                            "transaction_seconds": transactions, "batch_tasks": batch})
    finally:
        ledger.manifests._rolling_archive_evidence = original
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 108192
        assert session.scalar(text("SELECT count(*) FROM management.job_task_identities")) == 108192
        assert session.scalar(text("SELECT count(*) FROM management.execution_work")) == 0
        assert session.scalar(text("SELECT count(*) FROM management.execution_work_payloads")) == 0
        assert session.scalar(text("SELECT cursor FROM management.mps_plans WHERE job_id=:job"), {"job": job}) == 8192
    output = {"order": order, "history_seed": 100000, "group_tasks": 2048,
              "after_batch": after_batch, "results": results}
    directory = Path(os.environ.get("USR_ARCHIVE_IDENTITY_RESULTS", "/tmp"))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (order + '-' + str(after_batch) + ".json")).write_text(json.dumps(output, indent=2))
    print(json.dumps(output), flush=True)
