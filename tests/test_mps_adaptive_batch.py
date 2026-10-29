from __future__ import annotations

import math
import pytest
from ultima_scraper_backend.api.routes.mps import (
    calculate_adaptive_batch_size,
    _build_batch_plan,
)


def test_adaptive_batch_size_core_densities() -> None:
    # 100% missing -> 5,000
    assert calculate_adaptive_batch_size(
        total_ids=10_000,
        missing_count=10_000,
        candidate_count=10_000,
    ) == 5_000

    # 50% missing -> 10,000
    assert calculate_adaptive_batch_size(
        total_ids=10_000,
        missing_count=5_000,
        candidate_count=5_000,
    ) == 10_000

    # 25% missing -> 20,000
    assert calculate_adaptive_batch_size(
        total_ids=10_000,
        missing_count=2_500,
        candidate_count=2_500,
    ) == 20_000

    # 10% missing -> 50,000
    assert calculate_adaptive_batch_size(
        total_ids=10_000,
        missing_count=1_000,
        candidate_count=1_000,
    ) == 50_000

    # 1% missing -> 500,000
    assert calculate_adaptive_batch_size(
        total_ids=100_000,
        missing_count=1_000,
        candidate_count=1_000,
    ) == 500_000


def test_adaptive_batch_size_monotonic_inverse_scaling() -> None:
    total_ids = 1_000_000
    densities = [1.0, 0.8, 0.5, 0.25, 0.1, 0.05, 0.02, 0.01, 0.005]
    previous = 0

    for d in densities:
        missing = int(total_ids * d)
        rec = calculate_adaptive_batch_size(
            total_ids=total_ids,
            missing_count=missing,
            candidate_count=missing,
        )
        assert rec >= previous
        previous = rec


def test_adaptive_batch_size_limits_and_clamping() -> None:
    # Very low density clamped to default max recommendation (1,000,000)
    assert calculate_adaptive_batch_size(
        total_ids=100_000_000,
        missing_count=10,
        candidate_count=10,
    ) == 1_000_000

    # Minimum never drops below base_batch_size (5,000)
    assert calculate_adaptive_batch_size(
        total_ids=10_000,
        missing_count=10_000,
        candidate_count=10_000,
    ) == 5_000

    # Custom base_batch_size and max_recommendation
    assert calculate_adaptive_batch_size(
        total_ids=10_000,
        missing_count=5_000,
        candidate_count=5_000,
        base_batch_size=2_000,
        max_recommendation=50_000,
    ) == 4_000


def test_adaptive_batch_size_edge_cases() -> None:
    # Zero candidates -> 0
    assert calculate_adaptive_batch_size(
        total_ids=10_000,
        missing_count=0,
        candidate_count=0,
    ) == 0

    # Zero total IDs -> 0
    assert calculate_adaptive_batch_size(
        total_ids=0,
        missing_count=0,
        candidate_count=0,
    ) == 0

    # Zero missing IDs but invalid candidates enabled -> fallback to candidate density
    # 500 / 10,000 = 5% candidate density -> ceil(5,000 / 0.05) = 100,000
    assert calculate_adaptive_batch_size(
        total_ids=10_000,
        missing_count=0,
        candidate_count=500,
        include_missing=True,
    ) == 100_000

    # Missing IDs explicitly excluded by user -> fallback to candidate density
    # 1,000 / 100,000 = 1% candidate density -> ceil(5,000 / 0.01) = 500,000
    assert calculate_adaptive_batch_size(
        total_ids=100_000,
        missing_count=50_000,
        candidate_count=1_000,
        include_missing=False,
    ) == 500_000


def test_build_batch_plan_includes_adaptive_batch_size() -> None:
    plan = _build_batch_plan(
        candidate_count=10_000,
        candidate_offset=0,
        requested_batch_size=50_000,
        range_size=100_000,
        invalid_table_ready=True,
        include_invalid=False,
        invalid_last_checked_older_than_hours=None,
        include_existing_users=False,
        existing_last_checked_older_than_hours=None,
        missing_count=10_000,
        include_missing=True,
    )

    # 10,000 / 100,000 = 10% density -> 50,000 adaptive recommendation
    assert plan.adaptive_batch_size == 50_000
    # But actual planned_candidate_count is clamped to remaining candidates (10,000)
    assert plan.planned_candidate_count == 10_000
    assert plan.remaining_candidate_count == 10_000
    assert plan.has_next_batch is False


def test_adaptive_batch_size_dynamic_route_scaling() -> None:
    # 1 route: 50% missing -> 10,000
    assert calculate_adaptive_batch_size(
        total_ids=10_000,
        missing_count=5_000,
        candidate_count=5_000,
        routes=1,
    ) == 10_000

    # 10 routes: 50% missing -> 100,000 (10x base)
    assert calculate_adaptive_batch_size(
        total_ids=10_000,
        missing_count=5_000,
        candidate_count=5_000,
        routes=10,
    ) == 100_000

    # Large fleet: 107 routes at 31.02% missing density -> 1,724,725
    assert calculate_adaptive_batch_size(
        total_ids=598_973_341,
        missing_count=185_798_165,
        candidate_count=185_798_165,
        routes=107,
    ) == 1_724_725

    # Max cap scales with routes: 5 routes * 1,000,000 = 5,000,000
    assert calculate_adaptive_batch_size(
        total_ids=100_000_000,
        missing_count=10,
        candidate_count=10,
        routes=5,
    ) == 5_000_000


def test_build_batch_plan_scales_with_routes() -> None:
    plan = _build_batch_plan(
        candidate_count=500_000,
        candidate_offset=0,
        requested_batch_size=None,
        range_size=100_000,
        invalid_table_ready=True,
        include_invalid=False,
        invalid_last_checked_older_than_hours=None,
        include_existing_users=False,
        existing_last_checked_older_than_hours=None,
        missing_count=10_000,
        include_missing=True,
        routes=10,
    )

    # 10,000 / 100,000 = 10% density * 10 routes -> 500,000 adaptive recommendation
    assert plan.adaptive_batch_size == 500_000
