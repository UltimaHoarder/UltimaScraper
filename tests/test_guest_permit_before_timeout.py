"""A lookup may take its proxy's connection permit before its own timeout starts."""

import asyncio
from types import SimpleNamespace

import fakeredis.aioredis
import pytest
from test_guest_route_rate_limit import FakeSession
from ultima_scraper_api.managers import session_manager as sm
from ultima_scraper_api.managers.session_manager import AuthedSession
from ultima_scraper_backend.job_system.guest_route_permits import GuestRoutePermits, permit_key

PROXY = "http://user:secret@10.0.0.9:8080"
pytestmark = pytest.mark.asyncio


class PermitSession(FakeSession):
    _route_permit = AuthedSession._route_permit
    hold_route_permit = AuthedSession.hold_route_permit

    def __init__(self, statuses):
        super().__init__(statuses=statuses)
        self.auth = SimpleNamespace(guest=True, auth_details=SimpleNamespace(proxy_url=PROXY))


@pytest.fixture
def permits():
    client = fakeredis.aioredis.FakeRedis()
    provider = GuestRoutePermits(client, {PROXY: 1})
    sm.configure_guest_route_permits(provider)
    yield provider, client
    sm.configure_guest_route_permits(None)


async def _occupy(provider, seconds):
    async with provider(PROXY):
        await asyncio.sleep(seconds)


async def test_the_lookup_timeout_starts_after_the_permit(permits):
    provider, client = permits
    session = PermitSession([404])
    busy = asyncio.create_task(_occupy(provider, 0.3))
    await asyncio.sleep(0.02)
    async with session.hold_route_permit():
        # Queued ~0.3 s for the proxy's only connection, then a fast reply:
        # the 0.1 s timeout measures the reply, not the queue.
        await asyncio.wait_for(session._request("u"), 0.1)
    await busy
    assert len(session.sent) == 1
    assert await client.zcard(permit_key(PROXY)) == 0  # released on exit


async def test_without_holding_the_queue_counts_against_the_timeout(permits):
    provider, _ = permits
    session = PermitSession([404])
    busy = asyncio.create_task(_occupy(provider, 0.3))
    await asyncio.sleep(0.02)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(session._request("u"), 0.1)
    await busy
    assert session.sent == []


async def test_sends_inside_the_hold_reuse_its_permit(permits):
    _, client = permits
    session = PermitSession([404, 404])
    async with session.hold_route_permit():
        # Two sends with a capacity of one: a second permit would deadlock.
        await asyncio.wait_for(session._request("u"), 1)
        await asyncio.wait_for(session._request("u"), 1)
        assert await client.zcard(permit_key(PROXY)) == 1
    assert len(session.sent) == 2
    assert sm._HELD_PERMIT.get() is None


async def test_hold_is_a_no_op_without_permits():
    sm.configure_guest_route_permits(None)
    session = PermitSession([404])
    async with session.hold_route_permit():
        await session._request("u")
    assert len(session.sent) == 1
