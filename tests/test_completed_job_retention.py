"""Automatic Redis retirement retains ordinary durable history and active work."""

import time

import pytest
from sqlalchemy import text
import test_durable_job_history as history
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.job_system import storage as storage_module
from ultima_scraper_backend.services.terminal_job_reconciler import TerminalJobReconciler

postgres_engine = history.postgres_engine
store = history.store
redis_manager = history.redis_manager
window_runtime = history.window_runtime


async def test_reconciler_retires_completed_headers_without_remaining_task_blobs(
    store, window_runtime, monkeypatch
):
    completed = []
    for index in range(3):
        job = await history.windows.admit(
            window_runtime, tasks=[history.inputs.task(index, width=10)]
        )
        await history.complete_job(store, window_runtime, job.job_id)
        completed.append(job.job_id)
    active = await history.windows.admit(
        window_runtime, tasks=[history.inputs.task(99, width=10)]
    )
    reconciler = TerminalJobReconciler(window_runtime.redis)
    storage = reconciler.manager.storage
    storage.database_writes = mps_durable.DatabaseWriteClient(window_runtime.redis)
    client = storage._client()
    for job_id in completed:
        assert not await client.exists(storage.TASK_INDEX_KEY.format(job_id=job_id))
        assert await client.exists(storage.JOB_CONFIG_KEY.format(job_id=job_id))

    # Advance only the retention helper's cutoff clock; no deployment clock or
    # stored completion evidence changes. The active job must still survive.
    later = time.time() + storage.completed_job_retention_seconds + 1
    monkeypatch.setattr(storage_module, "_utc_timestamp", lambda: later)
    assert await reconciler.run_once() == 3
    for job_id in completed:
        assert not await client.exists(
            storage.JOB_CONFIG_KEY.format(job_id=job_id),
            storage.JOB_STATE_KEY.format(job_id=job_id),
        )
        assert store.get(job_id)["status"] == "complete"
    assert await client.exists(storage.JOB_CONFIG_KEY.format(job_id=active.job_id))
    with store.session_factory() as session:
        assert session.scalar(text(
            "SELECT count(*) FROM management.job_tasks WHERE status='completed'"
        )) == 3
    assert await reconciler.run_once() == 0


async def test_retirement_age_and_page_budget_are_independent_of_task_cleanup(
    store, window_runtime, monkeypatch
):
    for index in range(3):
        job = await history.windows.admit(
            window_runtime, tasks=[history.inputs.task(index, width=10)]
        )
        await history.complete_job(store, window_runtime, job.job_id)
    now = time.time()
    monkeypatch.setattr(storage_module, "_utc_timestamp", lambda: now + 3601)
    recent = TerminalJobReconciler(
        window_runtime.redis, retention_age_seconds=7200, retention_batch_size=1
    )
    recent.manager.storage.database_writes = mps_durable.DatabaseWriteClient(
        window_runtime.redis
    )
    assert await recent.run_once() == 0
    assert await window_runtime.redis.client.zcard(
        recent.manager.storage.JOB_INDEX_KEY
    ) == 3

    eligible = TerminalJobReconciler(
        window_runtime.redis,
        retention_age_seconds=3600,
        retention_batch_size=1,
        max_jobs_per_cycle=99,
    )
    eligible.manager.storage.database_writes = recent.manager.storage.database_writes
    assert [await eligible.run_once() for _ in range(4)] == [1, 1, 1, 0]
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 3


@pytest.mark.parametrize(
    "arguments", [
        {"retention_age_seconds": -1},
        {"retention_age_seconds": True},
        {"retention_batch_size": 0},
        {"retention_batch_size": 1.5},
    ]
)
def test_invalid_explicit_retention_settings_fail_before_initialization(arguments):
    with pytest.raises(ValueError, match="must be an integer"):
        TerminalJobReconciler(None, **arguments)


@pytest.mark.parametrize("value", ["0", "86401", "invalid", "1.5"])
def test_explicit_retention_environment_is_preserved_or_rejected(monkeypatch, value):
    from importlib import import_module

    api_app = import_module("ultima_scraper_backend.api.app")
    name = "USR_COMPLETED_JOB_RETENTION_SECONDS"
    monkeypatch.setattr(api_app, "runtime_env_value", lambda key: value)
    if value.isdecimal():
        assert api_app._env_int(name, 86400, strict=True) == int(value)
    else:
        with pytest.raises(ValueError, match=name):
            api_app._env_int(name, 86400, strict=True)
