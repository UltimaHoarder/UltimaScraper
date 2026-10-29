"""Missing-only MPS selection transfers IDs only for the requested window."""

import json
import random
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from test_mps_manifest import postgres_engine, store
from ultima_scraper_backend.database import mps_manifest

__all__ = ["postgres_engine", "store"]


def _seed(store, users, invalid):
    with store.session_factory() as session:
        if users:
            session.execute(
                text("INSERT INTO users SELECT unnest(CAST(:ids AS bigint[])), NULL"),
                {"ids": sorted(users)},
            )
        if invalid:
            session.execute(
                text(
                    "INSERT INTO invalid_users SELECT 'onlyfans', "
                    "unnest(CAST(:ids AS bigint[])), NULL, NULL"
                ),
                {"ids": sorted(invalid)},
            )
        session.commit()


def _plan(store, *, start_id, end_id, offset=0, limit=None, hint=None,
          commit=False, job_config=None):
    job_id = uuid4().hex
    params = {
        "job_id": job_id,
        "site": "onlyfans",
        "job_config": json.dumps(job_config or {"name": "Fixture"}),
        "selection": json.dumps(
            {"start_id": start_id, "end_id": end_id, "candidate_offset": offset}
        ),
        "proxy_pool": "[]",
        "start_id": start_id,
        "end_id": end_id,
        "candidate_offset": offset,
        "max_profiles": limit,
        "candidate_count_hint": hint,
    }
    with store.session_factory() as session:
        row = mps_manifest._create_missing_only_plan(session, params)
        ranges = session.execute(
            text(
                "SELECT first_ordinal, start_id, end_id FROM mps_candidate_ranges "
                "WHERE job_id = :job_id ORDER BY first_ordinal"
            ),
            {"job_id": job_id},
        ).all()
        if commit:
            session.commit()
        else:
            session.rollback()
    selected = []
    for first_ordinal, first, last in ranges:
        assert first_ordinal == len(selected)
        selected.extend(range(first, last + 1))
    return row, selected


@pytest.fixture
def small_blocks(monkeypatch):
    monkeypatch.setattr(mps_manifest, "_MPS_COVERAGE_ID_SPAN", 7)
    monkeypatch.setattr(mps_manifest, "_MPS_COVERAGE_FANOUT", 3)


@pytest.mark.parametrize("seed", range(4))
def test_windowed_selection_matches_brute_force(store, small_blocks, seed):
    rng = random.Random(seed)
    start_id, end_id = 5, 400
    users = set(rng.sample(range(1, 420), 160))
    invalid = set(rng.sample(range(1, 420), 90))  # Overlaps users on purpose.
    _seed(store, users, invalid)
    missing = [i for i in range(start_id, end_id + 1) if i not in users | invalid]
    for offset, limit in (
        (0, None), (0, 1), (0, 25), (13, 40), (len(missing) - 3, 10),
        (len(missing) - 1, None), (60, 1000),
    ):
        row, selected = _plan(
            store, start_id=start_id, end_id=end_id, offset=offset, limit=limit
        )
        expected = missing[offset: None if limit is None else offset + limit]
        assert selected == expected
        assert row is not None
        total, summary = row
        assert total == len(expected)
        summary = json.loads(summary)
        if limit is None or offset + limit >= len(missing):
            # The scan reached the end of the range: totals are exact.
            assert summary["candidate_count"] == len(missing)
            assert "candidate_count_exact" not in summary
        else:
            # Stopped after the window: a lower bound that proves a next batch.
            assert offset + limit < summary["candidate_count"] <= len(missing)
            assert summary["candidate_count_exact"] is False


def test_offset_past_the_end_selects_nothing(store, small_blocks):
    _seed(store, {1, 2, 3}, set())
    row, selected = _plan(store, start_id=1, end_id=10, offset=7)
    assert row is None and selected == []


def test_only_blocks_overlapping_the_window_stream_ids(store, monkeypatch):
    monkeypatch.setattr(mps_manifest, "_MPS_COVERAGE_ID_SPAN", 1000)
    monkeypatch.setattr(mps_manifest, "_MPS_COVERAGE_FANOUT", 4)
    # Every other ID is known: each block is half populated and would stream.
    _seed(store, set(range(1, 40_001, 2)), set())
    original = Session.execute
    streamed = []

    def execute(session, statement, *args, **kwargs):
        if str(statement).lstrip().startswith("SELECT id AS user_id"):
            streamed.append(args[0]["lower"])
        return original(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", execute)
    row, selected = _plan(
        store, start_id=1, end_id=40_000, offset=10_000, limit=300, hint=20_000
    )
    # Missing ordinal 10,000 is ID 20,002; 300 IDs span one 1,000-ID block.
    assert selected == list(range(20_002, 20_602, 2))
    assert streamed == [20_001]
    assert row is not None
    summary = json.loads(row[1])
    assert summary["candidate_count"] == 20_000
    assert summary["candidate_count_exact"] is False


def test_finite_window_does_not_count_the_rest_of_the_range(store, monkeypatch):
    monkeypatch.setattr(mps_manifest, "_MPS_COVERAGE_ID_SPAN", 1000)
    monkeypatch.setattr(mps_manifest, "_MPS_COVERAGE_FANOUT", 4)
    _seed(store, set(range(1, 400_001, 2)), set())
    original = Session.execute
    counted = []

    def execute(session, statement, *args, **kwargs):
        if str(statement).lstrip().startswith("SELECT (SELECT count(*)"):
            counted.append(args[0]["upper"])
        return original(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", execute)
    row, selected = _plan(store, start_id=1, end_id=400_000, limit=100)
    assert selected == list(range(2, 202, 2))
    # One coarse block, its first fine block, then the proof of a next batch.
    assert max(counted) <= 4_000
    summary = json.loads(row[1])
    assert summary["candidate_count_exact"] is False
    assert summary["candidate_count"] > 100


def _count_lowers(monkeypatch):
    original = Session.execute
    lowers = []

    def execute(session, statement, *args, **kwargs):
        if str(statement).lstrip().startswith("SELECT (SELECT count(*)"):
            lowers.append(args[0]["lower"])
        return original(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", execute)
    return lowers


def test_prior_plan_skips_its_proven_known_prefix(store, monkeypatch):
    monkeypatch.setattr(mps_manifest, "_MPS_COVERAGE_ID_SPAN", 100)
    monkeypatch.setattr(mps_manifest, "_MPS_COVERAGE_FANOUT", 4)
    gaps = {3_001, 3_050, 4_000, 4_500, 6_000}
    _seed(store, set(range(1, 8_001)) - gaps, set())
    _plan(store, start_id=1, end_id=10_000, limit=2, commit=True)
    lowers = _count_lowers(monkeypatch)
    row, selected = _plan(store, start_id=1, end_id=10_000, limit=4)
    assert selected == [3_001, 3_050, 4_000, 4_500]
    assert lowers and min(lowers) >= 3_001
    # Unlimited selections remain exact with the skipped prefix counted known.
    row, selected = _plan(store, start_id=1, end_id=10_000)
    assert selected == sorted(gaps) + list(range(8_001, 10_001))
    assert json.loads(row[1])["candidate_count"] == len(gaps) + 2_000


def test_retry_and_filtered_plans_never_supply_a_prefix(store, monkeypatch):
    monkeypatch.setattr(mps_manifest, "_MPS_COVERAGE_ID_SPAN", 100)
    _seed(store, set(range(1, 8_001)) - {500, 7_000}, set())
    # Its first range need not be the first missing ID: a retry holds failed IDs.
    _plan(store, start_id=6_000, end_id=10_000, limit=1, commit=True)
    _plan(store, start_id=1, end_id=10_000, offset=1, limit=1, commit=True)
    _plan(store, start_id=1, end_id=10_000, limit=1, commit=True,
          job_config={"name": "Retry", "metadata": {"retry_of": "source"}})
    with store.session_factory() as session:
        # Pretend the retry's frozen range starts past the real first gap.
        session.execute(text(
            "UPDATE mps_candidate_ranges r SET start_id = 7000, end_id = 7000 "
            "FROM mps_plans p WHERE p.job_id = r.job_id "
            "AND p.job_config_json::jsonb -> 'metadata' ? 'retry_of'"
        ))
        session.commit()
    lowers = _count_lowers(monkeypatch)
    row, selected = _plan(store, start_id=1, end_id=10_000, limit=1)
    assert selected == [500]
    assert min(lowers) == 1
