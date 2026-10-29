"""Keep ramp/drain and missing instrumentation out of steady CPU/SQL claims."""

import pytest
from mps_claim_metrics import claim_station_metrics, handler_capacity_model


def test_claim_cpu_driver_and_status_use_same_half_open_window():
    worker = {
        "claim_spans": [(0, 1, 100), (1, 2, 100), (3, 3.5, 0), (4, 5, 100)],
        "claim_details": [
            {"started": 0, "finished": 1, "tasks": 100,
             "thread_cpu_seconds": 9, "queries": {"select": {"calls": 1, "seconds": 9}}},
            {"started": 1, "finished": 2, "tasks": 100,
             "thread_cpu_seconds": 0.3, "queries": {"select": {"calls": 2, "seconds": 0.6}}},
            {"started": 4, "finished": 5, "tasks": 100,
             "thread_cpu_seconds": 9, "queries": {"select": {"calls": 1, "seconds": 9}}},
        ],
        "status_spans": [(0, 1), (1.5, 2), (4, 5)],
        "runtime_samples": [
            {"at": 0, "cpu_seconds": 0}, {"at": 2, "cpu_seconds": 10},
            {"at": 4, "cpu_seconds": 11}, {"at": 6, "cpu_seconds": 30},
        ],
    }
    result = claim_station_metrics([worker], 1.5, 5)
    assert result["steady_claim_calls"] == 2
    assert result["steady_claim_empty_calls"] == 1
    assert result["steady_claim_page_mean"] == 100
    assert result["claim_transaction_mean_ms"] == 1000
    assert result["claim_thread_cpu_mean_ms"] == pytest.approx(300)
    assert result["claim_driver_mean_ms"] == pytest.approx(600)
    assert result["claim_driver_stations"]["select"]["calls"] == 2
    assert result["worker_cpu_cores"] == 0.5
    assert result["steady_worker_status_calls"] == 1
    assert result["steady_worker_status_mean_ms"] == 500


def test_missing_old_instrumentation_stays_unknown_instead_of_zero():
    result = claim_station_metrics([{"claim_spans": [(1, 2, 100)]}], 0, 3)
    assert result["claim_transaction_mean_ms"] == 1000
    assert result["claim_thread_cpu_mean_ms"] is None
    assert result["claim_driver_mean_ms"] is None
    assert result["worker_cpu_cores"] is None
    assert result["worker_cpu_cores_by_process"] == [None]


def test_partial_worker_cpu_is_not_reported_as_whole_runtime_cpu():
    result = claim_station_metrics([
        {"runtime_samples": [{"at": 1, "cpu_seconds": 1}, {"at": 2, "cpu_seconds": 2}]},
        {},
    ], 0, 3)
    assert result["worker_cpu_cores"] is None
    assert result["worker_cpu_cores_by_process"] == [1, None]
    assert result["claim_transaction_mean_ms"] is None


def test_fetch_model_includes_long_tasks_crossing_steady_completion_boundary():
    inputs = [{"handler_ms": 1000}] * 9 + [{"handler_ms": 21000}]
    result = handler_capacity_model(inputs, 300)
    assert result["handler_workload_mean_seconds"] == 3
    assert result["modeled_fetch_ceiling_tasks_per_s"] == 100
    assert "not an independently measured" in result["fetch_ceiling_scope"]


def test_missing_fetch_budget_does_not_invent_a_capacity_denominator():
    result = handler_capacity_model([{"handler_ms": 1000}], None)
    assert result["modeled_fetch_ceiling_tasks_per_s"] is None
