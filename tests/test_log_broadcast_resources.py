from __future__ import annotations

import asyncio
import json
import logging
import threading
import tracemalloc
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ultima_scraper_api.managers.redis.log_handler import (
    AsyncRedisLogHandler,
    RedisLogHandler,
)
from test_database_write_queue import redis_manager  # noqa: F401


def record(message="test log"):
    return logging.LogRecord("fixture", logging.INFO, __file__, 1, message, (), None)


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_type", [RedisLogHandler, AsyncRedisLogHandler])
async def test_large_log_burst_has_one_consumer_and_bounded_pending_memory(
    handler_type,
):
    started = asyncio.Event()
    release = asyncio.Event()
    payloads = []

    async def publish(payload, **kwargs):
        payloads.append(payload)
        started.set()
        await release.wait()
        return True

    handler = handler_type(max_entries=3, max_bytes=4096)
    handler._redis = SimpleNamespace(is_connected=True, publish_log_payload=publish)
    handler.emit(record("first"))
    await asyncio.wait_for(started.wait(), 1)
    consumer = handler._task
    tracemalloc.start()
    try:
        for index in range(100_000):
            handler.emit(record(str(index)))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert handler._task is consumer
    assert handler.stats()["pending_entries"] == 3
    assert handler.stats()["pending_bytes"] <= 4096
    assert handler.stats()["dropped"] == 99_998
    assert peak < 64 * 1024
    release.set()
    await asyncio.wait_for(handler.aclose(), 1)
    assert [json.loads(payload)["message"] for payload in payloads] == [
        "first",
        "0",
        "1",
    ]
    assert handler.stats()["pending_entries"] == 0
    assert handler.stats()["pending_bytes"] == 0
    assert handler.stats()["published"] == 3


def test_preinitialization_and_thread_records_share_the_same_bounds():
    handler = AsyncRedisLogHandler(max_entries=4, max_bytes=4096)
    try:
        sender = threading.Thread(
            target=lambda: [handler.emit(record()) for _ in range(100)]
        )
        sender.start()
        sender.join()
        assert handler.stats()["accepted"] == 4
        assert handler.stats()["dropped"] == 96
        assert handler._task is None
    finally:
        handler.close()
    assert handler.stats()["pending_entries"] == 0
    assert handler.stats()["pending_bytes"] == 0


@pytest.mark.asyncio
async def test_thread_wakeup_is_coalesced_and_does_not_create_one_callback_per_record(
    monkeypatch,
):
    loop = asyncio.get_running_loop()
    handler = RedisLogHandler(max_entries=100, max_bytes=100_000)
    handler._loop = loop
    handler._redis = SimpleNamespace(
        is_connected=True, publish_log_payload=AsyncMock(return_value=True)
    )
    callbacks = []
    original = loop.call_soon_threadsafe

    def schedule(callback, *args, **kwargs):
        callbacks.append(callback)
        return original(callback, *args, **kwargs)

    monkeypatch.setattr(loop, "call_soon_threadsafe", schedule)
    sender = threading.Thread(
        target=lambda: [handler.emit(record(str(i))) for i in range(100)]
    )
    sender.start()
    sender.join()
    assert len(callbacks) == 1
    await asyncio.wait_for(handler.flush_queue(), 1)
    assert handler._redis.publish_log_payload.await_count == 100
    await handler.aclose()


@pytest.mark.asyncio
async def test_logs_emitted_by_event_loop_callbacks_are_admitted():
    handler = RedisLogHandler(max_entries=3)
    handler._redis = SimpleNamespace(
        is_connected=True, publish_log_payload=AsyncMock(return_value=True)
    )
    emitted = asyncio.Event()

    def callback():
        assert asyncio.current_task() is None
        handler.emit(record())
        emitted.set()

    asyncio.get_running_loop().call_soon(callback)
    await emitted.wait()
    await handler.aclose()
    assert handler.stats()["published"] == 1


def test_byte_budget_counts_ascii_payload_and_oversize_does_not_poison_following_logs():
    handler = RedisLogHandler(max_entries=100, max_bytes=1200)
    try:
        handler.emit(record("oversized" * 1000))
        for _ in range(100):
            handler.emit(record("😀" * 20))
        stats = handler.stats()
        assert 0 < stats["pending_entries"] < 100
        assert 0 < stats["pending_bytes"] <= 1200
        assert stats["pending_bytes"] == sum(
            len(payload.encode("ascii")) for payload in handler._queue
        )
        assert stats["dropped"] == 101 - stats["accepted"]
    finally:
        handler.close()


@pytest.mark.asyncio
async def test_disconnect_and_transport_failure_release_admission_for_future_records():
    handler = RedisLogHandler(max_entries=1, max_bytes=1024)
    redis = SimpleNamespace(
        is_connected=False, publish_log_payload=AsyncMock(return_value=True)
    )
    handler._redis = redis
    handler.emit(record("offline"))
    await handler.flush_queue()
    assert handler.stats()["failed"] == 1
    redis.is_connected = True
    redis.publish_log_payload.side_effect = RuntimeError("temporary")
    handler.emit(record("failure"))
    await handler.flush_queue()
    assert handler.stats()["failed"] == 2
    redis.publish_log_payload.side_effect = None
    handler.emit(record("recovered"))
    await handler.aclose()
    assert handler.stats()["published"] == 1
    assert handler.stats()["pending_bytes"] == 0


@pytest.mark.asyncio
async def test_close_cancels_inflight_and_clears_queue_without_negative_accounting():
    started = asyncio.Event()

    async def publish(payload, **kwargs):
        started.set()
        await asyncio.Event().wait()

    handler = RedisLogHandler(max_entries=3)
    handler._redis = SimpleNamespace(is_connected=True, publish_log_payload=publish)
    for _ in range(3):
        handler.emit(record())
    await started.wait()
    consumer = handler._task
    handler.close()
    handler.close()
    await asyncio.gather(consumer, return_exceptions=True)
    assert handler.stats()["pending_entries"] == 0
    assert handler.stats()["pending_bytes"] == 0
    assert handler.stats()["dropped"] == 2
    assert handler.stats()["failed"] == 1


def test_log_budget_configuration_keeps_explicit_values_authoritative(monkeypatch):
    monkeypatch.setenv("ULTIMA_LOG_QUEUE_MAX_ENTRIES", "7")
    monkeypatch.setenv("ULTIMA_LOG_QUEUE_MAX_BYTES", "8192")
    handler = RedisLogHandler(max_entries=11, max_bytes=16384)
    assert handler.max_entries == 11 and handler.max_bytes == 16384
    handler.close()
    handler = RedisLogHandler()
    assert handler.max_entries == 7 and handler.max_bytes == 8192
    handler.close()
    for invalid in ("0", "-1", "false", "1.2"):
        monkeypatch.setenv("ULTIMA_LOG_QUEUE_MAX_ENTRIES", invalid)
        with pytest.raises(ValueError, match="ULTIMA_LOG_QUEUE_MAX_ENTRIES"):
            RedisLogHandler()


@pytest.mark.asyncio
async def test_log_transport_serializes_once_and_appends_trims_and_publishes_atomically(
    monkeypatch,
):
    from ultima_scraper_api.managers.redis import connection
    from unittest.mock import MagicMock

    manager = connection.RedisManager.__new__(connection.RedisManager)
    manager._connected = True
    manager.LOGS_HISTORY_MAX = 2
    manager.client = MagicMock()
    pipeline = MagicMock()
    pipeline.__aenter__ = AsyncMock(return_value=pipeline)
    pipeline.__aexit__ = AsyncMock(return_value=False)
    pipeline.execute = AsyncMock()
    manager.client.pipeline.return_value = pipeline
    dumps = MagicMock(wraps=json.dumps)
    monkeypatch.setattr(connection.json, "dumps", dumps)
    assert await manager.publish_log({"message": "fixture"})
    dumps.assert_called_once()
    manager.client.pipeline.assert_called_once_with(transaction=True)
    encoded = (
        dumps.return_value
        if not pipeline.publish.call_args
        else pipeline.publish.call_args.args[1]
    )
    assert json.loads(encoded) == {"message": "fixture"}
    pipeline.lpush.assert_called_once_with(manager.LOGS_HISTORY_KEY, encoded)
    pipeline.ltrim.assert_called_once_with(manager.LOGS_HISTORY_KEY, 0, 1)
    pipeline.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_transport_keeps_bounded_history_and_honors_the_requested_channel(
    redis_manager,  # noqa: F811
):
    from ultima_scraper_api.managers.redis.connection import RedisManager

    manager = RedisManager.__new__(RedisManager)
    manager._connected = True
    manager.client = redis_manager.client
    manager.LOGS_HISTORY_MAX = 2
    subscription = manager.client.pubsub()
    channel = "fixture:log-broadcast"
    try:
        await subscription.subscribe(channel)
        await subscription.get_message(timeout=1)
        for index in range(3):
            assert await manager.publish_log_payload(
                json.dumps({"index": index}), channel=channel
            )
        message = await subscription.get_message(
            ignore_subscribe_messages=True, timeout=1
        )
        assert json.loads(message["data"]) == {"index": 0}
        history = await manager.client.lrange(manager.LOGS_HISTORY_KEY, 0, -1)
        assert [json.loads(item) for item in history] == [{"index": 2}, {"index": 1}]
    finally:
        await subscription.aclose()


@pytest.mark.asyncio
async def test_one_failed_publication_discards_the_outage_queue():
    handler = RedisLogHandler(max_entries=100)
    publisher = AsyncMock(return_value=False)
    handler._redis = SimpleNamespace(is_connected=True, publish_log_payload=publisher)
    for _ in range(100):
        handler.emit(record())
    await handler.aclose()
    publisher.assert_awaited_once()
    assert handler.stats()["failed"] == 1
    assert handler.stats()["dropped"] == 99
    assert handler.stats()["pending_entries"] == 0


def test_worker_memory_telemetry_exposes_pending_and_dropped_broadcasts():
    from ultima_scraper_backend.workers.worker_pool import Worker

    handler = RedisLogHandler(max_entries=1, max_bytes=2048)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    try:
        handler.emit(record("accepted"))
        handler.emit(record("dropped"))
        worker = Worker.__new__(Worker)
        worker.apis = {}
        worker.ultima_scraper_api = None
        metrics = worker._collect_memory_telemetry()
        assert metrics["log_queue_entries"] == 1
        assert metrics["log_queue_bytes"] > 0
        assert metrics["log_dropped"] == 1
    finally:
        root_logger.removeHandler(handler)
        handler.close()
