"""Shared recovery and producer policies keep bounded access and compatibility."""

from types import SimpleNamespace

import fakeredis.aioredis
import pytest
from ultima_scraper_backend.job_system import JobStorage, materializer, resources


@pytest.mark.parametrize("total", [100, 1_000_000])
async def test_processing_recovery_requests_only_a_bounded_page(monkeypatch, total):
    requested = []

    class VirtualProcessing:
        async def lrange(self, key, start, end):
            assert 0 <= start <= end < total
            assert end - start + 1 <= 3
            requested.append((start, end))
            return [f"job-{index}" for index in range(start, end + 1)]

        async def exists(self, key):
            return True

    monkeypatch.setenv("ULTIMA_JOB_RECOVERY_BATCH_SIZE", "3")
    runtime = SimpleNamespace(redis=SimpleNamespace(client=VirtualProcessing()))
    after = await materializer._recover_stale_mps_materializations(
        runtime, after=total - 6
    )
    assert after == total - 3
    await materializer._recover_stale_mps_materializations(runtime, after=after)
    assert requested == [(total - 6, total - 4), (total - 3, total - 1)]


async def test_recovery_pages_do_not_starve_entries_behind_owned_jobs(monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_RECOVERY_BATCH_SIZE", "3")
    async with fakeredis.aioredis.FakeRedis() as client:
        processing = materializer.MPS_MATERIALIZATION_PROCESSING_KEY
        queue = materializer.MPS_MATERIALIZATION_QUEUE_KEY
        await client.rpush(processing, *(f"job-{i}" for i in range(11)))
        for index in (0, 1, 5):
            await client.set(
                materializer._mps_materialization_lock_key(f"job-{index}"), "owner"
            )
        runtime = SimpleNamespace(redis=SimpleNamespace(client=client))
        after = 0
        for _ in range(6):
            after = await materializer._recover_stale_mps_materializations(
                runtime, after=after
            )
        assert set(await client.lrange(processing, 0, -1)) == {
            b"job-0",
            b"job-1",
            b"job-5",
        }
        queued = await client.lrange(queue, 0, -1)
        assert len(queued) == 8 and set(queued) == {
            f"job-{i}".encode() for i in (2, 3, 4, 6, 7, 8, 9, 10)
        }


@pytest.mark.parametrize("scope", ["ordinary", "mps"])
def test_all_producers_use_shared_window_limits(monkeypatch, scope):
    for key, value in {
        "WINDOW_MAX_TASKS": 7,
        "WINDOW_MAX_BYTES": 12000,
        "GLOBAL_WINDOW_MAX_TASKS": 21,
        "GLOBAL_WINDOW_MAX_BYTES": 48000,
    }.items():
        monkeypatch.setenv(f"ULTIMA_JOB_{key}", str(value))
        monkeypatch.setenv(f"ULTIMA_MPS_{key}", "999999")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_BATCH_SIZE", "3")
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_MAX_BYTES", "5000")
    storage = JobStorage(SimpleNamespace())
    explicit = resources.window_policy({"job_resource_scope": scope}, storage)
    legacy = resources.window_policy({"durable_job_kind": scope}, storage)
    assert explicit == legacy
    assert (
        explicit.tasks,
        explicit.bytes,
        explicit.global_tasks,
        explicit.global_bytes,
    ) == (7, 12000, 21, 48000)
    assert (explicit.input_rows, explicit.input_bytes) == (
        (3, 5000) if scope == "ordinary" else (7, 12000)
    )
    from ultima_scraper_backend.job_system import mps_state

    assert (explicit.budget_key, explicit.waiting_key, explicit.waiting_set_key) == (
        mps_state.BUDGET_KEY,
        mps_state.WAITING_KEY,
        mps_state.WAITING_SET_KEY,
    )


def test_removed_mps_window_settings_do_not_override_shared_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ultima_scraper_core.environment.get_env_path", lambda: tmp_path / ".env"
    )
    for key in (
        "WINDOW_MAX_TASKS", "WINDOW_MAX_BYTES",
        "GLOBAL_WINDOW_MAX_TASKS", "GLOBAL_WINDOW_MAX_BYTES",
    ):
        monkeypatch.delenv(f"ULTIMA_JOB_{key}", raising=False)
        monkeypatch.setenv(f"ULTIMA_MPS_{key}", "1")
    monkeypatch.setenv("ULTIMA_DATABASE_WRITE_MAX_COMMAND_BYTES", "65536")
    policy = resources.window_policy({}, JobStorage(SimpleNamespace()))
    assert (policy.tasks, policy.global_tasks) == (1000, 1000)
    assert (policy.bytes, policy.global_bytes) == (65536, 65536)


def test_shared_recovery_setting_preserves_legacy_fallback(monkeypatch):
    monkeypatch.setenv("ULTIMA_MPS_RECOVERY_BATCH_SIZE", "3")
    assert resources.recovery_page_size(10) == 3
    monkeypatch.setenv("ULTIMA_JOB_RECOVERY_BATCH_SIZE", "7")
    assert resources.recovery_page_size(10) == 7


@pytest.mark.parametrize("explicit", [False, True])
async def test_budget_retirement_uses_resolved_scope_and_accepts_old_windows(explicit):
    from ultima_scraper_backend.job_system import mps_state

    async with fakeredis.aioredis.FakeRedis() as client:
        fields = {
            "window_class": "ordinary",
            "reserved_tasks": 3,
            "reserved_bytes": 5000,
        }
        if explicit:
            # Resource ownership comes from resolved keys, independently of the
            # old descriptive job kind. Old plans still use their legacy class.
            fields.update(
                window_class="legacy-description",
                window_budget_key=mps_state.BUDGET_KEY,
                window_waiting_key=mps_state.WAITING_KEY,
                window_waiting_set_key=mps_state.WAITING_SET_KEY,
            )
        await client.hset(mps_state.PLAN_KEY.format(job_id="owner"), mapping=fields)
        await client.hset(mps_state.PLAN_KEY.format(job_id="waiting"), mapping=fields)
        await client.hset(
            mps_state.BUDGET_KEY, mapping={"tasks": 3, "bytes": 5000}
        )
        await mps_state.wait_for_budget(client, "waiting")
        assert await client.lrange(mps_state.WAITING_KEY, 0, -1) == [
            b"waiting"
        ]
        await mps_state.release_budget(client, "owner")
        assert await client.hmget(mps_state.BUDGET_KEY, "tasks", "bytes") == [
            b"0",
            b"0",
        ]
        assert await client.lrange(mps_state.QUEUE_KEY, 0, -1) == [b"waiting"]
        await mps_state.release_budget(client, "owner")
        assert await client.hmget(mps_state.BUDGET_KEY, "tasks", "bytes") == [
            b"0",
            b"0",
        ]
