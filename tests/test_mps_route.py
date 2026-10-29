from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlmodel import Session

from ultima_scraper_backend.api.routes import mps as mps_module
from ultima_scraper_backend.job_system import materializer, mps_tasks
from ultima_scraper_backend.api.routes.jobs import (
    JobStatus,
    _is_stale_incomplete_active_job,
)


class _FakeRedisManager:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.is_connected = True

    async def get(self, key: str) -> Any:
        return await self.client.get(key)

    async def set(self, key: str, value: Any, **kwargs: Any) -> Any:
        return await self.client.set(key, value, **kwargs)

    async def delete(self, key: str) -> Any:
        return await self.client.delete(key)

    async def hget(self, key: str, field: str) -> Any:
        return await self.client.hget(key, field)

    async def keys(self, pattern: str) -> list[str]:
        raw_keys = await self.client.keys(pattern)
        return [
            key.decode() if isinstance(key, bytes) else str(key) for key in raw_keys
        ]

    async def smembers(self, key: str) -> set[str]:
        raw_members = await self.client.smembers(key)
        return {
            member.decode() if isinstance(member, bytes) else str(member)
            for member in raw_members
        }


def test_active_materialization_is_not_reclassified_as_a_ghost_job() -> None:
    common = {
        "status": JobStatus.PENDING,
        "created_at": "2020-01-01T00:00:00+00:00",
        "has_redis_artifact": True,
        "has_canonical_artifacts": False,
        "expected_task_count": 10_000,
    }

    assert not _is_stale_incomplete_active_job(
        **common,
        materialization_status="materializing",
    )
    assert _is_stale_incomplete_active_job(
        **common,
        materialization_status=None,
    )


@pytest.mark.asyncio
async def test_materialization_lock_release_never_deletes_a_new_owner() -> None:
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    lock_key = "test:mps:materialization:lock"
    await client.set(lock_key, "new-owner")

    await materializer._release_mps_materialization_lock(
        client,
        lock_key=lock_key,
        owner="old-owner",
    )
    assert await client.get(lock_key) == b"new-owner"

    await materializer._release_mps_materialization_lock(
        client,
        lock_key=lock_key,
        owner="new-owner",
    )
    assert not await client.exists(lock_key)

    with pytest.raises(materializer._MPSMaterializationLockLost):
        await materializer._ensure_mps_materialization_lock(
            client,
            lock_key=lock_key,
            owner="new-owner",
        )

    await client.set(lock_key, "replacement-owner")
    with pytest.raises(materializer._MPSMaterializationBusy):
        await materializer._ensure_mps_materialization_lock(
            client,
            lock_key=lock_key,
            owner="new-owner",
        )


@pytest.mark.asyncio
async def test_invalid_only_scope_uses_invalid_table_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_manager = object()
    bounds_mock = AsyncMock(return_value=(40, 90))
    monkeypatch.setattr(mps_module, "_query_min_max", bounds_mock)

    scope = await mps_module._resolve_analysis_scope(
        mps_module.MPSAnalyzeRequest(
            site="OnlyFans",
            ignore_missing_ids=True,
            include_invalid=True,
        ),
        backend_manager=SimpleNamespace(get_site_db_manager=lambda _site: db_manager),
    )

    assert scope.start_id == 40
    assert scope.end_id == 90
    bounds_mock.assert_awaited_once_with(
        db_manager,
        site_key="onlyfans",
        include_user_bounds=False,
        include_invalid_bounds=True,
    )


def _full_missing_summary(result, *, existing_count=0, invalid_count=0, invalid_table_ready=True):
    """Stand in for the full coverage scan, which also reports inventories."""

    async def fake(*_args, **kwargs):
        if kwargs.get("coverage_summary") is not None:
            kwargs["coverage_summary"].update(
                existing_count=existing_count,
                invalid_count=invalid_count,
                invalid_table_ready=invalid_table_ready,
            )
        return result

    return AsyncMock(side_effect=fake)


def _forbid_standalone_user_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mps_module,
        "_query_existing_count",
        AsyncMock(side_effect=AssertionError("full analysis counts users in the coverage pass")),
    )


@pytest.mark.asyncio
async def test_compute_analysis_summary_includes_batch_plan_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_scope(_request, _backend_manager):
        return mps_module._AnalysisScope(
            site_display="OnlyFans",
            site_key="onlyfans",
            db_manager=object(),
            database_min_id=1,
            database_max_id=200_000,
            start_id=1,
            end_id=200_000,
        )

    monkeypatch.setattr(mps_module, "_resolve_analysis_scope", fake_scope)
    _forbid_standalone_user_count(monkeypatch)
    monkeypatch.setattr(
        mps_module, "_query_invalid_counts", AsyncMock(return_value=(0, 0, True))
    )
    monkeypatch.setattr(
        mps_module,
        "_query_existing_candidate_count",
        AsyncMock(return_value=75),
    )
    monkeypatch.setattr(
        mps_module,
        "_query_existing_candidate_ids_preview",
        AsyncMock(return_value=[1_000, 1_001]),
    )
    monkeypatch.setattr(
        mps_module,
        "_query_missing_ranges_summary",
        _full_missing_summary((1_250, 8, [(100, 199), (300, 349)]), existing_count=200),
    )

    response = await mps_module._compute_analysis_summary(
        mps_module.MPSAnalyzeRequest(
            site="OnlyFans",
            include_existing_users=True,
            existing_last_checked_older_than_hours=24,
            candidate_offset=250,
            batch_size=500,
            start_id=1,
            end_id=200_000,
        ),
        backend_manager=SimpleNamespace(),
    )

    assert response.candidate_count == 1_325
    assert response.candidate_offset == 250
    assert response.planned_candidate_count == 500
    assert response.remaining_candidate_count == 1_075
    assert response.next_candidate_offset == 750
    assert response.has_next_batch is True
    assert [item.batch_size for item in response.batch_recommendations] == [
        1_000,
        1_325,
    ]
    assert response.recommended_batch_size == 1_325
    assert any("skipping the first 250" in warning for warning in response.warnings)
    assert response.requires_confirmation is False


@pytest.mark.asyncio
async def test_compute_analysis_summary_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_scope(_request, _backend_manager):
        return mps_module._AnalysisScope(
            site_display="OnlyFans",
            site_key="onlyfans",
            db_manager=object(),
            database_min_id=1,
            database_max_id=500_000_000,
            start_id=1,
            end_id=500_000_000,
        )

    async def fake_missing_summary(*_args, **kwargs):
        if kwargs.get("candidate_summary") is not None:
            kwargs["candidate_summary"].update(
                count=500_000_000,
                range_count=1,
                ranges=[(1, 500_000_000)],
            )
        return (500_000_000, 1, [(1, 500_000_000)], None)

    monkeypatch.setattr(mps_module, "_resolve_analysis_scope", fake_scope)
    monkeypatch.setattr(
        mps_module, "_query_invalid_counts", AsyncMock(return_value=(0, 0, True))
    )
    monkeypatch.setattr(
        mps_module, "_query_missing_ranges_summary", fake_missing_summary
    )

    sampled_density = [mps_module.MPSDensityBucket(
        start_id=1, end_id=500_000_000, missing_count=500_000_000,
        invalid_count=0, existing_count=0, candidate_count=500_000_000, is_exact=False,
    )]
    density_mock = AsyncMock(return_value=sampled_density)
    monkeypatch.setattr(mps_module, "_sample_density_buckets", density_mock)

    response = await mps_module._compute_analysis_summary(
        mps_module.MPSAnalyzeRequest(
            site="OnlyFans",
            start_id=1,
            end_id=500_000_000,
            batch_size=5_000,
            bounded=True,
        ),
        backend_manager=SimpleNamespace(),
    )

    density_mock.assert_awaited_once()
    assert response.density_buckets == sampled_density
    assert response.density_is_exact is False
    assert response.end_id == 500_000_000
    assert response.range_size == 500_000_000
    assert response.candidate_count == 500_000_000
    assert response.planned_candidate_count == 5_000
    assert response.has_next_batch is True
    assert response.next_candidate_offset == 5_000


@pytest.mark.asyncio
async def test_compute_analysis_summary_detects_frontier_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_scope(_request, _backend_manager):
        return mps_module._AnalysisScope(
            site_display="OnlyFans",
            site_key="onlyfans",
            db_manager=object(),
            database_min_id=1,
            database_max_id=500_000_000,
            start_id=1,
            end_id=500_000_000,
        )

    monkeypatch.setattr(mps_module, "_resolve_analysis_scope", fake_scope)
    _forbid_standalone_user_count(monkeypatch)
    monkeypatch.setattr(
        mps_module, "_query_invalid_counts", AsyncMock(return_value=(0, 0, True))
    )
    monkeypatch.setattr(
        mps_module,
        "_query_existing_candidate_count",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        mps_module,
        "_query_existing_candidate_ids_preview",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        mps_module,
        "_query_missing_ranges_summary",
        _full_missing_summary(
            (
                400_000_000,
                10_000,
                [(100, 199), (480_000_000, 499_999_999)],
                (480_000_000, 499_999_999),
            ),
            existing_count=1_000,
        ),
    )

    response = await mps_module._compute_analysis_summary(
        mps_module.MPSAnalyzeRequest(
            site="OnlyFans",
            start_id=1,
            end_id=500_000_000,
        ),
        backend_manager=SimpleNamespace(),
    )

    assert response.missing_count == 400_000_000
    assert response.frontier_range is not None
    assert response.frontier_range.start_id == 480_000_000
    assert response.frontier_range.end_id == 499_999_999
    assert response.frontier_range.count == 20_000_000
    assert any(
        r.start_id == 480_000_000 and r.end_id == 499_999_999
        for r in response.candidate_ranges_preview
    )


def test_batch_plan_allows_a_million_profile_job() -> None:
    plan = mps_module._build_batch_plan(
        candidate_count=1_500_000,
        candidate_offset=0,
        requested_batch_size=1_000_000,
        range_size=2_000_000,
        invalid_table_ready=True,
        include_invalid=False,
        invalid_last_checked_older_than_hours=None,
        include_existing_users=False,
        existing_last_checked_older_than_hours=None,
    )

    assert plan.planned_candidate_count == 1_000_000
    assert plan.remaining_candidate_count == 1_500_000
    assert plan.next_candidate_offset == 1_000_000
    assert plan.has_next_batch is True


@pytest.mark.asyncio
async def test_compute_analysis_summary_supports_invalid_only_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_scope(_request, _backend_manager):
        return mps_module._AnalysisScope(
            site_display="OnlyFans",
            site_key="onlyfans",
            db_manager=object(),
            database_min_id=1,
            database_max_id=1_000,
            start_id=1,
            end_id=1_000,
        )

    invalid_counts_mock = AsyncMock(return_value=(0, 5, True))
    invalid_preview_mock = AsyncMock(return_value=[2, 4, 8, 9, 10])
    missing_summary_mock = _full_missing_summary(
        (0, 0, [], None), existing_count=100, invalid_count=12
    )
    monkeypatch.setattr(mps_module, "_resolve_analysis_scope", fake_scope)
    _forbid_standalone_user_count(monkeypatch)
    monkeypatch.setattr(mps_module, "_query_invalid_counts", invalid_counts_mock)
    monkeypatch.setattr(
        mps_module,
        "_query_invalid_candidate_ids_preview",
        invalid_preview_mock,
    )
    monkeypatch.setattr(
        mps_module, "_query_missing_ranges_summary", missing_summary_mock
    )

    response = await mps_module._compute_analysis_summary(
        mps_module.MPSAnalyzeRequest(
            site="OnlyFans",
            start_id=1,
            end_id=1_000,
            ignore_missing_ids=True,
            include_invalid=True,
            invalid_last_checked_older_than_hours=168,
        ),
        backend_manager=SimpleNamespace(),
    )

    assert response.missing_count == 0
    assert response.invalid_user_count == 12
    assert response.invalid_eligible_count == 5
    assert response.existing_eligible_count == 0
    assert response.candidate_count == 5
    assert response.candidate_ids_preview == [2, 4, 8, 9, 10]
    assert [
        (item.start_id, item.end_id, item.count)
        for item in response.candidate_ranges_preview
    ] == [(2, 2, 1), (4, 4, 1), (8, 10, 3)]
    assert response.candidate_preview_truncated is False
    assert missing_summary_mock.await_count == 1
    assert missing_summary_mock.await_args.kwargs["include_missing"] is False
    assert invalid_counts_mock.await_args.kwargs == {
        "site_key": "onlyfans",
        "start_id": 1,
        "end_id": 1_000,
        "include_invalid": True,
        "last_checked_older_than_hours": 168,
        "include_total": False,
    }
    assert invalid_preview_mock.await_args.kwargs == {
        "site_key": "onlyfans",
        "start_id": 1,
        "end_id": 1_000,
        "last_checked_older_than_hours": 168,
        "limit": 250,
    }


@pytest.mark.asyncio
async def test_compute_analysis_selects_only_eligible_invalid_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_scope(_request, _backend_manager):
        return mps_module._AnalysisScope(
            site_display="OnlyFans",
            site_key="onlyfans",
            db_manager=object(),
            database_min_id=1,
            database_max_id=10,
            start_id=1,
            end_id=10,
        )

    ids_mock = AsyncMock(return_value=([10], [2, 4, 10], [2, 4], True))
    monkeypatch.setattr(mps_module, "_resolve_analysis_scope", fake_scope)
    monkeypatch.setattr(mps_module, "_query_ids_in_range", ids_mock)

    analysis = await mps_module._compute_analysis(
        mps_module.MPSCreateJobRequest(
            site="OnlyFans",
            start_id=1,
            end_id=10,
            ignore_missing_ids=True,
            include_invalid=True,
            invalid_last_checked_older_than_hours=168,
        ),
        backend_manager=SimpleNamespace(),
    )

    assert analysis.missing_ranges == []
    assert analysis.eligible_invalid_ids == [2, 4]
    assert analysis.candidate_ranges == [(2, 2), (4, 4)]
    assert analysis.candidate_count == 2
    assert ids_mock.await_args.kwargs["invalid_last_checked_older_than_hours"] == 168


@pytest.mark.asyncio
async def test_compute_analysis_keeps_missing_and_eligible_invalid_ids_in_id_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_scope(_request, _backend_manager):
        return mps_module._AnalysisScope(
            site_display="OnlyFans",
            site_key="onlyfans",
            db_manager=object(),
            database_min_id=1,
            database_max_id=6,
            start_id=1,
            end_id=6,
        )

    monkeypatch.setattr(mps_module, "_resolve_analysis_scope", fake_scope)
    monkeypatch.setattr(
        mps_module,
        "_query_ids_in_range",
        AsyncMock(return_value=([1, 6], [2, 4], [4], True)),
    )

    analysis = await mps_module._compute_analysis(
        mps_module.MPSCreateJobRequest(
            site="OnlyFans",
            start_id=1,
            end_id=6,
            include_invalid=True,
            invalid_last_checked_older_than_hours=168,
        ),
        backend_manager=SimpleNamespace(),
    )

    assert analysis.missing_ranges == [(3, 3), (5, 5)]
    assert analysis.candidate_ranges == [(3, 5)]
    assert analysis.missing_count == 2
    assert analysis.candidate_count == 3
    assert mps_module._select_candidate_ids(
        candidate_ranges=analysis.candidate_ranges,
        eligible_existing_ids=[],
        offset=0,
        limit=None,
    ) == [3, 4, 5]


@pytest.mark.asyncio
async def test_create_mps_job_uses_durable_selection_with_redis(monkeypatch):
    from ultima_scraper_backend.api.routes import mps_durable

    durable_create = AsyncMock(return_value=object())
    full_analysis = AsyncMock(side_effect=AssertionError("Whole candidate analysis must not run"))
    monkeypatch.setattr(mps_durable, "create_job", durable_create)
    monkeypatch.setattr(mps_module, "_compute_analysis", full_analysis)
    request = mps_module.MPSCreateJobRequest(start_id=1, end_id=1_000_000)
    backend = SimpleNamespace(redis=SimpleNamespace(is_connected=True))
    backend_manager = SimpleNamespace()
    config = SimpleNamespace()
    result = await mps_module.create_mps_job(request, backend, backend_manager, config)
    assert result is durable_create.return_value
    durable_create.assert_awaited_once_with(request, backend, backend_manager, config)
    full_analysis.assert_not_awaited()


def test_resolve_proxy_pool_rejects_invalid_custom_proxy_urls() -> None:
    with pytest.raises(HTTPException) as exc_info:
        mps_module._resolve_proxy_pool(
            request=mps_module.MPSCreateJobRequest(
                site="OnlyFans",
                proxy_mode=mps_module.MPSProxyMode.CUSTOM,
                use_proxies=True,
                proxy_urls=["notaurl"],
            ),
            config=SimpleNamespace(
                settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
            ),
            backend_manager=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert "Invalid proxy URL" in str(exc_info.value.detail)


def test_resolve_proxy_pool_rejects_disabled_configured_custom_proxy() -> None:
    disabled_proxy_url = "http://disabled.example:8080"

    with pytest.raises(HTTPException) as exc_info:
        mps_module._resolve_proxy_pool(
            request=mps_module.MPSCreateJobRequest(
                site="OnlyFans",
                proxy_mode=mps_module.MPSProxyMode.CUSTOM,
                use_proxies=True,
                proxy_urls=[disabled_proxy_url],
            ),
            config=SimpleNamespace(
                settings=SimpleNamespace(
                    network=SimpleNamespace(
                        proxies=[SimpleNamespace(url=disabled_proxy_url, enabled=False)]
                    )
                )
            ),
            backend_manager=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert "disabled configured proxy" in str(exc_info.value.detail)


def test_resolve_proxy_pool_treats_only_active_auth_assignments_as_reserved() -> None:
    disabled_only_proxy = "http://disabled-only.example:8080"
    active_proxy = "http://active.example:8080"
    shared_proxy = "http://shared.example:8080"
    unassigned_proxy = "http://unassigned.example:8080"
    disabled_config_proxy = "http://disabled-config.example:8080"

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE user_auths ("
                "proxy_id VARCHAR(256), active BOOLEAN NOT NULL"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO user_auths (proxy_id, active) "
                "VALUES (:proxy_id, :active)"
            ),
            [
                {"proxy_id": disabled_only_proxy, "active": False},
                {"proxy_id": active_proxy, "active": True},
                {"proxy_id": shared_proxy, "active": False},
                {"proxy_id": shared_proxy, "active": True},
            ],
        )

    site_db = SimpleNamespace(get_session=lambda: Session(engine))

    def get_site_db_manager(site_name: str) -> SimpleNamespace:
        if site_name != "OnlyFans":
            raise LookupError(site_name)
        return site_db

    configured_proxies = [
        SimpleNamespace(url=disabled_only_proxy),
        SimpleNamespace(url=active_proxy),
        SimpleNamespace(url=shared_proxy),
        SimpleNamespace(url=unassigned_proxy),
        SimpleNamespace(url=disabled_config_proxy, enabled=False),
    ]

    proxy_pool = mps_module._resolve_proxy_pool(
        request=mps_module.MPSCreateJobRequest(
            site="OnlyFans",
            proxy_mode=mps_module.MPSProxyMode.UNASSIGNED_ONLY,
            use_proxies=True,
        ),
        config=SimpleNamespace(
            settings=SimpleNamespace(
                network=SimpleNamespace(proxies=configured_proxies)
            )
        ),
        backend_manager=SimpleNamespace(get_site_db_manager=get_site_db_manager),
    )

    assert proxy_pool == [disabled_only_proxy, unassigned_proxy]


def _active_assignment_backend(assigned_proxy: str) -> SimpleNamespace:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE user_auths ("
                "proxy_id VARCHAR(256), active BOOLEAN NOT NULL"
                ")"
            )
        )
        connection.execute(
            text("INSERT INTO user_auths (proxy_id, active) VALUES (:proxy_id, 1)"),
            {"proxy_id": assigned_proxy},
        )
    site_db = SimpleNamespace(get_session=lambda: Session(engine))

    def get_site_db_manager(site_name: str) -> SimpleNamespace:
        if site_name != "OnlyFans":
            raise LookupError(site_name)
        return site_db

    return SimpleNamespace(get_site_db_manager=get_site_db_manager)


def test_resolve_proxy_pool_all_mode_keeps_assigned_and_excludes_disabled() -> None:
    assigned_proxy = "http://assigned.example:8080"
    free_proxy = "http://free.example:8080"
    disabled_proxy = "http://disabled.example:8080"

    proxy_pool = mps_module._resolve_proxy_pool(
        request=mps_module.MPSCreateJobRequest(
            site="OnlyFans",
            proxy_mode=mps_module.MPSProxyMode.ALL,
            use_proxies=True,
        ),
        config=SimpleNamespace(
            settings=SimpleNamespace(
                network=SimpleNamespace(
                    proxies=[
                        SimpleNamespace(url=assigned_proxy),
                        SimpleNamespace(url=free_proxy),
                        SimpleNamespace(url=disabled_proxy, enabled=False),
                    ]
                )
            )
        ),
        backend_manager=_active_assignment_backend(assigned_proxy),
        expand_weights=False,
    )

    assert proxy_pool == [assigned_proxy, free_proxy]


def test_resolve_proxy_pool_custom_mode_allows_active_assigned_proxy() -> None:
    assigned_proxy = "http://assigned.example:8080"

    proxy_pool = mps_module._resolve_proxy_pool(
        request=mps_module.MPSCreateJobRequest(
            site="OnlyFans",
            proxy_mode=mps_module.MPSProxyMode.CUSTOM,
            use_proxies=True,
            proxy_urls=[assigned_proxy],
        ),
        config=SimpleNamespace(
            settings=SimpleNamespace(
                network=SimpleNamespace(proxies=[SimpleNamespace(url=assigned_proxy)])
            )
        ),
        backend_manager=_active_assignment_backend(assigned_proxy),
        expand_weights=False,
    )

    assert proxy_pool == [assigned_proxy]


def test_build_mps_task_payloads_with_empty_and_single_proxy_pool() -> None:
    # Empty pool: direct connection used as route 0 fallback
    empty_tasks = mps_module._build_mps_task_payloads(
        site_display="OnlyFans",
        target_user_ids=[101, 102],
        proxy_pool=[],
    )
    assert len(empty_tasks) == 2
    assert "guest_proxy_url" not in empty_tasks[0].params
    assert "guest_fallback_proxy_urls" not in empty_tasks[0].params
    assert empty_tasks[0].params["guest_direct_route_index"] == 0

    # Single proxy pool: direct connection excluded by default
    single_tasks = mps_module._build_mps_task_payloads(
        site_display="OnlyFans",
        target_user_ids=[101, 102],
        proxy_pool=["http://proxy1:8080"],
    )
    assert len(single_tasks) == 2
    assert single_tasks[0].params["guest_proxy_url"] == "http://proxy1:8080"
    assert "guest_fallback_proxy_urls" not in single_tasks[0].params
    assert single_tasks[0].params["guest_direct_route_index"] is None
    assert single_tasks[1].params["guest_direct_route_index"] is None

    # Single proxy pool with include_direct=True
    single_tasks_direct = mps_module._build_mps_task_payloads(
        site_display="OnlyFans",
        target_user_ids=[101, 102],
        proxy_pool=["http://proxy1:8080"],
        include_direct=True,
    )
    assert single_tasks_direct[0].params["guest_direct_route_index"] == 0
    assert single_tasks_direct[1].params["guest_direct_route_index"] == 1


def test_build_mps_task_payloads_with_multi_proxy_pool_rotates_fallbacks() -> None:
    proxies = [
        "http://proxy1:8080",
        "http://proxy2:8080",
        "http://proxy3:8080",
        "http://proxy4:8080",
        "http://proxy5:8080",
    ]
    tasks = mps_module._build_mps_task_payloads(
        site_display="OnlyFans",
        target_user_ids=[1, 2, 3],
        proxy_pool=proxies,
    )

    # Task 0 (User 1) - 3 proxy hops total (no direct connection): proxy1 + proxy2 + proxy3
    assert tasks[0].params["guest_direct_route_index"] is None
    assert tasks[0].params["guest_proxy_url"] == "http://proxy1:8080"
    assert tasks[0].params["guest_fallback_proxy_urls"] == [
        "http://proxy2:8080",
        "http://proxy3:8080",
    ]

    # Task 1 (User 2) - 3 proxy hops total (no direct connection): proxy2 + proxy3 + proxy4
    assert tasks[1].params["guest_direct_route_index"] is None
    assert tasks[1].params["guest_proxy_url"] == "http://proxy2:8080"
    assert tasks[1].params["guest_fallback_proxy_urls"] == [
        "http://proxy3:8080",
        "http://proxy4:8080",
    ]

    # Task 2 (User 3) - 3 proxy hops total (no direct connection): proxy3 + proxy4 + proxy5
    assert tasks[2].params["guest_direct_route_index"] is None
    assert tasks[2].params["guest_proxy_url"] == "http://proxy3:8080"
    assert tasks[2].params["guest_fallback_proxy_urls"] == [
        "http://proxy4:8080",
        "http://proxy5:8080",
    ]

    # When include_direct=True, direct route rotates across 3 hops (2 proxies + 1 direct)
    tasks_with_direct = mps_module._build_mps_task_payloads(
        site_display="OnlyFans",
        target_user_ids=[1, 2, 3],
        proxy_pool=proxies,
        include_direct=True,
    )
    assert tasks_with_direct[0].params["guest_direct_route_index"] == 0
    assert tasks_with_direct[0].params["guest_proxy_url"] == "http://proxy1:8080"
    assert tasks_with_direct[0].params["guest_fallback_proxy_urls"] == ["http://proxy2:8080"]

    assert tasks_with_direct[1].params["guest_direct_route_index"] == 1
    assert tasks_with_direct[1].params["guest_proxy_url"] == "http://proxy2:8080"
    assert tasks_with_direct[1].params["guest_fallback_proxy_urls"] == ["http://proxy3:8080"]

    assert tasks_with_direct[2].params["guest_direct_route_index"] == 2
    assert tasks_with_direct[2].params["guest_proxy_url"] == "http://proxy3:8080"
    assert tasks_with_direct[2].params["guest_fallback_proxy_urls"] == ["http://proxy4:8080"]


def test_build_mps_task_batch_is_restart_idempotent_and_keeps_route_order() -> None:
    proxies = ["http://proxy1:8080", "http://proxy2:8080"]
    first = mps_tasks._build_mps_task_batch(
        job_id="job-materialize",
        site_display="OnlyFans",
        target_user_ids=[101, 102],
        proxy_pool=proxies,
        candidate_offset=2,
    )
    replay = mps_tasks._build_mps_task_batch(
        job_id="job-materialize",
        site_display="OnlyFans",
        target_user_ids=[101, 102],
        proxy_pool=proxies,
        candidate_offset=2,
    )
    expected_routes = mps_module._build_mps_task_payloads(
        site_display="OnlyFans",
        target_user_ids=[99, 100, 101, 102],
        proxy_pool=proxies,
    )[2:]

    assert [task.task_id for task in first] == [task.task_id for task in replay]
    assert [task.user_id for task in first] == [101, 102]
    for task, expected in zip(first, expected_routes, strict=True):
        assert (
            task.payload_value("guest_proxy_url") == expected.params["guest_proxy_url"]
        )
        assert (
            task.payload_value("guest_direct_route_index")
            == expected.params["guest_direct_route_index"]
        )


@pytest.mark.asyncio
async def test_proxy_preview_includes_direct_connection_when_no_proxies() -> None:
    response = await mps_module.preview_mps_proxies(
        mps_module.MPSProxyPreviewRequest(
            site="OnlyFans",
            use_proxies=False,
            proxy_mode=mps_module.MPSProxyMode.NONE,
        ),
        config=SimpleNamespace(
            settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
        ),
        backend_manager=SimpleNamespace(),
    )

    assert response.proxies_used == 0
    assert response.direct_connection_included is True
    assert response.proxy_urls == []


@pytest.mark.asyncio
async def test_proxy_preview_excludes_direct_connection_by_default_when_proxies_present() -> None:
    response = await mps_module.preview_mps_proxies(
        mps_module.MPSProxyPreviewRequest(
            site="OnlyFans",
            use_proxies=True,
            proxy_mode=mps_module.MPSProxyMode.UNASSIGNED_ONLY,
        ),
        config=SimpleNamespace(
            settings=SimpleNamespace(
                network=SimpleNamespace(
                    proxies=[SimpleNamespace(url="http://p1:8080")]
                )
            )
        ),
        backend_manager=SimpleNamespace(),
    )

    assert response.proxies_used == 1
    assert response.direct_connection_included is False
    assert response.proxy_urls == ["http://p1:8080"]


@pytest.mark.asyncio
async def test_create_durable_mps_job_persists_include_direct_connection_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.api.routes import mps_durable
    from ultima_scraper_backend.job_system import Job

    captured_job_config: dict[str, Any] = {}

    class DummyWriteClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def submit(self, op: Any, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            nonlocal captured_job_config
            captured_job_config = payload.get("job_config", {})
            return {
                "total": 1,
                "summary": {
                    "candidate_count": 1,
                    "missing_count": 1,
                    "invalid_eligible_count": 0,
                    "existing_eligible_count": 0,
                },
            }

    monkeypatch.setattr(mps_durable, "DatabaseWriteClient", DummyWriteClient)
    dummy_job = Job.create(name="dummy", tasks=[], created_by="test")
    monkeypatch.setattr(mps_durable.durable, "publish", AsyncMock(return_value=dummy_job))
    from ultima_scraper_backend.api.routes import jobs as jobs_routes

    monkeypatch.setattr(jobs_routes, "publish_ws_event", AsyncMock())
    monkeypatch.setattr(
        mps_module,
        "_resolve_analysis_scope",
        AsyncMock(
            return_value=SimpleNamespace(
                site_key="onlyfans", site_display="OnlyFans", start_id=1, end_id=10
            )
        ),
    )
    monkeypatch.setattr(mps_module, "_resolve_proxy_pool", lambda **kwargs: [])
    monkeypatch.setattr(mps_module, "_resolve_proxy_pool_capacity", lambda **kwargs: 8)

    request = mps_module.MPSCreateJobRequest(
        site="OnlyFans",
        start_id=1,
        end_id=10,
        include_direct_connection=False,
    )
    backend = SimpleNamespace(redis=SimpleNamespace(is_connected=True))
    backend_manager = SimpleNamespace()
    config = SimpleNamespace(settings=SimpleNamespace(network=SimpleNamespace(proxies=[])))

    await mps_durable.create_job(request, backend, backend_manager, config)
    assert captured_job_config["metadata"]["include_direct_connection"] is False

    request_direct = mps_module.MPSCreateJobRequest(
        site="OnlyFans",
        start_id=1,
        end_id=10,
        include_direct_connection=True,
    )
    await mps_durable.create_job(request_direct, backend, backend_manager, config)
    assert captured_job_config["metadata"]["include_direct_connection"] is True


def test_backend_manager_initialization_accepts_backward_compatible_kwargs(monkeypatch: Any) -> None:
    from unittest.mock import MagicMock
    from ultima_scraper_backend.manager import BackendManager

    monkeypatch.setattr("ultima_scraper_backend.manager.get_global_engine", lambda: MagicMock())
    monkeypatch.setattr("ultima_scraper_backend.manager.MultiSiteDatabaseManager", lambda: MagicMock())

    # Must accept config_path keyword argument without raising TypeError
    bm_legacy = BackendManager(config_path=None)
    assert bm_legacy is not None

    bm_default = BackendManager()
    assert bm_default is not None


def test_get_backend_manager_dependency_singleton(monkeypatch: Any) -> None:
    from unittest.mock import MagicMock
    import ultima_scraper_backend.api.dependencies as deps

    monkeypatch.setattr(deps, "_backend_manager", None)
    monkeypatch.setattr("ultima_scraper_backend.manager.get_global_engine", lambda: MagicMock())
    monkeypatch.setattr("ultima_scraper_backend.manager.MultiSiteDatabaseManager", lambda: MagicMock())

    bm = deps.get_backend_manager()
    assert bm is not None
    assert deps.get_backend_manager() is bm


@pytest.mark.asyncio
async def test_mps_proxy_preview_handler() -> None:
    req = mps_module.MPSProxyPreviewRequest(
        site="OnlyFans",
        use_proxies=False,
        include_direct_connection=True,
    )
    fake_config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
    )
    fake_backend_manager = SimpleNamespace()

    resp = await mps_module.preview_mps_proxies(
        request=req,
        config=fake_config,  # type: ignore[arg-type]
        backend_manager=fake_backend_manager,  # type: ignore[arg-type]
    )
    assert resp.site == "OnlyFans"
    assert resp.direct_connection_included is True
    assert "proxy_capacity" in resp.model_dump()


