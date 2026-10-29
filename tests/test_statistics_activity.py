from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from ultima_scraper_backend.api.routes import statistics as routes
from ultima_scraper_backend.services.statistics_activity_service import (
    ActivityPoint,
    ActivitySiteSeries,
)
from ultima_scraper_backend.services.statistics_activity_service import (
    StatisticsActivityService as Service,
)


@pytest.mark.parametrize(
    ("interval", "range_key", "expected_start", "expected_end"),
    [
        ("minute", "1h", "2026-01-01T00:35:00+00:00", "2026-01-01T01:35:00+00:00"),
        ("hour", "24h", "2025-12-31T02:00:00+00:00", "2026-01-01T02:00:00+00:00"),
        ("day", "7d", "2025-12-26T00:00:00+00:00", "2026-01-02T00:00:00+00:00"),
        ("month", "1y", "2025-02-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"),
        ("year", "all", None, "2027-01-01T00:00:00+00:00"),
    ],
)
def test_activity_utc_windows(interval, range_key, expected_start, expected_end):
    start, end = Service.window(
        interval, range_key, datetime(2026, 1, 1, 1, 34, 56, tzinfo=UTC)
    )
    assert (start.isoformat() if start else None) == expected_start
    assert end.isoformat() == expected_end


def test_activity_calendar_buckets_handle_leap_days_and_timezones():
    assert Service.advance_bucket(
        datetime(2024, 2, 1, tzinfo=UTC), "month"
    ) == datetime(2024, 3, 1, tzinfo=UTC)
    assert Service.floor_bucket(
        datetime(2026, 1, 1, 0, 30, tzinfo=timezone(timedelta(hours=2))), "day"
    ) == datetime(2025, 12, 31, tzinfo=UTC)
    assert Service.window("minute", "all", datetime.now(UTC))[0] is None


def test_account_date_and_post_timestamp_queries_use_distinct_fields():
    now = datetime(2026, 10, 11, 10, tzinfo=UTC)
    start = datetime(2026, 10, 11, tzinfo=UTC)
    statements = [
        Service.count_statement(metric, "day", field, start, now).compile(
            dialect=postgresql.dialect()
        )
        for metric, field in [
            ("accounts", "join_date"),
            ("posts", "join_date"),
        ]
    ]
    assert "users.join_date" in str(statements[0])
    assert "x_posts.created_at" in str(statements[1])
    assert "users" not in str(statements[1])
    assert "timezone" in str(statements[1])
    assert now in statements[1].params.values()
    assert start in statements[1].params.values()
    with pytest.raises(ValueError, match="join_date"):
        Service.count_statement("accounts", "day", "created_at", start, now)


@pytest.fixture
def activity_cache(monkeypatch):
    monkeypatch.setattr(Service, "_cache", OrderedDict())
    monkeypatch.setattr(Service, "_inflight", {})


@pytest.mark.asyncio
async def test_activity_requests_share_work_and_refresh_bypasses_cache(
    activity_cache, monkeypatch
):
    import asyncio

    calls = []

    def load(site, metric, interval, account_date, start, now, **kwargs):
        calls.append((site, account_date))
        return ActivitySiteSeries(
            site, True, None, 4, [ActivityPoint(start.isoformat(), 7)]
        )

    monkeypatch.setattr(Service, "_load_site", staticmethod(load))
    first, second = await asyncio.gather(
        *(
            Service.get_activity(["onlyfans"], "accounts", "day", "30d")
            for _ in range(2)
        )
    )
    assert first is second
    assert len(calls) == 1
    assert first.sites[0].undated_count == 4
    assert await Service.get_activity(["onlyfans"], "accounts", "day", "30d") is first
    await Service.get_activity(["onlyfans"], "accounts", "day", "30d", refresh=True)
    with pytest.raises(ValueError, match="join_date"):
        await Service.get_activity(
            ["onlyfans"], "accounts", "day", "30d", account_date="created_at"
        )
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_failed_activity_site_is_unknown_and_not_cached(
    activity_cache, monkeypatch
):
    calls = []

    def load(site, *args, **kwargs):
        calls.append(site)
        if site == "fansly":
            raise RuntimeError("offline")
        return ActivitySiteSeries(site, True, None, 0, [])

    monkeypatch.setattr(Service, "_load_site", staticmethod(load))
    result = await Service.get_activity(["onlyfans", "fansly"], "posts", "hour", "24h")
    assert result.sites[0].available is False
    assert result.sites[0].undated_count is None
    assert result.sites[1].available is True
    await Service.get_activity(["onlyfans", "fansly"], "posts", "hour", "24h")
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_activity_route_precedes_site_route_and_validates_bucket_choices(
    activity_cache, monkeypatch
):
    monkeypatch.setattr(routes, "_supported_sites", lambda: ["onlyfans"])
    monkeypatch.setattr(
        Service,
        "_load_site",
        staticmethod(
            lambda site, *args, **kwargs: ActivitySiteSeries(site, True, None, 0, [])
        ),
    )
    monkeypatch.setattr(
        Service,
        "_first_timestamp",
        staticmethod(lambda *args: datetime(2020, 1, 15, tzinfo=UTC)),
    )
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/statistics/activity?metric=accounts&interval=year&range=all"
        )
        assert response.status_code == 200
        assert response.json()["date_field"] == "join_date"
        custom = await client.get(
            "/statistics/activity?metric=posts&interval=minute&range=custom&start_date=2020-01-15&end_date=2026-01-20"
        )
        assert custom.status_code == 200
        assert custom.json()["interval"] == "minute"
        assert custom.json()["coverage_end_at"] == "2026-01-21T00:00:00+00:00"
        assert (
            await client.get("/statistics/activity?range=custom")
        ).status_code == 422
        assert (
            await client.get(
                "/statistics/activity?metric=posts&interval=minute&range=all"
            )
        ).status_code == 200
        posts = await client.get(
            "/statistics/activity?metric=posts&interval=hour&range=all&account_date=join_date&refresh=false"
        )
        assert posts.status_code == 200
        assert posts.json()["start_at"] == "2020-01-15T00:00:00+00:00"
        assert posts.json()["interval"] == "hour"
        assert posts.json()["bucket_count"] > 2000
        assert (
            await client.get("/statistics/activity?bucket_offset=-1")
        ).status_code == 422
        assert posts.json()["date_field"] == "created_at"
        default = await client.get("/statistics/activity")
        assert default.status_code == 200 and default.json()["range"] == "all"
        assert (
            await client.get("/statistics/activity?account_date=created_at")
        ).status_code == 422
        assert (
            await client.get(
                "/statistics/activity?metric=accounts&interval=minute&range=1h"
            )
        ).status_code == 422
        assert (
            await client.get("/statistics/activity?site=missing")
        ).status_code == 404


@pytest.mark.asyncio
async def test_custom_activity_dates_preserve_the_interval_and_page_the_full_range(
    activity_cache, monkeypatch
):
    calls = []

    def load(site, metric, interval, account_date, start, cutoff, **kwargs):
        calls.append((interval, start, cutoff))
        return ActivitySiteSeries(site, True, None, 0, [])

    monkeypatch.setattr(Service, "_load_site", staticmethod(load))
    result = await Service.get_activity(
        ["onlyfans"],
        "posts",
        "minute",
        "custom",
        start_date=date(2020, 1, 15),
        end_date=date(2026, 1, 20),
    )
    assert result.interval == "minute"
    assert result.start_at == "2020-01-15T00:00:00+00:00"
    assert result.end_at == "2026-01-21T00:00:00+00:00"
    assert result.coverage_start_at == "2020-01-15T00:00:00+00:00"
    assert result.coverage_end_at == "2026-01-21T00:00:00+00:00"
    assert result.bucket_count > Service.MAX_BUCKETS
    assert result.window_end_at == result.end_at
    assert calls[0] == (
        "minute",
        datetime.fromisoformat(result.window_start_at),
        datetime(2026, 1, 21, tzinfo=UTC),
    )
    assert (
        Service.bucket_count(
            datetime.fromisoformat(result.window_start_at),
            datetime.fromisoformat(result.window_end_at),
            "minute",
        )
        == Service.MAX_BUCKETS
    )
    with pytest.raises(ValueError, match="Custom ranges"):
        await Service.get_activity(["onlyfans"], "posts", "day", "custom")
    with pytest.raises(ValueError, match="Custom ranges"):
        await Service.get_activity(
            ["onlyfans"],
            "posts",
            "day",
            "custom",
            start_date=date(2026, 1, 20),
            end_date=date(2020, 1, 1),
        )
    second = await Service.get_activity(
        ["onlyfans"],
        "posts",
        "minute",
        "custom",
        start_date=date(2020, 1, 15),
        end_date=date(2026, 1, 21),
    )
    assert second is not result and len(calls) == 2


@pytest.mark.asyncio
async def test_all_history_is_bounded_without_losing_the_first_dated_record(
    activity_cache, monkeypatch
):
    first = datetime(2000, 2, 15, tzinfo=UTC)
    monkeypatch.setattr(Service, "_first_timestamp", staticmethod(lambda *args: first))
    calls = []

    def load(site, metric, interval, account_date, start, cutoff, **kwargs):
        calls.append((interval, account_date, start, cutoff))
        return ActivitySiteSeries(
            site,
            True,
            None,
            1,
            [ActivityPoint(Service.floor_bucket(first, interval).isoformat(), 2)],
        )

    monkeypatch.setattr(Service, "_load_site", staticmethod(load))
    result = await Service.get_activity(["onlyfans"], "accounts", "day", "all")
    assert result.interval == "day"
    assert result.start_at == "2000-02-15T00:00:00+00:00"
    assert result.coverage_end_at == result.calculated_at
    assert result.sites[0].points[0].count == 2
    assert calls[0][1:3] == (
        "join_date",
        datetime.fromisoformat(result.window_start_at),
    )
    assert result.bucket_offset > 0
    first_page = await Service.get_activity(
        ["onlyfans"], "accounts", "day", "all", bucket_offset=0
    )
    assert first_page.interval == "day"
    assert first_page.window_start_at == first_page.start_at
    assert first_page.bucket_offset == 0
