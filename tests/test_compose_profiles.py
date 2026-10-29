from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALL_SERVICES = {"webui", "backend", "worker", "postgres", "redis"}

requires_compose = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0,
    reason="docker compose is not available",
)


def _config(*files: str, profiles: str | None = None) -> dict:
    environment = {key: value for key, value in os.environ.items() if key != "COMPOSE_PROFILES"}
    if profiles is not None:
        environment["COMPOSE_PROFILES"] = profiles
    # An empty env file: nothing may be required just to render the file.
    command = ["docker", "compose", "--env-file", os.devnull]
    for file in files:
        command += ["-f", str(ROOT / file)]
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@requires_compose
@pytest.mark.parametrize(
    "profiles",
    [
        "webui,backend,worker,postgres,redis",
        "webui",
        "worker",
        "backend",
        "backend,redis",
        "backend,worker,postgres",
        "postgres,redis",
    ],
)
def test_every_component_is_optional(profiles: str) -> None:
    services = set(_config("docker-compose.yml", profiles=profiles)["services"])

    assert services == set(profiles.split(","))


@requires_compose
def test_dependencies_on_unbundled_services_are_optional() -> None:
    backend = _config("docker-compose.yml", profiles="backend")["services"]["backend"]

    for store in ("postgres", "redis"):
        assert backend["depends_on"][store]["required"] is False
    # Without the bundled services the backend is pointed elsewhere by .env.
    assert backend["environment"]["REDIS_HOST"] == "redis"
    assert backend["environment"]["POSTGRES_HOST"] == "postgres"





@requires_compose
def test_bundled_redis_refuses_to_start_without_a_password() -> None:
    redis = _config("docker-compose.yml", profiles="redis")["services"]["redis"]

    assert any("Set REDIS_PASSWORD" in part for part in redis["command"])


def _components() -> ModuleType:
    path = ROOT / "scripts" / "release" / "components.py"
    spec = importlib.util.spec_from_file_location("usr_release_components", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_component_lock_round_trips_and_names_every_component(tmp_path: Path) -> None:
    components = _components()
    lock = tmp_path / "components.lock.json"
    commits = {name: f"{index:040x}" for index, name in enumerate(components.COMPONENTS)}

    components.write_lock(commits, lock)

    assert components.read_lock(lock) == commits


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda doc: doc["components"]["usr_api"].update(repository="https://example.test/fork.git"), "not approved"),
        (lambda doc: doc["components"]["usdb"].update(commit="main"), "full commit"),
        (lambda doc: doc["components"].pop("usr_backend"), "exactly"),
    ],
)
def test_component_lock_rejects_unpinned_or_unapproved_sources(
    tmp_path: Path, change, message: str
) -> None:
    components = _components()
    lock = tmp_path / "components.lock.json"
    components.write_lock({name: "a" * 40 for name in components.COMPONENTS}, lock)
    document = json.loads(lock.read_text())
    change(document)
    lock.write_text(json.dumps(document))

    with pytest.raises(SystemExit, match=message):
        components.read_lock(lock)


def test_the_committed_lock_is_valid() -> None:
    assert set(_components().read_lock()) == set(_components().COMPONENTS)


def test_private_components_are_fetched_from_the_mirror_and_public_ones_upstream() -> None:
    components = _components().COMPONENTS
    mirror = "https://forge.example/owner/"

    assert components["usr_backend"].fetch_url(mirror) == "https://forge.example/owner/UltimaScraperBackend.git"
    assert components["usdb"].fetch_url(mirror) == "https://forge.example/owner/UltimaScraperDB.git"
    assert components["usdb_archive"].fetch_url(mirror) == "https://forge.example/owner/UltimaScraperDBArchive.git"
    # Public upstream, and every component without a mirror, keep the locked repository.
    assert components["usr_api"].fetch_url(mirror) == components["usr_api"].repository
    assert components["usr_core"].fetch_url(mirror) == "https://github.com/UltimaHoarder/UltimaScraperCore.git"
    assert all(component.fetch_url(None) == component.repository for component in components.values())
