"""Reopen routes only after cooldown and a conclusive upstream probe."""

import asyncio
from datetime import UTC, datetime
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from ultima_scraper_api.managers import session_manager


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 0),
        ("12", 12),
        ("1.5", 1.5),
        ("-1", 0),
        ("nan", 0),
        ("inf", 0),
        ("bad", 0),
    ],
)
def test_retry_after_delay(value, expected):
    assert session_manager._retry_after_seconds(value) == expected


def test_retry_after_http_date(monkeypatch):
    monkeypatch.setattr(session_manager.time, "time", lambda: 1000)
    value = format_datetime(datetime.fromtimestamp(1042, UTC), usegmt=True)
    assert session_manager._retry_after_seconds(value) == 42


async def test_probe_uses_signed_profile_route_and_honors_cooldowns(monkeypatch):
    manager = session_manager.SessionManager(api=None)
    manager.get_ssl_context = Mock(return_value=None)
    route = "__direct__"
    url = "https://onlyfans.com/api2/v2/users/123"
    auth = SimpleNamespace(
        create_request_headers=Mock(
            side_effect=lambda target, extra_headers: {
                "fresh-signature": str(len(requests)),
                **extra_headers,
            }
        )
    )
    requester = object.__new__(session_manager.AuthedSession)
    requester.auth = auth
    now = [100.0]
    sleeps, requests, closed = [], [], []
    statuses = iter(
        [(400, {}), (403, {}), (500, {}), (429, {"Retry-After": "17"}), (404, {})]
    )

    async def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    class Response:
        def __init__(self, status, headers):
            self.status, self.headers = status, headers

        async def __aenter__(self):
            assert manager.is_route_rate_limited(route)
            return self

        async def __aexit__(self, *args):
            pass

    class Probe:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append(True)

        def get(self, target, headers):
            requests.append((target, dict(headers), now[0]))
            return Response(*next(statuses))

    monkeypatch.setattr(session_manager.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(session_manager.asyncio, "sleep", sleep)
    monkeypatch.setattr(
        session_manager.aiohttp, "TCPConnector", lambda **kwargs: object()
    )
    monkeypatch.setattr(session_manager, "ClientSession", Probe)
    requester.active_session = Probe()
    manager.mark_route_rate_limited(
        route, requester=requester, probe_url=url, retry_after="12"
    )
    task = manager._route_rate_limit_tasks[route]
    # Another response on the same route extends its deadline without another checker.
    manager.mark_route_rate_limited(
        route, requester=requester, probe_url=url, retry_after="15"
    )
    assert manager._route_rate_limit_tasks[route] is task
    await task
    assert [request[0] for request in requests] == [url] * 5
    assert [request[2] for request in requests] == [115, 120, 125, 130, 147]
    assert auth.create_request_headers.call_count == 5
    assert len({request[1]["fresh-signature"] for request in requests}) == 5
    assert all(
        request[1]["accept"] == "application/json, text/plain, */*"
        for request in requests
    )
    assert all(request[1]["Connection"] == "keep-alive" for request in requests)
    assert sum(sleeps) == 47
    assert manager.is_route_rate_limited(route) is False
    assert closed == []  # The checker borrows the normal requester client.
    assert not manager._route_rate_limit_tasks
    assert not manager._route_rate_limit_probes
    assert not manager._route_rate_limit_until


async def test_cancelled_probe_releases_client_and_auth_reference(monkeypatch):
    manager = session_manager.SessionManager(api=None)
    manager.get_ssl_context = Mock(return_value=None)
    manager._route_rate_limited["__direct__"] = True
    closed = []

    class Probe:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append(True)

        def get(self, *args, **kwargs):
            raise asyncio.CancelledError

    monkeypatch.setattr(
        session_manager.aiohttp, "TCPConnector", lambda **kwargs: object()
    )
    monkeypatch.setattr(session_manager, "ClientSession", Probe)
    with pytest.raises(asyncio.CancelledError):
        await manager.check_route_rate_limit()
    assert closed == [True]
    assert manager.is_route_rate_limited("__direct__") is True
    assert not manager._route_rate_limit_probes


async def test_cancelled_profile_probe_preserves_requester_client(monkeypatch):
    manager = session_manager.SessionManager(api=None)
    manager._route_rate_limited["__direct__"] = True
    client = SimpleNamespace(
        closed=False,
        get=Mock(side_effect=asyncio.CancelledError),
        close=Mock(),
    )
    manager._route_rate_limit_probes["__direct__"] = (
        SimpleNamespace(
            active_session=client, create_json_request_headers=lambda url: {}
        ),
        "https://onlyfans.com/api2/v2/users/123",
    )
    anonymous_client = Mock(
        side_effect=AssertionError("Must use normal cookie context")
    )
    monkeypatch.setattr(session_manager, "ClientSession", anonymous_client)
    with pytest.raises(asyncio.CancelledError):
        await manager.check_route_rate_limit()
    client.close.assert_not_called()
    anonymous_client.assert_not_called()
    assert manager.is_route_rate_limited("__direct__") is True
    assert not manager._route_rate_limit_probes


async def test_profile_probe_does_not_use_fresh_anonymous_cookie_context(monkeypatch):
    manager = session_manager.SessionManager(api=None)
    route = "__direct__"
    manager._route_rate_limited[route] = True
    requests = []
    statuses = iter([429, 404])
    now = [100.0]

    async def sleep(seconds):
        now[0] += seconds

    class Response:
        def __init__(self):
            self.headers = {}

        async def __aenter__(self):
            self.status = next(statuses)
            requests.append(self.status)
            return self

        async def __aexit__(self, *args):
            pass

    normal = SimpleNamespace(get=lambda *args, **kwargs: Response(), closed=False)
    manager._route_rate_limit_probes[route] = (
        SimpleNamespace(
            active_session=normal, create_json_request_headers=lambda url: {}
        ),
        "https://onlyfans.com/api2/v2/users/123",
    )
    anonymous_client = Mock(
        side_effect=AssertionError("Anonymous probe is not recovery")
    )
    monkeypatch.setattr(session_manager, "ClientSession", anonymous_client)
    monkeypatch.setattr(session_manager.asyncio, "sleep", sleep)
    monkeypatch.setattr(session_manager.time, "monotonic", lambda: now[0])
    await manager.check_route_rate_limit(route)
    assert requests == [429, 404]
    assert manager.is_route_rate_limited(route) is False
    anonymous_client.assert_not_called()


async def test_closed_profile_requester_cannot_recover_anonymously(monkeypatch):
    manager = session_manager.SessionManager(api=None)
    route = "__direct__"
    manager._route_rate_limited[route] = True
    manager._route_rate_limit_probes[route] = (
        SimpleNamespace(
            active_session=SimpleNamespace(closed=True),
            create_json_request_headers=lambda url: {},
        ),
        "https://onlyfans.com/api2/v2/users/123",
    )
    anonymous_client = Mock(
        side_effect=AssertionError("Closed requester is inconclusive")
    )

    async def sleep(seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(session_manager, "ClientSession", anonymous_client)
    monkeypatch.setattr(session_manager.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await manager.check_route_rate_limit(route)
    anonymous_client.assert_not_called()
    assert manager.is_route_rate_limited(route) is True


async def test_cancelled_waiter_does_not_cancel_shared_recovery():
    manager = session_manager.SessionManager(api=None)
    route = "__direct__"
    manager._route_rate_limited[route] = True
    released = asyncio.Event()

    async def recovery():
        await released.wait()
        manager._route_rate_limited[route] = False

    checker = asyncio.create_task(recovery())
    manager._route_rate_limit_tasks[route] = checker
    first = asyncio.create_task(manager.wait_for_route_recovery(route))
    second = asyncio.create_task(manager.wait_for_route_recovery(route))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not checker.done()
    assert not second.done()
    released.set()
    await second
    assert checker.done() and not checker.cancelled()
