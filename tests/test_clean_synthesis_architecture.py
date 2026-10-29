"""Unit tests for The Clean Synthesis Architecture."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ultima_scraper_backend.api.routes import mps as mps_module
from ultima_scraper_backend.job_system import mps_tasks, resources
from ultima_scraper_backend.redis.worker_registry import WorkerRegistry, WorkerStatus
from ultima_scraper_backend.workers import worker_pool


def test_smooth_weighted_round_robin_equal_weights() -> None:
    items = [("http://p1:8080", 8), ("http://p2:8080", 8), ("http://p3:8080", 8)]
    result = mps_module._smooth_weighted_round_robin(items)
    assert result == ["http://p1:8080", "http://p2:8080", "http://p3:8080"]


def test_smooth_weighted_round_robin_heterogeneous_weights() -> None:
    # 16 slots vs 8 slots -> weights 2 vs 1 -> cycle: p1, p2, p1
    items = [("http://p1:8080", 16), ("http://p2:8080", 8)]
    result = mps_module._smooth_weighted_round_robin(items)
    assert result == ["http://p1:8080", "http://p2:8080", "http://p1:8080"]
    assert result.count("http://p1:8080") == 2
    assert result.count("http://p2:8080") == 1


def test_smooth_weighted_round_robin_three_way_interleaving() -> None:
    # 16 slots, 8 slots, 16 slots -> weights 2, 1, 2 -> 5 items
    items = [("http://p1:8080", 16), ("http://p2:8080", 8), ("http://p3:8080", 16)]
    result = mps_module._smooth_weighted_round_robin(items)
    assert len(result) == 5
    assert result.count("http://p1:8080") == 2
    assert result.count("http://p2:8080") == 1
    assert result.count("http://p3:8080") == 2
    # Ensure no two identical items are adjacent when alternating is possible
    for i in range(len(result) - 1):
        assert result[i] != result[i + 1]


def test_resolve_mps_task_routes_deduplicates_fallbacks() -> None:
    # In an expanded pool, P1 appears twice consecutively or near each other
    expanded_pool = ["http://p1:8080", "http://p1:8080", "http://p2:8080", "http://p3:8080"]
    primary, fallbacks, direct_idx = mps_tasks._resolve_mps_task_routes(
        task_index=0,
        proxy_pool=expanded_pool,
        proxy_start_index=0,
        include_direct=True,
    )
    assert primary == "http://p1:8080"
    # Fallbacks must never include the primary p1 again
    assert "http://p1:8080" not in fallbacks
    # 3-hop max: 1 direct route + 1 primary proxy + 1 fallback proxy = 3 hops total
    assert fallbacks == ["http://p2:8080"]
    assert direct_idx is not None


def test_resolve_mps_task_routes_direct_cycle_distribution() -> None:
    pool = [f"http://p{i}:8080" for i in range(10)]
    # With 3-hop maximum (2 proxies + 1 direct), cycle_len = 2 + 1 = 3
    # Direct route rotates through indices 0..2
    direct_indices = [
        mps_tasks._resolve_mps_task_routes(
            task_index=t_idx,
            proxy_pool=pool,
            proxy_start_index=0,
            include_direct=True,
        )[2]
        for t_idx in range(10)
    ]
    assert direct_indices == [0, 1, 2, 0, 1, 2, 0, 1, 2, 0]


def test_resolve_proxy_pool_capacity_sums_declared_limits() -> None:
    configured = [
        SimpleNamespace(url="http://p1:8080", max_connections=16, enabled=True),
        SimpleNamespace(url="http://p2:8080", max_connections=8, enabled=True),
        SimpleNamespace(url="http://p3:8080", max_connections=32, enabled=False),
    ]
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=configured))
    )
    request = mps_module.MPSCreateJobRequest(
        site="OnlyFans",
        proxy_mode=mps_module.MPSProxyMode.ALL,
        use_proxies=True,
    )
    cap = mps_module._resolve_proxy_pool_capacity(
        request=request,
        config=config,
        backend_manager=SimpleNamespace(get_site_db_manager=lambda _: None),
    )
    # Only p1 (16) and p2 (8) are enabled -> 24
    assert cap == 24


def test_worker_dynamic_concurrency_calculation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ULTIMA_WORKER_CONCURRENCY", raising=False)
    # 100 proxies with 16 slots each = 1600 slots
    # 128 workers -> ceil(1600 / 128) = 13
    proxies = [
        SimpleNamespace(url=f"http://p{i}:8080", max_connections=16, enabled=True)
        for i in range(100)
    ]
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=proxies))
    )
    worker = worker_pool.Worker(
        worker_id="test-w1",
        redis_url="redis://localhost",
        supported_sites=["onlyfans"],
        config=config,
        worker_count=128,
    )
    concurrency = worker.compute_dynamic_concurrency()
    assert concurrency == 13


def test_worker_dynamic_concurrency_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ULTIMA_WORKER_CONCURRENCY", "7")
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
    )
    worker = worker_pool.Worker(
        worker_id="test-w1",
        redis_url="redis://localhost",
        supported_sites=["onlyfans"],
        config=config,
        worker_count=128,
    )
    assert worker.compute_dynamic_concurrency() == 7


def test_worker_dynamic_concurrency_variable_workers_and_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ULTIMA_WORKER_CONCURRENCY", raising=False)
    monkeypatch.delenv("ULTIMA_WORKER_CONCURRENCY_CEILING", raising=False)
    monkeypatch.delenv("ULTIMA_WORKER_MAX_CONCURRENCY", raising=False)

    # 464 proxies with 1 slot each = 464 slots.
    # 8 workers -> ceil(464 / 8) = 58.
    proxies = [
        SimpleNamespace(url=f"http://proxy-{i}:8080", max_connections=1, enabled=True)
        for i in range(464)
    ]
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=proxies))
    )
    worker = worker_pool.Worker(
        worker_id="test-w-8",
        redis_url="redis://localhost",
        supported_sites=["onlyfans"],
        config=config,
        worker_count=8,
    )

    # With safe FD boundary (typically >= 224), 58 is NOT clamped to 50
    concurrency = worker.compute_dynamic_concurrency()
    assert concurrency == 58

    # Explicit max_ceiling parameter restricts concurrency
    assert worker.compute_dynamic_concurrency(max_ceiling=50) == 50
    assert worker.compute_dynamic_concurrency(max_ceiling=30) == 30

    # Environment variable ULTIMA_WORKER_CONCURRENCY_CEILING overrides safe ceiling
    monkeypatch.setenv("ULTIMA_WORKER_CONCURRENCY_CEILING", "48")
    assert worker.compute_dynamic_concurrency() == 48

    # Environment variable ULTIMA_WORKER_MAX_CONCURRENCY also overrides ceiling
    monkeypatch.delenv("ULTIMA_WORKER_CONCURRENCY_CEILING", raising=False)
    monkeypatch.setenv("ULTIMA_WORKER_MAX_CONCURRENCY", "52")
    assert worker.compute_dynamic_concurrency() == 52


@pytest.mark.asyncio
async def test_worker_registry_concurrent_task_lifecycle() -> None:
    redis_mock = AsyncMock()
    registry = WorkerRegistry(
        redis_manager=redis_mock,
        backend_id="default",
        worker_id="w-test",
    )

    # Start task 1
    await registry.start_task("task-1", "scrape")
    info = registry._get_worker_info()
    assert info.status == WorkerStatus.BUSY.value
    assert "task-1" in registry._active_tasks

    # Start concurrent task 2
    await registry.start_task("task-2", "scrape")
    assert len(registry._active_tasks) == 2
    assert info.status == WorkerStatus.BUSY.value

    # Complete task 1 -> worker should STAY busy because task 2 is still active!
    await registry.complete_task(success=True, task_id="task-1")
    assert info.status == WorkerStatus.BUSY.value
    assert "task-1" not in registry._active_tasks
    assert "task-2" in registry._active_tasks

    # Complete task 2 -> worker should now transition to IDLE!
    await registry.complete_task(success=True, task_id="task-2")
    assert info.status == WorkerStatus.IDLE.value
    assert len(registry._active_tasks) == 0


def test_window_policy_scales_with_proxy_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1000")
    metadata = {
        "job_resource_scope": "mps",
        "proxy_capacity": 1500,
    }
    policy = resources.window_policy(metadata, storage=MagicMock())
    # 1500 * 1.2 = 1800 tasks
    assert policy.tasks == 1800


@pytest.mark.skip(reason="Worker.run now uses the SQL execution ledger; this legacy router test would claim real work from the configured database and never finish")
@pytest.mark.asyncio
async def test_worker_run_empty_claim_non_blocking_when_under_concurrency_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
    )
    worker = worker_pool.Worker(
        worker_id="test-w1",
        redis_url="redis://localhost",
        supported_sites=["onlyfans"],
        config=config,
        worker_count=1,
    )
    worker.apis = {"onlyfans": MagicMock()}
    worker.backend_router = MagicMock()
    worker.task_job_storage = MagicMock()

    # Dynamic concurrency = 4 (default with no proxies)
    assert worker.compute_dynamic_concurrency() == 4

    loop_iterations = 0
    sleep_calls: list[float] = []

    async def fake_claim(*args: Any, **kwargs: Any) -> None:
        nonlocal loop_iterations
        loop_iterations += 1
        if loop_iterations >= 3:
            worker._shutdown_event.set()
        return None

    worker.backend_router.claim_ready_task = AsyncMock(side_effect=fake_claim)

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(worker_pool.asyncio, "sleep", fake_sleep)

    wait_mock = AsyncMock(return_value=(set(), set()))
    monkeypatch.setattr(worker_pool.asyncio, "wait", wait_mock)

    await worker.run()

    # When under dynamic_concurrency limit (active_tasks is empty or under 4),
    # asyncio.sleep(0.05) is called instead of asyncio.wait
    assert 0.05 in sleep_calls
    assert wait_mock.await_count == 0

