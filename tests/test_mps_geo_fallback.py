from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ultima_scraper_api import ContentType

from ultima_scraper_backend.api.routes.jobs import (
    TaskPayload,
    _build_task_from_payload,
)
from ultima_scraper_backend.job_system.handlers.scrape.handler import (
    _mark_user_invalid,
    scrape_task_handler,
)
from ultima_scraper_backend.job_system.job_builder import build_task
from ultima_scraper_backend.job_system.models import Task, TaskRunContext, TaskType
from ultima_scraper_backend.job_system.payloads import ScrapeTaskPayload
from ultima_scraper_backend.job_system import guest_sessions, mps_tasks


def _database_writer() -> SimpleNamespace:
    return SimpleNamespace(submit=AsyncMock(return_value={"synced": True}))


@pytest.fixture(autouse=True)
def no_guest_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler.MPS_GUEST_ROUTE_RETRY_DELAY_SECONDS",
        0.0,
    )


@pytest.mark.asyncio
async def test_mark_user_invalid_queues_a_fresh_checked_timestamp() -> None:
    previous_check = datetime.now(timezone.utc) - timedelta(days=30)
    database_writes = SimpleNamespace(
        submit=AsyncMock(return_value={"upserted": True})
    )

    await _mark_user_invalid(
        task=SimpleNamespace(site_name="OnlyFans", task_id="task-invalid-user"),
        context=SimpleNamespace(
            site="OnlyFans",
            worker_id="test-worker",
            database_writes=database_writes,
            context={},
        ),
        user_id=123,
    )

    database_writes.submit.assert_awaited_once()
    payload = database_writes.submit.await_args.args[1]
    assert payload["user_id"] == 123
    assert payload["reason"] == "not_found"
    assert datetime.fromisoformat(payload["checked_at"]) > previous_check
    assert database_writes.submit.await_args.kwargs["site"] == "onlyfans"


def test_scrape_task_payload_with_fallback_proxies() -> None:
    payload = ScrapeTaskPayload(
        user_username="testuser",
        use_guest_auth=True,
        guest_proxy_url="http://proxy1:8080",
        guest_fallback_proxy_urls=["http://proxy2:8080", "http://proxy3:8080"],
        guest_direct_route_index=1,
    )
    assert payload.use_guest_auth is True
    assert payload.guest_proxy_url == "http://proxy1:8080"
    assert payload.guest_fallback_proxy_urls == [
        "http://proxy2:8080",
        "http://proxy3:8080",
    ]
    assert payload.guest_direct_route_index == 1


def test_build_task_passes_fallback_proxies() -> None:
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=12345,
        user_username="12345",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://proxy1:8080",
        guest_fallback_proxy_urls=["http://proxy2:8080", "http://proxy3:8080"],
        guest_direct_route_index=2,
    )
    assert isinstance(task.payload, ScrapeTaskPayload)
    assert task.payload.guest_proxy_url == "http://proxy1:8080"
    assert task.payload.guest_fallback_proxy_urls == [
        "http://proxy2:8080",
        "http://proxy3:8080",
    ]
    assert task.payload.guest_direct_route_index == 2


@pytest.mark.asyncio
async def test_convert_task_payload_parses_guest_fallback_proxies() -> None:
    backend_manager = SimpleNamespace()
    payload = TaskPayload(
        task_type="scrape_user",
        params={
            "site": "OnlyFans",
            "user_id": 999,
            "username": "999",
            "content_types": ["Profile"],
            "use_guest_auth": True,
            "guest_proxy_url": "http://primary:8080",
            "guest_fallback_proxy_urls": [
                "http://primary:8080",  # Duplicate of primary, should be filtered
                "http://fallback1:8080",
                "http://fallback2:8080",
                "http://fallback1:8080",  # Duplicate, should be deduplicated
            ],
            "guest_direct_route_index": "1",
            "track_invalid_user": True,
        },
    )

    task = await _build_task_from_payload(payload, backend_manager)
    assert isinstance(task, Task)
    assert isinstance(task.payload, ScrapeTaskPayload)
    assert task.payload.guest_proxy_url == "http://primary:8080"
    assert task.payload.guest_fallback_proxy_urls == [
        "http://fallback1:8080",
        "http://fallback2:8080",
    ]
    assert task.payload.guest_direct_route_index == 1


@pytest.mark.asyncio
async def test_scrape_handler_recovers_via_fallback_proxy_on_geoblock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=8888,
        user_username="8888",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://primary:8080",
        guest_fallback_proxy_urls=[
            "http://fallback-us:8080",
            "http://fallback-de:8080",
        ],
        track_invalid_user=True,
        max_items=1,
    )

    fake_primary_authed = SimpleNamespace(id=1, username="guest_primary")
    fake_fallback1_authed = SimpleNamespace(
        id=2,
        username="guest_fallback1",
        release_user=Mock(return_value=True),
    )

    # Primary proxy gets blocked (find_user/get_user returns None)
    # Fallback 1 resolves the user
    resolved_user = SimpleNamespace(
        id=8888,
        username="coolcreator",
        posts_count=10,
        archived_posts_count=0,
    )

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        if proxy_url == "http://primary:8080":
            return fake_primary_authed
        elif proxy_url == "http://fallback-us:8080":
            return fake_fallback1_authed
        return None

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        if authed is fake_fallback1_authed:
            return resolved_user
        return None

    mark_invalid_mock = AsyncMock()
    database_writes = _database_writer()

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )
    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": database_writes,
        },
    )

    result = await scrape_task_handler(task, context)

    assert result.success is True
    assert mark_invalid_mock.await_count == 0
    assert database_writes.submit.await_count == 1
    fake_fallback1_authed.release_user.assert_called_once_with(8888)


@pytest.mark.asyncio
async def test_scrape_handler_recovers_when_primary_guest_auth_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=8889,
        user_username="8889",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://primary:8080",
        guest_fallback_proxy_urls=["http://fallback:8080"],
        track_invalid_user=True,
        max_items=1,
    )
    fallback_authed = SimpleNamespace(
        id=2,
        username="guest_fallback",
        release_user=Mock(return_value=True),
    )
    resolved_user = SimpleNamespace(
        id=8889,
        username="fallbackcreator",
        posts_count=10,
        archived_posts_count=0,
    )
    attempted_proxy_urls: list[str | None] = []

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        attempted_proxy_urls.append(proxy_url)
        return fallback_authed if proxy_url == "http://fallback:8080" else None

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        return resolved_user if authed is fallback_authed else None

    mark_invalid_mock = AsyncMock()
    database_writes = _database_writer()
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )
    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": database_writes,
        },
    )

    result = await scrape_task_handler(task, context)

    assert result.success is True
    assert attempted_proxy_urls == [
        "http://primary:8080",
        "http://fallback:8080",
    ]
    assert mark_invalid_mock.await_count == 0
    assert database_writes.submit.await_count == 1
    fallback_authed.release_user.assert_called_once_with(8889)


@pytest.mark.asyncio
async def test_scrape_handler_uses_direct_connection_at_configured_route_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=8890,
        user_username="8890",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://primary:8080",
        guest_fallback_proxy_urls=["http://fallback:8080"],
        guest_direct_route_index=1,
        track_invalid_user=True,
        max_items=1,
    )
    proxy_authed = SimpleNamespace(id=1, username="guest_proxy")
    direct_authed = SimpleNamespace(
        id=2,
        username="guest_direct",
        release_user=Mock(return_value=True),
    )
    resolved_user = SimpleNamespace(
        id=8890,
        username="directcreator",
        posts_count=0,
        archived_posts_count=0,
    )
    attempted_proxy_urls: list[str | None] = []

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        del site_api, worker_id
        attempted_proxy_urls.append(proxy_url)
        return direct_authed if proxy_url is None else proxy_authed

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        del user_id, username, worker_id
        return resolved_user if authed is direct_authed else None

    mark_invalid_mock = AsyncMock()
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )
    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )

    result = await scrape_task_handler(task, context)

    assert result.success is True
    assert attempted_proxy_urls == ["http://primary:8080", None]
    assert mark_invalid_mock.await_count == 0
    direct_authed.release_user.assert_called_once_with(8890)


@pytest.mark.asyncio
async def test_scrape_handler_times_out_bad_route_and_uses_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=8891,
        user_username="8891",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://slow-primary:8080",
        guest_fallback_proxy_urls=["http://healthy-fallback:8080"],
        track_invalid_user=True,
        max_items=1,
    )
    primary_authed = SimpleNamespace(id=1, username="guest_primary")
    fallback_authed = SimpleNamespace(
        id=2,
        username="guest_fallback",
        release_user=Mock(return_value=True),
    )
    resolved_user = SimpleNamespace(
        id=8891,
        username="fallbackcreator",
        posts_count=0,
        archived_posts_count=0,
    )

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        del site_api, worker_id
        return (
            primary_authed
            if proxy_url == "http://slow-primary:8080"
            else fallback_authed
        )

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        del user_id, username, worker_id
        if authed is primary_authed:
            await asyncio.Event().wait()
        return resolved_user

    mark_invalid_mock = AsyncMock()
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler.MPS_GUEST_LOOKUP_ROUTE_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )
    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )

    result = await scrape_task_handler(task, context)

    assert result.success is True
    assert mark_invalid_mock.await_count == 0
    fallback_authed.release_user.assert_called_once_with(8891)


@pytest.mark.asyncio
async def test_scrape_handler_times_out_guest_auth_init_and_uses_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=8892,
        user_username="8892",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://hanging-primary:8080",
        guest_fallback_proxy_urls=["http://healthy-fallback:8080"],
        track_invalid_user=True,
        max_items=1,
    )
    fallback_authed = SimpleNamespace(
        id=2,
        username="guest_fallback",
        release_user=Mock(return_value=True),
    )
    resolved_user = SimpleNamespace(
        id=8892,
        username="fallbackcreator2",
        posts_count=0,
        archived_posts_count=0,
    )

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        del site_api, worker_id
        if proxy_url == "http://hanging-primary:8080":
            await asyncio.Event().wait()
        return fallback_authed

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        del user_id, username, worker_id
        return resolved_user

    mark_invalid_mock = AsyncMock()
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler.MPS_GUEST_LOOKUP_ROUTE_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )
    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )

    result = await scrape_task_handler(task, context)

    assert result.success is True
    assert mark_invalid_mock.await_count == 0
    fallback_authed.release_user.assert_called_once_with(8892)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["initialization", "lookup"])
@pytest.mark.parametrize("retry_outcome", ["found", "missing", "unavailable"])
async def test_guest_lookup_retries_only_inconclusive_routes(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure_stage: str,
    retry_outcome: str,
) -> None:
    routes = [
        "http://primary:8080",
        "http://retry-user:retry-secret@intermittent:8080",
        "http://fallback2:8080",
        "http://fallback3:8080",
        None,
    ]
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=3482765,
        user_username="3482765",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url=routes[0],
        guest_fallback_proxy_urls=routes[1:4],
        guest_direct_route_index=4,
        track_invalid_user=True,
        max_items=1,
    )
    auths = {
        route: SimpleNamespace(
            id=index + 1,
            username=f"guest_{index}",
            release_user=Mock(return_value=True),
        )
        for index, route in enumerate(routes)
    }
    resolved_user = SimpleNamespace(
        id=3482765, username="recovered", posts_count=0, archived_posts_count=0
    )
    attempted_routes: list[str | None] = []
    bad_attempts = 0

    def route_is_unavailable() -> bool:
        return bad_attempts == 1 or retry_outcome == "unavailable"

    async def resolve_auth(site_api, proxy_url, worker_id):
        nonlocal bad_attempts
        attempted_routes.append(proxy_url)
        if proxy_url == routes[1]:
            bad_attempts += 1
            if failure_stage == "initialization" and route_is_unavailable():
                return None
        return auths[proxy_url]

    async def resolve_user(authed, user_id, username, worker_id):
        if authed is auths[routes[1]]:
            if failure_stage == "lookup" and route_is_unavailable():
                raise TimeoutError
            if retry_outcome == "found":
                return resolved_user
        return None

    mark_invalid = AsyncMock()
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        resolve_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        resolve_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid,
    )
    context = TaskRunContext(
        job=SimpleNamespace(job_id="retry-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )
    caplog.set_level(logging.DEBUG)

    result = await scrape_task_handler(task, context)

    retry_count = 2 if retry_outcome == "unavailable" else 1
    assert attempted_routes == [*routes, *([routes[1]] * retry_count)]
    assert "retry-user" not in caplog.text
    assert "retry-secret" not in caplog.text
    assert "Retrying guest route http://intermittent:8080" in caplog.text
    if retry_outcome in ("missing", "unavailable"):
        assert result.success is True
        assert result.output["invalid_user"] is True
        assert "attempted" in result.message
        mark_invalid.assert_awaited_once()
    else:
        assert result.success is True
        mark_invalid.assert_not_awaited()
        auths[routes[1]].release_user.assert_called_once_with(3482765)


@pytest.mark.asyncio
async def test_scrape_handler_does_not_retire_user_when_all_lookups_time_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=8892,
        user_username="8892",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://slow-only:8080",
        track_invalid_user=True,
        max_items=1,
    )

    async def slow_lookup(authed, user_id, username, worker_id):
        del authed, user_id, username, worker_id
        await asyncio.Event().wait()

    mark_invalid_mock = AsyncMock()
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler.MPS_GUEST_LOOKUP_ROUTE_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        AsyncMock(return_value=SimpleNamespace(id=1, username="guest")),
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        slow_lookup,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )
    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )

    result = await scrape_task_handler(task, context)

    assert result.success is False
    assert "1 lookup" in result.message
    assert result.continue_job_on_failure is True
    assert result.metrics["failure_kind"] == "guest_route_unavailable"
    assert result.metrics["proxy_route_failures"] == 1
    assert mark_invalid_mock.await_count == 0


@pytest.mark.asyncio
async def test_scrape_handler_does_not_mark_invalid_after_guest_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=9998,
        user_username="9998",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://primary:8080",
        guest_fallback_proxy_urls=["http://fallback:8080"],
        track_invalid_user=True,
        max_items=1,
    )
    primary_authed = SimpleNamespace(id=1, username="guest_primary")

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        return primary_authed if proxy_url == "http://primary:8080" else None

    mark_invalid_mock = AsyncMock()
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )
    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )

    result = await scrape_task_handler(task, context)

    assert result.success is False
    assert "1 of 2 proxy route(s) failed to initialize" in result.message
    assert result.continue_job_on_failure is True
    assert mark_invalid_mock.await_count == 0


@pytest.mark.asyncio
async def test_scrape_handler_masks_proxy_credentials_in_fallback_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    primary_proxy_url = "http://primary-user:primary-secret@primary:8080"
    fallback_proxy_url = "http://fallback-user:fallback-secret@fallback:8080"
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=8890,
        user_username="8890",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url=primary_proxy_url,
        guest_fallback_proxy_urls=[fallback_proxy_url],
        max_items=1,
    )
    primary_authed = SimpleNamespace(id=1, username="guest_primary")
    fallback_authed = SimpleNamespace(id=2, username="guest_fallback")
    resolved_user = SimpleNamespace(
        id=8890,
        username="safecreator",
        posts_count=10,
        archived_posts_count=0,
    )

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        return fallback_authed if proxy_url == fallback_proxy_url else primary_authed

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        return resolved_user if authed is fallback_authed else None

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )
    caplog.set_level(logging.DEBUG)

    result = await scrape_task_handler(task, context)

    assert result.success is True
    assert "primary-user" not in caplog.text
    assert "primary-secret" not in caplog.text
    assert "fallback-user" not in caplog.text
    assert "fallback-secret" not in caplog.text
    assert "http://primary:8080" in caplog.text
    assert "http://fallback:8080" in caplog.text


@pytest.mark.asyncio
async def test_scrape_handler_marks_invalid_when_all_fallbacks_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=9999,
        user_username="9999",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://primary:8080",
        guest_fallback_proxy_urls=["http://fallback1:8080", "http://fallback2:8080"],
        track_invalid_user=True,
        max_items=1,
    )

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        return SimpleNamespace(id=1, username=f"guest_{proxy_url}")

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        # All proxies fail
        return None

    mark_invalid_mock = AsyncMock()

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )

    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )

    result = await scrape_task_handler(task, context)

    assert result.success is True
    assert result.output.get("invalid_user") is True
    assert result.output.get("proxy_url") is None
    assert result.output.get("proxy_hop_used") is None
    assert result.output.get("proxy_routes") == [
        "http://primary:8080",
        "http://fallback1:8080",
        "http://fallback2:8080",
    ]
    assert sorted(result.output.get("proxy_routes_attempted") or []) == [0, 1, 2]
    assert mark_invalid_mock.await_count == 1
    assert "attempted 3 proxy route(s)" in result.message


def test_resolve_mps_task_routes_3_hop_maximum() -> None:
    pool = [f"http://p{i}:8080" for i in range(10)]

    # When direct route is included: 1 primary + 1 fallback + 1 direct = 3 total hops
    primary, fallbacks, direct_idx = mps_tasks._resolve_mps_task_routes(
        task_index=0,
        proxy_pool=pool,
        proxy_start_index=0,
        include_direct=True,
    )
    assert primary == "http://p0:8080"
    assert len(fallbacks) == 1
    assert direct_idx is not None
    assert (1 + len(fallbacks) + 1) == 3

    # When direct route is excluded: 1 primary + 2 fallbacks = 3 total hops
    primary, fallbacks, direct_idx = mps_tasks._resolve_mps_task_routes(
        task_index=0,
        proxy_pool=pool,
        proxy_start_index=0,
        include_direct=False,
    )
    assert primary == "http://p0:8080"
    assert len(fallbacks) == 2
    assert direct_idx is None
    assert (1 + len(fallbacks)) == 3


def test_resolve_mps_task_routes_selects_geo_diverse_fallbacks() -> None:
    pool = [
        "http://proxy-us-1:8080",
        "http://proxy-us-2:8080",
        "http://proxy-us-3:8080",
        "http://proxy-gb-1:8080",
        "http://proxy-de-1:8080",
    ]
    geo_map = {
        "http://proxy-us-1:8080": "US",
        "http://proxy-us-2:8080": "US",
        "http://proxy-us-3:8080": "US",
        "http://proxy-gb-1:8080": "GB",
        "http://proxy-de-1:8080": "DE",
    }

    # With direct connection (max 2 proxies): should select US primary and skip US-2, US-3 to select GB-1
    primary, fallbacks, _ = mps_tasks._resolve_mps_task_routes(
        task_index=0,
        proxy_pool=pool,
        proxy_start_index=0,
        include_direct=True,
        proxy_geo_map=geo_map,
    )
    assert primary == "http://proxy-us-1:8080"
    assert fallbacks == ["http://proxy-gb-1:8080"]

    # Without direct connection (max 3 proxies): should select US primary, GB-1, and DE-1
    primary, fallbacks, _ = mps_tasks._resolve_mps_task_routes(
        task_index=0,
        proxy_pool=pool,
        proxy_start_index=0,
        include_direct=False,
        proxy_geo_map=geo_map,
    )
    assert primary == "http://proxy-us-1:8080"
    assert set(fallbacks) == {"http://proxy-gb-1:8080", "http://proxy-de-1:8080"}


def test_resolve_mps_task_routes_partial_geo_fills_residual_slots() -> None:
    pool = [
        "http://proxy-us-1:8080",
        "http://proxy-us-2:8080",
        "http://proxy-us-3:8080",
        "http://proxy-us-4:8080",
    ]
    geo_map = {
        "http://proxy-us-1:8080": "US",
        "http://proxy-us-2:8080": "US",
        "http://proxy-us-3:8080": "US",
        "http://proxy-us-4:8080": "US",
    }

    # All proxies are US. With include_direct=False (needs 3 proxies):
    # Pass 1 picks us-1. Pass 2 finds no distinct countries.
    # Pass 3 fills residual slots with us-2 and us-3.
    primary, fallbacks, _ = mps_tasks._resolve_mps_task_routes(
        task_index=0,
        proxy_pool=pool,
        proxy_start_index=0,
        include_direct=False,
        proxy_geo_map=geo_map,
    )
    assert primary == "http://proxy-us-1:8080"
    assert fallbacks == ["http://proxy-us-2:8080", "http://proxy-us-3:8080"]
    assert len(set([primary] + fallbacks)) == 3


def test_resolve_mps_task_routes_rotates_geo_fallbacks_across_tasks() -> None:
    pool = [
        "http://p1-us:8080",
        "http://p2-us:8080",
        "http://p3-gb:8080",
        "http://p4-gb:8080",
        "http://p5-de:8080",
        "http://p6-de:8080",
    ]
    geo_map = {
        "http://p1-us:8080": "US",
        "http://p2-us:8080": "US",
        "http://p3-gb:8080": "GB",
        "http://p4-gb:8080": "GB",
        "http://p5-de:8080": "DE",
        "http://p6-de:8080": "DE",
    }

    # Primary order stays cyclic; each task gets distinct geographic fallbacks.
    p0, f0, _ = mps_tasks._resolve_mps_task_routes(
        task_index=0,
        proxy_pool=pool,
        proxy_start_index=0,
        include_direct=False,
        proxy_geo_map=geo_map,
    )
    assert p0 == "http://p1-us:8080"
    assert {geo_map[url] for url in f0} == {"GB", "DE"}

    # Task 1 retains the next primary and geographic diversity.
    p1, f1, _ = mps_tasks._resolve_mps_task_routes(
        task_index=1,
        proxy_pool=pool,
        proxy_start_index=0,
        include_direct=False,
        proxy_geo_map=geo_map,
    )
    assert p1 == "http://p2-us:8080"
    assert {geo_map[url] for url in f1} == {"GB", "DE"}

    # A GB primary gets US and DE fallbacks.
    p2, f2, _ = mps_tasks._resolve_mps_task_routes(
        task_index=2,
        proxy_pool=pool,
        proxy_start_index=0,
        include_direct=False,
        proxy_geo_map=geo_map,
    )
    assert p2 == "http://p3-gb:8080"
    assert {geo_map[url] for url in f2} == {"US", "DE"}
    selected = set()
    for task_index in range(100):
        _, fallbacks, _ = mps_tasks._resolve_mps_task_routes(
            task_index=task_index, proxy_pool=pool, proxy_start_index=0,
            proxy_geo_map=geo_map,
        )
        selected.update(fallbacks)
    assert selected == set(pool)


@pytest.mark.asyncio
async def test_scrape_handler_recovers_via_geo_diverse_fallback_on_geoblock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = [
        "http://primary-us:8080",
        "http://skipped-us:8080",
        "http://fallback-gb:8080",
    ]
    geo_map = {
        "http://primary-us:8080": "US",
        "http://skipped-us:8080": "US",
        "http://fallback-gb:8080": "GB",
    }
    primary_proxy, fallback_proxies, direct_idx = mps_tasks._resolve_mps_task_routes(
        task_index=0,
        proxy_pool=pool,
        proxy_start_index=0,
        include_direct=False,
        proxy_geo_map=geo_map,
    )
    assert primary_proxy == "http://primary-us:8080"
    assert fallback_proxies[0] == "http://fallback-gb:8080"

    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=7777,
        user_username="7777",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url=primary_proxy,
        guest_fallback_proxy_urls=fallback_proxies,
        track_invalid_user=True,
        max_items=1,
    )

    fake_primary_authed = SimpleNamespace(id=1, username="guest_primary_us")
    fake_gb_authed = SimpleNamespace(
        id=2,
        username="guest_fallback_gb",
        release_user=Mock(return_value=True),
    )
    resolved_user = SimpleNamespace(
        id=7777,
        username="uk_creator",
        posts_count=5,
        archived_posts_count=0,
    )

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        if proxy_url == "http://primary-us:8080":
            return fake_primary_authed
        elif proxy_url == "http://fallback-gb:8080":
            return fake_gb_authed
        return None

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        # US is geoblocked, GB succeeds!
        if authed is fake_gb_authed:
            return resolved_user
        return None

    mark_invalid_mock = AsyncMock()

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )

    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )

    result = await scrape_task_handler(task, context)

    assert result.success is True
    assert result.output.get("items_scraped") == 1
    assert result.output.get("username") == "uk_creator"
    assert mark_invalid_mock.await_count == 0


def test_get_cached_proxy_geo_map_caching(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reset in-memory cache
    original_map = mps_tasks._CACHED_GEO_MAP
    original_at = mps_tasks._CACHED_GEO_MAP_AT
    mps_tasks._CACHED_GEO_MAP = {}
    mps_tasks._CACHED_GEO_MAP_AT = 0.0

    try:
        mock_service = Mock()
        mock_service.get_all_cached_geolocations.return_value = [
            {"proxy_url": "http://proxy1:8080", "country_code": "US"},
            {"proxy_url": "http://proxy2:8080/", "country_code": "gb"},
        ]

        monkeypatch.setattr(
            "ultima_scraper_backend.helpers.ip_geolocation.get_geolocation_service",
            lambda: mock_service,
        )

        geo_map1 = mps_tasks.get_cached_proxy_geo_map()
        assert geo_map1["http://proxy1:8080"] == "US"
        assert geo_map1["http://proxy2:8080"] == "GB"
        assert mock_service.get_all_cached_geolocations.call_count == 1

        # Second call should use in-memory cache within TTL
        geo_map2 = mps_tasks.get_cached_proxy_geo_map()
        assert geo_map2 == geo_map1
        assert mock_service.get_all_cached_geolocations.call_count == 1
    finally:
        mps_tasks._CACHED_GEO_MAP = original_map
        mps_tasks._CACHED_GEO_MAP_AT = original_at


def test_empty_proxy_geo_map_is_cached_until_expiry(monkeypatch):
    monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP", {})
    monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP_AT", 0.0)
    now = [100.0]
    monkeypatch.setattr(mps_tasks.time, "monotonic", lambda: now[0])
    service = Mock()
    service.get_all_cached_geolocations.return_value = []
    monkeypatch.setattr(
        "ultima_scraper_backend.helpers.ip_geolocation.get_geolocation_service",
        lambda: service,
    )
    assert mps_tasks.get_cached_proxy_geo_map() == {}
    assert mps_tasks.get_cached_proxy_geo_map() == {}
    assert service.get_all_cached_geolocations.call_count == 1
    now[0] += mps_tasks._GEO_MAP_CACHE_TTL + 1
    assert mps_tasks.get_cached_proxy_geo_map() == {}
    assert service.get_all_cached_geolocations.call_count == 2


def test_shared_geo_lookup_failure_does_not_cache_an_empty_result(monkeypatch):
    from ultima_scraper_backend.helpers.ip_geolocation import IPGeolocationService

    monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP", {})
    monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP_AT", 0.0)
    session = Mock()
    session.execute.side_effect = RuntimeError("Database lookup failed")
    monkeypatch.setattr(
        "ultima_scraper_backend.helpers.ip_geolocation.get_geolocation_service",
        lambda: IPGeolocationService(),
    )
    with pytest.raises(RuntimeError, match="Database lookup failed"):
        mps_tasks.get_cached_proxy_geo_map(db_session=session)
    assert mps_tasks._CACHED_GEO_MAP_AT == 0.0
    session.rollback.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.asyncio
async def test_scrape_handler_treats_2_not_found_plus_1_timeout_as_invalid_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 3-route lookup: Route 0 -> 404, Route 1 -> 404, Route 2 -> TimeoutError
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=17331061,
        user_username="17331061",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://route0:8080",
        guest_fallback_proxy_urls=["http://route1:8080", "http://route2:8080"],
        track_invalid_user=True,
        max_items=1,
    )

    fake_authed0 = SimpleNamespace(id=1, username="guest_route0")
    fake_authed1 = SimpleNamespace(id=2, username="guest_route1")
    fake_authed2 = SimpleNamespace(id=3, username="guest_route2")

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        if proxy_url == "http://route0:8080":
            return fake_authed0
        elif proxy_url == "http://route1:8080":
            return fake_authed1
        return fake_authed2

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        if authed is fake_authed0:
            return None  # HTTP 404
        elif authed is fake_authed1:
            return None  # HTTP 404
        # Route 2 suffers socket timeout / network error
        raise TimeoutError("Socket timeout")

    mark_invalid_mock = AsyncMock()

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )

    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )

    result = await scrape_task_handler(task, context)

    # Must succeed and mark invalid instead of failing task and tripping circuit breaker!
    assert result.success is True
    assert result.output.get("invalid_user") is True
    assert result.output.get("user_id") == 17331061
    assert "2 route(s) returned 404" in result.message
    assert "1 route(s) inconclusive" in result.message
    assert mark_invalid_mock.await_count == 1
    call_kwargs = mark_invalid_mock.await_args.kwargs
    assert call_kwargs["user_id"] == 17331061
    assert call_kwargs["reason"] == "not_found"


@pytest.mark.asyncio
async def test_scrape_handler_keeps_inconclusive_when_only_1_not_found_and_2_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 3-route lookup: Route 0 -> 404, Route 1 -> Timeout, Route 2 -> Timeout
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=17331062,
        user_username="17331062",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://route0:8080",
        guest_fallback_proxy_urls=["http://route1:8080", "http://route2:8080"],
        track_invalid_user=True,
        max_items=1,
    )

    fake_authed0 = SimpleNamespace(id=1, username="guest_route0")
    fake_authed1 = SimpleNamespace(id=2, username="guest_route1")
    fake_authed2 = SimpleNamespace(id=3, username="guest_route2")

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        if proxy_url == "http://route0:8080":
            return fake_authed0
        elif proxy_url == "http://route1:8080":
            return fake_authed1
        return fake_authed2

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        if authed is fake_authed0:
            return None  # HTTP 404
        # Routes 1 and 2 fail
        raise TimeoutError("Socket timeout")

    mark_invalid_mock = AsyncMock()

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )

    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )

    result = await scrape_task_handler(task, context)

    # Only 1 confirmed 404 is inconclusive when 2 routes timed out
    assert result.success is False
    assert result.continue_job_on_failure is True
    assert "Could not conclusively resolve user" in result.message
    assert mark_invalid_mock.await_count == 0


@pytest.mark.asyncio
async def test_scrape_handler_early_exits_when_custom_conclusive_threshold_reached(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=99991,
        user_username="99991",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://route0:8080",
        guest_fallback_proxy_urls=["http://route1:8080", "http://route2:8080"],
        track_invalid_user=True,
        conclusive_miss_threshold=2,
        max_items=1,
    )

    fake_authed0 = SimpleNamespace(id=1, username="guest_route0")
    fake_authed1 = SimpleNamespace(id=2, username="guest_route1")
    fake_authed2 = SimpleNamespace(id=3, username="guest_route2")
    queried_routes: list[str] = []

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        if proxy_url == "http://route0:8080":
            return fake_authed0
        elif proxy_url == "http://route1:8080":
            return fake_authed1
        return fake_authed2

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        if authed is fake_authed0:
            queried_routes.append("http://route0:8080")
            return None  # HTTP 404
        elif authed is fake_authed1:
            queried_routes.append("http://route1:8080")
            return None  # HTTP 404
        queried_routes.append("http://route2:8080")
        return None

    mark_invalid_mock = AsyncMock()

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )

    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )
    caplog.set_level(logging.INFO)

    result = await scrape_task_handler(task, context)

    # Route 2 must NEVER be queried because threshold of 2 misses was reached on Route 1!
    assert result.success is True
    assert result.output.get("invalid_user") is True
    assert result.output.get("user_id") == 99991
    assert queried_routes == ["http://route0:8080", "http://route1:8080"]
    assert "http://route2:8080" not in queried_routes
    assert mark_invalid_mock.await_count == 1
    assert "Conclusive not-found threshold (2) reached" not in caplog.text


@pytest.mark.asyncio
async def test_scrape_handler_defaults_to_3_hops_when_unspecified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=99992,
        user_username="99992",
        content_type=ContentType.PROFILE,
        use_guest_auth=True,
        guest_proxy_url="http://route0:8080",
        guest_fallback_proxy_urls=["http://route1:8080", "http://route2:8080"],
        track_invalid_user=True,
        max_items=1,
    )
    assert task.payload.conclusive_miss_threshold is None

    fake_authed0 = SimpleNamespace(id=1, username="guest_route0")
    fake_authed1 = SimpleNamespace(id=2, username="guest_route1")
    fake_authed2 = SimpleNamespace(id=3, username="guest_route2")
    queried_routes: list[str] = []

    async def fake_resolve_guest_auth(site_api, proxy_url, worker_id):
        if proxy_url == "http://route0:8080":
            return fake_authed0
        elif proxy_url == "http://route1:8080":
            return fake_authed1
        return fake_authed2

    async def fake_resolve_scrape_user(authed, user_id, username, worker_id):
        if authed is fake_authed0:
            queried_routes.append("http://route0:8080")
            return None
        elif authed is fake_authed1:
            queried_routes.append("http://route1:8080")
            return None
        queried_routes.append("http://route2:8080")
        return None

    mark_invalid_mock = AsyncMock()

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_guest_auth",
        fake_resolve_guest_auth,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._resolve_scrape_user",
        fake_resolve_scrape_user,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.scrape.handler._mark_user_invalid",
        mark_invalid_mock,
    )

    context = TaskRunContext(
        job=SimpleNamespace(job_id="test-job"),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": SimpleNamespace(),
            "worker_id": "test-worker",
            "db_managers": {"onlyfans": SimpleNamespace()},
            "database_writes": _database_writer(),
        },
    )

    result = await scrape_task_handler(task, context)

    # All 3 routes must be queried by default
    assert result.success is True
    assert result.output.get("invalid_user") is True
    assert queried_routes == ["http://route0:8080", "http://route1:8080", "http://route2:8080"]
    assert mark_invalid_mock.await_count == 1


def test_build_mps_task_batch_forwards_custom_options() -> None:
    proxy_pool = [
        "http://proxy0:8080",
        "http://proxy1:8080",
        "http://proxy2:8080",
        "http://proxy3:8080",
    ]
    tasks = mps_tasks._build_mps_task_batch(
        job_id="test-mps-custom",
        site_display="OnlyFans",
        target_user_ids=[101, 102],
        proxy_pool=proxy_pool,
        candidate_offset=0,
        max_route_hops=2,
        conclusive_miss_threshold=2,
    )
    assert len(tasks) == 2
    for t in tasks:
        assert isinstance(t.payload, ScrapeTaskPayload)
        assert t.payload.max_route_hops == 2
        assert t.payload.conclusive_miss_threshold == 2
        # max_route_hops=2 means 1 primary + 1 fallback = 2 total routes
        assert t.payload.guest_proxy_url is not None
        assert len(t.payload.guest_fallback_proxy_urls) == 1


def test_timeout_deferral_ignores_hedge_cancellation_and_recovers(monkeypatch):
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    api = SimpleNamespace()
    route = "http://timeout-route:8080"
    monkeypatch.setattr(handler.time, "monotonic", lambda: 100.0)
    for _ in range(3):
        handler._record_mps_guest_route_outcome(api, route, "lookup_cancelled")
    assert not handler._mps_guest_route_is_deferred(api, route)
    for _ in range(3):
        handler._record_mps_guest_route_outcome(api, route, "lookup_timeout")
    assert handler._mps_guest_route_is_deferred(api, route)
    assert not handler._mps_guest_route_is_deferred(api, route, now=131.0)
    for _ in range(3):
        handler._record_mps_guest_route_outcome(api, route, "lookup_timeout")
    handler._record_mps_guest_route_outcome(api, route, "not_found")
    assert not handler._mps_guest_route_is_deferred(api, route)


@pytest.mark.parametrize("fallback_finds", [True, False])
async def test_deferred_primary_remains_available_after_healthy_alternative(monkeypatch, fallback_finds):
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    monkeypatch.setattr(handler, "MPS_GUEST_LOOKUP_HEDGE_DELAY_SECONDS", 0)
    api = SimpleNamespace()
    primary, fallback = "http://slow-primary:8080", "http://healthy:8080"
    for _ in range(3):
        handler._record_mps_guest_route_outcome(api, primary, "lookup_timeout")
    attempts = []
    selections = []
    resolved = SimpleNamespace(id=8800, username="resolved", posts_count=0, archived_posts_count=0)
    async def auth(site_api, proxy_url, worker_id):
        attempts.append(proxy_url)
        return SimpleNamespace(proxy_url=proxy_url, release_user=Mock())
    async def lookup(authed, **kwargs):
        return resolved if (authed.proxy_url == fallback if fallback_finds else authed.proxy_url == primary) else None
    monkeypatch.setattr(handler, "_resolve_guest_auth", auth)
    monkeypatch.setattr(handler, "_resolve_scrape_user", lookup)
    task = build_task(TaskType.SCRAPE, site_name="OnlyFans", user_id=8800, user_username="8800",
        content_type=ContentType.PROFILE, use_guest_auth=True, guest_proxy_url=primary,
        guest_fallback_proxy_urls=[fallback], track_invalid_user=True, max_items=1)
    context = TaskRunContext(job=SimpleNamespace(job_id="route-deferral"),
        storage=SimpleNamespace(persist_task=AsyncMock()), previous_output=None,
        context={"site_api": api, "worker_id": "test-worker", "db_managers": {"onlyfans": SimpleNamespace()},
                 "database_writes": _database_writer(), "record_route_selection": lambda *args: selections.append(args)})
    result = await scrape_task_handler(task, context)
    assert result.success
    assert selections[0] == (handler._route_telemetry_id(fallback), "primary", False, False)
    if not fallback_finds:
        assert selections[1] == (handler._route_telemetry_id(primary), "fallback", True, False)
    assert attempts == ([fallback] if fallback_finds else [fallback, primary])
    assert handler._mps_guest_route_is_deferred(api, primary) is fallback_finds


def test_initialization_failures_defer_but_cancellations_do_not():
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    api = SimpleNamespace()
    route = "http://init-failure:8080"
    for _ in range(3):
        handler._record_mps_guest_route_outcome(api, route, "guest_init_cancelled")
    assert not handler._mps_guest_route_is_deferred(api, route)
    for _ in range(3):
        handler._record_mps_guest_route_outcome(api, route, "guest_init_failure")
    assert handler._mps_guest_route_is_deferred(api, route)
    handler._record_mps_guest_route_outcome(api, route, "found")
    assert not handler._mps_guest_route_is_deferred(api, route)


async def test_guest_auth_observes_shared_login_and_cache_reuse(monkeypatch):
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    authed = SimpleNamespace()
    monkeypatch.setattr(guest_sessions, "_is_guest_auth", lambda value: value is authed)
    monkeypatch.setattr(guest_sessions, "_get_auth_proxy_url", lambda value: "http://shared:8080")
    monkeypatch.setattr(guest_sessions, "_iter_site_auths", lambda api: [])
    async def login(**kwargs):
        await asyncio.sleep(0.01)
        return authed
    api = SimpleNamespace(login=AsyncMock(side_effect=login))
    observations = []
    token = handler._guest_auth_observer.set(lambda name, ms: observations.append((name, ms)))
    try:
        results = await asyncio.gather(*(handler._resolve_guest_auth(api, proxy_url="http://shared:8080", worker_id="test") for _ in range(5)))
        assert all(result is authed for result in results)
        assert await handler._resolve_guest_auth(api, proxy_url="http://shared:8080", worker_id="test") is authed
    finally:
        handler._guest_auth_observer.reset(token)
    names = [name for name, _ in observations]
    assert api.login.await_count == 1
    assert names.count("guest_auth_login_success") == 1
    assert names.count("guest_auth_cache_hit_after_shared_wait") == 4
    assert names.count("guest_auth_cache_hit") == 1
    assert names.count("guest_auth_shared_wait") == 5
    assert names.count("guest_auth_login_wall") == 1


async def test_failed_guest_login_records_reason_and_releases_lock(monkeypatch):
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    monkeypatch.setattr(guest_sessions, "_iter_site_auths", lambda api: [])
    api = SimpleNamespace(login=AsyncMock(side_effect=TimeoutError("fixture")))
    observations = []
    token = handler._guest_auth_observer.set(lambda name, ms: observations.append(name))
    try:
        assert await handler._resolve_guest_auth(api, proxy_url="http://failure:8080", worker_id="test") is None
    finally:
        handler._guest_auth_observer.reset(token)
    assert "guest_auth_login_timeout" in observations
    assert "guest_auth_login_wall" in observations
    assert not api._guest_auth_locks["http://failure:8080"].locked()


async def test_cancelled_waiter_preserves_shared_login(monkeypatch):
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    monkeypatch.setattr(guest_sessions, "_iter_site_auths", lambda api: [])
    entered, finish = asyncio.Event(), asyncio.Event()
    authed = SimpleNamespace()
    monkeypatch.setattr(guest_sessions, "_is_guest_auth", lambda value: value is authed)
    monkeypatch.setattr(guest_sessions, "_get_auth_proxy_url", lambda value: "http://cancelled:8080")
    async def login(**kwargs):
        entered.set()
        await finish.wait()
        return authed
    api = SimpleNamespace(login=AsyncMock(side_effect=login))
    first = asyncio.create_task(handler._resolve_guest_auth(api, proxy_url="http://cancelled:8080", worker_id="test"))
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert len(api._guest_auth_pending) == 1
    second = asyncio.create_task(handler._resolve_guest_auth(api, proxy_url="http://cancelled:8080", worker_id="test"))
    finish.set()
    assert await second is authed
    assert api.login.await_count == 1
    assert not api._guest_auth_pending
    assert await handler._resolve_guest_auth(api, proxy_url="http://cancelled:8080", worker_id="test") is authed


async def test_shared_login_deadline_cleans_up_and_allows_retry(monkeypatch):
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    monkeypatch.setattr(guest_sessions, "_iter_site_auths", lambda api: [])
    monkeypatch.setattr(guest_sessions, "GUEST_SHARED_INIT_TIMEOUT_SECONDS", 0.01)
    async def login(**kwargs):
        await asyncio.Event().wait()
    api = SimpleNamespace(login=login)
    observations = []
    token = handler._guest_auth_observer.set(lambda name, ms: observations.append(name))
    try:
        assert await handler._resolve_guest_auth(api, proxy_url=None, worker_id="test") is None
    finally:
        handler._guest_auth_observer.reset(token)
    assert "guest_auth_shared_init_timeout" in observations
    assert not api._guest_auth_pending
    assert all(not lock.locked() for lock in api._guest_auth_locks.values())
    authed = SimpleNamespace()
    api.login = AsyncMock(return_value=authed)
    assert await handler._resolve_guest_auth(api, proxy_url=None, worker_id="test") is authed


async def test_request_timeout_does_not_cancel_shared_initializer(monkeypatch):
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    monkeypatch.setattr(guest_sessions, "_iter_site_auths", lambda api: [])
    finish = asyncio.Event()
    authed = SimpleNamespace()
    async def login(**kwargs):
        await finish.wait()
        return authed
    api = SimpleNamespace(login=AsyncMock(side_effect=login))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(handler._resolve_guest_auth(api, proxy_url=None, worker_id="test"), timeout=0.01)
    assert len(api._guest_auth_pending) == 1
    finish.set()
    assert await handler._resolve_guest_auth(api, proxy_url=None, worker_id="test") is authed
    assert api.login.await_count == 1
    assert not api._guest_auth_pending


def test_intermittent_route_timeouts_are_deprioritized_and_recover(monkeypatch):
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    monkeypatch.setattr(handler.time, "monotonic", lambda: 100.0)
    api, route = SimpleNamespace(), "http://intermittent:8080"
    for _ in range(4):
        handler._record_mps_guest_route_outcome(api, route, "lookup_timeout")
        handler._record_mps_guest_route_outcome(api, route, "not_found")
    assert handler._mps_guest_route_is_deferred(api, route)
    for _ in range(32):
        handler._record_mps_guest_route_outcome(api, route, "not_found")
    assert not handler._mps_guest_route_is_deferred(api, route)
    recent = next(iter(handler._mps_guest_route_state(api).values()))["recent"]
    assert len(recent) == 32


def test_sparse_old_failures_and_cancellations_do_not_deprioritize(monkeypatch):
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    now = [100.0]
    monkeypatch.setattr(handler.time, "monotonic", lambda: now[0])
    api, route = SimpleNamespace(), "http://old:8080"
    for _ in range(3):
        handler._record_mps_guest_route_outcome(api, route, "lookup_timeout")
        handler._record_mps_guest_route_outcome(api, route, "found")
    now[0] = 200.0
    for _ in range(30):
        handler._record_mps_guest_route_outcome(api, route, "lookup_cancelled")
    handler._record_mps_guest_route_outcome(api, route, "not_found")
    assert not handler._mps_guest_route_is_deferred(api, route)
    assert len(next(iter(handler._mps_guest_route_state(api).values()))["recent"]) == 1


def test_retry_selection_gives_healthy_miss_one_probe_and_keeps_deferred_route():
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    api = SimpleNamespace()
    slow, healthy = "http://slow:8080", "http://healthy:8080"
    for _ in range(3):
        handler._record_mps_guest_route_outcome(api, slow, "lookup_timeout")
    configured = [(0, slow), (1, healthy)]
    probed = set()
    assert handler._select_mps_retry_routes(api, configured, [(0,slow)], {1}, probed) == [(1,healthy),(0,slow)]
    assert probed == {1}
    assert handler._select_mps_retry_routes(api, configured, [(0,slow)], {1}, probed) == [(0,slow)]
    assert handler._select_mps_retry_routes(SimpleNamespace(), configured, [(0,slow)], {1}, set()) == [(0,slow)]


@pytest.mark.asyncio
async def test_healthy_retry_recovers_before_repeating_deferred_route(monkeypatch):
    from ultima_scraper_backend.job_system.handlers.scrape import handler
    monkeypatch.setattr(handler, "MPS_GUEST_LOOKUP_HEDGE_DELAY_SECONDS", 0)
    api = SimpleNamespace()
    primary, fallback = "http://slow-primary:8080", "http://healthy:8080"
    for _ in range(3):
        handler._record_mps_guest_route_outcome(api, primary, "lookup_timeout")
    attempts = []
    selections = []
    resolved = SimpleNamespace(id=8800, username="resolved", posts_count=0, archived_posts_count=0)
    async def auth(site_api, proxy_url, worker_id):
        attempts.append(proxy_url)
        return SimpleNamespace(proxy_url=proxy_url, release_user=Mock())
    healthy_lookups = 0
    async def lookup(authed, **kwargs):
        nonlocal healthy_lookups
        if authed.proxy_url == primary:
            raise TimeoutError()
        healthy_lookups += 1
        return resolved if healthy_lookups == 2 else None
    monkeypatch.setattr(handler, "_resolve_guest_auth", auth)
    monkeypatch.setattr(handler, "_resolve_scrape_user", lookup)
    task = build_task(TaskType.SCRAPE, site_name="OnlyFans", user_id=8800, user_username="8800",
        content_type=ContentType.PROFILE, use_guest_auth=True, guest_proxy_url=primary,
        guest_fallback_proxy_urls=[fallback], track_invalid_user=True, max_items=1)
    context = TaskRunContext(job=SimpleNamespace(job_id="route-deferral"),
        storage=SimpleNamespace(persist_task=AsyncMock()), previous_output=None,
        context={"site_api": api, "worker_id": "test-worker", "db_managers": {"onlyfans": SimpleNamespace()},
                 "database_writes": _database_writer(), "record_route_selection": lambda *args: selections.append(args)})
    result = await scrape_task_handler(task, context)
    assert result.success
    assert attempts == [fallback, primary, fallback]
    assert selections[-1] == (handler._route_telemetry_id(fallback), "primary", False, True)
