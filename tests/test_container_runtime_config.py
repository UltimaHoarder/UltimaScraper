from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url
from ultima_scraper_backend.api.routes.setup import (
    DatabaseConnectionRequest,
    _build_database_url,
    _resolve_async_database_url,
)
from ultima_scraper_backend.config import UltimaScraperCollectionConfig
from ultima_scraper_db_archive import global_db


def test_runtime_config_uses_redis_environment_without_persisting_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("REDIS_HOST", "redis.internal")
    monkeypatch.setenv("REDIS_PORT", "30059")
    monkeypatch.setenv("REDIS_DB", "7")
    monkeypatch.setenv("REDIS_PASSWORD", "container-secret")

    config = UltimaScraperCollectionConfig.load_or_create_default_config()

    assert config.settings.redis.host == "redis.internal"
    assert config.settings.redis.port == 30059
    assert config.settings.redis.db == 7
    assert config.settings.redis.password == "container-secret"

    saved = config.persistence_payload()
    assert "redis" not in saved["settings"]
    assert "container-secret" not in json.dumps(saved)


def test_runtime_config_accepts_redis_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # This contract must not load local deployment settings or a live DB.
    monkeypatch.setattr("ultima_scraper_core.environment.get_env_path", lambda: tmp_path / ".env")
    for name in ("REDIS_HOST", "REDIS_PORT", "REDIS_DB", "REDIS_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://:p%40ss@redis.internal:6380/4")

    config = UltimaScraperCollectionConfig()
    config.settings.redis = config.settings.redis.model_copy(
        update={"host": "ignored", "port": 6379, "db": 0, "password": None}
    )
    monkeypatch.setattr(
        "ultima_scraper_backend.config_settings_sync.load_config_snapshot",
        lambda cls: config,
    )

    loaded = UltimaScraperCollectionConfig.load_or_create_default_config()

    assert loaded.settings.redis.host == "redis.internal"
    assert loaded.settings.redis.port == 6380
    assert loaded.settings.redis.db == 4
    assert loaded.settings.redis.password == "p@ss"


def test_postgres_bootstrap_prefers_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = "postgresql+psycopg://user:pass@postgres/usr_test"
    observed: list[str] = []
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(global_db, "_postgres_engine", None)
    monkeypatch.setattr(global_db, "set_postgres_url", observed.append)

    assert global_db.bootstrap_from_env() is True
    assert observed == [database_url]


def test_setup_database_url_prefers_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:pass@postgres/usr_test",
    )

    assert (
        _resolve_async_database_url()
        == "postgresql+asyncpg://user:pass@postgres/usr_test"
    )


def test_setup_database_url_encodes_reserved_credentials() -> None:
    request = DatabaseConnectionRequest(
        host="postgres.internal",
        port=5432,
        name="ultima_archive",
        username="user@example.test",
        password="p@ss:/?#[] value",
    )

    database_url = _build_database_url(
        request,
        drivername="postgresql+asyncpg",
    )
    parsed = make_url(database_url)

    assert parsed.drivername == "postgresql+asyncpg"
    assert parsed.username == request.username
    assert parsed.password == request.password
    assert parsed.host == request.host
    assert parsed.database == request.name


def test_setup_complete_ignores_legacy_environment_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Setup state is the stored config row; IS_SETUP no longer counts.
    monkeypatch.setenv("IS_SETUP", "true")
    monkeypatch.setattr(global_db, "archive_database_url", lambda: None)
    monkeypatch.setattr(global_db, "_setup_complete", False)

    assert global_db.is_setup_complete() is False
