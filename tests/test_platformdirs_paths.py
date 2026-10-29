"""Test platformdirs XDG-compliant path selection and environment overrides."""

import os
import tempfile
from pathlib import Path

import pytest
from platformdirs import user_data_dir

from ultima_scraper_backend.database.usr_factory import (
    APP_AUTHOR,
    APP_NAME,
    get_default_data_directory,
)


def test_default_data_directory():
    """Test that default data directory uses platformdirs."""
    # Clear any environment override
    original_env = os.environ.get("ULTIMA_SCRAPER_DATA_DIR")
    if "ULTIMA_SCRAPER_DATA_DIR" in os.environ:
        del os.environ["ULTIMA_SCRAPER_DATA_DIR"]

    try:
        result = get_default_data_directory()
        expected = Path(user_data_dir(APP_NAME, APP_AUTHOR))

        assert result == expected, f"Expected {expected}, got {result}"
        print(f"✓ Default data directory: {result}")

    finally:
        # Restore environment
        if original_env:
            os.environ["ULTIMA_SCRAPER_DATA_DIR"] = original_env


def test_environment_override():
    """Test that ULTIMA_SCRAPER_DATA_DIR overrides default."""
    with tempfile.TemporaryDirectory() as tmpdir:
        override_path = Path(tmpdir) / "custom_data"

        # Set environment variable
        os.environ["ULTIMA_SCRAPER_DATA_DIR"] = str(override_path)

        try:
            result = get_default_data_directory()
            assert result == override_path, f"Expected {override_path}, got {result}"
            print(f"✓ Environment override works: {result}")

        finally:
            # Clean up environment
            if "ULTIMA_SCRAPER_DATA_DIR" in os.environ:
                del os.environ["ULTIMA_SCRAPER_DATA_DIR"]


def test_create_usr_database_manager_uses_xdg(monkeypatch: pytest.MonkeyPatch):
    """Test that create_usr_database_manager delegates to the Postgres factory."""
    from ultima_scraper_backend.database.usr_factory import (
        create_usr_database_manager,
    )
    from ultima_scraper_backend.database.factory import DatabaseManagerFactory

    with tempfile.TemporaryDirectory() as tmpdir:
        test_base = Path(tmpdir)
        recorded: dict[str, object] = {}

        class DummyManager:
            def __init__(self) -> None:
                self.db_path = None

            def disconnect(self) -> None:
                return None

        def _fake_create_postgres_manager(**kwargs: object) -> DummyManager:
            recorded.update(kwargs)
            return DummyManager()

        original = DatabaseManagerFactory.create_postgres_manager
        DatabaseManagerFactory.create_postgres_manager = staticmethod(
            _fake_create_postgres_manager
        )
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql://user:pass@localhost/test"
        )

        try:
            manager = create_usr_database_manager(
                "onlyfans", base_directory=test_base, read_only=False
            )
            assert isinstance(manager, DummyManager)
            assert recorded["site"] == "onlyfans"
            assert recorded["auto_create"] is False
            assert recorded["auto_connect"] is True
            assert recorded["connection_string"] == "postgresql://user:pass@localhost/test"
        finally:
            DatabaseManagerFactory.create_postgres_manager = original


if __name__ == "__main__":
    print("Testing platformdirs XDG-compliant paths...\n")

    test_default_data_directory()
    test_environment_override()
    test_create_usr_database_manager_uses_xdg()

    print("\n✅ All platformdirs path tests passed!")
