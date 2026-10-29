"""Transaction-boundary tests for the canonical PostgreSQL writer."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteCommand,
    DatabaseWriteOperation,
)


def _command(
    command_id: str,
    operation: DatabaseWriteOperation,
    payload: dict[str, Any],
    *,
    site: str | None = "onlyfans",
) -> DatabaseWriteCommand:
    return DatabaseWriteCommand(
        command_id=command_id,
        operation=operation,
        site=site,
        payload=payload,
        producer_id="test-worker",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


class _ScalarRows(list):
    def all(self):
        return self


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.info = {}

    def execute(self, _statement: object, _parameters: object = None) -> object:
        # Transaction-shape fixture. Durable replay/rollback is tested against
        # native PostgreSQL in test_database_write_receipts.py.
        return SimpleNamespace(scalars=lambda: _ScalarRows())

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def flush(self) -> None:
        pass

    def connection(self, **_kwargs: object) -> object:
        # Non-PostgreSQL dialects take the plain session.execute insert path.
        return SimpleNamespace(dialect=SimpleNamespace(name="fixture"))

    def get_nested_transaction(self) -> None:
        return None

    def get_transaction(self) -> _Session:
        return self


class _DownloadDatabaseManager:
    def __init__(self, *, fail_sizes: bool = False) -> None:
        self.session = _Session()
        self.session_requests = 0
        self.calls: list[tuple[str, object]] = []
        self.fail_sizes = fail_sizes

    def get_session(self) -> _Session:
        self.session_requests += 1
        return self.session

    def mark_media_downloaded(self, media_ids: list[int], *, session: _Session) -> int:
        assert session is self.session
        self.calls.append(("downloaded", media_ids))
        return len(media_ids)

    def update_user(
        self,
        user_id: int,
        values: dict[str, Any],
        *,
        session: _Session,
    ) -> object:
        assert session is self.session
        self.calls.append(("user", (user_id, values)))
        return object()

    def batch_record_filepaths(
        self,
        rows: list[tuple[int, str, bool, bool]],
        *,
        session: _Session,
    ) -> int:
        assert session is self.session
        self.calls.append(("filepaths", rows))
        return len(rows)

    def update_media_sizes_bulk(
        self,
        sizes: dict[int, int],
        *,
        session: _Session,
    ) -> int:
        assert session is self.session
        self.calls.append(("sizes", sizes))
        if self.fail_sizes:
            raise RuntimeError("size update failed")
        return len(sizes)


def _executor_with_site_manager(manager: object) -> PostgreSQLWriteExecutor:
    executor = PostgreSQLWriteExecutor.__new__(PostgreSQLWriteExecutor)
    executor._site_manager = lambda _site: manager  # type: ignore[method-assign]
    executor.redis = SimpleNamespace()
    return executor


def test_finalize_download_batch_commits_once() -> None:
    manager = _DownloadDatabaseManager()
    executor = _executor_with_site_manager(manager)
    commands = [
        _command(
            "download-1",
            DatabaseWriteOperation.FINALIZE_DOWNLOAD,
            {
                "user_id": 10,
                "media_ids": [101, 102],
                "downloaded_at": "2026-09-04T12:00:00+00:00",
                "filepaths": [[101, "/media/a.mp4", True, False]],
                "media_sizes": {"101": 1234},
            },
        ),
        _command(
            "download-2",
            DatabaseWriteOperation.FINALIZE_DOWNLOAD,
            {
                "user_id": 20,
                "media_ids": [201],
                "downloaded_at": None,
                "filepaths": [[201, "/media/b.mp4", False, False]],
                "media_sizes": {"201": 5678},
            },
        ),
    ]

    results = executor._finalize_downloads(commands, "onlyfans")

    assert results == {
        "download-1": {
            "marked_downloaded": 2,
            "user_updated": True,
            "filepaths": 1,
            "media_sizes": 1,
        },
        "download-2": {
            "marked_downloaded": 1,
            "user_updated": False,
            "filepaths": 1,
            "media_sizes": 1,
        },
    }
    assert manager.session_requests == 1
    assert manager.session.commits == 1
    assert manager.session.rollbacks == 0


def test_finalize_download_batch_rolls_back_as_one_unit() -> None:
    manager = _DownloadDatabaseManager(fail_sizes=True)
    executor = _executor_with_site_manager(manager)
    command = _command(
        "download-failure",
        DatabaseWriteOperation.FINALIZE_DOWNLOAD,
        {
            "user_id": 10,
            "media_ids": [101],
            "downloaded_at": None,
            "filepaths": [],
            "media_sizes": {"101": 1234},
        },
    )

    with pytest.raises(RuntimeError, match="size update failed"):
        executor._finalize_downloads([command], "onlyfans")

    assert manager.session.commits == 0
    assert manager.session.rollbacks == 1


@pytest.mark.asyncio
async def test_executor_rejects_mixed_operation_batches() -> None:
    executor = _executor_with_site_manager(object())
    commands = [
        _command(
            "job-status",
            DatabaseWriteOperation.SYNC_JOB_STATUS,
            {"job_id": "job-1", "status": "running"},
            site=None,
        ),
        _command(
            "task-status",
            DatabaseWriteOperation.SYNC_TASK_STATUS,
            {"task_id": "task-1", "status": "running"},
            site=None,
        ),
    ]

    with pytest.raises(ValueError, match="one operation and one site"):
        await executor.execute_batch(commands)


@pytest.mark.asyncio
async def test_archive_command_requires_job_generation() -> None:
    executor = _executor_with_site_manager(object())

    with pytest.raises(ValueError, match="missing its job generation"):
        await executor._archive_job_tasks(
            [
                _command(
                    "archive-without-generation",
                    DatabaseWriteOperation.ARCHIVE_JOB_TASKS,
                    {"job_id": "job-1", "batch_size": 500},
                    site=None,
                )
            ]
        )
