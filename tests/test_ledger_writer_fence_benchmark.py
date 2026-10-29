"""Opt-in native SQL fence benchmark; no deployment or external API access."""
# ruff: noqa: F811 - imported pytest fixtures are injected into tests.

import importlib.util
import json
import os
import statistics
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import event
from test_ledger_writer_batch_fences import (  # noqa: F401
    identity,
    ledger,
    ledger_engine,
    owned_batch,
    postgres_engine,
)
from ultima_scraper_backend.job_system.ledger import validate_write_attempts


@pytest.mark.skipif(
    os.getenv("USR_BENCH_WRITER_FENCES") != "1",
    reason="Opt-in native writer fence benchmark",
)
@pytest.mark.parametrize("batch_size", [24, 100])
def test_writer_fence_benchmark(ledger, ledger_engine, batch_size):
    path = Path("/tmp/mps-before-batched-writer-fences-ledger.py")
    if not path.exists():
        pytest.skip("Pre-change source snapshot unavailable")
    name = "ultima_scraper_backend.job_system._writer_fence_baseline"
    spec = importlib.util.spec_from_file_location(name, path)
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[name] = baseline
    spec.loader.exec_module(baseline)
    identities = [identity(item) for item in owned_batch(ledger, batch_size)]
    results = {}
    for mode in ["before", "after"]:
        durations = []
        statements = []

        def counted(
            conn, cursor, statement, parameters, context, many, captured=statements
        ):
            captured.append(statement)

        for sample in range(13):
            with ledger.session_factory() as session:
                event.listen(ledger_engine, "after_cursor_execute", counted)
                started = time.perf_counter()
                try:
                    if mode == "before":
                        for item in identities:
                            baseline.validate_write_attempt(session, item)
                    else:
                        validate_write_attempts(session, identities)
                finally:
                    elapsed = (time.perf_counter() - started) * 1000
                    event.remove(ledger_engine, "after_cursor_execute", counted)
                if sample >= 3:
                    durations.append(elapsed)
        expected = 3 * batch_size if mode == "before" else 3
        assert len(statements) == 13 * expected
        results[mode] = {
            "median_ms": round(statistics.median(durations), 3),
            "mean_ms": round(statistics.mean(durations), 3),
            "statements": expected,
        }
    print("WRITER_FENCE", json.dumps({"batch_size": batch_size, **results}))
