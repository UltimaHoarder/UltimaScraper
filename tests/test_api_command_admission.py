"""A burst of worker API commands must not exhaust the API's connection pool."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ultima_scraper_backend.database.threads import API_COMMAND_ADMISSION_LIMIT
from ultima_scraper_backend.job_system.models import TaskState
from ultima_scraper_backend.manager import BackendManager


async def test_a_burst_of_commands_is_written_a_few_at_a_time() -> None:
    writing = 0
    most_writing = 0

    async def prepare_job(job, **_kwargs):
        nonlocal writing, most_writing
        writing += 1
        most_writing = max(most_writing, writing)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        writing -= 1
        return job

    manager = BackendManager.__new__(BackendManager)
    activate = AsyncMock()
    manager._job_manager = SimpleNamespace(prepare_job=prepare_job, activate_job=activate)
    manager._job_storage = SimpleNamespace(
        fetch_task=AsyncMock(
            return_value=SimpleNamespace(
                state=TaskState.COMPLETED,
                result=SimpleNamespace(success=True, message="done", output={}),
            )
        )
    )

    results = await asyncio.gather(
        *(
            manager._submit_worker_api_command(
                "onlyfans", "refresh_profile", {"user_id": user_id}, None, guest=True
            )
            for user_id in range(50)
        )
    )

    assert all(result.success for result in results)
    assert activate.await_count == 50
    assert most_writing == API_COMMAND_ADMISSION_LIMIT
