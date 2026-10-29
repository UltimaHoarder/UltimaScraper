from __future__ import annotations

import pytest
from redis import exceptions as redis_errors

from test_database_write_queue import _RecordingExecutor, redis_manager
from ultima_scraper_backend.database.write_queue import DatabaseWriterService
from ultima_scraper_backend.database.writer_runtime import _redis_restart_error

__all__ = ["redis_manager"]


@pytest.mark.parametrize(
    "error,retry",
    [
        (redis_errors.ConnectionError("server stopped"), True),
        (redis_errors.TimeoutError("transport timeout"), True),
        (redis_errors.BusyLoadingError("restoring persistence"), True),
        (redis_errors.ResponseError("NOGROUP No such consumer group"), True),
        (redis_errors.AuthenticationError("invalid credentials"), False),
        (redis_errors.AuthorizationError("permission denied"), False),
        (redis_errors.NoPermissionError("NOPERM operation denied"), False),
        (redis_errors.OutOfMemoryError("OOM command rejected"), False),
        (redis_errors.ResponseError("WRONGTYPE invalid key"), False),
    ],
)
def test_restart_retries_preserve_actionable_redis_failures(error, retry):
    assert _redis_restart_error(error) is retry


async def test_group_initialization_failure_still_closes_the_writer_executor(
    redis_manager,
    monkeypatch,
):
    executor = _RecordingExecutor()
    service = DatabaseWriterService(redis_manager, executor)

    async def unavailable():
        raise redis_errors.ConnectionError("Redis stopped during group initialization")

    monkeypatch.setattr(service, "_ensure_group", unavailable)
    with pytest.raises(redis_errors.ConnectionError):
        await service.run()
    assert executor.closed
