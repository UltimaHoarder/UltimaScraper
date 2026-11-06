from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest
from ultima_scraper_core.environment import read_env, update_env


def _write_key(args: tuple[str, str]) -> None:
    path, key = args
    update_env({key: "fixture"}, path)


def test_shared_environment_updates_preserve_unrelated_lines(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    original = '# Other application\nVAULT_URL="untouched"\nSECRET_KEY=fixture\n'
    path.write_text(original + "IS_SETUP=false\nIS_SETUP=false\n")
    update_env(
        {"DATABASE_URL": "postgresql://fixture.invalid/db", "IS_SETUP": "true"}, path
    )
    assert path.read_text().startswith(original)
    assert path.read_text().count("IS_SETUP=") == 1
    update_env({"IS_SETUP": None}, path)
    assert "IS_SETUP" not in read_env(path)
    assert read_env(path)["SECRET_KEY"] == "fixture"
    assert path.stat().st_mode & 0o777 == 0o600


def test_concurrent_environment_writers_do_not_lose_keys(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    with ProcessPoolExecutor(
        max_workers=4, mp_context=__import__("multiprocessing").get_context("spawn")
    ) as pool:
        list(pool.map(_write_key, [(str(path), f"KEY_{index}") for index in range(12)]))
    assert len(read_env(path)) == 12


def test_environment_round_trip_and_invalid_edit_preserve_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    value = ' spaces "quotes" \\ literal\\n and $dollars '
    update_env({"FIXTURE": value}, path)
    assert read_env(path)["FIXTURE"] == value
    before = path.read_bytes()
    with pytest.raises(ValueError, match="single-line"):
        update_env({"FIXTURE": "injected\nOTHER=value"}, path)
    assert path.read_bytes() == before


def test_persistence_payload_excludes_infrastructure_credentials() -> None:
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    config = UltimaScraperCollectionConfig()
    config.settings.redis.password = "redis-fixture"
    payload = config.persistence_payload()
    text = json.dumps(payload)
    assert "redis-fixture" not in text
    assert (
        not {"redis", "databases", "security", "hostname"} & payload["settings"].keys()
    )


def test_usapi_config_has_no_usr_fields_and_round_trips_standalone(tmp_path: Path) -> None:
    from ultima_scraper_api.config import Proxy as USAPIProxy, UltimaScraperAPIConfig
    from ultima_scraper_backend.config import (
        PluginProxyOwner,
        Proxy as USRProxy,
        UltimaScraperCollectionConfig,
    )

    api_proxy = USAPIProxy(url="http://proxy.example:8080")
    assert not hasattr(api_proxy, "managed_by")
    assert not hasattr(api_proxy, "downloads")

    api_config = UltimaScraperAPIConfig()
    assert not hasattr(api_config.settings.network, "plugin_sync_receipts")
    assert not hasattr(api_config.settings.network, "downloads")

    standalone_path = tmp_path / "usapi_config.json"
    api_config.settings.network.proxies.append(api_proxy)
    api_config.save_config(standalone_path)
    loaded = UltimaScraperAPIConfig.load_config(standalone_path)
    assert loaded.settings.network.proxies[0].url == "http://proxy.example:8080"

    usr_config = UltimaScraperCollectionConfig()
    usr_config.settings.network.proxies.append(
        USRProxy(
            url="http://usr-proxy.example:8080",
            managed_by=PluginProxyOwner(
                plugin_id="plugin", source="sync", provider_id="p1"
            ),
        )
    )
    converted = usr_config.to_usapi_config()
    assert isinstance(converted, UltimaScraperAPIConfig)
    assert converted.settings.network.proxies[0].url == "http://usr-proxy.example:8080"


def test_secret_walker_encrypts_proxy_passwords(monkeypatch) -> None:
    from ultima_scraper_backend import config

    payload = {
        "settings": {
            "network": {
                "proxies": [
                    {"url": "http://proxy.invalid:8080", "password": "fixture"}
                ]
            }
        }
    }
    monkeypatch.setattr(config, "encrypt_secret_value", lambda value: "encrypted")
    config.encrypt_config_secrets(payload)
    assert payload["settings"]["network"]["proxies"][0]["password"] == "encrypted"


def test_webhook_urls_are_encrypted_at_rest(monkeypatch) -> None:
    import copy

    from ultima_scraper_backend import config
    from ultima_scraper_db_archive.crypto import get_secret_crypto

    monkeypatch.setenv("USR_ENCRYPT_SECRETS", "true")
    monkeypatch.setenv("USR_SECRET_KEY", "webhook-fixture-key")
    get_secret_crypto.cache_clear()
    routed = "https://discord.com/api/webhooks/1/routed-token"
    legacy = "https://discord.com/api/webhooks/2/legacy-token"
    payload = {
        "settings": {
            "webhook_routing": {
                "onlyfans": {
                    "destinations": [{"id": "d1", "name": "Discord", "url": routed}],
                    "rules": [],
                },
                "fansly": None,
            }
        },
        "site_apis": {
            "onlyfans": {"webhooks": {"auth": {"url": legacy, "active": True}}},
            "loyalfans": {"webhooks": {"download": {"url": None, "active": False}}},
        },
    }
    try:
        stored = copy.deepcopy(payload)
        config.encrypt_config_secrets(stored)
        stored_routed = stored["settings"]["webhook_routing"]["onlyfans"]["destinations"][0]["url"]
        stored_legacy = stored["site_apis"]["onlyfans"]["webhooks"]["auth"]["url"]
        assert stored_routed.startswith("enc:v1:") and "routed-token" not in stored_routed
        assert stored_legacy.startswith("enc:v1:") and "legacy-token" not in stored_legacy
        assert stored["site_apis"]["loyalfans"]["webhooks"]["download"]["url"] is None

        config.decrypt_config_secrets(stored)
        assert stored == payload

        # Rows saved before this change hold plain URLs; they still load.
        plain = copy.deepcopy(payload)
        config.decrypt_config_secrets(plain)
        assert plain == payload
    finally:
        get_secret_crypto.cache_clear()


@pytest.mark.parametrize(
    "key",
    [
        "config",
        "db.connection",
        "redis.password",
        "download.directories",
        "network.config",
    ],
)
def test_raw_edits_cannot_bypass_application_settings(key: str) -> None:
    from fastapi import HTTPException
    from ultima_scraper_backend.api.routes.settings import _ensure_raw_setting_editable

    with pytest.raises(HTTPException) as error:
        _ensure_raw_setting_editable(key)
    assert error.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"hostname": "other"},
        {"redis": {"host": "other"}},
        {"security": {"allow_docs": True}},
        {"backend": {"backend_id": "other"}},
    ],
)
async def test_runtime_fields_cannot_be_written_through_application_settings(payload):
    from fastapi import HTTPException
    from ultima_scraper_backend.api.routes.settings import (
        SettingsUpdateRequest,
        update_settings,
    )

    with pytest.raises(HTTPException) as caught:
        await update_settings(SettingsUpdateRequest.model_validate(payload), None)
    assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_runtime_redis_settings_update_shared_environment_without_persisting_secret(
    monkeypatch,
):
    from ultima_scraper_backend.api.routes import settings as settings_module
    from ultima_scraper_backend.config import Redis, UltimaScraperCollectionConfig

    for name in settings_module._REDIS_ENVIRONMENT_KEYS:
        monkeypatch.delenv(name, raising=False)

    config = UltimaScraperCollectionConfig()
    config.settings.redis.password = "existing-secret"
    captured: dict[str, object | None] = {}

    def fake_update_env(values):
        captured.update(values)

    monkeypatch.setattr("ultima_scraper_core.update_env", fake_update_env)
    monkeypatch.setattr(
        settings_module.UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        classmethod(lambda cls: config),
    )

    response = await settings_module.update_runtime_redis_settings(
        Redis(
            host="redis.internal",
            port=6380,
            db=4,
            password=settings_module.SECRET_MASK,
            enabled=True,
        )
    )

    assert captured == {
        "REDIS_HOST": "redis.internal",
        "REDIS_PORT": 6380,
        "REDIS_DB": 4,
        "REDIS_ENABLED": "true",
    }
    assert "existing-secret" not in str(captured)
    assert response.runtime_restart_required is True

    replacement = settings_module._redis_environment_values(
        Redis(
            host="redis.internal",
            port=6380,
            db=4,
            password="replacement-secret",
            enabled=True,
        )
    )
    assert replacement["REDIS_URL"] is None
    assert replacement["REDIS_PASSWORD"] == "replacement-secret"


@pytest.mark.asyncio
async def test_runtime_redis_settings_reject_process_environment_override(monkeypatch):
    from fastapi import HTTPException
    from ultima_scraper_backend.api.routes import settings as settings_module
    from ultima_scraper_backend.config import Redis

    monkeypatch.setenv("REDIS_HOST", "process-owned")
    with pytest.raises(HTTPException) as caught:
        await settings_module.update_runtime_redis_settings(Redis(host="other"))

    assert caught.value.status_code == 409
    assert caught.value.detail["fields"] == ["REDIS_HOST"]


def test_masked_proxy_password_survives_unrelated_network_edit():
    from ultima_scraper_backend.api.routes.settings import _merge_model_update
    from ultima_scraper_backend.config import Network, Proxy

    current = Network(
        proxies=[
            Proxy(url="http://proxy.invalid", username="user", password="original")
        ]
    )
    raw = {
        "max_connections": 4,
        "proxies": [
            {"url": "http://proxy.invalid", "username": "user", "password": "********"}
        ],
    }
    _merge_model_update(current, Network.model_validate(raw), raw)
    assert current.proxies[0].password == "original"
    assert current.max_connections == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_engine", [False, True])
async def test_setup_preserves_other_projects_and_excludes_bootstrap_from_config(
    monkeypatch, tmp_path, existing_engine
):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from sqlalchemy.engine import make_url
    from ultima_scraper_backend.api.routes import setup
    from ultima_scraper_backend.config_settings_sync import PersistedConfigSnapshot
    from ultima_scraper_db_archive import global_db

    from ultima_scraper_backend import config_settings_sync
    from ultima_scraper_core import get_env_path, read_env

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    env = get_env_path()
    env.parent.mkdir(parents=True)
    env.write_text("VAULT_SETTING=keep-vault\nOTHER_ROOT_KEY=keep-key\n")
    engine = (
        SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://fixture:db-secret@db.invalid:5432/fixture"
            )
        )
        if existing_engine
        else None
    )
    monkeypatch.setattr(global_db, "get_postgres_engine", lambda: engine)
    monkeypatch.setattr(global_db, "set_postgres_url", MagicMock())
    monkeypatch.setattr(
        setup,
        "SettingsService",
        lambda: SimpleNamespace(invalidate=lambda: None, get_model=lambda *args: None),
    )
    persist = MagicMock(
        return_value=PersistedConfigSnapshot(1, "setup-fixture", 1, None)
    )
    monkeypatch.setattr(config_settings_sync, "persist_config_snapshot", persist)
    request = setup.InitialSetupRequest.model_validate(
        {
            "database": {
                "name": "fixture",
                "host": "db.invalid",
                "port": 5432,
                "username": "fixture",
                "password": "db-secret",
            },
            "redis": {"host": "redis.invalid", "password": "redis-secret"},
            "hostname": "setup-fixture",
        }
    )
    assert (await setup.complete_setup(request)).success
    values = read_env()
    assert values["VAULT_SETTING"] == "keep-vault"
    assert values["OTHER_ROOT_KEY"] == "keep-key"
    assert values["REDIS_PASSWORD"] == "redis-secret"
    stored = persist.call_args.args[0].persistence_payload()
    assert "db-secret" not in json.dumps(stored)
    assert "redis-secret" not in json.dumps(stored)


@pytest.mark.asyncio
async def test_setup_rejects_an_already_initialized_different_database(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from fastapi import HTTPException
    from sqlalchemy.engine import make_url
    from ultima_scraper_backend.api.routes import setup
    from ultima_scraper_db_archive import global_db

    engine = SimpleNamespace(
        url=make_url("postgresql://fixture:private@old.invalid/old")
    )
    monkeypatch.setattr(global_db, "get_postgres_engine", lambda: engine)
    settings_service = MagicMock()
    monkeypatch.setattr(setup, "SettingsService", settings_service)
    request = setup.InitialSetupRequest.model_validate(
        {
            "database": {
                "name": "new",
                "host": "new.invalid",
                "username": "fixture",
                "password": "different-private",
            }
        }
    )

    with pytest.raises(HTTPException) as caught:
        await setup.complete_setup(request)
    assert caught.value.status_code == 409
    assert "private" not in caught.value.detail
    settings_service.assert_not_called()
