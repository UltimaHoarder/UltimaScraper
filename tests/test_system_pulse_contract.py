import asyncio
import threading
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import fakeredis.aioredis
import pytest
from ultima_scraper_backend.api.routes import system as system_module
from ultima_scraper_backend.api.routes import websocket as websocket_module
from ultima_scraper_backend.config import ProcessRole
from ultima_scraper_backend.models import backend as backend_module
from ultima_scraper_backend.redis.worker_registry import WorkerRegistry
from ultima_scraper_backend.ultima_control.system_stats_reporter import (
    DiskStats,
    SystemStats,
    SystemStatsReporter,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["backend", "websocket"])
async def test_system_config_read_keeps_event_loop_responsive(monkeypatch, route):
    loop_thread = threading.get_ident()
    query_started = threading.Event()
    release = threading.Event()

    def read_config():
        query_started.set()
        assert threading.get_ident() != loop_thread
        assert release.wait(3)
        return SimpleNamespace(
            settings=SimpleNamespace(
                worker_pool=SimpleNamespace(size=1, sites=[]),
                download_setup=SimpleNamespace(drives=[]),
                metadata_setup=SimpleNamespace(drives=[]),
            )
        )

    monkeypatch.setattr(
        system_module.UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        read_config,
    )
    backend = SimpleNamespace(
        redis=None,
        instance_id="fixture",
        distributed_mode=False,
        job_queue=SimpleNamespace(size=AsyncMock(return_value=0)),
    )
    call = (
        system_module.get_backend_status
        if route == "backend"
        else websocket_module._build_system_health_snapshot
    )
    pending = asyncio.create_task(call(backend))
    try:
        async with asyncio.timeout(2):
            while not query_started.is_set():
                await asyncio.sleep(0.001)
        # A second coroutine runs while the settings query is still waiting.
        assert not pending.done()
        await asyncio.sleep(0)
    finally:
        release.set()
    result = await pending
    if route == "backend":
        assert result.max_workers == 1
    else:
        assert result["drives"] == []
        assert result["db_connected"] == {}


@pytest.mark.asyncio
async def test_backend_status_exposes_existing_system_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = SystemStats(
        backend_id="backend-pulse",
        timestamp="2026-09-01T12:00:00+00:00",
        cpu_percent=37.5,
        cpu_count=16,
        memory_total=64_000,
        memory_used=32_000,
        memory_free=32_000,
        memory_percent=50.0,
        disks=[
            DiskStats(
                device="nvme0n1",
                mount_point="/data",
                total_bytes=1_000_000,
                used_bytes=400_000,
                free_bytes=600_000,
                percent_used=40.0,
                read_bytes_per_sec=1_024.0,
                write_bytes_per_sec=2_048.0,
            )
        ],
    )
    monkeypatch.setattr(
        WorkerRegistry,
        "cleanup_dead_workers",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        WorkerRegistry,
        "get_backend_workers_info",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        SystemStatsReporter,
        "fetch_stats",
        AsyncMock(return_value=stats),
    )
    backend = SimpleNamespace(
        redis=object(),
        instance_id="backend-pulse",
        distributed_mode=True,
        job_queue=SimpleNamespace(size=AsyncMock(return_value=3)),
    )

    response = await system_module.get_backend_status(backend)

    assert response.pending_jobs == 3
    assert response.system_stats is not None
    assert response.system_stats.cpu_percent == 37.5
    assert response.system_stats.memory_percent == 50.0
    assert response.system_stats.disks[0].device == "nvme0n1"
    assert response.system_stats.disks[0].write_bytes_per_sec == 2_048.0


@pytest.mark.asyncio
async def test_backend_lifecycle_publishes_telemetry_consumed_by_status_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    published = asyncio.Event()
    stats = SystemStats(
        backend_id="backend-lifecycle",
        cpu_percent=37.5,
        memory_percent=50.0,
        disks=[
            DiskStats(
                "nvme0n1", "/data", 1000, 400, 600, 40.0, write_bytes_per_sec=2048.0
            )
        ],
    )

    async def publish(key: str, value: str, *, ex: int) -> None:
        await client.set(key, value, ex=ex)
        published.set()

    async def disconnect() -> None:
        assert reporter is not None
        assert not reporter.is_running
        assert reporter._task is None
        await client.aclose()

    redis = SimpleNamespace(
        client=client,
        set=publish,
        get=client.get,
        disconnect=disconnect,
    )
    backend = backend_module.BackendInstance(
        instance_id=stats.backend_id,
        redis=cast(Any, redis),
    )
    monkeypatch.setattr(backend, "_sync_backend_inventory", AsyncMock())
    monkeypatch.setattr(SystemStatsReporter, "_collect_stats", lambda self: stats)
    monkeypatch.setattr(WorkerRegistry, "cleanup_dead_workers", AsyncMock())
    monkeypatch.setattr(
        WorkerRegistry, "get_backend_workers_info", AsyncMock(return_value={})
    )

    reporter = None
    try:
        await backend.initialize()
        reporter = backend._stats_reporter
        assert reporter is not None
        first_task = reporter._task
        await backend.initialize()
        assert backend._stats_reporter is reporter
        assert reporter._task is first_task
        await asyncio.wait_for(published.wait(), timeout=2)

        response = await system_module.get_backend_status(backend)
        assert response.system_stats is not None
        assert response.system_stats.cpu_percent == 37.5
        assert response.system_stats.memory_percent == 50.0
        assert response.system_stats.disks[0].write_bytes_per_sec == 2048.0
        assert (
            0
            < await client.ttl(SystemStatsReporter.get_stats_key(stats.backend_id))
            <= 60
        )
    finally:
        await backend.close()
    assert backend._stats_reporter is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,has_redis", [(ProcessRole.CONTROL, False), (ProcessRole.WORKER, True)]
)
async def test_system_reporter_requires_control_process_and_redis(
    monkeypatch: pytest.MonkeyPatch,
    role: ProcessRole,
    has_redis: bool,
) -> None:
    reporter = Mock()
    monkeypatch.setattr(backend_module, "SystemStatsReporter", reporter)
    redis = SimpleNamespace(disconnect=AsyncMock()) if has_redis else None
    backend = backend_module.BackendInstance(
        instance_id="backend-no-reporter",
        redis=cast(Any, redis),
        process_role=role,
    )
    monkeypatch.setattr(backend, "_sync_backend_inventory", AsyncMock())
    try:
        await backend.initialize()
        reporter.assert_not_called()
    finally:
        await backend.close()
