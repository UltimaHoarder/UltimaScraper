"""Proxy connection limits are totals across workers, enforced with Redis permits."""

import asyncio
from types import SimpleNamespace

import fakeredis.aioredis
import pytest
from ultima_scraper_api.managers import session_manager as sm
from ultima_scraper_backend.job_system import guest_route_permits
from ultima_scraper_backend.job_system.guest_route_permits import (
    GuestRoutePermits,
    configure_route_permits,
    permit_key,
)

PROXY = "http://user:secret@10.0.0.1:8080"


@pytest.fixture
def client():
    return fakeredis.aioredis.FakeRedis()


@pytest.mark.asyncio
async def test_a_proxys_connections_are_a_total_across_workers(client):
    # Two workers share one proxy with 2 connections.
    workers = [GuestRoutePermits(client, {PROXY: 2}) for _ in range(2)]
    in_flight, peak, done = 0, 0, 0

    async def send(permits):
        nonlocal in_flight, peak, done
        async with permits(PROXY):
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            done += 1

    await asyncio.gather(*(send(workers[n % 2]) for n in range(12)))
    assert done == 12 and peak == 2
    assert await client.zcard(permit_key(PROXY)) == 0  # every permit released


@pytest.mark.asyncio
async def test_a_permit_is_released_when_the_send_fails_or_is_cancelled(client):
    permits = GuestRoutePermits(client, {PROXY: 1})
    with pytest.raises(RuntimeError):
        async with permits(PROXY):
            raise RuntimeError("429")
    holder_entered = asyncio.Event()

    async def holder():
        async with permits(PROXY):
            holder_entered.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(holder())
    await holder_entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with asyncio.timeout(1):
        async with permits(PROXY):
            pass


@pytest.mark.asyncio
async def test_a_dead_workers_permit_expires(client):
    permits = GuestRoutePermits(client, {PROXY: 1}, lease_seconds=0.05)
    assert await permits.acquire(permit_key(PROXY), 1)  # never released
    async with asyncio.timeout(1):
        async with permits(PROXY):
            pass


@pytest.mark.asyncio
async def test_unknown_routes_and_redis_failures_do_not_block_sends(client, caplog):
    permits = GuestRoutePermits(client, {PROXY: 1})
    async with permits("http://not-configured:1"):
        assert await client.keys("*") == []

    async def broken(*args, **kwargs):
        raise ConnectionError("redis down")

    permits._acquire = broken
    with caplog.at_level("WARNING", logger=guest_route_permits.__name__):
        async with permits(PROXY):
            pass  # fails open
    assert "sending without them" in caplog.text


def test_permit_keys_never_contain_proxy_credentials():
    key = permit_key(PROXY)
    assert key.startswith(guest_route_permits.KEY_PREFIX)
    assert "secret" not in key and "user" not in key and "10.0.0.1" not in key


def test_configure_installs_capacities_and_honours_the_switch(client, monkeypatch):
    monkeypatch.setattr("ultima_scraper_backend.usapi_initializer.resolve_proxy_url", lambda url: url)
    proxies = [
        SimpleNamespace(url=PROXY, max_connections=8, enabled=True),
        SimpleNamespace(url="http://off:1", max_connections=8, enabled=False),
    ]
    try:
        permits = configure_route_permits(client, proxies)
        assert permits is not None and permits.capacities == {PROXY: 8}
        assert sm._GUEST_ROUTE_PERMITS is permits
        monkeypatch.setenv("ULTIMA_GUEST_ROUTE_PERMITS", "0")
        assert configure_route_permits(client, proxies) is None
        assert sm._GUEST_ROUTE_PERMITS is None
        monkeypatch.delenv("ULTIMA_GUEST_ROUTE_PERMITS")
        assert configure_route_permits(None, proxies) is None  # no Redis
    finally:
        sm.configure_guest_route_permits(None)


@pytest.mark.asyncio
async def test_coalesced_releases_keep_the_total_across_workers(client):
    workers = [GuestRoutePermits(client, {PROXY: 2}, coalesce_seconds=0.005) for _ in range(3)]
    in_flight, peak, done = 0, 0, 0

    async def send(permits, n):
        nonlocal in_flight, peak, done
        async with permits(PROXY):
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.002 * (n % 3))
            in_flight -= 1
            done += 1

    await asyncio.gather(*(send(workers[n % 3], n) for n in range(30)))
    assert done == 30 and peak == 2
    async with asyncio.timeout(1):
        while await client.zcard(permit_key(PROXY)):
            await asyncio.sleep(0.005)  # the last releases flush on their timer


@pytest.mark.asyncio
async def test_a_release_rides_on_the_next_acquire(client):
    other = "http://user:secret@10.0.0.2:8080"
    permits = GuestRoutePermits(client, {PROXY: 1, other: 1}, coalesce_seconds=60)
    calls = []
    script = permits._release_and_acquire

    async def counted(*, keys, args):
        calls.append(list(keys))
        return await script(keys=keys, args=args)

    permits._release_and_acquire = counted
    async with permits(PROXY):
        pass
    assert await client.zcard(permit_key(PROXY)) == 1  # release deferred
    async with permits(other):
        pass
    # One script call released PROXY and acquired the other proxy.
    assert calls == [[permit_key(PROXY)], [permit_key(PROXY), permit_key(other)]]
    assert await client.zcard(permit_key(PROXY)) == 0
    await permits.flush_releases()
    assert await client.zcard(permit_key(other)) == 0
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_a_cancelled_acquire_keeps_its_carried_releases(client):
    permits = GuestRoutePermits(client, {PROXY: 1}, coalesce_seconds=60)
    async with permits(PROXY):
        pass
    pending = list(permits._pending_releases)
    assert len(pending) == 1

    async def cancelled(*, keys, args):
        raise asyncio.CancelledError

    script, permits._release_and_acquire = permits._release_and_acquire, cancelled
    with pytest.raises(asyncio.CancelledError):
        await permits.acquire(permit_key(PROXY), 1)
    assert permits._pending_releases == pending
    permits._release_and_acquire = script
    await permits.flush_releases()
    assert await client.zcard(permit_key(PROXY)) == 0


def test_release_coalescing_is_off_by_default(client, monkeypatch):
    monkeypatch.delenv("ULTIMA_GUEST_ROUTE_PERMIT_COALESCE_SECONDS", raising=False)
    assert GuestRoutePermits(client, {PROXY: 1})._release_and_acquire is None
    monkeypatch.setenv("ULTIMA_GUEST_ROUTE_PERMIT_COALESCE_SECONDS", "0.01")
    assert GuestRoutePermits(client, {PROXY: 1}).coalesce_seconds == 0.01
