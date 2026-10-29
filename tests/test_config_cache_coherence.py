from __future__ import annotations

import json

from ultima_scraper_api.config import Proxy, UltimaScraperAPIConfig


def test_save_config_replaces_the_file_atomically(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config = UltimaScraperAPIConfig()
    config.settings.network.proxies.append(Proxy(url="http://proxy.example:8080"))

    config.save_config(config_path)

    payload = json.loads(config_path.read_text())
    assert payload["settings"]["network"]["proxies"][0]["url"] == (
        "http://proxy.example:8080"
    )
    assert list(tmp_path.glob(".config.json.*.tmp")) == []


def test_get_config_observes_canonical_revisions_instead_of_disk(
    monkeypatch,
) -> None:
    from contextlib import contextmanager
    from types import SimpleNamespace

    from ultima_scraper_backend.api import dependencies

    from ultima_scraper_backend import config_settings_sync

    monkeypatch.setenv("DATABASE_URL", "postgresql://fixture.invalid/archive")
    monkeypatch.setenv("BACKEND_ID", "fixture-backend")
    row = SimpleNamespace(
        id=7,
        backend="fixture-backend",
        version=3,
        updated_at=None,
        value=json.dumps(
            {
                "configuration_schema_version": 2,
                "settings": {"worker_pool": {"size": 5}},
            }
        ),
    )

    @contextmanager
    def session():
        results = iter([None, row])
        yield SimpleNamespace(
            exec=lambda statement: SimpleNamespace(one_or_none=lambda: next(results))
        )

    monkeypatch.setattr(config_settings_sync, "get_global_session", session)

    first = dependencies.get_config()
    assert first._settings_version == 3
    assert first.settings.worker_pool.size == 5
    row.version = 4
    row.value = json.dumps(
        {"configuration_schema_version": 2, "settings": {"worker_pool": {"size": 9}}}
    )
    second = dependencies.get_config()
    assert second._settings_version == 4
    assert second.settings.worker_pool.size == 9


def test_runtime_reload_resolves_the_shared_scope(monkeypatch) -> None:
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig
    from ultima_scraper_backend.models.backend import BackendInstance

    config = UltimaScraperCollectionConfig()
    config.settings.backend.backend_id = "individual-host"
    config._settings_backend = "shared-workers"
    monkeypatch.setattr(
        UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        classmethod(lambda cls: config),
    )

    backend = object.__new__(BackendInstance)
    assert backend._get_local_settings_scope() == "shared-workers"
