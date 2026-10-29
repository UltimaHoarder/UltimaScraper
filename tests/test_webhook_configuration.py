"""Webhook routing validation, persistence, and outgoing delivery regressions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ultima_scraper_backend.api.routes import webhooks as routes
from ultima_scraper_backend.config import UltimaScraperCollectionConfig
from ultima_scraper_backend.redis_channels import AUTH_EVENTS_CHANNEL, HOOKS_CHANNEL, WEBSOCKET_STREAM_CHANNEL
from ultima_scraper_backend.services.webhook_delivery import WebhookDeliveryService, classify_hooks, plan_deliveries, request_payload
from ultima_scraper_backend.webhook_config import SiteWebhookRouting, WebhookDestination, WebhookRule, effective_site_routing


def site_routing():
    return SiteWebhookRouting(
        destinations=[WebhookDestination(id="ops", name="Operations", url="https://hooks.example.test/ops"), WebhookDestination(id="archive", name="Archive", url="https://hooks.example.test/archive", format="discord")],
        rules=[WebhookRule(id="notifications", name="Notifications", hooks=["auth", "chat_message", "subscriber"], destination_ids=["ops", "archive"], hide_info=["username"])],
    )


@pytest.fixture
def config():
    result = UltimaScraperCollectionConfig()
    result.is_configured = True
    result._settings_version = 14
    result.settings.webhook_routing.onlyfans = site_routing()
    return result


def test_existing_single_urls_become_reusable_destinations_without_changing_legacy_settings():
    config = UltimaScraperCollectionConfig()
    config.site_apis.onlyfans.webhooks.auth.url = "https://hooks.example.test/shared"
    config.site_apis.onlyfans.webhooks.auth.active = True
    config.site_apis.onlyfans.webhooks.auth.hide_info = ["username"]
    config.site_apis.onlyfans.webhooks.download.url = "https://hooks.example.test/shared"
    result = effective_site_routing(config, "onlyfans")
    assert len(result.destinations) == 1
    assert [rule.hooks for rule in result.rules] == [["auth"], ["download"]]
    assert result.rules[0].hide_info == ["username"]
    assert result.destinations[0].format == "discord"
    assert config.settings.webhook_routing.onlyfans is None


@pytest.mark.parametrize("change", [
    {"rules": [{"id": "r", "name": "R", "hooks": [], "destination_ids": ["ops"]}]},
    {"rules": [{"id": "r", "name": "R", "hooks": ["auth"], "destination_ids": ["missing"]}]},
    {"destinations": [{"id": "ops", "name": "Ops", "url": "file:///tmp/no"}]},
    {"destinations": [{"id": "ops", "name": "Ops", "url": "https://user:secret@example.test/hook"}]},
])
def test_invalid_routes_are_rejected(change):
    payload = site_routing().model_dump()
    payload.update(change)
    with pytest.raises(ValidationError):
        SiteWebhookRouting.model_validate(payload)


@pytest.mark.asyncio
async def test_save_persists_multiple_hooks_and_destinations_at_expected_revision(monkeypatch, config):
    monkeypatch.setattr(routes, "get_config", lambda: config)
    monkeypatch.setattr(routes, "validate_outbound_url", Mock())
    snapshot = SimpleNamespace(version=15)
    def persist(candidate, *, expected_version):
        assert expected_version == 14
        assert candidate.settings.webhook_routing.onlyfans.rules[0].hooks == ["auth", "chat_message", "subscriber"]
        candidate._settings_version = 15
        return snapshot
    monkeypatch.setattr(routes, "persist_config_snapshot", persist)
    result = await routes.update_webhook_configuration("onlyfans", routes.WebhookConfigurationUpdate(expected_version=14, routing=site_routing()))
    assert result.version == 15
    assert len(result.sites["onlyfans"].destinations) == 2
    summary = await routes.get_webhooks()
    assert summary.sites.onlyfans.auth.active
    assert summary.sites.onlyfans.auth.url == "https://hooks.example.test/ops"
    assert len(summary.configuration.catalog) == 11


@pytest.mark.asyncio
async def test_stale_save_and_unsupported_site_hooks_do_not_write(monkeypatch, config):
    monkeypatch.setattr(routes, "get_config", lambda: config)
    monkeypatch.setattr(routes, "validate_outbound_url", Mock())
    persist = Mock()
    monkeypatch.setattr(routes, "persist_config_snapshot", persist)
    with pytest.raises(HTTPException) as stale:
        await routes.update_webhook_configuration("onlyfans", routes.WebhookConfigurationUpdate(expected_version=13, routing=site_routing()))
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as unsupported:
        await routes.update_webhook_configuration("fansly", routes.WebhookConfigurationUpdate(expected_version=14, routing=site_routing()))
    assert unsupported.value.status_code == 422
    persist.assert_not_called()


def test_supported_site_message_shapes_cover_notifications_and_skip_keepalives():
    event = {"source_id": "onlyfans:ws:42", "api2_chat_message": {"id": 10}, "post_published": {"id": 20}, "post_updated": 21, "online": [1], "new_message": {"subType": "new_subscriber_trial"}, "toasts": [{"data": {"code": code}} for code in ("new_stream", "new_comment", "price_changed_from_free", "price_changed_not_from_free")]}
    assert classify_hooks(WEBSOCKET_STREAM_CHANNEL, event) == {"site_message", "chat_message", "post_published", "post_updated", "online", "subscriber", "stream_started", "comment", "price_changed"}
    assert not classify_hooks(WEBSOCKET_STREAM_CHANNEL, {"source_id": "onlyfans:ws:42", "act": "ping"})
    assert not classify_hooks(WEBSOCKET_STREAM_CHANNEL, {"source_id": "fansly:ws:42", "api2_chat_message": {}})
    assert classify_hooks(AUTH_EVENTS_CHANNEL, {"event": "auth_updated"}) == {"auth"}
    assert not classify_hooks(HOOKS_CHANNEL, {"event": "download_progress", "status": "progress"})
    assert classify_hooks(HOOKS_CHANNEL, {"event": "download_progress", "status": "completed"}) == {"download"}


def test_multi_destination_fanout_deduplicates_overlapping_rules_and_redacts_nested_fields(config):
    config.settings.webhook_routing.onlyfans.rules.append(WebhookRule(id="overlap", name="Everything", hooks=["site_message"], destination_ids=["ops"], hide_info=["private_field"]))
    event = {"id": "evt-1", "source_id": "onlyfans:ws:42", "username": "account", "api2_chat_message": {"password": "secret", "cookie": "secret", "private_field": "private", "username": "creator", "text": "Hi"}}
    deliveries = plan_deliveries(config, WEBSOCKET_STREAM_CHANNEL, event)
    assert len(deliveries) == 2
    assert deliveries[0].envelope["hooks"] == ["chat_message", "site_message"]
    assert deliveries[0].envelope["data"]["api2_chat_message"] == {"text": "Hi"}
    assert "username" not in deliveries[0].envelope["data"]
    assert "embeds" in request_payload(deliveries[1])
    assert request_payload(deliveries[1])["allowed_mentions"] == {"parse": []}
    assert not plan_deliveries(config, WEBSOCKET_STREAM_CHANNEL, {**event, "site": "fansly"})
    config.settings.webhook_routing.onlyfans.rules[0].active = False
    assert len(plan_deliveries(config, WEBSOCKET_STREAM_CHANNEL, event)) == 1


class FakeRedis:
    def __init__(self):
        self.values = {}
    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True
    async def get(self, key):
        return self.values.get(key)
    async def delete(self, key):
        self.values.pop(key, None)


class Response:
    def __init__(self, status):
        self.status = status
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_args):
        pass


@pytest.mark.asyncio
async def test_http_retries_and_shared_claim_prevent_double_delivery(monkeypatch, config):
    redis = FakeRedis()
    service = WebhookDeliveryService(SimpleNamespace(client=redis), lambda: config)
    service.config = config
    post = Mock(side_effect=[Response(503), Response(204)])
    service.session = SimpleNamespace(post=post)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    delivery = plan_deliveries(config, AUTH_EVENTS_CHANNEL, {"event": "auth_added", "site": "onlyfans", "auth_id": 42, "timestamp": "now"})[0]
    assert await service.deliver(delivery)
    assert not await service.deliver(delivery)
    assert post.call_count == 2
    assert post.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.kwargs["headers"]["X-Ultima-Event-ID"] == delivery.envelope["id"]
    assert redis.values[delivery.claim_key] == "delivered"


@pytest.mark.asyncio
async def test_rejected_destination_releases_claim_and_private_addresses_are_never_sent(config):
    redis = FakeRedis()
    service = WebhookDeliveryService(SimpleNamespace(client=redis), lambda: config)
    service.config = config
    post = Mock(return_value=Response(400))
    service.session = SimpleNamespace(post=post)
    delivery = plan_deliveries(config, AUTH_EVENTS_CHANNEL, {"event": "auth_added", "site": "onlyfans"})[0]
    assert not await service.deliver(delivery)
    assert delivery.claim_key not in redis.values
    assert post.call_count == 1
    config.settings.webhook_routing.onlyfans.destinations[0].url = "http://127.0.0.1/private"
    private = plan_deliveries(config, AUTH_EVENTS_CHANNEL, {"event": "auth_added", "site": "onlyfans"})[0]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(asyncio, "sleep", AsyncMock())
        assert not await service.deliver(private)
    assert post.call_count == 1


@pytest.mark.asyncio
async def test_disabled_rules_cancel_pending_deliveries(config):
    service = WebhookDeliveryService(SimpleNamespace(client=FakeRedis()), lambda: config)
    service.config = config
    post = Mock(return_value=Response(204))
    service.session = SimpleNamespace(post=post)
    pending = plan_deliveries(config, AUTH_EVENTS_CHANNEL, {"event": "auth_updated", "site": "onlyfans"})[0]
    config.settings.webhook_routing.onlyfans.rules[0].active = False
    assert not await service.deliver(pending)
    post.assert_not_called()
