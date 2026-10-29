"""Terminal runtime metadata must commit before the Redis header is removed."""

import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

import test_durable_job_history as history
import test_normal_archive_generation as ordinary
import test_normal_task_windows as windows
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.job_system import JobStorage, retention
from ultima_scraper_backend.database import job_history
from ultima_scraper_backend.database import threads as database_threads

postgres_engine = history.postgres_engine
store = history.store
redis_manager = history.redis_manager
window_runtime = history.window_runtime
public_route_session = history.public_route_session


@pytest.mark.parametrize("durable", [False, True])
async def test_runtime_metadata_survives_retirement(
    store, window_runtime, monkeypatch, durable
):
    if durable:
        job = await windows.admit(window_runtime, count=3)
        await history.complete_job(store, window_runtime, job.job_id)
        storage = JobStorage(window_runtime.redis)
    else:
        storage, job = await ordinary.seed(window_runtime.redis, count=3)
    client = storage._client()
    config_key = storage.JOB_CONFIG_KEY.format(job_id=job.job_id)
    config = json.loads(await client.get(config_key))
    config["metadata"].update(run_count=9, last_ran_at="2026-09-08T10:00:00+00:00")
    await client.set(config_key, json.dumps(config))
    storage.database_writes = mps_durable.DatabaseWriteClient(window_runtime.redis)
    assert await storage.cleanup_completed_jobs(0, batch_size=1) == 1
    assert not await client.exists(config_key)
    app = history.app_for(monkeypatch, SimpleNamespace(redis=None))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as http:
        detail = await http.get(f"/jobs/{job.job_id}")
        listing = await http.get("/jobs")
    assert detail.status_code == listing.status_code == 200
    assert detail.json()["status"] == "completed"
    assert (
        detail.json()["task_stats"]["total"]
        == detail.json()["task_stats"]["completed"]
        == 3
    )
    assert detail.json()["run_count"] == 9
    assert listing.json()["jobs"][0]["run_count"] == 9
    assert detail.json()["last_ran_at"] == "2026-09-08T10:00:00+00:00"


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize(
    "phase", ["write_failure", "after_sql_commit", "new_sql_revision"]
)
async def test_header_archive_failure_or_change_prevents_removal(
    store, window_runtime, monkeypatch, durable, phase
):
    if durable:
        job = await windows.admit(window_runtime, count=2)
        await history.complete_job(store, window_runtime, job.job_id)
        storage = JobStorage(window_runtime.redis)
    else:
        storage, job = await ordinary.seed(window_runtime.redis, count=2)
    client = storage._client()
    config_key = storage.JOB_CONFIG_KEY.format(job_id=job.job_id)
    config = json.loads(await client.get(config_key))
    config["metadata"]["run_count"] = 7
    await client.set(config_key, json.dumps(config))
    storage.database_writes = mps_durable.DatabaseWriteClient(window_runtime.redis)
    original = job_history.archive_runtime_header
    calls = []

    def persist(*args, **kwargs):
        calls.append(phase)
        if phase == "write_failure":
            raise RuntimeError("fixture header commit unavailable")
        if phase == "new_sql_revision":
            table = "mps_plans" if durable else "jobs"
            with store.session_factory() as session:
                saved = json.loads(
                    session.scalar(
                        text(
                            f"SELECT job_config_json FROM management.{table} WHERE job_id=:job"
                        ),
                        {"job": job.job_id},
                    )
                )
                key = "mps_config_revision" if durable else "config_revision"
                saved["metadata"][key] = (
                    int(saved["metadata"].get(key, 0)) + 1 if durable else "new-config"
                )
                saved["name"] = "new SQL name"
                session.execute(
                    text(
                        f"UPDATE management.{table} SET job_config_json=:config WHERE job_id=:job"
                    ),
                    {"config": json.dumps(saved), "job": job.job_id},
                )
                session.commit()
        return original(*args, **kwargs)

    monkeypatch.setattr(job_history, "archive_runtime_header", persist)
    run = database_threads.run_database_call

    async def run_then_update(function, *args, **kwargs):
        result = await run(function, *args, **kwargs)
        if function is persist and phase == "after_sql_commit":
            current = json.loads(await client.get(config_key))
            current["metadata"]["run_count"] = 8
            await client.set(config_key, json.dumps(current))
        return result

    monkeypatch.setattr(database_threads, "run_database_call", run_then_update)
    assert await storage.cleanup_completed_jobs(0, batch_size=1) == 0
    assert calls and await client.exists(config_key)
    if phase != "new_sql_revision":
        monkeypatch.setattr(job_history, "archive_runtime_header", original)
        monkeypatch.setattr(database_threads, "run_database_call", run)
        assert await storage.cleanup_completed_jobs(0, batch_size=1) == 1
        assert not await client.exists(config_key)
        saved = job_history.headers(store.session_factory, [job.job_id])[job.job_id]
        assert saved["config"]["metadata"]["run_count"] == (
            8 if phase == "after_sql_commit" else 7
        )
    else:
        table = "mps_plans" if durable else "jobs"
        with store.session_factory() as session:
            saved = json.loads(
                session.scalar(
                    text(
                        f"SELECT job_config_json FROM management.{table} WHERE job_id=:job"
                    ),
                    {"job": job.job_id},
                )
            )
        assert saved["name"] == "new SQL name"


@pytest.mark.parametrize("durable", [False, True])
async def test_archive_merges_runtime_without_replacing_sql_controls(
    store, window_runtime, monkeypatch, durable
):
    if durable:
        job = await windows.admit(window_runtime, count=2)
        await history.complete_job(store, window_runtime, job.job_id)
        storage = JobStorage(window_runtime.redis)
    else:
        storage, job = await ordinary.seed(window_runtime.redis, count=2)
    client = storage._client()
    table = "mps_plans" if durable else "jobs"
    with store.session_factory() as session:
        config = json.loads(
            session.scalar(
                text(
                    f"SELECT job_config_json FROM management.{table} WHERE job_id=:job"
                ),
                {"job": job.job_id},
            )
        )
        config["metadata"].update(priority=123, user_option="SQL authority")
        session.execute(
            text(
                f"UPDATE management.{table} SET job_config_json=:config WHERE job_id=:job"
            ),
            {"job": job.job_id, "config": json.dumps(config)},
        )
        session.commit()
    key = storage.JOB_CONFIG_KEY.format(job_id=job.job_id)
    raw = json.loads(await client.get(key))
    raw["metadata"].update(run_count=8, priority=987)
    await client.set(key, json.dumps(raw))
    storage.database_writes = mps_durable.DatabaseWriteClient(window_runtime.redis)
    assert await storage.cleanup_completed_jobs(0, batch_size=1) == 1
    saved = job_history.headers(store.session_factory, [job.job_id])[job.job_id][
        "config"
    ]["metadata"]
    assert saved["run_count"] == 8
    assert saved["priority"] == 123 and saved["user_option"] == "SQL authority"


@pytest.mark.parametrize("source", ["redis", "postgres"])
async def test_oversized_header_is_retained(store, window_runtime, monkeypatch, source):
    job = await windows.admit(window_runtime, count=1)
    await history.complete_job(store, window_runtime, job.job_id)
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    key = storage.JOB_CONFIG_KEY.format(job_id=job.job_id)
    config = json.loads(await client.get(key))
    allowance = len(json.dumps(config).encode()) + 1024
    config["metadata"]["large"] = "x" * 20000
    if source == "redis":
        await client.set(key, json.dumps(config))
    else:
        with store.session_factory() as session:
            session.execute(
                text(
                    "UPDATE management.mps_plans SET job_config_json=:config WHERE job_id=:job"
                ),
                {"job": job.job_id, "config": json.dumps(config)},
            )
            session.commit()
    monkeypatch.setenv("ULTIMA_JOB_HEADER_ARCHIVE_MAX_BYTES", str(allowance))
    storage.database_writes = mps_durable.DatabaseWriteClient(window_runtime.redis)
    assert await storage.cleanup_completed_jobs(0, batch_size=1) == 0
    assert await client.exists(key)
    if source == "redis":
        from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded

        with pytest.raises(TaskPayloadBudgetExceeded):
            await retention.read_header(storage, job.job_id, max_bytes=allowance)


async def test_header_and_task_archive_budgets_are_independent(store, window_runtime, monkeypatch):
    job = await windows.admit(window_runtime, count=2)
    await history.complete_job(store, window_runtime, job.job_id)
    storage = JobStorage(window_runtime.redis)
    config_key = storage.JOB_CONFIG_KEY.format(job_id=job.job_id)
    raw = await storage._client().get(config_key)
    allowance = len(raw.encode() if isinstance(raw, str) else raw) + 2048
    monkeypatch.setenv("ULTIMA_JOB_TASK_ARCHIVE_MAX_BYTES", "128")
    monkeypatch.setenv("ULTIMA_JOB_HEADER_ARCHIVE_MAX_BYTES", str(allowance))
    storage.database_writes = mps_durable.DatabaseWriteClient(window_runtime.redis)
    assert retention.header_byte_limit(storage) == allowance
    assert storage.task_archive_limits()[1] == 128
    assert await storage.cleanup_completed_jobs(0, batch_size=1) == 1
    assert not await storage._client().exists(config_key)


async def test_queued_header_allowance_remains_authoritative(store, window_runtime, monkeypatch):
    storage, job = await ordinary.seed(window_runtime.redis, count=2)
    snapshot = await retention.capture_terminal(storage, job.job_id, max_bytes=10000)
    item = ordinary.command(job, archive_header=True, header_max_bytes=10000,
        archive_signature=retention.archive_signature(snapshot))
    monkeypatch.setenv("ULTIMA_JOB_HEADER_ARCHIVE_MAX_BYTES", "invalid-later-setting")
    result = await ordinary.execute(storage, item)
    assert result["archived_tasks"] == 2 and not result.get("stale")
    assert await storage._client().exists(storage.JOB_CONFIG_KEY.format(job_id=job.job_id))
