from __future__ import annotations

import sys

import pytest

from ultima_scraper_backend.api import app as app_module
from ultima_scraper_backend import runtime_mode


def test_worker_count_reads_persisted_runtime_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CONTROL_WORKERS", raising=False)
    monkeypatch.setattr(
        app_module,
        "runtime_env_value",
        lambda name: "4" if name == "CONTROL_WORKERS" else None,
    )

    assert app_module._get_worker_count() == 4


def test_worker_count_process_environment_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTROL_WORKERS", "3")

    assert app_module._get_worker_count() == 3


def test_worker_count_auto_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "runtime_env_value", lambda _name: "auto")
    monkeypatch.setattr(app_module.os, "cpu_count", lambda: 128)

    assert app_module._get_worker_count() == 8


def test_worker_healthcheck_timeout_defaults_to_sixty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "runtime_env_value", lambda _name: None)

    assert app_module._get_worker_healthcheck_timeout() == 60


def test_worker_healthcheck_timeout_reads_runtime_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_module,
        "runtime_env_value",
        lambda name: "90" if name == "CONTROL_WORKER_HEALTHCHECK_TIMEOUT" else None,
    )

    assert app_module._get_worker_healthcheck_timeout() == 90


def test_multiworker_launcher_does_not_forward_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    original_stdin = sys.stdin

    monkeypatch.setenv("RUN_MODE", "api")
    monkeypatch.setenv("CONTROL_HOST", "127.0.0.1")
    monkeypatch.setattr(
        app_module,
        "runtime_env_value",
        lambda name: "4" if name == "CONTROL_WORKERS" else None,
    )
    monkeypatch.setenv("CONTROL_PORT", "21121")
    monkeypatch.setattr(
        app_module,
        "_find_available_port",
        lambda _port: pytest.fail("API mode must keep its configured port"),
    )
    monkeypatch.setattr(
        app_module,
        "log_security_startup_report",
        lambda **_kwargs: None,
    )

    def fake_uvicorn_run(*_args: object, **kwargs: object) -> None:
        observed["stdin"] = sys.stdin
        observed["workers"] = kwargs["workers"]
        observed["worker_healthcheck_timeout"] = kwargs["timeout_worker_healthcheck"]
        observed["startup_id"] = app_module.os.environ.get("USR_BACKEND_STARTUP_ID")
        observed["port"] = kwargs["port"]

    monkeypatch.setattr(app_module.uvicorn, "run", fake_uvicorn_run)

    app_module.run_control()

    assert observed["stdin"] is None
    assert observed["workers"] == 4
    assert observed["worker_healthcheck_timeout"] == 60
    assert observed["startup_id"]
    assert observed["port"] == 21121
    assert sys.stdin is original_stdin


@pytest.mark.parametrize("run_mode", ["backend", "tui"])
def test_retired_runtime_modes_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    run_mode: str,
) -> None:
    monkeypatch.setenv("RUN_MODE", run_mode)

    with pytest.raises(RuntimeError, match="Invalid RUN_MODE"):
        runtime_mode.get_runtime_mode()
