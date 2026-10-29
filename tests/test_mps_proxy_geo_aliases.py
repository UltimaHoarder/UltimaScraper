"""Geographic selection uses the same proxy identities as the frozen pool."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from ultima_scraper_backend.config import UltimaScraperCollectionConfig
from ultima_scraper_backend.job_system import mps_tasks
from ultima_scraper_backend.usapi_initializer import resolve_proxy_url


def install_geo_cache(monkeypatch, rows, proxies):
    monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP", {})
    monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP_AT", 0.0)
    service = Mock()
    service.get_all_cached_geolocations.return_value = rows
    monkeypatch.setattr(
        "ultima_scraper_backend.helpers.ip_geolocation.get_geolocation_service",
        lambda: service,
    )
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=proxies))
    )
    monkeypatch.setattr(
        UltimaScraperCollectionConfig, "load_or_create_default_config", lambda: config
    )


def test_resolved_authenticated_proxies_keep_cached_countries(monkeypatch):
    proxies = [
        SimpleNamespace(
            url=f"http://proxy-{i}:8000",
            username="guest@example",
            password="p:a",
            enabled=True,
        )
        for i in range(4)
    ]
    countries = ["US", "US", "GB", "DE"]
    install_geo_cache(
        monkeypatch,
        [
            {"proxy_url": proxy.url, "country_code": country}
            for proxy, country in zip(proxies, countries)
        ],
        proxies,
    )
    pool = [resolve_proxy_url(proxy.url) for proxy in proxies]
    geo = mps_tasks.get_cached_proxy_geo_map()
    assert [geo[url] for url in pool] == countries
    primary, fallbacks, direct = mps_tasks._resolve_mps_task_routes(
        task_index=0, proxy_pool=pool, proxy_start_index=0, proxy_geo_map=geo
    )
    assert primary == pool[0]
    assert set(fallbacks) == {pool[2], pool[3]}
    assert direct is None
    reserves = mps_tasks._build_mps_route_alternatives(
        selected_proxy_urls=[primary, *fallbacks],
        route_offset=0,
        proxy_geo_map=geo,
        proxy_country_groups=mps_tasks._group_mps_proxy_countries(pool, geo),
    )
    assert reserves == {pool[0]: [pool[1]]}


@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_resolved_country_takes_precedence_over_alias(monkeypatch, reverse):
    proxy = SimpleNamespace(
        url="http://proxy:8000", username="user", password="pass", enabled=True
    )
    rows = [
        {"proxy_url": proxy.url, "country_code": "US"},
        {"proxy_url": "http://user:pass@proxy:8000", "country_code": "GB"},
    ]
    install_geo_cache(monkeypatch, list(reversed(rows)) if reverse else rows, [proxy])
    geo = mps_tasks.get_cached_proxy_geo_map()
    assert geo[proxy.url] == "US"
    assert geo[resolve_proxy_url(proxy.url)] == "GB"


def test_geo_map_rebuild_parses_config_once(monkeypatch):
    # A rebuild used to re-read the config for every cached identifier,
    # stalling refill under the planner lock for seconds.
    proxies = [
        SimpleNamespace(url=f"http://proxy-{i}:8000", username="u", password="p", enabled=True)
        for i in range(5)
    ]
    install_geo_cache(
        monkeypatch,
        [{"proxy_url": proxy.url, "country_code": "us"} for proxy in proxies],
        proxies,
    )
    config = UltimaScraperCollectionConfig.load_or_create_default_config()
    loads = Mock(return_value=config)
    monkeypatch.setattr(UltimaScraperCollectionConfig, "load_or_create_default_config", loads)
    geo = mps_tasks.get_cached_proxy_geo_map()
    assert loads.call_count == 1
    for proxy in proxies:
        assert geo[resolve_proxy_url(proxy.url, config=config)] == "US"
