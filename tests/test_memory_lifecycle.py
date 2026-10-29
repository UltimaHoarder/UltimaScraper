"""Regression coverage for bounded caches and terminal-job cleanup."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
from pydantic import ValidationError

# These exercise the Redis runtime; the SQL execution ledger holds no runs.
pytestmark = pytest.mark.usefixtures("no_ledger_runs")


class _FakeRedisManager:
    def __init__(self) -> None:
        self.client = fakeredis.aioredis.FakeRedis(decode_responses=False)

    async def get(self, key: str) -> Any:
        return await self.client.get(key)

    async def set(self, key: str, value: Any, **kwargs: Any) -> Any:
        return await self.client.set(key, value, **kwargs)

    async def delete(self, key: str) -> Any:
        return await self.client.delete(key)


def test_media_proxy_cache_is_byte_bounded_ttl_lru(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.api.routes import media

    now = 100.0
    monkeypatch.setattr(media.time, "monotonic", lambda: now)
    cache = media._MediaProxyCache(
        max_bytes=4,
        max_entry_bytes=2,
        ttl_seconds=10,
    )

    assert cache.put("a", "image/jpeg", b"aa") is True
    assert cache.put("b", "image/png", b"bb") is True
    assert cache.get("a") == ("image/jpeg", b"aa")
    assert cache.put("c", "image/webp", b"cc") is True
    assert cache.get("b") is None
    assert cache.stats()["bytes"] == 4

    now = 111.0
    assert cache.get("a") is None
    assert cache.get("c") is None
    assert cache.stats()["bytes"] == 0


def test_media_proxy_cache_also_bounds_entry_count() -> None:
    from ultima_scraper_backend.api.routes import media

    cache = media._MediaProxyCache(
        max_bytes=100,
        max_entry_bytes=10,
        ttl_seconds=60,
        max_entries=2,
    )

    assert cache.put("empty", "image/png", b"") is False
    assert cache.put("a", "image/png", b"a") is True
    assert cache.put("b", "image/png", b"b") is True
    assert cache.get("a") == ("image/png", b"a")
    assert cache.put("c", "image/png", b"c") is True
    assert cache.get("b") is None
    assert cache.stats()["entries"] == 2


def test_remote_thumbnail_failure_cache_is_ttl_and_count_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.api.routes import media

    now = 100.0
    media._remote_thumbnail_failures.clear()
    monkeypatch.setattr(media.time, "monotonic", lambda: now)
    monkeypatch.setattr(media, "_REMOTE_THUMBNAIL_FAILURE_TTL_SECONDS", 10)
    monkeypatch.setattr(media, "_REMOTE_THUMBNAIL_FAILURE_CACHE_MAX_ENTRIES", 2)

    media._remember_remote_thumbnail_failure("a")
    media._remember_remote_thumbnail_failure("b")
    media._remember_remote_thumbnail_failure("c")
    assert list(media._remote_thumbnail_failures) == ["b", "c"]

    now = 111.0
    media._prune_remote_thumbnail_failures(now)
    assert not media._remote_thumbnail_failures


def test_ip_geolocation_cache_has_an_lru_ceiling() -> None:
    from ultima_scraper_backend.helpers.ip_geolocation import IPGeolocationService

    service = IPGeolocationService(max_cache_entries=2)
    service._store_cache_entry("203.0.113.1", {"ip": "203.0.113.1"})
    service._store_cache_entry("203.0.113.2", {"ip": "203.0.113.2"})
    service._store_cache_entry("203.0.113.3", {"ip": "203.0.113.3"})

    assert list(service._cache) == ["203.0.113.2", "203.0.113.3"]
    assert service.get_cache_size() == 2


def test_worker_memory_telemetry_uses_supported_object_contracts() -> None:
    from ultima_scraper_backend.workers.worker_pool import Worker

    scraped = SimpleNamespace(Posts={1: object(), 2: object()}, Messages={3: object()})
    user = SimpleNamespace(scrape_manager=SimpleNamespace(scraped=scraped))
    auth = SimpleNamespace(guest=True, users={10: user})
    worker = Worker.__new__(Worker)
    worker.apis = {"OnlyFans": SimpleNamespace(auths={7: auth})}
    worker.ultima_scraper_api = SimpleNamespace(
        websocket_manager=SimpleNamespace(
            get_statistics=lambda: {
                "total_connections": 1,
                "total_message_history": 2,
                "total_event_history": 3,
            }
        )
    )

    telemetry = worker._collect_memory_telemetry()

    assert telemetry["rss_bytes"] > 0
    assert telemetry["auth_count"] == 1
    assert telemetry["guest_auth_count"] == 1
    assert telemetry["cached_user_count"] == 1
    assert telemetry["cached_content_count"] == 3
    assert telemetry["websocket_connections"] == 1
    assert telemetry["websocket_message_history"] == 2
    assert telemetry["websocket_event_history"] == 3


def test_websocket_histories_are_bounded() -> None:
    from ultima_scraper_api.managers.websocket_manager.connection import (
        WebSocketConnection,
    )

    connection = WebSocketConnection(
        SimpleNamespace(is_connected=False),
        max_message_history=2,
        max_event_history=1,
    )
    connection._message_history.extend([{"id": 1}, {"id": 2}, {"id": 3}])
    connection._event_history.extend([{"type": "one"}, {"type": "two"}])

    assert connection.message_history == [{"id": 2}, {"id": 3}]
    assert connection.event_history == [{"type": "two"}]
    assert connection.get_statistics()["message_history_limit"] == 2


@pytest.mark.asyncio
async def test_websocket_stop_releases_retained_objects() -> None:
    from ultima_scraper_api.managers.websocket_manager.connection import (
        WebSocketConnection,
    )

    disconnected: list[bool] = []

    async def disconnect() -> None:
        disconnected.append(True)

    connection = WebSocketConnection(
        SimpleNamespace(is_connected=False, disconnect=disconnect)
    )
    connection._message_history.append({"id": 1})
    connection._event_history.append({"type": "connected"})
    connection._callbacks["message"].append(lambda _message: None)
    connection.subscribe()

    await connection.stop()

    assert disconnected == [True]
    assert connection.message_history == []
    assert connection.event_history == []
    assert connection.get_statistics()["subscriber_count"] == 0
    assert connection._callbacks["message"] == []


@pytest.mark.asyncio
async def test_shared_auth_removal_owns_session_cleanup() -> None:
    from ultima_scraper_api.apis.api_streamliner import StreamlinedAPI
    from ultima_scraper_api.apis.fansly.fansly import FanslyAPI
    from ultima_scraper_api.apis.loyalfans.loyalfans import LoyalFansAPI

    session = SimpleNamespace(close=AsyncMock())
    auth = SimpleNamespace(
        id=7,
        get_requester=lambda: SimpleNamespace(active_session=session),
    )
    api = StreamlinedAPI.__new__(StreamlinedAPI)
    api.api = SimpleNamespace(auths={auth.id: auth})

    await api.remove_auth(auth)

    session.close.assert_awaited_once_with()
    assert api.api.auths == {}
    assert FanslyAPI.remove_auth is StreamlinedAPI.remove_auth
    assert LoyalFansAPI.remove_auth is StreamlinedAPI.remove_auth


@pytest.mark.asyncio
async def test_onlyfans_auth_removal_closes_websocket_and_shared_session() -> None:
    from ultima_scraper_api.apis.onlyfans.onlyfans import OnlyFansAPI

    session = SimpleNamespace(close=AsyncMock())
    auth = SimpleNamespace(
        id=7,
        get_requester=lambda: SimpleNamespace(active_session=session),
    )
    api = OnlyFansAPI.__new__(OnlyFansAPI)
    api.api = api
    api.auths = {auth.id: auth}
    api.websocket_manager = SimpleNamespace(close_connection=AsyncMock())

    await api.remove_auth(auth)

    api.websocket_manager.close_connection.assert_awaited_once_with("onlyfans_7")
    session.close.assert_awaited_once_with()
    assert api.auths == {}


def test_auth_release_user_drops_scrape_working_set() -> None:
    from ultima_scraper_api.apis.auth_streamliner import Cache, StreamlinedAuth

    released: list[bool] = []
    transient_user = SimpleNamespace(
        id=22,
        release_cached_objects=lambda: released.append(True),
    )
    auth = StreamlinedAuth.__new__(StreamlinedAuth)
    auth.user = SimpleNamespace(id=11)
    auth.users = {11: auth.user, 22: transient_user}
    auth.cache = Cache()
    auth.cache.users(22).activate()

    assert auth.release_user(22) is True
    assert auth.users == {11: auth.user}
    assert released == [True]
    assert 22 not in auth.cache.data["users"]
    assert auth.release_user(11) is False


def test_paid_feed_release_drops_items_authors_and_cache() -> None:
    from ultima_scraper_api.apis.auth_streamliner import Cache, StreamlinedAuth
    from ultima_scraper_backend.job_system.handlers.scrape.handler import (
        _release_paid_content_working_set,
    )

    author = SimpleNamespace(id=22, release_cached_objects=lambda: None)
    item = SimpleNamespace(get_author=lambda: author)
    auth = StreamlinedAuth.__new__(StreamlinedAuth)
    auth.user = SimpleNamespace(id=11)
    auth.users = {11: auth.user, 22: author}
    auth.cache = Cache()
    auth.cache.paid_content.activate()
    auth.paid_content = [item]

    _release_paid_content_working_set(auth)

    assert auth.paid_content == []
    assert auth.users == {11: auth.user}
    assert auth.cache.paid_content.is_released() is True


def test_mps_requests_allow_large_positive_task_counts() -> None:
    from ultima_scraper_backend.api.routes.mps import (
        MPSAnalyzeRequest,
        MPSCreateJobRequest,
    )

    analyze_request = MPSAnalyzeRequest(batch_size=1_000_000)
    create_request = MPSCreateJobRequest(max_profiles=1_000_000)

    assert analyze_request.batch_size == 1_000_000
    assert create_request.max_profiles == 1_000_000

    with pytest.raises(ValidationError):
        MPSAnalyzeRequest(batch_size=0)
    with pytest.raises(ValidationError):
        MPSCreateJobRequest(max_profiles=0)


@pytest.mark.asyncio
async def test_memory_status_is_available_without_redis() -> None:
    from ultima_scraper_backend.api.routes.system import get_memory_status

    response = await get_memory_status(
        backend=SimpleNamespace(instance_id="memory-test", redis=None)
    )

    assert response.backend_id == "memory-test"
    assert response.process.rss_bytes > 0
    assert response.redis is None
    assert response.media_proxy_cache["bytes"] >= 0


@pytest.mark.asyncio
async def test_archive_marker_makes_partial_purge_restart_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.job_system.models import Job, Task, TaskType
    from ultima_scraper_backend.job_system.storage import JobStorage

    redis = _FakeRedisManager()
    storage = JobStorage(redis)
    job = Job(
        job_id="job-resumable-archive",
        name="resumable",
        created_by="tests",
        tasks=[
            Task(task_id="task-a", task_type=TaskType.SCRAPE, user_id=1),
            Task(task_id="task-b", task_type=TaskType.SCRAPE, user_id=2),
        ],
    )
    await storage.persist_job(job, persist_tasks=True)

    inserted_rows: list[dict[str, Any]] = []
    monkeypatch.setattr(
        type(storage),
        "_delete_central_tasks_sync",
        staticmethod(lambda _job_id: inserted_rows.clear() or 0),
    )
    monkeypatch.setattr(
        type(storage),
        "_insert_central_tasks_sync",
        staticmethod(
            lambda rows: inserted_rows.extend(dict(row) for row in rows) or len(rows)
        ),
    )
    monkeypatch.setattr(
        type(storage),
        "_count_central_tasks_sync",
        staticmethod(lambda _job_id: len(inserted_rows)),
    )

    assert await storage._archive_job_tasks_to_db(job.job_id) == 2
    marker_key = storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    assert json.loads((await redis.get(marker_key)).decode())["task_count"] == 2

    # Simulate a crash after the first Redis task was purged. A retry must use
    # the completed archive marker and must not replace DB rows from the now-
    # incomplete Redis source.
    await redis.client.delete(
        storage.TASK_KEY.format(job_id=job.job_id, task_id="task-a")
    )
    await redis.client.zrem(storage.TASK_INDEX_KEY.format(job_id=job.job_id), "task-a")
    assert await storage._archive_job_tasks_to_db(job.job_id) == 2
    assert {row["task_id"] for row in inserted_rows} == {"task-a", "task-b"}

    assert await storage.purge_job_task_blobs(job.job_id) == 1
    assert await redis.client.exists(marker_key) == 0

    # A delayed duplicate archive command can arrive after the source working
    # set was purged. It must preserve the already-canonical database rows.
    assert await storage._archive_job_tasks_to_db(job.job_id) == 2
    assert {row["task_id"] for row in inserted_rows} == {"task-a", "task-b"}


@pytest.mark.asyncio
async def test_archive_marker_fails_closed_when_database_rows_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.job_system.storage import JobStorage

    redis = _FakeRedisManager()
    storage = JobStorage(redis)
    job_id = "job-incomplete-archive"
    marker_key = storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job_id)
    await redis.set(marker_key, json.dumps({"task_count": 10}))
    monkeypatch.setattr(
        type(storage),
        "_count_central_tasks_sync",
        staticmethod(lambda _job_id: 9),
    )

    with pytest.raises(RuntimeError, match="archive.*incomplete"):
        await storage._archive_job_tasks_to_db(job_id)


@pytest.mark.asyncio
async def test_terminal_reconciler_finds_stranded_job() -> None:
    from ultima_scraper_backend.job_system.models import JobState
    from ultima_scraper_backend.services.terminal_job_reconciler import (
        TerminalJobReconciler,
    )

    redis = _FakeRedisManager()
    reconciler = TerminalJobReconciler(redis, min_age_seconds=0, max_jobs_per_cycle=2)
    storage = reconciler.manager.storage
    job_id = "job-stranded"
    await redis.client.zadd(storage.JOB_INDEX_KEY, {job_id: time.time() - 60})
    await redis.client.hset(
        storage.JOB_STATE_KEY.format(job_id=job_id),
        mapping={"status": JobState.CANCELLED.value},
    )
    await redis.client.zadd(storage.TASK_INDEX_KEY.format(job_id=job_id), {"task-a": 1})
    finalize = AsyncMock()
    reconciler.manager._finalize_terminal_job_cleanup = finalize

    assert await reconciler.run_once() == 1
    finalize.assert_awaited_once_with(job_id, terminal_state=JobState.CANCELLED)
