"""A busy batch must not lose the receipt sweep checkpoint or cutoff."""

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ultima_scraper_backend.database.receipt_retention import ReceiptPurgeResult


@pytest.fixture
def cli(monkeypatch):
    path = (
        Path(__file__).resolve().parents[1] / "scripts/purge_database_write_receipts.py"
    )
    spec = importlib.util.spec_from_file_location("receipt_cleanup_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    redis = SimpleNamespace(
        connect=AsyncMock(return_value=True), disconnect=AsyncMock()
    )
    monkeypatch.setattr(module, "RedisManager", Mock(return_value=redis))
    monkeypatch.setattr(
        module.UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        Mock(return_value=SimpleNamespace(settings=SimpleNamespace(redis=None))),
    )
    monkeypatch.setattr(
        module, "pending_command_ids", AsyncMock(return_value={"queued"})
    )
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    module.test_redis = redis
    return module


@pytest.mark.asyncio
async def test_busy_and_active_job_retry_preserve_cursor_and_fixed_cutoff(
    cli, monkeypatch, tmp_path
):
    state = tmp_path / "state.json"
    monkeypatch.setattr(
        "sys.argv",
        ["purge", "--apply", "--max-batches", "0", "--state-file", str(state)],
    )
    runner = AsyncMock(
        side_effect=[
            ReceiptPurgeResult(0, 0, True),
            ReceiptPurgeResult(0, 0, paused_reason="execution_active"),
            ReceiptPurgeResult(2, 2, next_cursor="(128,0)"),
            ReceiptPurgeResult(0, 0, next_cursor="(256,0)", finished=True),
        ]
    )
    monkeypatch.setattr(cli, "run_database_call", runner)
    await cli.main()
    calls = [call.kwargs for call in runner.await_args_list]
    assert [call["cursor"] for call in calls] == ["(0,0)", "(0,0)", "(0,0)", "(128,0)"]
    assert len({call["cutoff"] for call in calls}) == 1
    checkpoint = json.loads(state.read_text())
    assert checkpoint["finished"] and checkpoint["total_deleted"] == 2
    assert not state.with_suffix(".json.tmp").exists()
    cli.test_redis.disconnect.assert_awaited_once()
    cli.asyncio.sleep.assert_any_await(5.0)


@pytest.mark.asyncio
async def test_resume_keeps_committed_count_and_cutoff(cli, monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    cutoff = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    state.write_text(
        json.dumps(
            {
                "cursor": "(99,0)",
                "total_deleted": 100,
                "cutoff": cutoff,
                "finished": False,
            }
        )
    )
    monkeypatch.setattr("sys.argv", ["purge", "--apply", "--state-file", str(state)])
    runner = AsyncMock(
        return_value=ReceiptPurgeResult(0, 0, next_cursor="(227,0)", finished=True)
    )
    monkeypatch.setattr(cli, "run_database_call", runner)
    await cli.main()
    assert runner.await_args.kwargs["cursor"] == "(99,0)"
    assert runner.await_args.kwargs["cutoff"].isoformat() == cutoff
    assert json.loads(state.read_text())["total_deleted"] == 100
