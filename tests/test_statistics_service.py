import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from ultima_scraper_backend.services import statistics_service as statistics_service_module
from ultima_scraper_backend.services.statistics_service import (
    DailyStatisticsSnapshot,
    KnownUserMediaStats,
    SiteStatisticsAvailability,
    StatisticsService,
)


def _snapshot(**overrides: int | float | str) -> DailyStatisticsSnapshot:
    base = DailyStatisticsSnapshot(
        site="onlyfans",
        bucket_date="2026-03-08",
        bucket_started_at="2026-03-08T00:00:00+00:00",
        bucket_ends_at="2026-03-09T00:00:00+00:00",
        calculated_at="2026-03-08T00:00:05+00:00",
        total_media_count=100,
        sized_media_count=75,
        zero_size_media_count=25,
        image_media_count=40,
        image_sized_count=30,
        video_media_count=30,
        video_sized_count=24,
        audio_media_count=10,
        audio_sized_count=8,
        other_media_count=20,
        other_sized_count=13,
        total_known_bytes=10_000,
        avg_media_size_bytes=100,
        avg_image_size_bytes=50,
        avg_video_size_bytes=200,
        avg_audio_size_bytes=25,
        avg_other_size_bytes=80,
        size_coverage_ratio=0.75,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_estimate_profile_size_uses_category_averages_and_remaining_media() -> None:
    snapshot = _snapshot()

    estimated = StatisticsService.estimate_profile_size(
        media_count=8,
        image_count=3,
        video_count=2,
        audio_count=1,
        stream_count=1,
        snapshot=snapshot,
    )

    assert estimated == (3 * 50) + (2 * 200) + (1 * 25) + (1 * 200) + (1 * 80)


def test_estimate_profile_size_falls_back_to_overall_average() -> None:
    snapshot = _snapshot(
        avg_image_size_bytes=0,
        avg_video_size_bytes=0,
        avg_audio_size_bytes=0,
        avg_other_size_bytes=0,
        avg_media_size_bytes=128,
    )

    estimated = StatisticsService.estimate_profile_size(
        media_count=4,
        image_count=1,
        video_count=1,
        audio_count=1,
        stream_count=0,
        snapshot=snapshot,
    )

    assert estimated == 4 * 128


def test_seconds_until_next_utc_midnight_uses_utc_boundary() -> None:
    now = datetime(2026, 3, 8, 23, 59, 30, tzinfo=timezone.utc)
    assert StatisticsService.seconds_until_next_utc_midnight(now) == 30


def test_statistics_history_ranges_include_today() -> None:
    now = datetime(2026, 3, 8, 23, 0, tzinfo=timezone.utc)

    assert StatisticsService.history_date_window("7d", now) == (
        date(2026, 3, 2),
        date(2026, 3, 8),
    )
    assert StatisticsService.history_date_window("30d", now) == (
        date(2026, 2, 7),
        date(2026, 3, 8),
    )
    assert StatisticsService.history_date_window("all", now) == (
        None,
        date(2026, 3, 8),
    )


def test_legacy_statistics_cache_payload_defaults_inventory_metrics_to_unknown() -> None:
    payload = json.loads(_snapshot().to_cache_payload())
    for field in (
        "user_record_count",
        "performer_profile_count",
        "archived_content_count",
        "downloaded_media_count",
    ):
        payload.pop(field)

    restored = DailyStatisticsSnapshot.from_cache_payload(json.dumps(payload))

    assert restored.user_record_count is None
    assert restored.performer_profile_count is None
    assert restored.archived_content_count is None
    assert restored.downloaded_media_count is None


class _FakeRow:
    _mapping = {"value": 2048}

    def __getitem__(self, index: int) -> int:
        if index != 0:
            raise IndexError(index)
        return 2048


class _FakeExecResult:
    def one(self) -> _FakeRow:
        return _FakeRow()


class _FakeSession:
    def exec(self, _query: object) -> _FakeExecResult:
        return _FakeExecResult()


def test_get_actual_media_size_handles_single_column_row_results() -> None:
    session = _FakeSession()
    assert StatisticsService.get_actual_media_size(session, 123) == 2048


def _snapshot_model(**overrides: int | float | str) -> SimpleNamespace:
    snapshot = _snapshot(**overrides)
    return SimpleNamespace(
        bucket_date=date.fromisoformat(snapshot.bucket_date),
        bucket_started_at=datetime.fromisoformat(snapshot.bucket_started_at),
        bucket_ends_at=datetime.fromisoformat(snapshot.bucket_ends_at),
        calculated_at=datetime.fromisoformat(snapshot.calculated_at),
        total_media_count=snapshot.total_media_count,
        sized_media_count=snapshot.sized_media_count,
        zero_size_media_count=snapshot.zero_size_media_count,
        image_media_count=snapshot.image_media_count,
        image_sized_count=snapshot.image_sized_count,
        video_media_count=snapshot.video_media_count,
        video_sized_count=snapshot.video_sized_count,
        audio_media_count=snapshot.audio_media_count,
        audio_sized_count=snapshot.audio_sized_count,
        other_media_count=snapshot.other_media_count,
        other_sized_count=snapshot.other_sized_count,
        total_known_bytes=snapshot.total_known_bytes,
        avg_media_size_bytes=snapshot.avg_media_size_bytes,
        avg_image_size_bytes=snapshot.avg_image_size_bytes,
        avg_video_size_bytes=snapshot.avg_video_size_bytes,
        avg_audio_size_bytes=snapshot.avg_audio_size_bytes,
        avg_other_size_bytes=snapshot.avg_other_size_bytes,
        size_coverage_ratio=snapshot.size_coverage_ratio,
    )


class _WrappedSnapshotRow:
    def __init__(self, model: SimpleNamespace) -> None:
        self._model = model
        self._mapping = {"statistics": model}

    def __getitem__(self, index: int) -> SimpleNamespace:
        if index != 0:
            raise IndexError(index)
        return self._model


def test_unwrap_snapshot_model_handles_wrapped_model_rows() -> None:
    model = _snapshot_model()
    row = _WrappedSnapshotRow(model)

    assert StatisticsService._unwrap_snapshot_model(row) is model


@pytest.mark.asyncio
async def test_get_statistics_availability_uses_latest_snapshot_while_today_builds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_snapshot = _snapshot(
        bucket_date="2026-03-07",
        bucket_started_at="2026-03-07T00:00:00+00:00",
        bucket_ends_at="2026-03-08T00:00:00+00:00",
        calculated_at="2026-03-07T00:00:05+00:00",
    )

    async def _fake_cached_snapshot(*_args: object, **_kwargs: object) -> None:
        return None

    async def _fake_started(*_args: object, **_kwargs: object) -> bool:
        return True

    async def _fake_building(*_args: object, **_kwargs: object) -> bool:
        return False

    async def _fake_to_thread(func: object, /, *args: object, **kwargs: object) -> object:
        assert callable(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(StatisticsService, "_get_cached_snapshot", _fake_cached_snapshot)
    monkeypatch.setattr(StatisticsService, "_load_latest_snapshot_sync", lambda *_args, **_kwargs: stale_snapshot)
    monkeypatch.setattr(StatisticsService, "ensure_daily_statistics_started", _fake_started)
    monkeypatch.setattr(StatisticsService, "_is_build_in_progress", _fake_building)
    monkeypatch.setattr(statistics_service_module.asyncio, "to_thread", _fake_to_thread)

    availability = await StatisticsService.get_statistics_availability(
        "onlyfans",
        schedule_if_missing=True,
        now=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert availability.snapshot is not None
    assert availability.snapshot.bucket_date == "2026-03-07"
    assert availability.snapshot_source == "latest"
    assert availability.is_current is False
    assert availability.is_building is True


@pytest.mark.asyncio
async def test_get_statistics_availability_forces_rebuild_for_legacy_current_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_snapshot = _snapshot()
    started_options: list[bool] = []

    async def _fake_cached_snapshot(*_args: object, **_kwargs: object):
        return legacy_snapshot

    async def _fake_started(*_args: object, **kwargs: object) -> bool:
        started_options.append(bool(kwargs.get("force_refresh")))
        return True

    async def _fake_building(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr(StatisticsService, "_get_cached_snapshot", _fake_cached_snapshot)
    monkeypatch.setattr(StatisticsService, "ensure_daily_statistics_started", _fake_started)
    monkeypatch.setattr(StatisticsService, "_is_build_in_progress", _fake_building)

    availability = await StatisticsService.get_statistics_availability(
        "onlyfans",
        schedule_if_missing=True,
        now=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
    )

    assert availability.is_current is True
    assert availability.is_building is True
    assert started_options == [True]


@pytest.mark.asyncio
async def test_resolve_user_size_uses_latest_available_snapshot_for_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_snapshot = _snapshot(
        bucket_date="2026-03-07",
        bucket_started_at="2026-03-07T00:00:00+00:00",
        bucket_ends_at="2026-03-08T00:00:00+00:00",
        calculated_at="2026-03-07T00:00:05+00:00",
    )

    async def _fake_availability(*_args: object, **_kwargs: object) -> SiteStatisticsAvailability:
        return SiteStatisticsAvailability(
            site="onlyfans",
            target_bucket_date="2026-03-08",
            snapshot=stale_snapshot,
            snapshot_source="latest",
            is_current=False,
            is_building=True,
        )

    monkeypatch.setattr(StatisticsService, "get_actual_media_size", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        StatisticsService,
        "get_known_media_stats",
        lambda *_args, **_kwargs: KnownUserMediaStats(),
    )
    monkeypatch.setattr(StatisticsService, "get_statistics_availability", _fake_availability)

    resolved = await StatisticsService.resolve_user_size(
        session=object(),
        user_id=123,
        site="onlyfans",
        stored_size=0,
        media_count=4,
        image_count=1,
        video_count=1,
        audio_count=1,
        stream_count=0,
        redis_manager=None,
    )

    assert resolved.size == 0
    assert resolved.display_size == 355
    assert resolved.estimated_size == 355
    assert resolved.size_source == "estimated"
    assert resolved.statistics_bucket_date == "2026-03-07"


@pytest.mark.asyncio
async def test_resolve_user_size_uses_preloaded_statistics_without_async_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    availability = SiteStatisticsAvailability(
        site="onlyfans",
        target_bucket_date="2026-03-08",
        snapshot=_snapshot(),
        snapshot_source="current",
        is_current=True,
        is_building=False,
    )

    async def fail_if_loaded(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("statistics were already loaded before the transaction")

    monkeypatch.setattr(
        StatisticsService,
        "get_actual_media_size",
        lambda *_args, **_kwargs: 0,
    )
    monkeypatch.setattr(
        StatisticsService,
        "get_statistics_availability",
        fail_if_loaded,
    )

    resolved = await StatisticsService.resolve_user_size(
        session=object(),
        user_id=123,
        site="onlyfans",
        stored_size=0,
        media_count=2,
        image_count=1,
        video_count=1,
        audio_count=0,
        stream_count=0,
        statistics_availability=availability,
    )

    assert resolved.display_size == 250
    assert resolved.statistics_bucket_date == "2026-03-08"


@pytest.mark.asyncio
async def test_resolve_user_size_adds_confirmed_bytes_to_remaining_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(
        bucket_date="2026-03-07",
        bucket_started_at="2026-03-07T00:00:00+00:00",
        bucket_ends_at="2026-03-08T00:00:00+00:00",
        calculated_at="2026-03-07T00:00:05+00:00",
    )

    async def _fake_availability(*_args: object, **_kwargs: object) -> SiteStatisticsAvailability:
        return SiteStatisticsAvailability(
            site="onlyfans",
            target_bucket_date="2026-03-08",
            snapshot=snapshot,
            snapshot_source="latest",
            is_current=False,
            is_building=True,
        )

    monkeypatch.setattr(
        StatisticsService,
        "get_known_media_stats",
        lambda *_args, **_kwargs: KnownUserMediaStats(
            total_size=500,
            total_count=2,
            image_count=1,
            video_count=1,
            audio_count=0,
        ),
    )
    monkeypatch.setattr(StatisticsService, "get_statistics_availability", _fake_availability)

    resolved = await StatisticsService.resolve_user_size(
        session=object(),
        user_id=123,
        site="onlyfans",
        stored_size=500,
        media_count=6,
        image_count=1,
        video_count=2,
        audio_count=1,
        stream_count=0,
        redis_manager=None,
    )

    assert resolved.size == 500
    assert resolved.display_size == 500
    assert resolved.estimated_size == 885
    assert resolved.size_source == "actual"
    assert resolved.statistics_bucket_date == "2026-03-07"
