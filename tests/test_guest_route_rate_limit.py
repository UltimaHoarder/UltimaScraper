"""Guest requests are paced per route; a 429 benches the session and slows the route."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from aiohttp import ClientResponseError, RequestInfo
from multidict import CIMultiDict, CIMultiDictProxy
from ultima_scraper_api.managers import session_manager as sm
from ultima_scraper_api.managers.session_manager import AuthedSession
from ultima_scraper_backend.job_system.guest_sessions import configure_guest_route_rate_limit
from yarl import URL


class FakeResponse:
    content = b""
    content_type = "application/json"

    def __init__(self, status):
        self.status = status
        self.released = False

    def raise_for_status(self):
        if self.status >= 400:
            raise ClientResponseError(
                RequestInfo(URL("https://example.test"), "GET", CIMultiDictProxy(CIMultiDict())),
                (), status=self.status, headers=CIMultiDict({"Retry-After": "0"}),
            )

    def release(self):
        self.released = True


class FakeSession:
    _route_limiter = AuthedSession._route_limiter
    _route_permit = AuthedSession._route_permit
    _note_guest_route_outcome = AuthedSession._note_guest_route_outcome
    acquire_route_rate = AuthedSession.acquire_route_rate
    prepay_route_rate = AuthedSession.prepay_route_rate
    release_prepaid_route_rate = AuthedSession.release_prepaid_route_rate
    _take_prepaid_route_rate = AuthedSession._take_prepaid_route_rate
    _request = AuthedSession._request

    def __init__(self, route="route-a", statuses=(), guest=True):
        self.route = route
        self.auth = SimpleNamespace(guest=guest)
        self.manager = SimpleNamespace(
            max_attempts=10, time2sleep=0, is_route_rate_limited=lambda key: False,
            mark_route_rate_limited=Mock(),
        )
        self.statuses = list(statuses)
        self.sent = []

        async def get(url, headers=None):
            self.sent.append(asyncio.get_running_loop().time())
            return FakeResponse(self.statuses.pop(0))

        self.active_session = SimpleNamespace(get=get)

    def get_session_manager(self):
        return self.manager

    def get_route_key(self):
        return self.route

    def get_rate_limit_key(self):
        return self.route

    def get_current_proxy_info(self):
        return None

    def create_json_request_headers(self, url):
        return {}


@pytest.fixture(autouse=True)
def reset_rate():
    sm.configure_guest_route_rate(None)
    yield
    sm.configure_guest_route_rate(None)


@pytest.mark.asyncio
async def test_guest_requests_burst_then_hold_the_route_rate():
    sm.configure_guest_route_rate(10)  # 10/s with a 0.5 s burst: 5 at once, then every 100 ms
    a, b = FakeSession("route-a", [404] * 7), FakeSession("route-b", [404])
    await asyncio.gather(*(a._request("u") for _ in range(7)), b._request("u"))
    assert a.sent[4] - a.sent[0] < 0.02  # the burst goes out immediately
    gaps = [later - earlier for earlier, later in zip(a.sent[4:], a.sent[5:])]
    assert all(gap >= 0.09 for gap in gaps)  # then the route rate holds
    assert b.sent[0] - a.sent[0] < 0.02  # another route is not held back


@pytest.mark.asyncio
async def test_rate_limit_is_off_by_default_and_skips_authenticated_sessions():
    session = FakeSession(statuses=[404] * 5)
    await asyncio.gather(*(session._request("u") for _ in range(5)))
    assert session.sent[-1] - session.sent[0] < 0.01
    sm.configure_guest_route_rate(1)
    authed = FakeSession(statuses=[404] * 3, guest=False)
    await asyncio.gather(*(authed._request("u") for _ in range(3)))
    assert authed.sent[-1] - authed.sent[0] < 0.01


@pytest.mark.asyncio
async def test_prepaid_token_is_used_once_by_the_lookup_task():
    sm.configure_guest_route_rate(2)  # 500 ms between requests, burst of one
    session = FakeSession(statuses=[404, 404])
    token = await session.prepay_route_rate()  # takes the only token now
    try:
        started = asyncio.get_running_loop().time()
        await asyncio.wait_for(session._request("u"), 0.1)  # child task, no wait
        assert session.sent[0] - started < 0.05
        with pytest.raises(TimeoutError):  # the token was spent; the next one waits
            await asyncio.wait_for(session._request("u"), 0.1)
    finally:
        session.release_prepaid_route_rate(token)


@pytest.mark.asyncio
async def test_guest_429_benches_the_session_and_slows_the_route():
    sm.configure_guest_route_rate(10)
    session = FakeSession(statuses=[429, 404])
    with pytest.raises(ClientResponseError) as raised:
        await session._request("u")
    # One request: retrying the same visitor session cannot succeed.
    assert raised.value.status == 429 and len(session.sent) == 1
    mark = session.manager.mark_route_rate_limited
    mark.assert_called_once()
    assert mark.call_args.args == ("route-a",)
    assert mark.call_args.kwargs["min_delay"] == sm.GUEST_SESSION_BENCH_SECONDS
    assert session._route_limiter().rate == pytest.approx(10 * sm.GUEST_RATE_CUT)


def test_route_budget_is_shared_by_every_process():
    # 8 workers: the API process keeps 1/s; every worker, including the
    # interactive-first worker 0 (it also takes bulk work), shares 34.
    assert configure_guest_route_rate_limit(35, worker_count=8, worker_index=3) == pytest.approx(34 / 8)
    assert sm._GUEST_ROUTE_RATE == pytest.approx(34 / 8)
    assert configure_guest_route_rate_limit(35, worker_count=8, worker_index=0) == pytest.approx(34 / 8)
    assert configure_guest_route_rate_limit(35, worker_count=1) == 1.0  # API process
    assert configure_guest_route_rate_limit(35, worker_count=1, worker_index=0) == 34
    assert configure_guest_route_rate_limit(0, worker_count=8, worker_index=3) is None
    assert sm._GUEST_ROUTE_RATE is None


def test_rate_limit_is_a_network_setting():
    from ultima_scraper_api.config import Network as USAPINetwork
    from ultima_scraper_backend.config import Network

    for cls in (Network, USAPINetwork):
        assert cls().guest_route_rate_limit == 35
        assert cls(guest_route_rate_limit=20).guest_route_rate_limit == 20
        with pytest.raises(ValueError):
            cls(guest_route_rate_limit=-1)
