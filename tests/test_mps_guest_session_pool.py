"""Bound visitor ownership, requests and cookie-specific cooldowns."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ultima_scraper_api.apis.api_streamliner import StreamlinedAPI
from ultima_scraper_api.apis.onlyfans.authenticator import OnlyFansAuthenticator
from ultima_scraper_api.apis.onlyfans.classes.auth_model import OnlyFansAuthModel
from ultima_scraper_api.apis.onlyfans.classes.extras import AuthDetails
from ultima_scraper_api.apis.onlyfans.onlyfans import OnlyFansAPI
from ultima_scraper_api.config import UltimaScraperAPIConfig
from ultima_scraper_api.managers.session_manager import (
    DEFAULT_GUEST_TOTAL_TIMEOUT,
    AuthedSession,
    SessionManager,
)
from ultima_scraper_backend.job_system.guest_sessions import (
    GuestSessionPool,
    configured_route_capacities,
)
from ultima_scraper_backend.job_system.handlers.scrape import handler


def test_slots_partition_existing_capacity_without_duplicates():
    capacities = {"route-a": 26, "route-b": 8}
    pools = [GuestSessionPool(capacities, index, 8) for index in range(8)]
    for route, capacity in capacities.items():
        all_keys = [key for pool in pools for key in pool.slots[route]]
        assert len(all_keys) == len(set(all_keys)) == capacity
    assert [len(pool.slots["route-a"]) for pool in pools] == [4, 4, 3, 3, 3, 3, 3, 3]


def test_every_worker_gets_a_session_on_a_proxy_with_fewer_connections():
    # The route permits cap the proxy at its 7 connections across workers;
    # the pool just has to let all 8 workers use it.
    pools = [GuestSessionPool({"route": 7}, index, 8) for index in range(8)]
    keys = [key for pool in pools for key in pool.slots["route"]]
    assert [len(pool.slots["route"]) for pool in pools] == [1] * 8
    assert len(set(keys)) == 8


def test_route_capacity_resolves_credentials_and_deduplicates_conservatively():
    proxies = [
        SimpleNamespace(url="route-a", max_connections=26, enabled=True),
        SimpleNamespace(url="alias-a", max_connections=8, enabled=True),
        SimpleNamespace(url="off", max_connections=-1, enabled=False),
    ]
    assert configured_route_capacities(proxies, lambda url: "resolved-a") == {"resolved-a": 8}
    assert configured_route_capacities(
        [SimpleNamespace(url="route", max_connections=-1)], lambda url: url,
    ) == {"route": 8}


@pytest.mark.parametrize("limit", [-1, None, 0, "26"])
def test_unlimited_network_routes_use_the_same_bounded_mps_preview_budget(limit):
    from ultima_scraper_backend.job_system.mps_tasks import mps_proxy_connection_limit

    proxies = [SimpleNamespace(url="route", max_connections=limit, enabled=True)]
    capacities = configured_route_capacities(proxies, lambda url: url)
    assert capacities == {"route": mps_proxy_connection_limit(limit)} == {"route": 8}
    pools = [GuestSessionPool(capacities, index, 8) for index in range(8)]
    keys = [key for pool in pools for key in pool.slots["route"]]
    assert len(keys) == len(set(keys)) == 8


async def test_pool_preserves_independent_visitors_and_shares_cold_initialization():
    route = "http://proxy.example:8080"
    pool = GuestSessionPool({route: 2}, 0, 1)
    started = asyncio.Event()
    ready = asyncio.Event()
    sessions = []
    manager = SessionManager(api=None)

    async def login(*, auth_json, guest, guest_session_key):
        assert guest
        session = SimpleNamespace(
            guest_session_key=guest_session_key, request_waiters=0,
            session_manager=manager, get_rate_limit_key=lambda: guest_session_key,
        )
        authed = SimpleNamespace(
            guest=True, auth_session=session,
            authenticator=SimpleNamespace(auth_details=SimpleNamespace(proxy_url=route)),
        )
        sessions.append(authed)
        started.set()
        await ready.wait()
        return authed

    api = SimpleNamespace(_guest_session_pool=pool, auths={}, login=login)
    tasks = [asyncio.create_task(handler._resolve_guest_auth(
        api, proxy_url=route, worker_id="worker",
    )) for _ in range(6)]
    await started.wait()
    await asyncio.sleep(0)
    tasks[0].cancel()
    ready.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError)
    assert len(sessions) == len(api._guest_auth_cache) == 2
    assert len({id(result) for result in results[1:]}) == 2
    assert not api._guest_auth_pending
    limited = pool.slots[route][0]
    manager._route_rate_limited[limited] = True
    selected = await handler._resolve_guest_auth(api, proxy_url=route, worker_id="worker")
    assert selected.auth_session.guest_session_key != limited
    assert manager.is_route_rate_limited(limited)
    with pytest.raises(ValueError, match="outside"):
        pool.select(api, "unconfigured")


async def test_request_cancellation_releases_bounded_visitor_queue():
    session = object.__new__(AuthedSession)
    session._guest_request_semaphore = asyncio.Semaphore(1)
    session.request_waiters = 0
    started = asyncio.Event()
    release = asyncio.Event()
    active = peak = 0

    async def request(*args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        started.set()
        try:
            await release.wait()
        finally:
            active -= 1

    session._request = request
    first = asyncio.create_task(session.request("https://example.com"))
    await started.wait()
    queued = asyncio.create_task(session.request("https://example.com"))
    await asyncio.sleep(0)
    assert session.request_waiters == 2
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    assert session.request_waiters == 1
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    await session.request("https://example.com")
    assert peak == 1
    assert session.request_waiters == 0


async def test_guest_registry_owns_each_client_until_cleanup():
    api = object.__new__(StreamlinedAPI)
    api.api = SimpleNamespace(auths={})
    api.session_manager = SimpleNamespace(stop_rate_limit_checker=AsyncMock())
    auths = []
    for seed in (123, 124):
        client = SimpleNamespace(close=AsyncMock())
        auth = SimpleNamespace(
            id=0, guest=True,
            authenticator=SimpleNamespace(auth_details=SimpleNamespace(id=seed)),
            get_requester=lambda client=client: SimpleNamespace(active_session=client),
        )
        auths.append(auth)
        api.add_auth(auth)
    assert api.api.auths == {123: auths[0], 124: auths[1]}
    await api.close_pools()
    assert not api.api.auths
    for auth in auths:
        auth.get_requester().active_session.close.assert_awaited_once()


async def test_bounded_clients_keep_distinct_cookies_and_one_connector_slot():
    api = SimpleNamespace(session_manager=SessionManager(api=None))
    auths = [OnlyFansAuthenticator(
        api, AuthDetails(id=seed, proxy_url="http://proxy.example:8080"), True,
        guest_session_key=f"guest-{seed}",
    ) for seed in (123, 124)]
    try:
        sessions = [auth.auth_session for auth in auths]
        assert sessions[0].active_session.cookie_jar is not sessions[1].active_session.cookie_jar
        assert sessions[0].get_route_key() == sessions[1].get_route_key()
        assert sessions[0].get_rate_limit_key() != sessions[1].get_rate_limit_key()
        for session in sessions:
            assert session.active_session.connector.limit == 1
            assert session.active_session.timeout.total == DEFAULT_GUEST_TOTAL_TIMEOUT
    finally:
        await asyncio.gather(*(auth.close() for auth in auths))


async def test_cancelled_guest_login_closes_unregistered_client():
    api = object.__new__(OnlyFansAPI)
    api.auths = {}
    authenticator = SimpleNamespace(
        login=AsyncMock(side_effect=asyncio.CancelledError), close=AsyncMock(),
    )
    api.authenticator = lambda *args, **kwargs: authenticator
    with pytest.raises(asyncio.CancelledError):
        await api.login(auth_json={"id": 123}, guest=True, guest_session_key="guest-123")
    authenticator.close.assert_awaited_once()
    assert not api.auths


async def test_real_guest_models_preserve_registration_after_id_zero_update():
    api = object.__new__(OnlyFansAPI)
    api.api = api
    api.auths = {}
    api.config = UltimaScraperAPIConfig()
    api.websocket_manager = SimpleNamespace(create_connection=lambda **kwargs: object())
    api.websocket_impl_class = object()
    api.session_manager = SessionManager(api=api)
    authenticators = []
    try:
        for seed in (123, 124):
            authenticator = OnlyFansAuthenticator(
                api, AuthDetails(id=seed), True, guest_session_key=f"guest-{seed}",
            )
            authenticators.append(authenticator)
            authenticator.__raw__ = {"id": 0, "username": "guest"}
            authenticator.auth_details.activate_guest()
            # Construct the actual model: update() replaces AuthDetails.id with 0.
            auth = OnlyFansAuthModel(authenticator)
            assert auth.id == auth.get_auth_details().id == 0
            api.add_auth(auth)
        assert set(api.auths) == {123, 124}
    finally:
        await asyncio.gather(*(auth.close() for auth in authenticators))


@pytest.mark.parametrize(
    ("guest", "session_key", "eager"),
    [(True, "pooled-visitor", False), (True, None, True), (False, None, True)],
)
async def test_real_auth_models_defer_only_pooled_visitor_drm(
    monkeypatch, tmp_path, guest, session_key, eager,
):
    api = object.__new__(OnlyFansAPI)
    api.api = api
    api.auths = {}
    api.config = UltimaScraperAPIConfig()
    api.websocket_manager = SimpleNamespace(create_connection=lambda **kwargs: object())
    api.websocket_impl_class = object()
    api.session_manager = SessionManager(api=api)
    client_path = tmp_path / "device-client"
    key_path = tmp_path / "device-key"
    client_path.touch()
    key_path.touch()
    api.config.settings.drm.device_client_blob_filepath = client_path
    api.config.settings.drm.device_private_key_filepath = key_path
    device = object()
    constructor = Mock(return_value=device)
    monkeypatch.setattr(
        "ultima_scraper_api.apis.onlyfans.classes.only_drm.OnlyDRM", constructor,
    )
    authenticator = OnlyFansAuthenticator(
        api, AuthDetails(id=123), guest, guest_session_key=session_key,
    )
    authenticator.__raw__ = {"id": 0 if guest else 123, "username": "test"}
    try:
        auth = OnlyFansAuthModel(authenticator)
        auth.update()
        assert (constructor.call_count == 1) == eager
        assert (await auth.get_authed_user()).username == "test"
        assert (constructor.call_count == 1) == eager
        assert auth.drm is device
        assert auth.drm is device
        constructor.assert_called_once_with(client_path, key_path, auth)
        replacement = object()
        auth.drm = replacement
        assert auth.drm is replacement
        assert constructor.call_count == 1
    finally:
        await authenticator.close()


@pytest.mark.parametrize("failure", [False, True])
async def test_pooled_visitor_drm_unavailable_is_cached(monkeypatch, tmp_path, failure):
    api = object.__new__(OnlyFansAPI)
    api.api = api
    api.auths = {}
    api.config = UltimaScraperAPIConfig()
    api.websocket_manager = SimpleNamespace(create_connection=lambda **kwargs: object())
    api.websocket_impl_class = object()
    api.session_manager = SessionManager(api=api)
    constructor = Mock(side_effect=RuntimeError("invalid test device"))
    monkeypatch.setattr(
        "ultima_scraper_api.apis.onlyfans.classes.only_drm.OnlyDRM", constructor,
    )
    if failure:
        client_path = tmp_path / "device-client"
        key_path = tmp_path / "device-key"
        client_path.touch()
        key_path.touch()
        api.config.settings.drm.device_client_blob_filepath = client_path
        api.config.settings.drm.device_private_key_filepath = key_path
    authenticator = OnlyFansAuthenticator(
        api, AuthDetails(id=123), True, guest_session_key="pooled-visitor",
    )
    authenticator.__raw__ = {"id": 0, "username": "test"}
    try:
        auth = OnlyFansAuthModel(authenticator)
        constructor.assert_not_called()
        assert auth.drm is None
        assert auth.drm is None
        assert auth._drm_initialized
        assert constructor.call_count == int(failure)
    finally:
        await authenticator.close()
