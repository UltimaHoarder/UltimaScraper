"""Range samples must not masquerade as exact gap statistics."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session
from ultima_scraper_backend.api.routes import mps


@pytest.mark.asyncio
async def test_large_range_has_exact_gap_count_and_counts_overlap():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("CREATE TABLE invalid_users (site text, user_id bigint)"))
        c.execute(text("INSERT INTO users VALUES (2)"))
        c.execute(text("INSERT INTO invalid_users VALUES ('onlyfans', 2)"))
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cursor, statement, params, ctx, many: statements.append(statement))
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    result = await mps._query_missing_ranges_summary(
        SimpleNamespace(get_session=get_session), site_key="onlyfans", start_id=1,
        end_id=200000, include_invalid_table=True, preview_limit=1,
        existing_count=1, invalid_count=1,
    )
    assert result[0] == 199999  # Overlapping identities are counted once.
    assert result[1] == 2
    assert all("mps_candidate_ranges" not in statement for statement in statements)
    engine.dispose()


@pytest.mark.asyncio
async def test_small_range_count_is_exact_even_when_preview_is_truncated():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("INSERT INTO users VALUES (2), (4), (6)"))
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    result = await mps._query_missing_ranges_summary(
        SimpleNamespace(get_session=get_session), site_key="onlyfans", start_id=1,
        end_id=8, include_invalid_table=False, preview_limit=1,
        existing_count=3, invalid_count=0,
    )
    assert result[:3] == (5, 4, [(1, 1)])
    engine.dispose()


@pytest.mark.asyncio
async def test_dense_initial_window_does_not_read_old_manifests():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("WITH RECURSIVE ids(id) AS (SELECT 1 UNION ALL SELECT id+1 FROM ids WHERE id<100000) INSERT INTO users SELECT id FROM ids"))
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cursor, statement, params, ctx, many: statements.append(statement))
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    result = await mps._query_missing_ranges_summary(
        SimpleNamespace(get_session=get_session), site_key="onlyfans", start_id=1,
        end_id=200000, include_invalid_table=False, preview_limit=4,
        existing_count=100000, invalid_count=0,
    )
    assert result[0] == 100000
    assert result[1] == 1
    assert result[3] == (100001, 200000)
    assert all("mps_candidate_ranges" not in statement for statement in statements)
    engine.dispose()


@pytest.mark.asyncio
async def test_complete_ranges_cross_preview_windows_and_ids_are_not_expanded():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("INSERT INTO users VALUES (2), (110000)"))
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    summary = {}
    result = await mps._query_missing_ranges_summary(
        SimpleNamespace(get_session=get_session), site_key="onlyfans", start_id=1,
        end_id=593173836, include_invalid_table=False, preview_limit=2,
        candidate_summary=summary,
    )
    assert result[:3] == (593173834, 3, [(1, 1), (3, 109999)])
    assert summary["range_count"] == 3
    assert summary["ranges"] == [(1, 1), (110001, 593173836)]
    assert summary["count"] == 593173834
    engine.dispose()


@pytest.mark.asyncio
async def test_candidate_groups_merge_sources_and_apply_cooldowns():
    from datetime import datetime, timezone
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY, last_checked_at text)"))
        c.execute(text("CREATE TABLE invalid_users (site text, user_id bigint, updated_at text, last_checked_at text)"))
        c.execute(text("INSERT INTO users VALUES (2, '2026-10-01T00:00:00+00:00'), (5, NULL)"))
        c.execute(text("INSERT INTO invalid_users VALUES ('onlyfans',3,'2026-09-01T00:00:00+00:00',NULL),('onlyfans',5,NULL,NULL),('onlyfans',7,'2026-10-01T00:00:00+00:00',NULL)"))
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    summary = {}
    result = await mps._query_missing_ranges_summary(
        SimpleNamespace(get_session=get_session), site_key="onlyfans", start_id=1,
        end_id=10, include_invalid_table=True, preview_limit=10,
        include_invalid_candidates=True, include_existing_candidates=True,
        invalid_cutoff=datetime(2026,9,15,tzinfo=timezone.utc),
        existing_cutoff=datetime(2026,9,15,tzinfo=timezone.utc), candidate_summary=summary,
    )
    assert result[:3] == (6, 4, [(1,1),(4,4),(6,6),(8,10)])
    assert summary == {"count":8, "range_count":3, "ranges":[(1,1),(3,6),(8,10)]}
    engine.dispose()


@pytest.mark.asyncio
async def test_invalid_only_groups_exclude_existing_and_honor_cooldowns():
    from datetime import datetime, timezone
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("CREATE TABLE invalid_users (site text, user_id bigint, updated_at text, last_checked_at text)"))
        c.execute(text("INSERT INTO users VALUES (5)"))
        c.execute(text("INSERT INTO invalid_users VALUES ('onlyfans',3,NULL,NULL),('onlyfans',4,NULL,NULL),('onlyfans',5,NULL,NULL),('onlyfans',7,'2026-10-01T00:00:00+00:00',NULL)"))
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    summary = {}
    result = await mps._query_missing_ranges_summary(
        SimpleNamespace(get_session=get_session), site_key="onlyfans", start_id=1,
        end_id=10, include_invalid_table=True, preview_limit=1,
        include_missing=False, include_invalid_candidates=True,
        invalid_cutoff=datetime(2026,9,15,tzinfo=timezone.utc), candidate_summary=summary,
    )
    assert result == (0,0,[],None)
    assert summary == {"count":2, "range_count":1, "ranges":[(3,4)]}
    engine.dispose()


@pytest.mark.asyncio
async def test_existing_count_executes_unified_range_query_by_default():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("INSERT INTO users VALUES (1), (2), (3), (4), (6), (7), (8), (9), (10)"))
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cursor, statement, params, ctx, many: statements.append((statement, params)))
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    result = await mps._query_existing_count(SimpleNamespace(get_session=get_session), start_id=2, end_id=9)
    assert result == 7
    counts = [params for statement, params in statements if "count(" in statement]
    assert counts == [(2, 9)]
    engine.dispose()


@pytest.mark.asyncio
async def test_existing_count_partitions_exact_range_without_overlap(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("INSERT INTO users VALUES (1), (2), (3), (4), (6), (7), (8), (9), (10)"))
    monkeypatch.setattr(mps, "MPS_ANALYSIS_COUNT_ID_SPAN", 3)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cursor, statement, params, ctx, many: statements.append((statement, params)))
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    result = await mps._query_existing_count(SimpleNamespace(get_session=get_session), start_id=2, end_id=9)
    assert result == 7
    counts = [params for statement, params in statements if "count(" in statement]
    assert counts == [(2, 4), (5, 7), (8, 9)]
    engine.dispose()


@pytest.mark.asyncio
async def test_invalid_count_executes_unified_query_by_default():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("CREATE TABLE invalid_users (site text, user_id bigint, updated_at datetime, last_checked_at datetime)"))
        c.execute(text("INSERT INTO users VALUES (3)"))
        c.execute(text("INSERT INTO invalid_users (site,user_id) VALUES ('onlyfans',2),('onlyfans',3),('onlyfans',4),('onlyfans',7),('fansly',5),('onlyfans',10)"))
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cursor, statement, params, ctx, many: statements.append((statement, params)))
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    res = await mps._query_invalid_counts(SimpleNamespace(get_session=get_session), site_key="onlyfans", start_id=2, end_id=9, include_invalid=True, last_checked_older_than_hours=24)
    assert res == (4, 3, True)
    counts = [params for statement, params in statements if "count(" in statement]
    assert len(counts) == 2
    engine.dispose()


@pytest.mark.asyncio
async def test_invalid_count_partitions_and_excludes_existing(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("CREATE TABLE invalid_users (site text, user_id bigint, updated_at datetime, last_checked_at datetime)"))
        c.execute(text("INSERT INTO users VALUES (3)"))
        c.execute(text("INSERT INTO invalid_users (site,user_id) VALUES ('onlyfans',2),('onlyfans',3),('onlyfans',4),('onlyfans',7),('fansly',5),('onlyfans',10)"))
    monkeypatch.setattr(mps, "MPS_ANALYSIS_COUNT_ID_SPAN", 3)
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    assert await mps._query_invalid_counts(SimpleNamespace(get_session=get_session), site_key="onlyfans", start_id=2, end_id=9, include_invalid=True, last_checked_older_than_hours=24) == (4,3,True)
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("code,unavailable", [("57014",False),("42P01",True),("42703",True)])
async def test_invalid_query_errors_do_not_masquerade_as_missing_table(code, unavailable):
    from sqlalchemy.exc import OperationalError
    class DriverError(Exception):
        sqlstate = code
    class FakeSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
        def exec(self, query):
            raise OperationalError("fixture", {}, DriverError())
    @contextmanager
    def get_session():
        yield FakeSession()
    call = mps._query_invalid_counts(SimpleNamespace(get_session=get_session), site_key="onlyfans", start_id=1, end_id=9, include_invalid=False, last_checked_older_than_hours=None)
    if unavailable:
        assert await call == (0,0,False)
    else:
        with pytest.raises(mps.HTTPException) as error:
            await call
        assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_verified_coverage_skips_dense_blocks_and_scans_deleted_gaps(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("CREATE TABLE invalid_users (site text,user_id bigint)"))
        c.execute(text("INSERT INTO users VALUES (1),(2),(3),(4),(6),(9),(10),(11),(12)"))
        c.execute(text("INSERT INTO invalid_users VALUES ('onlyfans',4),('onlyfans',5),('onlyfans',5),('onlyfans',8),('fansly',7)"))
    monkeypatch.setattr(mps, "MPS_ANALYSIS_COUNT_ID_SPAN", 3)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cursor, statement, params, ctx, many: statements.append((statement,params)))
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    summary = {}
    result = await mps._query_missing_ranges_summary(SimpleNamespace(get_session=get_session), site_key="onlyfans", start_id=1, end_id=12, include_invalid_table=True, preview_limit=1, candidate_summary=summary)
    assert result[:3] == (1,1,[(7,7)])
    assert summary["existing_count"] == 9
    # Full analysis reads run boundaries for the one block with a hole.
    scans = [params for query,params in statements if "lag(user_id)" in query]
    assert scans == [(7,9,"onlyfans",7,9)]
    assert not [query for query,_ in statements if query.startswith("SELECT id AS")]
    # A hole introduced in formerly dense coverage must be detected on reanalysis.
    with engine.begin() as c:
        c.execute(text("DELETE FROM users WHERE id=2"))
    result = await mps._query_missing_ranges_summary(SimpleNamespace(get_session=get_session), site_key="onlyfans", start_id=1, end_id=12, include_invalid_table=True, preview_limit=1)
    assert result[:3] == (2,2,[(2,2)])
    engine.dispose()


def _coverage_fixture_ids(seed: int, end_id: int) -> tuple[list[int], list[tuple[str, int]]]:
    import random
    rng = random.Random(seed)
    users = set(range(1, 41)) | set(rng.sample(range(41, end_id + 1), end_id // 3))
    # Block 31-40 is dense only once invalid-only IDs fill the user holes.
    users -= {33, 36}
    invalid = [("onlyfans", 33), ("onlyfans", 36), ("onlyfans", 36)]
    invalid += [("onlyfans", uid) for uid in rng.sample(range(41, end_id + 1), end_id // 8)]
    invalid += [("onlyfans", uid) for uid in rng.sample(sorted(users), 5)]  # overlap users
    invalid += [("fansly", uid) for uid in rng.sample(range(1, end_id + 1), 20)]  # other site
    return sorted(users), invalid


def _coverage_engine(path, users, invalid):
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY, last_checked_at timestamp)"))
        c.execute(text("CREATE TABLE invalid_users (site text, user_id bigint, updated_at timestamp, last_checked_at timestamp)"))
        c.execute(text("INSERT INTO users (id) VALUES (:id)"), [{"id": uid} for uid in users])
        c.execute(text("INSERT INTO invalid_users (site, user_id) VALUES (:site, :id)"), [{"site": s, "id": uid} for s, uid in invalid])
    return engine


@pytest.mark.asyncio
@pytest.mark.parametrize("seed", [1, 2, 3])
async def test_full_grouped_coverage_matches_per_block_scan_exactly(monkeypatch, tmp_path, seed):
    end_id = 600
    users, invalid = _coverage_fixture_ids(seed, end_id)
    engine = _coverage_engine(tmp_path / "coverage.db", users, invalid)
    monkeypatch.setattr(mps, "MPS_ANALYSIS_COUNT_ID_SPAN", 10)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cursor, statement, params, ctx, many: statements.append(statement))
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    db = SimpleNamespace(get_session=get_session)
    common = dict(site_key="onlyfans", start_id=1, end_id=end_id, include_invalid_table=True, density_resolution=64)

    coverage, full_candidates, full_density = {}, {}, {}
    full = await mps._query_missing_ranges_summary(
        db, preview_limit=4, bounded=False, coverage_summary=coverage,
        candidate_summary=full_candidates, density_summary=full_density, **common,
    )
    grouped_count_statements = [s for s in statements if "count(" in s]
    statements.clear()
    # A bounded scan whose preview never fills walks every block with per-block counts.
    reference_candidates, reference_density = {}, {}
    reference = await mps._query_missing_ranges_summary(
        db, preview_limit=10_000, bounded=True, existing_count=len(users),
        candidate_summary=reference_candidates, density_summary=reference_density, **common,
    )
    per_block_count_statements = [s for s in statements if "count(" in s]

    known = set(users) | {uid for site, uid in invalid if site == "onlyfans"}
    missing = [uid for uid in range(1, end_id + 1) if uid not in known]
    runs = sum(1 for index, uid in enumerate(missing) if index == 0 or missing[index - 1] != uid - 1)
    assert full[:2] == (len(missing), runs)
    assert full[3] == reference[3]
    assert reference[:2] == full[:2]
    assert full_candidates["count"] == reference_candidates["count"] == len(missing)
    assert full_candidates["range_count"] == reference_candidates["range_count"] == runs
    assert full_candidates["existing_count"] == len(users)
    assert full_density["density_buckets"] == reference_density["density_buckets"]
    assert coverage == {
        "existing_count": len(users),
        "invalid_count": sum(1 for site, _ in invalid if site == "onlyfans"),
        "invalid_table_ready": True,
    }
    # One grouped statement per source replaces two statements per block.
    assert len(grouped_count_statements) == 2
    assert len(per_block_count_statements) == 2 * (end_id // 10)
    assert sum(b.missing_count + b.invalid_count + b.existing_count for b in full_density["density_buckets"]) == end_id
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("code,unavailable", [("57014", False), ("42P01", True)])
async def test_grouped_coverage_reports_missing_invalid_table_without_aborting(code, unavailable):
    from contextlib import nullcontext
    from sqlalchemy.exc import OperationalError
    class DriverError(Exception):
        sqlstate = code
    class FakeSession:
        def execute(self, statement, params=None):
            if "invalid_users" in str(statement):
                raise OperationalError("fixture", {}, DriverError())
            return iter([(0, 3), (2, 1)])
        def begin_nested(self):
            return nullcontext()
    call = lambda: mps._count_coverage_blocks(
        FakeSession(), site_key="onlyfans", base_id=1, end_id=30, span=10, include_invalid_table=True,
    )
    if unavailable:
        assert call() == ({0: (3, 0), 2: (1, 0)}, 4, 0, False)
    else:
        with pytest.raises(mps.HTTPException) as error:
            call()
        assert error.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("include_invalid", [False, True])
async def test_full_analysis_takes_inventories_from_coverage_pass(monkeypatch, tmp_path, include_invalid):
    from unittest.mock import AsyncMock
    end_id = 600
    users, invalid = _coverage_fixture_ids(7, end_id)
    invalid = list(dict.fromkeys(invalid))  # invalid_users is unique per (site, user_id)
    engine = _coverage_engine(tmp_path / "analysis.db", users, invalid)
    @contextmanager
    def get_session():
        with Session(engine) as session:
            yield session
    scope = mps._AnalysisScope(site_display="OnlyFans", site_key="onlyfans",
        db_manager=SimpleNamespace(get_session=get_session),
        database_min_id=1, database_max_id=end_id, start_id=1, end_id=end_id)
    monkeypatch.setattr(mps, "_resolve_analysis_scope", AsyncMock(return_value=scope))
    monkeypatch.setattr(mps, "_query_existing_count", AsyncMock(side_effect=AssertionError("counted twice")))
    monkeypatch.setattr(mps, "MPS_ANALYSIS_COUNT_ID_SPAN", 10)
    monkeypatch.setattr(mps, "_USER_COUNT_CACHE", {})
    monkeypatch.setattr(mps, "_INVALID_COUNT_CACHE", {})

    response = await mps._compute_analysis_summary(
        mps.MPSAnalyzeRequest(start_id=1, end_id=end_id, include_invalid=include_invalid, density_resolution=64),
        SimpleNamespace(),
    )

    invalid_ids = {uid for site, uid in invalid if site == "onlyfans"}
    invalid_only = invalid_ids - set(users)
    missing = end_id - len(set(users) | invalid_ids)
    assert response.existing_user_count == len(users)
    assert response.invalid_user_count == len(invalid_ids)
    assert response.invalid_table_ready is True
    assert response.missing_count == missing
    assert response.invalid_eligible_count == (len(invalid_only) if include_invalid else 0)
    assert response.candidate_count == missing + (len(invalid_only) if include_invalid else 0)
    assert response.density_is_exact is True
    assert sum(bucket.existing_count + bucket.invalid_count + bucket.missing_count for bucket in response.density_buckets) == end_id
    assert mps._USER_COUNT_CACHE[("users", 1, end_id)][1] == len(users)
    assert mps._INVALID_COUNT_CACHE[("onlyfans", 1, end_id)][1] == len(invalid_ids)
    engine.dispose()


def test_density_bucket_index_follows_bucket_boundaries():
    acc = mps.DensityAccumulator(1, 600, resolution=64)
    # Proportional division puts 38 in bucket 3, but bucket 4 starts at 38.
    assert (acc.bucket_starts[4], acc.bucket_index(38)) == (38, 4)
    for index, (lo, hi) in enumerate(zip(acc.bucket_starts, acc.bucket_ends)):
        assert acc.bucket_index(lo) == acc.bucket_index(hi) == index
    acc.add_range(38, 38, "existing")
    acc.add_range(29, 47, "missing", is_candidate=True)
    assert acc.existing[4] == 1 and acc.existing[3] == 0
    assert sum(acc.missing) == sum(acc.candidate) == 19


def test_known_islands_merge_sources_and_ignore_duplicates():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE users (id bigint PRIMARY KEY)"))
        c.execute(text("CREATE TABLE invalid_users (site text, user_id bigint)"))
        c.execute(text("INSERT INTO users VALUES (1),(2),(3),(7),(9),(10),(20)"))
        # 3 overlaps users, 4 is duplicated, 12 is an isolated duplicate, 15 belongs to another site.
        c.execute(text(
            "INSERT INTO invalid_users VALUES ('onlyfans',3),('onlyfans',4),('onlyfans',4),"
            "('onlyfans',12),('onlyfans',12),('fansly',15),('onlyfans',30)"
        ))
    with Session(engine) as session:
        islands = mps._query_known_islands(session, site_key="onlyfans", lower=2, upper=20, include_invalid_table=True)
        users_only = mps._query_known_islands(session, site_key="onlyfans", lower=1, upper=20, include_invalid_table=False)
        empty = mps._query_known_islands(session, site_key="onlyfans", lower=21, upper=29, include_invalid_table=True)
    assert islands == [(2, 4), (7, 7), (9, 10), (12, 12), (20, 20)]
    assert users_only == [(1, 3), (7, 7), (9, 10), (20, 20)]
    assert empty == []
    engine.dispose()
