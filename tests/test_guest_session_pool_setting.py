"""The guest session pool is a network setting, on by default."""

import logging
from types import SimpleNamespace

from ultima_scraper_backend.config import Network
from ultima_scraper_backend.job_system import guest_sessions
from ultima_scraper_backend.job_system.guest_sessions import configure_guest_session_pool


def proxies(*connections):
    return [SimpleNamespace(url=f"http://proxy-{i}.example:8000", enabled=True, max_connections=c)
            for i, c in enumerate(connections)]


def configure(monkeypatch, enabled, connections):
    monkeypatch.setattr("ultima_scraper_backend.usapi_initializer.resolve_proxy_url", lambda url: url)
    site_api = SimpleNamespace()
    active = configure_guest_session_pool(
        site_api, proxies(*connections), enabled=enabled, worker_index=1, worker_count=8,
    )
    return active, getattr(site_api, "_guest_session_pool", None)


def test_pool_is_on_by_default():
    assert Network().guest_session_pool is True
    assert Network(guest_session_pool=False).guest_session_pool is False


def test_enabled_pool_shards_each_route(monkeypatch):
    active, pool = configure(monkeypatch, True, (26, 8))
    assert active and pool is not None
    assert [len(keys) for keys in pool.slots.values()] == [4, 1]  # worker 1 of 8


def test_disabled_setting_leaves_guest_sessions_unpooled(monkeypatch):
    active, pool = configure(monkeypatch, False, (26,))
    assert not active and pool is None


def test_a_proxy_with_fewer_connections_than_workers_keeps_the_pool(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger=guest_sessions.__name__):
        active, pool = configure(monkeypatch, True, (26, 4))
    assert active and pool is not None
    assert "Guest session pool disabled" not in caplog.text


def _saved_network(monkeypatch, network):
    from ultima_scraper_backend import config as config_module

    saved = SimpleNamespace(settings=SimpleNamespace(network=network))
    monkeypatch.setattr(
        config_module.UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        classmethod(lambda cls: saved),
    )


def test_a_proxy_edited_after_startup_rebuilds_the_pool(monkeypatch):
    active, pool = configure(monkeypatch, True, (8,))
    site_api = SimpleNamespace(_guest_session_pool=pool)
    pool.built_at -= guest_sessions.GUEST_POOL_REBUILD_INTERVAL_SECONDS
    edited = "http://192.0.2.7:8000"
    _saved_network(monkeypatch, SimpleNamespace(
        proxies=[SimpleNamespace(url=edited, enabled=True, max_connections=8)],
        guest_session_pool=True,
    ))

    rebuilt = guest_sessions._guest_session_pool_for(site_api, edited)

    assert rebuilt is site_api._guest_session_pool is not pool
    assert list(rebuilt.slots) == [edited]
    assert (rebuilt.worker_index, rebuilt.worker_count) == (1, 8)
    assert rebuilt.select(site_api, edited)


def test_a_new_pool_is_not_rebuilt_for_every_unknown_route(monkeypatch):
    active, pool = configure(monkeypatch, True, (8,))
    site_api = SimpleNamespace(_guest_session_pool=pool)

    def load():
        raise AssertionError("settings were read again")

    from ultima_scraper_backend import config as config_module

    monkeypatch.setattr(
        config_module.UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        classmethod(lambda cls: load()),
    )

    assert guest_sessions._guest_session_pool_for(site_api, "http://192.0.2.8:8000") is pool


def test_a_worker_settings_reload_rebuilds_guest_routes(monkeypatch):
    from ultima_scraper_backend.job_system import guest_route_permits
    from ultima_scraper_backend.workers.worker_pool import Worker

    monkeypatch.setattr("ultima_scraper_backend.usapi_initializer.resolve_proxy_url", lambda url: url)
    permits = []
    monkeypatch.setattr(
        guest_route_permits, "configure_route_permits",
        lambda client, proxies, **_: permits.append([p.url for p in proxies]),
    )
    site_api = SimpleNamespace(_guest_session_pool=None)
    worker = Worker.__new__(Worker)
    worker.apis = {"OnlyFans": site_api}
    worker.worker_index, worker.worker_count, worker.redis = 0, 2, None
    edited = "http://192.0.2.9:8000"
    config = SimpleNamespace(settings=SimpleNamespace(network=SimpleNamespace(
        proxies=[SimpleNamespace(url=edited, enabled=True, max_connections=4)],
        guest_session_pool=True,
    )))

    worker._refresh_guest_routes(config)

    assert list(site_api._guest_session_pool.slots) == [edited]
    assert permits == [[edited]]
