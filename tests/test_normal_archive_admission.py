"""Count/byte-bounded terminal archival using owned PostgreSQL and Redis."""

import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import test_mps_manifest as fixtures
from ultima_scraper_backend.job_system import (
    Job,
    JobStorage,
    Task,
    TaskResult,
    TaskState,
)
from ultima_scraper_backend.job_system.models import JobState, TaskType
from ultima_scraper_backend.job_system import storage as storage_module
import legacy_redis_runtime as legacy

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


def storage_for(redis_manager):
    client = redis_manager.client
    return JobStorage(
        SimpleNamespace(
            client=client, get=client.get, set=client.set, delete=client.delete
        )
    )


async def saved_job(storage, count=7, size=10000):
    tasks = [
        Task(
            task_type=TaskType.SCRAPE,
            site_name="OnlyFans",
            user_id=index + 1,
            state=TaskState.COMPLETED,
            result=TaskResult(success=True, output={"payload": "x" * size}),
        )
        for index in range(count)
    ]
    job = Job.create(name="Archive fixture", created_by="tests", tasks=tasks)
    job.state = JobState.COMPLETED
    job.completed_at = datetime.now(timezone.utc).isoformat()
    await storage.persist_job(job, persist_tasks=True)
    return job


@pytest.mark.usefixtures("no_ledger_runs")
async def test_byte_limited_pages_preserve_order_without_skipping_the_unread_prefix(
    redis_manager,
):
    storage = storage_for(redis_manager)
    job = await saved_job(storage)
    client = storage._client()
    lengths = [
        await client.strlen(
            storage.TASK_KEY.format(job_id=job.job_id, task_id=task.task_id)
        )
        for task in job.tasks
    ]
    budget = sum(lengths[:2])
    expected = await legacy.list_tasks_for_job(storage, job.job_id)
    found = []
    cursor = None
    while True:
        page = await storage.fetch_task_page(
            job.job_id, limit=100, cursor=cursor, max_bytes=budget
        )
        sizes = [
            await client.strlen(
                storage.TASK_KEY.format(job_id=job.job_id, task_id=task.task_id)
            )
            for task in page.tasks
        ]
        assert sum(sizes) <= budget
        found.extend(task.task_id for task in page.tasks)
        if not page.next_cursor:
            break
        assert page.next_cursor != cursor
        cursor = page.next_cursor
    assert found == expected


@pytest.mark.usefixtures("no_ledger_runs")
async def test_oversized_first_value_is_rejected_before_task_decode(
    redis_manager, monkeypatch
):
    storage = storage_for(redis_manager)
    job = await saved_job(storage, count=1, size=100000)

    def unexpected_decode(*args):
        pytest.fail("An oversized task body reached Python task decoding")

    monkeypatch.setattr(storage, "_decode_task", unexpected_decode)
    with pytest.raises(storage_module.TaskPayloadBudgetExceeded) as error:
        await storage.fetch_task_page(job.job_id, max_bytes=2000)
    assert error.value.task_id == job.tasks[0].task_id
    assert error.value.required_bytes > 100000
    assert await storage._client().exists(
        storage.TASK_KEY.format(job_id=job.job_id, task_id=job.tasks[0].task_id)
    )


@pytest.mark.usefixtures("no_ledger_runs")
async def test_growth_before_atomic_read_is_rechecked(redis_manager, monkeypatch):
    storage = storage_for(redis_manager)
    job = await saved_job(storage, count=1, size=10)
    client = storage._client()
    evaluate = client.eval

    async def grow(script, key_count, *args):
        if script == storage_module._TASK_PREFIX_WITHIN_BYTES:
            task = job.tasks[0]
            task.result = TaskResult(success=True, output={"payload": "x" * 100000})
            await client.set(args[0], json.dumps(task.to_dict()))
        return await evaluate(script, key_count, *args)

    monkeypatch.setattr(client, "eval", grow)
    with pytest.raises(storage_module.TaskPayloadBudgetExceeded):
        await storage.fetch_task_page(job.job_id, max_bytes=2000)


@pytest.mark.usefixtures("no_ledger_runs")
async def test_filtered_stream_continues_past_empty_bounded_scan_pages(
    redis_manager, monkeypatch
):
    monkeypatch.setenv("ULTIMA_TASK_PAGE_SCAN_ENTRIES", "2")
    storage = storage_for(redis_manager)
    job = await saved_job(storage, count=7, size=1)
    last = job.tasks[-1]
    last.task_type = TaskType.DOWNLOAD
    await storage.persist_task(job.job_id, last)
    tasks = [
        task
        async for task in storage.fetch_tasks_stream(
            job.job_id, batch_size=2, task_type="download"
        )
    ]
    assert [task.task_id for task in tasks] == [last.task_id]


@pytest.mark.usefixtures("no_ledger_runs")
async def test_missing_prefix_members_advance_the_byte_cursor(redis_manager):
    storage = storage_for(redis_manager)
    job = await saved_job(storage, count=5, size=1)
    await storage._client().delete(
        *[
            storage.TASK_KEY.format(job_id=job.job_id, task_id=task.task_id)
            for task in job.tasks[:4]
        ]
    )
    tasks = [
        task
        async for task in storage.fetch_tasks_stream(
            job.job_id, batch_size=2, max_bytes=10000
        )
    ]
    assert [task.task_id for task in tasks] == [job.tasks[-1].task_id]


@pytest.mark.parametrize("count_budget", [1, 100])
async def test_archive_bounds_redis_and_sql_batches_and_preserves_all_results(
    store,
    window_runtime,
    monkeypatch,
    count_budget,
):
    monkeypatch.setenv("ULTIMA_JOB_TASK_ARCHIVE_BATCH_SIZE", str(count_budget))
    monkeypatch.setenv("ULTIMA_JOB_TASK_ARCHIVE_MAX_BYTES", "25000")
    storage = JobStorage(window_runtime.redis)
    job = await saved_job(storage, count=21, size=10000)
    client = storage._client()
    evaluate, insert = client.eval, storage._insert_central_tasks_sync
    reads, writes = [], []

    async def inspect_read(script, key_count, *args):
        result = await evaluate(script, key_count, *args)
        if script == storage_module._TASK_PREFIX_WITHIN_BYTES:
            reads.append((len(result[2]), int(result[0])))
        return result

    def inspect_insert(rows):
        writes.append(
            (
                len(rows),
                sum(
                    len(str(value).encode("utf-8"))
                    for row in rows
                    for value in row.values()
                    if value is not None
                ),
            )
        )
        return insert(rows)

    monkeypatch.setattr(client, "eval", inspect_read)
    monkeypatch.setattr(storage, "_insert_central_tasks_sync", inspect_insert)
    assert await storage._archive_job_tasks_to_db(job.job_id) == 21
    assert reads and writes
    assert all(
        count <= count_budget and size <= 25000 for count, size in reads + writes
    )
    with store.session_factory() as session:
        results = session.execute(
            text(
                "SELECT user_id, result_json FROM management.job_tasks WHERE job_id=:job ORDER BY user_id"
            ),
            {"job": job.job_id},
        ).all()
    assert [row.user_id for row in results] == list(range(1, 22))
    assert all(
        json.loads(row.result_json)["output"]["payload"] == "x" * 10000
        for row in results
    )


async def test_sql_output_expansion_cannot_exceed_the_archive_byte_budget(
    store, window_runtime
):
    storage = JobStorage(window_runtime.redis)
    job = await saved_job(storage, count=1, size=1)
    task = job.tasks[0]
    task.result = TaskResult(success=True, output={"payload": "😀" * 2000})
    key = storage.TASK_KEY.format(job_id=job.job_id, task_id=task.task_id)
    await storage._client().set(key, json.dumps(task.to_dict(), ensure_ascii=False))
    assert await storage._client().strlen(key) < 14000
    with pytest.raises(storage_module.TaskPayloadBudgetExceeded, match="SQL archive"):
        await storage._archive_job_tasks_to_db(job.job_id, max_bytes=14000)
    assert not await storage._client().exists(
        storage.TASK_ARCHIVE_MARKER_KEY.format(job_id=job.job_id)
    )
    assert await storage._client().exists(key)
    assert await storage._archive_job_tasks_to_db(job.job_id, max_bytes=30000) == 1


async def test_omitted_byte_budget_derives_from_writer_and_explicit_values_override_environment(
    store,
    window_runtime,
    monkeypatch,
):
    monkeypatch.setenv("ULTIMA_DATABASE_WRITE_MAX_COMMAND_BYTES", "4000")
    storage = JobStorage(window_runtime.redis)
    job = await saved_job(storage, count=3, size=10000)
    with pytest.raises(storage_module.TaskPayloadBudgetExceeded):
        await storage._archive_job_tasks_to_db(job.job_id)
    monkeypatch.setenv("ULTIMA_JOB_TASK_ARCHIVE_MAX_BYTES", "1000")
    monkeypatch.setenv("ULTIMA_JOB_TASK_ARCHIVE_BATCH_SIZE", "1000")
    assert (
        await storage._archive_job_tasks_to_db(
            job.job_id, batch_size=1, max_bytes=30000
        )
        == 3
    )


async def test_larger_configured_budget_does_not_replay_the_previous_rejection(
    store,
    window_runtime,
    monkeypatch,
):
    from ultima_scraper_backend.database.write_queue import (
        DatabaseWriteCommand,
        DatabaseWriteResult,
    )
    from ultima_scraper_backend.database.write_receipts import record_failure
    from ultima_scraper_backend.job_system import JobManager

    monkeypatch.setenv("ULTIMA_JOB_TASK_ARCHIVE_MAX_BYTES", "2000")
    manager = JobManager(window_runtime.redis)
    storage = manager.storage
    job = await saved_job(storage, count=3, size=10000)
    # Ordinary admission commits this owner header before tasks can execute.
    # The archive now checks it on every independently committed SQL batch.
    from ultima_scraper_backend.api.routes.jobs import _persist_central_job_submission_sync

    _persist_central_job_submission_sync(
        job_id=job.job_id,
        job_type="fixture",
        status="pending",
        site="onlyfans",
        args_payload={"job_name": job.name},
        tasks=job.tasks,
        job_config=job.to_config(include_task_ids=False).to_dict(),
    )
    commands = []

    async def submit(operation, payload, **kwargs):
        commands.append((kwargs["command_id"], dict(payload)))
        try:
            return await window_runtime.writes.submit(operation, payload, **kwargs)
        except storage_module.TaskPayloadBudgetExceeded as error:
            now = datetime.now(timezone.utc).isoformat()
            command = DatabaseWriteCommand(
                kwargs["command_id"],
                operation,
                None,
                payload,
                "archive-budget-test",
                now,
            )
            failure = DatabaseWriteResult(
                command.command_id, False, {}, str(error), now
            )
            await asyncio.to_thread(record_failure, command, failure)
            raise

    manager.database_writes = SimpleNamespace(submit=submit)
    await legacy.finalize_job_completion(manager, job.job_id)
    assert (
        await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id))
        == 3
    )
    monkeypatch.setenv("ULTIMA_JOB_TASK_ARCHIVE_MAX_BYTES", "30000")
    await legacy.finalize_job_completion(manager, job.job_id)
    assert len(commands) == 2
    assert commands[0][0] != commands[1][0]
    assert [payload["max_bytes"] for _, payload in commands] == [2000, 30000]
    assert (
        await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id))
        == 0
    )
    with store.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.job_tasks WHERE job_id=:job"),
                {"job": job.job_id},
            )
            == 3
        )


@pytest.mark.parametrize(
    "name", ["ULTIMA_JOB_TASK_ARCHIVE_BATCH_SIZE", "ULTIMA_JOB_TASK_ARCHIVE_MAX_BYTES"]
)
@pytest.mark.parametrize("value", ["0", "-1", "bad"])
async def test_invalid_archive_settings_fail_before_sql_mutation(
    redis_manager, monkeypatch, name, value
):
    monkeypatch.setenv(name, value)
    storage = storage_for(redis_manager)

    def unexpected_delete(*args):
        pytest.fail("Invalid resource settings reached a SQL mutation")

    monkeypatch.setattr(storage, "_delete_central_tasks_sync", unexpected_delete)
    with pytest.raises(ValueError, match="positive integer"):
        await storage._archive_job_tasks_to_db("unread-job")
