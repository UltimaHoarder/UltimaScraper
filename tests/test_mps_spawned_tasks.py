"""Dynamic MPS work must commit with its parent and use normal window budgets."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

import test_mps_attempt_ownership as attempts
import test_mps_manifest as fixtures
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
from ultima_scraper_backend.job_system import JobManager, JobStorage, Task, TaskResult
from ultima_scraper_backend.job_system.models import TaskRegistry, TaskType
from ultima_scraper_backend.job_system.storage import _task_to_central_row
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


@pytest.mark.parametrize("explicit", [False, True])
async def test_spawned_download_commits_with_parent_and_uses_next_window(
    store, window_runtime, monkeypatch, explicit
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    plan = fixtures.prepare_runtime_plan(store, 1)
    job_id = plan["job_id"]
    storage = JobStorage(window_runtime.redis)
    await mps_durable.advance(window_runtime, job_id)
    if explicit:
        manager = JobManager(window_runtime.redis)
        manager.database_writes = window_runtime.writes
        await manager.update_job_by_id(
            job_id,
            tasks=[
                Task(
                    task_type=TaskType.SCRAPE,
                    site_name="OnlyFans",
                    user_id=1,
                    payload={"paid_content_feed": True},
                )
            ],
        )
    (parent_id,) = await legacy.list_tasks_for_job(storage, job_id)
    child = Task(
        task_id=uuid4().hex,
        task_type=TaskType.DOWNLOAD,
        site_name="OnlyFans",
        user_id=1,
        depends_on=[parent_id],
    )
    seen_output = []

    async def scrape(task, context):
        return TaskResult(
            success=True,
            message="parent retained",
            output={"selection": "durable media reference"},
            new_tasks=[child],
        )

    async def download(task, context):
        seen_output.append(context.previous_output)
        return TaskResult(success=True, message="child retained")

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, scrape)
    monkeypatch.setitem(TaskRegistry._handlers, TaskType.DOWNLOAD, download)
    worker = attempts.worker_for(window_runtime, storage, [])
    assert await worker._execute_ready_task(job_id, parent_id) == (True, False, None)
    # A handler may describe children, but cannot expand the active Redis window.
    assert await legacy.list_tasks_for_job(storage, job_id) == [parent_id]
    assert await storage.fetch_task(job_id, child.task_id) is None
    assert await mps_durable.advance(window_runtime, job_id)
    durable = store.get(job_id)
    assert (durable["cursor"], durable["total"], durable["status"]) == (1, 2, "ready")
    with store.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.mps_task_definitions WHERE task_id=:id"
                ),
                {"id": child.task_id},
            )
            == 1
        )
    await mps_durable.advance(window_runtime, job_id)
    assert await legacy.list_tasks_for_job(storage, job_id) == [child.task_id]
    assert await worker._execute_ready_task(job_id, child.task_id) == (
        True,
        False,
        None,
    )
    assert seen_output == [{"selection": "durable media reference"}]
    assert not await mps_durable.advance(window_runtime, job_id)
    durable = store.get(job_id)
    assert (durable["cursor"], durable["total"], durable["status"]) == (
        2,
        2,
        "complete",
    )
    with store.session_factory() as session:
        rows = session.execute(
            text(
                "SELECT task_id, status, result_json FROM management.job_tasks WHERE job_id=:id"
            ),
            {"id": job_id},
        ).all()
        assert {row.task_id for row in rows} == {parent_id, child.task_id}
        assert all(row.status == "completed" for row in rows)
        assert {json.loads(row.result_json)["message"] for row in rows} == {
            "parent retained",
            "child retained",
        }


async def prepared_parent(
    store, runtime, monkeypatch, *, explicit=False, total=1, factory=None, succeeds=True
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    plan = fixtures.prepare_runtime_plan(store, total)
    job_id = plan["job_id"]
    storage = JobStorage(runtime.redis)
    await mps_durable.advance(runtime, job_id)
    if explicit:
        manager = JobManager(runtime.redis)
        manager.database_writes = runtime.writes
        await manager.update_job_by_id(
            job_id,
            tasks=[
                Task(
                    task_type=TaskType.SCRAPE,
                    site_name="OnlyFans",
                    user_id=1,
                )
            ],
        )
    (parent_id,) = await legacy.list_tasks_for_job(storage, job_id)
    children = (
        factory(parent_id)
        if factory
        else [
            Task(
                task_type=TaskType.DOWNLOAD,
                user_id=1,
                site_name="OnlyFans",
                depends_on=[parent_id],
            )
        ]
    )

    async def parent_handler(task, context):
        return TaskResult(
            success=succeeds,
            message="parent checkpoint",
            output={"parent": parent_id},
            new_tasks=children,
            continue_job_on_failure=not succeeds,
        )

    async def child_handler(task, context):
        return TaskResult(success=True, message="child checkpoint")

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, parent_handler)
    monkeypatch.setitem(TaskRegistry._handlers, TaskType.DOWNLOAD, child_handler)
    worker = attempts.worker_for(runtime, storage, [])
    await worker._execute_ready_task(job_id, parent_id)
    parent = await storage.fetch_task(job_id, parent_id)
    return SimpleNamespace(
        job_id=job_id, storage=storage, parent=parent, children=children, worker=worker
    )


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("fault", ["lost_commit_reply", "empty_redis"])
async def test_committed_children_survive_lost_reply_and_empty_redis(
    store, window_runtime, monkeypatch, explicit, fault
):
    case = await prepared_parent(store, window_runtime, monkeypatch, explicit=explicit)
    if fault == "lost_commit_reply":
        writes_type = type(window_runtime.writes)
        submit = writes_type.submit
        armed = True

        async def lose_reply(self, operation, payload, **kwargs):
            nonlocal armed
            result = await submit(self, operation, payload, **kwargs)
            if operation == DatabaseWriteOperation.ARCHIVE_MPS_WINDOW and armed:
                armed = False
                raise RuntimeError("lost commit reply")
            return result

        monkeypatch.setattr(writes_type, "submit", lose_reply)
    else:
        purge = mps_durable._purge_archived_window

        async def stop_before_purge(*args, **kwargs):
            raise RuntimeError("stopped before Redis purge")

        monkeypatch.setattr(mps_durable, "_purge_archived_window", stop_before_purge)
    with pytest.raises(RuntimeError):
        await mps_durable.advance(window_runtime, case.job_id)
    committed = store.get(case.job_id)
    assert (committed["cursor"], committed["total"], committed["status"]) == (
        1,
        2,
        "ready",
    )
    if fault == "empty_redis":
        monkeypatch.setattr(mps_durable, "_purge_archived_window", purge)
        await case.storage._client().flushall()  # This test owns the fixture server.
        await mps_durable.recover(window_runtime)
    await mps_durable.advance(window_runtime, case.job_id)
    assert await legacy.list_tasks_for_job(case.storage, case.job_id) == [
        case.children[0].task_id
    ]
    assert await case.storage.get_task_output(case.job_id, case.parent.task_id) == {
        "parent": case.parent.task_id
    }
    replay = store.archive_window(
        case.job_id,
        start=0,
        end=1,
        rows=[_task_to_central_row(case.parent, case.job_id)],
        manifest_id=committed["selection"].get("task_manifest_id"),
    )
    assert replay["total"] == 2
    with store.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.mps_task_definitions WHERE task_id=:id"
                ),
                {"id": case.children[0].task_id},
            )
            == 1
        )
    await case.worker._execute_ready_task(case.job_id, case.children[0].task_id)
    assert not await mps_durable.advance(window_runtime, case.job_id)
    assert store.get(case.job_id)["status"] == "complete"


@pytest.mark.parametrize(
    "invalid", ["missing", "cycle", "duplicate", "parent_collision"]
)
async def test_invalid_children_roll_back_parent_checkpoint(
    store, window_runtime, monkeypatch, invalid
):
    def factory(parent_id):
        first = Task(task_type=TaskType.DOWNLOAD, user_id=1, site_name="OnlyFans")
        if invalid == "missing":
            first.depends_on = ["missing-task"]
            return [first]
        if invalid == "parent_collision":
            first.task_id = parent_id
            return [first]
        if invalid == "duplicate":
            return [first, first]
        second = Task(
            task_type=TaskType.DOWNLOAD,
            user_id=2,
            site_name="OnlyFans",
            depends_on=[first.task_id],
        )
        first.depends_on = [second.task_id]
        return [first, second]

    case = await prepared_parent(store, window_runtime, monkeypatch, factory=factory)
    before = store.get(case.job_id)
    with pytest.raises(ValueError):
        await mps_durable.advance(window_runtime, case.job_id)
    assert store.get(case.job_id) == before
    assert (
        await case.storage.fetch_task(case.job_id, case.parent.task_id)
    ).result.message == "parent checkpoint"
    with store.session_factory() as session:
        assert (
            session.scalar(text("SELECT count(*) FROM management.mps_task_definitions"))
            == 0
        )
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 0


@pytest.mark.parametrize("explicit", [False, True])
async def test_failed_parent_does_not_admit_children(
    store, window_runtime, monkeypatch, explicit
):
    case = await prepared_parent(
        store, window_runtime, monkeypatch, explicit=explicit, succeeds=False
    )
    assert not await mps_durable.advance(window_runtime, case.job_id)
    plan = store.get(case.job_id)
    assert (plan["total"], plan["failed"], plan["status"]) == (1, 1, "complete")
    with store.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.mps_task_definitions WHERE task_id=:id"
                ),
                {"id": case.children[0].task_id},
            )
            == 0
        )


async def test_million_profile_prefix_stays_compressed_and_child_history_is_paged(
    store, window_runtime, monkeypatch
):
    from ultima_scraper_backend.api.routes import jobs

    case = await prepared_parent(store, window_runtime, monkeypatch, total=1_000_000)
    assert await mps_durable.advance(window_runtime, case.job_id)
    plan = store.get(case.job_id)
    assert (plan["cursor"], plan["total"]) == (1, 1_000_001)
    assert plan["selection"]["candidate_total"] == 1_000_000
    with store.session_factory() as session:
        assert (
            session.scalar(text("SELECT count(*) FROM management.mps_candidate_ranges"))
            == 1
        )
        assert (
            session.scalar(text("SELECT count(*) FROM management.mps_task_definitions"))
            == 1
        )
    page = await jobs.get_job_tasks(
        case.job_id, offset=0, limit=2, backend=window_runtime
    )
    assert {task.task_id for task in page.tasks} == {
        case.parent.task_id,
        case.children[0].task_id,
    }
    assert page.scanned_count == 2
    filtered = await jobs.get_job_tasks(
        case.job_id, offset=0, limit=1, task_type="download", backend=window_runtime
    )
    assert [task.task_id for task in filtered.tasks] == [case.children[0].task_id]
    await mps_durable.advance(window_runtime, case.job_id)
    live = [task async for task in case.storage.fetch_tasks_stream(case.job_id)]
    assert len(live) == 1 and live[0].user_id == 2
    assert await case.storage.fetch_task(case.job_id, case.children[0].task_id) is None


@pytest.mark.parametrize("explicit", [False, True])
async def test_descendant_chain_uses_one_window_as_history_grows(
    store, window_runtime, monkeypatch, explicit
):
    case = await prepared_parent(store, window_runtime, monkeypatch, explicit=explicit)
    depth = 32
    handled = []

    async def descend(task, context):
        handled.append(task.task_id)
        children = (
            []
            if len(handled) == depth
            else [
                Task(
                    task_type=TaskType.DOWNLOAD,
                    user_id=1,
                    site_name="OnlyFans",
                    depends_on=[task.task_id],
                )
            ]
        )
        return TaskResult(
            success=True,
            message="descendant",
            output={"depth": len(handled)},
            new_tasks=children,
        )

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.DOWNLOAD, descend)
    peak_keys = 0
    while store.get(case.job_id)["status"] == "ready":
        more = await mps_durable.advance(window_runtime, case.job_id)
        if more:
            await mps_durable.advance(window_runtime, case.job_id)
        tasks = [task async for task in case.storage.fetch_tasks_stream(case.job_id)]
        assert len(tasks) <= 1
        if tasks:
            await case.worker._execute_ready_task(case.job_id, tasks[0].task_id)
        peak_keys = max(peak_keys, await case.storage._client().dbsize())
    plan = store.get(case.job_id)
    assert (plan["total"], plan["cursor"], plan["completed"]) == (
        depth + 1,
        depth + 1,
        depth + 1,
    )
    assert len(set(handled)) == depth
    assert plan["job_config"]["metadata"]["mps_task_type_counts"] == {
        "scrape": 1,
        "download": depth,
    }
    assert (
        peak_keys < 50
    )  # Task/window keys stay bounded despite 33 retained SQL results.


async def test_replacement_retires_discovered_range_children(
    store, window_runtime, monkeypatch
):
    case = await prepared_parent(store, window_runtime, monkeypatch)
    assert await mps_durable.advance(window_runtime, case.job_id)
    manager = JobManager(window_runtime.redis)
    manager.database_writes = window_runtime.writes
    await case.storage._client().hset(
        case.storage.JOB_STATE_KEY.format(job_id=case.job_id), "status", "paused"
    )
    replacement = Task(task_type=TaskType.SCRAPE, user_id=2, site_name="OnlyFans")
    await manager.update_job_by_id(case.job_id, tasks=[replacement])
    assert await legacy.list_tasks_for_job(case.storage, case.job_id) == [replacement.task_id]
    with store.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.mps_task_definitions WHERE manifest_id=:id"
                ),
                {"id": case.job_id},
            )
            == 0
        )
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id=:id"),
                {"id": case.job_id},
            )
            == 0
        )
    with pytest.raises(ValueError, match="definition changed"):
        store.archive_window(
            case.job_id,
            start=0,
            end=1,
            rows=[_task_to_central_row(case.parent, case.job_id)],
        )


@pytest.mark.parametrize("explicit", [False, True])
async def test_child_fanout_respects_window_count_budget(
    store, window_runtime, monkeypatch, explicit
):
    def factory(parent_id):
        return [
            Task(
                task_type=TaskType.DOWNLOAD,
                user_id=user_id,
                site_name="OnlyFans",
                depends_on=[parent_id],
            )
            for user_id in range(1, 10)
        ]

    case = await prepared_parent(
        store, window_runtime, monkeypatch, explicit=explicit, factory=factory
    )
    assert await legacy.list_tasks_for_job(case.storage, case.job_id) == [case.parent.task_id]
    assert await mps_durable.advance(window_runtime, case.job_id)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    completed = []
    while store.get(case.job_id)["status"] == "ready":
        more = await mps_durable.advance(window_runtime, case.job_id)
        if more:
            await mps_durable.advance(window_runtime, case.job_id)
        tasks = [task async for task in case.storage.fetch_tasks_stream(case.job_id)]
        assert len(tasks) <= 2
        for task in tasks:
            await case.worker._execute_ready_task(case.job_id, task.task_id)
            completed.append(task.task_id)
    assert set(completed) == {task.task_id for task in case.children}
    assert store.get(case.job_id)["total"] == 10


async def test_oversized_child_stays_durable_until_explicit_budget_is_raised(
    store, window_runtime, monkeypatch
):
    def factory(parent_id):
        return [
            Task(
                task_type=TaskType.DOWNLOAD,
                user_id=1,
                site_name="OnlyFans",
                depends_on=[parent_id],
                payload={"data": "x" * 8000},
            )
        ]

    case = await prepared_parent(store, window_runtime, monkeypatch, factory=factory)
    assert await mps_durable.advance(window_runtime, case.job_id)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "2000")
    with pytest.raises(ValueError, match="byte budget"):
        await mps_durable.advance(window_runtime, case.job_id)
    assert await legacy.list_tasks_for_job(case.storage, case.job_id) == []
    assert (store.get(case.job_id)["cursor"], store.get(case.job_id)["total"]) == (1, 2)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", "20000")
    await mps_durable.advance(window_runtime, case.job_id)
    assert await legacy.list_tasks_for_job(case.storage, case.job_id) == [
        case.children[0].task_id
    ]


async def test_auth_override_applies_to_download_without_scrape_only_payload_fields(
    store, window_runtime, monkeypatch
):
    from ultima_scraper_backend.job_system.payloads import DownloadTaskPayload

    case = await prepared_parent(store, window_runtime, monkeypatch)
    assert await mps_durable.advance(window_runtime, case.job_id)
    with store.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.mps_plans SET selection_json=(selection_json::jsonb || CAST(:changes AS jsonb))::text WHERE job_id=:id"
            ),
            {"id": case.job_id, "changes": json.dumps({"retry_auth_id": 99})},
        )
        session.commit()
    await mps_durable.advance(window_runtime, case.job_id)
    child = await case.storage.fetch_task(case.job_id, case.children[0].task_id)
    assert child.auth_id == 99
    assert isinstance(child.payload, DownloadTaskPayload)
    assert not hasattr(child.payload, "use_guest_auth")
