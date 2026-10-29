from types import SimpleNamespace

import pytest

from ultima_scraper_backend.api.routes import system as system_module


@pytest.mark.asyncio
async def test_system_bootstrap_reports_webui_postgres_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = SimpleNamespace(
        instance_id="backend-main",
        distributed_mode=False,
        redis=None,
    )
    config = SimpleNamespace(
        settings=SimpleNamespace(
            worker_pool=SimpleNamespace(sites=["OnlyFans", "Fansly"])
        )
    )

    class DummySettingsService:
        def get_setup_status(self) -> dict[str, object]:
            return {
                "is_configured": True,
                "has_config": True,
                "has_database": True,
                "data_directory": "/tmp/usr",
                "startup_id": "startup-123",
            }

    monkeypatch.setattr(system_module, "SettingsService", DummySettingsService)
    monkeypatch.setattr(system_module, "_get_runtime_version", lambda: "9.9.9")
    monkeypatch.setattr(
        system_module,
        "get_backend_startup_id",
        lambda: "shared-startup-123",
    )
    monkeypatch.setattr(system_module.socket, "gethostname", lambda: "test-host")

    response = system_module.get_system_bootstrap(backend, config)

    assert response.backend_id == "backend-main"
    assert response.hostname == "test-host"
    assert response.version == "9.9.9"
    assert response.supported_sites == ["onlyfans", "fansly"]
    assert response.setup.is_configured is True
    assert response.features.remote_backends is False
    assert response.support_matrix.ui_mode == "webui"
    assert response.support_matrix.runtime_database == "postgresql"
    assert response.support_matrix.tui_supported is False
    assert response.support_matrix.sqlite_runtime_supported is False
    assert response.setup.startup_id == "shared-startup-123"
