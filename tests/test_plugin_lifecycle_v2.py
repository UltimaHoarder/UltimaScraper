from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
import yaml


def _manifest(
    *,
    capabilities: list[str] | None = None,
    compatibility: str = ">=0.1.0",
) -> dict[str, object]:
    return {
        "manifest_schema_version": 1,
        "plugin_id": "lifecycle-plugin",
        "plugin_version": "1.0.0",
        "display_name": "Lifecycle Plugin",
        "usr_compatibility": compatibility,
        "capabilities": capabilities or ["events.read"],
        "event_subscriptions": [],
        "outbound_deliveries": [],
    }


def _write_manifest(plugins_dir: Path, payload: dict[str, object]) -> Path:
    plugin_dir = plugins_dir / str(payload["plugin_id"])
    plugin_dir.mkdir(parents=True)
    manifest_path = plugin_dir / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return manifest_path


def test_manifest_rejects_invalid_compatibility_range() -> None:
    from ultima_scraper_backend.plugin_system.manifest import load_manifest_from_dict

    with pytest.raises(Exception, match="valid version range"):
        load_manifest_from_dict(_manifest(compatibility="definitely-not-a-range"))


def test_incompatible_plugin_cannot_be_enabled(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    _write_manifest(tmp_path, _manifest(compatibility=">=999.0.0"))
    platform = PluginPlatform(tmp_path)
    platform.load_all()

    preflight = platform.preflight_plugin("lifecycle-plugin")
    assert preflight["ready"] is False
    assert "does not satisfy" in preflight["summary"]
    with pytest.raises(ValueError, match="does not satisfy"):
        platform.enable_plugin("lifecycle-plugin")


def test_capability_expansion_requires_reapproval(tmp_path: Path) -> None:
    from ultima_scraper_backend.plugin_system.platform import PluginPlatform

    manifest_path = _write_manifest(tmp_path, _manifest())
    platform = PluginPlatform(tmp_path)
    platform.load_all()
    enabled = platform.enable_plugin("lifecycle-plugin")
    assert enabled["status"] == "enabled"
    assert enabled["granted_capabilities"] == ["events.read"]

    expanded = _manifest(capabilities=["events.read", "workers.status.read"])
    updated = platform.update_plugin_manifest_yaml(
        "lifecycle-plugin",
        yaml.safe_dump(expanded, sort_keys=False),
    )
    assert updated["status"] == "disabled"
    assert updated["health_status"] == "approval_required"
    assert updated["pending_capabilities"] == ["workers.status.read"]
    assert manifest_path.exists()

    with pytest.raises(ValueError, match="approval required"):
        platform.enable_plugin("lifecycle-plugin")

    approved = platform.approve_capabilities("lifecycle-plugin")
    assert approved["pending_capabilities"] == []
    assert platform.enable_plugin("lifecycle-plugin")["status"] == "enabled"


def test_plugin_secrets_are_encrypted_at_rest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_db_archive.crypto import get_secret_crypto
    from ultima_scraper_backend.plugin_system.secrets import SecretManager

    monkeypatch.setenv("USR_ENCRYPT_SECRETS", "true")
    monkeypatch.setenv("USR_SECRET_KEY", "plugin-test-master-key")
    get_secret_crypto.cache_clear()
    try:
        storage_path = tmp_path / "secrets.json"
        manager = SecretManager(storage_path)
        raw_secret = manager.create_secret("lifecycle-plugin", "outbound", "main")

        stored_text = storage_path.read_text(encoding="utf-8")
        stored = json.loads(stored_text)
        assert raw_secret not in stored_text
        assert stored["secrets"][0]["active_secret_value"].startswith("enc:v1:")
        assert storage_path.stat().st_mode & 0o777 == 0o600

        restored = SecretManager(storage_path)
        assert restored.get_raw_secret("lifecycle-plugin", "outbound", "main") == raw_secret
    finally:
        get_secret_crypto.cache_clear()


@pytest.mark.asyncio
async def test_outbound_delivery_signs_with_the_shared_secret() -> None:
    from ultima_scraper_backend.plugin_system.delivery import (
        EventDeliveryEngine,
        EventEnvelope,
    )

    captured_headers: dict[str, str] = {}

    async def http_post(
        _url: str,
        _body: bytes,
        headers: dict[str, str],
    ) -> int:
        captured_headers.update(headers)
        return 204

    engine = EventDeliveryEngine(http_post=http_post)
    envelope = EventEnvelope(
        event_family="plugin.lifecycle",
        event_type="plugin.enabled",
        plugin_id="lifecycle-plugin",
        body={"enabled": True},
    )
    secret = "shared-callback-secret"
    await engine.deliver(
        envelope,
        url="https://plugin.example/events",
        target_name="events",
        signing_secret=secret,
        retry_policy_max_retries=0,
    )

    expected = hmac.new(
        secret.encode(),
        envelope.to_json_bytes(),
        hashlib.sha256,
    ).hexdigest()
    assert captured_headers["X-Plugin-Signature"] == f"sha256={expected}"
