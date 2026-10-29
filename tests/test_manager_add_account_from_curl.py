from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import ultima_scraper_backend.database.helpers.user_sync as user_sync_module
import ultima_scraper_backend.manager as manager_module


class _FakeAuthDetails:
    def export(self) -> dict[str, str]:
        return {
            "id": "123",
            "username": "tester",
            "cookie": "sess=abc",
            "x_bc": "xbc",
            "user_agent": "ua",
        }


@pytest.mark.asyncio
async def test_add_account_from_curl_syncs_authed_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authed = SimpleNamespace(id=123, username="tester")
    stored_auth = SimpleNamespace(id=123, username="tester")
    sync_mock = AsyncMock(return_value=True)

    monkeypatch.setitem(
        manager_module._AUTH_EXTRACTORS,
        "onlyfans",
        lambda _curl: _FakeAuthDetails(),
    )
    monkeypatch.setattr(user_sync_module, "sync_authed_user_from_api", sync_mock)

    backend = object.__new__(manager_module.BackendManager)
    backend._auth_event_publisher = None
    # Credentials are verified by a worker, then the stored session is synced.
    backend.execute_worker_api_method = AsyncMock(return_value=authed)
    backend.get_authed_session = AsyncMock(return_value=stored_auth)
    backend._store_account = AsyncMock(return_value=SimpleNamespace(username="tester"))
    backend.get_site_db_manager = Mock(return_value=SimpleNamespace())

    result = await manager_module.BackendManager.add_account_from_curl(
        backend,
        "onlyfans",
        "curl https://example.test",
    )

    assert result.success is True
    backend.execute_worker_api_method.assert_awaited_once()
    assert backend.execute_worker_api_method.await_args.kwargs["method"] == "get_authed_user"
    backend._store_account.assert_awaited_once()
    backend.get_authed_session.assert_awaited_once_with("onlyfans", 123)
    sync_mock.assert_awaited_once_with(
        backend.get_site_db_manager.return_value,
        stored_auth,
        site="onlyfans",
    )
