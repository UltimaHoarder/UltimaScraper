from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from ultima_scraper_backend.api import app as app_module
from ultima_scraper_db_archive import global_db


@pytest.mark.asyncio
async def test_statistics_refresh_waits_for_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_scheduled(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("statistics must not be scheduled before setup")

    monkeypatch.setattr(global_db, "is_setup_complete", lambda: False)
    monkeypatch.setattr(
        app_module.StatisticsService,
        "get_statistics_availability",
        fail_if_scheduled,
    )

    setup_complete = await app_module._refresh_daily_statistics_once(
        SimpleNamespace(redis=object())
    )

    assert setup_complete is False


@pytest.mark.asyncio
async def test_statistics_refresh_schedules_missing_daily_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = object()
    calls: list[tuple[str, object | None, bool]] = []

    async def record_availability(
        site: str,
        *,
        redis_manager: object | None = None,
        schedule_if_missing: bool = False,
    ) -> SimpleNamespace:
        calls.append((site, redis_manager, schedule_if_missing))
        return SimpleNamespace()

    monkeypatch.setattr(global_db, "is_setup_complete", lambda: True)
    monkeypatch.setattr(app_module, "get_enabled_sites", lambda: ["OnlyFans", "Fansly"])
    monkeypatch.setattr(
        app_module.StatisticsService,
        "get_statistics_availability",
        record_availability,
    )

    setup_complete = await app_module._refresh_daily_statistics_once(
        SimpleNamespace(redis=redis)
    )

    assert setup_complete is True
    assert calls == [
        ("onlyfans", redis, True),
        ("fansly", redis, True),
    ]


@pytest.mark.asyncio
async def test_statistics_refresh_loop_rechecks_after_setup_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_results = iter([False, True])
    delays: list[int] = []

    async def refresh_once(_backend: object) -> bool:
        return next(refresh_results)

    async def record_sleep(delay: int) -> None:
        delays.append(delay)
        if len(delays) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_module, "_refresh_daily_statistics_once", refresh_once)
    monkeypatch.setattr(app_module.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(
        app_module.StatisticsService,
        "seconds_until_next_utc_midnight",
        lambda: 3_600,
    )

    with pytest.raises(asyncio.CancelledError):
        await app_module._statistics_refresh_loop(object())

    assert delays == [
        app_module._STATISTICS_SETUP_RETRY_SECONDS,
        app_module._STATISTICS_REFRESH_POLL_SECONDS,
    ]
