"""Tests for `_central_task_row_to_detail` rehydration from archived rows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ultima_scraper_backend.api.routes.jobs import _central_task_row_to_detail


@dataclass
class _FakeRow:
    task_id: str = "task-1"
    job_id: str = "job-1"
    task_type: str = "download"
    status: str = "completed"
    site: str | None = "OnlyFans"
    username: str | None = "diva"
    content_type: str | None = "Posts"
    auth_id: int | None = 1
    items_processed: int = 5
    items_total: int | None = 5
    created_at: datetime = datetime(2026, 4, 22, tzinfo=timezone.utc)
    started_at: datetime | None = datetime(2026, 4, 22, tzinfo=timezone.utc)
    completed_at: datetime | None = datetime(2026, 4, 22, tzinfo=timezone.utc)
    last_event_at: datetime | None = datetime(2026, 4, 22, tzinfo=timezone.utc)
    error: str | None = None
    message: str | None = None
    result_json: str | None = None


def test_rehydrates_result_json_with_download_results() -> None:
    download_results = [
        {"status": "failed", "error_type": "size_mismatch", "media_id": 1},
        {"status": "downloaded", "media_id": 2},
    ]
    payload: dict[str, Any] = {
        "success": True,
        "message": "Scraped Posts: saved=1, failed=1",
        "output": {"download_results": download_results},
    }
    row = _FakeRow(
        message="Scraped Posts: saved=1, failed=1",
        result_json=json.dumps(payload),
    )

    detail = _central_task_row_to_detail(row)  # type: ignore[arg-type]

    assert detail.result is not None
    assert detail.result["message"] == "Scraped Posts: saved=1, failed=1"
    assert detail.result["output"]["download_results"] == download_results


def test_falls_back_to_message_column_when_result_json_missing() -> None:
    row = _FakeRow(
        message="Scraped Posts as diva: scraped=2, saved=2",
        result_json=None,
    )

    detail = _central_task_row_to_detail(row)  # type: ignore[arg-type]

    assert detail.result == {"message": "Scraped Posts as diva: scraped=2, saved=2"}


def test_returns_none_result_when_no_archive_fields() -> None:
    row = _FakeRow(message=None, result_json=None)

    detail = _central_task_row_to_detail(row)  # type: ignore[arg-type]

    assert detail.result is None


def test_message_column_does_not_override_result_json_message() -> None:
    payload = {"message": "detailed", "output": {}}
    row = _FakeRow(
        message="summary",
        result_json=json.dumps(payload),
    )

    detail = _central_task_row_to_detail(row)  # type: ignore[arg-type]

    assert detail.result is not None
    assert detail.result["message"] == "detailed"


def test_invalid_result_json_still_yields_message_fallback() -> None:
    row = _FakeRow(message="fallback", result_json="{not valid json")

    detail = _central_task_row_to_detail(row)  # type: ignore[arg-type]

    assert detail.result == {"message": "fallback"}
