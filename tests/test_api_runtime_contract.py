from __future__ import annotations

from types import SimpleNamespace

import pytest

from ultima_scraper_backend.api import app as app_module
from ultima_scraper_backend.api.routes import admin
from ultima_scraper_backend.config import ExecutionMode, ProcessRole
from ultima_scraper_backend.models import backend as backend_model
from ultima_scraper_backend.plugin_system import platform as plugin_platform_module
from ultima_scraper_backend.plugin_system import runtime_owner


class FakeRedis:
    def __init__(self, *, connected: bool = True, healthy: bool = True) -> None:
        self.is_connected = connected
        self._healthy = healthy
        self.client = SimpleNamespace()

    async def health_check(self) -> bool:
        return self._healthy


class FakeBackend:
    def __init__(self, redis: FakeRedis | None) -> None:
        self.instance_id = "control-test"
        self.redis = redis


async def _noop_async(*_args, **_kwargs) -> None:
    return None


@pytest.mark.parametrize(
    ("run_mode", "expected_executor_events"),
    [
        ("api", ["ledger:start", "ledger:stop"]),
        (
            "webui",
            [
                "ledger:start",
                "ledger:stop",
            ],
        ),
    ],
)
async def test_lifespan_obeys_api_executor_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    run_mode: str,
    expected_executor_events: list[str],
) -> None:
    events: list[str] = []
    backend = FakeBackend(FakeRedis(connected=run_mode == "webui"))

    class FakePluginPlatform:
        def __init__(self, _plugins_dir, *, repository) -> None:
            pass

        def load_all(self) -> list[object]:
            return []

        def attach_backend(self, _backend) -> None:
            pass

    class FakeCoordinator:
        def __init__(self, *_args) -> None:
            events.append("coordinator:init")

        def start(self) -> None:
            events.append("coordinator:start")

        async def stop(self) -> None:
            events.append("coordinator:stop")

    async def start_ledger(_backend):
        events.append("ledger:start")

    async def stop_ledger():
        events.append("ledger:stop")

    async def preflight_postgres() -> None:
        events.append("postgres:preflight")

    async def get_backend() -> FakeBackend:
        events.append("backend:init")
        return backend

    monkeypatch.setenv("RUN_MODE", run_mode)
    monkeypatch.setattr(app_module, "prune_old_logs", lambda *_args: None)
    monkeypatch.setattr(
        app_module, "_append_backend_init_debug_line", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(app_module, "configure_log_redaction", lambda: None)
    monkeypatch.setattr(app_module, "validate_security_configuration", lambda: None)
    monkeypatch.setattr(
        app_module, "validate_secret_crypto_configuration", lambda: None
    )
    monkeypatch.setattr(admin, "ensure_api_postgres_dependency", preflight_postgres)
    monkeypatch.setattr(app_module, "_resolve_plugins_dir", lambda: tmp_path)
    monkeypatch.setattr(app_module, "get_backend_instance", get_backend)
    monkeypatch.setattr(app_module, "setup_event_broadcasting", _noop_async)
    monkeypatch.setattr(app_module, "setup_status_broadcasting", _noop_async)
    monkeypatch.setattr(app_module, "subscribe_to_redis_logs", _noop_async)
    monkeypatch.setattr(app_module, "stop_event_broadcasting", _noop_async)
    monkeypatch.setattr(app_module, "stop_status_broadcasting", _noop_async)
    monkeypatch.setattr(app_module, "shutdown_backend", _noop_async)
    monkeypatch.setattr(admin, "ensure_api_runtime_dependencies", _noop_async)
    monkeypatch.setattr(plugin_platform_module, "PluginPlatform", FakePluginPlatform)
    from ultima_scraper_backend.plugin_system import postgres_repository
    monkeypatch.setattr(postgres_repository, "PostgresPluginRepository", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runtime_owner, "PluginRuntimeCoordinator", FakeCoordinator)
    from ultima_scraper_backend.job_system import ledger_runtime, mps_state
    monkeypatch.setattr(ledger_runtime, "start_service", start_ledger)
    monkeypatch.setattr(ledger_runtime, "stop_service", stop_ledger)
    monkeypatch.setattr(mps_state, "sync_runtime_settings", _noop_async)
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig
    monkeypatch.setattr(UltimaScraperCollectionConfig, "load_or_create_default_config", lambda: SimpleNamespace(settings=SimpleNamespace()))
    monkeypatch.setattr(app_module, "_statistics_refresh_task", None)

    from ultima_scraper_db_archive import global_db

    monkeypatch.setattr(global_db, "is_setup_complete", lambda: False)

    test_app = SimpleNamespace(state=SimpleNamespace())
    async with app_module.lifespan(test_app):  # type: ignore[arg-type]
        pass

    assert events.index("postgres:preflight") < events.index("backend:init")
    assert [
        event for event in events if event not in {"postgres:preflight", "backend:init"}
    ] == expected_executor_events


async def test_api_readiness_probes_redis_and_expected_postgres_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_databases: list[str] = []

    monkeypatch.setenv("RUN_MODE", "api")
    monkeypatch.setenv("USR_EXPECTED_DATABASE", "ultima_archive")
    monkeypatch.setattr(
        admin,
        "_check_postgres_readiness",
        observed_databases.append,
    )

    await admin.ensure_api_runtime_dependencies(FakeBackend(FakeRedis()))  # type: ignore[arg-type]

    assert observed_databases == ["ultima_archive"]


async def test_api_readiness_fails_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUN_MODE", "api")

    with pytest.raises(RuntimeError, match="Redis is unavailable"):
        await admin.ensure_api_runtime_dependencies(
            FakeBackend(FakeRedis(healthy=False))  # type: ignore[arg-type]
        )


async def test_control_backend_never_registers_recovers_or_claims_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    backend = backend_model.BackendInstance(
        instance_id="api-control",
        redis=SimpleNamespace(),  # type: ignore[arg-type]
        distributed_mode=True,
        execution_mode=ExecutionMode.DISTRIBUTED,
        process_role=ProcessRole.CONTROL,
    )

    async def enable_distributed_mode() -> None:
        events.append("distributed:enable")
        backend._distributed_mode = True

    async def record(name: str) -> None:
        events.append(name)

    monkeypatch.setattr(backend, "enable_distributed_mode", enable_distributed_mode)
    monkeypatch.setattr(backend, "_setup_registry", lambda: record("registry:setup"))
    monkeypatch.setattr(
        backend, "_sync_backend_inventory", lambda: record("inventory:sync")
    )
    monkeypatch.setattr(
        backend, "_start_config_subscriber", lambda: record("config:subscribe")
    )
    monkeypatch.setattr(
        backend, "_publish_config_to_redis", lambda: record("config:publish")
    )

    await backend.initialize()

    assert events == [
        "distributed:enable",
        "inventory:sync",
        "config:subscribe",
        "config:publish",
    ]


async def test_full_runtime_health_does_not_require_api_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUN_MODE", "webui")

    response = await admin.health_check(
        FakeBackend(redis=None)  # type: ignore[arg-type]
    )

    assert response.status == "ok"


def test_degen_facing_api_routes_remain_available() -> None:
    routes = {
        (method, route.path)
        for route in app_module.app.routes
        for method in (getattr(route, "methods", None) or set())
    }
    required = {
        ("GET", "/api/v1/admin/health"),
        ("POST", "/api/v1/jobs"),
        ("GET", "/api/v1/jobs/{job_id}"),
        ("POST", "/api/v1/account-purchases/quote"),
        ("POST", "/api/v1/account-purchases/execute"),
        ("GET", "/api/v1/database/archive-metrics"),
        ("GET", "/api/v1/database/archive-metrics/purchase-facts"),
        ("GET", "/api/v1/database/users"),
        ("GET", "/api/v1/database/users/{user_id}/profile_media"),
        ("GET", "/api/v1/proxies/"),
        ("POST", "/api/v1/proxies/"),
        ("PUT", "/api/v1/proxies/{proxy_url:path}"),
        ("GET", "/api/v1/auths/{auth_id}"),
        ("POST", "/api/v1/auths/{auth_id}/test"),
        ("POST", "/api/v1/auths/{auth_id}/proxy-test"),
        ("GET", "/api/v1/auths/{auth_id}/balance"),
        ("GET", "/api/v1/media/thumbnail/{site_name}/{media_id}"),
        ("POST", "/api/v1/media/{site_name}/{content_type}/bulk"),
        ("GET", "/api/v1/media/{site_name}/by_url"),
        ("GET", "/api/v1/files/"),
    }

    assert required <= routes
