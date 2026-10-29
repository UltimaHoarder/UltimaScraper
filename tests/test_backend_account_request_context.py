from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ultima_scraper_backend.manager import BackendManager


def test_account_request_context_does_not_open_api_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = object.__new__(BackendManager)
    account = SimpleNamespace(id=7, user_id=901, site="onlyfans")
    find_account = MagicMock(return_value=account)
    build_payload = MagicMock(
        return_value={
            "cookie": "sess=stored",
            "authorization": "Bearer stored",
            "user_agent": "Stored Agent",
            "proxy_url": "http://proxy.example.test:8080",
        }
    )
    login = MagicMock()
    monkeypatch.setattr(manager, "_find_account", find_account)
    monkeypatch.setattr(manager, "_build_auth_payload", build_payload)
    monkeypatch.setattr(manager, "_login_with_account", login)

    context = manager.get_account_request_context("OnlyFans", 901)

    assert context is not None
    assert context.cookie == "sess=stored"
    assert context.authorization == "Bearer stored"
    assert context.user_agent == "Stored Agent"
    assert context.proxy_url == "http://proxy.example.test:8080"
    assert "sess=stored" not in repr(context)
    assert "Bearer stored" not in repr(context)
    find_account.assert_called_once_with("onlyfans", 901)
    build_payload.assert_called_once_with(account, "onlyfans")
    login.assert_not_called()
