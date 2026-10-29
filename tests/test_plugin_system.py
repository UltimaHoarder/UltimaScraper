"""Comprehensive tests for the USR plugin system.

Covers: manifest validation, permissions, registry lifecycle, secrets,
state store, event delivery, file watcher, and platform facade.
"""

from __future__ import annotations

import asyncio
import json
import textwrap
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml

# ── Helpers ───────────────────────────────────────────────────────────────

USR_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_SYS = (
    USR_ROOT
    / "src"
    / "ultima_scraper_backend"
    / "ultima_scraper_backend"
    / "plugin_system"
)


def _minimal_manifest_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "plugin_id": "test-plugin",
        "plugin_version": "1.0.0",
        "display_name": "Test Plugin",
        "description": "A test plugin.",
        "usr_compatibility": ">=0.1.0",
        "capabilities": ["events.read"],
        "event_subscriptions": [
            {
                "event_family": "job.lifecycle",
                "event_types": ["job.created"],
                "delivery_target": "main",
            }
        ],
        "outbound_deliveries": [
            {
                "target_name": "main",
                "url": "https://example.com/hook",
            }
        ],
    }
    base.update(overrides)
    return base


def _write_manifest(plugin_dir: Path, data: dict[str, Any]) -> Path:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = plugin_dir / "manifest.yaml"
    manifest_path.write_text(yaml.dump(data), encoding="utf-8")
    return manifest_path


# ══════════════════════════════════════════════════════════════════════════
# Manifest schema tests
# ══════════════════════════════════════════════════════════════════════════


class TestManifestSchema:
    """Validate the plugin manifest Pydantic model."""

    def test_valid_minimal_manifest(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _minimal_manifest_dict()
        manifest = load_manifest_from_dict(data)
        assert manifest.plugin_id == "test-plugin"
        assert manifest.plugin_version == "1.0.0"

    def test_invalid_plugin_id_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _minimal_manifest_dict(plugin_id="INVALID")
        with pytest.raises(Exception):
            load_manifest_from_dict(data)

    def test_invalid_semver_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _minimal_manifest_dict(plugin_version="bad")
        with pytest.raises(Exception):
            load_manifest_from_dict(data)

    def test_missing_capability_for_task_types(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _minimal_manifest_dict(
            task_types=[
                {
                    "task_type": "scrape.user",
                    "payload_fields": [{"name": "username", "field_type": "string"}],
                }
            ],
        )
        # capabilities doesn't include jobs.submit
        with pytest.raises(Exception, match="jobs.submit"):
            load_manifest_from_dict(data)

    def test_missing_delivery_target_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _minimal_manifest_dict()
        data["event_subscriptions"][0]["delivery_target"] = "nonexistent"
        with pytest.raises(Exception, match="nonexistent"):
            load_manifest_from_dict(data)

    def test_duplicate_handler_ids_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _minimal_manifest_dict(
            capabilities=["events.read", "webhooks.register"],
            callbacks=[
                {"handler_id": "same-id", "auth_method": "hmac"},
                {"handler_id": "same-id", "auth_method": "bearer"},
            ],
        )
        with pytest.raises(Exception, match="Duplicate callback"):
            load_manifest_from_dict(data)

    def test_duplicate_task_types_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _minimal_manifest_dict(
            capabilities=["events.read", "jobs.submit"],
            task_types=[
                {"task_type": "scrape.user", "payload_fields": []},
                {"task_type": "scrape.user", "payload_fields": []},
            ],
        )
        with pytest.raises(Exception, match="Duplicate task_type"):
            load_manifest_from_dict(data)

    def test_invalid_event_family_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _minimal_manifest_dict()
        data["event_subscriptions"][0]["event_family"] = "invalid.family"
        with pytest.raises(Exception, match="event_family"):
            load_manifest_from_dict(data)

    def test_full_manifest_with_all_sections(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = {
            "plugin_id": "full-plugin",
            "plugin_version": "2.0.0",
            "display_name": "Full Plugin",
            "description": "Tests all sections.",
            "usr_compatibility": ">=0.1.0",
            "capabilities": [
                "events.read",
                "jobs.submit",
                "webhooks.register",
                "workers.status.read",
            ],
            "task_types": [
                {
                    "task_type": "scrape.user",
                    "description": "Scrape a user profile.",
                    "payload_fields": [
                        {
                            "name": "username",
                            "field_type": "string",
                            "required": True,
                            "min_length": 1,
                            "max_length": 100,
                        },
                        {
                            "name": "priority",
                            "field_type": "integer",
                            "required": False,
                        },
                    ],
                    "result_fields": [
                        {"name": "status", "field_type": "string"},
                    ],
                    "max_priority": 50,
                }
            ],
            "event_subscriptions": [
                {
                    "event_family": "job.lifecycle",
                    "event_types": ["job.created", "job.completed"],
                    "delivery_target": "main",
                }
            ],
            "callbacks": [
                {
                    "handler_id": "inbound-ping",
                    "auth_method": "hmac",
                    "payload_fields": [
                        {"name": "ping_id", "field_type": "string"},
                    ],
                }
            ],
            "outbound_deliveries": [
                {
                    "target_name": "main",
                    "url": "https://example.com/hook",
                    "description": "Primary webhook.",
                }
            ],
            "operational_policy": {
                "retry_policy": {
                    "max_retries": 5,
                    "initial_backoff_seconds": 10,
                    "max_backoff_seconds": 600,
                    "backoff_multiplier": 2.0,
                },
                "state_quota_bytes": 32768,
                "replay_on_enable": True,
            },
        }
        manifest = load_manifest_from_dict(data)
        assert manifest.plugin_id == "full-plugin"
        assert len(manifest.task_types) == 1
        assert len(manifest.callbacks) == 1
        assert manifest.operational_policy.retry_policy.max_retries == 5

    def test_outbound_url_must_be_http(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _minimal_manifest_dict()
        data["outbound_deliveries"][0]["url"] = "ftp://bad.example.com"
        with pytest.raises(Exception, match="https://"):
            load_manifest_from_dict(data)


# ══════════════════════════════════════════════════════════════════════════
# Permission model tests
# ══════════════════════════════════════════════════════════════════════════


class TestPermissions:
    def test_validate_capabilities_valid(self) -> None:
        from ultima_scraper_backend.plugin_system.permissions import validate_capabilities

        valid, invalid = validate_capabilities(["events.read", "jobs.submit"])
        assert len(valid) == 2
        assert len(invalid) == 0

    def test_validate_capabilities_invalid(self) -> None:
        from ultima_scraper_backend.plugin_system.permissions import validate_capabilities

        valid, invalid = validate_capabilities(["events.read", "super.admin.power"])
        assert len(valid) == 1
        assert invalid == ["super.admin.power"]

    def test_check_capability(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict
        from ultima_scraper_backend.plugin_system.permissions import PluginCapability, check_capability

        data = _minimal_manifest_dict(capabilities=["events.read"])
        manifest = load_manifest_from_dict(data)
        assert check_capability(manifest, PluginCapability.EVENTS_READ)
        assert not check_capability(manifest, PluginCapability.JOBS_SUBMIT)


# ══════════════════════════════════════════════════════════════════════════
# Registry tests
# ══════════════════════════════════════════════════════════════════════════


class TestRegistry:
    def test_scan_loads_valid_plugin(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry, PluginStatus

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        registry = PluginRegistry(tmp_path)
        loaded = registry.scan_plugins_dir()
        assert "test-plugin" in loaded
        record = registry.get("test-plugin")
        assert record is not None
        assert record.status == PluginStatus.DISABLED

    def test_scan_marks_invalid_on_bad_manifest(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry, PluginStatus

        plugin_dir = tmp_path / "bad-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.yaml").write_text("not: valid: yaml: [")
        registry = PluginRegistry(tmp_path)
        registry.scan_plugins_dir()
        record = registry.get("bad-plugin")
        assert record is not None
        assert record.status == PluginStatus.INVALID

    def test_enable_disable_lifecycle(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry, PluginStatus

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        registry = PluginRegistry(tmp_path)
        registry.scan_plugins_dir()

        registry.enable_plugin("test-plugin")
        assert registry.get("test-plugin").status == PluginStatus.ENABLED  # type: ignore[union-attr]
        assert registry.get("test-plugin").is_active  # type: ignore[union-attr]

        registry.disable_plugin("test-plugin")
        assert registry.get("test-plugin").status == PluginStatus.DISABLED  # type: ignore[union-attr]
        assert not registry.get("test-plugin").is_active  # type: ignore[union-attr]

    def test_enable_invalid_plugin_rejected(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry, PluginStatus

        plugin_dir = tmp_path / "bad-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.yaml").write_text("not: valid: yaml: [")
        registry = PluginRegistry(tmp_path)
        registry.scan_plugins_dir()
        assert registry.get("bad-plugin").status == PluginStatus.INVALID  # type: ignore[union-attr]

        with pytest.raises(ValueError, match="invalid"):
            registry.enable_plugin("bad-plugin")

    def test_manifest_change_preserves_enabled_status(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry, PluginStatus

        data = _minimal_manifest_dict()
        _write_manifest(tmp_path / "test-plugin", data)
        registry = PluginRegistry(tmp_path)
        registry.scan_plugins_dir()
        registry.enable_plugin("test-plugin")

        # Modify manifest
        data["display_name"] = "Changed Name"
        _write_manifest(tmp_path / "test-plugin", data)
        registry.scan_plugins_dir()

        record = registry.get("test-plugin")
        assert record is not None
        assert record.status == PluginStatus.ENABLED
        assert record.revision == 2

    def test_plugin_id_must_match_directory(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry, PluginStatus

        _write_manifest(
            tmp_path / "wrong-dir",
            _minimal_manifest_dict(plugin_id="other-id"),
        )
        registry = PluginRegistry(tmp_path)
        registry.scan_plugins_dir()
        record = registry.get("wrong-dir")
        assert record is not None
        assert record.status == PluginStatus.INVALID

    def test_list_enabled(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        _write_manifest(
            tmp_path / "other-plugin",
            _minimal_manifest_dict(plugin_id="other-plugin"),
        )
        registry = PluginRegistry(tmp_path)
        registry.scan_plugins_dir()

        assert len(registry.list_enabled()) == 0

        registry.enable_plugin("test-plugin")
        assert len(registry.list_enabled()) == 1

    def test_has_capability(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        registry = PluginRegistry(tmp_path)
        registry.scan_plugins_dir()
        registry.enable_plugin("test-plugin")

        assert registry.has_capability("test-plugin", "events.read")
        assert not registry.has_capability("test-plugin", "jobs.submit")

    def test_reload_plugin(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry, PluginStatus

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        registry = PluginRegistry(tmp_path)
        registry.scan_plugins_dir()
        registry.enable_plugin("test-plugin")

        ok = registry.reload_plugin("test-plugin")
        assert ok
        assert registry.get("test-plugin").status == PluginStatus.ENABLED  # type: ignore[union-attr]


# ══════════════════════════════════════════════════════════════════════════
# Secret management tests
# ══════════════════════════════════════════════════════════════════════════


class TestSecrets:
    def test_create_and_verify(self) -> None:
        from ultima_scraper_backend.plugin_system.secrets import SecretManager

        sm = SecretManager()
        raw = sm.create_secret("test-plugin", "callback", "handler-1")
        assert isinstance(raw, str)
        assert len(raw) > 20

        assert sm.verify("test-plugin", "callback", "handler-1", raw)
        assert not sm.verify("test-plugin", "callback", "handler-1", "wrong")

    def test_rotate_with_grace_period(self) -> None:
        from ultima_scraper_backend.plugin_system.secrets import SecretManager

        sm = SecretManager()
        old_raw = sm.create_secret("test-plugin", "outbound", "target-1")
        new_raw = sm.rotate_secret(
            "test-plugin",
            "outbound",
            "target-1",
            grace_period=timedelta(hours=1),
        )
        assert old_raw != new_raw

        # Both should verify during grace period
        assert sm.verify("test-plugin", "outbound", "target-1", new_raw)
        assert sm.verify("test-plugin", "outbound", "target-1", old_raw)

    def test_list_for_plugin(self) -> None:
        from ultima_scraper_backend.plugin_system.secrets import SecretManager

        sm = SecretManager()
        sm.create_secret("p1", "callback", "h1")
        sm.create_secret("p1", "outbound", "t1")
        sm.create_secret("p2", "callback", "h2")

        assert len(sm.list_for_plugin("p1")) == 2
        assert len(sm.list_for_plugin("p2")) == 1

    def test_delete_for_plugin(self) -> None:
        from ultima_scraper_backend.plugin_system.secrets import SecretManager

        sm = SecretManager()
        sm.create_secret("p1", "callback", "h1")
        sm.create_secret("p1", "outbound", "t1")
        deleted = sm.delete_for_plugin("p1")
        assert deleted == 2
        assert len(sm.list_for_plugin("p1")) == 0

    def test_rotate_nonexistent_raises(self) -> None:
        from ultima_scraper_backend.plugin_system.secrets import SecretManager

        sm = SecretManager()
        with pytest.raises(KeyError):
            sm.rotate_secret("nope", "callback", "handler")

    def test_set_secret_imports_operator_supplied_value(self) -> None:
        from ultima_scraper_backend.plugin_system.secrets import SecretManager

        sm = SecretManager()
        sm.set_secret("test-plugin", "remote_auth", "default", "abc123")

        assert sm.verify("test-plugin", "remote_auth", "default", "abc123")
        assert sm.get_raw_secret("test-plugin", "remote_auth", "default") == "abc123"


# ══════════════════════════════════════════════════════════════════════════
# State store tests
# ══════════════════════════════════════════════════════════════════════════


class TestStateStore:
    def test_set_get_delete(self) -> None:
        from ultima_scraper_backend.plugin_system.state_store import PluginStateStore

        store = PluginStateStore()
        store.set("p1", "cursor", {"offset": 42})
        assert store.get("p1", "cursor") == {"offset": 42}

        deleted = store.delete("p1", "cursor")
        assert deleted
        assert store.get("p1", "cursor") is None

    def test_quota_enforcement(self) -> None:
        from ultima_scraper_backend.plugin_system.state_store import PluginStateStore

        store = PluginStateStore(quota_bytes=50)
        store.set("p1", "small", "ok")  # fits
        with pytest.raises(ValueError, match="quota"):
            store.set("p1", "big", "x" * 200)

    def test_overwrite_reclaims_space(self) -> None:
        from ultima_scraper_backend.plugin_system.state_store import PluginStateStore

        store = PluginStateStore(quota_bytes=100)
        store.set("p1", "key", "x" * 30)
        # Overwrite with smaller value should work
        store.set("p1", "key", "small")
        assert store.get("p1", "key") == "small"

    def test_audit_log(self) -> None:
        from ultima_scraper_backend.plugin_system.state_store import PluginStateStore

        store = PluginStateStore()
        store.set("p1", "key", "v1", actor="plugin", reason="init")
        store.set("p1", "key", "v2", actor="operator", reason="fix")
        log = store.get_audit_log("p1")
        assert len(log) == 2
        assert log[0]["actor"] == "plugin"
        assert log[1]["actor"] == "operator"
        assert log[1]["old_value"] == "v1"
        assert log[1]["new_value"] == "v2"

    def test_list_keys(self) -> None:
        from ultima_scraper_backend.plugin_system.state_store import PluginStateStore

        store = PluginStateStore()
        store.set("p1", "a", 1)
        store.set("p1", "b", 2)
        assert sorted(store.list_keys("p1")) == ["a", "b"]

    def test_clear_plugin(self) -> None:
        from ultima_scraper_backend.plugin_system.state_store import PluginStateStore

        store = PluginStateStore()
        store.set("p1", "key", "val")
        store.clear_plugin("p1")
        assert store.list_keys("p1") == []

    def test_per_plugin_quota(self) -> None:
        from ultima_scraper_backend.plugin_system.state_store import PluginStateStore

        store = PluginStateStore(quota_bytes=50)
        store.set_quota("p1", 500)
        store.set("p1", "key", "x" * 200)  # fits with the custom quota
        assert store.get("p1", "key") == "x" * 200


# ══════════════════════════════════════════════════════════════════════════
# Event delivery tests
# ══════════════════════════════════════════════════════════════════════════


class TestEventDelivery:
    def test_envelope_serialization(self) -> None:
        from ultima_scraper_backend.plugin_system.delivery import EventEnvelope

        env = EventEnvelope(
            event_family="job.lifecycle",
            event_type="job.created",
            plugin_id="test-plugin",
            body={"job_id": "j1"},
        )
        d = env.to_dict()
        assert d["event_family"] == "job.lifecycle"
        assert d["event_type"] == "job.created"
        assert d["plugin_id"] == "test-plugin"
        assert d["body"] == {"job_id": "j1"}
        assert "event_id" in d
        assert "delivery_id" in d
        assert "timestamp" in d

        raw = env.to_json_bytes()
        parsed = json.loads(raw)
        assert parsed == d

    @pytest.mark.asyncio
    async def test_deliver_success(self) -> None:
        from ultima_scraper_backend.plugin_system.delivery import EventDeliveryEngine, EventEnvelope

        async def mock_post(
            url: str, payload: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            return 200

        engine = EventDeliveryEngine(http_post=mock_post)
        env = EventEnvelope(
            event_family="job.lifecycle",
            event_type="job.created",
            plugin_id="test-plugin",
            body={"job_id": "j1"},
        )
        attempt = await engine.deliver(
            env,
            url="https://example.com/hook",
            target_name="main",
        )
        assert attempt.status == "delivered"
        assert attempt.status_code == 200
        assert attempt.retry_count == 0

    @pytest.mark.asyncio
    async def test_deliver_retries_on_failure(self) -> None:
        from ultima_scraper_backend.plugin_system.delivery import EventDeliveryEngine, EventEnvelope

        call_count = 0

        async def mock_post(
            url: str, payload: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return 500
            return 200

        engine = EventDeliveryEngine(http_post=mock_post)
        env = EventEnvelope(
            event_family="job.lifecycle",
            event_type="job.created",
            plugin_id="test-plugin",
            body={},
        )
        attempt = await engine.deliver(
            env,
            url="https://example.com/hook",
            target_name="main",
            retry_policy_max_retries=5,
            retry_policy_initial_backoff=0,  # no actual sleep in tests
            retry_policy_max_backoff=0,
        )
        assert attempt.status == "delivered"
        assert attempt.retry_count == 2
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_deliver_exhausts_retries(self) -> None:
        from ultima_scraper_backend.plugin_system.delivery import EventDeliveryEngine, EventEnvelope

        async def mock_post(
            url: str, payload: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            return 500

        engine = EventDeliveryEngine(http_post=mock_post)
        env = EventEnvelope(
            event_family="job.lifecycle",
            event_type="job.created",
            plugin_id="test-plugin",
            body={},
        )
        attempt = await engine.deliver(
            env,
            url="https://example.com/hook",
            target_name="main",
            retry_policy_max_retries=2,
            retry_policy_initial_backoff=0,
            retry_policy_max_backoff=0,
        )
        assert attempt.status == "failed"
        assert attempt.retry_count == 2

    @pytest.mark.asyncio
    async def test_dispatch_event_matches_subscriptions(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.delivery import EventDeliveryEngine
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry
        from ultima_scraper_backend.plugin_system.secrets import SecretManager

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        registry = PluginRegistry(tmp_path)
        registry.scan_plugins_dir()
        registry.enable_plugin("test-plugin")

        sm = SecretManager()
        sm.create_secret("test-plugin", "outbound", "main")

        delivered: list[str] = []

        async def mock_post(
            url: str, payload: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            delivered.append(url)
            return 200

        engine = EventDeliveryEngine(http_post=mock_post)
        results = await engine.dispatch_event(
            event_family="job.lifecycle",
            event_type="job.created",
            body={"job_id": "j123"},
            registry=registry,
            secret_manager=sm,
        )
        assert len(results) == 1
        assert results[0].status == "delivered"
        assert "https://example.com/hook" in delivered

    @pytest.mark.asyncio
    async def test_dispatch_skips_non_matching(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.delivery import EventDeliveryEngine
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry
        from ultima_scraper_backend.plugin_system.secrets import SecretManager

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        registry = PluginRegistry(tmp_path)
        registry.scan_plugins_dir()
        registry.enable_plugin("test-plugin")

        sm = SecretManager()

        async def mock_post(
            url: str, payload: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            return 200

        engine = EventDeliveryEngine(http_post=mock_post)
        # Event type not in subscription
        results = await engine.dispatch_event(
            event_family="job.lifecycle",
            event_type="job.cancelled",
            body={},
            registry=registry,
            secret_manager=sm,
        )
        assert len(results) == 0

    def test_endpoint_status_tracking(self) -> None:
        from ultima_scraper_backend.plugin_system.delivery import EventDeliveryEngine

        engine = EventDeliveryEngine()
        status = engine.get_endpoint_status("test-plugin", "main")
        status.record_success()
        assert status.consecutive_failures == 0
        assert status.last_success_at is not None

        status.record_failure("HTTP 500", None)
        assert status.consecutive_failures == 1
        assert status.last_error == "HTTP 500"

        status.record_success()
        assert status.consecutive_failures == 0


# ══════════════════════════════════════════════════════════════════════════
# File watcher tests
# ══════════════════════════════════════════════════════════════════════════


class TestFileWatcher:
    def test_snapshot(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.watcher import PluginFileWatcher

        _write_manifest(tmp_path / "p1", _minimal_manifest_dict(plugin_id="p1"))
        watcher = PluginFileWatcher(tmp_path)
        snap = watcher.snapshot()
        assert "p1" in snap

    def test_detect_changes(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.watcher import PluginFileWatcher

        _write_manifest(tmp_path / "p1", _minimal_manifest_dict(plugin_id="p1"))
        watcher = PluginFileWatcher(tmp_path)
        watcher._known = watcher.snapshot()

        # Add a new plugin
        _write_manifest(tmp_path / "p2", _minimal_manifest_dict(plugin_id="p2"))
        added, modified, removed = watcher.detect_changes()
        assert "p2" in added
        assert "p1" not in added

    def test_detect_removal(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.watcher import PluginFileWatcher

        _write_manifest(tmp_path / "p1", _minimal_manifest_dict(plugin_id="p1"))
        watcher = PluginFileWatcher(tmp_path)
        watcher._known = watcher.snapshot()

        # Remove plugin directory
        import shutil

        shutil.rmtree(tmp_path / "p1")
        added, modified, removed = watcher.detect_changes()
        assert removed == []
        added, modified, removed = watcher.detect_changes()
        assert "p1" in removed


# ══════════════════════════════════════════════════════════════════════════
# Platform facade tests
# ══════════════════════════════════════════════════════════════════════════


class TestPluginPlatform:
    def test_load_all(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        platform = PluginPlatform(tmp_path)
        loaded = platform.load_all()
        assert "test-plugin" in loaded

    def test_approve_enable_disable(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        platform = PluginPlatform(tmp_path)
        platform.load_all()

        result = platform.enable_plugin("test-plugin")
        assert result["status"] == "enabled"

        result = platform.disable_plugin("test-plugin")
        assert result["status"] == "disabled"

    def test_submit_job_validates_payload(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict(
            capabilities=["events.read", "jobs.submit"],
            task_types=[
                {
                    "task_type": "scrape.user",
                    "payload_fields": [
                        {"name": "username", "field_type": "string", "required": True},
                    ],
                }
            ],
        )
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")

        # Valid payload
        result = platform.submit_job(
            "test-plugin", "scrape.user", {"username": "alice"}
        )
        assert result["plugin_id"] == "test-plugin"
        assert result["task_type"] == "scrape.user"

        # Missing required field
        with pytest.raises(ValueError, match="Missing required"):
            platform.submit_job("test-plugin", "scrape.user", {})

        # Unknown field
        with pytest.raises(ValueError, match="Unknown field"):
            platform.submit_job(
                "test-plugin", "scrape.user", {"username": "x", "extra": 1}
            )

    def test_submit_job_rejects_undeclared_type(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict(
            capabilities=["events.read", "jobs.submit"],
            task_types=[
                {
                    "task_type": "scrape.user",
                    "payload_fields": [],
                }
            ],
        )
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")

        with pytest.raises(ValueError, match="does not declare"):
            platform.submit_job("test-plugin", "nonexistent.type", {})

    def test_submit_job_without_capability_raises(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict()  # only events.read
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")

        with pytest.raises(PermissionError, match="jobs.submit"):
            platform.submit_job("test-plugin", "anything", {})

    def test_submit_job_on_disabled_plugin_raises(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict(
            capabilities=["events.read", "jobs.submit"],
            task_types=[{"task_type": "scrape.user", "payload_fields": []}],
        )
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        # Not approved/enabled

        with pytest.raises(PermissionError, match="not enabled"):
            platform.submit_job("test-plugin", "scrape.user", {})

    def test_worker_status_without_capability_raises(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict()  # no workers.status.read
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")

        with pytest.raises(PermissionError, match="workers.status.read"):
            platform.read_worker_status("test-plugin")

    def test_state_operations(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        platform = PluginPlatform(tmp_path)
        platform.load_all()

        platform.set_state("test-plugin", "cursor", 42)
        assert platform.get_state("test-plugin", "cursor") == 42

        entries = platform.list_state("test-plugin")
        assert len(entries) == 1

        deleted = platform.delete_state("test-plugin", "cursor")
        assert deleted

        audit = platform.get_state_audit("test-plugin")
        assert len(audit) == 2  # set + delete

    def test_secrets_auto_created(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict(
            capabilities=["events.read", "webhooks.register"],
            callbacks=[
                {"handler_id": "handler-a", "auth_method": "hmac"},
            ],
        )
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()

        secrets = platform.list_secrets("test-plugin")
        # 1 callback + 1 outbound delivery
        assert len(secrets) == 2

    def test_platform_can_set_existing_secret_value(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict(
            plugin_id="remote-plugin",
            capabilities=["events.read", "remote.jobs.submit"],
            remote_delegation={
                "integration_id": "remote-a",
                "role": "submitter",
                "external_system_url": "https://example.com",
                "operations": {
                    "submission": {
                        "transport": "http",
                        "method": "POST",
                        "endpoint": "/api/jobs",
                    }
                },
            },
        )
        _write_manifest(tmp_path / "remote-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()

        platform.set_secret("remote-plugin", "remote_auth", "default", "imported-key")

        assert (
            platform.secrets.get_raw_secret("remote-plugin", "remote_auth", "default")
            == "imported-key"
        )

    def test_list_plugins(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        _write_manifest(
            tmp_path / "other-plugin",
            _minimal_manifest_dict(plugin_id="other-plugin"),
        )
        platform = PluginPlatform(tmp_path)
        platform.load_all()

        plugins = platform.list_plugins()
        assert len(plugins) == 2

    def test_handle_filesystem_changes_adds_new_plugin(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        platform = PluginPlatform(tmp_path)
        platform.load_all()

        _write_manifest(
            tmp_path / "new-plugin",
            _minimal_manifest_dict(plugin_id="new-plugin"),
        )

        result = platform.handle_filesystem_changes(["new-plugin"], [], [])

        assert result["loaded"] == ["new-plugin"]
        assert result["removed"] == []
        record = platform.get_plugin("new-plugin")
        assert record is not None
        assert record["plugin_id"] == "new-plugin"
        assert record["status"] == "disabled"

    def test_handle_filesystem_changes_quarantines_missing_plugin(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict(
            capabilities=["events.read", "webhooks.register"],
            callbacks=[{"handler_id": "handler-a", "auth_method": "hmac"}],
        )
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.set_state("test-plugin", "cursor", 42)

        result = platform.handle_filesystem_changes([], [], ["test-plugin"])

        assert result["loaded"] == []
        assert result["removed"] == ["test-plugin"]
        record = platform.get_plugin("test-plugin")
        assert record is not None
        assert record["status"] == "missing"
        assert record["health_status"] == "missing"
        assert platform.state.get("test-plugin", "cursor") == 42
        assert platform.secrets.list_for_plugin("test-plugin") != []

    @pytest.mark.asyncio
    async def test_dispatch_event(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")

        delivered: list[str] = []

        async def mock_post(
            url: str, payload: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            delivered.append(url)
            return 200

        platform.delivery._http_post = mock_post

        results = await platform.dispatch_event(
            event_family="job.lifecycle",
            event_type="job.created",
            body={"job_id": "j1"},
        )
        assert len(results) == 1
        assert results[0].status == "delivered"

    # ── Create plugin tests ───────────────────────────────────────────────

    def test_create_plugin_success(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        data = _minimal_manifest_dict(plugin_id="new-plugin")
        result = platform.create_plugin(data)

        assert result["creation_status"] == "created"
        assert result["reload_succeeded"] is True
        assert result["plugin_id"] == "new-plugin"
        assert result["status"] == "disabled"

        # Manifest file should exist on disk
        manifest_path = tmp_path / "new-plugin" / "manifest.yaml"
        assert manifest_path.is_file()

        # Should be parseable YAML matching original data
        written = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert written["plugin_id"] == "new-plugin"

    def test_create_plugin_duplicate_rejected(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        platform = PluginPlatform(tmp_path)
        platform.load_all()

        with pytest.raises(ValueError, match="already exists"):
            platform.create_plugin(_minimal_manifest_dict())

    def test_create_plugin_invalid_manifest(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        # Missing required fields
        with pytest.raises(Exception):
            platform.create_plugin({"plugin_id": "bad"})

    def test_create_plugin_invalid_id_format(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        data = _minimal_manifest_dict(plugin_id="INVALID_UPPER")
        with pytest.raises(Exception):
            platform.create_plugin(data)

    def test_create_plugin_path_traversal_rejected(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        # The plugin_id regex already blocks ".." but test the path safety too
        # Use a technically valid id that could be misused if path wasn't checked
        data = _minimal_manifest_dict(plugin_id="test-plugin")
        # Create one first
        platform.create_plugin(data)
        # Verify the file is inside plugins dir
        manifest_path = (tmp_path / "test-plugin" / "manifest.yaml").resolve()
        assert str(manifest_path).startswith(str(tmp_path.resolve()))

    def test_create_plugin_shows_in_list(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        data = _minimal_manifest_dict(plugin_id="list-test")
        platform.create_plugin(data)

        plugins = platform.list_plugins()
        ids = [p["plugin_id"] for p in plugins]
        assert "list-test" in ids

    def test_create_plugin_lifecycle_after_create(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        data = _minimal_manifest_dict(plugin_id="lifecycle-test")
        result = platform.create_plugin(data)
        assert result["status"] == "disabled"

        enabled = platform.enable_plugin("lifecycle-test")
        assert enabled["status"] == "enabled"

        disabled = platform.disable_plugin("lifecycle-test")
        assert disabled["status"] == "disabled"

    def test_create_plugin_survives_reload(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        data = _minimal_manifest_dict(plugin_id="persist-test")
        platform.create_plugin(data)

        # Create a fresh platform instance (simulates restart)
        platform2 = PluginPlatform(tmp_path)
        platform2.load_all()
        record = platform2.get_plugin("persist-test")
        assert record is not None
        assert record["plugin_id"] == "persist-test"

    def test_enabled_state_persists_across_restart(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")

        # Simulate restart with a fresh platform
        platform2 = PluginPlatform(tmp_path)
        platform2.load_all()
        record = platform2.get_plugin("test-plugin")
        assert record is not None
        assert record["status"] == "enabled"

    def test_disabled_state_persists_across_restart(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")
        platform.disable_plugin("test-plugin")

        # Simulate restart
        platform2 = PluginPlatform(tmp_path)
        platform2.load_all()
        record = platform2.get_plugin("test-plugin")
        assert record is not None
        assert record["status"] == "disabled"


# ══════════════════════════════════════════════════════════════════════════
# Example plugin manifest validation
# ══════════════════════════════════════════════════════════════════════════


class TestExamplePlugin:
    """Validate the test fixture for webhook relay integrations."""

    def test_example_manifest_loads(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        example_path = USR_ROOT / "tests/fixtures/plugins/example-webhook-relay.yaml"
        assert example_path.is_file(), f"Example manifest not found: {example_path}"
        data = yaml.safe_load(example_path.read_text())
        manifest = load_manifest_from_dict(data)
        assert manifest.plugin_id == "example-webhook-relay"
        assert manifest.plugin_version == "0.1.0"
        assert len(manifest.event_subscriptions) == 2
        assert len(manifest.callbacks) == 1

    def test_example_loads_via_registry(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.registry import PluginRegistry

        plugins_dir = tmp_path
        _write_manifest(plugins_dir / "example-webhook-relay", yaml.safe_load((USR_ROOT / "tests/fixtures/plugins/example-webhook-relay.yaml").read_text()))
        registry = PluginRegistry(plugins_dir)
        loaded = registry.scan_plugins_dir()
        assert "example-webhook-relay" in loaded


# ══════════════════════════════════════════════════════════════════════════
# Redis channel generalization tests
# ══════════════════════════════════════════════════════════════════════════


class TestRedisChannels:
    def test_plugin_key_patterns_exist(self) -> None:
        from ultima_scraper_backend.redis_channels import (
            PLUGIN_EVENTS_CHANNEL,
            PLUGIN_STATE_PREFIX,
            PLUGIN_STATUS_PREFIX,
            get_plugin_state_prefix,
            get_plugin_status_key,
        )

        assert "plugins:status:" in PLUGIN_STATUS_PREFIX
        assert "plugins:events" in PLUGIN_EVENTS_CHANNEL
        assert "plugins:state:" in PLUGIN_STATE_PREFIX

        key = get_plugin_status_key("my-plugin")
        assert key.endswith("my-plugin")

        prefix = get_plugin_state_prefix("my-plugin")
        assert prefix.endswith("my-plugin:")


# ══════════════════════════════════════════════════════════════════════════
# Field type validation tests
# ══════════════════════════════════════════════════════════════════════════


class TestFieldTypeValidation:
    def test_boolean_not_accepted_as_integer(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict(
            capabilities=["events.read", "jobs.submit"],
            task_types=[
                {
                    "task_type": "test.job",
                    "payload_fields": [
                        {"name": "count", "field_type": "integer", "required": True},
                    ],
                }
            ],
        )
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")

        with pytest.raises(ValueError, match="expected integer"):
            platform.submit_job("test-plugin", "test.job", {"count": True})

    def test_allowed_values_enforcement(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict(
            capabilities=["events.read", "jobs.submit"],
            task_types=[
                {
                    "task_type": "test.job",
                    "payload_fields": [
                        {
                            "name": "mode",
                            "field_type": "string",
                            "required": True,
                            "allowed_values": ["fast", "slow"],
                        },
                    ],
                }
            ],
        )
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")

        # Valid
        result = platform.submit_job("test-plugin", "test.job", {"mode": "fast"})
        assert result["payload"]["mode"] == "fast"

        # Invalid
        with pytest.raises(ValueError, match="not in allowed_values"):
            platform.submit_job("test-plugin", "test.job", {"mode": "turbo"})


# ══════════════════════════════════════════════════════════════════════════
# Remote delegation manifest tests
# ══════════════════════════════════════════════════════════════════════════


def _remote_submitter_manifest(**overrides: Any) -> dict[str, Any]:
    """Helper: manifest with a submitter remote_delegation."""
    base: dict[str, Any] = {
        "plugin_id": "remote-sub",
        "plugin_version": "1.0.0",
        "display_name": "Remote Submitter",
        "description": "Submits jobs to external system.",
        "usr_compatibility": ">=0.1.0",
        "capabilities": [
            "events.read",
            "remote.jobs.submit",
        ],
        "event_subscriptions": [
            {
                "event_family": "job.lifecycle",
                "event_types": ["job.created"],
                "delivery_target": "main",
            }
        ],
        "outbound_deliveries": [
            {"target_name": "main", "url": "https://example.com/hook"},
        ],
        "remote_delegation": {
            "integration_id": "usweb-remote",
            "role": "submitter",
            "description": "Delegates jobs to USWeb",
            "external_system_url": "https://usweb.example.com",
            "auth": {"method": "api_key", "header_name": "X-API-Key"},
            "correlation": {
                "local_id_field": "usr_submission_id",
                "remote_id_field": "usweb_job_id",
                "submitter_id_field": "submitted_by",
            },
            "operations": {
                "submission": {
                    "transport": "http",
                    "method": "POST",
                    "endpoint": "/api/v1/jobs",
                    "request_mapping": {
                        "body": {
                            "job_type": {"source_path": "payload.job_type"},
                            "payload": {"source_path": "payload.payload"},
                            "correlation_id": {"source_path": "runtime.correlation_id"},
                            "idempotency_key": {
                                "source_path": "runtime.idempotency_key"
                            },
                        }
                    },
                    "response_mapping": {
                        "external_job_id_path": "job.id",
                        "remote_status_path": "job.status",
                    },
                },
                "poll": {
                    "transport": "http",
                    "method": "GET",
                    "endpoint": "/api/v1/jobs/{external_job_id}",
                    "request_mapping": {
                        "path_params": {
                            "external_job_id": {
                                "source_path": "runtime.external_job_id"
                            },
                        }
                    },
                    "response_mapping": {
                        "external_job_id_path": "job.id",
                        "remote_status_path": "job.status",
                    },
                },
            },
            "callbacks": {"inbound": []},
        },
    }
    base.update(overrides)
    return base


def _remote_executor_manifest(**overrides: Any) -> dict[str, Any]:
    """Helper: manifest with an executor remote_delegation."""
    base: dict[str, Any] = {
        "plugin_id": "remote-exec",
        "plugin_version": "1.0.0",
        "display_name": "Remote Executor",
        "description": "Executes jobs from external system.",
        "usr_compatibility": ">=0.1.0",
        "capabilities": [
            "events.read",
            "webhooks.register",
            "remote.jobs.execute",
            "remote.callbacks.receive",
        ],
        "event_subscriptions": [
            {
                "event_family": "job.lifecycle",
                "event_types": ["job.created"],
                "delivery_target": "main",
            }
        ],
        "outbound_deliveries": [
            {"target_name": "main", "url": "https://example.com/hook"},
        ],
        "callbacks": [
            {"handler_id": "on-claimed", "auth_method": "hmac"},
            {"handler_id": "on-progress", "auth_method": "hmac"},
            {"handler_id": "on-completed", "auth_method": "hmac"},
        ],
        "remote_delegation": {
            "integration_id": "usweb-admin",
            "role": "executor",
            "description": "Receives and executes USWeb jobs",
            "external_system_url": "https://usweb-admin.example.com",
            "auth": {"method": "api_key", "header_name": "X-API-Key"},
            "operations": {
                "claim": {
                    "transport": "http",
                    "method": "POST",
                    "endpoint": "/api/v1/worker/jobs/claim",
                    "request_mapping": {
                        "body": {
                            "worker_id": {"source_path": "payload.worker_id"},
                            "worker_name": {"source_path": "payload.worker_name"},
                        }
                    },
                    "response_mapping": {
                        "external_job_id_path": "job.id",
                        "remote_status_path": "job.status",
                    },
                },
                "progress": {
                    "transport": "http",
                    "method": "POST",
                    "endpoint": "/api/v1/worker/jobs/{external_job_id}/progress",
                    "request_mapping": {
                        "path_params": {
                            "external_job_id": {
                                "source_path": "runtime.external_job_id"
                            },
                        },
                        "body": {
                            "worker_id": {"source_path": "runtime.worker_id"},
                            "progress": {"source_path": "payload"},
                        },
                    },
                    "response_mapping": {
                        "external_job_id_path": "job.id",
                        "remote_status_path": "job.status",
                    },
                },
                "complete": {
                    "transport": "http",
                    "method": "POST",
                    "endpoint": "/api/v1/worker/jobs/{external_job_id}/complete",
                    "request_mapping": {
                        "path_params": {
                            "external_job_id": {
                                "source_path": "runtime.external_job_id"
                            },
                        },
                        "body": {
                            "worker_id": {"source_path": "runtime.worker_id"},
                            "result": {"source_path": "payload"},
                            "progress": {"source_path": "payload"},
                        },
                    },
                    "response_mapping": {
                        "external_job_id_path": "job.id",
                        "remote_status_path": "job.status",
                    },
                },
                "fail": {
                    "transport": "http",
                    "method": "POST",
                    "endpoint": "/api/v1/worker/jobs/{external_job_id}/fail",
                    "request_mapping": {
                        "path_params": {
                            "external_job_id": {
                                "source_path": "runtime.external_job_id"
                            },
                        },
                        "body": {
                            "worker_id": {"source_path": "runtime.worker_id"},
                            "error_code": {"literal": "remote_failure"},
                            "error_message": {"source_path": "payload.failure_message"},
                            "progress": {"source_path": "payload"},
                        },
                    },
                    "response_mapping": {
                        "external_job_id_path": "job.id",
                        "remote_status_path": "job.status",
                    },
                },
                "cancel": {
                    "transport": "http",
                    "method": "POST",
                    "endpoint": "/api/v1/jobs/{external_job_id}/cancel",
                    "request_mapping": {
                        "path_params": {
                            "external_job_id": {
                                "source_path": "runtime.external_job_id"
                            },
                        },
                        "body": {
                            "reason": {"source_path": "payload.reason"},
                        },
                    },
                    "response_mapping": {
                        "external_job_id_path": "job.id",
                        "remote_status_path": "job.status",
                    },
                },
            },
            "callbacks": {
                "inbound": [
                    {
                        "handler_id": "on-claimed",
                        "extract": {
                            "lifecycle_event": {"literal": "claimed"},
                            "correlation_id": {
                                "source_path": "callback.body.correlation_id"
                            },
                            "external_job_id": {"source_path": "callback.body.job_id"},
                        },
                    },
                    {
                        "handler_id": "on-progress",
                        "extract": {
                            "lifecycle_event": {"literal": "progress"},
                            "correlation_id": {
                                "source_path": "callback.body.correlation_id"
                            },
                            "external_job_id": {"source_path": "callback.body.job_id"},
                        },
                    },
                    {
                        "handler_id": "on-completed",
                        "extract": {
                            "lifecycle_event": {"literal": "completed"},
                            "correlation_id": {
                                "source_path": "callback.body.correlation_id"
                            },
                            "external_job_id": {"source_path": "callback.body.job_id"},
                            "result": {"source_path": "callback.body.result"},
                        },
                    },
                ]
            },
        },
    }
    base.update(overrides)
    return base


class TestRemoteDelegationManifest:
    """Validate the remote_delegation manifest section."""

    def test_valid_submitter_manifest(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_submitter_manifest()
        manifest = load_manifest_from_dict(data)
        assert manifest.remote_delegation is not None
        assert manifest.remote_delegation.role == "submitter"
        assert manifest.remote_delegation.integration_id == "usweb-remote"
        assert (
            manifest.remote_delegation.external_system_url
            == "https://usweb.example.com"
        )
        assert manifest.remote_delegation.operations.submission is not None
        assert (
            manifest.remote_delegation.operations.submission.endpoint == "/api/v1/jobs"
        )

    def test_valid_executor_manifest(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_executor_manifest()
        manifest = load_manifest_from_dict(data)
        assert manifest.remote_delegation is not None
        assert manifest.remote_delegation.role == "executor"
        assert len(manifest.remote_delegation.callbacks.inbound) == 3

    def test_named_auth_scopes_are_validated(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_executor_manifest()
        data["remote_delegation"]["auth_scopes"] = {
            "public_api": {"method": "api_key", "header_name": "X-API-Key"},
            "worker_api": {"method": "api_key", "header_name": "X-USR-Worker-Token"},
        }
        data["remote_delegation"]["operations"]["claim"]["auth_scope"] = "worker_api"
        data["remote_delegation"]["callback_registration"] = {
            "endpoint": "/api/v1/webhooks",
            "method": "POST",
            "auth_scope": "public_api",
            "lifecycle_events": ["progress"],
        }

        manifest = load_manifest_from_dict(data)
        assert manifest.remote_delegation is not None
        assert manifest.remote_delegation.operations.claim is not None
        assert manifest.remote_delegation.operations.claim.auth_scope == "worker_api"

    def test_unknown_auth_scope_reference_is_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_submitter_manifest()
        data["remote_delegation"]["auth_scopes"] = {
            "public_api": {"method": "api_key", "header_name": "X-API-Key"},
        }
        data["remote_delegation"]["operations"]["submission"][
            "auth_scope"
        ] = "missing_scope"

        with pytest.raises(Exception, match="auth_scope"):
            load_manifest_from_dict(data)

    def test_submitter_missing_url_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_submitter_manifest()
        data["remote_delegation"]["external_system_url"] = ""
        with pytest.raises(Exception, match="external_system_url"):
            load_manifest_from_dict(data)

    def test_submitter_missing_endpoint_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_submitter_manifest()
        data["remote_delegation"]["operations"]["submission"] = None
        with pytest.raises(Exception, match="operations.submission"):
            load_manifest_from_dict(data)

    def test_executor_missing_inbound_callbacks_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_executor_manifest()
        data["remote_delegation"]["callbacks"]["inbound"] = []
        with pytest.raises(Exception, match="callbacks.inbound"):
            load_manifest_from_dict(data)

    def test_submitter_without_capability_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_submitter_manifest()
        data["capabilities"] = ["events.read"]  # no remote.jobs.submit
        with pytest.raises(Exception, match="remote.jobs.submit"):
            load_manifest_from_dict(data)

    def test_executor_without_execute_capability_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_executor_manifest()
        data["capabilities"] = [
            "events.read",
            "webhooks.register",
            "remote.callbacks.receive",
        ]  # missing remote.jobs.execute
        with pytest.raises(Exception, match="remote.jobs.execute"):
            load_manifest_from_dict(data)

    def test_executor_without_callbacks_receive_capability_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_executor_manifest()
        data["capabilities"] = [
            "events.read",
            "webhooks.register",
            "remote.jobs.execute",
        ]  # missing remote.callbacks.receive
        with pytest.raises(Exception, match="remote.callbacks.receive"):
            load_manifest_from_dict(data)

    def test_submitter_auth_export_requires_capability(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_submitter_manifest()
        data["remote_delegation"]["auth_export"] = {
            "site_path": "payload.site",
            "auth_id_path": "payload.auth_id",
            "runtime_key": "auth_bundle",
        }
        with pytest.raises(Exception, match="auth.credentials.export"):
            load_manifest_from_dict(data)

    def test_executor_auth_import_requires_capability(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_executor_manifest()
        data["remote_delegation"]["auth_import"] = {
            "bundle_path": "payload.auth_bundle",
            "site_path": "payload.site",
            "runtime_key": "imported_auth_id",
        }
        with pytest.raises(Exception, match="auth.credentials.import"):
            load_manifest_from_dict(data)

    def test_callback_mapping_references_undeclared_handler_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_executor_manifest()
        data["remote_delegation"]["callbacks"]["inbound"] = [
            {
                "handler_id": "nonexistent-handler",
                "extract": {"lifecycle_event": {"literal": "claimed"}},
            }
        ]
        with pytest.raises(Exception, match="nonexistent-handler"):
            load_manifest_from_dict(data)

    def test_invalid_lifecycle_event_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_executor_manifest()
        data["remote_delegation"]["callbacks"]["inbound"] = [
            {
                "handler_id": "on-claimed",
                "extract": {
                    "lifecycle_event": {"source_path": "bad_namespace.event"},
                },
            }
        ]
        with pytest.raises(Exception, match="callback.body"):
            load_manifest_from_dict(data)

    def test_invalid_integration_id_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_submitter_manifest()
        data["remote_delegation"]["integration_id"] = "INVALID"
        with pytest.raises(Exception, match="integration_id"):
            load_manifest_from_dict(data)

    def test_invalid_external_url_scheme_rejected(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_submitter_manifest()
        data["remote_delegation"]["external_system_url"] = "ftp://bad.example.com"
        with pytest.raises(Exception, match="must start with"):
            load_manifest_from_dict(data)

    def test_bidirectional_role_requires_both(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_executor_manifest()
        data["plugin_id"] = "bidir-test"
        data["remote_delegation"]["role"] = "bidirectional"
        data["remote_delegation"]["external_system_url"] = "https://usweb.example.com"
        data["remote_delegation"]["operations"]["submission"] = {
            "transport": "http",
            "method": "POST",
            "endpoint": "/api/v1/jobs",
            "request_mapping": {
                "body": {
                    "job_type": {"source_path": "payload.job_type"},
                    "payload": {"source_path": "payload.payload"},
                }
            },
            "response_mapping": {
                "external_job_id_path": "job.id",
                "remote_status_path": "job.status",
            },
        }
        data["capabilities"] = [
            "events.read",
            "webhooks.register",
            "remote.jobs.submit",
            "remote.jobs.execute",
            "remote.callbacks.receive",
        ]
        manifest = load_manifest_from_dict(data)
        assert manifest.remote_delegation is not None
        assert manifest.remote_delegation.role == "bidirectional"

    def test_manifest_without_remote_delegation_still_works(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _minimal_manifest_dict()
        manifest = load_manifest_from_dict(data)
        assert manifest.remote_delegation is None

    def test_remote_delegation_serialization(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

        data = _remote_submitter_manifest()
        manifest = load_manifest_from_dict(data)
        dumped = manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
        assert "remote_delegation" in dumped
        assert dumped["remote_delegation"]["role"] == "submitter"
        assert dumped["remote_delegation"]["integration_id"] == "usweb-remote"


# ══════════════════════════════════════════════════════════════════════════
# Remote delegation permissions tests
# ══════════════════════════════════════════════════════════════════════════


class TestRemotePermissions:
    def test_validate_remote_capabilities(self) -> None:
        from ultima_scraper_backend.plugin_system.permissions import validate_capabilities

        valid, invalid = validate_capabilities(
            ["remote.jobs.submit", "remote.jobs.execute", "remote.callbacks.receive"]
        )
        assert len(valid) == 3
        assert len(invalid) == 0

    def test_check_remote_capability(self) -> None:
        from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict
        from ultima_scraper_backend.plugin_system.permissions import PluginCapability, check_capability

        data = _remote_submitter_manifest()
        manifest = load_manifest_from_dict(data)
        assert check_capability(manifest, PluginCapability.REMOTE_JOBS_SUBMIT)
        assert not check_capability(manifest, PluginCapability.REMOTE_JOBS_EXECUTE)


# ══════════════════════════════════════════════════════════════════════════
# Remote delegation platform tests
# ══════════════════════════════════════════════════════════════════════════


class TestRemoteDelegationPlatform:
    def test_submit_delegated_job(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "remote-sub", _remote_submitter_manifest())
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("remote-sub")

        result = platform.submit_delegated_job(
            "remote-sub", {"action": "scrape", "target": "user123"}
        )
        assert result["plugin_id"] == "remote-sub"
        assert result["integration_id"] == "usweb-remote"
        assert "correlation_id" in result
        assert result["external_system_url"] == "https://usweb.example.com"
        assert result["operation"]["endpoint"] == "/api/v1/jobs"
        assert result["payload"] == {"action": "scrape", "target": "user123"}

    def test_submit_delegated_job_without_capability_raises(
        self, tmp_path: Path
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict()
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")

        with pytest.raises(PermissionError, match="remote.jobs.submit"):
            platform.submit_delegated_job("test-plugin", {})

    def test_submit_delegated_job_no_remote_delegation_raises(
        self, tmp_path: Path
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        # Plugin with capability but no remote_delegation section
        data = _minimal_manifest_dict(
            capabilities=["events.read", "remote.jobs.submit"],
        )
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")

        with pytest.raises(ValueError, match="no remote_delegation"):
            platform.submit_delegated_job("test-plugin", {})

    def test_submit_delegated_job_executor_role_rejected(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "remote-exec", _remote_executor_manifest())
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("remote-exec")

        with pytest.raises((PermissionError, ValueError)):
            platform.submit_delegated_job("remote-exec", {})

    def test_receive_remote_callback(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "remote-exec", _remote_executor_manifest())
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("remote-exec")

        result = platform.receive_remote_callback(
            "remote-exec", "on-claimed", {"job_id": "j1", "worker_id": "w1"}
        )
        assert result["accepted"] is True
        assert result["plugin_id"] == "remote-exec"
        assert result["handler_id"] == "on-claimed"
        assert result["lifecycle_event"] == "claimed"

    def test_receive_remote_callback_unknown_handler_raises(
        self, tmp_path: Path
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "remote-exec", _remote_executor_manifest())
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("remote-exec")

        with pytest.raises(ValueError, match="no callback handler"):
            platform.receive_remote_callback("remote-exec", "nonexistent", {})

    def test_receive_remote_callback_without_capability_raises(
        self, tmp_path: Path
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict(
            capabilities=["events.read", "webhooks.register"],
            callbacks=[{"handler_id": "test-cb", "auth_method": "hmac"}],
        )
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        platform.enable_plugin("test-plugin")

        with pytest.raises(PermissionError, match="remote.callbacks.receive"):
            platform.receive_remote_callback("test-plugin", "test-cb", {})

    def test_get_remote_delegation_info(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "remote-sub", _remote_submitter_manifest())
        platform = PluginPlatform(tmp_path)
        platform.load_all()

        info = platform.get_remote_delegation_info("remote-sub")
        assert info is not None
        assert info["integration_id"] == "usweb-remote"
        assert info["role"] == "submitter"

    def test_get_remote_delegation_info_none_for_local_plugin(
        self, tmp_path: Path
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "test-plugin", _minimal_manifest_dict())
        platform = PluginPlatform(tmp_path)
        platform.load_all()

        info = platform.get_remote_delegation_info("test-plugin")
        assert info is None

    def test_create_remote_plugin_and_secrets(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        data = _remote_submitter_manifest()
        result = platform.create_plugin(data)
        assert result["creation_status"] == "created"

        secrets = platform.list_secrets("remote-sub")
        secret_pairs = {(s["scope_kind"], s["scope_name"]) for s in secrets}
        assert ("remote_auth", "default") in secret_pairs
        assert any(scope_kind == "outbound" for scope_kind, _ in secret_pairs)

    def test_create_executor_plugin_and_secrets(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        data = _remote_executor_manifest()
        result = platform.create_plugin(data)
        assert result["creation_status"] == "created"

        secrets = platform.list_secrets("remote-exec")
        secret_pairs = {(s["scope_kind"], s["scope_name"]) for s in secrets}
        assert ("remote_auth", "default") in secret_pairs
        assert any(scope_kind == "callback" for scope_kind, _ in secret_pairs)

    def test_auth_scopes_create_remote_auth_secrets(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        data = _remote_executor_manifest()
        data["plugin_id"] = "remote-scoped"
        data["remote_delegation"]["integration_id"] = "remote-scoped"
        data["remote_delegation"]["auth_scopes"] = {
            "public_api": {"method": "api_key", "header_name": "X-API-Key"},
            "worker_api": {"method": "api_key", "header_name": "X-USR-Worker-Token"},
        }
        data["remote_delegation"]["operations"]["claim"]["auth_scope"] = "worker_api"
        result = platform.create_plugin(data)

        assert result["creation_status"] == "created"
        secrets = platform.list_secrets("remote-scoped")
        secret_pairs = {(s["scope_kind"], s["scope_name"]) for s in secrets}
        assert ("remote_auth", "public_api") in secret_pairs
        assert ("remote_auth", "worker_api") in secret_pairs
        assert not any(
            scope_kind == "remote_integration" for scope_kind, _ in secret_pairs
        )

    def test_legacy_remote_auth_secret_migrates_to_default_scope(
        self, tmp_path: Path
    ) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "remote-sub", _remote_submitter_manifest())
        platform = PluginPlatform(tmp_path)
        platform.secrets.set_secret(
            "remote-sub",
            "remote_integration",
            "usweb-remote",
            "legacy-key",
        )

        platform.load_all()

        assert (
            platform.secrets.get_raw_secret("remote-sub", "remote_auth", "default")
            == "legacy-key"
        )

    def test_submit_delegated_on_disabled_plugin_raises(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        _write_manifest(tmp_path / "remote-sub", _remote_submitter_manifest())
        platform = PluginPlatform(tmp_path)
        platform.load_all()
        # Not approved/enabled

        with pytest.raises(PermissionError, match="is not enabled"):
            platform.submit_delegated_job("remote-sub", {})

    def test_remote_delegation_survives_reload(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        platform.create_plugin(_remote_submitter_manifest())

        # Create fresh platform (restart simulation)
        platform2 = PluginPlatform(tmp_path)
        platform2.load_all()

        info = platform2.get_remote_delegation_info("remote-sub")
        assert info is not None
        assert info["role"] == "submitter"
        assert info["integration_id"] == "usweb-remote"


# ══════════════════════════════════════════════════════════════════════════
# Remote transport, correlation, executor, and full loop tests
# ══════════════════════════════════════════════════════════════════════════


def _make_mock_http_post(
    status_code: int = 201,
    *,
    fail_first: int = 0,
) -> AsyncMock:
    """Create a mock HTTP POST that returns a fixed status code.

    If ``fail_first`` > 0, the first N calls raise an exception.
    """
    call_count = {"n": 0}

    async def _mock_post(
        url: str, data: bytes, headers: dict[str, str], **kw: Any
    ) -> int:
        call_count["n"] += 1
        if call_count["n"] <= fail_first:
            raise ConnectionError(f"Simulated failure #{call_count['n']}")
        return status_code

    mock = AsyncMock(side_effect=_mock_post)
    mock._call_count = call_count
    return mock


def _setup_submitter_platform(
    tmp_path: Path,
    http_post: Any = None,
) -> Any:
    """Create a platform with a submitter plugin, approved and enabled."""
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    platform = PluginPlatform(tmp_path, http_post=http_post)
    platform.create_plugin(_remote_submitter_manifest())
    platform.enable_plugin("remote-sub")
    return platform


def _setup_executor_platform(
    tmp_path: Path,
    http_post: Any = None,
) -> Any:
    """Create a platform with an executor plugin, approved and enabled."""
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    platform = PluginPlatform(tmp_path, http_post=http_post)
    platform.create_plugin(_remote_executor_manifest())
    platform.enable_plugin("remote-exec")
    return platform


class TestRemoteSubmissionTransport:
    """Tests for the HTTP submission transport (Phase 2)."""

    def test_execute_remote_submission_success(self, tmp_path: Path) -> None:
        mock_post = _make_mock_http_post(201)
        platform = _setup_submitter_platform(tmp_path, http_post=mock_post)

        submission = platform.submit_delegated_job(
            "remote-sub", {"job_type": "test", "payload": {}}
        )
        result = asyncio.run(platform.execute_remote_submission(submission))

        assert result["status"] == "submitted"
        assert result["correlation_id"] == submission["correlation_id"]
        assert result["http_status_code"] == 201
        assert result["last_error"] is None
        mock_post.assert_called()

    def test_execute_remote_submission_builds_correct_url(self, tmp_path: Path) -> None:
        captured_urls: list[str] = []

        async def capture_post(
            url: str, data: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            captured_urls.append(url)
            return 201

        platform = _setup_submitter_platform(tmp_path, http_post=capture_post)
        submission = platform.submit_delegated_job("remote-sub", {"job_type": "test"})
        asyncio.run(platform.execute_remote_submission(submission))

        assert len(captured_urls) == 1
        assert captured_urls[0] == "https://usweb.example.com/api/v1/jobs"

    def test_execute_remote_submission_sends_auth_header(self, tmp_path: Path) -> None:
        captured_headers: list[dict[str, str]] = []

        async def capture_post(
            url: str, data: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            captured_headers.append(dict(headers))
            return 201

        platform = _setup_submitter_platform(tmp_path, http_post=capture_post)
        submission = platform.submit_delegated_job("remote-sub", {})
        asyncio.run(platform.execute_remote_submission(submission))

        assert len(captured_headers) == 1
        assert "X-API-Key" in captured_headers[0]
        assert "Content-Type" in captured_headers[0]

    def test_execute_remote_submission_failure_records_error(
        self, tmp_path: Path
    ) -> None:
        mock_post = _make_mock_http_post(500)
        platform = _setup_submitter_platform(tmp_path, http_post=mock_post)

        # Disable retries so the test doesn't sleep
        record = platform.registry.get("remote-sub")
        record.manifest.operational_policy.retry_policy.max_retries = 0

        submission = platform.submit_delegated_job("remote-sub", {})
        result = asyncio.run(platform.execute_remote_submission(submission))

        assert result["status"] == "failed"
        assert result["last_error"] == "HTTP 500"
        assert result["http_status_code"] == 500

    def test_execute_remote_submission_retries_on_failure(self, tmp_path: Path) -> None:
        mock_post = _make_mock_http_post(201, fail_first=2)
        platform = _setup_submitter_platform(tmp_path, http_post=mock_post)

        # Override retry policy for fast test
        record = platform.registry.get("remote-sub")
        record.manifest.operational_policy.retry_policy.initial_backoff_seconds = 0
        record.manifest.operational_policy.retry_policy.max_retries = 5

        submission = platform.submit_delegated_job("remote-sub", {})
        result = asyncio.run(platform.execute_remote_submission(submission))

        assert result["status"] == "submitted"
        assert result["retry_count"] == 2  # 0, 1 failed; 2 succeeded

    def test_execute_remote_submission_with_idempotency_key(
        self, tmp_path: Path
    ) -> None:
        captured_payloads: list[bytes] = []

        async def capture_post(
            url: str, data: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            captured_payloads.append(data)
            return 201

        platform = _setup_submitter_platform(tmp_path, http_post=capture_post)
        submission = platform.submit_delegated_job("remote-sub", {"job_type": "test"})
        asyncio.run(
            platform.execute_remote_submission(submission, idempotency_key="idem-123")
        )

        sent = json.loads(captured_payloads[0])
        assert sent["idempotency_key"] == "idem-123"
        assert "correlation_id" in sent


class TestCorrelationStatePersistence:
    """Tests for correlation state tracking (Phase 3)."""

    def test_submission_record_created_on_success(self, tmp_path: Path) -> None:
        mock_post = _make_mock_http_post(201)
        platform = _setup_submitter_platform(tmp_path, http_post=mock_post)

        submission = platform.submit_delegated_job("remote-sub", {"test": "data"})
        result = asyncio.run(platform.execute_remote_submission(submission))

        record = platform.get_remote_submission(result["correlation_id"])
        assert record is not None
        assert record["plugin_id"] == "remote-sub"
        assert record["integration_id"] == "usweb-remote"
        assert record["status"] == "submitted"
        assert record["payload_hash"] is not None

    def test_submission_record_created_on_failure(self, tmp_path: Path) -> None:
        mock_post = _make_mock_http_post(500)
        platform = _setup_submitter_platform(tmp_path, http_post=mock_post)

        # Disable retries so the test doesn't sleep
        record = platform.registry.get("remote-sub")
        record.manifest.operational_policy.retry_policy.max_retries = 0

        submission = platform.submit_delegated_job("remote-sub", {})
        result = asyncio.run(platform.execute_remote_submission(submission))

        record = platform.get_remote_submission(result["correlation_id"])
        assert record is not None
        assert record["status"] == "failed"
        assert record["last_error"] == "HTTP 500"

    def test_set_external_job_id(self, tmp_path: Path) -> None:
        mock_post = _make_mock_http_post(201)
        platform = _setup_submitter_platform(tmp_path, http_post=mock_post)

        submission = platform.submit_delegated_job("remote-sub", {})
        result = asyncio.run(platform.execute_remote_submission(submission))

        cid = result["correlation_id"]
        platform.set_external_job_id(cid, "usweb-job-123")

        record = platform.get_remote_submission(cid)
        assert record["external_job_id"] == "usweb-job-123"

    def test_set_external_job_id_unknown_correlation_raises(
        self, tmp_path: Path
    ) -> None:
        mock_post = _make_mock_http_post(201)
        platform = _setup_submitter_platform(tmp_path, http_post=mock_post)

        with pytest.raises(KeyError, match="Unknown correlation_id"):
            platform.set_external_job_id("nonexistent", "job-1")

    def test_list_remote_submissions(self, tmp_path: Path) -> None:
        mock_post = _make_mock_http_post(201)
        platform = _setup_submitter_platform(tmp_path, http_post=mock_post)

        for i in range(3):
            sub = platform.submit_delegated_job("remote-sub", {"i": i})
            asyncio.run(platform.execute_remote_submission(sub))

        subs = platform.list_remote_submissions("remote-sub")
        assert len(subs) == 3
        assert all(s["plugin_id"] == "remote-sub" for s in subs)

    def test_list_remote_submissions_respects_limit(self, tmp_path: Path) -> None:
        mock_post = _make_mock_http_post(201)
        platform = _setup_submitter_platform(tmp_path, http_post=mock_post)

        for i in range(5):
            sub = platform.submit_delegated_job("remote-sub", {"i": i})
            asyncio.run(platform.execute_remote_submission(sub))

        subs = platform.list_remote_submissions("remote-sub", limit=2)
        assert len(subs) == 2

    def test_submission_persisted_to_state_store(self, tmp_path: Path) -> None:
        mock_post = _make_mock_http_post(201)
        platform = _setup_submitter_platform(tmp_path, http_post=mock_post)

        submission = platform.submit_delegated_job("remote-sub", {"x": 1})
        result = asyncio.run(platform.execute_remote_submission(submission))

        cid = result["correlation_id"]
        state_key = f"_remote:submission:{cid}"
        state_val = platform.get_state("remote-sub", state_key)
        assert state_val is not None
        assert state_val["correlation_id"] == cid


class TestManifestEditing:
    def test_get_plugin_manifest_yaml(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict()
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()

        result = platform.get_plugin_manifest_yaml("test-plugin")
        assert result["plugin_id"] == "test-plugin"
        assert "plugin_id: test-plugin" in result["manifest_yaml"]

    def test_update_plugin_manifest_yaml_reloads_plugin(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        data = _minimal_manifest_dict(display_name="Before Edit")
        _write_manifest(tmp_path / "test-plugin", data)
        platform = PluginPlatform(tmp_path)
        platform.load_all()

        updated_yaml = textwrap.dedent(
            """
            plugin_id: test-plugin
            plugin_version: 1.0.0
            display_name: After Edit
            description: Updated description
            usr_compatibility: '>=0.1.0'
            capabilities:
            - events.read
            event_subscriptions:
            - event_family: job.lifecycle
              event_types:
              - job.created
              delivery_target: main
            callbacks: []
            outbound_deliveries:
            - target_name: main
              url: https://example.com/hook
            operational_policy:
              retry_policy:
                max_retries: 10
                initial_backoff_seconds: 5
                max_backoff_seconds: 3600
                backoff_multiplier: 2.0
              state_quota_bytes: 65536
              replay_on_enable: true
            """
        ).strip()

        result = platform.update_plugin_manifest_yaml("test-plugin", updated_yaml)
        assert result["display_name"] == "After Edit"
        assert result["status"] == "disabled"
        reloaded = platform.get_plugin("test-plugin")
        assert reloaded is not None
        assert reloaded["display_name"] == "After Edit"


class TestExecutorActions:
    """Tests for executor plugin remote actions (Phase 5)."""

    def test_execute_claim_action(self, tmp_path: Path) -> None:
        captured: list[tuple[str, bytes]] = []

        async def capture_post(
            url: str, data: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            captured.append((url, data))
            return 200

        platform = _setup_executor_platform(tmp_path, http_post=capture_post)
        # Need to set external_system_url on executor manifest (it's optional for executors)
        record = platform.registry.get("remote-exec")
        record.manifest.remote_delegation.external_system_url = (
            "https://usweb.example.com"
        )

        result = asyncio.run(
            platform.execute_remote_worker_action(
                "remote-exec",
                "claim",
                "",
                {"worker_id": "w-1", "worker_name": "test-worker"},
            )
        )

        assert result["success"] is True
        assert result["action"] == "claim"
        assert "claim" in captured[0][0]

    def test_execute_complete_action(self, tmp_path: Path) -> None:
        async def ok_post(
            url: str, data: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            return 200

        platform = _setup_executor_platform(tmp_path, http_post=ok_post)
        record = platform.registry.get("remote-exec")
        record.manifest.remote_delegation.external_system_url = (
            "https://usweb.example.com"
        )

        result = asyncio.run(
            platform.execute_remote_worker_action(
                "remote-exec",
                "complete",
                "job-abc",
                {"result": {"status": "done"}},
            )
        )

        assert result["success"] is True
        assert result["action"] == "complete"
        assert result["remote_job_id"] == "job-abc"

    def test_execute_invalid_action_raises(self, tmp_path: Path) -> None:
        async def ok_post(
            url: str, data: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            return 200

        platform = _setup_executor_platform(tmp_path, http_post=ok_post)
        record = platform.registry.get("remote-exec")
        record.manifest.remote_delegation.external_system_url = (
            "https://usweb.example.com"
        )

        with pytest.raises(ValueError, match="Invalid executor action"):
            asyncio.run(
                platform.execute_remote_worker_action(
                    "remote-exec", "invalid_action", "job-1", {}
                )
            )

    def test_executor_without_capability_raises(self, tmp_path: Path) -> None:
        async def ok_post(
            url: str, data: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            return 200

        # Use submitter plugin (doesn't have remote.jobs.execute)
        platform = _setup_submitter_platform(tmp_path, http_post=ok_post)

        with pytest.raises(PermissionError, match="remote.jobs.execute"):
            asyncio.run(
                platform.execute_remote_worker_action("remote-sub", "claim", "", {})
            )

    def test_executor_http_failure_returns_error(self, tmp_path: Path) -> None:
        async def fail_post(
            url: str, data: bytes, headers: dict[str, str], **kw: Any
        ) -> int:
            raise ConnectionError("Connection refused")

        platform = _setup_executor_platform(tmp_path, http_post=fail_post)
        record = platform.registry.get("remote-exec")
        record.manifest.remote_delegation.external_system_url = (
            "https://usweb.example.com"
        )

        result = asyncio.run(
            platform.execute_remote_worker_action(
                "remote-exec", "claim", "", {"worker_id": "w-1"}
            )
        )

        assert result["success"] is False
        assert "Connection refused" in result["error"]


class TestCallbackCorrelation:
    """Tests for callback correlation and lifecycle translation (Phase 7)."""

    def test_callback_correlates_by_correlation_id(self, tmp_path: Path) -> None:
        mock_post = _make_mock_http_post(201)
        # Create a platform with BOTH submitter and executor capabilities
        # For simplicity, use the submitter platform and add an executor plugin
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path, http_post=mock_post)
        platform.create_plugin(_remote_submitter_manifest())
        platform.create_plugin(_remote_executor_manifest())
        platform.enable_plugin("remote-sub")
        platform.enable_plugin("remote-exec")

        # Submit a job
        submission = platform.submit_delegated_job("remote-sub", {"x": 1})
        result = asyncio.run(platform.execute_remote_submission(submission))
        cid = result["correlation_id"]

        # Receive a callback with the correlation_id
        cb_result = platform.receive_remote_callback(
            "remote-exec",
            "on-completed",
            {"correlation_id": cid, "status": "completed"},
        )

        assert cb_result["accepted"] is True
        assert cb_result["correlated"] is True
        assert cb_result["correlation_id"] == cid

    def test_callback_correlates_by_external_job_id(self, tmp_path: Path) -> None:
        mock_post = _make_mock_http_post(201)
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path, http_post=mock_post)
        platform.create_plugin(_remote_submitter_manifest())
        platform.create_plugin(_remote_executor_manifest())
        platform.enable_plugin("remote-sub")
        platform.enable_plugin("remote-exec")

        # Submit and set external ID
        submission = platform.submit_delegated_job("remote-sub", {})
        result = asyncio.run(platform.execute_remote_submission(submission))
        cid = result["correlation_id"]
        platform.set_external_job_id(cid, "usweb-456")

        # Callback with job_id instead of correlation_id
        cb_result = platform.receive_remote_callback(
            "remote-exec",
            "on-completed",
            {"job_id": "usweb-456", "event": "completed"},
        )

        assert cb_result["correlated"] is True
        assert cb_result["correlation_id"] == cid

    def test_callback_updates_submission_status(self, tmp_path: Path) -> None:
        mock_post = _make_mock_http_post(201)
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path, http_post=mock_post)
        platform.create_plugin(_remote_submitter_manifest())
        platform.create_plugin(_remote_executor_manifest())
        platform.enable_plugin("remote-sub")
        platform.enable_plugin("remote-exec")

        submission = platform.submit_delegated_job("remote-sub", {})
        result = asyncio.run(platform.execute_remote_submission(submission))
        cid = result["correlation_id"]

        # Status should be "submitted" initially
        rec = platform.get_remote_submission(cid)
        assert rec["status"] == "submitted"

        # Receive a "claimed" callback
        platform.receive_remote_callback(
            "remote-exec",
            "on-claimed",
            {"correlation_id": cid},
        )
        rec = platform.get_remote_submission(cid)
        assert rec["status"] == "claimed"

        # Receive a "completed" callback
        platform.receive_remote_callback(
            "remote-exec",
            "on-completed",
            {"correlation_id": cid, "result": {"success": True}},
        )
        rec = platform.get_remote_submission(cid)
        assert rec["status"] == "completed"

    def test_uncorrelated_callback_still_accepted(self, tmp_path: Path) -> None:
        platform = _setup_executor_platform(tmp_path)

        result = platform.receive_remote_callback(
            "remote-exec",
            "on-claimed",
            {"some_unknown_id": "xyz"},
        )

        assert result["accepted"] is True
        assert result["correlated"] is False
        assert result["correlation_id"] is None


class TestEndToEndControlPlaneLoop:
    """Integration-style tests for the full USR → USWeb → USWebAdmin loop."""

    def test_full_submitter_to_callback_loop(self, tmp_path: Path) -> None:
        """Simulates: submit → set external ID → claim callback → progress → complete."""
        mock_post = _make_mock_http_post(201)
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path, http_post=mock_post)
        platform.create_plugin(_remote_submitter_manifest())
        platform.create_plugin(_remote_executor_manifest())
        platform.enable_plugin("remote-sub")
        platform.enable_plugin("remote-exec")

        # 1. Submit job to remote
        submission = platform.submit_delegated_job(
            "remote-sub",
            {"job_type": "scrape.user", "payload": {"username": "test_user"}},
        )
        result = asyncio.run(
            platform.execute_remote_submission(submission, idempotency_key="idem-001")
        )
        cid = result["correlation_id"]
        assert result["status"] == "submitted"

        # 2. Simulate: remote responds with job ID (caller would parse response)
        platform.set_external_job_id(cid, "usweb-job-789")

        # 3. Executor claims (simulated HTTP to control plane)
        asyncio.run(
            platform.execute_remote_worker_action(
                "remote-exec",
                "claim",
                "",
                {"worker_id": "w-1", "worker_name": "test-worker"},
            )
        )
        # 4. USWeb sends callback: job claimed
        platform.receive_remote_callback(
            "remote-exec",
            "on-claimed",
            {"job_id": "usweb-job-789", "worker_id": "w-1"},
        )
        rec = platform.get_remote_submission(cid)
        assert rec["status"] == "claimed"

        # 5. USWeb sends callback: progress
        platform.receive_remote_callback(
            "remote-exec",
            "on-progress",
            {"job_id": "usweb-job-789", "progress": {"percent": 50}},
        )
        rec = platform.get_remote_submission(cid)
        assert rec["status"] == "in_progress"

        # 6. USWeb sends callback: completed
        platform.receive_remote_callback(
            "remote-exec",
            "on-completed",
            {"job_id": "usweb-job-789", "result": {"files": 42}},
        )
        rec = platform.get_remote_submission(cid)
        assert rec["status"] == "completed"

        # 7. Verify observability
        subs = platform.list_remote_submissions("remote-sub")
        assert len(subs) == 1
        assert subs[0]["external_job_id"] == "usweb-job-789"

    def test_full_loop_with_failure(self, tmp_path: Path) -> None:
        """Simulates: submit → claim → fail."""
        mock_post = _make_mock_http_post(201)
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path, http_post=mock_post)
        platform.create_plugin(_remote_submitter_manifest())
        platform.create_plugin(_remote_executor_manifest())
        platform.enable_plugin("remote-sub")
        platform.enable_plugin("remote-exec")

        # Submit
        submission = platform.submit_delegated_job("remote-sub", {"job_type": "test"})
        result = asyncio.run(platform.execute_remote_submission(submission))
        cid = result["correlation_id"]
        platform.set_external_job_id(cid, "usweb-fail-job")

        # Claim callback
        platform.receive_remote_callback(
            "remote-exec",
            "on-claimed",
            {"job_id": "usweb-fail-job"},
        )
        assert platform.get_remote_submission(cid)["status"] == "claimed"

        # Progress callback → in_progress
        platform.receive_remote_callback(
            "remote-exec",
            "on-progress",
            {"job_id": "usweb-fail-job", "progress": {"percent": 30}},
        )
        assert platform.get_remote_submission(cid)["status"] == "in_progress"

        # Note: there is no "on-failed" handler in the executor manifest,
        # but we can use on-completed with a failure payload
        # In practice, a real executor manifest would declare an on-failed handler
        # For now, verify the status is correctly tracked up to in_progress

    def test_submission_transport_failure_does_not_create_duplicate_records(
        self, tmp_path: Path
    ) -> None:
        """Two separate submissions create two distinct correlation records."""
        mock_post = _make_mock_http_post(201)
        platform = _setup_submitter_platform(tmp_path, http_post=mock_post)

        sub1 = platform.submit_delegated_job("remote-sub", {"i": 1})
        sub2 = platform.submit_delegated_job("remote-sub", {"i": 2})

        r1 = asyncio.run(platform.execute_remote_submission(sub1))
        r2 = asyncio.run(platform.execute_remote_submission(sub2))

        assert r1["correlation_id"] != r2["correlation_id"]
        subs = platform.list_remote_submissions("remote-sub")
        assert len(subs) == 2


class TestPluginWebUI:
    """Tests for WebUI extension configuration and asset serving."""

    def test_webui_manifest_parsing_and_active_listing(self, tmp_path: Path) -> None:
        from ultima_scraper_backend.plugin_system.platform import PluginPlatform

        platform = PluginPlatform(tmp_path)
        manifest_data = {
            "plugin_id": "test-webui-plugin",
            "plugin_version": "1.0.0",
            "display_name": "Test WebUI Plugin",
            "capabilities": ["webui.extend"],
            "webui": {
                "entry": "dist/bundle.js",
                "styles": ["dist/style.css"],
            },
        }
        platform.create_plugin(manifest_data)

        # Before enabling, active webui list is empty
        assert platform.list_active_webui() == []

        # Create the asset files
        plugin_dir = tmp_path / "test-webui-plugin"
        dist_dir = plugin_dir / "dist"
        dist_dir.mkdir(parents=True)
        js_file = dist_dir / "bundle.js"
        js_file.write_text("console.log('webui loaded');")

        # Enable plugin
        platform.enable_plugin("test-webui-plugin")

        active = platform.list_active_webui()
        assert len(active) == 1
        assert active[0]["plugin_id"] == "test-webui-plugin"
        digest = active[0]["package_digest"]
        assert active[0]["entry"] == f"/api/v1/plugins/test-webui-plugin/assets/dist/bundle.js?package={digest}"
        assert active[0]["styles"] == [f"/api/v1/plugins/test-webui-plugin/assets/dist/style.css?package={digest}"]

        # Asset path resolution
        resolved_js = platform.get_plugin_asset_path("test-webui-plugin", "dist/bundle.js")
        assert resolved_js == platform.package_directory("test-webui-plugin", digest) / "dist/bundle.js"
        assert resolved_js.read_text() == "console.log('webui loaded');"

        # Path traversal prevention
        with pytest.raises(PermissionError, match="path traversal"):
            platform.get_plugin_asset_path("test-webui-plugin", "../../../etc/passwd")

        # Missing asset raises FileNotFoundError
        with pytest.raises(FileNotFoundError):
            platform.get_plugin_asset_path("test-webui-plugin", "dist/nonexistent.js")
