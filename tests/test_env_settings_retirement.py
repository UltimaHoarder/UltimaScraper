"""Retired env flags, env-to-settings moves, setup state and bootstrap."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from ultima_scraper_backend import bootstrap, deprecated_env
from ultima_scraper_backend.api.routes import favourites as favourites_route
from ultima_scraper_backend.api.routes import setup as setup_route
from ultima_scraper_backend.config import JobExecutionSettings, WorkerPool
from ultima_scraper_backend.job_system.ledger_runtime import ledger_claim_page_size
from ultima_scraper_backend.services.settings_service import SettingsService
from ultima_scraper_backend.services.terminal_job_reconciler import (
    TerminalJobReconciler,
)
from ultima_scraper_backend.workers import worker_pool
from ultima_scraper_core import read_env
from ultima_scraper_db_archive import global_db


@pytest.fixture(autouse=True)
def _fresh_deprecation_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deprecated_env, "_reported", set())
    for name in deprecated_env.DEPRECATED_SETTINGS_ENV:
        # Blank values bypass the workspace dotenv, like unset ones.
        monkeypatch.setenv(name, "")


def _settings_engine(rows: list[tuple[str, str]], backends: list[tuple[str, int]] = ()):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as connection:
        connection.execute(text("ATTACH DATABASE ':memory:' AS management"))
        connection.execute(text(
            "CREATE TABLE management.settings (id INTEGER PRIMARY KEY, backend TEXT, key TEXT)"
        ))
        connection.execute(text(
            "CREATE TABLE management.backends (hostname TEXT, settings_id INTEGER)"
        ))
        for backend, key in rows:
            connection.execute(
                text("INSERT INTO management.settings (backend, key) VALUES (:b, :k)"),
                {"b": backend, "k": key},
            )
        for hostname, settings_id in backends:
            connection.execute(
                text("INSERT INTO management.backends VALUES (:h, :s)"),
                {"h": hostname, "s": settings_id},
            )
    return engine


@pytest.fixture
def setup_database(monkeypatch: pytest.MonkeyPatch):
    def install(engine) -> None:
        monkeypatch.setattr(global_db, "archive_database_url", lambda: "postgresql://fixture.invalid/db")
        monkeypatch.setattr(global_db, "get_global_engine", lambda *a, **k: engine)
        monkeypatch.setattr(global_db, "_setup_complete", False)
        monkeypatch.setenv("BACKEND_ID", "host-a")

    return install


def test_setup_incomplete_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(global_db, "archive_database_url", lambda: None)
    monkeypatch.setattr(global_db, "_setup_complete", False)
    assert global_db.is_setup_complete() is False


def test_setup_state_is_this_backends_config_row(setup_database) -> None:
    setup_database(_settings_engine([("host-b", "config"), ("host-a", "other")]))
    assert global_db.is_setup_complete() is False

    setup_database(_settings_engine([("host-a", "config")]))
    assert global_db.is_setup_complete() is True


def test_setup_state_follows_backend_inventory_mapping(setup_database) -> None:
    # host-a is mapped onto the shared row 1, whose scope name differs.
    setup_database(_settings_engine([("shared", "config")], backends=[("host-a", 1)]))
    assert global_db.is_setup_complete() is True


def test_setup_state_caches_positive_result(setup_database, monkeypatch) -> None:
    setup_database(_settings_engine([("host-a", "config")]))
    assert global_db.is_setup_complete() is True

    def unreachable(*args, **kwargs):
        raise AssertionError("cached result should not query again")

    monkeypatch.setattr(global_db, "get_global_engine", unreachable)
    assert global_db.is_setup_complete() is True


def test_setup_state_reports_unreachable_database_as_incomplete(setup_database, monkeypatch) -> None:
    setup_database(_settings_engine([]))

    def unreachable(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(global_db, "get_global_engine", unreachable)
    assert global_db.is_setup_complete() is False


def test_reset_refuses_over_stored_configuration(monkeypatch) -> None:
    monkeypatch.setattr(SettingsService, "is_configured", lambda self: True)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(setup_route.reset_setup())
    assert raised.value.status_code == 409

    monkeypatch.setattr(SettingsService, "is_configured", lambda self: False)
    assert asyncio.run(setup_route.reset_setup()).is_configured is False


def test_deprecated_env_override_warns_once(monkeypatch, caplog) -> None:
    monkeypatch.setenv("ULTIMA_CLAIM_BATCH_SIZE", "16")
    with caplog.at_level(logging.WARNING, logger=deprecated_env.__name__):
        assert deprecated_env.deprecated_env_int("ULTIMA_CLAIM_BATCH_SIZE") == 16
        assert deprecated_env.deprecated_env_int("ULTIMA_CLAIM_BATCH_SIZE") == 16
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1
    assert "worker_pool.claim_batch_size" in messages[0]


@pytest.mark.parametrize("raw", ["", "  ", "abc", "0", "-3"])
def test_deprecated_env_ignores_blank_and_invalid(monkeypatch, raw: str) -> None:
    monkeypatch.setenv("ULTIMA_WORKER_CONCURRENCY", raw)
    assert deprecated_env.deprecated_env_int("ULTIMA_WORKER_CONCURRENCY") is None


def test_claim_page_uses_setting_capped_by_ledger_batch(monkeypatch) -> None:
    assert ledger_claim_page_size(128) == 128
    assert ledger_claim_page_size(128, 16) == 16
    assert ledger_claim_page_size(128, 512) == 128
    monkeypatch.setenv("ULTIMA_CLAIM_BATCH_SIZE", "8")
    assert ledger_claim_page_size(128, 16) == 8


def _worker(pool: WorkerPool) -> worker_pool.Worker:
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[]), worker_pool=pool)
    )
    return worker_pool.Worker(
        worker_id="test-w1",
        redis_url="redis://localhost",
        supported_sites=["onlyfans"],
        config=config,
        worker_count=4,
    )


def test_worker_concurrency_comes_from_settings(monkeypatch) -> None:
    assert _worker(WorkerPool(task_concurrency=11)).compute_dynamic_concurrency() == 11
    # No proxies and no setting keeps the existing fallback.
    assert _worker(WorkerPool()).compute_dynamic_concurrency() == 4
    monkeypatch.setenv("ULTIMA_WORKER_CONCURRENCY", "7")
    assert _worker(WorkerPool(task_concurrency=11)).compute_dynamic_concurrency() == 7


def test_worker_pool_settings_reject_non_positive_values() -> None:
    with pytest.raises(ValueError):
        WorkerPool(task_concurrency=0)
    with pytest.raises(ValueError):
        WorkerPool(claim_batch_size=0)


def test_reconciler_applies_settings_except_env_overrides() -> None:
    settings = JobExecutionSettings(
        terminal_reconcile_interval_seconds=60,
        terminal_reconcile_min_age_seconds=10,
        terminal_reconcile_batch_size=5,
        completed_job_retention_seconds=0,
        completed_job_retention_batch_size=50,
    )

    async def loader():
        return settings

    reconciler = TerminalJobReconciler(
        SimpleNamespace(),
        settings_loader=loader,
        overrides={"max_jobs_per_cycle"},
        max_jobs_per_cycle=9,
    )
    asyncio.run(reconciler.refresh_settings())

    assert reconciler.interval_seconds == 60
    assert reconciler.min_age_seconds == 10
    assert reconciler.max_jobs_per_cycle == 9
    assert reconciler.retention_age_seconds == 0
    assert reconciler.retention_batch_size == 50


def test_reconciler_keeps_limits_when_settings_unavailable() -> None:
    async def failing():
        raise OSError("database unavailable")

    async def before_setup():
        return None

    for loader in (failing, before_setup):
        reconciler = TerminalJobReconciler(SimpleNamespace(), settings_loader=loader)
        asyncio.run(reconciler.refresh_settings())
        assert reconciler.interval_seconds == 300
        assert reconciler.max_jobs_per_cycle == 2


def test_job_execution_cleanup_defaults_match_previous_environment_defaults() -> None:
    settings = JobExecutionSettings()
    assert settings.terminal_reconcile_interval_seconds == 300
    assert settings.terminal_reconcile_min_age_seconds == 300
    assert settings.terminal_reconcile_batch_size == 2
    assert settings.completed_job_retention_seconds == 86400
    assert settings.completed_job_retention_batch_size == 1000


def test_bootstrap_keeps_values_and_fills_placeholders(tmp_path: Path, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "USR_SECRET_KEY=keep-me\n"
        "USR_ADMIN_TOKEN=replace-with-a-long-random-token\n"
        "UNRELATED=1\n"
    )

    assert bootstrap.main(["--env-file", str(env_file), "--compose", "--backend-id", "host-a"]) == 0
    values = read_env(env_file)

    assert values["USR_SECRET_KEY"] == "keep-me"
    assert values["UNRELATED"] == "1"
    assert values["BACKEND_ID"] == "host-a"
    assert not values["USR_ADMIN_TOKEN"].startswith("replace-with-")
    assert len(values["USR_ADMIN_TOKEN"]) >= 32
    assert values["POSTGRES_PASSWORD"] and values["REDIS_PASSWORD"]
    assert env_file.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr().out
    assert values["USR_ADMIN_TOKEN"] not in output

    before = env_file.read_text()
    assert bootstrap.main(["--env-file", str(env_file), "--compose"]) == 0
    assert env_file.read_text() == before


@pytest.mark.parametrize(("status_code", "expected"), [(None, True), (503, False)])
def test_favourites_status_reflects_cutover_state(monkeypatch, status_code, expected) -> None:
    from contextlib import contextmanager

    @contextmanager
    def session():
        yield object()

    def ensure_active(_session, site=None):
        if status_code is not None:
            raise HTTPException(status_code, "Favourites backfill/cutover is incomplete")

    monkeypatch.setattr(favourites_route, "global_session", session)
    monkeypatch.setattr(favourites_route.service, "ensure_active", ensure_active)
    assert favourites_route.status() == {"enabled": expected}


def test_favourites_status_propagates_other_errors(monkeypatch) -> None:
    from contextlib import contextmanager

    @contextmanager
    def session():
        yield object()

    def ensure_active(_session, site=None):
        raise HTTPException(422, "Unsupported site")

    monkeypatch.setattr(favourites_route, "global_session", session)
    monkeypatch.setattr(favourites_route.service, "ensure_active", ensure_active)
    with pytest.raises(HTTPException):
        favourites_route.status()
