"""The test suite must not reach the developer's configured services."""

import os

import pytest
from ultima_scraper_core import archive_database_url, get_env_path, runtime_env_value


@pytest.mark.skipif(
    os.environ.get("USR_TEST_USE_CONFIGURED_SERVICES") == "1",
    reason="configured services were explicitly requested",
)
def test_shared_service_configuration_is_isolated() -> None:
    assert "usr-test-config-" in str(get_env_path())
    assert not get_env_path().exists()
    if "DATABASE_URL" not in os.environ and "ULTIMA_ARCHIVE_DATABASE_URL" not in os.environ:
        assert archive_database_url() is None
    if "REDIS_HOST" not in os.environ:
        assert runtime_env_value("REDIS_HOST") is None
