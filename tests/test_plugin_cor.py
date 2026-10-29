from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml


def _manifest(plugin_id: str = "cor-plugin") -> dict[str, object]:
    return {
        "manifest_schema_version": 1,
        "plugin_id": plugin_id,
        "plugin_version": "1.0.0",
        "display_name": "COR Plugin",
        "usr_compatibility": ">=0.1.0",
        "capabilities": ["events.read"],
        "event_subscriptions": [],
        "outbound_deliveries": [],
    }


def _write_manifest(plugins_dir: Path, plugin_id: str = "cor-plugin") -> None:
    plugin_dir = plugins_dir / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.yaml").write_text(
        yaml.safe_dump(_manifest(plugin_id), sort_keys=False),
        encoding="utf-8",
    )


def test_repository_imports_legacy_json_without_removing_it(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.repository import PluginRepository

    runtime_dir = tmp_path / ".runtime"
    runtime_dir.mkdir()
    enabled_path = runtime_dir / "enabled_plugins.json"
    enabled_path.write_text(json.dumps(["cor-plugin"]), encoding="utf-8")
    grants_path = runtime_dir / "capability_grants.json"
    grants_path.write_text(
        json.dumps({"version": 1, "grants": {"cor-plugin": ["events.read"]}}),
        encoding="utf-8",
    )

    repository = PluginRepository(
        runtime_dir / "plugin-runtime.sqlite3",
        legacy_runtime_dir=runtime_dir,
    )

    assert repository.list_enabled_plugins() == {"cor-plugin"}
    assert repository.get_grants("cor-plugin") == {"events.read"}
    assert enabled_path.exists()
    assert grants_path.exists()


def test_repository_refuses_to_downgrade_a_newer_schema(tmp_path: Path) -> None:
    import sqlite3

    from ultima_scraper_backend.plugin_system.repository import PluginRepository

    database_path = tmp_path / "runtime.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE plugin_repository_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO plugin_repository_meta(key, value) VALUES ('schema_version', '999')"
        )

    with pytest.raises(RuntimeError, match="newer than supported"):
        PluginRepository(database_path)

    with sqlite3.connect(database_path) as connection:
        stored_version = connection.execute(
            "SELECT value FROM plugin_repository_meta WHERE key = 'schema_version'"
        ).fetchone()
    assert stored_version == ("999",)


def test_malformed_legacy_json_remains_retryable(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.repository import PluginRepository

    runtime_dir = tmp_path / ".runtime"
    runtime_dir.mkdir()
    secrets_path = runtime_dir / "secrets.json"
    secrets_path.write_text("{not-json", encoding="utf-8")
    database_path = runtime_dir / "plugin-runtime.sqlite3"

    with pytest.raises(RuntimeError, match="must be repaired before retrying"):
        PluginRepository(database_path, legacy_runtime_dir=runtime_dir)
    assert secrets_path.read_text(encoding="utf-8") == "{not-json"

    secrets_path.write_text(json.dumps({"secrets": []}), encoding="utf-8")
    repository = PluginRepository(
        database_path,
        legacy_runtime_dir=runtime_dir,
    )
    assert repository.list_secret_payloads() == []


def test_repository_shares_state_between_platform_instances(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    _write_manifest(tmp_path)
    first = PluginPlatform(tmp_path)
    second = PluginPlatform(tmp_path)
    first.load_all()
    second.load_all()

    first.enable_plugin("cor-plugin")
    first.set_state("cor-plugin", "cursor", {"page": 3})

    assert second.repository.list_enabled_plugins() == {"cor-plugin"}
    assert second.state.get("cor-plugin", "cursor") == {"page": 3}
    assert second.capability_grants.get("cor-plugin") == {"events.read"}


def test_concurrent_workers_initialize_one_authoritative_secret(
    tmp_path: Path,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from ultima_scraper_backend.plugin_system.repository import PluginRepository
    from ultima_scraper_backend.plugin_system.secrets import SecretManager

    database_path = tmp_path / "runtime.sqlite3"
    first = SecretManager(repository=PluginRepository(database_path))
    second = SecretManager(repository=PluginRepository(database_path))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                manager.ensure_secret,
                "cor-plugin",
                "callback",
                "receive-event",
            )
            for manager in (first, second)
        ]
        for future in futures:
            future.result()

    first_value = first.get_raw_secret(
        "cor-plugin",
        "callback",
        "receive-event",
    )
    second_value = second.get_raw_secret(
        "cor-plugin",
        "callback",
        "receive-event",
    )
    assert first_value
    assert first_value == second_value


def test_rotating_one_secret_does_not_restore_another_workers_stale_cache(
    tmp_path: Path,
) -> None:
    from ultima_scraper_backend.plugin_system.repository import PluginRepository
    from ultima_scraper_backend.plugin_system.secrets import SecretManager

    database_path = tmp_path / "runtime.sqlite3"
    setup = SecretManager(repository=PluginRepository(database_path))
    setup.create_secret("first-plugin", "callback", "receive-event")
    setup.create_secret("second-plugin", "callback", "receive-event")

    first_worker = SecretManager(repository=PluginRepository(database_path))
    second_worker = SecretManager(repository=PluginRepository(database_path))
    first_rotated = first_worker.rotate_secret(
        "first-plugin",
        "callback",
        "receive-event",
    )
    second_rotated = second_worker.rotate_secret(
        "second-plugin",
        "callback",
        "receive-event",
    )

    authoritative = SecretManager(repository=PluginRepository(database_path))
    assert authoritative.get_raw_secret(
        "first-plugin",
        "callback",
        "receive-event",
    ) == first_rotated
    assert authoritative.get_raw_secret(
        "second-plugin",
        "callback",
        "receive-event",
    ) == second_rotated


def test_catalog_and_enabled_state_refresh_across_api_workers(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    first = PluginPlatform(tmp_path)
    second = PluginPlatform(tmp_path)
    first.load_all()
    second.load_all()

    first.create_plugin(_manifest())
    first.enable_plugin("cor-plugin")

    follower_view = second.get_plugin("cor-plugin")
    assert follower_view is not None
    assert follower_view["status"] == "enabled"

    manifest_path = tmp_path / "cor-plugin" / "manifest.yaml"
    manifest_yaml = manifest_path.read_text(encoding="utf-8")
    manifest_path.unlink()
    first.handle_filesystem_changes([], [], ["cor-plugin"])

    missing_view = second.get_plugin("cor-plugin")
    assert missing_view is not None
    assert missing_view["status"] == "missing"

    manifest_path.write_text(manifest_yaml, encoding="utf-8")
    first.handle_filesystem_changes(["cor-plugin"], [], [])
    restored_view = second.get_plugin("cor-plugin")
    assert restored_view is not None
    assert restored_view["status"] == "disabled"


def test_api_workers_do_not_clobber_each_others_enabled_plugins(
    tmp_path: Path,
) -> None:
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    _write_manifest(tmp_path, "first-plugin")
    _write_manifest(tmp_path, "second-plugin")
    first = PluginPlatform(tmp_path)
    second = PluginPlatform(tmp_path)
    first.load_all()
    second.load_all()

    first.enable_plugin("first-plugin")
    second.enable_plugin("second-plugin")

    assert first.repository.list_enabled_plugins() == {
        "first-plugin",
        "second-plugin",
    }

    first.disable_plugin("first-plugin")
    assert second.repository.list_enabled_plugins() == {"second-plugin"}


def test_missing_tombstone_and_data_survive_restart(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    _write_manifest(tmp_path)
    first = PluginPlatform(tmp_path)
    first.load_all()
    first.set_state("cor-plugin", "cursor", 11)

    (tmp_path / "cor-plugin" / "manifest.yaml").unlink()
    first.handle_filesystem_changes([], [], ["cor-plugin"])

    restarted = PluginPlatform(tmp_path)
    restarted.load_all()
    view = restarted.get_plugin("cor-plugin")
    assert view is not None
    assert view["status"] == "missing"
    assert restarted.state.get("cor-plugin", "cursor") == 11
    assert restarted.reload_plugin("cor-plugin")["status"] == "missing"
    assert restarted.disable_plugin("cor-plugin")["status"] == "missing"


def test_startup_discovers_manifest_removed_while_usr_was_offline(
    tmp_path: Path,
) -> None:
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    _write_manifest(tmp_path)
    before_shutdown = PluginPlatform(tmp_path)
    before_shutdown.load_all()
    before_shutdown.enable_plugin("cor-plugin")
    before_shutdown.set_state("cor-plugin", "cursor", 17)

    (tmp_path / "cor-plugin" / "manifest.yaml").unlink()

    restarted = PluginPlatform(tmp_path)
    restarted.load_all()
    view = restarted.get_plugin("cor-plugin")
    assert view is not None
    assert view["status"] == "missing"
    assert restarted.repository.list_enabled_plugins() == set()
    assert restarted.state.get("cor-plugin", "cursor") == 17
    # A missing placeholder has no manifest but must still be listable.
    assert [view["plugin_id"] for view in restarted.list_plugins()] == ["cor-plugin"]


def test_runtime_ownership_is_exclusive_and_recoverable(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.runtime_owner import (
        PluginRuntimeOwnership,
    )

    lock_path = tmp_path / "runtime-owner.lock"
    first = PluginRuntimeOwnership(lock_path)
    second = PluginRuntimeOwnership(lock_path)

    assert first.try_acquire() is True
    assert second.try_acquire() is False
    first.release()
    assert second.try_acquire() is True
    second.release()


@pytest.mark.asyncio
async def test_watcher_retries_a_change_when_callback_fails(tmp_path: Path) -> None:
    import asyncio

    from ultima_scraper_backend.plugin_system.watcher import PluginFileWatcher

    attempts = 0
    applied = asyncio.Event()

    async def on_change(
        added: list[str],
        modified: list[str],
        removed: list[str],
    ) -> None:
        nonlocal attempts
        assert added == ["retry-plugin"]
        assert modified == []
        assert removed == []
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient apply failure")
        applied.set()

    watcher = PluginFileWatcher(
        tmp_path,
        poll_interval=0.01,
        on_change=on_change,
    )
    watcher.start()
    try:
        await asyncio.sleep(0.03)
        _write_manifest(tmp_path, "retry-plugin")
        await asyncio.wait_for(applied.wait(), timeout=1)
    finally:
        await watcher.stop()

    assert attempts == 2


@pytest.mark.asyncio
async def test_runtime_coordinator_has_one_owner_and_fails_over(tmp_path: Path) -> None:
    import asyncio

    from ultima_scraper_backend.plugin_system.repository import PluginRepository
    from ultima_scraper_backend.plugin_system.runtime_owner import (
        PluginRuntimeCoordinator,
    )

    class FakePlatform:
        def __init__(self) -> None:
            self.repository = PluginRepository(tmp_path / ".runtime" / "runtime.sqlite3")
            self.starts = 0
            self.stops = 0
            self._runtime_started = False

        async def start_runtime(self) -> None:
            self.starts += 1
            self._runtime_started = True

        async def stop_runtime(self) -> None:
            self.stops += 1
            self._runtime_started = False

        def handle_filesystem_changes(
            self,
            added: list[str],
            modified: list[str],
            removed: list[str],
        ) -> dict[str, list[str]]:
            return {"loaded": [*added, *modified], "removed": removed}

    async def wait_until(predicate: Callable[[], bool]) -> None:
        for _ in range(100):
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("coordinator condition was not reached")

    first_platform = FakePlatform()
    second_platform = FakePlatform()
    first = PluginRuntimeCoordinator(
        first_platform,
        tmp_path,
        election_interval=0.01,
        watcher_interval=1,
    )
    second = PluginRuntimeCoordinator(
        second_platform,
        tmp_path,
        election_interval=0.01,
        watcher_interval=1,
    )
    first.start()
    second.start()
    try:
        await wait_until(lambda: (first.is_owner and first_platform.starts == 1) or (second.is_owner and second_platform.starts == 1))
        assert first.is_owner is not second.is_owner
        owner, follower = (first, second) if first.is_owner else (second, first)
        owner_platform = first_platform if first.is_owner else second_platform
        follower_platform = second_platform if first.is_owner else first_platform
        assert owner_platform.starts == 1
        assert follower_platform.starts == 0

        await owner.stop()
        await wait_until(lambda: follower.is_owner and follower_platform.starts == 1)
        assert follower_platform.starts == 1
        assert follower.platform.repository.get_runtime_owner()["active"] is True
    finally:
        await first.stop()
        await second.stop()


def test_runtime_owner_heartbeat_is_shared_between_workers(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.repository import PluginRepository

    repository = PluginRepository(tmp_path / "runtime.sqlite3")
    repository.claim_runtime_owner("worker-a", 123)

    owner = repository.get_runtime_owner()
    assert owner is not None
    assert owner["owner_id"] == "worker-a"
    assert owner["pid"] == 123
    assert owner["active"] is True
    assert repository.heartbeat_runtime_owner("worker-a") is True

    repository.release_runtime_owner("worker-a")
    assert repository.get_runtime_owner() is None


def test_follower_reports_shared_runtime_as_available(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    _write_manifest(tmp_path)
    owner = PluginPlatform(tmp_path)
    owner.load_all()
    owner.enable_plugin("cor-plugin")
    owner.repository.claim_runtime_owner("worker-a", 123)

    follower = PluginPlatform(tmp_path)
    follower.load_all()
    view = follower.get_plugin("cor-plugin")

    assert view is not None
    assert view["health_status"] == "healthy"
    assert follower.get_remote_delegation_overview()["runtime_started"] is True

    owner.repository.release_runtime_owner("worker-a")


def test_remote_status_static_route_precedes_plugin_id_route() -> None:
    from ultima_scraper_backend.plugin_system.api_routes import router

    paths = [route.path for route in router.routes]
    assert paths.index("/plugins/metadata") < paths.index("/plugins/{plugin_id}")
    assert paths.index("/plugins/remote-status") < paths.index("/plugins/{plugin_id}")


def test_only_exact_plugin_callback_path_bypasses_admin_auth() -> None:
    from ultima_scraper_backend.api.app import _uses_plugin_callback_auth

    valid = (
        "/api/v1/plugins/cor-plugin/remote-delegation/callbacks/receive-event"
    )
    assert _uses_plugin_callback_auth(valid) is True
    assert _uses_plugin_callback_auth(valid + "/extra") is False
    assert _uses_plugin_callback_auth("/api/v1/plugins/cor-plugin/enable") is False


def test_plugin_directory_resolves_to_repository_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.api.app import _resolve_plugins_dir

    monkeypatch.delenv("USR_PLUGINS_DIR", raising=False)
    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("USR_REPOSITORY_ROOT", str(repository_root))
    # The catalog is the plugins folder at the repository root; it ships empty.
    assert _resolve_plugins_dir() == repository_root / "plugins"


@pytest.mark.asyncio
async def test_callback_body_limit_applies_while_streaming() -> None:
    from fastapi import HTTPException
    from starlette.requests import Request

    from ultima_scraper_backend.plugin_system.api_routes import (
        MAX_PLUGIN_CALLBACK_BODY_BYTES,
        _read_bounded_callback_body,
    )

    chunks = iter(
        [
            {
                "type": "http.request",
                "body": b"x" * MAX_PLUGIN_CALLBACK_BODY_BYTES,
                "more_body": True,
            },
            {"type": "http.request", "body": b"x", "more_body": False},
        ]
    )

    async def receive() -> dict[str, object]:
        return next(chunks)

    request = Request(
        {"type": "http", "method": "POST", "path": "/callback", "headers": []},
        receive,
    )
    with pytest.raises(HTTPException) as exc_info:
        await _read_bounded_callback_body(request)
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_default_websocket_transport_uses_current_header_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.plugin_system import platform as platform_module

    captured: dict[str, object] = {}
    sentinel = object()

    async def connect(
        url: str,
        *,
        additional_headers: dict[str, str] | None = None,
        proxy: object = True,
    ) -> object:
        captured.update(
            url=url,
            additional_headers=additional_headers,
            proxy=proxy,
        )
        return sentinel

    monkeypatch.setattr(platform_module.websockets, "connect", connect)
    result = await platform_module._default_websocket_connect(
        "wss://example.test/socket",
        {"Authorization": "Bearer token"},
    )

    assert result is sentinel
    assert captured["additional_headers"] == {"Authorization": "Bearer token"}
    assert captured["proxy"] is None


def test_missing_manifest_quarantines_without_data_loss(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    _write_manifest(tmp_path)
    platform = PluginPlatform(tmp_path)
    platform.load_all()
    platform.set_state("cor-plugin", "cursor", 9)

    result = platform.handle_filesystem_changes([], [], ["cor-plugin"])

    assert result["removed"] == ["cor-plugin"]
    assert platform.get_plugin("cor-plugin")["status"] == "missing"  # type: ignore[index]
    assert platform.state.get("cor-plugin", "cursor") == 9


def test_explicit_purge_requires_disabled_plugin_and_confirmation(
    tmp_path: Path,
) -> None:
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    _write_manifest(tmp_path)
    platform = PluginPlatform(tmp_path)
    platform.load_all()
    platform.enable_plugin("cor-plugin")
    platform.set_state("cor-plugin", "cursor", 9)

    with pytest.raises(ValueError, match="Disable"):
        platform.purge_plugin_data("cor-plugin", "PURGE cor-plugin")

    platform.disable_plugin("cor-plugin")
    with pytest.raises(ValueError, match="exactly match"):
        platform.purge_plugin_data("cor-plugin", "cor-plugin")

    result = platform.purge_plugin_data("cor-plugin", "PURGE cor-plugin")
    assert result["status"] == "purged"
    assert result["manifest_retained"] is True
    assert platform.state.get("cor-plugin", "cursor") is None
    assert platform.capability_grants.has_record("cor-plugin") is False


@pytest.mark.asyncio
async def test_delivery_attempts_are_shared_through_repository(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.delivery import (
        EventDeliveryEngine,
        EventEnvelope,
    )
    from ultima_scraper_backend.plugin_system.repository import PluginRepository

    async def ok_post(
        url: str,
        payload: bytes,
        headers: dict[str, str],
        **_: object,
    ) -> int:
        return 204

    repository = PluginRepository(tmp_path / "runtime.sqlite3")
    engine = EventDeliveryEngine(http_post=ok_post, repository=repository)
    envelope = EventEnvelope(
        event_family="job.lifecycle",
        event_type="job.created",
        plugin_id="cor-plugin",
        body={"job_id": "job-1"},
    )

    await engine.deliver(
        envelope,
        url="https://example.invalid/hook",
        target_name="primary",
    )

    restored = EventDeliveryEngine(http_post=ok_post, repository=repository)
    assert restored.recent_deliveries("cor-plugin")[0]["status"] == "delivered"
    statuses = restored.list_endpoint_statuses("cor-plugin")
    assert statuses[0]["target_name"] == "primary"
    assert statuses[0]["consecutive_failures"] == 0
    assert statuses[0]["last_success_at"] is not None


@pytest.mark.asyncio
async def test_runtime_event_queue_does_not_wait_for_delivery(
    tmp_path: Path,
) -> None:
    import asyncio

    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_post(
        url: str,
        payload: bytes,
        headers: dict[str, str],
        **_: object,
    ) -> int:
        started.set()
        await release.wait()
        return 204

    manifest = _manifest()
    manifest["event_subscriptions"] = [
        {
            "event_family": "job.lifecycle",
            "event_types": ["job.created"],
            "delivery_target": "primary",
        }
    ]
    manifest["outbound_deliveries"] = [
        {"target_name": "primary", "url": "https://example.invalid/hook"}
    ]
    plugin_dir = tmp_path / "cor-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )

    platform = PluginPlatform(tmp_path, http_post=slow_post)
    platform.load_all()
    platform.enable_plugin("cor-plugin")
    await platform.start_runtime()
    try:
        await asyncio.wait_for(
            platform._emit_event(
                event_family="job.lifecycle",
                event_type="job.created",
                body={"job_id": "job-1"},
            ),
            timeout=0.1,
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        release.set()
        await asyncio.wait_for(platform._delivery_queue.join(), timeout=1)
    finally:
        release.set()
        await platform.stop_runtime()


def test_private_outbound_networks_require_manifest_opt_in() -> None:
    from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict
    from ultima_scraper_backend.plugin_system.outbound_policy import (
        validate_plugin_http_url,
    )

    manifest = load_manifest_from_dict(_manifest())
    with pytest.raises(ValueError, match="Target IP is not allowed"):
        validate_plugin_http_url(manifest, "https://127.0.0.1:8443/hook")
    with pytest.raises(ValueError, match="Cleartext outbound URL blocked"):
        validate_plugin_http_url(manifest, "http://example.com/hook")

    allowed_data = _manifest()
    allowed_data["operational_policy"] = {
        "allow_private_networks": True,
        "allow_insecure_http": True,
        "allowed_outbound_domains": ["localhost"],
    }
    allowed_manifest = load_manifest_from_dict(allowed_data)
    validate_plugin_http_url(allowed_manifest, "http://localhost:8080/hook")
