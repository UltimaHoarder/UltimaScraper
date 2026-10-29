"""Runtime header capacity is independent of the durable job population."""

import asyncio
import copy
import json
from types import SimpleNamespace

import fakeredis.aioredis
import pytest

from ultima_scraper_backend.job_system import Job, JobStorage, durable, runtime_admission

# These exercise the Redis runtime; the SQL execution ledger holds no runs.
pytestmark = pytest.mark.usefixtures("no_ledger_runs")


def storage_for(client):
    return JobStorage(SimpleNamespace(client=client, get=client.get, delete=client.delete))


def plan_for(job_id, *, total=1_000_000, name="Fixture", scope="ordinary"):
    job = Job(name=name, created_by="fixture", job_id=job_id, tasks=[], metadata={
        "mps_manifest": True, "mps_task_manifest": f"definition-{job_id}",
        "job_resource_scope": scope, "durable_job_kind": scope,
    })
    return dict(job_id=job_id, site="onlyfans", status="ready", total=total,
                cursor=0, completed=0, failed=0, job_config=job.to_dict(),
                selection={"task_manifest_id": f"definition-{job_id}"})


def install_store(monkeypatch, plans):
    monkeypatch.setattr(durable, "MPSManifestStore", lambda: SimpleNamespace(
        get=lambda job_id: copy.deepcopy(plans[job_id])
    ))


async def assert_budget(client, storage, count, *, maximum=None):
    fields = await client.hgetall(runtime_admission.LEDGER_KEY)
    fields = {key.decode(): int(value) for key, value in fields.items()}
    assert fields.get("count", 0) == count
    assert await client.zcard(storage.JOB_INDEX_KEY) == count
    sizes = [await client.strlen(storage.JOB_CONFIG_KEY.format(job_id=key[2:]))
             for key in fields if key.startswith("j:")]
    assert len(sizes) == count and sum(sizes) <= fields.get("bytes", 0)
    assert all(size <= fields[key] for key, size in zip((key for key in fields if key.startswith("j:")), sizes))
    if maximum is not None:
        assert fields.get("bytes", 0) <= maximum


@pytest.mark.parametrize("logical_jobs", [100, 1_000_000])
async def test_concurrent_durable_publications_wait_without_extra_headers(monkeypatch, logical_jobs):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "3")
    ids = [f"job-{start+i}" for start in (0, logical_jobs//2, logical_jobs-5) for i in range(5)]
    plans = {job_id: plan_for(job_id) for job_id in ids}
    install_store(monkeypatch, plans)
    async with fakeredis.aioredis.FakeRedis() as client:
        storage = storage_for(client)
        outcomes = await asyncio.gather(*(durable.publish(storage, plan) for plan in plans.values()))
        assert all(job.total_tasks == 1_000_000 for job in outcomes)
        await assert_budget(client, storage, 3)
        assert await client.exists(runtime_admission.PRESSURE_KEY)
        assert await client.scard(durable.mps_state.SCHEDULED_KEY) == 3
        assert len(plans) == 15  # Only bounded samples exist in this virtual source.


async def test_encoded_configurations_share_a_byte_budget(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "100")
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_BYTES", "6000")
    plans = {f"job-{i}": plan_for(f"job-{i}", name="é"*150) for i in range(9)}
    install_store(monkeypatch, plans)
    async with fakeredis.aioredis.FakeRedis() as client:
        storage = storage_for(client)
        outcomes = await asyncio.gather(*(durable.publish(storage, plan) for plan in plans.values()))
        assert all(job.total_tasks == 1_000_000 for job in outcomes)
        count = await client.zcard(storage.JOB_INDEX_KEY)
        assert 0 < count < len(plans)
        await assert_budget(client, storage, count, maximum=6000)


async def test_ordinary_publication_uses_the_same_ledger_and_limit(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "1")
    async with fakeredis.aioredis.FakeRedis() as client:
        storage = storage_for(client)
        first = Job(name="Manual", created_by="fixture", tasks=[])
        second = Job(name="Excess", created_by="fixture", tasks=[])
        await storage.persist_job(first)
        with pytest.raises(runtime_admission.RuntimeAdmissionDeferred):
            await storage.persist_job(second)
        assert await storage.fetch_job(second.job_id, include_tasks=False) is None
        await assert_budget(client, storage, 1)
        first.name = "Updated manual name"
        await storage.persist_job(first)
        await assert_budget(client, storage, 1)


async def test_partial_legacy_accounting_blocks_new_byte_admission(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "10")
    async with fakeredis.aioredis.FakeRedis() as client:
        storage = storage_for(client)
        for i in range(3):
            job = Job(name="Old", created_by="fixture", tasks=[], job_id=f"old-{i}")
            await client.set(storage.JOB_CONFIG_KEY.format(job_id=job.job_id), json.dumps(job.to_config().to_dict()))
            await client.zadd(storage.JOB_INDEX_KEY, {job.job_id: i})
        newcomer = Job(name="New", created_by="fixture", tasks=[])
        with pytest.raises(runtime_admission.RuntimeAdmissionDeferred):
            await storage.persist_job(newcomer)
        await runtime_admission.reconcile(storage, limit=2)
        assert int(await client.hget(runtime_admission.LEDGER_KEY, "count")) == 2
        with pytest.raises(runtime_admission.RuntimeAdmissionDeferred):
            await storage.persist_job(newcomer)
        await runtime_admission.reconcile(storage, limit=2)
        await storage.persist_job(newcomer)
        await assert_budget(client, storage, 4)
        # A lost whole ledger is rebuilt from another bounded pass, without
        # admitting work against a retained but incomplete byte total.
        await client.delete(runtime_admission.LEDGER_KEY)
        with pytest.raises(runtime_admission.RuntimeAdmissionDeferred):
            await storage.persist_job(Job(name="Later", created_by="fixture", tasks=[]))
        for _ in range(3):
            await runtime_admission.reconcile(storage, limit=2)
        await assert_budget(client, storage, 4)


async def test_deletion_releases_the_charge_atomically_and_allows_waiting_work(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "1")
    async with fakeredis.aioredis.FakeRedis() as client:
        storage = storage_for(client)
        first = Job(name="First", created_by="fixture", tasks=[])
        second = Job(name="Second", created_by="fixture", tasks=[])
        await storage.persist_job(first)
        with pytest.raises(runtime_admission.RuntimeAdmissionDeferred):
            await storage.persist_job(second)
        await storage.delete_job(first.job_id)
        await assert_budget(client, storage, 0)
        await storage.delete_job(first.job_id)
        await assert_budget(client, storage, 0)
        await storage.persist_job(second)
        await assert_budget(client, storage, 1)


async def test_full_byte_budget_still_allows_runtime_identity_and_failure_updates(monkeypatch):
    plan = plan_for("running")
    install_store(monkeypatch, {"running": plan})
    async with fakeredis.aioredis.FakeRedis() as client:
        storage = storage_for(client)
        job = await durable.publish(storage, plan)
        reservation = int(await client.hget(runtime_admission.LEDGER_KEY, "bytes"))
        monkeypatch.setenv("ULTIMA_JOB_RUNTIME_METADATA_MAX_BYTES", "4096")
        monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_BYTES", str(reservation))
        job.metadata.update(worker_id="worker-1", backend_id="backend-1", failure_reason="é" * 100_000)
        await storage.persist_job(job)
        await assert_budget(client, storage, 1, maximum=reservation)
        assert int(await client.hget(runtime_admission.LEDGER_KEY, "bytes")) == reservation
        cached = await storage.fetch_job(job.job_id, include_tasks=False)
        assert cached.metadata["worker_id"] == "worker-1"
        assert cached.metadata["backend_id"] == "backend-1"
        assert cached.metadata["failure_reason"].endswith("…")
        assert len(cached.metadata["failure_reason"]) < 100_000
        assert job.metadata["failure_reason"] == "é" * 100_000


async def test_a_header_larger_than_its_reservation_budget_is_rejected(monkeypatch):
    from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded

    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_BYTES", "4096")
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_METADATA_MAX_BYTES", "4096")
    async with fakeredis.aioredis.FakeRedis() as client:
        storage = storage_for(client)
        job = Job(name="Too large with runtime metadata", created_by="fixture", tasks=[])
        with pytest.raises(TaskPayloadBudgetExceeded):
            await storage.persist_job(job)
        assert not await client.exists(runtime_admission.LEDGER_KEY)
        assert not await client.exists(runtime_admission.PRESSURE_KEY)
        assert not await client.zcard(storage.JOB_INDEX_KEY)


async def test_partial_cache_loss_retires_orphaned_charge_with_its_index(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "1")
    async with fakeredis.aioredis.FakeRedis() as client:
        storage = storage_for(client)
        job = Job(name="Evicted header", created_by="fixture", tasks=[])
        await storage.persist_job(job)
        await client.delete(storage.JOB_CONFIG_KEY.format(job_id=job.job_id), storage.JOB_STATE_KEY.format(job_id=job.job_id))
        assert await storage.cleanup_completed_jobs(0, batch_size=1, max_deleted=1) == 1
        await assert_budget(client, storage, 0)
        await storage.persist_job(Job(name="Next", created_by="fixture", tasks=[]))
        await assert_budget(client, storage, 1)
