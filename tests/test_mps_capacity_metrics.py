"""Boundary regressions: avoid overcounting ramp/drain or sampled gaps."""

import pytest
from mps_capacity_metrics import (
    configured_worker_budgets,
    interval_occupancy,
    sampled_mean,
)


def test_occupancy_clips_spanning_tasks_and_half_open_boundaries():
    assert interval_occupancy([(-2, 3), (3, 6), (2, 4), (7, 8)], 0, 6) == {
        "mean": 8 / 6,
        "max": 2,
    }


def test_sampled_mean_weights_intervals_instead_of_samples():
    samples = [{"at": 0, "ready": 0}, {"at": 1, "ready": 10}, {"at": 5, "ready": 0}]
    assert sampled_mean(samples, "ready", 0, 6) == pytest.approx(40 / 6)
    assert sampled_mean(samples, "ready", 2, 4) == 10
    assert sampled_mean([], "ready", 2, 4) is None


def test_worker_budgets_follow_recorded_topology_and_do_not_invent_old_capacity():
    assert configured_worker_budgets([
        {"configured_fetch_slots": 80, "configured_persistence_slots": 80},
        {"configured_fetch_slots": 300, "configured_persistence_slots": 100},
    ]) == (380, 560)
    assert configured_worker_budgets([{}]) == (None, None)
    with pytest.raises(ValueError, match="Invalid recorded"):
        configured_worker_budgets([
            {"configured_fetch_slots": 0, "configured_persistence_slots": 100}
        ])
