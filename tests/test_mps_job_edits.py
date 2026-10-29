"""MPS edits preserve SQL selection, attempt history and due-time controls."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import test_execution_ledger as execution_fixtures
import test_mps_manifest as fixtures

from ultima_scraper_backend.job_system import Job, JobManager, JobSchedule, JobStorage
from ultima_scraper_backend.job_system import ledger as ledger_module

claim, finish = execution_fixtures.claim, execution_fixtures.finish
ledger, ledger_engine, postgres_engine = (
    execution_fixtures.ledger,
    execution_fixtures.ledger_engine,
    execution_fixtures.postgres_engine,
)


# Shared low-level archive fixtures are also imported by historical protocol tests.
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime
activate_materialized_job = JobManager.activate_materialized_job


async def prepared_window(store, runtime, *, archived):
    from ultima_scraper_backend.job_system import durable as mps_durable

    runtime.redis.hget = runtime.redis.client.hget
    runtime.redis.keys = runtime.redis.client.keys
    runtime.redis.smembers = runtime.redis.client.smembers
    plan = fixtures.prepare_runtime_plan(store, 1_000_000)
    storage = JobStorage(runtime.redis)
    await mps_durable.advance(runtime, plan["job_id"])
    if archived:
        await fixtures.complete_window(storage, plan["job_id"])
        assert await mps_durable.advance(runtime, plan["job_id"]) is True
        await mps_durable.advance(runtime, plan["job_id"])
    manager = JobManager(runtime.redis)
    manager.database_writes = runtime.writes
    return plan, storage, manager


@pytest.fixture
def mps_run(ledger, monkeypatch):
    job = Job.create(
        name="MPS fixture", created_by="test", tasks=[], metadata={"mps_manifest": True}
    )
    plan = ledger.manifests.create(
        job_id=job.job_id,
        site="onlyfans",
        job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": 1_000_000, "max_profiles": None},
        proxy_pool=[],
        site_session_factory=ledger.session_factory,
    )
    monkeypatch.setattr(ledger_module, "ExecutionLedger", lambda: ledger)
    return ledger, plan["job_id"], JobManager(SimpleNamespace())


@pytest.mark.parametrize("archived", [False, True])
async def test_name_edit_preserves_selection_and_checkpoint_without_redis(
    mps_run, archived
):
    ledger, job_id, manager = mps_run
    ledger.tick()
    if archived:
        finish(ledger, claim(ledger))
        ledger.tick()
    before = ledger.manifests.get(job_id)
    updated = await manager.update_job_by_id(job_id, name="  Renamed MPS  ")
    after = ledger.manifests.get(job_id)
    assert updated.name == "Renamed MPS"
    assert after["total"] == 1_000_000
    assert after["cursor"] == before["cursor"]
    assert after["completed"] == before["completed"]
    assert after["selection"] == before["selection"]
    with ledger.session_factory() as session:
        assert (
            session.scalar(text("SELECT count(*) FROM management.mps_candidate_ranges"))
            == 1
        )
        assert (
            session.scalar(
                text(
                    "SELECT args_json::json->>'job_name' FROM management.jobs WHERE job_id=:id"
                ),
                {"id": job_id},
            )
            == "Renamed MPS"
        )


async def test_future_schedule_defers_sql_window_and_claims(mps_run):
    ledger, job_id, manager = mps_run
    future = JobSchedule(
        scheduled_for=(datetime.now(UTC) + timedelta(days=1)).isoformat()
    )
    await manager.update_job_by_id(job_id, schedule=future)
    assert ledger.tick() is None and claim(ledger) is None
    assert ledger.stats(job_id)["ready"] == 0
    assert ledger.manifests.get(job_id)["cursor"] == 0
    assert (
        await manager.storage.fetch_job(job_id, include_tasks=False)
    ).schedule == future


async def test_due_schedule_uses_same_sql_window_without_redis_trigger(mps_run):
    ledger, job_id, manager = mps_run
    ledger.tick()
    before_ids = [row["task_id"] for row in ledger.task_page(job_id, limit=4)["tasks"]]
    future = JobSchedule(
        scheduled_for=(datetime.now(UTC) + timedelta(days=1)).isoformat()
    )
    await manager.update_job_by_id(job_id, schedule=future)
    assert claim(ledger) is None
    due = JobSchedule(
        scheduled_for=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    )
    await manager.update_job_by_id(job_id, schedule=due)
    owned = claim(ledger)
    assert owned.task_id in before_ids
    assert ledger.manifests.get(job_id)["cursor"] == 0


async def test_started_run_cannot_be_rescheduled(mps_run):
    ledger, job_id, manager = mps_run
    ledger.tick()
    owned = claim(ledger)
    future = JobSchedule(
        scheduled_for=(datetime.now(UTC) + timedelta(days=1)).isoformat()
    )
    with pytest.raises(ValueError, match="started run cannot be rescheduled"):
        await manager.update_job_by_id(job_id, schedule=future)
    assert ledger.renew(owned)


async def test_committed_edit_remains_readable_after_new_storage_instance(mps_run):
    ledger, job_id, manager = mps_run
    await manager.update_job_by_id(job_id, name="Committed rename")
    restored = await JobStorage(SimpleNamespace()).fetch_job(
        job_id, include_tasks=False
    )
    assert restored.name == "Committed rename" and restored.total_tasks == 1_000_000


async def test_postponed_schedule_cannot_be_released_by_an_earlier_due_snapshot(
    mps_run,
):
    ledger, job_id, manager = mps_run
    due = JobSchedule(
        scheduled_for=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    )
    await manager.update_job_by_id(job_id, schedule=due)
    ledger.tick()
    future = JobSchedule(
        scheduled_for=(datetime.now(UTC) + timedelta(days=1)).isoformat()
    )
    await manager.update_job_by_id(job_id, schedule=future)
    assert ledger.tick() is None and claim(ledger) is None
    assert ledger.job(job_id)["schedule"] == future.to_dict()


async def test_name_edit_does_not_reset_committed_attempt_results(mps_run):
    ledger, job_id, manager = mps_run
    ledger.tick()
    owned = claim(ledger)
    finish(ledger, owned)
    await manager.update_job_by_id(job_id, name="Still completing")
    assert ledger.stats(job_id)["completed"] == 1
    ledger.tick()
    assert ledger.manifests.get(job_id)["completed"] == 1
    assert ledger.task(job_id, owned.task_id)["result"]["success"]
    assert ledger.attempts(job_id)[0]["state"] == "completed"


async def test_api_metadata_edit_keeps_sql_history_in_agreement(mps_run):
    from ultima_scraper_backend.api.routes import jobs

    ledger, job_id, manager = mps_run
    updated = await jobs.update_job(
        job_id,
        jobs.UpdateJobRequest(job_name="Updated through API"),
        backend=SimpleNamespace(
            redis=SimpleNamespace(is_connected=True), distributed_mode=True
        ),
        backend_manager=SimpleNamespace(),
    )
    assert updated.job_name == "Updated through API" and updated.task_count == 1_000_000
    assert ledger.manifests.get(job_id)["job_config"]["name"] == updated.job_name
    with ledger.session_factory() as session:
        config = session.scalar(
            text("SELECT job_config_json FROM management.jobs WHERE job_id=:id"),
            {"id": job_id},
        )
        assert json.loads(config)["name"] == updated.job_name
