"""Real UTC aggregation against an isolated temporary PostgreSQL cluster."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
import test_mps_manifest as postgres_fixtures
from sqlalchemy import event, text
from sqlmodel import Session
from ultima_scraper_backend.services import statistics_activity_service as module
from ultima_scraper_backend.services.statistics_activity_service import (
    StatisticsActivityService as Service,
)

postgres_engine = postgres_fixtures.postgres_engine


@pytest.fixture(scope="module")
def activity_engine(postgres_engine):
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE onlyfans.users ADD COLUMN join_date timestamptz, ADD COLUMN created_at timestamptz"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE onlyfans.x_posts (id bigint PRIMARY KEY, created_at timestamptz NOT NULL)"
            )
        )
        connection.execute(
            text("""INSERT INTO onlyfans.users (id, join_date, created_at) VALUES
            (1, '2024-02-29 23:59:00+00', '2026-10-11 09:00:00+00'),
            (2, '2024-03-01 00:59:00+01', '2026-10-11 09:01:00+00'),
            (3, NULL, '2026-10-11 09:01:00+00'),
            (4, '2025-01-01 00:00:00+00', '2026-10-11 09:02:00+00'),
            (5, '2027-01-01 00:00:00+00', '2027-01-01 00:00:00+00'),
            (6, '0001-01-01 00:00:00+00', '2026-10-11 09:02:00+00')""")
        )
        connection.execute(
            text("""INSERT INTO onlyfans.x_posts VALUES
            (1, '2026-10-11 08:59:59+00'), (2, '2026-10-11 10:00:00+01'),
            (3, '2026-10-11 09:00:59+00'), (4, '2026-10-11 09:01:00+00'),
            (5, '2026-10-11 10:00:00+00'), (6, '0001-01-01 00:00:00+00')""")
        )
    return postgres_engine


@pytest.fixture
def manager(activity_engine, monkeypatch):
    class ActivitySession(Session):
        pass

    @event.listens_for(ActivitySession, "after_begin")
    def configure(session, transaction, connection):
        connection.execute(text("SET LOCAL search_path = onlyfans, public"))
        connection.execute(text("SET LOCAL timezone = 'America/Los_Angeles'"))

    manager = SimpleNamespace(get_session=lambda: ActivitySession(activity_engine))
    monkeypatch.setattr(
        module,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(get_or_create_manager=lambda site: manager),
    )
    return manager


def test_account_join_month_and_year_counts_use_join_date(manager):
    now = datetime(2026, 10, 11, 9, 5, tzinfo=UTC)
    months = Service._load_site("onlyfans", "accounts", "month", "join_date", None, now)
    assert [(point.bucket_started_at, point.count) for point in months.points] == [
        ("2024-02-01T00:00:00+00:00", 2),
        ("2025-01-01T00:00:00+00:00", 1),
    ]
    assert months.undated_count == 2
    years = Service._load_site("onlyfans", "accounts", "year", "join_date", None, now)
    assert [point.count for point in years.points] == [2, 1]
    with pytest.raises(ValueError, match="join_date"):
        Service._load_site("onlyfans", "accounts", "day", "created_at", None, now)
    assert Service._first_timestamp(
        "onlyfans", "accounts", "join_date", now
    ) == datetime(2024, 2, 29, 23, 59, tzinfo=UTC)


def test_post_minute_hour_day_counts_use_utc_and_exclude_future_records(manager):
    now = datetime(2026, 10, 11, 9, 5, tzinfo=UTC)
    minutes = Service._load_site(
        "onlyfans",
        "posts",
        "minute",
        "join_date",
        datetime(2026, 10, 11, 9, tzinfo=UTC),
        now,
    )
    assert [(point.bucket_started_at, point.count) for point in minutes.points] == [
        ("2026-10-11T09:00:00+00:00", 2),
        ("2026-10-11T09:01:00+00:00", 1),
    ]
    hours = Service._load_site(
        "onlyfans",
        "posts",
        "hour",
        "join_date",
        datetime(2026, 10, 11, 9, tzinfo=UTC),
        now,
    )
    assert [(point.bucket_started_at, point.count) for point in hours.points] == [
        ("2026-10-11T09:00:00+00:00", 3)
    ]
    days = Service._load_site(
        "onlyfans", "posts", "day", "join_date", datetime(2026, 10, 11, tzinfo=UTC), now
    )
    assert [point.count for point in days.points] == [4]


@pytest.mark.asyncio
async def test_seasonality_hour_weekday_and_month_bins_are_utc_with_exact_bounds(
    manager, monkeypatch
):
    from ultima_scraper_backend.services import (
        statistics_seasonality_service as seasonal,
    )

    monkeypatch.setattr(
        seasonal,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(get_or_create_manager=lambda site: manager),
    )
    service = seasonal.StatisticsSeasonalityService
    start, end = datetime(2024, 2, 1, tzinfo=UTC), datetime(2024, 3, 1, tzinfo=UTC)
    hours = service._load_site("onlyfans", "accounts", "hour", "join_date", start, end)
    assert hours.counts[23] == 2 and sum(hours.counts) == 2
    weekdays = service._load_site(
        "onlyfans", "accounts", "weekday", "join_date", start, end
    )
    assert weekdays.counts[3] == 2  # UTC Thursday, February 29
    months = service._load_site(
        "onlyfans", "accounts", "month", "join_date", start, end
    )
    assert months.counts[1] == 2 and months.counts[2] == 0
    monthdays = service._load_site(
        "onlyfans", "accounts", "monthday", "join_date", start, end
    )
    assert monthdays.counts[28] == 2 and monthdays.counts[30] == 0
    assert service.exposures(date(2024, 2, 1), date(2024, 3, 1), "month")[
        1
    ] == pytest.approx(1)
    posts = service._load_site(
        "onlyfans",
        "posts",
        "hour",
        "join_date",
        datetime(2026, 10, 11, 9, tzinfo=UTC),
        datetime(2026, 10, 11, 10, tzinfo=UTC),
    )
    assert posts.counts[9] == 3 and sum(posts.counts) == 3


@pytest.mark.asyncio
async def test_default_full_history_uses_earliest_join_date_not_archive_creation(
    manager, monkeypatch
):
    from collections import OrderedDict

    from ultima_scraper_backend.services import (
        statistics_seasonality_service as seasonal,
    )

    monkeypatch.setattr(Service, "_cache", OrderedDict())
    monkeypatch.setattr(Service, "_inflight", {})
    result = await Service.get_activity(["onlyfans"], "accounts", "day", "all")
    assert result.start_at == "2024-02-29T00:00:00+00:00"
    assert result.date_field == "join_date"
    assert sum(point.count for point in result.sites[0].points) == 3
    assert result.sites[0].undated_count == 2
    monkeypatch.setattr(
        seasonal,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(get_or_create_manager=lambda site: manager),
    )
    monkeypatch.setattr(seasonal.StatisticsSeasonalityService, "_cache", OrderedDict())
    monkeypatch.setattr(seasonal.StatisticsSeasonalityService, "_inflight", {})
    profile = await seasonal.StatisticsSeasonalityService.get_seasonality(
        ["onlyfans"], "accounts", "month"
    )
    assert profile.start_date == "2024-02-29"
    assert sum(profile.sites[0].counts) == 3


@pytest.mark.asyncio
async def test_all_post_history_and_seasonality_exclude_year_one_placeholders(
    manager, monkeypatch
):
    from collections import OrderedDict

    from ultima_scraper_backend.services import (
        statistics_seasonality_service as seasonal,
    )

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 12, 9, 5, tzinfo=UTC)

    monkeypatch.setattr(module, "datetime", FixedDatetime)
    monkeypatch.setattr(Service, "_cache", OrderedDict())
    monkeypatch.setattr(Service, "_inflight", {})
    result = await Service.get_activity(["onlyfans"], "posts", "hour", "all")
    assert result.start_at == "2026-10-11T08:00:00+00:00"
    assert result.interval == "hour"
    assert sum(point.count for point in result.sites[0].points) == 5
    assert result.sites[0].undated_count == 1

    monkeypatch.setattr(seasonal, "datetime", FixedDatetime)
    monkeypatch.setattr(
        seasonal,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(get_or_create_manager=lambda site: manager),
    )
    monkeypatch.setattr(seasonal.StatisticsSeasonalityService, "_cache", OrderedDict())
    monkeypatch.setattr(seasonal.StatisticsSeasonalityService, "_inflight", {})
    profile = await seasonal.StatisticsSeasonalityService.get_seasonality(
        ["onlyfans"], "posts", "hour"
    )
    assert profile.start_date == "2026-10-11"
    assert sum(profile.sites[0].counts) == 5


@pytest.mark.asyncio
async def test_exact_hour_and_minute_windows_keep_full_totals_and_cumulative_prefix(
    activity_engine, manager, monkeypatch
):
    from collections import OrderedDict

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 12, 9, 5, tzinfo=UTC)

    monkeypatch.setattr(module, "datetime", FixedDatetime)
    monkeypatch.setattr(Service, "_cache", OrderedDict())
    monkeypatch.setattr(Service, "_inflight", {})
    with activity_engine.begin() as connection:
        connection.execute(text("INSERT INTO onlyfans.x_posts VALUES (7, '2016-07-15 14:06:51+00')"))
    try:
        for interval in ("hour", "minute"):
            latest = await Service.get_activity(["onlyfans"], "posts", interval, "all")
            assert latest.interval == interval
            assert latest.bucket_count > Service.MAX_BUCKETS
            assert latest.sites[0].total_count == 6
            assert latest.sites[0].before_window_count == 1
            assert sum(point.count for point in latest.sites[0].points) == 5
            assert latest.sites[0].undated_count == 1
            earliest = await Service.get_activity(
                ["onlyfans"], "posts", interval, "all", bucket_offset=0
            )
            assert earliest.window_start_at == earliest.start_at
            assert earliest.sites[0].total_count == 6
            assert earliest.sites[0].before_window_count == 0
            assert sum(point.count for point in earliest.sites[0].points) == 1
    finally:
        with activity_engine.begin() as connection:
            connection.execute(text("DELETE FROM onlyfans.x_posts WHERE id = 7"))
