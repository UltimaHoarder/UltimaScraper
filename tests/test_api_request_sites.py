from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from ultima_scraper_backend import api_command_sites
from ultima_scraper_backend.api.routes import api_requests as api_requests_module
from ultima_scraper_backend.job_system.handlers import (
    api_command as api_command_module,
)
from ultima_scraper_backend.manager import (
    API_COMMAND_MAP,
    BackendManager,
    BackendResult,
)


class FullAuth:
    """A site with every option, like OnlyFans."""

    async def get_chats(self, limit: int = 100, offset: int = 0): ...

    async def search_chats(self, query: str, limit: int = 100, offset: int = 0): ...

    async def blocked_users(self, limit: int = 100, offset: int = 0): ...


class SearchByChatsAuth:
    """A site that searches through get_chats, like Fansly."""

    async def get_chats(self, limit: int | None = None, offset: int = 0, search: str = ""): ...


class PlainChatsAuth:
    """A site whose get_chats takes only a limit, like Privacy or DarkFans."""

    async def get_chats(self, limit: int | None = None): ...


@pytest.fixture
def fake_sites(monkeypatch: pytest.MonkeyPatch):
    classes = {"full": FullAuth, "search": SearchByChatsAuth, "plain": PlainChatsAuth}
    monkeypatch.setattr(api_command_sites, "auth_model_classes", lambda: classes)
    api_command_sites.sites_supporting.cache_clear()
    yield classes
    api_command_sites.sites_supporting.cache_clear()


def test_each_command_lists_the_sites_that_implement_it(fake_sites) -> None:
    assert API_COMMAND_MAP["get_chats"].sites == ("full", "search", "plain")
    # Searching works through search_chats or a get_chats that takes a search.
    assert API_COMMAND_MAP["search_chats"].sites == ("full", "search")
    assert API_COMMAND_MAP["blocked_users"].sites == ("full",)
    assert API_COMMAND_MAP["blocked_users"].to_dict()["sites"] == ["full"]


@pytest.mark.asyncio
async def test_a_site_without_the_method_is_refused(fake_sites, monkeypatch) -> None:
    manager = BackendManager.__new__(BackendManager)
    manager._api_command_map = API_COMMAND_MAP
    submit = AsyncMock(return_value=BackendResult(True, "ok", {}))
    monkeypatch.setattr(manager, "_submit_worker_api_command", submit)

    refused = await manager.run_api_command("plain", "blocked_users", {}, account_id=1)
    allowed = await manager.run_api_command("search", "search_chats", {"query": "a"}, account_id=1)

    assert refused.success is False
    assert "Supported sites: full." in refused.message
    assert allowed.success is True
    submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_catalogue_lists_the_enabled_sites() -> None:
    response = await api_requests_module.list_methods()

    assert response["sites"] == api_command_sites.enabled_sites()
    assert {"key": "onlyfans", "label": "OnlyFans"} in response["sites"]
    for spec in response["methods"].values():
        assert set(spec["sites"]) <= {site["key"] for site in response["sites"]}


def _context(site: str) -> Any:
    return SimpleNamespace(worker_id="worker-1", site=site)


@pytest.mark.asyncio
async def test_chats_skip_their_offset_on_sites_without_one() -> None:
    authed = SimpleNamespace()

    async def get_chats(limit: int | None = None) -> list[int]:
        authed.asked_for = limit
        return list(range(limit or 0))

    authed.get_chats = get_chats

    result = await api_command_module._get_chats(
        authed, _context("privacy"), {"limit": 3, "offset": 2}
    )

    assert authed.asked_for == 5
    assert result == {"chats": [2, 3, 4], "count": 3}


@pytest.mark.asyncio
async def test_search_uses_get_chats_where_there_is_no_search_chats() -> None:
    authed = SimpleNamespace(get_chats=AsyncMock(return_value=["chat"]))

    result = await api_command_module._search_chats(
        authed, _context("fansly"), {"query": "anna", "limit": 10, "offset": 0}
    )

    authed.get_chats.assert_awaited_once_with(limit=10, offset=0, search="anna")
    assert result == {"chats": ["chat"], "query": "anna", "count": 1}


@pytest.mark.asyncio
async def test_messages_leave_out_paging_a_site_does_not_take() -> None:
    calls: list[dict[str, Any]] = []

    async def get_messages(limit: int | None = None) -> list[Any]:
        calls.append({"limit": limit})
        return [SimpleNamespace(id=1, created_at="2026-11-20T00:00:00", text="hi", media=[])]

    user = SimpleNamespace(id=9, username="someone", get_messages=get_messages)
    authed = SimpleNamespace(get_user=AsyncMock(return_value=user))

    result = await api_command_module._get_messages(
        authed,
        _context("darkfans"),
        {"user_id": "someone", "limit": 5, "offset_id": 40, "cutoff_id": None},
    )

    assert calls == [{"limit": 5}]
    assert result["messages"][0]["created_at"] == "2026-11-20T00:00:00"
    assert result["messages"][0]["text"] == "hi"


@pytest.mark.asyncio
async def test_messages_page_where_the_site_can() -> None:
    user = SimpleNamespace(get_messages=AsyncMock(return_value=[]))

    async def get_messages(limit: int = 20, offset_id: int | None = None, cutoff_id: int | None = None):
        return await user.get_messages(limit=limit, offset_id=offset_id, cutoff_id=cutoff_id)

    authed = SimpleNamespace(
        get_user=AsyncMock(return_value=SimpleNamespace(id=9, username="u", get_messages=get_messages))
    )

    await api_command_module._get_messages(
        authed, _context("onlyfans"), {"user_id": "9", "limit": 5, "offset_id": "40"}
    )

    user.get_messages.assert_awaited_once_with(limit=5, offset_id=40, cutoff_id=None)


@pytest.mark.asyncio
async def test_paid_content_looks_up_a_username_and_keeps_site_json() -> None:
    authed = SimpleNamespace(
        get_user=AsyncMock(return_value=SimpleNamespace(id=321)),
        get_paid_content=AsyncMock(return_value=[{"id": 5, "price": 9.99}]),
    )

    result = await api_command_module._get_paid_content(
        authed, _context("fansly"), {"performer_id": "anna", "limit": 4, "offset": 8}
    )

    authed.get_user.assert_awaited_once_with("anna")
    authed.get_paid_content.assert_awaited_once_with(performer_id=321, limit=4, offset=8)
    assert result == {"paid_content": [{"id": 5, "price": 9.99}], "count": 1}
