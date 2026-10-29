"""Verification of MPS ID-space density bucket partition invariants and candidate accounting."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session
from ultima_scraper_backend.api.routes import mps


def test_density_accumulator_bucket_partition_invariants():
    """Verify bucket boundaries cover the interval with 0 gaps, 0 overlap, and exact sums."""
    start_id = 1
    end_id = 10_000_000
    resolution = 512
    acc = mps.DensityAccumulator(start_id, end_id, resolution=resolution)

    models = acc.to_models()
    assert len(models) == resolution
    assert models[0].start_id == start_id
    assert models[-1].end_id == end_id

    # Verify contiguous deterministic boundaries
    for i in range(len(models) - 1):
        assert models[i].start_id <= models[i].end_id
        assert models[i + 1].start_id == models[i].end_id + 1

    # Add various ranges crossing multiple boundaries
    acc.add_range(1, 50_000, "existing", is_candidate=False)
    acc.add_range(50_001, 100_000, "invalid", is_candidate=True)
    acc.add_range(100_001, 10_000_000, "missing", is_candidate=True)

    models = acc.to_models()
    assert len(models) == resolution

    total_missing = sum(b.missing_count or 0 for b in models)
    total_invalid = sum(b.invalid_count or 0 for b in models)
    total_existing = sum(b.existing_count or 0 for b in models)
    total_candidate = sum(b.candidate_count or 0 for b in models)

    assert total_missing == (10_000_000 - 100_001 + 1)
    assert total_invalid == (100_000 - 50_001 + 1)
    assert total_existing == (50_000 - 1 + 1)
    assert total_candidate == total_missing + total_invalid
    assert total_missing + total_invalid + total_existing == (end_id - start_id + 1)
    assert acc.is_all_exact() is True
    assert all(b.is_exact for b in models)


@pytest.mark.asyncio
async def test_bounded_mode_does_not_create_phantom_candidates():
    """Bounded analysis must never classify unscanned IDs as missing profiles."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    total_space = 100_000
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("CREATE TABLE invalid_users (site text, user_id bigint)"))
        # 500 users in lower region with small gaps (triggers preview limit)
        for uid in range(1, 1000, 2):
            c.execute(text(f"INSERT INTO users VALUES ({uid})"))
        # 1000 users in upper region (unscanned if preview limit is small)
        for uid in range(50_000, 51_000):
            c.execute(text(f"INSERT INTO users VALUES ({uid})"))

    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session

    db_manager = SimpleNamespace(get_session=get_session)
    existing_count = 500 + 1000  # 1500 total users

    # Full analysis (bounded=False) with streaming mode (site_key="fansly")
    candidate_summary_full = {}
    density_summary_full = {}
    full_res = await mps._query_missing_ranges_summary(
        db_manager,
        site_key="fansly",
        start_id=1,
        end_id=total_space,
        include_invalid_table=False,
        preview_limit=10,
        existing_count=existing_count,
        invalid_count=0,
        bounded=False,
        candidate_summary=candidate_summary_full,
        density_summary=density_summary_full,
    )

    # Normal analysis (bounded=True)
    candidate_summary_bounded = {}
    density_summary_bounded = {}
    authoritative_missing = total_space - existing_count
    bounded_res = await mps._query_missing_ranges_summary(
        db_manager,
        site_key="fansly",
        start_id=1,
        end_id=total_space,
        include_invalid_table=False,
        preview_limit=10,
        existing_count=existing_count,
        invalid_count=0,
        bounded=True,
        authoritative_missing=authoritative_missing,
        authoritative_candidate=authoritative_missing,
        candidate_summary=candidate_summary_bounded,
        density_summary=density_summary_bounded,
    )

    # Candidate accounting MUST match exactly between Normal and Full analysis!
    # No phantom candidate inflation.
    expected_candidates = total_space - existing_count
    assert full_res[0] == expected_candidates
    assert bounded_res[0] == expected_candidates
    assert candidate_summary_full["count"] == expected_candidates
    assert candidate_summary_bounded["count"] == expected_candidates

    # Full analysis buckets are all exact
    assert density_summary_full["density_is_exact"] is True
    assert all(b.is_exact for b in density_summary_full["density_buckets"])

    # Bounded analysis buckets have exact=False on unscanned regions, but non-zero estimates
    assert density_summary_bounded["density_is_exact"] is False
    unscanned_buckets = [b for b in density_summary_bounded["density_buckets"] if not b.is_exact]
    assert len(unscanned_buckets) > 0
    # Unscanned buckets must NOT be presented as 0 density!
    assert all(b.missing_count is not None and b.missing_count > 0 for b in unscanned_buckets)

    # Dense pockets are extracted and valid
    pockets = density_summary_bounded["dense_pockets"]
    assert len(pockets) > 0
    for p in pockets:
        assert p.candidate_count > 0
        assert p.density_percentage > 0.0

    engine.dispose()


@pytest.mark.asyncio
async def test_quick_density_samples_the_whole_space_and_preserves_classification():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id bigint PRIMARY KEY, last_checked_at timestamp)"))
        connection.execute(text("CREATE TABLE invalid_users (site text, user_id bigint, last_checked_at timestamp, updated_at timestamp)"))
        # A dense existing region, an invalid region, and a genuinely missing tail.
        connection.execute(text("WITH RECURSIVE ids(id) AS (SELECT 1 UNION ALL SELECT id+1 FROM ids WHERE id<128) INSERT INTO users SELECT id, NULL FROM ids"))
        connection.execute(text("WITH RECURSIVE ids(id) AS (SELECT 65 UNION ALL SELECT id+1 FROM ids WHERE id<256) INSERT INTO invalid_users SELECT 'onlyfans', id, NULL, NULL FROM ids"))

    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session

    buckets = await mps._sample_density_buckets(
        SimpleNamespace(get_session=get_session),
        request=mps.MPSAnalyzeRequest(density_resolution=64, include_invalid=True),
        site_key="onlyfans", start_id=1, end_id=6400, invalid_table_ready=True,
    )
    assert len(buckets) == 64
    assert buckets[0].existing_count == 100
    assert buckets[0].missing_count == buckets[0].invalid_count == buckets[0].candidate_count == 0
    assert buckets[1].invalid_count > 0
    assert buckets[-1].missing_count == buckets[-1].candidate_count == 100
    assert all(not bucket.is_exact for bucket in buckets)
    assert all(bucket.missing_count + bucket.invalid_count + bucket.existing_count == 100 for bucket in buckets)
    # Sampling estimates must not alter the authoritative run totals.
    assert sum(bucket.candidate_count for bucket in buckets) <= 6400
    engine.dispose()


@pytest.mark.asyncio
async def test_fast_plan_reads_invalid_inventory_when_cache_is_cold(monkeypatch):
    from unittest.mock import AsyncMock
    scope = mps._AnalysisScope(site_display="OnlyFans", site_key="onlyfans", db_manager=object(),
        database_min_id=1, database_max_id=100, start_id=1, end_id=100)
    monkeypatch.setattr(mps, "_resolve_analysis_scope", AsyncMock(return_value=scope))
    monkeypatch.setattr(mps, "_INVALID_COUNT_CACHE", {})
    monkeypatch.setattr(mps, "_query_recent_plan_preview", AsyncMock(return_value={
        "summary": {"missing_count": 80, "candidate_count": 80}, "ranges": [(1, 80)]}))
    invalid_query = AsyncMock(return_value=(7, 0, True))
    monkeypatch.setattr(mps, "_query_invalid_counts", invalid_query)
    monkeypatch.setattr(mps, "_sample_density_buckets", AsyncMock(return_value=[
        mps.MPSDensityBucket(start_id=1, end_id=100, missing_count=80, invalid_count=7,
            existing_count=13, candidate_count=80, is_exact=False)]))
    response = await mps._compute_analysis_summary(mps.MPSAnalyzeRequest(bounded=True, include_invalid=False), SimpleNamespace())
    assert response.invalid_user_count == 7
    assert response.invalid_eligible_count == 0
    assert response.candidate_count == 80
    assert response.density_buckets[0].invalid_count == 7
    assert invalid_query.await_args.kwargs["include_invalid"] is False
    assert invalid_query.await_args.kwargs["bounded"] is True


@pytest.mark.asyncio
async def test_fast_plan_bypassed_when_candidate_count_not_exact(monkeypatch):
    from unittest.mock import AsyncMock
    scope = mps._AnalysisScope(site_display="OnlyFans", site_key="onlyfans", db_manager=object(),
        database_min_id=1, database_max_id=100, start_id=1, end_id=100)
    monkeypatch.setattr(mps, "_resolve_analysis_scope", AsyncMock(return_value=scope))
    monkeypatch.setattr(mps, "_query_recent_plan_preview", AsyncMock(return_value={
        "summary": {"missing_count": 20, "candidate_count": 20, "candidate_count_exact": False},
        "ranges": [(1, 20)],
    }))
    monkeypatch.setattr(mps, "_query_existing_count", AsyncMock(return_value=15))
    monkeypatch.setattr(mps, "_query_invalid_counts", AsyncMock(return_value=(5, 0, True)))
    monkeypatch.setattr(mps, "_query_missing_ranges_summary", AsyncMock(return_value=(80, 1, [(1, 80)], None)))
    monkeypatch.setattr(mps, "_sample_density_buckets", AsyncMock(return_value=[
        mps.MPSDensityBucket(start_id=1, end_id=100, missing_count=80, invalid_count=5,
            existing_count=15, candidate_count=80, is_exact=True)]))
    response = await mps._compute_analysis_summary(mps.MPSAnalyzeRequest(bounded=True, include_invalid=False), SimpleNamespace())
    # Should ignore the truncated 20-candidate partial batch preview and compute the true 80 candidates!
    assert response.candidate_count == 80
    assert response.missing_count == 80

