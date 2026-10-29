from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_worker_image_does_not_inherit_api_exposure() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    worker_stage = dockerfile.split("FROM runtime-base AS worker-runtime", 1)[1]

    assert "FROM runtime AS worker-runtime" not in dockerfile
    assert "EXPOSE 21121" not in worker_stage
    assert "USR_CONTAINER_ROLE=worker" in worker_stage
    assert 'CMD ["python", "/usr/local/bin/usr-worker-healthcheck"]' in worker_stage


def test_compose_build_targets_match_container_roles() -> None:
    compose = (ROOT / "docker-compose.build.yml").read_text(encoding="utf-8")
    backend, worker = compose.split("  worker:", 1)

    assert "target: runtime" in backend
    assert "target: worker-runtime" in worker


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
