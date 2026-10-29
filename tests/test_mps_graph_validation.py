"""Reject cyclic SQL task definitions before replacing a live MPS job."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DataError

import test_mps_job_edits as runtime_fixtures
import test_mps_replacement_definitions as fixtures
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation as Op
from ultima_scraper_backend.job_system import Task, TaskType
from ultima_scraper_backend.job_system.mps_attempt import lock_key
from ultima_scraper_db_archive.global_db import DatabaseWriteReceiptModel
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


async def upload_graph(runtime, job_id, dependencies, *, batch_size=2):
    manifest = "mps-edit-" + uuid4().hex
    await runtime.writes.submit(
        Op.BEGIN_MPS_REPLACEMENT,
        {
            "job_id": job_id,
            "manifest_id": manifest,
        },
    )
    identities = [f"{manifest}-task-{i}" for i in range(len(dependencies))]
    for offset in range(0, len(dependencies), batch_size):
        tasks = [
            Task(
                task_id=identities[i],
                task_type=TaskType.SCRAPE,
                site_name="OnlyFans",
                user_id=i + 1,
                depends_on=[identities[dependency] for dependency in dependencies[i]],
            )
            for i in range(offset, min(len(dependencies), offset + batch_size))
        ]
        await runtime.writes.submit(
            Op.APPEND_MPS_REPLACEMENT,
            {
                "manifest_id": manifest,
                "offset": offset,
                "tasks": [task.to_dict() for task in tasks],
            },
        )
    return manifest, identities


@pytest.mark.parametrize(
    "dependencies",
    [
        [[0]],
        [[1], [0]],
        [[1], [2], [0]],
        [[], [0], [1, 3], [2]],
        [[], [0], [3], [2], [1]],
        [[4], [0], [], [1], [3]],
    ],
    ids=[
        "self",
        "pair",
        "triangle",
        "after-ready-prefix",
        "disconnected",
        "cross-upload-batches",
    ],
)
async def test_cycle_rejection_preserves_selection_history_and_live_window(
    store, window_runtime, dependencies
):
    plan, storage, _manager = await runtime_fixtures.prepared_window(
        store, window_runtime, archived=True
    )
    job_id = plan["job_id"]
    before = store.get(job_id)
    before_ids = await legacy.list_tasks_for_job(storage, job_id)
    before_stats = await storage.get_job_task_stats(job_id)
    manifest, _ = await upload_graph(window_runtime, job_id, dependencies)
    command_id = uuid4().hex
    with pytest.raises(ValueError, match="cycle"):
        await fixtures.commit(
            window_runtime, job_id, manifest, len(dependencies), command_id=command_id
        )
    assert store.get(job_id) == before
    assert store.get(manifest)["status"] == "staging"
    assert await legacy.list_tasks_for_job(storage, job_id) == before_ids
    assert await storage.get_job_task_stats(job_id) == before_stats
    with store.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"),
                {"job": job_id},
            )
            == 3
        )
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.mps_candidate_ranges WHERE job_id=:job"
                ),
                {"job": job_id},
            )
            == 1
        )


@pytest.mark.parametrize(
    "dependencies",
    [
        [[]],
        [[], [], [], []],
        [[], [0], [1], [2], [3]],
        [[1], [2], [3], [4], []],
        [[], [0], [0], [1, 2]],
        [[], [0, 0], [0, 1, 1]],
        [[], [0], [0], [0], [1, 2, 3]],
        [[], []]
        + [[i - 2, i - 1] if i % 2 == 0 else [i - 3, i - 2] for i in range(2, 42)],
    ],
    ids=[
        "one",
        "independent",
        "chain",
        "reverse-chain",
        "diamond",
        "duplicate-edges",
        "fan-out-in",
        "many-overlapping-paths",
    ],
)
async def test_acyclic_definitions_keep_dependencies_and_admit_ready_nodes(
    store, window_runtime, monkeypatch, dependencies
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "2")
    job_id = fixtures.fixtures.prepare_runtime_plan(store, 1_000_000)["job_id"]
    manifest, identities = await upload_graph(window_runtime, job_id, dependencies)
    replaced = await fixtures.commit(
        window_runtime, job_id, manifest, len(dependencies)
    )
    assert replaced["selection"] == {"task_manifest_id": manifest}
    assert replaced["total"] == len(dependencies)
    ready = store.definitions.ready_page(manifest, limit=len(dependencies))
    assert [row["task_id"] for row in ready] == [
        identities[i] for i, deps in enumerate(dependencies) if not deps
    ]
    for offset in range(0, len(dependencies), 2):
        page = store.definitions.page(manifest, offset=offset, limit=2)
        for row in page:
            assert row["task"]["depends_on"] == [
                identities[i] for i in dependencies[row["ordinal"]]
            ]


async def test_multiple_definitions_can_validate_in_one_writer_transaction(
    store, window_runtime
):
    definitions = []
    for _ in range(2):
        job_id = fixtures.fixtures.prepare_runtime_plan(store, 10)["job_id"]
        manifest, _ = await upload_graph(window_runtime, job_id, [[], [0], [1]])
        definitions.append((job_id, manifest))
    with store.session_factory() as session:
        for job_id, manifest in definitions:
            store.definitions.commit(job_id, manifest, total=3, db_session=session)
        session.commit()
    for job_id, manifest in definitions:
        assert store.get(job_id)["selection"] == {"task_manifest_id": manifest}


async def test_rejected_manager_edit_leaves_original_tasks_dispatchable(
    store, window_runtime
):
    plan, storage, manager = await runtime_fixtures.prepared_window(
        store, window_runtime, archived=False
    )
    job_id = plan["job_id"]
    original = await legacy.list_tasks_for_job(storage, job_id)
    first = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=11)
    second = Task(task_type=TaskType.SCRAPE, site_name="OnlyFans", user_id=12)
    first.depends_on = [second.task_id]
    second.depends_on = [first.task_id]
    with pytest.raises(ValueError, match="cycle"):
        await manager.update_job_by_id(job_id, tasks=[first, second])
    assert store.get(job_id)["selection"] == plan["selection"]
    assert not await storage._client().exists(lock_key(job_id))
    assert await legacy.list_tasks_for_job(storage, job_id) == original
    assert await legacy.mark_task_started(storage, job_id, original[0])


async def test_sql_failure_during_validation_rolls_back_and_replays_the_upload(
    store, window_runtime, postgres_engine
):
    plan = fixtures.fixtures.prepare_runtime_plan(store, 10)
    manifest, _ = await upload_graph(window_runtime, plan["job_id"], [[], [0], [1]])
    command_id = uuid4().hex

    def interrupt_validation(conn, _cursor, statement, _params, _context, _many):
        if statement.strip().startswith("DO $validation$"):
            # Abort a real PostgreSQL transaction after creating the temporary
            # graph, before the active definition or receipt can be published.
            conn.execute(text("SELECT 1/0"))

    event.listen(postgres_engine, "before_cursor_execute", interrupt_validation)
    try:
        with pytest.raises(DataError):
            await fixtures.commit(
                window_runtime, plan["job_id"], manifest, 3, command_id=command_id
            )
    finally:
        event.remove(postgres_engine, "before_cursor_execute", interrupt_validation)
    assert store.get(plan["job_id"]) == plan
    assert store.get(manifest)["status"] == "staging"
    with store.session_factory() as session:
        assert session.get(DatabaseWriteReceiptModel, command_id) is None
    result = await fixtures.commit(
        window_runtime, plan["job_id"], manifest, 3, command_id=command_id
    )
    assert result["selection"] == {"task_manifest_id": manifest}
