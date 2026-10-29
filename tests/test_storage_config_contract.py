from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import ultima_scraper_backend.api.routes.settings as settings_routes
import ultima_scraper_backend.api.routes.system as system_routes
import ultima_scraper_backend.storage_config_propagation as propagation_module
import ultima_scraper_backend.workers.worker_pool as worker_pool_module
from fastapi import HTTPException
from ultima_scraper_backend.api.routes.settings import SettingsUpdateRequest
from ultima_scraper_backend.api.routes.system import (
    DirectoryConfigRequest,
    update_directory_config,
)
from ultima_scraper_backend.config import (
    DownloadPathSetup,
    Drive,
    UltimaScraperCollectionConfig,
)
from ultima_scraper_backend.config_settings_sync import (
    CanonicalStorageConfigSnapshot,
    ConfigVersionConflict,
    PersistedConfigSnapshot,
)
from ultima_scraper_backend.job_system.drive_selection import select_user_destination
from ultima_scraper_backend.storage_config_propagation import propagate_storage_config


def _config_for_backend(
    backend_id: str,
    *,
    directory: Path | None = None,
) -> UltimaScraperCollectionConfig:
    config = UltimaScraperCollectionConfig()
    config.settings.backend.backend_id = backend_id
    if directory is not None:
        config.settings.download_setup = DownloadPathSetup(
            drives=[Drive(directories=[directory])]
        )
    return config


@pytest.mark.asyncio
async def test_directory_update_rejects_other_backend_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "downloads"
    config = _config_for_backend("backend-local", directory=directory)
    persist = MagicMock()
    propagate = AsyncMock()
    monkeypatch.setattr(system_routes, "_persist_storage_config", persist)
    monkeypatch.setattr(system_routes, "propagate_storage_config", propagate)

    response = await update_directory_config(
        DirectoryConfigRequest(
            directory_path=str(directory),
            setup_type="download",
            store=False,
            target_backend_id="backend-remote",
            expected_version=3,
        ),
        config,
        SimpleNamespace(instance_id="backend-local"),
    )

    assert response.success is False
    assert "backend-remote" in response.message
    assert config.settings.download_setup.drives[0].store is True
    persist.assert_not_called()
    propagate.assert_not_awaited()


@pytest.mark.asyncio
async def test_directory_update_conflict_does_not_mutate_or_propagate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "downloads"
    config = _config_for_backend("backend-local", directory=directory)
    candidate_store_values: list[bool] = []

    def conflict(candidate: UltimaScraperCollectionConfig, **_kwargs: object) -> None:
        candidate_store_values.append(candidate.settings.download_setup.drives[0].store)
        raise ConfigVersionConflict(current_version=8)

    propagate = AsyncMock()
    monkeypatch.setattr(system_routes, "_persist_storage_config", conflict)
    monkeypatch.setattr(system_routes, "propagate_storage_config", propagate)

    with pytest.raises(HTTPException) as exc_info:
        await update_directory_config(
            DirectoryConfigRequest(
                directory_path=str(directory),
                setup_type="download",
                store=False,
                target_backend_id="backend-local",
                expected_version=7,
            ),
            config,
            SimpleNamespace(instance_id="backend-local"),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["current_version"] == 8
    assert candidate_store_values == [False]
    assert config.settings.download_setup.drives[0].store is True
    propagate.assert_not_awaited()


def test_storage_save_persists_canonical_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config_for_backend("backend-a", directory=tmp_path / "downloads")
    snapshot = PersistedConfigSnapshot(
        settings_id=11,
        settings_scope="backend-a",
        version=8,
        updated_at=None,
        previous_value="encrypted-previous-config",
    )
    persist = MagicMock(return_value=snapshot)
    monkeypatch.setattr(
        system_routes,
        "persist_config_snapshot",
        persist,
    )

    result = system_routes._persist_storage_config(
        config,
        setup_type="download",
        expected_version=7,
    )

    assert result is snapshot
    persist.assert_called_once_with(config, expected_version=7)


class _SettingsRequest:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    async def json(self) -> dict[str, object]:
        return self.payload


@pytest.mark.asyncio
async def test_global_storage_endpoint_saves_the_canonical_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config_for_backend("backend-a", directory=tmp_path / "downloads")
    snapshot = PersistedConfigSnapshot(
        settings_id=21,
        settings_scope="backend-a",
        version=8,
        updated_at=None,
        previous_value=config.model_dump_json(),
    )
    update = SettingsUpdateRequest(
        download_setup=config.settings.download_setup.model_copy(deep=True),
        expected_version=7,
    )
    response = SimpleNamespace(storage_propagation=None)
    persist = MagicMock(return_value=snapshot)
    monkeypatch.setattr(
        settings_routes,
        "persist_config_snapshot",
        persist,
    )
    monkeypatch.setattr(
        UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        MagicMock(return_value=config),
    )
    monkeypatch.setattr(
        settings_routes,
        "propagate_storage_config",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(settings_routes, "publish_ws_event", AsyncMock())
    monkeypatch.setattr(
        settings_routes,
        "_publish_settings_updated_event",
        AsyncMock(),
    )
    monkeypatch.setattr(
        settings_routes,
        "_config_to_response",
        MagicMock(return_value=response),
    )

    result = await settings_routes.update_settings(
        update,
        SimpleNamespace(redis=None, instance_id="backend-a"),
    )

    assert result is response
    persist.assert_called_once_with(config, expected_version=7)


AckBuilder = Callable[[dict[str, Any]], dict[str, Any]]


def _ack(
    event: dict[str, Any],
    worker_id: str,
    *,
    success: bool = True,
    **overrides: object,
) -> dict[str, Any]:
    acknowledgement: dict[str, Any] = {
        "type": "storage_config_reload_ack",
        "target_backend_id": event["target_backend_id"],
        "settings_scope": event["settings_scope"],
        "config_version": event["config_version"],
        "worker_id": worker_id,
        "request_id": event["request_id"],
        "revision": event["revision"],
        "success": success,
    }
    acknowledgement.update(overrides)
    return acknowledgement


class _FakePubSub:
    def __init__(self, redis: _FakeRedis, builders: list[AckBuilder]) -> None:
        self.redis = redis
        self.builders = list(builders)
        self.subscribed = False
        self.closed = False

    async def subscribe(self, _channel: str) -> None:
        self.subscribed = True

    async def get_message(self, **_kwargs: object) -> dict[str, object] | None:
        if not self.builders:
            return None
        event = self.redis.published[-1]
        acknowledgement = self.builders.pop(0)(event)
        return {
            "type": "message",
            "data": json.dumps(acknowledgement),
        }

    async def unsubscribe(self, _channel: str) -> None:
        self.subscribed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeRedisClient:
    def __init__(self, redis: _FakeRedis, builders: list[AckBuilder]) -> None:
        self._pubsub = _FakePubSub(redis, builders)

    def pubsub(self) -> _FakePubSub:
        return self._pubsub


class _FakeRedis:
    def __init__(self, builders: list[AckBuilder] | None = None) -> None:
        self.is_connected = True
        self.published: list[dict[str, Any]] = []
        self.client = _FakeRedisClient(self, builders or [])

    async def publish(self, _channel: str, payload: str) -> int:
        self.published.append(json.loads(payload))
        return 1


def _backend_with_redis(redis: _FakeRedis | None) -> SimpleNamespace:
    return SimpleNamespace(instance_id="backend-a", redis=redis)


@pytest.mark.asyncio
async def test_propagation_accepts_only_matching_acknowledgements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config_for_backend("backend-a", directory=tmp_path / "downloads")
    redis = _FakeRedis(
        [
            lambda event: _ack(event, "worker-a", request_id="wrong-request"),
            lambda event: _ack(event, "worker-a", revision="wrong-revision"),
            lambda event: _ack(event, "worker-a", config_version=99),
            lambda event: _ack(event, "worker-a", target_backend_id="backend-b"),
            lambda event: _ack(event, "unknown-worker"),
            lambda event: _ack(event, "worker-a"),
            lambda event: _ack(event, "worker-b"),
        ]
    )
    monkeypatch.setattr(
        propagation_module.WorkerRegistry,
        "get_backend_workers_info",
        AsyncMock(return_value={"worker-a": object(), "worker-b": object()}),
    )

    result = await propagate_storage_config(
        _backend_with_redis(redis),
        config,
        changed_sections={"download_setup"},
        config_version=7,
        timeout_seconds=0.1,
    )

    assert result.status == "acknowledged"
    assert result.target_backend_id == "backend-a"
    assert result.config_version == 7
    assert result.acknowledged_workers == ["worker-a", "worker-b"]
    assert result.failed_workers == []
    event = redis.published[0]
    assert event["target_backend_id"] == "backend-a"
    assert event["config_version"] == 7
    assert event["changed_fields"] == ["download_setup"]


@pytest.mark.asyncio
async def test_propagation_reports_partial_and_pending_statuses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config_for_backend("backend-a", directory=tmp_path / "downloads")
    workers = {"worker-a": object(), "worker-b": object()}
    monkeypatch.setattr(
        propagation_module.WorkerRegistry,
        "get_backend_workers_info",
        AsyncMock(return_value=workers),
    )

    partial_redis = _FakeRedis(
        [
            lambda event: _ack(event, "worker-a"),
            lambda event: _ack(event, "worker-b", success=False),
        ]
    )
    partial = await propagate_storage_config(
        _backend_with_redis(partial_redis),
        config,
        changed_sections={"download_setup"},
        config_version=8,
        timeout_seconds=0.1,
    )

    pending_redis = _FakeRedis()
    pending = await propagate_storage_config(
        _backend_with_redis(pending_redis),
        config,
        changed_sections={"download_setup"},
        config_version=9,
        timeout_seconds=0.1,
    )

    assert partial.status == "partial"
    assert partial.acknowledged_workers == ["worker-a"]
    assert partial.failed_workers == ["worker-b"]
    assert pending.status == "pending"
    assert pending.acknowledged_workers == []
    assert pending.failed_workers == []


@pytest.mark.asyncio
async def test_propagation_reports_no_workers_and_local_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config_for_backend("backend-a", directory=tmp_path / "downloads")
    registry_lookup = AsyncMock(return_value={})
    monkeypatch.setattr(
        propagation_module.WorkerRegistry,
        "get_backend_workers_info",
        registry_lookup,
    )
    redis = _FakeRedis()

    no_workers = await propagate_storage_config(
        _backend_with_redis(redis),
        config,
        changed_sections={"download_setup"},
        config_version=10,
    )
    local_only = await propagate_storage_config(
        _backend_with_redis(None),
        config,
        changed_sections={"download_setup"},
        config_version=11,
    )

    assert no_workers.status == "no_workers"
    assert len(redis.published) == 1
    assert local_only.status == "local_only"
    assert local_only.expected_workers == []
    registry_lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_propagation_does_not_report_no_workers_when_registry_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config_for_backend("backend-a", directory=tmp_path / "downloads")
    monkeypatch.setattr(
        propagation_module.WorkerRegistry,
        "get_backend_workers_info",
        AsyncMock(side_effect=RuntimeError("registry unavailable")),
    )
    redis = _FakeRedis()

    result = await propagate_storage_config(
        _backend_with_redis(redis),
        config,
        changed_sections={"download_setup"},
        config_version=12,
    )

    assert result.status == "pending"
    assert "registry could not be read" in result.message
    assert len(redis.published) == 1


@pytest.mark.asyncio
async def test_propagation_publish_and_close_failures_do_not_fail_saved_update(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config_for_backend("backend-a", directory=tmp_path / "downloads")

    class FailingPublishRedis(_FakeRedis):
        async def publish(self, _channel: str, payload: str) -> int:
            raise RuntimeError(f"publish failed for {payload[:12]}")

    monkeypatch.setattr(
        propagation_module.WorkerRegistry,
        "get_backend_workers_info",
        AsyncMock(return_value={}),
    )
    publish_failure = await propagate_storage_config(
        _backend_with_redis(FailingPublishRedis()),
        config,
        changed_sections={"download_setup"},
        config_version=13,
    )

    redis = _FakeRedis([lambda event: _ack(event, "worker-a")])
    redis.client._pubsub.aclose = AsyncMock(side_effect=RuntimeError("close failed"))
    monkeypatch.setattr(
        propagation_module.WorkerRegistry,
        "get_backend_workers_info",
        AsyncMock(return_value={"worker-a": object()}),
    )
    close_failure = await propagate_storage_config(
        _backend_with_redis(redis),
        config,
        changed_sections={"download_setup"},
        config_version=14,
        timeout_seconds=0.1,
    )

    assert publish_failure.status == "pending"
    assert "could not be published" in publish_failure.message
    assert close_failure.status == "acknowledged"
    assert close_failure.acknowledged_workers == ["worker-a"]


class _PublishOnlyRedis:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(self, _channel: str, payload: str) -> int:
        self.published.append(json.loads(payload))
        return 1


@pytest.mark.asyncio
async def test_worker_rejects_stale_version_without_reapplying(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config_for_backend("backend-a", directory=tmp_path / "old")
    new_setup = DownloadPathSetup(
        drives=[Drive(store=False, directories=[tmp_path / "new"])]
    )
    payload: dict[str, object] = {"download_setup": new_setup.model_dump(mode="json")}
    event = {
        "type": "storage_config_updated",
        "target_backend_id": "backend-a",
        "settings_scope": "backend-a",
        "config_version": 4,
        "worker_id": "worker-a",
        "request_id": "request-4",
        "revision": worker_pool_module.Worker._storage_event_revision(payload),
        **payload,
    }

    worker = worker_pool_module.Worker.__new__(worker_pool_module.Worker)
    worker.worker_id = "worker-a"
    worker.backend_id = "backend-a"
    worker.config = config
    worker.redis = _PublishOnlyRedis()
    worker._config_reload_lock = asyncio.Lock()
    worker._settings_last_applied_versions = {"backend-a": 5}
    worker._settings_last_applied_storage_revisions = {}
    worker._install_runtime_storage_config = AsyncMock()
    canonical_payload = {
        "download_setup": config.settings.download_setup.model_dump(mode="json")
    }
    monkeypatch.setattr(
        worker_pool_module,
        "get_canonical_storage_config_snapshot",
        lambda _scope, _sections: CanonicalStorageConfigSnapshot(
            version=5,
            payload=canonical_payload,
        ),
    )

    await worker._apply_storage_config_update_event(event)

    worker._install_runtime_storage_config.assert_not_awaited()
    assert worker.config is config
    assert worker.redis.published == [
        {
            "type": "storage_config_reload_ack",
            "target_backend_id": "backend-a",
            "settings_scope": "backend-a",
            "config_version": 4,
            "worker_id": "worker-a",
            "request_id": "request-4",
            "revision": event["revision"],
            "success": False,
            "error": "stale storage config version 4; canonical version is 5",
        }
    ]


@pytest.mark.asyncio
async def test_restarted_worker_rejects_event_older_than_canonical_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config_for_backend("backend-a", directory=tmp_path / "current")
    stale_setup = DownloadPathSetup(
        drives=[Drive(store=False, directories=[tmp_path / "stale"])]
    )
    payload: dict[str, object] = {"download_setup": stale_setup.model_dump(mode="json")}
    event = {
        "type": "storage_config_updated",
        "target_backend_id": "backend-a",
        "settings_scope": "backend-a",
        "config_version": 4,
        "request_id": "request-4",
        "revision": worker_pool_module.Worker._storage_event_revision(payload),
        **payload,
    }

    worker = worker_pool_module.Worker.__new__(worker_pool_module.Worker)
    worker.worker_id = "worker-a"
    worker.backend_id = "backend-a"
    worker.config = config
    worker.redis = _PublishOnlyRedis()
    worker._config_reload_lock = asyncio.Lock()
    worker._settings_last_applied_versions = {}
    worker._settings_last_applied_storage_revisions = {}
    worker._install_runtime_storage_config = AsyncMock()
    canonical_payload = {
        "download_setup": config.settings.download_setup.model_dump(mode="json")
    }
    monkeypatch.setattr(
        worker_pool_module,
        "get_canonical_storage_config_snapshot",
        lambda _scope, _sections: CanonicalStorageConfigSnapshot(
            version=5,
            payload=canonical_payload,
        ),
    )

    await worker._apply_storage_config_update_event(event)

    worker._install_runtime_storage_config.assert_not_awaited()
    assert worker.config is config
    assert worker.redis.published[0]["success"] is False
    assert worker.redis.published[0]["error"] == (
        "stale storage config version 4; canonical version is 5"
    )


@pytest.mark.asyncio
async def test_worker_acknowledges_only_after_replacement_state_is_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_config = _config_for_backend("backend-a", directory=tmp_path / "old")
    new_setup = DownloadPathSetup(drives=[Drive(directories=[tmp_path / "new"])])
    payload: dict[str, object] = {"download_setup": new_setup.model_dump(mode="json")}
    event = {
        "type": "storage_config_updated",
        "target_backend_id": "backend-a",
        "settings_scope": "backend-a",
        "config_version": 7,
        "request_id": "request-7",
        "revision": worker_pool_module.Worker._storage_event_revision(payload),
        **payload,
    }
    entered_install = asyncio.Event()
    release_install = asyncio.Event()

    worker = worker_pool_module.Worker.__new__(worker_pool_module.Worker)
    worker.worker_id = "worker-a"
    worker.backend_id = "backend-a"
    worker.config = old_config
    worker.redis = _PublishOnlyRedis()
    worker._config_reload_lock = asyncio.Lock()
    worker._settings_last_applied_versions = {}
    worker._settings_last_applied_storage_revisions = {}

    async def install(fresh_config: UltimaScraperCollectionConfig) -> None:
        entered_install.set()
        await release_install.wait()
        worker.config = fresh_config

    worker._install_runtime_storage_config = install
    monkeypatch.setattr(
        worker_pool_module,
        "get_canonical_storage_config_snapshot",
        lambda _scope, _sections: CanonicalStorageConfigSnapshot(
            version=7,
            payload=payload,
        ),
    )
    monkeypatch.setattr(
        UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        MagicMock(return_value=old_config.model_copy(deep=True)),
    )

    apply_task = asyncio.create_task(worker._apply_storage_config_update_event(event))
    await asyncio.wait_for(entered_install.wait(), timeout=1)
    assert worker.redis.published == []

    release_install.set()
    await asyncio.wait_for(apply_task, timeout=1)

    assert worker.config.settings.download_setup == new_setup
    assert worker.redis.published[0]["success"] is True
    assert worker.redis.published[0]["revision"] == event["revision"]


@pytest.mark.asyncio
async def test_worker_accepts_older_event_when_latest_canonical_storage_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_config = _config_for_backend("backend-a", directory=tmp_path / "old")
    current_setup = DownloadPathSetup(
        drives=[Drive(directories=[tmp_path / "current"])]
    )
    payload: dict[str, object] = {
        "download_setup": current_setup.model_dump(mode="json")
    }
    event = {
        "type": "storage_config_updated",
        "target_backend_id": "backend-a",
        "settings_scope": "backend-a",
        "config_version": 8,
        "request_id": "request-8",
        "revision": worker_pool_module.Worker._storage_event_revision(payload),
        **payload,
    }

    worker = worker_pool_module.Worker.__new__(worker_pool_module.Worker)
    worker.worker_id = "worker-a"
    worker.backend_id = "backend-a"
    worker.config = old_config
    worker.redis = _PublishOnlyRedis()
    worker._config_reload_lock = asyncio.Lock()
    worker._settings_last_applied_versions = {}
    worker._settings_last_applied_storage_revisions = {}

    async def install(fresh_config: UltimaScraperCollectionConfig) -> None:
        worker.config = fresh_config

    worker._install_runtime_storage_config = install
    monkeypatch.setattr(
        worker_pool_module,
        "get_canonical_storage_config_snapshot",
        lambda _scope, _sections: CanonicalStorageConfigSnapshot(
            version=9,
            payload=payload,
        ),
    )
    monkeypatch.setattr(
        UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        MagicMock(return_value=old_config.model_copy(deep=True)),
    )

    await worker._apply_storage_config_update_event(event)

    assert worker.config.settings.download_setup == current_setup
    assert worker._settings_last_applied_versions["backend-a"] == 8
    assert worker.redis.published[0]["success"] is True


@pytest.mark.asyncio
async def test_worker_swaps_config_only_after_new_user_manager_is_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_root = tmp_path / "old-target"
    new_root = tmp_path / "new-target"
    old_root.mkdir()
    new_root.mkdir()
    old_config = _config_for_backend("backend-a", directory=old_root)
    new_config = _config_for_backend("backend-a", directory=new_root)
    old_manager = SimpleNamespace(config=old_config, marker="old")
    entered_population = asyncio.Event()
    release_population = asyncio.Event()

    worker = worker_pool_module.Worker.__new__(worker_pool_module.Worker)
    worker.config = old_config
    worker.user_manager = old_manager

    async def populate(
        new_manager: SimpleNamespace,
        *,
        worker_count: int | None = None,
    ) -> bool:
        assert worker_count is None
        assert worker.config is old_config
        assert worker.user_manager is old_manager
        assert new_manager.config is new_config
        entered_population.set()
        await release_population.wait()
        return True

    worker._populate_user_manager = populate
    monkeypatch.setattr(
        worker_pool_module,
        "UserManager",
        lambda config: SimpleNamespace(config=config, marker="new"),
    )

    install_task = asyncio.create_task(
        worker._install_runtime_storage_config(new_config)
    )
    await asyncio.wait_for(entered_population.wait(), timeout=1)

    old_task_context = (worker.config, worker.user_manager)
    assert old_task_context == (old_config, old_manager)
    old_task_destination = select_user_destination(
        user_id=123,
        usernames=["performer"],
        site_name="onlyfans",
        user_manager=old_task_context[1],
        config=old_task_context[0],
        ignore_space_requirements=True,
    )

    release_population.set()
    await asyncio.wait_for(install_task, timeout=1)

    assert old_task_context == (old_config, old_manager)
    assert worker.config is new_config
    assert worker.user_manager.config is new_config
    assert worker.user_manager.marker == "new"
    new_task_destination = select_user_destination(
        user_id=123,
        usernames=["performer"],
        site_name="onlyfans",
        user_manager=worker.user_manager,
        config=worker.config,
        ignore_space_requirements=True,
    )
    assert old_task_destination.root.resolve() == old_root.resolve()
    assert new_task_destination.root.resolve() == new_root.resolve()
