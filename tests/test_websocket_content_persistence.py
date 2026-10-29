"""Realtime chat messages and published posts are queued for DB persistence,
and the chat list routes run inside the event loop."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from ultima_scraper_backend import websocket_actions
from ultima_scraper_backend.database.write_executor import (
    serialize_content_write_item,
)
from ultima_scraper_backend.job_system.handlers.scrape import content as scrape_content

AUTH_ID = 1000
FAN_ID = 2000


class _FakeUser(SimpleNamespace):
    def get_authed(self) -> "_FakeAuthed":
        return self.authed


class _FakeAuthed:
    def __init__(self) -> None:
        self.id = AUTH_ID
        self.users: dict[int, _FakeUser] = {}
        self.fetched_posts: list[int] = []

    def resolve_user(self, data: dict[str, Any], *, cache: bool = True) -> _FakeUser:
        user = self.users.get(int(data["id"]))
        if user is None:
            user = _FakeUser(id=int(data["id"]), authed=self)
            self.users[user.id] = user
        return user

    def find_user(self, identifier: int) -> _FakeUser | None:
        return self.users.get(identifier)

    async def get_user(self, identifier: int) -> _FakeUser:
        return self.resolve_user({"id": identifier})


def _handler(monkeypatch: pytest.MonkeyPatch, authed: _FakeAuthed) -> tuple[Any, list[dict[str, Any]]]:
    handler = websocket_actions.WebSocketActionHandler(SimpleNamespace(database_writes=object()))

    async def fake_get_authed(source_id: Any, site_name: str) -> _FakeAuthed:
        return authed

    monkeypatch.setattr(handler, "_get_authed_for_account", fake_get_authed)
    calls: list[dict[str, Any]] = []

    async def fake_save(items, user_id, content_type, **kwargs):
        calls.append({"items": items, "user_id": user_id, "content_type": content_type, **kwargs})
        return len(items), []

    monkeypatch.setattr(scrape_content, "save_content_to_db", fake_save)
    return handler, calls


def _chat_payload(from_id: int, **extra: Any) -> dict[str, Any]:
    return {
        "id": 555,
        "text": "hello",
        "price": 0,
        "fromUser": {"id": from_id},
        "media": [],
        "createdAt": "2026-10-28T12:00:00+00:00",
        **extra,
    }


async def test_incoming_chat_message_is_queued_for_the_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, calls = _handler(monkeypatch, _FakeAuthed())

    await handler._handle_chat_message(_chat_payload(FAN_ID), AUTH_ID, "onlyfans")

    assert len(calls) == 1
    call = calls[0]
    assert call["user_id"] == FAN_ID
    assert call["content_type"] == "messages"
    assert call["auth_user_id"] == AUTH_ID
    assert call["site"] == "onlyfans"
    payload = serialize_content_write_item(
        call["items"][0],
        content_type="messages",
        user_id=FAN_ID,
        auth_user_id=AUTH_ID,
        record_bought_content=False,
    )
    assert payload["kind"] == "message"
    assert payload["id"] == 555
    assert payload["author_id"] == FAN_ID
    assert payload["receiver_id"] == AUTH_ID


async def test_outgoing_chat_message_uses_recipient_or_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, calls = _handler(monkeypatch, _FakeAuthed())

    await handler._handle_chat_message(_chat_payload(AUTH_ID), AUTH_ID, "onlyfans")
    assert calls == []

    await handler._handle_chat_message(
        _chat_payload(AUTH_ID, toUser={"id": FAN_ID}), AUTH_ID, "onlyfans"
    )
    assert [call["user_id"] for call in calls] == [FAN_ID]


async def test_published_post_is_fetched_and_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    authed = _FakeAuthed()
    handler, calls = _handler(monkeypatch, authed)
    author = authed.resolve_user({"id": FAN_ID})

    async def get_post(post_id: int) -> SimpleNamespace:
        authed.fetched_posts.append(post_id)
        return SimpleNamespace(id=post_id, author=author)

    author.get_post = get_post

    await handler._handle_post_published(
        {"id": "777", "user_id": str(FAN_ID)}, AUTH_ID, "user", "onlyfans"
    )

    assert authed.fetched_posts == [777]
    assert len(calls) == 1
    assert calls[0]["user_id"] == FAN_ID
    assert calls[0]["content_type"] == "posts"
    assert calls[0]["items"][0].id == 777


async def test_process_message_routes_chat_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, calls = _handler(monkeypatch, _FakeAuthed())

    await handler.process_message(
        {"api2_chat_message": _chat_payload(FAN_ID), "source_id": f"onlyfans:ws:{AUTH_ID}"}
    )
    for _ in range(5):
        await asyncio.sleep(0)

    assert [call["user_id"] for call in calls] == [FAN_ID]


async def test_list_chats_spawns_sync_inside_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from ultima_scraper_backend.api.routes import chats

    spawned: list[Any] = []
    monkeypatch.setattr(chats, "_get_db_engine", lambda backend, site: object())
    monkeypatch.setattr(chats, "_get_auth_ids_for_site", lambda engine, site, auth_id: [AUTH_ID])
    monkeypatch.setattr(chats, "_get_chats_from_db", lambda engine, ids, limit: [])
    monkeypatch.setattr(chats, "_sync_on_cooldown", lambda key, last: False)
    chats._active_chat_syncs.clear()

    def fake_spawn(coro, **kwargs):
        coro.close()
        spawned.append(asyncio.get_running_loop())

    monkeypatch.setattr(chats, "spawn_background_task", fake_spawn)

    response = await chats.list_chats("onlyfans", auth_id=AUTH_ID, limit=10, offset=0, backend_manager=object())

    assert response.success is True
    assert response.syncing is True
    assert len(spawned) == 1
