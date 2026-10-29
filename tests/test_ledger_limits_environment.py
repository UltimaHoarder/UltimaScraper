"""File-backed ledger limits stay fresh and preserve process precedence."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest
from ultima_scraper_backend.job_system import ledger

from ultima_scraper_core import environment

SETTING_NAMES = (
    "ULTIMA_JOB_WINDOW_MAX_TASKS", "ULTIMA_JOB_WINDOW_MAX_BYTES",
    "ULTIMA_DATABASE_WRITE_MAX_COMMAND_BYTES", "ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS",
    "ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", "ULTIMA_LEDGER_TASKS", "ULTIMA_LEDGER_BYTES",
    "ULTIMA_LEDGER_GLOBAL_TASKS", "ULTIMA_LEDGER_GLOBAL_BYTES", "ULTIMA_LEDGER_BATCH",
    "ULTIMA_LEDGER_LEASE_SECONDS", "ULTIMA_LEDGER_RESULT_BYTES",
    "ULTIMA_LEDGER_PLANNER_BATCH", "ULTIMA_LEDGER_ARCHIVE_BATCH",
    "ULTIMA_LEDGER_TERMINAL_TASKS", "ULTIMA_LEDGER_TERMINAL_BYTES",
)


@pytest.fixture
def env_file(monkeypatch, tmp_path: Path) -> Path:
    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    path.write_text("")
    monkeypatch.setattr(environment, "get_env_path", lambda: path)
    return path


def test_limits_parse_one_fresh_file_per_load(monkeypatch, env_file: Path):
    env_file.write_text(
        "ULTIMA_JOB_WINDOW_MAX_TASKS=90\n"
        "ULTIMA_DATABASE_WRITE_MAX_COMMAND_BYTES=8192\n"
        "ULTIMA_LEDGER_BATCH=7\n"
    )
    reads = []
    original = ledger.read_env

    def counted():
        reads.append(True)
        return original()

    monkeypatch.setattr(ledger, "read_env", counted)
    first = ledger.Limits.load()
    assert len(reads) == 1
    assert asdict(first) == {
        "tasks": 90, "bytes": 8192, "global_tasks": 90, "global_bytes": 8192,
        "batch": 7, "lease_seconds": 120, "result_bytes": 16 * 1024 * 1024,
        "planner_batch": 7, "archive_batch": 2048,
        "terminal_tasks": 180, "terminal_bytes": 8192,
    }
    env_file.write_text("ULTIMA_JOB_WINDOW_MAX_TASKS=100\nULTIMA_LEDGER_BATCH=9\n")
    second = ledger.Limits.load()
    assert len(reads) == 2
    assert second.tasks == second.global_tasks == 100
    assert second.batch == second.planner_batch == 9
    assert first.tasks == 90


def test_process_blanks_and_overrides_shadow_file(env_file: Path, monkeypatch):
    env_file.write_text(
        "ULTIMA_LEDGER_TASKS=12\nULTIMA_LEDGER_BATCH=9\n"
        "ULTIMA_LEDGER_PLANNER_BATCH=33\nULTIMA_LEDGER_TERMINAL_BYTES=600\n"
    )
    monkeypatch.setenv("ULTIMA_LEDGER_TASKS", "16")
    monkeypatch.setenv("ULTIMA_LEDGER_BATCH", "  ")
    monkeypatch.setenv("ULTIMA_LEDGER_PLANNER_BATCH", "")
    first = ledger.Limits.load()
    assert first.tasks == 16
    assert first.batch == 128 and first.planner_batch == 512
    assert first.terminal_bytes == 600
    monkeypatch.setenv("ULTIMA_LEDGER_BATCH", "32")
    second = ledger.Limits.load()
    assert second.batch == second.planner_batch == 32


def test_complete_process_config_does_not_read_unusable_file(env_file: Path, monkeypatch):
    for name in SETTING_NAMES:
        monkeypatch.setenv(name, "13")
    env_file.unlink()
    env_file.mkdir()
    assert all(value == 13 for value in asdict(ledger.Limits.load()).values())


def test_missing_file_keeps_defaults(env_file: Path):
    env_file.unlink()
    limits = ledger.Limits.load()
    assert limits.tasks == limits.global_tasks == 1000
    assert limits.batch == 128 and limits.planner_batch == 512
    assert limits.bytes == limits.global_bytes == 64 * 1024 * 1024


def test_unreadable_file_is_not_silently_ignored(env_file: Path):
    env_file.unlink()
    env_file.mkdir()
    with pytest.raises(RuntimeError, match="Unable to read environment file"):
        ledger.Limits.load()


@pytest.mark.parametrize("name", SETTING_NAMES)
@pytest.mark.parametrize("bad", ["0", "-1", "not-an-integer"])
def test_invalid_limits_are_still_rejected(env_file: Path, name: str, bad: str):
    env_file.write_text(f"{name}={bad}\n")
    with pytest.raises(ValueError):
        ledger.Limits.load()
