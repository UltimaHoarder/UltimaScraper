"""Focused tests for the real-time WebSocket route."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from ultima_scraper_backend.api.routes import websocket as websocket_module


class _FakeWebSocket:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.query_params: dict[str, str] = {}
        self.accept = AsyncMock()


@pytest.mark.asyncio
async def test_disconnect_during_log_history_is_cleaned_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    backend = object()

    monkeypatch.setattr(
        websocket_module,
        "_resolve_ws_security",
        lambda: ([], None, False),
    )
    monkeypatch.setattr(
        websocket_module,
        "ensure_ws_admin_auth",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        websocket_module,
        "get_backend_instance",
        AsyncMock(return_value=backend),
    )
    monkeypatch.setattr(
        websocket_module,
        "_send_log_history",
        AsyncMock(side_effect=websocket_module.WebSocketDisconnect(code=1006)),
    )

    websocket_module.active_connections.discard(websocket)
    await websocket_module.websocket_events(websocket)  # type: ignore[arg-type]

    websocket.accept.assert_awaited_once_with()
    assert websocket not in websocket_module.active_connections


@pytest.mark.asyncio
async def test_idle_subscriber_skips_decoding_and_delivers_after_client_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No recipients require no parsing; a join at the next read still receives it."""
    socket = _FakeWebSocket()
    socket.send_text = AsyncMock()
    connections = set()
    monkeypatch.setattr(websocket_module, "active_connections", connections)
    normalize = websocket_module._normalize_pubsub_message
    normalized = []

    def observed_normalize(raw):
        normalized.append(raw)
        return normalize(raw)

    monkeypatch.setattr(websocket_module, "_normalize_pubsub_message", observed_normalize)
    delivered = [
        {"event": "auth_updated", "account_id": 42},
        {"event": "job_updated", "job_id": "job-public"},
        {"event": "task_completed", "job_id": "job-public", "success": True},
        {"type": "queue_depth", "queues": {"ready": 2}},
    ]
    channels = (
        websocket_module.AUTH_EVENTS_CHANNEL,
        websocket_module.JOB_EVENTS_CHANNEL,
        websocket_module.HOOKS_CHANNEL,
        websocket_module.WEBSOCKET_STREAM_CHANNEL,
    )
    idle_message = {"type": "message", "channel": b"ignored", "data": "invalid JSON"}

    async def listen():
        yield idle_message
        connections.add(socket)
        for channel, data in zip(channels, delivered):
            yield {"type": "message", "channel": channel.encode(), "data": json.dumps(data).encode()}
        for job_id in ("api", "API-secret", "test-fixture"):
            yield {"type": "message", "channel": channels[1], "data": json.dumps({"id": job_id})}
        # A disconnect at the next Redis read must stop further decoding.
        connections.clear()
        yield idle_message

    pubsub = SimpleNamespace(
        subscribe=AsyncMock(), listen=listen, unsubscribe=AsyncMock(), close=AsyncMock()
    )
    backend = SimpleNamespace(redis=SimpleNamespace(
        is_connected=True, client=SimpleNamespace(pubsub=lambda: pubsub)
    ))
    await websocket_module.subscribe_to_redis_job_events(backend)

    pubsub.subscribe.assert_awaited_once_with(*channels)
    assert len(normalized) == 7
    assert idle_message not in normalized
    assert [json.loads(call.args[0]) for call in socket.send_text.await_args_list] == delivered
    pubsub.unsubscribe.assert_awaited_once_with()
    pubsub.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_idle_subscriber_cancellation_closes_pubsub(monkeypatch):
    monkeypatch.setattr(websocket_module, "active_connections", set())
    listening = asyncio.Event()

    async def listen():
        listening.set()
        await asyncio.Event().wait()
        yield {}

    pubsub = SimpleNamespace(
        subscribe=AsyncMock(), listen=listen, unsubscribe=AsyncMock(), close=AsyncMock()
    )
    backend = SimpleNamespace(redis=SimpleNamespace(
        is_connected=True, client=SimpleNamespace(pubsub=lambda: pubsub)
    ))
    task = asyncio.create_task(websocket_module.subscribe_to_redis_job_events(backend))
    await asyncio.wait_for(listening.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    pubsub.unsubscribe.assert_awaited_once_with()
    pubsub.close.assert_awaited_once_with()
