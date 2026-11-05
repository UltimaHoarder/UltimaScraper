from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _healthcheck_module():
    path = ROOT / "docker" / "worker-healthcheck.py"
    spec = importlib.util.spec_from_file_location("usr_worker_healthcheck", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_healthcheck_requires_runtime_role_and_redis_heartbeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthcheck = _healthcheck_module()
    readiness = {"expected_workers": 2, "worker_ids": ["one", "two"], "backend_id": "test"}
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("USR_CONTAINER_ROLE", "worker")
    monkeypatch.setattr(healthcheck, "_read_readiness", lambda: readiness)
    monkeypatch.setattr(healthcheck, "_active_worker_count", lambda _config: 2)

    healthcheck.main()
    monkeypatch.setattr(healthcheck, "_active_worker_count", lambda _config: 1)

    with pytest.raises(SystemExit, match="heartbeats are incomplete"):
        healthcheck.main()


def test_one_image_runs_every_role() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    healthcheck = (ROOT / "docker" / "healthcheck.sh").read_text(encoding="utf-8")

    # One final stage: no per-role images to drift apart.
    assert dockerfile.count(" AS runtime\n") == 1
    assert "worker-runtime" not in dockerfile and "runtime-base" not in dockerfile
    assert "ENV USR_CONTAINER_ROLE=api" in dockerfile
    assert 'CMD ["usr-healthcheck"]' in dockerfile
    # The WebUI build and server are in the same image.
    assert "COPY --from=webui-assets /build/dist /opt/webui/static" in dockerfile
    assert "./web/ultima_webui_server" in dockerfile
    # Each role's healthcheck checks that role.
    assert "exec python /usr/local/bin/usr-worker-healthcheck" in healthcheck
    assert "exec python -m ultima_webui_server.healthcheck" in healthcheck
    assert "/api/v1/admin/health" in healthcheck


def test_compose_runs_every_service_from_the_one_image() -> None:
    for path in (ROOT / "docker-compose.yml", ROOT / "docker-compose.build.yml"):
        compose = yaml.safe_load(path.read_text(encoding="utf-8"))["services"]
        images = {compose[name]["image"] for name in ("backend", "worker", "webui")}
        assert len(images) == 1, (path.name, images)

    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    assert {name: services[name]["environment"]["USR_CONTAINER_ROLE"] for name in ("backend", "worker", "webui")} == {
        "backend": "api",
        "worker": "worker",
        "webui": "webui",
    }


def test_compose_build_builds_the_image_once() -> None:
    services = yaml.safe_load((ROOT / "docker-compose.build.yml").read_text(encoding="utf-8"))["services"]

    assert services["backend"]["build"]["target"] == "runtime"
    assert "build" not in services["worker"] and "build" not in services["webui"]
    assert services["worker"]["pull_policy"] == services["webui"]["pull_policy"] == "never"


@pytest.mark.parametrize(
    ("secret_value", "expected_password"),
    [("worker-secret\n", "worker-secret"), ("", None)],
)
def test_worker_healthcheck_reads_optional_redis_password_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    secret_value: str,
    expected_password: str | None,
) -> None:
    healthcheck = _healthcheck_module()
    secret = tmp_path / "redis-password"
    secret.write_text(secret_value, encoding="utf-8")
    observed: dict[str, object] = {}

    class FakeRedis:
        def __init__(self, **kwargs) -> None:
            observed.update(kwargs)

        def ping(self) -> bool:
            return True

        def smembers(self, _key: str) -> set[str]:
            return set()

        def pipeline(self, **kwargs):
            return self

        def execute(self):
            return [True, set()]

        def close(self) -> None:
            pass

    config = {"backend_id": "backend-test", "worker_ids": []}
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.setenv("REDIS_PASSWORD_FILE", str(secret))
    monkeypatch.setenv("REDIS_HOST", "redis.internal")
    monkeypatch.setattr(healthcheck, "Redis", FakeRedis)

    assert healthcheck._active_worker_count(config) == 0
    assert observed["password"] == expected_password
