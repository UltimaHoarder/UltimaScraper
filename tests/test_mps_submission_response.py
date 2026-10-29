"""Submission must return its durable job instead of failing after publication."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from ultima_scraper_backend.api.routes import jobs, mps, mps_durable
from ultima_scraper_backend.job_system import Job


@pytest.mark.parametrize("deleted", [False, True])
async def test_mps_submission_presents_published_job(monkeypatch, deleted):
    committed = []

    class Writes:
        def __init__(self, *args, **kwargs):
            pass

        async def submit(self, operation, payload, **kwargs):
            committed.append(payload)
            return {
                "job_config": payload["job_config"],
                "total": 50_000,
                "summary": {
                    "candidate_count": 50_000,
                    "missing_count": 50_000,
                    "invalid_eligible_count": 0,
                    "existing_eligible_count": 0,
                },
            }

    async def publish(storage, plan):
        return None if deleted else Job.from_dict(plan["job_config"])

    monkeypatch.setattr(mps_durable, "DatabaseWriteClient", Writes)
    monkeypatch.setattr(mps_durable.durable, "publish", publish)
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    monkeypatch.setattr(
        mps,
        "_resolve_analysis_scope",
        AsyncMock(
            return_value=SimpleNamespace(
                site_display="OnlyFans", site_key="onlyfans", start_id=1, end_id=50_000
            )
        ),
    )
    monkeypatch.setattr(mps, "_resolve_proxy_pool", lambda **kwargs: [])
    monkeypatch.setattr(mps, "_resolve_proxy_pool_capacity", lambda **kwargs: 0)
    request = mps.MPSCreateJobRequest(start_id=1, end_id=50_000, max_profiles=50_000)
    backend = SimpleNamespace(redis=SimpleNamespace(is_connected=True))
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[]))
    )
    if deleted:
        with pytest.raises(HTTPException) as error:
            await mps.create_mps_job(request, backend, SimpleNamespace(), config)
        assert error.value.status_code == 409
        jobs.publish_ws_event.assert_not_awaited()
    else:
        response = await mps.create_mps_job(request, backend, SimpleNamespace(), config)
        assert response.selected_profiles == 50_000
        assert response.job.job_id == committed[0]["job_id"]
        assert response.model_dump(mode="json")["job"]["job_id"] == response.job.job_id
        jobs.publish_ws_event.assert_awaited_once()
        assert jobs.publish_ws_event.await_args.args[1]["job_id"] == response.job.job_id
    assert len(committed) == 1
