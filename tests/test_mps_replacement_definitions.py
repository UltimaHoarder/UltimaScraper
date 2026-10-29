"""Native SQL/writer contracts needed for durable explicit MPS replacements."""

from __future__ import annotations

import gc
import json
import time
import tracemalloc
from uuid import uuid4

import pytest
from sqlalchemy import text

import test_mps_manifest as fixtures
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation as Op
from ultima_scraper_backend.job_system import Task, TaskType

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


def task(user_id=41, *, kind=TaskType.SCRAPE, depends_on=()):
    return Task(
        user_id=user_id, task_type=kind, site_name="OnlyFans", content_type="Posts",
        auth_id=13, user_username=f"u{user_id}", depends_on=list(depends_on),
        ip_lock_key="fixture-profile-lock", payload={"use_guest_auth": False},
    )


async def upload(runtime, job_id, tasks, *, name=None):
    manifest_id = "mps-edit-" + uuid4().hex
    await runtime.writes.submit(Op.BEGIN_MPS_REPLACEMENT, {
        "job_id": job_id, "manifest_id": manifest_id, "name": name,
    })
    await runtime.writes.submit(Op.APPEND_MPS_REPLACEMENT, {
        "manifest_id": manifest_id, "offset": 0, "tasks": [t.to_dict() for t in tasks],
    })
    return manifest_id


async def commit(runtime, job_id, manifest_id, total, **kwargs):
    return await runtime.writes.submit(Op.COMMIT_MPS_REPLACEMENT, {
        "job_id": job_id, "manifest_id": manifest_id, "total": total,
    }, **kwargs)


def archive_row(job_id, definition, status="completed"):
    from ultima_scraper_backend.job_system.storage import _task_to_central_row

    row = _task_to_central_row(definition, job_id)
    row["status"] = status
    return row


async def test_partial_upload_keeps_the_original_selection_and_resumes_from_sql(
    store, window_runtime,
):
    plan = fixtures.prepare_runtime_plan(store, 1_000_000)
    job_id = plan["job_id"]
    first, second = task(), task(42, kind=TaskType.DOWNLOAD)
    manifest_id = await upload(window_runtime, job_id, [first])
    assert store.get(job_id) == plan
    assert store.active_page(limit=20) == [job_id]
    with pytest.raises(ValueError, match="incomplete"):
        await commit(window_runtime, job_id, manifest_id, 2)
    assert store.get(job_id) == plan
    # A new store/connection reads the durable upload checkpoint and appends.
    resumed = type(store)(store.session_factory)
    assert resumed.get(manifest_id)["total"] == 1
    await window_runtime.writes.submit(Op.APPEND_MPS_REPLACEMENT, {
        "manifest_id": manifest_id, "offset": 1, "tasks": [second.to_dict()],
    })
    store.update_config(job_id, name="Concurrent rename")
    replaced = await commit(window_runtime, job_id, manifest_id, 2)
    assert replaced["job_id"] == job_id
    assert replaced["job_config"]["name"] == "Concurrent rename"
    assert replaced["selection"] == {"task_manifest_id": manifest_id}
    assert replaced["total"] == 2
    assert replaced["cursor"] == replaced["completed"] == replaced["failed"] == 0
    page = resumed.definitions.page(manifest_id, offset=1, limit=1)
    assert [row["task_id"] for row in page] == [second.task_id]
    saved = page[0]["task"]
    assert saved["task_type"] == "download"
    assert saved["auth_id"] == 13
    assert saved["ip_lock_key"] == second.ip_lock_key
    assert saved["payload"] == second.to_dict()["payload"]
    assert store.active_page(limit=20) == [job_id]
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.mps_candidate_ranges")) == 0
        history = json.loads(session.scalar(text(
            "SELECT args_json FROM management.jobs WHERE job_id=:job"
        ), {"job": job_id}))
        assert history["task_count"] == 2
        assert sorted(history["task_types"]) == ["download", "scrape"]
        assert "tasks" not in history


async def test_dependencies_can_cross_windows_and_precede_their_input_in_the_list(
    store, window_runtime,
):
    plan = fixtures.prepare_runtime_plan(store, 1_000_000)
    job_id = plan["job_id"]
    scrape = task(41)
    download = task(41, kind=TaskType.DOWNLOAD, depends_on=[scrape.task_id])
    independent = task(42)
    manifest_id = await upload(window_runtime, job_id, [download, independent, scrape])
    await commit(window_runtime, job_id, manifest_id, 3)
    assert [r["task_id"] for r in store.definitions.ready_page(manifest_id, limit=1)] == [independent.task_id]
    with pytest.raises(ValueError, match="candidate evidence"):
        store.archive_window(job_id, start=0, end=1, manifest_id=manifest_id,
                             rows=[archive_row(job_id, download)])
    for ordinal, selected in enumerate([independent, scrape, download]):
        ready = store.definitions.ready_page(manifest_id, limit=1)
        assert [r["task_id"] for r in ready] == [selected.task_id]
        assert ready[0]["dependency_failed"] is False
        archived = store.archive_window(
            job_id, start=ordinal, end=ordinal + 1, manifest_id=manifest_id,
            rows=[archive_row(job_id, selected)],
        )
        assert archived["cursor"] == archived["completed"] == ordinal + 1
    assert store.get(job_id)["status"] == "complete"
    assert store.definitions.ready_page(manifest_id, limit=1) == []
    assert store.definitions.page(manifest_id, offset=0, limit=1)[0]["task"]["depends_on"] == [scrape.task_id]


async def test_failed_dependency_requires_failed_downstream_evidence(store, window_runtime):
    job_id = fixtures.prepare_runtime_plan(store, 10)["job_id"]
    scrape = task()
    download = task(kind=TaskType.DOWNLOAD, depends_on=[scrape.task_id])
    manifest_id = await upload(window_runtime, job_id, [scrape, download])
    await commit(window_runtime, job_id, manifest_id, 2)
    store.archive_window(job_id, start=0, end=1, manifest_id=manifest_id,
                         rows=[archive_row(job_id, scrape, "failed")])
    ready = store.definitions.ready_page(manifest_id, limit=1)
    assert ready[0]["task_id"] == download.task_id and ready[0]["dependency_failed"]
    with pytest.raises(ValueError, match="explicit task definition"):
        store.archive_window(job_id, start=1, end=2, manifest_id=manifest_id,
                             rows=[archive_row(job_id, download)])
    result = store.archive_window(job_id, start=1, end=2, manifest_id=manifest_id,
                                  rows=[archive_row(job_id, download, "failed")])
    assert (result["cursor"], result["completed"], result["failed"]) == (2, 0, 2)


@pytest.mark.parametrize("initial_id,resolved_id,valid", [(0, 77, True), ("41", 41, True), (41, 77, False)])
async def test_explicit_task_identity_allows_resolution_but_preserves_known_ids(
    store, window_runtime, initial_id, resolved_id, valid,
):
    job_id = fixtures.prepare_runtime_plan(store, 10)["job_id"]
    selected = task(initial_id)
    manifest_id = await upload(window_runtime, job_id, [selected])
    await commit(window_runtime, job_id, manifest_id, 1)
    selected.user_id = resolved_id
    rows = [archive_row(job_id, selected)]
    if not valid:
        with pytest.raises(ValueError, match="identity differs"):
            store.archive_window(job_id, start=0, end=1, manifest_id=manifest_id, rows=rows)
        assert store.get(job_id)["cursor"] == 0
    else:
        store.archive_window(job_id, start=0, end=1, manifest_id=manifest_id, rows=rows)
        with store.session_factory() as session:
            assert session.scalar(text(
                "SELECT user_id FROM management.job_tasks WHERE task_id=:task"
            ), {"task": selected.task_id}) == resolved_id


async def test_unknown_dependency_and_truncated_upload_do_not_replace_the_job(
    store, window_runtime,
):
    plan = fixtures.prepare_runtime_plan(store, 1_000_000)
    manifest_id = await upload(window_runtime, plan["job_id"], [task(depends_on=["missing"])])
    with pytest.raises(ValueError, match="missing task"):
        await commit(window_runtime, plan["job_id"], manifest_id, 1)
    assert store.get(plan["job_id"]) == plan
    assert store.get(manifest_id)["status"] == "staging"


async def test_writer_replay_does_not_duplicate_upload_or_reset_new_progress(
    store, window_runtime,
):
    job_id = fixtures.prepare_runtime_plan(store, 10)["job_id"]
    manifest_id = "mps-edit-" + uuid4().hex
    await window_runtime.writes.submit(Op.BEGIN_MPS_REPLACEMENT, {
        "job_id": job_id, "manifest_id": manifest_id,
    })
    selected = task()
    command_id = uuid4().hex
    payload = {"manifest_id": manifest_id, "offset": 0, "tasks": [selected.to_dict()]}
    first = await window_runtime.writes.submit(Op.APPEND_MPS_REPLACEMENT, payload, command_id=command_id)
    assert await window_runtime.writes.submit(Op.APPEND_MPS_REPLACEMENT, payload, command_id=command_id) == first
    assert store.get(manifest_id)["total"] == 1
    commit_id = uuid4().hex
    committed = await commit(window_runtime, job_id, manifest_id, 1, command_id=commit_id)
    row = archive_row(job_id, selected)
    store.archive_window(job_id, start=0, end=1, manifest_id=manifest_id, rows=[row])
    assert await commit(window_runtime, job_id, manifest_id, 1, command_id=commit_id) == committed
    assert store.get(job_id)["cursor"] == 1
    assert store.archive_window(job_id, start=0, end=1, manifest_id=manifest_id, rows=[row])["cursor"] == 1


async def test_old_definition_cannot_archive_into_or_overwrite_a_later_replacement(
    store, window_runtime,
):
    job_id = fixtures.prepare_runtime_plan(store, 10)["job_id"]
    old_task = task()
    old_id = await upload(window_runtime, job_id, [old_task])
    stale_id = await upload(window_runtime, job_id, [task(42)])
    await commit(window_runtime, job_id, old_id, 1)
    with pytest.raises(ValueError, match="selection changed|not found"):
        await commit(window_runtime, job_id, stale_id, 1)
    new_task = task(43)
    new_id = await upload(window_runtime, job_id, [new_task])
    await commit(window_runtime, job_id, new_id, 1)
    with pytest.raises(ValueError, match="definition changed"):
        store.archive_window(job_id, start=0, end=1, manifest_id=old_id,
                             rows=[archive_row(job_id, old_task)])
    assert store.get(old_id) is None
    assert store.get(job_id)["cursor"] == 0
    assert [r["task_id"] for r in store.definitions.ready_page(new_id, limit=1)] == [new_task.task_id]


def test_upload_allocations_and_reads_remain_bounded_as_the_definition_grows(store):
    from sqlalchemy import event

    measurements = []
    template = task().to_dict()
    # Dataset/batch values exercise growth; they are not deployment settings.
    for total in [2_000, 20_000]:
        job_id = fixtures.prepare_runtime_plan(store, 1_000_000)["job_id"]
        manifest_id = "mps-edit-" + uuid4().hex
        store.definitions.begin(job_id, manifest_id)
        gc.collect()
        tracemalloc.start()
        started = time.monotonic()
        for offset in range(0, total, 100):
            batch = [
                {**template, "task_id": f"fixture-{manifest_id}-{i}", "user_id": i + 1}
                for i in range(offset, min(offset + 100, total))
            ]
            store.definitions.append(manifest_id, offset=offset, tasks=batch)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        measurements.append({"tasks": total, "batch": 100, "peak_traced_bytes": peak,
                             "seconds": time.monotonic() - started})
        store.definitions.commit(job_id, manifest_id, total=total)
        assert len(store.definitions.page(manifest_id, offset=total - 2, limit=2)) == 2
    # Catch retained per-task objects across the tenfold dataset increase.
    assert measurements[1]["peak_traced_bytes"] < measurements[0]["peak_traced_bytes"] * 3
    assert measurements[1]["peak_traced_bytes"] < 4 * 1024 * 1024

    with store.session_factory() as session:
        session.execute(text("ANALYZE management.mps_task_definitions"))
        session.commit()
    statements = []

    def capture(_conn, _cursor, statement, parameters, _context, _many):
        if "FROM management.mps_task_definitions AS node" in statement:
            statements.append((statement, parameters))

    with store.session_factory() as session:
        engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert len(store.definitions.ready_page(manifest_id, limit=2)) == 2
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    with engine.connect() as connection:
        statement, parameters = statements[0]
        plan = connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters,
        ).scalar_one()[0]["Plan"]

    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    scans = [node for node in nodes(plan) if node.get("Alias") == "node"]
    assert scans and all("Index" in node["Node Type"] for node in scans)
    assert sum(node["Actual Rows"] for node in scans) <= 2
    print("MPS_DEFINITION_MEASUREMENTS " + json.dumps({"uploads": measurements, "ready_plan": plan}))


def test_deleting_job_removes_committed_and_unfinished_definitions(store):
    job_id = fixtures.prepare_runtime_plan(store, 10)["job_id"]
    committed, unfinished = ["mps-edit-" + uuid4().hex for _ in range(2)]
    for manifest_id in [committed, unfinished]:
        store.definitions.begin(job_id, manifest_id)
        store.definitions.append(manifest_id, offset=0, tasks=[task().to_dict()])
        if manifest_id == committed:
            store.definitions.commit(job_id, manifest_id, total=1)
    with store.session_factory() as session:
        session.execute(text("""
            INSERT INTO management.mps_plans
              (job_id, site, job_config_json, selection_json, proxy_pool_json, status, total, summary_json)
            SELECT 'unrelated-' || n, 'onlyfans', '{}', '{}', '[]', 'definition', 0, '{}'
            FROM generate_series(1, 20000) AS n
        """))
        session.execute(text("ANALYZE management.mps_plans"))
        plan = session.execute(text("""
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT job_id FROM management.mps_plans WHERE parent_job_id=:job
        """), {"job": job_id}).scalar_one()[0]["Plan"]
        nodes = [plan]
        indexes = []
        while nodes:
            node = nodes.pop()
            if node.get("Index Name"):
                indexes.append(node["Index Name"])
            nodes.extend(node.get("Plans", []))
        assert "idx_mps_plans_parent_job" in indexes
        print("MPS_DEFINITION_OWNERSHIP_PLAN " + json.dumps(plan))
        session.execute(text("DELETE FROM management.mps_plans WHERE job_id=:job"), {"job": job_id})
        session.commit()
        assert session.scalar(text("SELECT count(*) FROM management.mps_task_definitions")) == 0
        assert session.scalar(text("SELECT count(*) FROM management.mps_plans WHERE job_id IN (:committed, :unfinished)"), {"committed": committed, "unfinished": unfinished}) == 0
        assert session.scalar(text("SELECT count(*) FROM management.mps_plans")) == 20000


def test_replacing_large_task_history_does_not_return_deleted_rows_to_python(store):
    job_id = fixtures.prepare_runtime_plan(store, 1_000_000)["job_id"]
    manifest_id = "mps-edit-" + uuid4().hex
    store.definitions.begin(job_id, manifest_id)
    store.definitions.append(manifest_id, offset=0, tasks=[task().to_dict()])
    # Seed retained history in SQL without constructing a Python result list.
    with store.session_factory() as session:
        session.execute(text("""
            INSERT INTO management.job_tasks (job_id, task_id, task_type, status, user_id)
            SELECT :job, 'retained-history-' || n, 'scrape', 'completed', n
            FROM generate_series(1, 40000) AS n
        """), {"job": job_id})
        session.execute(text("""
            UPDATE management.mps_plans SET cursor=40000, completed=40000 WHERE job_id=:job
        """), {"job": job_id})
        session.commit()
    gc.collect()
    tracemalloc.start()
    try:
        replaced = store.definitions.commit(job_id, manifest_id, total=1)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    print("MPS_HISTORY_REPLACEMENT_PEAK " + str(peak))
    assert replaced["total"] == 1 and replaced["cursor"] == 0
    assert peak < 4 * 1024 * 1024, f"History reset retained deleted SQL rows: {peak} bytes"
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 0


def test_reviewable_definition_schema_matches_the_model_and_cascades(postgres_engine, monkeypatch):
    import importlib.util
    from pathlib import Path

    import ultima_scraper_db_archive
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect
    from ultima_scraper_db_archive.global_db import MPSPlanModel, MPSTaskDefinitionModel

    path = Path(ultima_scraper_db_archive.__file__).parent / "migrations/alembic/versions/d613ac49e82b_add_mps_task_definitions.py"
    spec = importlib.util.spec_from_file_location("mps_definition_schema_fixture", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "a92e10b6f3d8"
    base_spec = importlib.util.spec_from_file_location(
        "mps_base_schema_fixture", path.parent / "a0f7d3c6e921_add_durable_mps_manifests.py"
    )
    base = importlib.util.module_from_spec(base_spec)
    base_spec.loader.exec_module(base)
    database = "definition_schema_" + uuid4().hex
    with postgres_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f"CREATE DATABASE {database}"))
    engine = create_engine(postgres_engine.url.set(database=database))
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA management"))
            monkeypatch.setattr(base, "op", Operations(MigrationContext.configure(connection)))
            base.upgrade()
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            inspector = inspect(connection)
            assert {c["name"] for c in inspector.get_columns("mps_plans", schema="management")} == set(MPSPlanModel.__table__.columns.keys())
            columns = inspector.get_columns("mps_task_definitions", schema="management")
            assert {c["name"]: c["nullable"] for c in columns} == {
                column.name: column.nullable for column in MPSTaskDefinitionModel.__table__.columns
            }
            assert inspector.get_pk_constraint("mps_task_definitions", schema="management")["constrained_columns"] == ["manifest_id", "ordinal"]
            assert inspector.get_foreign_keys("mps_task_definitions", schema="management")[0]["options"]["ondelete"] == "CASCADE"
            connection.execute(text("""
                INSERT INTO management.mps_plans
                  (job_id, site, job_config_json, selection_json, proxy_pool_json, total, summary_json)
                VALUES ('fixture', 'onlyfans', '{}', '{}', '[]', 1, '{}')
            """))
            connection.execute(text("""
                INSERT INTO management.mps_task_definitions
                  (manifest_id, ordinal, task_id, task_json, dependency_ids)
                VALUES ('fixture', 0, 'task-fixture', '{}', ARRAY[]::varchar[])
            """))
            connection.execute(text("DELETE FROM management.mps_plans WHERE job_id='fixture'"))
            assert connection.scalar(text("SELECT count(*) FROM management.mps_task_definitions")) == 0
            migration.downgrade()
            assert not inspect(connection).has_table("mps_task_definitions", schema="management")
    finally:
        engine.dispose()
        with postgres_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f"DROP DATABASE {database}"))
