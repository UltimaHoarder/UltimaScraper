from collections import OrderedDict
from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
from ultima_scraper_backend.api.routes import statistics as routes
from ultima_scraper_backend.services.statistics_seasonality_service import (
    SeasonalSite,
)
from ultima_scraper_backend.services.statistics_seasonality_service import (
    StatisticsSeasonalityService as Service,
)


def test_calendar_exposure_accounts_for_leap_months_and_unobserved_bins():
    start, end = date(2024, 2, 1), date(2024, 3, 1)
    assert Service.exposures(start, end, "hour") == [29.0] * 24
    assert sum(Service.exposures(start, end, "weekday")) == 29
    months = Service.exposures(start, end, "month")
    assert months[1] == pytest.approx(1)
    assert months[0] == 0
    days = Service.exposures(date(2024, 1, 1), date(2024, 3, 1), "monthday")
    assert days[0] == 2 and days[28] == 2 and days[29] == 1 and days[30] == 1
    assert Service.exposures(date(2024, 2, 15), end, "month")[1] == pytest.approx(
        15 / 29
    )


def test_seasonality_groups_source_timestamps_in_utc_with_exact_date_bounds():
    start, end = datetime(2024, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)
    statement = Service.count_statement(
        "accounts", "weekday", "join_date", start, end
    ).compile(dialect=postgresql.dialect())
    assert "users.join_date" in str(statement)
    assert "timezone" in str(statement)
    assert "isodow" in str(statement)
    assert start in statement.params.values() and end in statement.params.values()


@pytest.mark.asyncio
async def test_seasonality_coalesces_work_and_keeps_failed_sites_unknown(monkeypatch):
    import asyncio

    monkeypatch.setattr(Service, "_cache", OrderedDict())
    monkeypatch.setattr(Service, "_inflight", {})
    calls = []

    def load(site, *args):
        calls.append(site)
        return SeasonalSite(site, True, [3] * 7)

    monkeypatch.setattr(Service, "_load_site", staticmethod(load))
    args = (
        ["onlyfans"],
        "posts",
        "weekday",
        "join_date",
        date(2024, 1, 1),
        date(2024, 1, 7),
    )
    first, second = await asyncio.gather(
        Service.get_seasonality(*args), Service.get_seasonality(*args)
    )
    assert first is second and len(calls) == 1
    assert first.exposures == [1] * 7
    assert first.start_date == "2024-01-01" and first.end_date == "2024-01-07"

    def fail(*args):
        raise RuntimeError("offline")

    monkeypatch.setattr(Service, "_load_site", staticmethod(fail))
    failed = await Service.get_seasonality(["fansly"], *args[1:])
    assert not failed.sites[0].available and failed.sites[0].counts == []
    assert len(Service._cache) == 1


@pytest.mark.asyncio
async def test_seasonality_endpoint_validates_dates_cycle_and_site(monkeypatch):
    monkeypatch.setattr(routes, "_supported_sites", lambda: ["onlyfans"])
    monkeypatch.setattr(Service, "_cache", OrderedDict())
    monkeypatch.setattr(Service, "_inflight", {})
    monkeypatch.setattr(
        Service,
        "_load_site",
        staticmethod(lambda site, *args: SeasonalSite(site, True, [0] * 7)),
    )
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/statistics/seasonality?start_date=2024-01-01&end_date=2024-01-07"
        )
        assert response.status_code == 200
        assert response.json()["exposures"] == [1] * 7
        assert (
            await client.get("/statistics/seasonality?cycle=invalid")
        ).status_code == 422
        assert (
            await client.get("/statistics/seasonality?site=missing")
        ).status_code == 404
        assert (
            await client.get(
                "/statistics/seasonality?start_date=2024-02-01&end_date=2024-01-01"
            )
        ).status_code == 422


@pytest.mark.asyncio
async def test_default_seasonality_starts_at_earliest_join_date_and_rejects_archive_arrival(
    monkeypatch,
):
    monkeypatch.setattr(Service, "_cache", OrderedDict())
    monkeypatch.setattr(Service, "_inflight", {})
    starts = []

    def load(site, metric, cycle, account_date, start, end):
        starts.append(start)
        return SeasonalSite(site, True, [1] * 7, first_date="2000-01-01")

    monkeypatch.setattr(Service, "_load_site", staticmethod(load))
    result = await Service.get_seasonality(["onlyfans"], "accounts", "weekday")
    assert result.start_date == "2000-01-01" and result.date_field == "join_date"
    assert starts == [None]
    assert (
        sum(result.exposures)
        == (date.fromisoformat(result.end_date) - date(2000, 1, 1)).days + 1
    )
    with pytest.raises(ValueError, match="join_date"):
        await Service.get_seasonality(["onlyfans"], "accounts", "weekday", "created_at")
