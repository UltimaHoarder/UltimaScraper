"""One per-route guest budget shared by every worker, enforced through Redis."""

import asyncio
import time
from types import SimpleNamespace

import fakeredis.aioredis
import pytest
from ultima_scraper_api.managers import session_manager as sm

from ultima_scraper_backend.job_system import guest_route_rate_pool
from ultima_scraper_backend.job_system.guest_route_rate_pool import (
    GuestRouteRatePool,
    configure_route_rate_pool,
    schedule_key,
)

ROUTE = "http://user:secret@10.0.0.1:8080"
pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    return fakeredis.aioredis.FakeRedis()


async def _send_times(workers, count, rate_fraction=1.0):
    started = time.monotonic()
    times = []

    async def send(pool):
        assert await pool(ROUTE, rate_fraction)
        times.append(time.monotonic() - started)

    await asyncio.gather(*(send(workers[n % len(workers)]) for n in range(count)))
    return sorted(times)


async def test_the_route_rate_is_a_total_across_workers(client):
    # Three workers share one route at 100/s with a 50 ms burst (5 requests).
    workers = [GuestRouteRatePool(client, 100.0, burst_seconds=0.05) for _ in range(3)]
    times = await _send_times(workers, 30)
    # The burst goes at once; the other 25 are spaced 10 ms apart in total.
    assert times[4] < 0.03
    assert times[-1] == pytest.approx(0.25, abs=0.05)
    for index in range(5, 30, 5):
        # Never more than the burst plus the rate since the start.
        assert sum(t <= times[index] for t in times) <= 5 + 100 * times[index] + 2


async def test_a_429_cut_widens_only_that_workers_spacing(client):
    fast = GuestRouteRatePool(client, 100.0, burst_seconds=0.0)
    times = await _send_times([fast], 6, rate_fraction=0.5)
    # Half the rate: 20 ms apart.
    assert times[-1] == pytest.approx(0.1, abs=0.03)


async def test_redis_failure_falls_back_to_local_pacing(client, caplog):
    pool = GuestRouteRatePool(client, 10.0, burst_seconds=0.5)

    async def broken(*args, **kwargs):
        raise ConnectionError("redis down")

    pool._reserve = broken
    with caplog.at_level("WARNING", logger=guest_route_rate_pool.__name__):
        assert await pool(ROUTE, 1.0) is False
    assert "pacing per worker" in caplog.text


async def test_the_first_redis_failure_is_logged_right_after_boot(client, caplog, monkeypatch):
    # time.monotonic() counts from boot: a fresh machine must still log the first failure.
    monkeypatch.setattr(guest_route_rate_pool, "time", SimpleNamespace(monotonic=lambda: 5.0))
    pool = GuestRouteRatePool(client, 10.0, burst_seconds=0.5)

    async def broken(*args, **kwargs):
        raise ConnectionError("redis down")

    pool._reserve = broken
    with caplog.at_level("WARNING", logger=guest_route_rate_pool.__name__):
        assert await pool(ROUTE, 1.0) is False
    assert "pacing per worker" in caplog.text


def test_schedule_keys_never_contain_proxy_credentials():
    key = schedule_key(ROUTE)
    assert key.startswith(guest_route_rate_pool.KEY_PREFIX)
    assert "secret" not in key and "10.0.0.1" not in key


def test_configure_honours_the_switch_and_skips_api_processes(client, monkeypatch):
    try:
        monkeypatch.delenv("ULTIMA_GUEST_ROUTE_RATE_POOL", raising=False)
        assert configure_route_rate_pool(client, 35.0, worker_count=10, worker_index=1) is None
        assert sm._GUEST_ROUTE_RATE_POOL is None
        monkeypatch.setenv("ULTIMA_GUEST_ROUTE_RATE_POOL", "1")
        pool = configure_route_rate_pool(client, 35.0, worker_count=10, worker_index=1)
        assert pool is not None and pool.rate == 34.0  # minus the API share
        assert sm._GUEST_ROUTE_RATE_POOL is pool
        monkeypatch.setenv("ULTIMA_GUEST_ROUTE_RATE_POOL_RATE", "31")
        assert configure_route_rate_pool(client, 35.0, worker_count=10, worker_index=1).rate == 31.0
        monkeypatch.setenv("ULTIMA_GUEST_ROUTE_RATE_POOL_RATE", "50")  # never above the setting
        assert configure_route_rate_pool(client, 35.0, worker_count=10, worker_index=1).rate == 34.0
        monkeypatch.delenv("ULTIMA_GUEST_ROUTE_RATE_POOL_RATE")
        assert configure_route_rate_pool(client, 35.0, worker_count=10, worker_index=None) is None
        assert configure_route_rate_pool(None, 35.0, worker_count=10, worker_index=1) is None
    finally:
        sm.configure_guest_route_rate_pool(None)


async def test_session_paces_through_the_pool_and_falls_back(monkeypatch):
    calls = []
    answer = True

    async def pool(route_key, fraction):
        calls.append((route_key, fraction))
        return answer

    session = SimpleNamespace(
        auth=SimpleNamespace(guest=True),
        get_route_key=lambda: "route-key",
    )
    session._route_limiter = lambda: limiter
    limiter = sm._RouteRateLimiter(4.0)
    limiter.rate = 2.0  # after a 429 cut
    acquired = []

    async def local_acquire():
        acquired.append(True)

    limiter.acquire = local_acquire
    try:
        sm.configure_guest_route_rate_pool(pool)
        await sm.AuthedSession.acquire_route_rate(session)
        assert calls == [("route-key", 0.5)] and not acquired
        answer = False
        await sm.AuthedSession.acquire_route_rate(session)
        assert acquired == [True]
    finally:
        sm.configure_guest_route_rate_pool(None)
