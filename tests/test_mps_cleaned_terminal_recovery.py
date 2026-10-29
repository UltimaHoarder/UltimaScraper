"""A terminal job whose live index was cleaned must close its SQL plan."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ultima_scraper_backend.job_system import durable, JobState


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [JobState.CANCELLED, JobState.FAILED, JobState.RUNNING])
@pytest.mark.parametrize("index_present", [False, True])
@pytest.mark.parametrize("replacement", [False, True])
async def test_recovery_closes_cleaned_terminal_window_without_reading_task_evidence(state, replacement, index_present):
    backend = SimpleNamespace(redis=MagicMock())
    storage = MagicMock()
    client = storage._client.return_value
    client.exists = AsyncMock(return_value=index_present)
    client.hgetall = AsyncMock(side_effect=AssertionError("Cleaned terminal windows must not be drained"))
    storage.fetch_job = AsyncMock(return_value=SimpleNamespace(
        state=state, metadata={"mps_task_manifest": "replacement" if replacement else "manifest"},
    ))
    plan = {"status":"ready", "cursor":639585, "total":3152000,
            "completed":639580, "failed":5, "selection":{"task_manifest_id":"manifest"},
            # Store rows always carry the job config; this one is not ledger-owned.
            "job_config":{"metadata":{}}}
    store = MagicMock()
    store.get.return_value = plan
    with patch.object(durable, "JobStorage", return_value=storage), patch.object(durable, "MPSManifestStore", return_value=store), patch.object(durable, "ensure_plan", new_callable=AsyncMock), patch.object(durable, "_terminate_runtime_mps_job", new_callable=AsyncMock) as terminate:
        should_reconcile = not replacement and not index_present and state in {JobState.CANCELLED, JobState.FAILED}
        if not replacement and not should_reconcile:
            with pytest.raises(AssertionError, match="Cleaned terminal windows"):
                await durable.advance(backend, "job-test", activate=False)
            terminate.assert_not_awaited()
            client.hgetall.assert_awaited_once()
            return
        assert await durable.advance(backend, "job-test", activate=False) is False
        if replacement:
            terminate.assert_not_awaited()
            client.exists.assert_not_awaited()
        else:
            terminate.assert_awaited_once_with(backend.redis, storage, storage.fetch_job.return_value, "manifest")
            client.exists.assert_awaited_once_with(storage.TASK_INDEX_KEY.format(job_id="job-test"))
        client.hgetall.assert_not_awaited()
