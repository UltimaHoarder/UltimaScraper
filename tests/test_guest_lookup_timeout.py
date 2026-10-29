"""Guest lookup timeout is a first-class setting across network and proxies."""

from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from ultima_scraper_backend.config import Network, Proxy
from ultima_scraper_backend.job_system.handlers.scrape.handler import (
    DEFAULT_MPS_GUEST_LOOKUP_TIMEOUT_SECONDS,
    _resolve_mps_guest_lookup_timeout,
)


def test_guest_lookup_timeout_model_defaults_and_validation():
    net = Network()
    assert net.guest_lookup_timeout == 3.5

    custom = Network(guest_lookup_timeout=6.5)
    assert custom.guest_lookup_timeout == 6.5

    with pytest.raises(ValidationError):
        Network(guest_lookup_timeout=0.1)

    proxy = Proxy(url="http://test:8080")
    assert proxy.guest_lookup_timeout is None

    custom_proxy = Proxy(url="http://test:8080", guest_lookup_timeout=8.0)
    assert custom_proxy.guest_lookup_timeout == 8.0


def test_resolve_mps_guest_lookup_timeout_from_global_setting(monkeypatch):
    monkeypatch.delenv("ULTIMA_MPS_GUEST_LOOKUP_TIMEOUT", raising=False)

    config = SimpleNamespace(
        settings=SimpleNamespace(
            network=SimpleNamespace(
                guest_lookup_timeout=5.5,
                proxies=[],
            )
        )
    )
    context = SimpleNamespace(config=config, context={})
    assert _resolve_mps_guest_lookup_timeout(context, "http://proxy1:8080") == 5.5


def test_resolve_mps_guest_lookup_timeout_from_proxy_override(monkeypatch):
    monkeypatch.delenv("ULTIMA_MPS_GUEST_LOOKUP_TIMEOUT", raising=False)

    proxy1 = SimpleNamespace(url="http://proxy1:8080", guest_lookup_timeout=9.0)
    proxy2 = SimpleNamespace(url="http://proxy2:8080", guest_lookup_timeout=None)
    config = SimpleNamespace(
        settings=SimpleNamespace(
            network=SimpleNamespace(
                guest_lookup_timeout=4.0,
                proxies=[proxy1, proxy2],
            )
        )
    )
    context = SimpleNamespace(config=config, context={})

    # proxy1 has an explicit override of 9.0s
    assert _resolve_mps_guest_lookup_timeout(context, "http://proxy1:8080") == 9.0
    # proxy1 with credentials in route URL matches proxy1 config
    assert _resolve_mps_guest_lookup_timeout(context, "http://user:pass@proxy1:8080") == 9.0
    # proxy2 inherits global network setting of 4.0s
    assert _resolve_mps_guest_lookup_timeout(context, "http://proxy2:8080") == 4.0
    assert _resolve_mps_guest_lookup_timeout(context, "http://user:pass@proxy2:8080") == 4.0


def test_resolve_mps_guest_lookup_timeout_fallback_to_env_and_default(monkeypatch):
    # Without context, falls back to env var if set
    monkeypatch.setenv("ULTIMA_MPS_GUEST_LOOKUP_TIMEOUT", "7.2")
    assert _resolve_mps_guest_lookup_timeout(None) == 7.2

    # Without env var and without context, falls back to default 3.5s
    monkeypatch.delenv("ULTIMA_MPS_GUEST_LOOKUP_TIMEOUT", raising=False)
    assert _resolve_mps_guest_lookup_timeout(None) == DEFAULT_MPS_GUEST_LOOKUP_TIMEOUT_SECONDS


def test_guest_lookup_timeout_settings_update_and_persistence():
    from ultima_scraper_backend.api.routes.settings import (
        SettingsUpdateRequest,
        _config_to_response,
        _merge_model_update,
    )
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    config = UltimaScraperCollectionConfig.load_or_create_default_config()
    update = SettingsUpdateRequest(network={"guest_lookup_timeout": 6.0})
    raw_update = update.model_dump(mode="json", exclude_unset=True)

    _merge_model_update(
        config.settings.network,
        update.network,
        raw_update.get("network", {}),
    )
    assert config.settings.network.guest_lookup_timeout == 6.0

    # Serialization into SettingsResponse
    resp = _config_to_response(config)
    assert resp.network.guest_lookup_timeout == 6.0

    # Persistence payload
    payload = config.persistence_payload()
    assert payload["settings"]["network"]["guest_lookup_timeout"] == 6.0


@pytest.mark.asyncio
async def test_proxy_edit_route_guest_lookup_timeout():
    from ultima_scraper_backend.api.routes.proxies import (
        ProxyUpdateRequest,
        BulkProxyEditRequest,
        update_proxy,
        bulk_edit_proxies,
    )
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    config = UltimaScraperCollectionConfig.load_or_create_default_config()
    test_proxy = Proxy(url="http://62.105.205.21:5165", max_connections=10)
    config.settings.network.proxies = [test_proxy]

    # Update proxy with guest_lookup_timeout override
    req = ProxyUpdateRequest(guest_lookup_timeout=8.0)
    res = await update_proxy("http://62.105.205.21:5165", req, config=config)
    assert res.guest_lookup_timeout == 8.0
    assert test_proxy.guest_lookup_timeout == 8.0

    # Masked URL matching works (e.g. credentialed URL in path)
    req2 = ProxyUpdateRequest(guest_lookup_timeout=9.5)
    res2 = await update_proxy("http://user:pass@62.105.205.21:5165", req2, config=config)
    assert res2.guest_lookup_timeout == 9.5
    assert test_proxy.guest_lookup_timeout == 9.5

    # Setting guest_lookup_timeout to None clears the override
    req_clear = ProxyUpdateRequest(guest_lookup_timeout=None)
    res_clear = await update_proxy("http://62.105.205.21:5165", req_clear, config=config)
    assert res_clear.guest_lookup_timeout is None
    assert test_proxy.guest_lookup_timeout is None

    # Bulk edit proxies with guest_lookup_timeout
    bulk_req = BulkProxyEditRequest(
        proxy_urls=["http://62.105.205.21:5165"],
        guest_lookup_timeout=7.5,
    )
    bulk_res = await bulk_edit_proxies(bulk_req, config=config)
    assert bulk_res.updated_count == 1
    assert bulk_res.guest_lookup_timeout == 7.5
    assert test_proxy.guest_lookup_timeout == 7.5




def test_group_timeout_applies_between_proxy_and_network(monkeypatch):
    monkeypatch.delenv("ULTIMA_MPS_GUEST_LOOKUP_TIMEOUT", raising=False)
    own = Proxy(url="http://proxy1:8080", group="Proton", guest_lookup_timeout=9.0)
    grouped = Proxy(url="http://proxy2:8080", group="Proton")
    other = Proxy(url="http://proxy3:8080", group="Webshare")
    ungrouped = Proxy(url="http://proxy4:8080")
    network = Network(
        guest_lookup_timeout=4.0,
        proxies=[own, grouped, other, ungrouped],
        proxy_groups={"Proton": {"guest_lookup_timeout": 7.5}},
    )
    context = SimpleNamespace(config=SimpleNamespace(settings=SimpleNamespace(network=network)), context={})

    assert _resolve_mps_guest_lookup_timeout(context, "http://user:pass@proxy1:8080") == 9.0
    assert _resolve_mps_guest_lookup_timeout(context, "http://user:pass@proxy2:8080") == 7.5
    assert _resolve_mps_guest_lookup_timeout(context, "http://proxy3:8080") == 4.0
    assert _resolve_mps_guest_lookup_timeout(context, "http://proxy4:8080") == 4.0
    # Unknown route: the network default.
    assert _resolve_mps_guest_lookup_timeout(context, "http://unknown:1") == 4.0


def test_group_timeouts_survive_persistence_and_reach_the_api_config():
    network = Network(proxy_groups={"Proton": {"guest_lookup_timeout": 7.5}})
    restored = Network.model_validate_json(network.model_dump_json())
    assert restored.proxy_groups["Proton"].guest_lookup_timeout == 7.5
    assert restored.to_usapi_network().proxy_groups["Proton"].guest_lookup_timeout == 7.5
    with pytest.raises(ValidationError):
        Network(proxy_groups={"Proton": {"guest_lookup_timeout": 0.1}})


@pytest.mark.asyncio
async def test_group_settings_route_sets_reads_and_clears_the_group_timeout(monkeypatch):
    from unittest.mock import Mock

    from ultima_scraper_backend.api.routes import proxies as proxies_module

    p1 = Proxy(url="http://p1:1", group="Proton", max_connections=8)
    network = Network(proxies=[p1])
    config = SimpleNamespace(settings=SimpleNamespace(network=network))
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", Mock())

    req = proxies_module.GroupSettingsUpdateRequest(guest_lookup_timeout=8.0)
    res = await proxies_module.update_group_settings("Proton", req, config=config)
    assert res.guest_lookup_timeout == 8.0
    assert network.proxy_groups["Proton"].guest_lookup_timeout == 8.0
    assert p1.guest_lookup_timeout is None  # stored on the group, not copied
    assert (await proxies_module.get_group_settings("Proton", config=config)).guest_lookup_timeout == 8.0

    # A request that does not mention the timeout leaves it alone.
    await proxies_module.update_group_settings(
        "Proton", proxies_module.GroupSettingsUpdateRequest(max_connections=6), config=config
    )
    assert network.proxy_groups["Proton"].guest_lookup_timeout == 8.0

    # An explicit null clears it.
    cleared = proxies_module.GroupSettingsUpdateRequest.model_validate({"guest_lookup_timeout": None})
    await proxies_module.update_group_settings("Proton", cleared, config=config)
    assert "Proton" not in network.proxy_groups
