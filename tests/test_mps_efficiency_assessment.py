"""Measurement boundaries that could otherwise inflate reported efficiency."""

import importlib.util
from pathlib import Path

import pytest

_path = Path(__file__).parents[1] / "scripts/performance/assess_mps_efficiency.py"
_spec = importlib.util.spec_from_file_location("mps_efficiency", _path)
assessment = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(assessment)


def test_window_uses_preceding_sample_and_weights_elapsed_time():
    samples = [{"timestamp_ms": 0, "ready": 0}, {"timestamp_ms": 1000, "ready": 10}, {"timestamp_ms": 5000, "ready": 0}]
    result = assessment.held_samples(samples, "ready", 2000, 6000)
    assert result["mean"] == 7.5
    assert result["coverage_ratio"] == 1
    assert result["longest_held_interval_ms"] == 3000


def test_missing_observation_is_not_invented_or_scored_as_zero():
    result = assessment.held_samples([{"timestamp_ms": 3000, "ready": 10}], "ready", 2000, 6000)
    assert result["mean"] == 10
    assert result["coverage_ratio"] == 0.75
    assert assessment.held_samples([], "ready", 0, 1000)["mean"] is None


def test_repeated_polls_do_not_weight_the_same_runtime_sample_twice():
    samples = [{"timestamp_ms": 0, "inflight": 2}] * 4 + [{"timestamp_ms": 1000, "inflight": 4}]
    assert assessment.held_samples(samples, "inflight", 0, 2000)["mean"] == 3


def test_timestamps_require_unambiguous_timezone():
    with pytest.raises(ValueError, match="timezone"):
        assessment.timestamp_ms("2026-10-09T12:00:00")
    assert assessment.timestamp_ms("2026-10-09T12:00:00+00:00") == assessment.timestamp_ms("2026-10-09T13:00:00+01:00")


def test_invalid_observation_window_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        assessment.held_samples([], "ready", 5, 5)


def test_exact_intervals_clip_tasks_crossing_both_window_boundaries():
    spans = [{"started_ms": -1, "finished_ms": 3}, {"started_ms": 2, "finished_ms": 6}, {"started_ms": 6, "finished_ms": 8}]
    assert assessment.interval_mean(spans, 0, 5) == 6 / 5
