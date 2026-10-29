"""Suite-wide test isolation and shared fixtures."""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any

import pytest


# The shared .env and config.json live under the user config directory and
# point at real PostgreSQL/Redis services. Unless explicitly requested, give
# the suite an empty config directory before any backend module is imported so
# no test can read or write those services. Variables exported in the process
# environment are still honoured because they are an explicit choice.
_ISOLATED_CONFIG_HOME: str | None = None
if os.environ.get("USR_TEST_USE_CONFIGURED_SERVICES") != "1":
    _ISOLATED_CONFIG_HOME = tempfile.mkdtemp(prefix="usr-test-config-")
    os.environ["XDG_CONFIG_HOME"] = _ISOLATED_CONFIG_HOME


@pytest.fixture
def no_ledger_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SQL execution ledger knows no runs, exactly as an empty database.

    Redis-runtime tests use this so ledger-first lookups fall through to Redis
    without needing (or touching) a PostgreSQL database.
    """
    from ultima_scraper_backend.job_system.ledger import ExecutionLedger

    def no_run(*_args: Any, **_kwargs: Any) -> None:
        return None

    for method in ("job", "stats", "task", "control"):
        monkeypatch.setattr(ExecutionLedger, method, no_run)


@pytest.fixture
def requires_configured_postgres() -> None:
    """Skip tests that need (and write to) a real archive database unless one is set."""
    from ultima_scraper_core import archive_database_url

    if archive_database_url() is None:
        pytest.skip(
            "requires a disposable PostgreSQL database: export DATABASE_URL, "
            "or set USR_TEST_USE_CONFIGURED_SERVICES=1 to use the configured one"
        )


@pytest.fixture
def no_site_databases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Job building finds no site database, so tasks pass through unexpanded."""
    from ultima_scraper_backend.job_system import job_builder

    def missing_site_database(**_kwargs: Any) -> None:
        raise FileNotFoundError("tests have no site database")

    monkeypatch.setattr(job_builder, "create_usr_database_manager", missing_site_database)


def pytest_unconfigure(config: pytest.Config) -> None:
    del config
    if _ISOLATED_CONFIG_HOME is not None:
        shutil.rmtree(_ISOLATED_CONFIG_HOME, ignore_errors=True)


@pytest.fixture
def live_task_events():
    """Capture per-task events the ledger would publish after commit."""
    from ultima_scraper_backend.job_system import live_events

    published: list[dict[str, Any]] = []
    live_events.set_publisher(published.extend)
    try:
        yield published
    finally:
        live_events.set_publisher(None)
