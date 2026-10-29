from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultima_scraper_backend import config_settings_sync
from ultima_scraper_backend.config import UltimaScraperCollectionConfig


@pytest.mark.parametrize("section", ["metadata_setup", "download_setup"])
def test_config_load_preserves_unavailable_drive_paths_without_probing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    section: str,
) -> None:
    drives = [
        {
            "minimum_space": 1024**3,
            "store": False,
            "scan_existing": True,
            "overflow": False,
            "directories": [
                "/usr-test-offline-drive/media",
                "/usr-test-other-offline-drive/archive",
            ],
        },
        {
            "minimum_space": 0,
            "store": True,
            "scan_existing": False,
            "overflow": True,
            "directories": ["/usr-test-offline-drive/downloads"],
        },
    ]
    payload = {
        "configuration_schema_version": 2,
        "settings": {section: {"drives": drives}},
    }
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    row = SimpleNamespace(
        id=7,
        backend="shared-scope",
        version=42,
        updated_at=None,
        value=json.dumps(payload),
    )

    @contextmanager
    def session():
        results = iter([SimpleNamespace(settings_id=row.id), row])
        yield SimpleNamespace(
            exec=lambda statement: SimpleNamespace(one_or_none=lambda: next(results))
        )

    monkeypatch.setattr(config_settings_sync, "get_global_session", session)
    monkeypatch.setattr(
        config_settings_sync,
        "archive_database_url",
        lambda: "postgresql://fixture.invalid/archive",
    )

    def guard(probe):
        def checked(path, *args, **kwargs):
            if not isinstance(path, int):
                text = os.fsdecode(path)
                if text.startswith(
                    ("/usr-test-offline-drive", "/usr-test-other-offline-drive")
                ):
                    pytest.fail(
                        f"Configuration loading probed an offline drive: {text}"
                    )
            return probe(path, *args, **kwargs)

        return checked

    # Fail at the filesystem boundary instead of touching a real stalled mount.
    for name in ("stat", "lstat", "readlink", "statvfs", "listdir", "scandir"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, guard(getattr(os, name)))

    config = UltimaScraperCollectionConfig.load_or_create_default_config()
    assert config._settings_backend == "shared-scope"
    assert config._settings_id == 7
    assert config._settings_version == 42

    setup = getattr(config.settings, section)
    assert setup.model_dump(mode="json")["drives"] == drives
    assert json.loads(row.value) == payload
