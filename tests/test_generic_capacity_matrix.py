"""Sample logical-scale transitions using owned SQL and native/fake Redis.

Large prefixes are synthetic counters, with omitted old/future definition and
history rows explicitly recorded. Only the sampled rows exist. These tests prove
bounded sampled access and recovery, not million-row query performance or full
application creation throughput. The separate cardinality runner supplies that
database experiment. Writer transport and task work use the existing window
fixture; real SQL execution, wire encoding and Redis state transitions remain.
"""

import json
import tracemalloc
from uuid import uuid4

import pytest
from sqlalchemy import event, text

import test_mps_manifest as fixtures
from test_mps_attempt_ownership import worker_for
from test_normal_task_windows import admit
from test_normal_durable_inputs import task
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation as Op
from ultima_scraper_backend.job_system import JobStorage, TaskResult, durable, mps_state
from ultima_scraper_backend.job_system.models import TaskRegistry, TaskType
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime

WINDOW = 3
BYTE_LIMIT = 32768


def position(total, edge):
    return {"first": 0, "middle": total // 2, "final": total - WINDOW}[edge]


async def sampled_plan(store, runtime, *, total, prefix, shape, tasks=None):
    """Retain at most six actual definitions or three sparse compact ranges."""
    count = min(WINDOW * 2, total - prefix)
    if shape == "explicit":
        tasks = tasks if tasks is not None else [task(prefix+i, width=32) for i in range(count)]
        count = len(tasks)
        job = await admit(runtime, tasks=tasks)
        job_id = job.job_id
        manifest = job.metadata["mps_task_manifest"]
        with store.session_factory() as session:
            session.execute(text("UPDATE management.mps_task_definitions SET ordinal=ordinal+:prefix WHERE manifest_id=:manifest"),
                            {"prefix": prefix, "manifest": manifest})
            session.execute(text("UPDATE management.mps_plans SET total=:total WHERE job_id=:manifest"),
                            {"total": total, "manifest": manifest})
            session.commit()
        # Preparation published only the original small header. Recovery must
        # reconstruct the newly declared sampled state from SQL, not that cache.
        await runtime.redis.client.flushdb()
    else:
        plan = fixtures.prepare_runtime_plan(store, total)
        job_id, manifest = plan["job_id"], None
        # Three disjoint ranges preserve sparse source IDs without enumerating
        # the logical membership. The middle sample crosses a range boundary.
        cuts = (0, total // 2 + 1, total - 10, total)
        with store.session_factory() as session:
            session.execute(text("DELETE FROM management.mps_candidate_ranges WHERE job_id=:job"), {"job": job_id})
            for index, (lo, hi) in enumerate(zip(cuts, cuts[1:])):
                start = 1 + index * 10_000_000
                session.execute(text("INSERT INTO management.mps_candidate_ranges(job_id,first_ordinal,start_id,end_id) VALUES (:job,:ordinal,:start,:end)"),
                                {"job": job_id, "ordinal": lo, "start": start, "end": start + hi-lo-1})
            session.commit()
    with store.session_factory() as session:
        session.execute(text("""
            UPDATE management.mps_plans SET total=:total, cursor=:prefix, completed=:prefix,
              job_config_json=(job_config_json::jsonb || jsonb_build_object(
                'total_tasks',:total,'completed_tasks',:prefix))::text WHERE job_id=:job
        """), {"job": job_id, "total": total, "prefix": prefix})
        session.commit()
    return job_id, manifest, count if manifest else 0


@pytest.mark.parametrize("total", [100, 1_000_000])
@pytest.mark.parametrize("edge", ["first", "middle", "final"])
@pytest.mark.parametrize("shape", ["sparse_ranges", "explicit"])
@pytest.mark.parametrize("fault", ["none", "lost_commit_reply", "retirement"])
async def test_sampled_windows_recover_at_large_ordinals(
    store, window_runtime, monkeypatch, record_property, total, edge, shape, fault,
):
    for scope in ("JOB", "MPS"):
        for aggregate in ("", "GLOBAL_"):
            monkeypatch.setenv(f"ULTIMA_{scope}_{aggregate}WINDOW_MAX_TASKS", str(WINDOW))
            monkeypatch.setenv(f"ULTIMA_{scope}_{aggregate}WINDOW_MAX_BYTES", str(BYTE_LIMIT))
    prefix = position(total, edge)
    job_id, manifest, definition_count = await sampled_plan(
        store, window_runtime, total=total, prefix=prefix, shape=shape,
    )
    storage = JobStorage(window_runtime.redis)
    client = storage._client()
    budget = mps_state.BUDGET_KEY
    returned_rows = []
    with store.session_factory() as session:
        engine = session.get_bind()

    def capture(_connection, cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            returned_rows.append(cursor.rowcount)

    event.listen(engine, "after_cursor_execute", capture)
    tracemalloc.start()
    try:
        await durable.advance(window_runtime, job_id)
        first_ids = await legacy.list_tasks_for_job(storage, job_id)
        assert len(first_ids) == WINDOW
        assert int(await client.hget(budget, "tasks")) == WINDOW
        assert 0 < int(await client.hget(budget, "bytes")) <= BYTE_LIMIT
        completed = await fixtures.complete_window(storage, job_id)
        assert len(completed) == WINDOW
        if fault == "lost_commit_reply":
            writes_type, armed = type(window_runtime.writes), True
            submit = writes_type.submit

            async def lose_reply(self, operation, payload, **kwargs):
                nonlocal armed
                result = await submit(self, operation, payload, **kwargs)
                if operation == Op.ARCHIVE_MPS_WINDOW and armed:
                    armed = False
                    raise RuntimeError("sampled lost commit reply")
                return result

            monkeypatch.setattr(writes_type, "submit", lose_reply)
        elif fault == "retirement":
            purge = durable._purge_archived_window

            async def interrupt(*_args, **_kwargs):
                raise RuntimeError("sampled interrupted retirement")

            monkeypatch.setattr(durable, "_purge_archived_window", interrupt)
        if fault == "none":
            await durable.advance(window_runtime, job_id)
        else:
            with pytest.raises(RuntimeError, match="sampled"):
                await durable.advance(window_runtime, job_id)
            assert store.get(job_id)["cursor"] == prefix + WINDOW
            assert await legacy.list_tasks_for_job(storage, job_id) == first_ids
            if fault == "retirement":
                monkeypatch.setattr(durable, "_purge_archived_window", purge)
        # Replay after a committed checkpoint must purge the old tasks without
        # counting them twice. A non-final sample may publish only the next page.
        await durable.advance(window_runtime, job_id)
        current_ids = await legacy.list_tasks_for_job(storage, job_id)
        assert not set(first_ids).intersection(current_ids)
        assert len(current_ids) <= WINDOW
        assert int(await client.hget(budget, "tasks") or 0) <= WINDOW
        assert int(await client.hget(budget, "bytes") or 0) <= BYTE_LIMIT
        plan = store.get(job_id)
        assert (plan["cursor"], plan["completed"], plan["total"]) == (prefix + WINDOW, prefix + WINDOW, total)
        page = await jobs.get_job_tasks(job_id, cursor=str(prefix), limit=WINDOW, backend=window_runtime)
        assert {row.task_id for row in page.tasks} == set(first_ids)
        assert all(row.status == "completed" for row in page.tasks)
        if edge == "final":
            assert plan["status"] == "complete" and not current_ids
            assert page.next_cursor is None
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        event.remove(engine, "after_cursor_execute", capture)
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"), {"job": job_id}) == WINDOW
        assert session.scalar(text("SELECT count(*) FROM management.mps_task_definitions")) == definition_count
        assert session.scalar(text("SELECT count(*) FROM management.mps_candidate_ranges")) == (0 if manifest else 3)
    assert peak < 16 * 1024 * 1024
    assert max(returned_rows) <= 10
    assert await client.dbsize() < 100
    record_property("sample", json.dumps({
        "logical_total": total, "synthetic_completed_prefix": prefix,
        "physical_definitions": definition_count, "compact_ranges": 0 if manifest else 3,
        "physical_history": WINDOW, "completed_sample_tasks": len(completed),
        "next_window_tasks": len(current_ids), "max_query_rows_returned": max(returned_rows),
        "redis_keys": await client.dbsize(), "traced_peak_bytes": peak,
        "omitted_rows": "all old history and non-sampled explicit definitions",
    }))


@pytest.mark.parametrize("total", [100, 1_000_000])
@pytest.mark.parametrize("edge", ["first", "middle", "final"])
async def test_later_preparation_checkpoint_replays_without_publication(
    store, window_runtime, record_property, total, edge,
):
    prefix = position(total, edge)
    source = fixtures.prepare_runtime_plan(store, total)
    manifest = "sampled-stage-" + uuid4().hex
    await window_runtime.writes.submit(Op.BEGIN_MPS_REPLACEMENT, {
        "job_id": source["job_id"], "manifest_id": manifest,
    })
    with store.session_factory() as session:
        # Earlier input pages are represented only by their durable checkpoint.
        session.execute(text("UPDATE management.mps_plans SET total=:prefix WHERE job_id=:manifest"),
                        {"prefix": prefix, "manifest": manifest})
        session.commit()
    payload = {"manifest_id": manifest, "offset": prefix,
               "tasks": [task(prefix+i, width=32).to_dict() for i in range(WINDOW)]}
    command_id = uuid4().hex
    first = await window_runtime.writes.submit(Op.APPEND_MPS_REPLACEMENT, payload, command_id=command_id)
    # Simulate a caller losing the successful reply; a fresh writer client uses
    # the same durable command identity after its restart.
    replay = await type(window_runtime.writes)().submit(Op.APPEND_MPS_REPLACEMENT, payload, command_id=command_id)
    assert first == replay and replay["uploaded"] == prefix + WINDOW
    assert store.get(source["job_id"]) == source
    assert manifest not in store.active_page(limit=10)
    rows = store.definitions.page(manifest, offset=prefix, limit=WINDOW)
    assert [row["ordinal"] for row in rows] == list(range(prefix, prefix + WINDOW))
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.mps_task_definitions")) == WINDOW
    record_property("preparation", json.dumps({"logical_total": total, "synthetic_prefix": prefix,
        "materialized_task_dictionaries": WINDOW, "physical_definitions": len(rows), "published_replacement": False}))


@pytest.mark.parametrize("total", [100, 1_000_000])
@pytest.mark.parametrize("edge", ["first", "middle", "final"])
async def test_dependencies_and_spawned_child_use_large_ordinals(
    store, window_runtime, monkeypatch, record_property, total, edge,
):
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS", "1")
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_BYTES", str(BYTE_LIMIT))
    monkeypatch.setenv("ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES", str(BYTE_LIMIT))
    prefix = position(total, edge)
    parents = [task(prefix+i, width=32) for i in range(3)]
    parents[1].depends_on = [parents[0].task_id]
    parents[2].depends_on = [parents[1].task_id]
    child = task(total+1, width=32)
    child.task_id = "sampled-child-" + uuid4().hex
    child.depends_on = [parents[0].task_id]
    job_id, manifest, _count = await sampled_plan(
        store, window_runtime, total=total, prefix=prefix, shape="explicit", tasks=parents,
    )
    storage = JobStorage(window_runtime.redis)
    seen = []

    async def handler(value, context):
        seen.append((value.task_id, context.previous_output))
        return TaskResult(success=True, output={"parent": value.task_id},
                          new_tasks=[child] if value.task_id == parents[0].task_id else [])

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, handler)
    worker = worker_for(window_runtime, storage, [])
    for index in range(4):
        await durable.advance(window_runtime, job_id)
        (task_id,) = await legacy.list_tasks_for_job(storage, job_id)
        assert task_id == (parents[index].task_id if index < 3 else child.task_id)
        assert await worker._execute_ready_task(job_id, task_id) == (True, False, None)
        assert await legacy.list_tasks_for_job(storage, job_id) == [task_id]
        await durable.advance(window_runtime, job_id)
        assert store.get(job_id)["cursor"] == prefix + index + 1
    assert [item[1] for item in seen[1:]] == [
        {"parent": parents[0].task_id}, {"parent": parents[1].task_id}, {"parent": parents[0].task_id},
    ]
    assert store.get(job_id)["total"] == total + 1
    assert len(await legacy.list_tasks_for_job(storage, job_id)) <= 1
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.mps_task_definitions WHERE manifest_id=:manifest"), {"manifest": manifest}) == 4
        assert session.scalar(text("SELECT ordinal FROM management.mps_task_definitions WHERE manifest_id=:manifest AND task_id=:child"),
                              {"manifest": manifest, "child": child.task_id}) == total
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"), {"job": job_id}) == 4
    record_property("dependencies", json.dumps({"logical_total_before_child": total,
        "synthetic_prefix": prefix, "physical_definitions_after_child": 4,
        "physical_history": 4, "worker_attempts": len(seen), "window_tasks": 1}))
