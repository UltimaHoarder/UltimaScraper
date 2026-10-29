"""Tests for adaptive user-ID boundary discovery and population estimation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from ultima_scraper_backend.api.routes import mps as mps_module
from ultima_scraper_backend.boundary_discovery import (
    AdaptiveBoundaryDiscoverer,
    BoundaryDiscoveryConfig,
    calculate_german_tank_estimate,
    calculate_highest_id_confidence_interval,
    calculate_wilson_density_and_population,
    discover_user_id_boundaries,
    get_z_score,
    is_adaptive_boundary_discovery_enabled,
)

# ---------------------------------------------------------------------------
# Unit tests for statistical formulas and estimators
# ---------------------------------------------------------------------------


def test_get_z_score() -> None:
    assert get_z_score(0.95) == 1.960
    assert get_z_score(0.99) == 2.576
    assert get_z_score(0.90) == 1.645
    assert get_z_score(0.80) == 1.282


def test_calculate_german_tank_estimate() -> None:
    # Highest observed 1000 from 10 samples in upper bound 2000
    # MVUE: 1000 + (1000 - 10) / 10 = 1000 + 99 = 1099
    est = calculate_german_tank_estimate(highest_observed=1000, k_samples=10, upper_bound=2000)
    assert est == 1099

    # Capped by upper bound
    est_capped = calculate_german_tank_estimate(highest_observed=1000, k_samples=2, upper_bound=1200)
    assert est_capped == 1200

    # No samples or zero
    assert calculate_german_tank_estimate(0, 0, 1000) == 1


def test_calculate_highest_id_confidence_interval() -> None:
    lower, upper = calculate_highest_id_confidence_interval(
        highest_observed=1000, k_samples=10, upper_bound=2000, confidence_level=0.95
    )
    assert lower == 1000
    assert upper >= 1000
    assert upper <= 2000


def test_calculate_wilson_density_and_population() -> None:
    # 50 valid hits out of 100 samples across range size 10,000
    density, moe, pop, (pop_lower, pop_upper) = calculate_wilson_density_and_population(
        total_range_size=10_000,
        valid_count=50,
        sample_count=100,
        confidence_level=0.95,
    )
    assert density == 0.5
    assert moe > 0.0
    assert pop == 5000
    assert pop_lower < 5000
    assert pop_upper > 5000
    assert pop_lower >= 50
    assert pop_upper <= 10_000


# ---------------------------------------------------------------------------
# Unit tests for the discovery algorithm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exponential_probing_and_refinement() -> None:
    # Simulate platform where user IDs exist up to 45,000
    # and 30% of IDs are valid (sparse allocation)
    valid_set = {uid for uid in range(1, 45_001) if uid % 3 == 0}

    async def mock_lookup(user_id: int) -> bool:
        return user_id in valid_set

    config = BoundaryDiscoveryConfig(
        probe_multiplier=10.0,
        min_id=1,
        max_id_ceiling=1_000_000,
        max_probes=60,
        samples_per_step=3,
        refinement_steps=6,
        confidence_level=0.95,
    )

    result = await discover_user_id_boundaries(
        site="OnlyFans",
        lookup_fn=mock_lookup,
        config=config,
    )

    assert result.highest_observed_id is not None
    assert result.highest_observed_id <= 45_000
    assert result.highest_observed_id >= 10_000
    assert result.discovered_end_id >= result.highest_observed_id
    assert result.discovered_end_id <= 100_000
    assert result.discovered_start_id <= result.discovered_end_id
    assert result.estimated_total_users > 0
    assert result.population_confidence_interval[0] <= result.estimated_total_users
    assert result.population_confidence_interval[1] >= result.estimated_total_users
    assert result.total_probes_used <= 60


@pytest.mark.asyncio
async def test_non_sequential_allocation_missing_ids_do_not_halt_search() -> None:
    """A failed lookup must not be treated as proof that higher IDs do not exist."""
    # IDs 1..999 do NOT exist, 1000..1010 do NOT exist,
    # but ID 50,000 and 55,000 DO exist.
    sparse_valid = {5, 50_000, 55_000}

    async def mock_lookup(user_id: int) -> bool:
        return user_id in sparse_valid

    config = BoundaryDiscoveryConfig(
        probe_multiplier=10.0,
        min_id=1,
        max_id_ceiling=1_000_000,
        max_probes=50,
        samples_per_step=3,
        consecutive_empty_brackets=4,
    )

    result = await discover_user_id_boundaries(
        site="Fansly",
        lookup_fn=mock_lookup,
        config=config,
    )

    # Search did NOT halt at missing 10, 100, 1000; it discovered 50,000 or 55,000!
    assert result.highest_observed_id is not None
    assert result.highest_observed_id >= 50_000


@pytest.mark.asyncio
async def test_sparse_hole_decade_does_not_halt_search() -> None:
    """An empty decade with holes must not falsely terminate probing."""
    # Decade 1..10 has ID 1.
    # Decades 10..100 and 100..1000 are completely empty (holes/deletions).
    # Decade 1000..10000 has ID 2000.
    holes_valid = {1, 2000}

    async def mock_lookup(user_id: int) -> bool:
        return user_id in holes_valid

    config = BoundaryDiscoveryConfig(
        probe_multiplier=10.0,
        min_id=1,
        max_id_ceiling=100_000,
        max_probes=40,
        consecutive_empty_brackets=3,  # Needs 3 empty brackets before stopping
    )

    result = await discover_user_id_boundaries(
        site="OnlyFans",
        lookup_fn=mock_lookup,
        config=config,
    )

    assert result.highest_observed_id == 2000
    assert result.discovered_end_id >= 2000


@pytest.mark.asyncio
async def test_adaptive_sampling_population_accuracy() -> None:
    # 5,000 users distributed in 1..10,000 (every even ID is valid -> 50% density)
    async def mock_lookup(user_id: int) -> bool:
        return 1 <= user_id <= 10_000 and user_id % 2 == 0

    config = BoundaryDiscoveryConfig(
        probe_multiplier=10.0,
        min_id=1,
        max_id_ceiling=100_000,
        max_probes=80,
        target_margin_of_error=0.15,
    )

    result = await discover_user_id_boundaries(
        site="OnlyFans",
        lookup_fn=mock_lookup,
        config=config,
    )

    assert result.highest_observed_id is not None
    assert result.highest_observed_id <= 10_000
    # Density should be around 0.5
    assert 0.25 <= result.estimated_density <= 0.75
    # Population should be in the thousands
    assert 2000 <= result.estimated_total_users <= 8000
    assert result.population_confidence_interval[0] <= 5000 <= result.population_confidence_interval[1]


@pytest.mark.asyncio
async def test_configurable_limits_strictly_respected() -> None:
    probes_called = 0

    async def mock_lookup(user_id: int) -> bool:
        nonlocal probes_called
        probes_called += 1
        return user_id <= 500

    config = BoundaryDiscoveryConfig(
        max_probes=12,
        max_id_ceiling=10_000,
    )

    result = await discover_user_id_boundaries(
        site="OnlyFans",
        lookup_fn=mock_lookup,
        config=config,
    )

    assert probes_called <= 12
    assert result.total_probes_used <= 12


@pytest.mark.asyncio
async def test_all_lookups_fail_cleanly() -> None:
    async def mock_lookup(_user_id: int) -> bool:
        return False

    config = BoundaryDiscoveryConfig(
        max_probes=20,
        max_id_ceiling=10_000,
        consecutive_empty_brackets=2,
    )

    result = await discover_user_id_boundaries(
        site="OnlyFans",
        lookup_fn=mock_lookup,
        config=config,
    )

    assert result.highest_observed_id is None
    assert result.estimated_total_users == 0
    assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# Feature flag and default enablement tests
# ---------------------------------------------------------------------------


def test_is_adaptive_boundary_discovery_enabled() -> None:
    # Enabled by default without any env vars or configuration
    assert is_adaptive_boundary_discovery_enabled()

    req = SimpleNamespace()
    assert is_adaptive_boundary_discovery_enabled(request=req)

    req_off = SimpleNamespace(enable_adaptive_discovery=False)
    assert not is_adaptive_boundary_discovery_enabled(request=req_off)


# ---------------------------------------------------------------------------
# Integration with MPS routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mps_resolve_analysis_scope_empty_db_explicitly_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DB is empty and discovery is explicitly disabled, raises HTTPException 400."""
    monkeypatch.setattr(mps_module, "_query_min_max", AsyncMock(return_value=(None, None)))

    db_manager = object()
    backend_manager = SimpleNamespace(get_site_db_manager=lambda _site: db_manager)

    request = mps_module.MPSAnalyzeRequest(
        site="OnlyFans",
        start_id=None,
        end_id=None,
        enable_adaptive_discovery=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await mps_module._resolve_analysis_scope(request, backend_manager)

    assert exc_info.value.status_code == 400
    assert "No records found for the selected profile sources" in exc_info.value.detail


@pytest.mark.asyncio
async def test_mps_resolve_analysis_scope_empty_db_automatic_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DB is empty and no flags are provided, automatically resolves boundaries adaptively."""
    monkeypatch.setattr(mps_module, "_query_min_max", AsyncMock(return_value=(None, None)))

    async def mock_get_user(_site: str, user_id: int) -> SimpleNamespace:
        return SimpleNamespace(success=(1 <= user_id <= 25_000 and user_id % 2 == 0))

    db_manager = object()
    backend_manager = SimpleNamespace(
        get_site_db_manager=lambda _site: db_manager,
        get_user=mock_get_user,
    )

    # Note: enable_adaptive_discovery is NOT passed; discovery runs automatically on empty DB!
    request = mps_module.MPSAnalyzeRequest(
        site="OnlyFans",
        start_id=None,
        end_id=None,
        adaptive_discovery_max_probes=40,
        adaptive_discovery_ceiling=100_000,
    )

    scope = await mps_module._resolve_analysis_scope(request, backend_manager)

    assert scope.start_id >= 1
    assert scope.end_id >= 10_000
    assert scope.discovery_result is not None
    assert scope.discovery_result.estimated_total_users > 0


@pytest.mark.asyncio
async def test_mps_compute_analysis_summary_with_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When discovery is performed, MPSAnalyzeResponse includes population and confidence."""
    async def mock_get_user(_site: str, user_id: int) -> SimpleNamespace:
        return SimpleNamespace(success=(1 <= user_id <= 10_000))

    db_manager = object()
    backend_manager = SimpleNamespace(
        get_site_db_manager=lambda _site: db_manager,
        get_user=mock_get_user,
    )

    monkeypatch.setattr(mps_module, "_query_min_max", AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(
        mps_module, "_query_existing_candidate_count", AsyncMock(return_value=(0, 0))
    )
    monkeypatch.setattr(
        mps_module, "_query_existing_count", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        mps_module, "_query_invalid_counts", AsyncMock(return_value=(0, 0, True))
    )
    monkeypatch.setattr(
        mps_module, "_query_invalid_candidate_ids_preview", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        mps_module, "_query_existing_candidate_ids_preview", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        mps_module, "_sample_density_buckets", AsyncMock(return_value=[])
    )
    def fake_missing_summary(*_args, **kwargs):
        if kwargs.get("coverage_summary") is not None:
            kwargs["coverage_summary"].update(
                existing_count=0,
                invalid_count=0,
                invalid_table_ready=True,
            )
        return (0, 0, [], None)

    monkeypatch.setattr(
        mps_module,
        "_query_missing_ranges_summary",
        AsyncMock(side_effect=fake_missing_summary),
    )
    monkeypatch.setattr(
        mps_module, "_query_ids_in_range", AsyncMock(return_value=[])
    )

    request = mps_module.MPSAnalyzeRequest(
        site="OnlyFans",
        start_id=None,
        end_id=None,
        enable_adaptive_discovery=True,
        adaptive_discovery_max_probes=40,
        adaptive_discovery_ceiling=50_000,
    )

    response = await mps_module.analyze_mps(request, backend_manager)

    assert response.adaptive_discovery_performed is True
    assert response.population_estimate is not None
    assert response.population_estimate > 0
    assert response.population_confidence_interval is not None
    assert response.highest_id_confidence_interval is not None
    assert response.density_estimate is not None
    assert any("Discovered user boundaries" in w for w in response.warnings)


@pytest.mark.asyncio
async def test_mps_discover_bounds_endpoint() -> None:
    """Tests the dedicated POST /mps/discover-bounds endpoint."""
    async def mock_get_user(_site: str, user_id: int) -> SimpleNamespace:
        return SimpleNamespace(success=(user_id in {10, 50, 100, 500, 1000}))

    backend_manager = SimpleNamespace(
        get_user=mock_get_user,
    )

    request = mps_module.MPSBoundaryDiscoveryRequest(
        site="OnlyFans",
        max_probes=30,
        max_id_ceiling=10_000,
    )

    response = await mps_module.discover_bounds_endpoint(request, backend_manager)

    assert response.site == "OnlyFans"
    assert response.discovered_start_id <= 10
    assert response.discovered_end_id >= 1000
    assert response.highest_observed_id == 1000
    assert response.lowest_observed_id == 10
    assert response.total_probes_used <= 30


@pytest.mark.asyncio
async def test_discovery_starts_from_known_highest_id() -> None:
    """Tests that discovery starts probing from known_max_id and does not probe below it."""
    valid_set = {uid for uid in range(1, 300_001) if uid % 2 == 0}
    probed_ids: list[int] = []

    async def mock_lookup(user_id: int) -> bool:
        probed_ids.append(user_id)
        return user_id in valid_set

    config = BoundaryDiscoveryConfig(
        probe_multiplier=10.0,
        known_min_id=1,
        known_max_id=50_000,
        max_id_ceiling=1_000_000,
        max_probes=50,
        samples_per_step=3,
        refinement_steps=6,
        confidence_level=0.95,
    )

    result = await discover_user_id_boundaries(
        site="OnlyFans",
        lookup_fn=mock_lookup,
        config=config,
    )

    # All probes during exponential search should be > 50,000
    # (adaptive sampling later may sample across [start_id, end_id])
    assert result.highest_observed_id is not None
    assert result.highest_observed_id >= 50_000
    assert result.discovered_start_id == 1
    assert result.discovered_end_id >= 50_000
    assert result.discovered_end_id <= 1_000_000
    # The first probed ID should be strictly greater than known_max_id (50,000)
    assert probed_ids[0] > 50_000


@pytest.mark.asyncio
async def test_discover_bounds_endpoint_uses_database_max_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests that discover_bounds_endpoint reads db_max_id from the site database."""
    async def mock_get_user(_site: str, user_id: int) -> SimpleNamespace:
        return SimpleNamespace(success=(user_id in {50_000, 100_000, 200_000}))

    backend_manager = SimpleNamespace(
        get_user=mock_get_user,
        get_site_db_manager=lambda _site: "mock_db_manager",
    )

    # Mock _query_min_max to return known bounds from existing database
    monkeypatch.setattr(
        mps_module,
        "_query_min_max",
        AsyncMock(return_value=(1, 50_000)),
    )

    request = mps_module.MPSBoundaryDiscoveryRequest(
        site="OnlyFans",
        max_probes=30,
        max_id_ceiling=500_000,
    )

    response = await mps_module.discover_bounds_endpoint(request, backend_manager)

    assert response.site == "OnlyFans"
    assert response.discovered_start_id == 1
    assert response.discovered_end_id >= 50_000
    assert response.highest_observed_id >= 50_000


@pytest.mark.asyncio
async def test_mps_site_bounds_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests the fast GET /mps/site-bounds endpoint."""
    backend_manager = SimpleNamespace(
        get_site_db_manager=lambda _site: "mock_db_manager",
    )

    monkeypatch.setattr(
        mps_module,
        "_query_min_max",
        AsyncMock(return_value=(42, 999_999)),
    )

    response = await mps_module.get_site_bounds_endpoint("OnlyFans", backend_manager)

    assert response.site == "OnlyFans"
    assert response.database_min_id == 42
    assert response.database_max_id == 999_999

    monkeypatch.setattr(
        mps_module,
        "_query_min_max",
        AsyncMock(return_value=(None, None)),
    )
    empty_resp = await mps_module.get_site_bounds_endpoint("Fansly", backend_manager)
    assert empty_resp.site == "Fansly"
    assert empty_resp.database_min_id is None
    assert empty_resp.database_max_id is None


@pytest.mark.asyncio
async def test_discover_bounds_endpoint_honors_explicit_starting_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests that discover_bounds_endpoint prioritizes explicit request.min_id even when db_max_id is higher."""
    probed_ids: list[int] = []

    async def mock_get_user(_site: str, user_id: int) -> SimpleNamespace:
        probed_ids.append(user_id)
        return SimpleNamespace(success=(user_id == 10001))

    backend_manager = SimpleNamespace(
        get_user=mock_get_user,
        get_site_db_manager=lambda _site: None,
    )

    # Mock database to simulate an existing database with a high max_id
    monkeypatch.setattr(
        mps_module,
        "_query_min_max",
        AsyncMock(return_value=(1, 598_973_341)),
    )

    request = mps_module.MPSBoundaryDiscoveryRequest(
        site="OnlyFans",
        min_id=10001,
        max_probes=15,
        max_id_ceiling=100_000,
    )

    response = await mps_module.discover_bounds_endpoint(request, backend_manager)

    # Discovery must start at 10001 and probe 10001 first
    assert probed_ids[0] == 10001
    assert response.discovered_start_id == 10001
    assert response.highest_observed_id is not None
    assert response.highest_observed_id >= 10001


def test_generate_bracket_candidates_always_includes_start_id() -> None:
    """Tests that _generate_bracket_candidates always places start_id as the first candidate."""
    discoverer = AdaptiveBoundaryDiscoverer(lookup_fn=AsyncMock(return_value=True))

    # Custom starting ID that is not a power of 10
    cands_custom = discoverer._generate_bracket_candidates(10001, 100009, 3)
    assert cands_custom[0] == 10001
    assert len(cands_custom) == 3

    # Power of 10 decade bracket
    cands_decade = discoverer._generate_bracket_candidates(100, 999, 3)
    assert cands_decade[0] == 100
    assert cands_decade == [100, 200, 500]


@pytest.mark.asyncio
async def test_default_lookup_fast_paths_database() -> None:
    """Tests that _default_lookup checks the site database manager first to avoid redundant network calls."""
    db_probes: list[int] = []
    network_probes: list[int] = []

    class MockSiteDB:
        def get_user(self, user_id: int) -> SimpleNamespace | None:
            db_probes.append(user_id)
            if user_id == 10001:
                return SimpleNamespace(id=10001, active=True)
            return None

    async def mock_network_get_user(_site: str, user_id: int) -> SimpleNamespace:
        network_probes.append(user_id)
        return SimpleNamespace(success=False)

    bm = SimpleNamespace(
        get_site_db_manager=lambda _site: MockSiteDB(),
        get_user=mock_network_get_user,
    )

    cfg = BoundaryDiscoveryConfig(
        min_id=10001,
        max_probes=10,
        max_id_ceiling=20_000,
    )

    result = await discover_user_id_boundaries("OnlyFans", backend_manager=bm, config=cfg)

    assert 10001 in db_probes
    assert 10001 not in network_probes
    assert result.highest_observed_id is not None
    assert result.highest_observed_id >= 10001


def test_auth_model_find_user_matches_numeric_string() -> None:
    """Tests that auth_model.find_user resolves numeric string IDs against integer keys."""
    from ultima_scraper_api.apis.onlyfans.classes.auth_model import OnlyFansAuthModel

    auth = OnlyFansAuthModel.__new__(OnlyFansAuthModel)
    user_10001 = SimpleNamespace(id=10001, username="u10001", name="Lindo")
    auth.users = {10001: user_10001}

    assert auth.find_user(10001) is user_10001
    assert auth.find_user("10001") is user_10001
    assert auth.find_user("u10001") is user_10001
    assert auth.find_user("99999") is None


@pytest.mark.asyncio
async def test_discover_bounds_endpoint_min_id_one_uses_db_max_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests that min_id=1 does not wipe out database max_id frontier."""
    probed_ids: list[int] = []

    async def mock_get_user(_site: str, user_id: int) -> SimpleNamespace:
        probed_ids.append(user_id)
        return SimpleNamespace(success=(user_id == 50_000))

    backend_manager = SimpleNamespace(
        get_user=mock_get_user,
        get_site_db_manager=lambda _site: "mock_db_manager",
    )

    monkeypatch.setattr(
        mps_module,
        "_query_min_max",
        AsyncMock(return_value=(1, 50_000)),
    )

    request = mps_module.MPSBoundaryDiscoveryRequest(
        site="OnlyFans",
        min_id=1,
        max_probes=15,
        max_id_ceiling=100_000,
    )

    response = await mps_module.discover_bounds_endpoint(request, backend_manager)

    # Probing should start from frontier (> 50,000), not starting at 1
    assert probed_ids[0] > 50_000
    assert response.discovered_start_id == 1
    assert response.discovered_end_id >= 50_000


@pytest.mark.asyncio
async def test_discover_bounds_endpoint_frontier_preserves_db_min_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests that providing a frontier min_id >= db_max_id preserves db_min_id as discovered_start_id."""
    probed_ids: list[int] = []

    async def mock_get_user(_site: str, user_id: int) -> SimpleNamespace:
        probed_ids.append(user_id)
        return SimpleNamespace(success=(user_id == 60_000))

    backend_manager = SimpleNamespace(
        get_user=mock_get_user,
        get_site_db_manager=lambda _site: "mock_db_manager",
    )

    monkeypatch.setattr(
        mps_module,
        "_query_min_max",
        AsyncMock(return_value=(1, 50_000)),
    )

    request = mps_module.MPSBoundaryDiscoveryRequest(
        site="OnlyFans",
        min_id=50_000,
        max_probes=15,
        max_id_ceiling=100_000,
    )

    response = await mps_module.discover_bounds_endpoint(request, backend_manager)

    assert probed_ids[0] > 50_000
    assert response.discovered_start_id == 1
    assert response.discovered_end_id >= 50_000




