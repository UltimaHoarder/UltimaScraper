"""Retry graphs retain types, dependencies and bounded, retry-owned execution."""

from __future__ import annotations

import json
import tracemalloc
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text

import test_mps_attempt_ownership as attempts
import test_mps_manifest as fixtures
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import durable as mps_durable
from ultima_scraper_backend.api.routes import mps_durable as mps_submission
from ultima_scraper_backend.database.mps_retry import retry_task_id
from ultima_scraper_backend.job_system import (
    Job,
    JobStorage,
    Task,
    TaskResult,
    TaskState,
)
from ultima_scraper_backend.job_system.models import TaskRegistry, TaskType
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


def explicit_plan(store, tasks):
    plan = fixtures.prepare_runtime_plan(store, 1)
    manifest = uuid4().hex
    store.definitions.begin(plan["job_id"], manifest)
    store.definitions.append(
        manifest, offset=0, tasks=[task.to_dict() for task in tasks]
    )
    return store.definitions.commit(plan["job_id"], manifest, total=len(tasks))


def clone(store, source, *, auth_id=None, commit=True, config=None, **kwargs):
    config = (
        config
        or Job.create(
            name="Retry graph",
            tasks=[],
            created_by="tests",
            metadata={"mps_manifest": True, "retry_of": source["job_id"]},
        ).to_dict()
    )
    with store.session_factory() as session:
        result = store.clone_for_retry(
            source_job_id=source["job_id"],
            job_id=config["job_id"],
            job_config=config,
            site=source["site"],
            live_failed_user_ids=[],
            auth_id=auth_id,
            db_session=session,
            **kwargs,
        )
        if commit:
            session.commit()
    return result


async def execute_job(store, runtime, job_id):
    storage = JobStorage(runtime.redis)
    worker = attempts.worker_for(runtime, storage, [])
    maximum = 0
    for _ in range(50):
        await mps_durable.advance(runtime, job_id)
        tasks = [task async for task in storage.fetch_tasks_stream(job_id)]
        maximum = max(maximum, len(tasks))
        for task in tasks:
            if task.state == TaskState.PENDING:
                await worker._execute_ready_task(job_id, task.task_id)
        if store.get(job_id)["status"] == "complete":
            return maximum
    pytest.fail("Fixture job did not reach its durable terminal checkpoint")


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("failed_only", [False, True])
async def test_generated_retry_refreshes_one_owned_child_and_uses_fresh_output(
    store, window_runtime, monkeypatch, explicit, failed_only
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    root = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1, auth_id=17)
    source = (
        explicit_plan(store, [root])
        if explicit
        else fixtures.prepare_runtime_plan(store, 1)
    )
    seen = []

    async def parent(task, context):
        child = Task(
            task_type=TaskType.DOWNLOAD,
            site_name="OnlyFans",
            user_id=task.auth_id or 17,
            auth_id=task.auth_id or 17,
            depends_on=[task.task_id],
            payload={"paid_content_feed": True},
        )
        return TaskResult(
            success=True,
            output={"owner": task.job_id, "producer": task.task_id},
            new_tasks=[child],
        )

    async def download(task, context):
        seen.append((task.job_id, task.task_id, task.auth_id, context.previous_output))
        return TaskResult(
            success=not (failed_only and task.job_id == source["job_id"]),
            continue_job_on_failure=True,
        )

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, parent)
    monkeypatch.setitem(TaskRegistry._handlers, TaskType.DOWNLOAD, download)
    assert await execute_job(store, window_runtime, source["job_id"]) == 1
    retry = clone(store, store.get(source["job_id"]), auth_id=99)
    assert retry["total"] == 2
    nodes = store.definitions.page(
        retry["selection"]["task_manifest_id"], offset=0, limit=5
    )
    assert len(nodes) == 2
    assert {node["task"]["job_id"] for node in nodes} == {retry["job_id"]}
    assert {node["task"]["task_type"] for node in nodes} == {"scrape", "download"}
    assert all(node["task"]["auth_id"] == 99 for node in nodes)
    # Redis may disappear completely after the durable clone commits.
    await window_runtime.redis.client.flushdb()
    assert await execute_job(store, window_runtime, retry["job_id"]) == 1
    assert store.get(retry["job_id"])["total"] == 2
    assert len(seen) == 2 and seen[-1][2] == 99
    assert seen[-1][3]["owner"] == retry["job_id"]
    with store.session_factory() as session:
        rows = session.execute(
            text(
                "SELECT task_id,task_type,result_json FROM management.job_tasks WHERE job_id=:job"
            ),
            {"job": retry["job_id"]},
        ).all()
        assert {row.task_id for row in rows} == {node["task_id"] for node in nodes}
        producer = next(row for row in rows if row.task_type == "scrape")
        assert [
            task["task_id"] for task in json.loads(producer.result_json)["new_tasks"]
        ] == [seen[-1][1]]
    # A chained retry must use its own graph again, including refreshed slots.
    chained = clone(store, store.get(retry["job_id"]))
    assert await execute_job(store, window_runtime, chained["job_id"]) == 1
    assert store.get(chained["job_id"])["total"] == 2


async def test_failed_download_retry_reexecutes_prerequisite_but_excludes_successful_sibling(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    source = explicit_plan(
        store, [Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1)]
    )
    downloaded = []

    async def parent(task, context):
        return TaskResult(
            success=True,
            new_tasks=[
                Task(
                    task_type=TaskType.DOWNLOAD,
                    site_name="OnlyFans",
                    user_id=user,
                    depends_on=[task.task_id],
                )
                for user in (1, 2)
            ],
        )

    async def download(task, context):
        downloaded.append((task.job_id, task.user_id))
        return TaskResult(
            success=not (task.job_id == source["job_id"] and task.user_id == 2),
            continue_job_on_failure=True,
        )

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, parent)
    monkeypatch.setitem(TaskRegistry._handlers, TaskType.DOWNLOAD, download)
    await execute_job(store, window_runtime, source["job_id"])
    retry = clone(store, store.get(source["job_id"]))
    assert retry["total"] == 2
    await execute_job(store, window_runtime, retry["job_id"])
    assert [user for job, user in downloaded if job == retry["job_id"]] == [2]
    assert store.get(retry["job_id"])["total"] == 2


async def test_static_mixed_retry_preserves_tasks_and_auth_instead_of_rebuilding_profile_scrapes(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    parent = Task(
        task_type=TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=None,
        user_username="unresolved",
        auth_id=17,
        payload={"download_media": False},
    )
    child = Task(
        task_type=TaskType.DOWNLOAD,
        site_name="OnlyFans",
        user_id=3,
        auth_id=17,
        depends_on=[parent.task_id],
        max_attempts=7,
    )
    sibling = Task(task_type=TaskType.API_COMMAND, site_name="OnlyFans", user_id=4)
    source = explicit_plan(store, [child, sibling, parent])

    async def success(task, context):
        return TaskResult(success=True, output={"owner": task.job_id})

    async def download(task, context):
        return TaskResult(
            success=task.job_id != source["job_id"], continue_job_on_failure=True
        )

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, success)
    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, success)
    monkeypatch.setitem(TaskRegistry._handlers, TaskType.DOWNLOAD, download)
    await execute_job(store, window_runtime, source["job_id"])
    retry = clone(store, store.get(source["job_id"]))
    nodes = store.definitions.page(retry["job_id"], offset=0, limit=10)
    assert len(nodes) == 2
    download_node = next(
        node["task"] for node in nodes if node["task"]["task_type"] == "download"
    )
    assert download_node["depends_on"] == [
        retry_task_id(retry["job_id"], parent.task_id)
    ]
    assert download_node["auth_id"] == 17 and download_node["max_attempts"] == 7
    await execute_job(store, window_runtime, retry["job_id"])
    assert store.get(retry["job_id"])["failed"] == 0


async def test_retry_route_accepts_unresolved_failed_task_identity(
    store, window_runtime, monkeypatch
):
    source = explicit_plan(
        store,
        [
            Task(
                task_type=TaskType.SCRAPE,
                site_name="OnlyFans",
                user_id=None,
                user_username="unresolved",
            )
        ],
    )
    await mps_durable.advance(window_runtime, source["job_id"])
    storage = JobStorage(window_runtime.redis)
    (task_id,) = await legacy.list_tasks_for_job(storage, source["job_id"])
    task = await storage.fetch_task(source["job_id"], task_id)
    task.state = TaskState.FAILED
    await storage.persist_task(job_id=source["job_id"], task=task)
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    monkeypatch.setattr(mps_durable, "_retire_retry_source", AsyncMock())
    response = await mps_submission.retry_job(
        source, request=SimpleNamespace(auth_id=None), backend=window_runtime
    )
    assert response.task_count == 1
    (node,) = store.definitions.page(response.job_id, offset=0, limit=2)
    assert node["task"]["user_username"] == "unresolved"


def test_graph_retry_is_atomic_replayable_and_rejects_replaced_generation(store):
    source = explicit_plan(
        store, [Task(task_type=TaskType.DOWNLOAD, site_name="OnlyFans", user_id=1)]
    )
    config = Job.create(
        name="Retry",
        tasks=[],
        created_by="tests",
        metadata={"mps_manifest": True, "retry_of": source["job_id"]},
    ).to_dict()
    retry = clone(store, source, config=config, commit=False)
    assert store.get(retry["job_id"]) is None
    assert store.get(source["job_id"])["status"] == "ready"
    with pytest.raises(ValueError, match="definition changed"):
        clone(store, source, expected_manifest_id="stale")
    first = clone(store, source, config=config)
    assert clone(store, source, config=config, auth_id=999) == first


@pytest.mark.parametrize("count", [2000, 20000])
def test_graph_retry_copy_uses_bounded_pages(
    store, monkeypatch, count, record_property
):
    source = explicit_plan(
        store, [Task(task_type=TaskType.DOWNLOAD, site_name="OnlyFans", user_id=1)]
    )
    with store.session_factory() as session:
        session.execute(
            text("""
            INSERT INTO management.mps_task_definitions(manifest_id,ordinal,task_id,task_json,dependency_ids)
            SELECT :manifest, i, 'scale-' || i,
              jsonb_build_object('task_id','scale-' || i,'task_type','download','site_name','OnlyFans','user_id',i)::text,
              ARRAY[]::varchar[] FROM generate_series(1,:count-1) i
        """),
            {"manifest": source["selection"]["task_manifest_id"], "count": count},
        )
        session.execute(
            text("UPDATE management.mps_plans SET total=:count WHERE job_id=:job"),
            {"job": source["job_id"], "count": count},
        )
        session.commit()
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "25")
    tracemalloc.start()
    try:
        retry = clone(store, source)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert retry["total"] == count
    assert peak < 4 * 1024 * 1024
    record_property("tasks", count)
    record_property("peak_traced_bytes", peak)
    assert len(store.definitions.page(retry["job_id"], offset=count - 1, limit=10)) == 1


@pytest.mark.parametrize("change", ["absent", "identity", "dependency"])
async def test_changed_retry_emission_cannot_execute_stale_child(
    store, window_runtime, monkeypatch, change
):
    from ultima_scraper_backend.job_system.storage import _task_to_central_row

    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    source = explicit_plan(
        store, [Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1)]
    )
    changed = False
    seen_downloads = []

    async def parent(task, context):
        if changed and change == "absent":
            return TaskResult(success=True)
        child = Task(
            task_type=TaskType.DOWNLOAD,
            site_name="OnlyFans",
            user_id=2 if changed and change == "identity" else 1,
            depends_on=["missing"]
            if changed and change == "dependency"
            else [task.task_id],
        )
        return TaskResult(success=True, new_tasks=[child])

    async def download(task, context):
        seen_downloads.append(task.job_id)
        return TaskResult(success=True)

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, parent)
    monkeypatch.setitem(TaskRegistry._handlers, TaskType.DOWNLOAD, download)
    await execute_job(store, window_runtime, source["job_id"])
    retry = clone(store, store.get(source["job_id"]))
    changed = True
    if change == "absent":
        await execute_job(store, window_runtime, retry["job_id"])
        assert store.get(retry["job_id"])["failed"] == 1
        with store.session_factory() as session:
            message = session.scalar(
                text(
                    "SELECT result_json FROM management.job_tasks WHERE job_id=:job AND task_type='download'"
                ),
                {"job": retry["job_id"]},
            )
        assert "did not emit" in message
    else:
        storage = JobStorage(window_runtime.redis)
        await mps_durable.advance(window_runtime, retry["job_id"])
        (identifier,) = await legacy.list_tasks_for_job(storage, retry["job_id"])
        worker = attempts.worker_for(window_runtime, storage, [])
        await worker._execute_ready_task(retry["job_id"], identifier)
        task = await storage.fetch_task(retry["job_id"], identifier)
        with pytest.raises(ValueError, match="identity|dependencies"):
            store.archive_window(
                retry["job_id"],
                start=0,
                end=1,
                manifest_id=retry["job_id"],
                rows=[_task_to_central_row(task, retry["job_id"])],
            )
        assert store.get(retry["job_id"])["cursor"] == 0
        with store.session_factory() as session:
            assert (
                session.scalar(
                    text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"),
                    {"job": retry["job_id"]},
                )
                == 0
            )
    assert seen_downloads == [source["job_id"]]


async def test_new_child_in_retry_retains_producer_for_subsequent_retry(
    store, window_runtime, monkeypatch
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    source = explicit_plan(
        store, [Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1)]
    )
    emission = False

    async def parent(task, context):
        return TaskResult(
            success=True,
            new_tasks=[
                Task(
                    task_type=TaskType.DOWNLOAD,
                    site_name="OnlyFans",
                    user_id=1,
                    depends_on=[task.task_id],
                )
            ]
            if emission
            else [],
        )

    async def download(task, context):
        return TaskResult(success=True)

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, parent)
    monkeypatch.setitem(TaskRegistry._handlers, TaskType.DOWNLOAD, download)
    await execute_job(store, window_runtime, source["job_id"])
    retry = clone(store, store.get(source["job_id"]))
    emission = True
    await execute_job(store, window_runtime, retry["job_id"])
    assert store.get(retry["job_id"])["total"] == 2
    chained = clone(store, store.get(retry["job_id"]))
    await execute_job(store, window_runtime, chained["job_id"])
    assert store.get(chained["job_id"])["total"] == 2


def test_unexecuted_chained_retry_preserves_nested_task_ownership(store):
    parent = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=1)
    nested = Task(
        task_type=TaskType.DOWNLOAD, site_name="OnlyFans", user_id=1, auth_id=12
    )
    legacy.add_subtask(parent, nested)
    source = explicit_plan(store, [parent])
    retry = clone(store, source, auth_id=17)
    chained = clone(store, retry)
    (node,) = store.definitions.page(chained["job_id"], offset=0, limit=1)
    nested = node["task"]["subtasks"][0]
    assert nested["job_id"] == nested["mps_task_manifest"] == chained["job_id"]
    assert nested["parent_task_id"] == node["task_id"]
    assert nested["auth_id"] == 17


@pytest.mark.parametrize(
    "live_failure", ["none", "profile", "child", "foreign", "unresolved_child"]
)
async def test_hybrid_retry_keeps_unprocessed_profile_parameters_and_live_task_identity(
    store, window_runtime, monkeypatch, live_failure
):
    from test_mps_spawned_tasks import prepared_parent
    from ultima_scraper_backend.job_system.mps_tasks import _build_mps_task_batch

    case = await prepared_parent(
        store,
        window_runtime,
        monkeypatch,
        total=12,
        factory=lambda parent: [
            Task(
                task_type=TaskType.DOWNLOAD,
                user_id="unresolved" if live_failure == "unresolved_child" else 5,
                site_name="OnlyFans",
                depends_on=[parent],
            )
        ],
    )
    await mps_durable.advance(window_runtime, case.job_id)
    proxies = [f"http://route-{index}.invalid" for index in range(6)]
    with store.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.mps_plans SET proxy_pool_json=:pool WHERE job_id=:job"
            ),
            {"pool": json.dumps(proxies), "job": case.job_id},
        )
        session.commit()
    expected = _build_mps_task_batch(
        job_id=case.job_id,
        site_display="OnlyFans",
        target_user_ids=[5],
        proxy_pool=proxies,
        candidate_offset=4,
    )[0]
    live = []
    if live_failure != "none":
        live = [
            {
                "task_id": {
                    "profile": expected.task_id,
                    "child": case.children[0].task_id,
                    "foreign": "foreign-task",
                    "unresolved_child": case.children[0].task_id,
                }[live_failure],
                "user_id": "unresolved" if live_failure == "unresolved_child" else 5,
            }
        ]
    if live_failure == "foreign":
        with pytest.raises(ValueError, match="identity"):
            clone(store, store.get(case.job_id), live_failed_tasks=live)
        assert store.get(case.job_id)["status"] == "ready"
        return
    retry = clone(store, store.get(case.job_id), live_failed_tasks=live)
    nodes = store.definitions.page(retry["job_id"], offset=0, limit=20)
    assert (
        len(nodes)
        == {"none": 13, "profile": 1, "child": 2, "unresolved_child": 2}[live_failure]
    )
    if live_failure not in {"child", "unresolved_child"}:
        profile = next(
            node["task"]
            for node in nodes
            if node["task"]["user_id"] == 5 and node["task"]["task_type"] == "scrape"
        )
        assert profile["payload"] == expected.to_dict()["payload"]
    else:
        child = next(
            node["task"] for node in nodes if node["task"]["task_type"] == "download"
        )
        assert child["depends_on"] == [
            retry_task_id(retry["job_id"], case.parent.task_id)
        ]
