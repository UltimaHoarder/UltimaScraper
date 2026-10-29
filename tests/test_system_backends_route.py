"""Regression coverage for the system backends route."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ultima_scraper_backend.api.routes import system as system_routes


@pytest.mark.asyncio
async def test_get_all_backends_returns_local_response_without_redis() -> None:
    backend = SimpleNamespace(redis=None, instance_id="backend-a")

    response = await system_routes.get_all_backends(backend)

    assert response.success is True
    assert response.local_backend_id == "backend-a"
    assert response.backends == []
    assert response.total_backends == 0


@pytest.mark.asyncio
async def test_get_all_backends_hydrates_presence_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    mock_redis = AsyncMock()

    # Mock BackendRegistry
    monkeypatch.setattr(
        "ultima_scraper_backend.ultima_control.backend_registry.BackendRegistry.cleanup_dead_backends",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.ultima_control.backend_registry.BackendRegistry.get_all_backends",
        AsyncMock(return_value={}),
    )

    # Mock read_presence
    presence_data = [
        {
            "backend_id": "remote-node-1",
            "hostname": "container-hex-id",
            "cluster_id": "test-cluster",
            "api_url": None,
            "version": "0.1.0",
            "last_seen": "2026-10-25T18:00:00Z",
        }
    ]
    monkeypatch.setattr(
        "ultima_scraper_backend.cluster.read_presence",
        AsyncMock(return_value=presence_data),
    )

    # Mock WorkerRegistry
    mock_worker_info = SimpleNamespace(
        status="idle",
        current_task=None,
        tasks_completed=5,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.redis.worker_registry.WorkerRegistry.get_backend_workers_info",
        AsyncMock(return_value={"worker-abc": mock_worker_info}),
    )

    # Mock SystemStatsReporter
    mock_disk = SimpleNamespace(
        device="sda",
        mount_point="/mnt/storage",
        total_bytes=1000,
        used_bytes=400,
        free_bytes=600,
        percent_used=40.0,
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.ultima_control.system_stats_reporter.SystemStatsReporter.fetch_stats",
        AsyncMock(return_value=SimpleNamespace(disks=[mock_disk])),
    )

    backend = SimpleNamespace(redis=mock_redis, instance_id="local-backend")
    response = await system_routes.get_all_backends(backend)

    assert response.success is True
    assert response.total_backends == 1
    node = response.backends[0]
    assert node.backend_id == "remote-node-1"
    assert node.max_workers == 1
    assert len(node.workers) == 1
    assert node.workers[0].worker_id == "worker-abc"
    assert len(node.drives) == 1
    assert node.drives[0].path == "/mnt/storage"


@pytest.mark.asyncio
async def test_get_remote_settings_loads_from_database(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock
    from ultima_scraper_backend.api.routes import settings as settings_routes
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    cfg = UltimaScraperCollectionConfig()
    cfg.settings.worker_pool.size = 12
    cfg.settings.worker_pool.max_claimed_jobs = 30
    cfg.settings.hostname = "remote-node-1"

    row = SimpleNamespace(backend="global", id=1, version=5, updated_at=None)
    inv = SimpleNamespace(id=1, hostname="remote-node-1", settings_id=1)

    monkeypatch.setattr(
        settings_routes,
        "_load_backend_config",
        lambda backend_id: (cfg, row, inv),
    )

    backend = SimpleNamespace(redis=AsyncMock(is_connected=True), instance_id="local-backend")
    response = await settings_routes.get_remote_settings("remote-node-1", backend)

    assert response.error is None
    assert response.settings is not None
    assert response.settings.worker_pool.size == 12
    assert response.settings.worker_pool.max_claimed_jobs == 30
    assert response.settings.hostname == "remote-node-1"


@pytest.mark.asyncio
async def test_update_remote_settings_updates_and_publishes_worker_pool_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from unittest.mock import AsyncMock
    from ultima_scraper_backend.api.routes import settings as settings_routes
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    cfg = UltimaScraperCollectionConfig()
    cfg.settings.worker_pool.size = 10
    cfg.settings.worker_pool.max_claimed_jobs = 50
    cfg.settings.hostname = "alpha-node"

    row = SimpleNamespace(backend="alpha-node", id=2, version=3, updated_at=None)
    inv = SimpleNamespace(id=2, hostname="alpha-node", settings_id=2)

    monkeypatch.setattr(
        settings_routes,
        "_load_backend_config",
        lambda backend_id: (cfg, row, inv),
    )

    persisted_snapshot = SimpleNamespace(
        settings_id=2,
        settings_scope="alpha-node",
        version=4,
        updated_at="2026-10-25T19:00:00Z",
    )
    monkeypatch.setattr(
        settings_routes,
        "persist_config_snapshot",
        lambda config, expected_version=None: persisted_snapshot,
    )

    published_events = []
    mock_redis = AsyncMock(is_connected=True)
    async def mock_publish(channel, message):
        published_events.append((channel, json.loads(message)))
        return 1

    mock_redis.publish = mock_publish
    backend = SimpleNamespace(redis=mock_redis, instance_id="local-backend")

    update_req = settings_routes.SettingsUpdateRequest(
        worker_pool={"size": 4, "max_claimed_jobs": 20},
    )

    response = await settings_routes.update_remote_settings("alpha-node", update_req, backend)

    assert response.success is True
    assert "Settings updated successfully" in response.message

    # Check published events
    event_types = [msg["type"] for ch, msg in published_events]
    assert "settings_updated" in event_types
    assert "worker_pool_scale" in event_types

    scale_event = next(msg for ch, msg in published_events if msg["type"] == "worker_pool_scale")
    assert scale_event["target_size"] == 4
    assert scale_event["backend_id"] == "alpha-node"



@pytest.mark.asyncio
async def test_update_remote_settings_reports_local_conflict_as_readable_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException
    from ultima_scraper_backend.api.routes import settings as settings_routes

    async def conflicting_update(update, backend):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Settings have changed since you loaded them.",
                "current": {"infinite_loop": False},
                "current_version": 121,
            },
        )

    monkeypatch.setattr(settings_routes, "update_settings", conflicting_update)
    backend = SimpleNamespace(instance_id="alpha-node")
    update_req = settings_routes.SettingsUpdateRequest(expected_version=120)

    response = await settings_routes.update_remote_settings("alpha-node", update_req, backend)

    assert response.success is False
    assert response.message == (
        "Settings have changed since you loaded them. "
        "Reload to get version 121, then save again."
    )


def test_settings_update_rejects_unknown_format_tokens() -> None:
    from fastapi import HTTPException
    from ultima_scraper_backend.api.routes import settings as settings_routes
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    update = settings_routes.SettingsUpdateRequest(
        download_setup={
            "directory_format": "{site_name}/{user_username}/{user_date}",
            "filename_format": "{filename}.{ext}",
            "alt_directory_formats": ["{site_name}/{user_username}/{value}"],
        },
    )

    with pytest.raises(HTTPException) as raised:
        settings_routes._apply_settings_update_to_config(
            UltimaScraperCollectionConfig(), update
        )

    assert raised.value.status_code == 422
    assert raised.value.detail["message"] == (
        "{user_date} is not a valid token in download_setup.directory_format."
    )


def test_settings_update_accepts_current_and_legacy_format_tokens() -> None:
    from ultima_scraper_backend.api.routes import settings as settings_routes
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    update = settings_routes.SettingsUpdateRequest(
        download_setup={
            "directory_format": "{site_name}/{first_username_letter}/{user_username}/{content_type}/{content_value}/{media_type}",
            "filename_format": "{media_id}_{filename}.{ext}",
        },
        metadata_setup={"directory_format": "{site_name}/{first_letter}/{model_username}/Metadata"},
    )

    changed = settings_routes._apply_settings_update_to_config(
        UltimaScraperCollectionConfig(), update
    )

    assert changed == ["download_setup", "metadata_setup"]
