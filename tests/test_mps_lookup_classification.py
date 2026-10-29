"""Inconclusive HTTP responses must never count as missing-user evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import python_socks
from aiohttp import ClientResponseError
from ultima_scraper_api import ContentType
from ultima_scraper_api.apis.onlyfans.classes import auth_model
from ultima_scraper_api.managers import session_manager
from ultima_scraper_api.managers.redis import hooks
from ultima_scraper_backend.job_system.handlers.scrape import handler
from ultima_scraper_backend.job_system.job_builder import build_task
from ultima_scraper_backend.job_system.models import TaskRunContext, TaskType


@pytest.fixture(autouse=True)
def isolated_hooks(monkeypatch):
    monkeypatch.setattr(hooks, "_publish_hook_event", AsyncMock())


def auth_for(response):
    auth = object.__new__(auth_model.OnlyFansAuthModel)
    auth.guest = True
    auth.users = {}
    auth.auth_session = SimpleNamespace(json_request=AsyncMock(return_value=response))
    return auth


@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_json_request_retains_http_error_code(status):
    session = object.__new__(session_manager.AuthedSession)
    session.request = AsyncMock(
        side_effect=ClientResponseError(
            request_info=SimpleNamespace(
                real_url="https://onlyfans.com/api2/v2/users/123"
            ),
            history=(),
            status=status,
            message="Upstream error",
        )
    )
    response = await session.json_request("https://onlyfans.com/api2/v2/users/123")
    assert response["error"]["code"] == status


@pytest.mark.parametrize(
    "proxy_error_type", [python_socks.ProxyError, session_manager.SocksProxyError]
)
async def test_proxy_auth_error_retains_proxy_status_without_a_missing_user(
    proxy_error_type,
):
    session = object.__new__(session_manager.AuthedSession)
    session.request = AsyncMock(
        side_effect=proxy_error_type(
            "407 Proxy Authentication Required", error_code=407
        )
    )
    response = await session.json_request("https://onlyfans.com/api2/v2/users/123")
    assert response["error"]["code"] == 0
    assert response["error"]["proxy_code"] == 407
    with pytest.raises(auth_model.UserLookupError) as caught:
        await handler._resolve_scrape_user(
            auth_for(response), user_id=123, username="123", worker_id="test"
        )
    assert caught.value.proxy_code == 407


@pytest.mark.parametrize(
    "response",
    [
        {"error": {"code": code, "message": "Upstream error"}}
        for code in [0, 400, 401, 403, 429, 500, 502, 503, 504]
    ]
    + [{}, None, [], {"error": None}, {"id": 0}, {"id": True}, {"id": 124}],
)
async def test_guest_lookup_rejects_inconclusive_and_malformed_responses(response):
    with pytest.raises(auth_model.UserLookupError):
        await handler._resolve_scrape_user(
            auth_for(response), user_id=123, username="123", worker_id="test"
        )


@pytest.mark.parametrize(
    "response",
    [
        {"error": {"code": 404, "message": "Not Found"}},
        {"error": {"code": 0, "message": "User not found"}},
    ],
)
async def test_authoritative_missing_profile_returns_none(response):
    assert (
        await handler._resolve_scrape_user(
            auth_for(response), user_id=123, username="123", worker_id="test"
        )
        is None
    )


async def test_valid_profile_and_legacy_optional_lookup(monkeypatch):
    user = SimpleNamespace(id=123, username="present")
    constructor = Mock(return_value=user)
    monkeypatch.setattr(auth_model, "UserModel", constructor)
    auth = auth_for({"id": 123, "username": "present"})
    assert (
        await handler._resolve_scrape_user(
            auth, user_id=123, username="123", worker_id="test"
        )
        is user
    )
    constructor.assert_called_once_with(
        {"id": 123, "username": "present"}, auth, cache=False
    )
    assert await auth_for({"error": {"code": 429}}).get_user(123, cache=False) is None


async def test_guest_task_waits_for_route_recovery_before_profile_request():
    auth = auth_for({"error": {"code": 404}})
    calls = []

    async def recovery(route):
        assert route == "__direct__"
        calls.append("recovered")

    async def lookup(url):
        assert calls == ["recovered"]
        calls.append("requested")
        return {"error": {"code": 404}}

    auth.auth_session.json_request.side_effect = lookup
    auth.auth_session.get_route_key = lambda: "__direct__"
    auth.auth_session.session_manager = SimpleNamespace(
        is_route_rate_limited=lambda route: True,
        wait_for_route_recovery=recovery,
    )
    assert (
        await handler._resolve_scrape_user(
            auth, user_id=123, username="123", worker_id="test"
        )
        is None
    )
    assert calls == ["recovered", "requested"]


@pytest.mark.parametrize(
    ("codes", "expected_success"),
    [
        ([429, 429, 429], False),
        ([404, 404, 429], False),
        ([404, 404, 503], False),
        ([404, 404, 404], True),
    ],
)
async def test_three_miss_contract_through_real_guest_lookup(
    monkeypatch, codes, expected_success
):
    routes = [f"http://route{index}:8080" for index in range(3)]
    auths = {
        route: auth_for({"error": {"code": code, "message": "Upstream response"}})
        for route, code in zip(routes, codes)
    }
    monkeypatch.setattr(
        handler,
        "_resolve_guest_auth",
        AsyncMock(side_effect=lambda site_api, proxy_url, worker_id: auths[proxy_url]),
    )
    monkeypatch.setattr(handler, "MPS_GUEST_ROUTE_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(handler, "MPS_GUEST_LOOKUP_HEDGE_DELAY_SECONDS", 0)
    prepared = []
    async def confirmed_before_write(**kwargs):
        assert len(prepared) == 1
        assert prepared[0]["success"] is True
        assert prepared[0]["output"]["invalid_user"] is True
    invalid_write = AsyncMock(side_effect=confirmed_before_write)
    monkeypatch.setattr(handler, "_mark_user_invalid", invalid_write)
    database_writes = SimpleNamespace(submit=AsyncMock())
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=123,
        user_username="123",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url=routes[0],
        guest_fallback_proxy_urls=routes[1:],
        track_invalid_user=True,
        conclusive_miss_threshold=3,
        max_items=1,
    )
    context = TaskRunContext(
        job=SimpleNamespace(job_id="classification-test"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": database_writes,
            "prepare_profile_completion": lambda result: prepared.append(result.to_dict()),
        },
    )
    result = await handler.scrape_task_handler(task, context)
    assert result.success is expected_success
    assert invalid_write.await_count == int(expected_success)
    assert len(prepared) == int(expected_success)
    if expected_success:
        assert prepared[0]["output"] == result.output
        assert prepared[0]["metrics"] == result.metrics
    database_writes.submit.assert_not_awaited()
    if not expected_success:
        assert result.continue_job_on_failure is True
    for code, auth in zip(codes, auths.values()):
        assert auth.auth_session.json_request.await_count == (
            1 if code == 404 else handler.MPS_GUEST_ROUTE_MAX_ATTEMPTS
        )


@pytest.mark.parametrize(("proxy_code", "should_defer"), [(407, True), (503, False)])
async def test_proxy_auth_failure_uses_frozen_reserve_before_next_task_lookup(
    monkeypatch,
    proxy_code,
    should_defer,
):
    routes = [f"http://route{index}:8080" for index in range(3)]
    reserve = "http://same-country-reserve:8080"
    auths = {route: auth_for({"error": {"code": 404}}) for route in [*routes, reserve]}
    auths[routes[0]] = auth_for({"error": {"code": 0, "proxy_code": proxy_code}})
    monkeypatch.setattr(
        handler,
        "_resolve_guest_auth",
        AsyncMock(side_effect=lambda site_api, proxy_url, worker_id: auths[proxy_url]),
    )
    monkeypatch.setattr(handler, "MPS_GUEST_ROUTE_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(handler, "MPS_GUEST_LOOKUP_HEDGE_DELAY_SECONDS", 0)
    invalid_write = AsyncMock()
    monkeypatch.setattr(handler, "_mark_user_invalid", invalid_write)
    api = SimpleNamespace()
    context = TaskRunContext(
        job=SimpleNamespace(job_id="proxy-auth-test"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": api,
            "worker_id": "test",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": SimpleNamespace(submit=AsyncMock()),
        },
    )

    def task():
        return build_task(
            TaskType.SCRAPE,
            site_name="OnlyFans",
            user_id=123,
            user_username="123",
            content_type=ContentType.PROFILE,
            use_guest_auth=True,
            guest_proxy_url=routes[0],
            guest_fallback_proxy_urls=routes[1:],
            guest_proxy_alternatives={routes[0]: [reserve]},
            track_invalid_user=True,
            conclusive_miss_threshold=3,
            max_items=1,
        )

    first = await handler.scrape_task_handler(task(), context)
    assert first.success is False
    invalid_write.assert_not_awaited()
    auths[reserve].auth_session.json_request.assert_not_awaited()
    prior_failed_lookups = auths[routes[0]].auth_session.json_request.await_count
    assert handler._mps_guest_route_is_deferred(api, routes[0]) is should_defer
    second = await handler.scrape_task_handler(task(), context)
    if not should_defer:
        assert second.success is False
        invalid_write.assert_not_awaited()
        auths[reserve].auth_session.json_request.assert_not_awaited()
        return
    assert second.success is True
    invalid_write.assert_awaited_once()
    assert (
        auths[routes[0]].auth_session.json_request.await_count == prior_failed_lookups
    )
    auths[reserve].auth_session.json_request.assert_awaited_once()
    assert set(second.metrics["proxy_routes"]) == {reserve, *routes[1:]}


def test_proxy_auth_deferral_expires_and_conclusive_responses_recover_it():
    api = SimpleNamespace()
    route = "http://bad-auth:8080"
    handler._record_mps_guest_route_outcome(api, route, "proxy_auth_failure")
    assert handler._mps_guest_route_is_deferred(api, route)
    handler._record_mps_guest_route_outcome(api, route, "found")
    assert not handler._mps_guest_route_is_deferred(api, route)
    handler._record_mps_guest_route_outcome(api, route, "proxy_auth_failure")
    assert not handler._mps_guest_route_is_deferred(
        api,
        route,
        now=handler.time.monotonic() + handler.MPS_GUEST_PROXY_AUTH_DEFER_SECONDS + 1,
    )
