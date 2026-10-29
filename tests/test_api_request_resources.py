from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ultima_scraper_api.managers.session_manager import (
    AuthedSession,
    SessionManager,
    consume_response_json,
)


def session(*, concurrency=2, attempts=2):
    value = AuthedSession.__new__(AuthedSession)
    value.session_manager = SimpleNamespace(
        max_threads=concurrency,
        max_attempts=attempts,
        rate_limit_check=False,
        is_rate_limited=None,
    )
    value.auth = SimpleNamespace(create_request_headers=lambda *args, **kwargs: {})
    value.active_session = SimpleNamespace(get=AsyncMock())
    # Constructor state for a non-guest session.
    value.guest_session_key = None
    value.request_waiters = 0
    value._guest_request_semaphore = None
    value.current_proxy = None
    return value


def bare_session_manager() -> SessionManager:
    """A SessionManager with only the rate-limit and TLS state its constructor sets."""
    manager = SessionManager.__new__(SessionManager)
    manager._route_rate_limited = {}
    manager._route_rate_limit_tasks = {}
    manager._route_proxies = {}
    manager._route_rate_limit_until = {}
    manager._route_rate_limit_probes = {}
    manager.time2sleep = 5
    manager.kill = False
    manager._ssl_context = None
    return manager


class Response:
    def __init__(self, payload=None, status=200, json_body=True):
        self.status = status
        self.content = True
        self.content_type = (
            "application/json" if json_body else "application/octet-stream"
        )
        self.reason = "fixture"
        self.json = AsyncMock(return_value=payload)
        self.raise_for_status = Mock()
        self.release = Mock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.release()


@pytest.mark.asyncio
async def test_json_request_decodes_once_and_transfers_the_validated_value():
    client = session()
    payload = {"list": [{"id": 1}]}
    response = Response(payload)
    client.active_session.get.return_value = response
    assert await client.json_request("https://fixture.invalid/posts") is payload
    response.json.assert_awaited_once()
    assert "_ultima_validated_json" not in vars(response)
    # Callers retain ordinary ClientResponse.json behavior outside this handoff.
    assert await response.json() is payload
    assert response.json.await_count == 2


@pytest.mark.asyncio
async def test_scrape_consumer_reuses_validation_and_handles_empty_json_values():
    from ultima_scraper_api.managers.scrape_manager import ScrapeManager

    for payload in ({}, [], None, {"list": [1]}):
        client = session()
        response = Response(payload)
        client.active_session.get.return_value = response
        client.semaphore = asyncio.Semaphore(1)
        scraper = ScrapeManager(
            SimpleNamespace(
                auth_session=client,
                api=SimpleNamespace(CategorizedContent=lambda: None),
            )
        )
        scraper.handle_error = AsyncMock(side_effect=lambda url, value: value)
        assert await scraper.scrape("https://fixture.invalid/posts") is payload
        response.json.assert_awaited_once()
        assert "_ultima_validated_json" not in vars(response)


@pytest.mark.asyncio
async def test_invalid_json_keeps_retry_contract_and_releases_failed_response(
    monkeypatch,
):
    client = session()
    bad = Response()
    bad.json.side_effect = json.JSONDecodeError("invalid", "{", 1)
    good = Response({"id": 1})
    client.active_session.get.side_effect = [bad, good]
    monkeypatch.setattr(
        "ultima_scraper_api.managers.session_manager.asyncio.sleep", AsyncMock()
    )
    assert await client.json_request("https://fixture.invalid/posts") == {"id": 1}
    bad.release.assert_called_once()
    good.release.assert_not_called()
    assert client.active_session.get.await_count == 2
    good.json.assert_awaited_once()


@pytest.mark.asyncio
async def test_binary_response_is_not_read_or_released_before_its_consumer():
    client = session()
    response = Response(json_body=False)
    client.active_session.get.return_value = response
    assert (
        await client.request(
            "https://fixture.invalid/file", premade_settings="download"
        )
        is response
    )
    response.json.assert_not_awaited()
    response.release.assert_not_called()


@pytest.mark.asyncio
async def test_http_error_body_remains_available_without_another_decode():
    from aiohttp import ClientResponseError

    client = session()
    response = Response({"error": {"code": 403}}, status=403)
    response.raise_for_status.side_effect = ClientResponseError(Mock(), (), status=403)
    client.active_session.get.return_value = response
    returned = await client.request("https://fixture.invalid/denied")
    assert returned is response
    assert await consume_response_json(returned) == {"error": {"code": 403}}
    response.json.assert_awaited_once()
    response.release.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("json_requests", [False, True])
async def test_bulk_requests_bound_admission_keep_order_and_cancel_children(
    json_requests,
):
    client = session(concurrency=3)
    admitted = []
    closed = []
    saturated = asyncio.Event()
    gates = [asyncio.Event() for _ in range(7)]

    async def request(url, **kwargs):
        index = int(url)
        admitted.append(index)
        if len(admitted) == 3:
            saturated.set()
        try:
            await gates[index].wait()
            return {"id": index} if json_requests else index
        finally:
            closed.append(index)

    client.request = request
    client.json_request = request
    fetch = client.bulk_json_requests if json_requests else client.bulk_requests
    running = asyncio.create_task(fetch([str(i) for i in range(7)]))
    await asyncio.wait_for(saturated.wait(), 1)
    assert admitted == [0, 1, 2]
    # Complete pages in reverse order while preserving the public ordered result.
    for gate in reversed(gates):
        gate.set()
    expected = [{"id": i} for i in range(7)] if json_requests else list(range(7))
    assert await asyncio.wait_for(running, 1) == expected

    admitted.clear()
    closed.clear()
    saturated.clear()
    for gate in gates:
        gate.clear()
    running = asyncio.create_task(fetch([str(i) for i in range(1_000_000)]))
    await asyncio.wait_for(saturated.wait(), 1)
    assert admitted == [0, 1, 2]
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert set(closed) == {0, 1, 2}


@pytest.mark.asyncio
async def test_bulk_json_keeps_payload_pairing_and_existing_short_zip_contract():
    client = session(concurrency=3)
    client.json_request = AsyncMock(side_effect=lambda url, **kw: {"url": url, **kw})
    assert await client.bulk_json_requests(
        ["a", "b", "c"], [{"x": 1}, {"x": 2}], "POST"
    ) == [
        {"url": "a", "payload": {"x": 1}, "method": "POST"},
        {"url": "b", "payload": {"x": 2}, "method": "POST"},
    ]
    client.session_manager.max_threads = 0
    with pytest.raises(ValueError, match="positive integer"):
        await client.bulk_json_requests(["a"])


@pytest.mark.asyncio
async def test_rate_limit_probe_is_async_single_owned_and_closed_on_shutdown(
    monkeypatch,
):
    entered = asyncio.Event()
    closed = []

    class Probe:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            closed.append(True)

        def get(self, url, **kwargs):
            return PendingResponse()

    class PendingResponse:
        async def __aenter__(self):
            entered.set()
            await asyncio.Event().wait()

        async def __aexit__(self, *_):
            pass

    monkeypatch.setattr(
        "ultima_scraper_api.managers.session_manager.ClientSession",
        lambda **kw: Probe(),
    )
    monkeypatch.setattr(
        "ultima_scraper_api.managers.session_manager.aiohttp.TCPConnector",
        lambda **kw: object(),
    )
    manager = bare_session_manager()
    manager._rate_limit_task = None
    manager.rate_limit_checker_active = False
    manager.rate_limit_check = True
    # The direct route's cooldown has already elapsed; probe immediately.
    manager._route_rate_limit_until.clear()
    manager.lock = asyncio.Lock()
    manager.time2sleep = 5
    task = manager.start_rate_limit_checker()
    assert manager.start_rate_limit_checker() is task
    await asyncio.wait_for(entered.wait(), 1)
    assert manager.rate_limit_checker_active
    # The event loop reached here while the HTTP probe is still pending.
    await manager.stop_rate_limit_checker()
    assert task.cancelled()
    assert closed == [True]
    assert manager._rate_limit_task is None
    assert not manager.rate_limit_checker_active
    assert not manager._route_rate_limit_tasks


def test_media_type_aliases_keep_their_exact_existing_singular_values():
    from ultima_scraper_api import MediaType
    from ultima_scraper_api.apis.onlyfans.classes.media_model import MediaModel

    expected = {
        "gif": "gif",
        "photo": "image",
        "image": "image",
        "video": "video",
        "stream": "video",
        "application": "video",
        "audio": "audio",
    }
    observed_types = set()
    for api_type, singular in expected.items():
        observed_types.add(MediaType.from_api_type(api_type))
        for spelling in (api_type, api_type.upper()):
            assert (
                MediaModel({"id": 1, "type": spelling}, SimpleNamespace()).type
                == singular
            )
    assert observed_types == set(MediaType)
    with pytest.raises(ValueError, match="Unknown media type"):
        MediaModel({"id": 1, "type": "unsupported"}, SimpleNamespace())


@pytest.mark.asyncio
async def test_rate_limit_429_waits_then_resumes_and_closes_the_probe(monkeypatch):
    statuses = iter([429, 200])
    paused = []
    resumed = asyncio.Event()

    class Probe:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def get(self, url, **kwargs):
            return Response(status=next(statuses))

    real_sleep = asyncio.sleep

    async def sleep(delay):
        if manager.rate_limit_check:
            paused.append((delay, manager.is_rate_limited))
            await real_sleep(0)
        else:
            resumed.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(
        "ultima_scraper_api.managers.session_manager.ClientSession",
        lambda **kw: Probe(),
    )
    monkeypatch.setattr(
        "ultima_scraper_api.managers.session_manager.asyncio.sleep", sleep
    )
    monkeypatch.setattr(
        "ultima_scraper_api.managers.session_manager.aiohttp.TCPConnector",
        lambda **kw: object(),
    )
    manager = bare_session_manager()
    manager._rate_limit_task = None
    manager.rate_limit_checker_active = False
    manager.time2sleep = 7
    manager.rate_limit_check = True
    # The direct route's cooldown has already elapsed; probe immediately.
    manager._route_rate_limit_until.clear()
    manager.lock = asyncio.Lock()
    manager.start_rate_limit_checker()
    await asyncio.wait_for(resumed.wait(), 1)
    # The 429 waits time2sleep before re-probing, and every wait happens
    # while the route is still limited (the patched sleep does not advance
    # the cooldown clock, so the remaining cooldown is also slept here).
    assert paused[0] == (7, True)
    assert all(limited is True for _, limited in paused)
    assert manager.rate_limit_check is False
    assert manager.is_rate_limited is None
    await manager.stop_rate_limit_checker()


@pytest.mark.asyncio
async def test_real_aiohttp_response_handoff_preserves_retry_and_binary_streams(
    monkeypatch,
):
    import os
    import aiohttp
    from aiohttp import web

    if os.environ.get("USR_TEST_WITH_HTTP") != "1":
        pytest.skip(
            "Opt in to a private disposable HTTP listener with USR_TEST_WITH_HTTP=1"
        )
    attempts = 0

    async def endpoint(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return web.Response(body=b"{invalid", content_type="application/json")
        return web.json_response({"list": [1, 2, 3]})

    app = web.Application()
    app.router.add_get("/json", endpoint)

    async def file_endpoint(request):
        return web.Response(body=b"content", content_type="application/octet-stream")

    app.router.add_get("/file", file_endpoint)
    runner = web.AppRunner(app)
    await runner.setup()
    listener = web.TCPSite(runner, "127.0.0.1", 0)
    try:
        await listener.start()
        port = runner.addresses[0][1]
        origin = f"http://127.0.0.1:{port}"
        original_json = aiohttp.ClientResponse.json
        decode_calls = 0

        async def count_json(response, *args, **kwargs):
            nonlocal decode_calls
            decode_calls += 1
            return await original_json(response, *args, **kwargs)

        monkeypatch.setattr(aiohttp.ClientResponse, "json", count_json)
        async with aiohttp.ClientSession() as transport:
            client = session()
            client.active_session = transport
            assert await client.json_request(origin + "/json") == {"list": [1, 2, 3]}
            assert attempts == 2 and decode_calls == 2
            response = await client.request(
                origin + "/file", premade_settings="download"
            )
            assert await response.read() == b"content"
            assert decode_calls == 2
            response.release()
    finally:
        await runner.cleanup()
