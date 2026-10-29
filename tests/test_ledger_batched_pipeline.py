"""Native ownership, independent refill and bounded pipeline regressions."""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, text
from test_execution_ledger import (
    finish,
    ledger,
    ledger_engine,
    postgres_engine,
    submit,
    task,
)
from test_ledger_planner_batches import create_range
from ultima_scraper_backend.job_system.ledger import StaleAttempt, Work
from ultima_scraper_backend.job_system.ledger_batches import (
    checkpoint_request,
    completion_request,
)
from ultima_scraper_backend.job_system.ledger_runtime import (
    ExecutionTelemetry,
    worker_claim_capacity,
)
from ultima_scraper_backend.job_system.lifecycle_batcher import LifecycleBatcher
from ultima_scraper_backend.job_system.models import Task, TaskResult, TaskState

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def test_terminal_defaults_follow_effective_global_overrides(monkeypatch):
    from ultima_scraper_backend.job_system.ledger import Limits

    monkeypatch.setenv("ULTIMA_LEDGER_GLOBAL_TASKS", "24000")
    monkeypatch.setenv("ULTIMA_LEDGER_GLOBAL_BYTES", "134217728")
    monkeypatch.delenv("ULTIMA_LEDGER_TERMINAL_TASKS", raising=False)
    monkeypatch.delenv("ULTIMA_LEDGER_TERMINAL_BYTES", raising=False)
    limits = Limits.load()
    assert limits.terminal_tasks == 48000
    assert limits.terminal_bytes == 134217728


def test_ledger_claim_pages_use_ledger_cap_instead_of_legacy_default(monkeypatch):
    from ultima_scraper_backend.job_system.ledger_runtime import ledger_claim_page_size

    # Explicitly blank bypasses the workspace's dotenv override in this test.
    monkeypatch.setenv("ULTIMA_CLAIM_BATCH_SIZE", "")
    assert ledger_claim_page_size(128) == 128
    monkeypatch.setenv("ULTIMA_CLAIM_BATCH_SIZE", "16")
    assert ledger_claim_page_size(128) == 16
    monkeypatch.setenv("ULTIMA_CLAIM_BATCH_SIZE", "256")
    assert ledger_claim_page_size(128) == 128


def inputs(ledger, count=4):
    submit(ledger, [task(f"task-{i:03}", user_id=i + 1) for i in range(count)])
    ledger.tick()
    return ledger.claim_many(
        owner="worker-a", backend_id="backend-a", capabilities=["onlyfans"], count=count
    )


def completed(owned, *, success=True):
    item = Task.from_dict(owned.task)
    item.state = TaskState.COMPLETED if success else TaskState.FAILED
    item.result = TaskResult(
        success=success, output={"value": 7}, message="test outcome"
    )
    item.completed_at = item.result.completed_at
    return item


def test_one_batch_preserves_exact_states_resources_events_and_replay(
    ledger, ledger_engine, live_task_events
):
    owned = inputs(ledger)
    statements = []

    def capture(conn, cursor, statement, *args):
        if not statement.startswith("SET LOCAL"):
            statements.append(statement)

    event.listen(ledger_engine, "after_cursor_execute", capture)
    try:
        assert (
            ledger.checkpoint_batch(
                [
                    checkpoint_request(ledger, c, c.task, persisting=True, renew=True)
                    for c in owned
                ]
            )
            == [None] * 4
        )
        assert len(statements) == 1
        statements.clear()
        requests = [
            completion_request(ledger, c, completed(c), timings={"value": i})
            for i, c in enumerate(owned)
        ]
        assert ledger.finish_batch(requests) == [None] * 4
        assert (
            len(statements) <= 3
        )  # Fixed transaction work, independent of task count.
    finally:
        event.remove(ledger_engine, "after_cursor_execute", capture)
    assert ledger.stats("job-test")["completed"] == 4
    ledger.archive_tick()
    assert ledger.finish_batch(requests) == [None] * 4
    with ledger.session_factory() as session:
        assert (
            session.scalar(text("SELECT count(*) FROM management.execution_resources"))
            == 0
        )
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.execution_outbox WHERE payload_json LIKE '%task_completed%'"
                )
            )
            == 0
        )
        assert [e["event"] for e in live_task_events].count("task_completed") == 4
        assert (
            len(session.execute(text("SELECT * FROM management.job_tasks")).all()) == 4
        )


def test_finish_probes_attempt_keys_instead_of_merging_the_run(ledger, ledger_engine):
    # Every attempt of a run shares its run_id. In production a merge join on
    # run_id read the run's whole attempt partition for each finish batch.
    from ultima_scraper_backend.job_system.ledger_batches import _FINISH, _FINISH_PLANNER

    owned = inputs(ledger)
    with ledger.session_factory() as session:
        session.execute(
            text(
                """INSERT INTO management.execution_attempts
                (run_id,task_id,number,token,owner,state,started_at,completed_at,timings_json)
                SELECT 'job-test','bulk-'||g,1,md5(g::text),'w','completed',
                    now()-make_interval(secs=>g),now(),'{}'
                FROM generate_series(1,50000) g"""
            )
        )
        session.commit()
        session.execute(text("ANALYZE management.execution_attempts"))
        session.commit()
        requests = [completion_request(ledger, c, completed(c)) for c in owned]
        session.execute(_FINISH_PLANNER)
        plan = "\n".join(
            row[0]
            for row in session.execute(
                text("EXPLAIN " + _FINISH.text),
                {
                    "requests": json.dumps(
                        [{**r, "ordinal": i} for i, r in enumerate(requests)]
                    ),
                    "history_run_ids": ["job-test"],
                },
            )
        )
        session.rollback()
    attempt_plan = plan.split("CTE finished_attempt")[1].split("CTE released_resource")[0]
    assert "Merge Join" not in attempt_plan and "Hash Join" not in attempt_plan
    assert "pkey" in attempt_plan and "number = " in attempt_plan

    statements = []

    def capture(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(ledger_engine, "after_cursor_execute", capture)
    try:
        assert ledger.finish_batch(requests) == [None] * 4
    finally:
        event.remove(ledger_engine, "after_cursor_execute", capture)
    guard = statements.index("SET LOCAL enable_mergejoin=off")
    finish = next(i for i, s in enumerate(statements) if "finished_attempt AS" in s)
    assert guard < finish


def test_expired_member_does_not_poison_live_member(ledger):
    owned = inputs(ledger, 2)
    with ledger.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.execution_work SET lease_until=clock_timestamp()-interval '1 second' WHERE task_id=:id"
            ),
            {"id": owned[0].task_id},
        )
        session.commit()
    results = ledger.checkpoint_batch(
        [
            checkpoint_request(ledger, c, c.task, persisting=True, renew=True)
            for c in owned
        ]
    )
    assert isinstance(results[0], StaleAttempt) and results[1] is None
    results = ledger.finish_batch(
        [completion_request(ledger, c, completed(c)) for c in owned]
    )
    assert isinstance(results[0], StaleAttempt) and results[1] is None
    assert ledger.stats("job-test")["completed"] == 1


def test_cancelled_run_does_not_poison_other_run_in_batch(ledger):
    submit(ledger, [task("task-a", user_id=1)], identity="job-a")
    submit(ledger, [task("task-b", user_id=2)], identity="job-b")
    ledger.tick()
    ledger.tick()
    owned = ledger.claim_many(
        owner="worker-a", backend_id="backend-a", capabilities=["onlyfans"], count=2
    )
    assert len(owned) == 2
    ledger.control("job-a", "cancel")
    results = ledger.finish_batch(
        [completion_request(ledger, c, completed(c)) for c in owned]
    )
    for c, result in zip(owned, results, strict=True):
        assert (
            isinstance(result, StaleAttempt) if c.run_id == "job-a" else result is None
        )
    assert ledger.stats("job-b")["completed"] == 1


@pytest.mark.asyncio
async def test_buffered_renewal_preserves_start_payload_and_drops_expired_claim(ledger):
    from ultima_scraper_backend.job_system.ledger_runtime import LedgerRouterAdapter

    owned = inputs(ledger, 2)
    router = LedgerRouterAdapter.__new__(LedgerRouterAdapter)
    router.ledger = ledger
    router.claims = {(c.run_id, c.task_id): (ledger, c) for c in owned}
    with ledger.session_factory() as session:
        original = session.scalar(
            select(Work.payload_json).where(Work.task_id == owned[1].task_id)
        )
        session.execute(
            text(
                "UPDATE management.execution_work SET lease_until=clock_timestamp()-interval '1 second' WHERE task_id=:id"
            ),
            {"id": owned[0].task_id},
        )
        session.commit()
    live = await router.renew_buffered(list(router.claims))
    assert live == {(owned[1].run_id, owned[1].task_id)}
    assert set(router.claims) == live
    with ledger.session_factory() as session:
        assert (
            session.scalar(
                select(Work.payload_json).where(Work.task_id == owned[1].task_id)
            )
            == original
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("paid", [False, True])
async def test_only_final_mps_profile_stage_releases_fetch_capacity(
    ledger, monkeypatch, paid
):
    from test_execution_ledger import pool
    from ultima_scraper_backend.job_system import ledger_runtime
    from ultima_scraper_backend.job_system.models import TaskRegistry, TaskType
    from ultima_scraper_backend.job_system.payloads import ScrapeTaskPayload

    worker = pool()
    worker._ledger_stage_changed = asyncio.Event()
    item = task()
    item.content_type = "profile"
    item.payload = ScrapeTaskPayload(
        max_items=1, paid_content_feed=paid, download_media=False
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(item, context):
        context.context["release_fetch_capacity"]()
        entered.set()
        await release.wait()
        return TaskResult(success=True)

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, handler)
    submit(ledger, [item])
    ledger.tick()
    owned = ledger.claim_many(
        owner="worker-a", backend_id="backend-a", capabilities=["onlyfans"], count=1
    )[0]
    running = asyncio.create_task(ledger_runtime.execute(worker, ledger, owned))
    await asyncio.wait_for(entered.wait(), 2)
    assert bool(worker._ledger_persisting_tasks) is (not paid)
    assert worker._ledger_stage_changed.is_set() is (not paid)
    assert ledger.stats("job-test")["completed"] == 0
    release.set()
    await running
    await worker._ledger_lifecycle_batcher.close()
    assert not worker._ledger_persisting_tasks


@pytest.mark.parametrize("kind", ["checkpoint", "finish"])
def test_batch_expiry_is_checked_after_all_locks(ledger, kind):
    owned = inputs(ledger, 2)
    with ledger.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.execution_work SET lease_until=clock_timestamp()+interval '250 milliseconds'"
            )
        )
        session.commit()

    def call():
        if kind == "checkpoint":
            return ledger.checkpoint_batch(
                [checkpoint_request(ledger, c, c.task, renew=True) for c in owned]
            )
        return ledger.finish_batch(
            [completion_request(ledger, c, completed(c)) for c in owned]
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        with ledger.session_factory() as blocker:
            blocker.execute(
                text(
                    "SELECT task_id FROM management.execution_work ORDER BY task_id FOR UPDATE"
                )
            )
            future = executor.submit(call)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
            time.sleep(0.25)
            blocker.commit()
        assert all(isinstance(r, StaleAttempt) for r in future.result(timeout=3))
    assert ledger.stats("job-test")["completed"] == 0


def test_batch_finish_failure_rolls_back_all_then_can_retry(ledger, ledger_engine, live_task_events):
    owned = inputs(ledger)
    requests = [completion_request(ledger, c, completed(c)) for c in owned]
    live_task_events.clear()

    def reject(conn, cursor, statement, *args):
        if "finished_attempt" in statement:
            raise ConnectionError("controlled rollback")

    event.listen(ledger_engine, "before_cursor_execute", reject)
    try:
        with pytest.raises(ConnectionError):
            ledger.finish_batch(requests)
    finally:
        event.remove(ledger_engine, "before_cursor_execute", reject)
    assert ledger.stats("job-test")["inflight"] == 4
    assert live_task_events == []  # Nothing is announced for a rolled-back batch.
    assert ledger.finish_batch(requests) == [None] * 4
    assert [e["event"] for e in live_task_events].count("task_completed") == 4


def test_batch_retry_preserves_backoff_payload_and_finish_replay(ledger):
    owned = inputs(ledger, 2)
    requests = [
        completion_request(ledger, c, completed(c, success=False), retry=True)
        for c in owned
    ]
    assert ledger.finish_batch(requests) == [None] * 2
    assert ledger.finish_batch(requests) == [None] * 2
    with ledger.session_factory() as session:
        rows = session.execute(
            text(
                "SELECT p.payload_json,w.available_at,a.completed_at FROM management.execution_work w JOIN management.execution_work_payloads p USING(run_id,task_id) JOIN management.execution_attempts a USING(run_id,task_id)"
            )
        ).all()
        for row in rows:
            assert json.loads(row.payload_json)["result"] is None
            assert (row.available_at - row.completed_at).total_seconds() == 2


def test_refill_proceeds_while_archive_holds_plan_lock(ledger):
    create_range(ledger, "job-range")
    ledger.tick(refill_only=True)
    for owned in ledger.claim_many(
        owner="worker-a", backend_id="backend-a", capabilities=["onlyfans"], count=4
    ):
        finish(ledger, owned)
    with (
        ThreadPoolExecutor(max_workers=1) as executor,
        ledger.session_factory() as blocker,
    ):
        blocker.execute(text("SELECT job_id FROM management.mps_plans FOR UPDATE"))
        assert (
            executor.submit(ledger.tick, refill_only=True).result(timeout=3)
            == "job-range"
        )
        blocker.rollback()
    assert ledger.stats("job-range")["completed"] == 4
    assert ledger.stats("job-range")["ready"] == 4
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 0
        rows = session.execute(select(Work.candidate)).scalars().all()
        assert len(set(rows)) == len(rows) == 8


def test_archive_commit_between_window_and_plan_cannot_duplicate_candidates(
    ledger, ledger_engine
):
    create_range(ledger, "job-range")
    ledger.tick(refill_only=True)
    for owned in ledger.claim_many(
        owner="worker-a", backend_id="backend-a", capabilities=["onlyfans"], count=4
    ):
        finish(ledger, owned)
    triggered = False

    def archive_after_window(conn, cursor, statement, *args):
        nonlocal triggered
        if not triggered and "AS global_terminal_count" in statement:
            triggered = True
            assert ledger.archive_tick() == "job-range"

    event.listen(ledger_engine, "after_cursor_execute", archive_after_window)
    try:
        assert ledger.tick(refill_only=True) == "job-range"
    finally:
        event.remove(ledger_engine, "after_cursor_execute", archive_after_window)
    assert triggered
    with ledger.session_factory() as session:
        assert sorted(session.execute(select(Work.candidate)).scalars()) == [4, 5, 6, 7]
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 4


@pytest.mark.parametrize("budget", ["count", "bytes"])
def test_terminal_backpressure_stops_refill_and_archive_releases_it(ledger, budget):
    create_range(ledger, "job-range")
    ledger.tick(refill_only=True)
    for owned in ledger.claim_many(
        owner="worker-a", backend_id="backend-a", capabilities=["onlyfans"], count=4
    ):
        finish(ledger, owned)
    ledger.limits = replace(
        ledger.limits,
        **({"terminal_tasks": 4} if budget == "count" else {"terminal_bytes": 1}),
    )
    assert ledger.tick(refill_only=True) is None
    assert ledger.stats("job-range")["ready"] == 0
    assert ledger.archive_tick() == "job-range"
    assert ledger.tick(refill_only=True) == "job-range"
    assert ledger.stats("job-range")["ready"] == 4


@pytest.mark.asyncio
async def test_async_batcher_combines_peers_and_records_admission(ledger):
    owned = inputs(ledger)
    batcher = LifecycleBatcher(ledger)
    metrics = [ExecutionTelemetry() for c in owned]
    await asyncio.gather(
        *(
            batcher.submit(
                "checkpoint",
                checkpoint_request(ledger, c, c.task, persisting=True, renew=True),
                metrics=m,
                phase="writer_prepare",
            )
            for c, m in zip(owned, metrics)
        )
    )
    await batcher.close()
    assert batcher._tasks == batcher._bytes == 0
    assert all(
        m.ledger["writer_prepare_batch_wait_admission"]["count"] == 1 for m in metrics
    )
    assert all(ledger.task(c.run_id, c.task_id)["state"] == "saving_db" for c in owned)


@pytest.mark.asyncio
async def test_cancellation_after_enqueue_waits_for_owned_commit(ledger, monkeypatch):
    owned = inputs(ledger, 1)[0]
    entered, release = asyncio.Event(), asyncio.Event()
    from ultima_scraper_backend.job_system import lifecycle_batcher

    async def delayed(function):
        entered.set()
        await release.wait()
        return function()

    monkeypatch.setattr(lifecycle_batcher, "run_database_call", delayed)
    batcher = LifecycleBatcher(ledger)
    pending = asyncio.create_task(
        batcher.submit("finish", completion_request(ledger, owned, completed(owned)))
    )
    await asyncio.wait_for(entered.wait(), 2)
    pending.cancel()
    await asyncio.sleep(0.01)
    assert not pending.done() and ledger.stats("job-test")["completed"] == 0
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await batcher.close()
    assert ledger.stats("job-test")["completed"] == 1


def test_fetch_capacity_recycles_only_within_persistence_bound():
    pool = SimpleNamespace(_ledger_persisting_tasks=set(range(6)))
    assert worker_claim_capacity(pool, 10, 10, 4) == (4, 14)
    assert worker_claim_capacity(pool, 14, 10, 4) == (0, 14)
    pool._ledger_persisting_tasks.clear()
    assert worker_claim_capacity(pool, 10, 10, 4) == (0, 14)


@pytest.mark.asyncio
async def test_fetch_stage_wakes_dispatch_before_task_completion():
    from ultima_scraper_backend.job_system.ledger_runtime import (
        wait_for_worker_capacity,
    )

    stage_changed, complete = asyncio.Event(), asyncio.Event()
    active = asyncio.create_task(complete.wait())
    waiting = asyncio.create_task(wait_for_worker_capacity({active}, stage_changed))
    stage_changed.set()
    await asyncio.wait_for(waiting, 0.1)
    assert not active.done()
    complete.set()
    await active


@pytest.mark.asyncio
async def test_queue_backpressure_bounds_pending_requests(monkeypatch):
    from ultima_scraper_backend.job_system import lifecycle_batcher

    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(function):
        entered.set()
        await release.wait()
        return function()

    monkeypatch.setattr(lifecycle_batcher, "run_database_call", delayed)
    fake = SimpleNamespace(
        limits=SimpleNamespace(batch=2, result_bytes=1024),
        checkpoint_batch=lambda rows: [None] * len(rows),
    )
    batcher = LifecycleBatcher(fake)
    calls = [
        asyncio.create_task(batcher.submit("checkpoint", {"payload": str(i)}))
        for i in range(8)
    ]
    await asyncio.wait_for(entered.wait(), 2)
    assert batcher._tasks == 4 and batcher._bytes <= batcher.capacity_bytes
    release.set()
    await asyncio.gather(*calls)
    await batcher.close()
    assert batcher._tasks == batcher._bytes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_kind", ["checkpoint", "finish"])
async def test_lifecycle_phases_do_not_wait_for_each_other(monkeypatch, blocked_kind):
    from ultima_scraper_backend.job_system import lifecycle_batcher

    entered, release = asyncio.Event(), asyncio.Event()
    called = []

    def execute(kind, rows):
        called.append(kind)
        return [None] * len(rows)

    fake = SimpleNamespace(
        limits=SimpleNamespace(batch=4, result_bytes=1024),
        checkpoint_batch=lambda rows: execute("checkpoint", rows),
        finish_batch=lambda rows: execute("finish", rows),
    )

    async def delayed(function):
        results = function()
        if called[-1] == blocked_kind:
            entered.set()
            await release.wait()
        return results

    monkeypatch.setattr(lifecycle_batcher, "run_database_call", delayed)
    batcher = LifecycleBatcher(fake)
    blocked = asyncio.create_task(batcher.submit(blocked_kind, {"payload": "blocked"}))
    await asyncio.wait_for(entered.wait(), 1)
    other = "finish" if blocked_kind == "checkpoint" else "checkpoint"
    await asyncio.wait_for(batcher.submit(other, {"payload": "independent"}), 1)
    assert not blocked.done()
    closing = asyncio.create_task(batcher.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await asyncio.gather(blocked, closing)
    assert batcher._tasks == batcher._bytes == 0 and not batcher._runners


@pytest.mark.parametrize("phase", ["checkpoint", "finish"])
def test_oversized_batch_does_not_change_any_attempt(ledger, phase):
    owned = inputs(ledger)
    rows = [
        checkpoint_request(ledger, c, c.task)
        if phase == "checkpoint"
        else completion_request(ledger, c, completed(c))
        for c in owned
    ]
    ledger.limits = replace(ledger.limits, result_bytes=100)
    with pytest.raises(ValueError, match="byte budget"):
        getattr(ledger, f"{phase}_batch")(rows)
    assert ledger.stats("job-test")["inflight"] == 4
