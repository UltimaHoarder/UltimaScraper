from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from ultima_scraper_core import read_env

from ultima_scraper_backend import bootstrap, security
from ultima_scraper_backend.api.routes import setup


@pytest.fixture
def unconfigured_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> MagicMock:
    monkeypatch.setattr(setup, "_migration_runtime_dir", lambda: tmp_path)
    monkeypatch.setenv("USR_BACKEND_STARTUP_ID", "startup-a")
    monkeypatch.setenv("USR_ADMIN_TOKEN", "fixture-admin-token")
    monkeypatch.setenv("RUN_MODE", "api")
    monkeypatch.delenv("SECURITY_ENFORCEMENT", raising=False)
    monkeypatch.delenv("USR_ADMIN_TOKEN_REQUIRED", raising=False)
    settings_service = MagicMock()
    settings_service.return_value.is_configured.return_value = False
    monkeypatch.setattr(setup, "SettingsService", settings_service)
    return settings_service


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("USR_ADMIN_TOKEN", "replace-with-a-long-random-token"),
        ("USR_SECRET_KEY", "replace-with-a-separate-long-random-secret"),
        (
            "ULTIMA_ARCHIVE_DATABASE_URL",
            "postgresql+psycopg://usr:replace-with-your-password@db/ultima_archive",
        ),
    ],
)
def test_api_refuses_env_example_placeholders(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv("USR_ADMIN_TOKEN", "fixture-admin-token")
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=f"{name} still has the .env.example placeholder"):
        security.validate_security_configuration()


@pytest.mark.asyncio
async def test_setup_keeps_the_deployment_backend_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BACKEND_ID", "usr-docker")

    with pytest.raises(HTTPException) as caught:
        await setup.complete_setup(setup.InitialSetupRequest(hostname="my-scraper"))

    assert caught.value.status_code == 409
    assert "BACKEND_ID=usr-docker" in caught.value.detail


@pytest.mark.asyncio
async def test_setup_status_reports_the_deployment_backend_id(
    unconfigured_backend: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    unconfigured_backend.return_value.get_setup_status.return_value = {
        "is_configured": False,
        "has_config": False,
        "has_database": True,
        "data_directory": "/data",
    }
    monkeypatch.setenv("BACKEND_ID", "usr-docker")

    assert (await setup.get_setup_status()).backend_id == "usr-docker"


def test_bootstrap_fills_empty_env_example_secrets(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("USR_ADMIN_TOKEN=\nUSR_SECRET_KEY=keep-me\n")

    assert bootstrap.main(["--env-file", str(env_file)]) == 0

    values = read_env(env_file)
    assert len(values["USR_ADMIN_TOKEN"]) >= 32
    assert values["USR_SECRET_KEY"] == "keep-me"


def test_plugin_platform_starts_on_first_use_after_setup() -> None:
    from types import SimpleNamespace

    from ultima_scraper_backend.plugin_system.api_routes import resolve_plugin_platform

    created = object()
    attempts: list[str] = []

    def ensure_plugin_platform() -> object | None:
        attempts.append("ensure")
        # The schema appears once setup has run its migration.
        return created if len(attempts) > 1 else None

    app = SimpleNamespace(
        state=SimpleNamespace(plugin_platform=None, ensure_plugin_platform=ensure_plugin_platform)
    )

    assert resolve_plugin_platform(app) is None
    assert resolve_plugin_platform(app) is created
    app.state.plugin_platform = created
    assert resolve_plugin_platform(app) is created
    assert attempts == ["ensure", "ensure"]


@pytest.mark.parametrize(
    ("peer", "forwarded", "local"),
    [
        ("127.0.0.1", None, True),
        ("8.8.8.8", None, False),
        # Through a proxy, the last hop is the browser.
        ("172.18.0.5", "8.8.8.8, 192.168.1.20", True),
        # A spoofed private address before the proxy's own hop is ignored.
        ("172.18.0.5", "10.0.0.2, 8.8.8.8", False),
        ("172.18.0.5", "not-an-address", False),
    ],
)
def test_visitor_locality(peer: str, forwarded: str | None, local: bool) -> None:
    """The WebUI server's first-visitor rule."""
    from ultima_scraper_core.claims import visitor_is_local

    assert visitor_is_local(peer, forwarded) is local


def test_configured_connections_come_from_the_deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ULTIMA_ARCHIVE_DATABASE_URL",
        "postgresql+psycopg://usr:p%40ss@postgres:5433/ultima_archive",
    )
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_PASSWORD", "redis-secret")

    database = setup._configured_database_request()
    assert database is not None
    assert (database.host, database.port, database.name) == ("postgres", 5433, "ultima_archive")
    assert (database.username, database.password) == ("usr", "p@ss")
    redis = setup._configured_redis_request()
    assert redis is not None and redis.password == "redis-secret"
    assert setup._configured_redis_target() == "redis:6380"


@pytest.mark.asyncio
async def test_setup_with_the_configured_database_prepares_its_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared: list[str] = []

    async def prepare() -> setup.DatabaseConnectionResponse:
        prepared.append("schema")
        return setup.DatabaseConnectionResponse(success=False, message="no CREATE privilege")

    monkeypatch.setenv("ULTIMA_ARCHIVE_DATABASE_URL", "postgresql+psycopg://usr:pw@db/ultima_archive")
    monkeypatch.delenv("BACKEND_ID", raising=False)
    monkeypatch.delenv("USR_SCHEMA_MANAGEMENT_ENABLED", raising=False)
    monkeypatch.setattr(setup, "test_configured_database", prepare)

    with pytest.raises(HTTPException) as caught:
        await setup.complete_setup(setup.InitialSetupRequest())

    assert prepared == ["schema"]
    assert caught.value.status_code == 400
    assert caught.value.detail == "no CREATE privilege"


def test_setup_accepts_proxies_from_the_network_form() -> None:
    network = setup.NetworkConfig.model_validate(
        {
            "proxies": [
                "http://legacy:8080",
                {"url": "socks5://proxy:1080", "username": "u", "password": "p", "group": "eu", "max_connections": 4},
            ]
        }
    )
    assert network.proxies[0] == "http://legacy:8080"
    proxy = network.proxies[1]
    assert isinstance(proxy, setup.SetupProxy)
    assert (proxy.username, proxy.group, proxy.max_connections) == ("u", "eu", 4)


def test_filesystem_browser_lists_folders_first(tmp_path: Path) -> None:
    from ultima_scraper_backend.api.routes import system

    (tmp_path / "b-folder").mkdir()
    (tmp_path / "A-folder").mkdir()
    (tmp_path / "file.bin").write_bytes(b"")

    folders = system.browse_filesystem(str(tmp_path))
    assert [entry.name for entry in folders.entries] == ["A-folder", "b-folder"]
    assert folders.parent == str(tmp_path.parent) and folders.writable

    everything = system.browse_filesystem(str(tmp_path), include_files=True)
    assert [entry.name for entry in everything.entries] == ["A-folder", "b-folder", "file.bin"]

    for bad_path, status in (("relative/path", 400), (str(tmp_path / "file.bin"), 404)):
        with pytest.raises(HTTPException) as caught:
            system.browse_filesystem(bad_path)
        assert caught.value.status_code == status
