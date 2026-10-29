from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlmodel import Session

import test_mps_manifest as postgres_fixtures
from ultima_scraper_backend.services.statistics_service import StatisticsService

postgres_engine = postgres_fixtures.postgres_engine


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / ".env"
    monkeypatch.setattr("ultima_scraper_core.environment.get_env_path", lambda: path)
    monkeypatch.delenv("ULTIMA_STATS_BATCH_SIZE", raising=False)
    return path


@pytest.fixture(scope="module")
def stats_engine(postgres_engine):
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE onlyfans.media (id bigint PRIMARY KEY, category varchar(64), size bigint, downloaded boolean NOT NULL DEFAULT false)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE onlyfans.users (id bigint PRIMARY KEY, performer boolean NOT NULL DEFAULT false)"
            )
        )
        for table in ("x_posts", "x_messages", "x_stories", "x_mass_messages"):
            connection.execute(
                text(f"CREATE TABLE onlyfans.{table} (id bigint PRIMARY KEY)")
            )
    return postgres_engine


@pytest.fixture
def media_rows(stats_engine):
    with stats_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO onlyfans.media (id, category, size, downloaded) VALUES (1, 'image', 10, true), (2, ' video ', 20, false), (5, NULL, 0, false), (9, 'audio', 30, true), (13, 'other', 40, false)"
            )
        )
        connection.execute(
            text("INSERT INTO onlyfans.users VALUES (1, true), (2, false), (3, true)")
        )
        for table in ("x_posts", "x_messages", "x_stories", "x_mass_messages"):
            connection.execute(text(f"INSERT INTO onlyfans.{table} VALUES (1)"))
    try:
        yield stats_engine
    finally:
        with stats_engine.begin() as connection:
            connection.execute(text("DELETE FROM onlyfans.media"))
            connection.execute(text("DELETE FROM onlyfans.users"))
            for table in ("x_posts", "x_messages", "x_stories", "x_mass_messages"):
                connection.execute(text(f"DELETE FROM onlyfans.{table}"))


def _compute(session, progress=None):
    day, start, end = StatisticsService.utc_day_window(
        datetime(2026, 9, 6, tzinfo=timezone.utc)
    )
    return StatisticsService._compute_snapshot(
        session, "onlyfans", day, start, end, progress
    )


def test_statistics_budget_honors_shared_process_and_class_fallback(
    isolated_environment: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert StatisticsService._chunk_batch_size() == StatisticsService.CHUNK_BATCH_SIZE
    isolated_environment.write_text("ULTIMA_STATS_BATCH_SIZE=3\n")
    assert StatisticsService._chunk_batch_size() == 3
    monkeypatch.setenv("ULTIMA_STATS_BATCH_SIZE", "257")
    assert StatisticsService._chunk_batch_size() == 257
    monkeypatch.setenv("ULTIMA_STATS_BATCH_SIZE", "521579")
    assert StatisticsService._chunk_batch_size() == 521579
    monkeypatch.setattr(StatisticsService, "CHUNK_BATCH_SIZE", 17)
    monkeypatch.setenv("ULTIMA_STATS_BATCH_SIZE", "")
    assert StatisticsService._chunk_batch_size() == 17


@pytest.mark.parametrize("raw", ["0", "-1", "false", "1.5"])
def test_invalid_statistics_budget_fails_before_sql(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("ULTIMA_STATS_BATCH_SIZE", raw)

    def no_query(*args, **kwargs):
        pytest.fail("Invalid resource settings reached SQL")

    with pytest.raises(ValueError, match="positive integer"):
        _compute(SimpleNamespace(exec=no_query))


def test_native_snapshot_keeps_explicit_small_pages_and_initial_horizon(
    media_rows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ULTIMA_STATS_BATCH_SIZE", "2")
    fetched = []
    progress = []

    class RecordingSession(Session):
        def exec(self, statement, *args, **kwargs):
            result = super().exec(statement, *args, **kwargs)

            def all_rows():
                rows = result.all()
                fetched.append(len(rows))
                return rows

            return SimpleNamespace(one=result.one, all=all_rows)

    def append_during_scan(status):
        progress.append(status)
        if len(progress) == 1:
            with media_rows.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO onlyfans.media (id, category, size) VALUES (9007199254740993, 'video', 1000)"
                    )
                )

    with RecordingSession(media_rows) as session:
        session.execute(text("SET LOCAL search_path = onlyfans, management, public"))
        snapshot = _compute(session, append_during_scan)
        assert fetched == [2, 2, 1, 0]
        assert snapshot.total_media_count == 5
        assert snapshot.total_known_bytes == 100
        assert snapshot.image_media_count == 1
        assert snapshot.video_media_count == 1
        assert snapshot.audio_media_count == 1
        assert snapshot.other_media_count == 2
        assert snapshot.zero_size_media_count == 1
        assert snapshot.user_record_count == 3
        assert snapshot.performer_profile_count == 2
        assert snapshot.archived_content_count == 4
        assert snapshot.downloaded_media_count == 2
        assert all(status.max_id == 13 for status in progress)
        assert progress[-1].last_processed_id == 13
        assert progress[-1].progress_ratio == 1.0
        assert not session.identity_map
        next_snapshot = _compute(session)
        assert next_snapshot.total_media_count == 6
        assert next_snapshot.total_known_bytes == 1100


def test_native_empty_snapshot(stats_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ULTIMA_STATS_BATCH_SIZE", "1")
    with Session(stats_engine) as session:
        session.execute(text("SET LOCAL search_path = onlyfans, management, public"))
        snapshot = _compute(session)
    assert snapshot.total_media_count == 0
    assert snapshot.total_known_bytes == 0
    assert snapshot.user_record_count == 0
    assert snapshot.archived_content_count == 0
    assert snapshot.downloaded_media_count == 0
