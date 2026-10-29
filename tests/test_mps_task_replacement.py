"""Durable task edits must control bounded MPS admission after Redis loss."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text

import test_mps_job_edits as fixtures
from ultima_scraper_backend.api.routes import mps_history
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
from ultima_scraper_backend.job_system import JobSchedule, Task, TaskResult, TaskState
from ultima_scraper_backend.job_system.models import TaskType
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


@pytest.mark.parametrize("archived", [False, True])
async def test_edited_tasks_replace_selection_after_redis_loss(
    store, window_runtime, archived
):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=archived
    )
    job_id = plan["job_id"]
    live = [task async for task in storage.fetch_tasks_stream(job_id)]
    replacement = Task.from_dict(live[0].to_dict())
    replacement.task_id = f"task-{uuid4().hex}"
    await manager.update_job_by_id(
        job_id, tasks=iter([replacement]), route_immediate_job=False
    )
    assert await legacy.list_tasks_for_job(storage, job_id) == [replacement.task_id]
    assert store.get(job_id)["total"] == 1
    await storage._client().flushall()
    await mps_durable.recover(window_runtime)
    await mps_durable.advance(window_runtime, job_id)
    assert await legacy.list_tasks_for_job(storage, job_id) == [replacement.task_id]


@pytest.mark.parametrize("failed_parent", [False, True])
async def test_mixed_dependencies_cross_windows_and_survive_redis_loss(
    store, window_runtime, failed_parent
):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=True
    )
    job_id = plan["job_id"]
    parent = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=41)
    download = Task(
        task_type=TaskType.DOWNLOAD,
        site_name="OnlyFans",
        user_id=41,
        depends_on=[parent.task_id],
    )
    # Put the child first to exercise readiness rather than submission order.
    await manager.update_job_by_id(job_id, tasks=[download, parent])
    assert await legacy.list_tasks_for_job(storage, job_id) == [parent.task_id]
    assert (await storage.get_job_task_stats(job_id))["task_type_counts"] == {
        "scrape": 1,
        "download": 1,
    }
    parent = await storage.fetch_task(job_id, parent.task_id)
    assert await legacy.mark_task_started(storage, job_id, parent.task_id)
    parent.state = TaskState.FAILED if failed_parent else TaskState.COMPLETED
    parent.result = TaskResult(
        success=not failed_parent, output={"selected_media": ["fixture"]}
    )
    await legacy.persist_task_result(storage, job_id, parent)
    if failed_parent:
        await legacy.mark_task_failed(storage, job_id, parent.task_id)
    else:
        await legacy.mark_task_completed(storage, job_id, parent.task_id)
    assert await mps_durable.advance(window_runtime, job_id)
    await storage._client().flushall()
    await mps_durable.recover(window_runtime)
    await mps_durable.advance(window_runtime, job_id)
    assert await legacy.list_tasks_for_job(storage, job_id) == [download.task_id]
    active = await storage.fetch_task(job_id, download.task_id)
    assert active.depends_on == [parent.task_id]
    if failed_parent:
        assert active.state == TaskState.FAILED
        assert "dependency failed" in active.result.message
    else:
        assert active.state == TaskState.PENDING
        assert (
            await storage.get_task_output(job_id, parent.task_id)
            == parent.result.output
        )
        await fixtures.fixtures.complete_window(storage, job_id)
    await mps_durable.advance(window_runtime, job_id)
    assert store.get(job_id)["cursor"] == 2
    assert store.get(job_id)["failed"] == (2 if failed_parent else 0)
    page = await mps_history.task_page(
        storage, job_id, offset=0, limit=2, task_type="download"
    )
    assert [task.task_id for task in page.tasks] == [download.task_id]
    assert page.tasks[0].status == ("failed" if failed_parent else "completed")


async def test_partial_upload_leaves_current_selection_authoritative(
    store, window_runtime, monkeypatch
):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=True
    )
    job_id = plan["job_id"]
    original = await legacy.list_tasks_for_job(storage, job_id)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    submit = manager.database_writes.submit
    offsets = []

    async def fail_second_chunk(operation, payload, **kwargs):
        if operation == DatabaseWriteOperation.APPEND_MPS_REPLACEMENT:
            offsets.append(payload["offset"])
            if payload["offset"] > 0:
                raise RuntimeError("injected upload interruption")
        return await submit(operation, payload, **kwargs)

    monkeypatch.setattr(manager.database_writes, "submit", fail_second_chunk)
    tasks = (
        Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=i)
        for i in range(30, 35)
    )
    with pytest.raises(RuntimeError, match="upload interruption"):
        await manager.update_job_by_id(job_id, tasks=tasks)
    assert offsets == [0, 2]
    assert store.get(job_id)["total"] == 1_000_000
    assert store.get(job_id)["cursor"] == 3
    assert await legacy.list_tasks_for_job(storage, job_id) == original


async def test_committed_edit_recovers_when_response_is_lost(
    store, window_runtime, monkeypatch
):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=True
    )
    job_id = plan["job_id"]
    old_ids = await legacy.list_tasks_for_job(storage, job_id)
    replacement = Task(task_type=TaskType.DOWNLOAD, site_name="OnlyFans", user_id=77)
    submit = manager.database_writes.submit

    async def lose_commit_reply(operation, payload, **kwargs):
        result = await submit(operation, payload, **kwargs)
        if operation == DatabaseWriteOperation.COMMIT_MPS_REPLACEMENT:
            raise RuntimeError("injected lost commit reply")
        return result

    monkeypatch.setattr(manager.database_writes, "submit", lose_commit_reply)
    with pytest.raises(RuntimeError, match="lost commit reply"):
        await manager.update_job_by_id(job_id, tasks=[replacement])
    assert store.get(job_id)["total"] == 1
    assert await legacy.list_tasks_for_job(storage, job_id) == old_ids
    await mps_durable.recover(window_runtime)
    await mps_durable.advance(window_runtime, job_id)
    assert await legacy.list_tasks_for_job(storage, job_id) == [replacement.task_id]
    budget = await storage._client().hgetall(mps_durable.mps_state.BUDGET_KEY)
    assert int(budget.get(b"tasks", budget.get("tasks", 0))) == 1


async def test_replacement_stream_respects_count_and_wire_byte_budgets(
    store, window_runtime, monkeypatch
):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=False
    )
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "3")
    writes = manager.database_writes
    writes.max_command_bytes = writes.max_queue_bytes = 3500
    submit = writes.submit
    consumed = 0
    uploaded = 0
    batch_counts = []

    async def observe_upload(operation, payload, **kwargs):
        nonlocal uploaded
        if operation == DatabaseWriteOperation.APPEND_MPS_REPLACEMENT:
            assert 1 <= len(payload["tasks"]) <= 3
            assert consumed - uploaded <= len(payload["tasks"]) + 1
            assert payload["job_id"] == plan["job_id"]  # writer shard ordering
            batch_counts.append(len(payload["tasks"]))
            uploaded += len(payload["tasks"])
        return await submit(operation, payload, **kwargs)

    def tasks():
        nonlocal consumed
        for user_id in range(40, 140):
            consumed += 1
            yield Task(
                task_type=TaskType.SCRAPE,
                site_name="OnlyFans",
                user_id=user_id,
                user_username="unicode-" + "\u03bb" * 150,
            )

    monkeypatch.setattr(writes, "submit", observe_upload)
    await manager.update_job_by_id(plan["job_id"], tasks=tasks())
    assert uploaded == consumed == 100
    assert max(batch_counts) < 3  # The actual JSON envelope is the binding budget.
    assert (
        await storage._client().zcard(
            storage.TASK_INDEX_KEY.format(job_id=plan["job_id"])
        )
        <= 3
    )


async def test_future_replacement_schedule_holds_admission(store, window_runtime):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=True
    )
    task = Task(task_type=TaskType.DOWNLOAD, site_name="OnlyFans", user_id=41)
    schedule = JobSchedule(
        scheduled_for=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    )
    await manager.update_job_by_id(
        plan["job_id"], name="Edited", tasks=[task], schedule=schedule
    )
    assert await legacy.list_tasks_for_job(storage, plan["job_id"]) == []
    await storage._client().flushall()
    await mps_durable.recover(window_runtime)
    job = await storage.fetch_job(plan["job_id"], include_tasks=False)
    assert job is None
    saved = mps_durable.job_from_plan(store.get(plan["job_id"]))
    assert saved.name == "Edited"
    assert saved.schedule == schedule
    await mps_durable.advance(window_runtime, plan["job_id"])
    assert await legacy.list_tasks_for_job(storage, plan["job_id"]) == []


async def test_api_edit_keeps_compact_central_arguments(
    store, window_runtime, monkeypatch
):
    from ultima_scraper_backend.api.routes import jobs

    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=False
    )
    monkeypatch.setattr(jobs, "JobManager", lambda redis: manager)
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    monkeypatch.setattr(
        jobs,
        "_build_task_from_payload",
        AsyncMock(
            return_value=Task(
                task_type=TaskType.DOWNLOAD, site_name="OnlyFans", user_id=41
            )
        ),
    )
    request = jobs.UpdateJobRequest(
        tasks=[
            jobs.TaskPayload(
                task_type="download", params={"site": "onlyfans", "user_id": 41}
            )
        ]
    )
    await jobs.update_job(plan["job_id"], request, backend=window_runtime)
    with store.session_factory() as session:
        args = json.loads(
            session.scalar(
                text("SELECT args_json FROM management.jobs WHERE job_id=:id"),
                {"id": plan["job_id"]},
            )
        )
    assert "tasks" not in args
    assert args["task_count"] == 1
    assert args["mps_task_manifest"]


async def test_dependency_outputs_are_included_in_window_byte_budget(
    store, window_runtime, monkeypatch
):
    from ultima_scraper_backend.job_system import mps_state

    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=False
    )
    job_id = plan["job_id"]
    parents = [
        Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=i)
        for i in (41, 42)
    ]
    children = [
        Task(
            task_type=TaskType.DOWNLOAD,
            site_name="OnlyFans",
            user_id=p.user_id,
            depends_on=[p.task_id],
        )
        for p in parents
    ]
    await manager.update_job_by_id(job_id, tasks=[*children, *parents])
    for parent in parents:
        parent = await storage.fetch_task(job_id, parent.task_id)
        assert await legacy.mark_task_started(storage, job_id, parent.task_id)
        parent.state = TaskState.COMPLETED
        parent.result = TaskResult(success=True, output={"data": "x" * 35_000})
        await legacy.persist_task_result(storage, job_id, parent)
        await legacy.mark_task_completed(storage, job_id, parent.task_id)
    assert await mps_durable.advance(window_runtime, job_id)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "60000")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", "60000")
    await mps_durable.advance(window_runtime, job_id)
    assert await legacy.list_tasks_for_job(storage, job_id) == [children[0].task_id]
    assert await storage.get_task_output(job_id, parents[0].task_id) == {
        "data": "x" * 35_000
    }
    assert await storage.get_task_output(job_id, parents[1].task_id) is None
    assert int(await storage._client().hget(mps_state.BUDGET_KEY, "bytes")) <= 60_000
    await fixtures.fixtures.complete_window(storage, job_id)
    assert await mps_durable.advance(window_runtime, job_id)
    await mps_durable.advance(window_runtime, job_id)
    assert await legacy.list_tasks_for_job(storage, job_id) == [children[1].task_id]
    assert await storage.get_task_output(job_id, parents[1].task_id) == {
        "data": "x" * 35_000
    }


async def test_metadata_sync_cannot_promote_an_unreconciled_definition(
    store, window_runtime
):
    plan, storage, manager = await fixtures.prepared_window(
        store, window_runtime, archived=False
    )
    job_id = plan["job_id"]
    task = Task(task_type=TaskType.DOWNLOAD, site_name="OnlyFans", user_id=41)
    manifest_id = f"definition-{uuid4().hex}"
    store.definitions.begin(job_id, manifest_id, name="New definition")
    store.definitions.append(manifest_id, offset=0, tasks=[task.to_dict()])
    changed = store.definitions.commit(job_id, manifest_id, total=1)
    # This is the boundary reached when retirement loses WATCH to another
    # config writer. Metadata reconciliation must not hide the pending reset.
    await mps_durable._sync_job_config(storage, changed)
    old = await storage.fetch_job(job_id, include_tasks=False)
    assert old.metadata.get("mps_task_manifest") is None
    assert old.metadata.get("mps_config_revision", 0) == 0
    await mps_durable.advance(window_runtime, job_id)
    assert await legacy.list_tasks_for_job(storage, job_id) == [task.task_id]
