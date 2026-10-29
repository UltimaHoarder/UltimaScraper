"""Deployment allocation includes standby, per-site and dedicated owners."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "connection_budget", Path(__file__).resolve().parents[1] / "scripts/performance/connection_budget.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_combined_budget_preserves_writer_and_advisory_allocations():
    backends = [{"id": identity, "owners": [
        {"name": "writer", "role": "writer", "processes": 1,
         "engines_per_process": 4, "pool_size": 4},
        {"name": "management", "role": "worker_reader", "processes": 5,
         "pool_mode": "transaction", "pool_size": 2},
        {"name": "site readers", "role": "worker_reader", "processes": 4,
         "pool_mode": "transaction", "site_reader": True},
        {"name": "migration", "role": "advisory_lock", "processes": 1,
         "pool_mode": "session", "pool_size": 1},
    ]} for identity in ("pi-api", "pi-workers")]
    result = module.calculate({"backends": backends, "reserved_connections": 5, "allocation_limit": 58})
    assert result["allocated_clients"] == 59
    assert result["within_allocation_limit"] is False
    for backend in backends:
        backend["owners"][1]["pool_mode"] = "session"
    result = module.calculate({"backends": backends})
    assert result["allocated_clients"] == 34
    assert sum(row["transient_nullpool_demand_excluded"] for row in result["owners"]) == 4


def test_duplicate_backends_and_transaction_pooled_session_locks_are_rejected():
    backend = {"id": "pi", "owners": []}
    with pytest.raises(ValueError, match="unique"):
        module.calculate({"backends": [backend, backend]})
    backend["owners"] = [{"name": "lock", "role": "advisory_lock", "processes": 1, "pool_mode": "transaction"}]
    with pytest.raises(ValueError, match="dedicated"):
        module.calculate({"backends": [backend]})
