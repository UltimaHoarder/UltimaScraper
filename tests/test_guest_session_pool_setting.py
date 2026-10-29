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
