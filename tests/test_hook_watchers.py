"""Per-call API hooks are built and published only while someone watches them."""

from types import SimpleNamespace

import pytest
from ultima_scraper_api.managers.redis import hooks


@pytest.fixture
def published(monkeypatch):
    events = []

    async def publish(metadata):
        events.append(metadata)

    monkeypatch.setattr(hooks, "_publish_hook_event", publish)
    monkeypatch.setattr(hooks, "_watched", {"checked_at": float("-inf"), "value": False})
    return events


def fake_redis(monkeypatch, watching):
    calls = []

    async def exists(key):
        calls.append(key)
        return 1 if watching else 0

    monkeypatch.setattr(hooks, "get_redis", lambda: SimpleNamespace(is_connected=True, client=SimpleNamespace(exists=exists)))
    return calls


@pytest.mark.asyncio
async def test_unwatched_hooks_are_skipped_but_calls_and_errors_proceed(monkeypatch, published):
    fake_redis(monkeypatch, watching=False)

    @hooks.with_hooks
    async def lookup(user_id):
        if user_id < 0:
            raise ValueError("bad id")
        return {"id": user_id}

    assert await lookup(5) == {"id": 5}
    with pytest.raises(ValueError):
        await lookup(-1)
    assert published == []


@pytest.mark.asyncio
async def test_watched_hooks_publish_and_the_key_is_checked_once_per_second(monkeypatch, published):
    calls = fake_redis(monkeypatch, watching=True)

    @hooks.with_hooks
    async def lookup(user_id):
        return {"id": user_id}

    for user_id in range(3):
        await lookup(user_id)
    assert [e["event_type"] for e in published] == ["started", "finished"] * 3
    assert calls == [hooks.API_HOOK_WATCHERS_KEY]
