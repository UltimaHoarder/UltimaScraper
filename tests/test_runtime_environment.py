import os
from pathlib import Path

import pytest

from ultima_scraper_backend import security
from ultima_scraper_backend.database.managers import postgres_manager
from ultima_scraper_core import environment
from ultima_scraper_db_archive import crypto


@pytest.mark.parametrize(
    ("read_setting", "name"),
    [
        (security.get_admin_token, "USR_ADMIN_TOKEN"),
        (crypto.is_secret_encryption_enabled, "USR_ENCRYPT_SECRETS"),
        (
            lambda: postgres_manager._runtime_env_int("ULTIMA_DB_POOL_SIZE", 5),
            "ULTIMA_DB_POOL_SIZE",
        ),
    ],
)
def test_runtime_consumers_surface_unreadable_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, read_setting, name: str
) -> None:
    monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(environment, "get_env_path", lambda: tmp_path)

    with pytest.raises(RuntimeError, match="Unable to read environment file"):
        read_setting()


@pytest.mark.parametrize("process_value", [None, "", "process-value"])
def test_runtime_environment_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, process_value: str | None
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("AUDIT_TEST_SETTING=file-value\n")
    if process_value is None:
        monkeypatch.delenv("AUDIT_TEST_SETTING", raising=False)
    else:
        monkeypatch.setenv("AUDIT_TEST_SETTING", process_value)

    expected = "file-value" if process_value is None else process_value
    assert environment.runtime_env_value("AUDIT_TEST_SETTING", env_file) == expected


def test_get_env_path_resolution_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("ULTIMA_ENV_PATH", raising=False)

    component_dir = tmp_path / "ultima_scraper_verse" / "UltimaScraper"
    component_file = component_dir / ".env"

    # Default points to the component location
    assert environment.get_env_path() == component_file

    # Explicit override takes top precedence
    custom = tmp_path / "custom.env"
    monkeypatch.setenv("ULTIMA_ENV_PATH", str(custom))
    assert environment.get_env_path() == custom


def test_layered_env_loading_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "ultima_scraper_verse" / "UltimaScraper"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_env = config_dir / ".env"
    config_env.write_text("TEST_SHARED=from_config\nTEST_CONFIG_ONLY=from_config\n")

    local_dir = tmp_path / "workspace"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_env = local_dir / ".env"
    local_env.write_text("TEST_SHARED=from_local\nTEST_LOCAL_ONLY=from_local\nTEST_ENV_OVERRIDE=from_local\n")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("USR_REPOSITORY_ROOT", str(local_dir))
    monkeypatch.setenv("TEST_ENV_OVERRIDE", "from_process")
    monkeypatch.delenv("TEST_SHARED", raising=False)
    monkeypatch.delenv("TEST_CONFIG_ONLY", raising=False)
    monkeypatch.delenv("TEST_LOCAL_ONLY", raising=False)

    loaded = environment.load_env()
    assert loaded["TEST_CONFIG_ONLY"] == "from_config"
    assert loaded["TEST_SHARED"] == "from_local"
    assert loaded["TEST_LOCAL_ONLY"] == "from_local"

    # Process environment wins over files
    assert os.environ["TEST_ENV_OVERRIDE"] == "from_process"
    assert os.environ["TEST_SHARED"] == "from_local"
    assert os.environ["TEST_CONFIG_ONLY"] == "from_config"
    assert os.environ["TEST_LOCAL_ONLY"] == "from_local"

    # runtime_env_value reflects the same precedence
    assert environment.runtime_env_value("TEST_CONFIG_ONLY") == "from_config"
    assert environment.runtime_env_value("TEST_SHARED") == "from_local"
    assert environment.runtime_env_value("TEST_ENV_OVERRIDE") == "from_process"

