"""Real SQL proof must recover a final profile result without repeating HTTP."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from test_execution_ledger import (  # noqa: F401 - native fixture dependencies
    claim,
    ledger_engine,
    pool,
    postgres_engine,
    submit,
    task,
)
from ultima_scraper_api import ContentType
from test_execution_ledger import (
    ledger as ledger_fixture,
)
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteCommand,
    DatabaseWriteOperation,
)
from ultima_scraper_backend.database.write_receipts import receipt_batch
from ultima_scraper_backend.job_system.ledger import StaleAttempt
from ultima_scraper_backend.job_system.ledger_batches import completion_request
from ultima_scraper_backend.job_system.ledger_runtime import (
    FencedWriter,
    LedgerTaskStorage,
    execute,
    worker_claim_capacity,
)
from ultima_scraper_backend.job_system.models import (
    Task,
    TaskRegistry,
    TaskResult,
    TaskState,
    TaskType,
)
from ultima_scraper_backend.job_system.payloads import ScrapeTaskPayload
from ultima_scraper_backend.job_system.profile_completion import PROFILE_COMPLETION_KEY

ledger = ledger_fixture


def profile_task(*, max_attempts=3):
    item = task()
    item.content_type = ContentType.PROFILE
    item.mps_task_manifest = "owned-native-mps"
    item.max_attempts = max_attempts
    item.payload = ScrapeTaskPayload(download_media=False)
    return item


def conclusive_result(operation):
    output = {"user_id": 1, "proxy_routes": ["native-route-a", "native-route-b"]}
    if operation == DatabaseWriteOperation.UPSERT_INVALID_USER:
        output["invalid_user"] = True
    else:
        output.update(
            content_type=ContentType.PROFILE.value,
            items_saved=1,
            media_urls=[],
            media_selection=None,
        )
    return TaskResult(
        success=True,
        output=output,
        message="Original conclusive outcome",
        metrics={"worker_id": "original-worker", "route_observations": 2},
    )


class NativeWrites:
    def __init__(self, ledger, *, rollback=False, lost_ack=False):
        self.ledger, self.rollback, self.lost_ack = ledger, rollback, lost_ack
        self.commands = []
        self.accepted = asyncio.Event()
        self.results = {}

    async def enqueue(self, operation, payload, **kwargs):
        command = DatabaseWriteCommand(
            command_id=kwargs["command_id"],
            operation=operation,
            site="onlyfans",
            payload=payload,
            producer_id="native-test",
            created_at=datetime.now(UTC).isoformat(),
            version=2,
            execution_attempt=kwargs["execution_attempt"],
            execution_key=kwargs["execution_key"],
        )
        command = DatabaseWriteCommand.from_json(command.to_json())
        with self.ledger.session_factory() as session:
            results = {}
            with receipt_batch(session, [command], results) as pending:
                if pending:
                    if operation == DatabaseWriteOperation.UPSERT_INVALID_USER:
                        session.execute(
                            text(
                                "INSERT INTO onlyfans.invalid_users (site,user_id,last_checked_at) VALUES ('onlyfans',1,clock_timestamp())"
                            )
                        )
                    else:
                        session.execute(
                            text("INSERT INTO onlyfans.users (id) VALUES (1)")
                        )
                    results[command.command_id] = {"saved": True}
            if self.rollback:
                raise ConnectionError("Native write rolled back before commit")
            session.commit()
        self.commands.append(command)
        self.results.update(results)
        self.accepted.set()
        return command.command_id, {}

    async def wait_for_result(self, command_id, **kwargs):
        if self.lost_ack:
            await asyncio.Future()
        return self.results[command_id]

    async def submit(self, operation, payload, **kwargs):
        identity, _ = await self.enqueue(operation, payload, **kwargs)
        return await self.wait_for_result(identity)


async def prepared_write(
    ledger,
    *,
    operation=DatabaseWriteOperation.UPSERT_USER,
    max_attempts=3,
    rollback=False,
):
    submit(ledger, [profile_task(max_attempts=max_attempts)])
    ledger.tick()
    owned = claim(ledger)
    item = Task.from_dict(owned.task)
    storage = LedgerTaskStorage(ledger, owned, item, None)
    native = NativeWrites(ledger, rollback=rollback)
    writer = FencedWriter(native, ledger, owned, storage)
    expected = conclusive_result(operation)
    writer.prepare_profile_completion(expected)
    if rollback:
        with pytest.raises(ConnectionError):
            await writer.submit(
                operation, {"user_id": 1}, site="onlyfans", command_id="final-profile"
            )
    else:
        await writer.submit(
            operation, {"user_id": 1}, site="onlyfans", command_id="final-profile"
        )
    return owned, expected, native


def expire(ledger):
    with ledger.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.execution_work SET lease_until=clock_timestamp()-interval '1 second'"
            )
        )
        session.commit()


def effects(ledger):
    with ledger.session_factory() as session:
        return {
            "users": session.scalar(text("SELECT count(*) FROM onlyfans.users")),
            "invalid": session.scalar(
                text("SELECT count(*) FROM onlyfans.invalid_users")
            ),
            "mutations": session.scalar(
                text("SELECT count(*) FROM management.execution_mutations")
            ),
            "receipts": session.scalar(
                text("SELECT count(*) FROM management.database_write_receipts")
            ),
        }


@pytest.mark.parametrize(
    "operation",
    [DatabaseWriteOperation.UPSERT_USER, DatabaseWriteOperation.UPSERT_INVALID_USER],
)
@pytest.mark.parametrize("max_attempts", [1, 3])
async def test_lease_recovery_uses_committed_result_even_at_attempt_limit(
    ledger, operation, max_attempts
):
    owned, expected, native = await prepared_write(
        ledger, operation=operation, max_attempts=max_attempts
    )
    assert ledger.task("job-test", "task-a")["state"] == "saving_db"
    expire(ledger)
    assert ledger.recover_expired() == 1
    recovered = ledger.task("job-test", "task-a")
    assert recovered["state"] == "completed"
    for field in ("output", "message", "metrics", "errors"):
        assert recovered["result"][field] == expected.to_dict()[field]
    assert claim(ledger) is None
    assert [a["state"] for a in ledger.attempts("job-test")] == ["completed"]
    assert effects(ledger) == {
        "users": int(operation == DatabaseWriteOperation.UPSERT_USER),
        "invalid": int(operation == DatabaseWriteOperation.UPSERT_INVALID_USER),
        "mutations": 1,
        "receipts": 1,
    }
    assert len(native.commands) == 1
    with pytest.raises(StaleAttempt):
        ledger.renew(owned)
    assert ledger.archive_tick() == "job-test"
    with ledger.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.execution_work WHERE run_id='job-test'"
                )
            )
            == 0
        )


async def test_rollback_does_not_make_prepared_result_terminal(ledger):
    owned, _, _ = await prepared_write(ledger, rollback=True)
    assert PROFILE_COMPLETION_KEY in owned.task
    assert ledger.profile_completion(owned) is None
    expire(ledger)
    assert ledger.recover_expired() == 1
    assert ledger.task("job-test", "task-a")["state"] == "pending"
    assert claim(ledger).number == 2
    assert effects(ledger) == {"users": 0, "invalid": 0, "mutations": 0, "receipts": 0}


@pytest.mark.parametrize("batch", [False, True])
async def test_retry_preserves_checkpoint_and_skips_handler(ledger, monkeypatch, batch):
    owned, expected, _ = await prepared_write(ledger)
    item = Task.from_dict(owned.task)
    item.state = TaskState.FAILED
    item.result = TaskResult(success=False, message="Acknowledgement lost")
    if batch:
        assert ledger.finish_batch(
            [completion_request(ledger, owned, item, retry=True)]
        ) == [None]
    else:
        ledger.finish(owned, item, retry=True)
    with ledger.session_factory() as session:
        session.execute(
            text("UPDATE management.execution_work SET available_at=clock_timestamp()")
        )
        session.commit()
    replacement = claim(ledger)
    assert replacement.number == 2 and PROFILE_COMPLETION_KEY in replacement.task

    async def must_not_repeat_http(*args, **kwargs):
        pytest.fail("A committed profile outcome repeated its upstream handler")

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, must_not_repeat_http)
    worker = pool()
    await execute(worker, ledger, replacement)
    assert ledger.task("job-test", "task-a")["result"]["output"] == expected.output
    assert [a["state"] for a in ledger.attempts("job-test")] == ["failed", "completed"]
    worker._ensure_auth_loaded_for_task.assert_not_awaited()
    worker._refresh_storage_config_before_task.assert_not_awaited()
    assert effects(ledger)["mutations"] == effects(ledger)["receipts"] == 1


async def test_cancellation_and_run_lock_precede_receipt_reconciliation(ledger):
    await prepared_write(ledger)
    expire(ledger)
    with ledger.session_factory() as control:
        control.execute(
            text(
                "SELECT run_id FROM management.execution_runs WHERE run_id='job-test' FOR UPDATE"
            )
        )
        # A control already owns the run fence: recovery must skip it.
        assert ledger.recover_expired() == 0
    ledger.control("job-test", "cancel")
    assert ledger.recover_expired() == 0
    assert ledger.task("job-test", "task-a")["state"] == "cancelled"
    assert claim(ledger) is None
    assert effects(ledger)["mutations"] == 1


async def test_profile_intent_obeys_existing_byte_budget_before_mutation(ledger):
    submit(ledger, [profile_task()])
    ledger.tick()
    owned = claim(ledger)
    item = Task.from_dict(owned.task)
    ledger.limits = replace(ledger.limits, result_bytes=2048)
    native = NativeWrites(ledger)
    writer = FencedWriter(
        native, ledger, owned, LedgerTaskStorage(ledger, owned, item, None)
    )
    result = conclusive_result(DatabaseWriteOperation.UPSERT_USER)
    result.output["large_detail"] = "x" * 4096
    writer.prepare_profile_completion(result)
    with pytest.raises(ValueError, match="payload budget"):
        await writer.submit(
            DatabaseWriteOperation.UPSERT_USER, {"user_id": 1}, site="onlyfans"
        )
    assert not native.commands
    assert effects(ledger)["mutations"] == 0


@pytest.mark.parametrize("missing", ["mutation", "receipt", "wrong_key"])
async def test_checkpoint_requires_matching_mutation_and_receipt(ledger, missing):
    owned, _, _ = await prepared_write(ledger)
    with ledger.session_factory() as session:
        if missing == "mutation":
            session.execute(text("DELETE FROM management.execution_mutations"))
        elif missing == "receipt":
            session.execute(text("DELETE FROM management.database_write_receipts"))
        else:
            owned.task[PROFILE_COMPLETION_KEY]["execution_key"] = (
                "uncommitted-logical-write"
            )
        session.commit()
    assert ledger.profile_completion(owned) is None


@pytest.mark.parametrize("from_job_metadata", [False, True])
async def test_post_commit_acknowledgement_error_recovers_same_attempt(
    ledger, monkeypatch, from_job_metadata
):
    native = NativeWrites(ledger)

    async def failed_ack(command_id, **kwargs):
        raise ConnectionError("Committed acknowledgement was lost")

    native.wait_for_result = failed_ack
    worker = pool()
    worker.database_writes = native
    expected = conclusive_result(DatabaseWriteOperation.UPSERT_USER)

    async def handler(item, context):
        context.context["prepare_profile_completion"](expected)
        await context.database_writes.submit(
            DatabaseWriteOperation.UPSERT_USER,
            {"user_id": 1},
            site="onlyfans",
            command_id="final-profile",
        )
        return expected

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, handler)
    item = profile_task()
    if from_job_metadata:
        item.mps_task_manifest = None
    submit(ledger, [item])
    ledger.tick()
    owned = claim(ledger)
    if from_job_metadata:
        owned.job.setdefault("metadata", {})["mps_manifest"] = True
    await execute(worker, ledger, owned)
    assert ledger.task("job-test", "task-a")["state"] == "completed"
    assert ledger.task("job-test", "task-a")["result"]["output"] == expected.output
    assert [a["state"] for a in ledger.attempts("job-test")] == ["completed"]
    assert effects(ledger)["mutations"] == effects(ledger)["receipts"] == 1


async def test_declared_final_profile_boundary_rejects_a_second_write(
    ledger, monkeypatch
):
    native = NativeWrites(ledger)
    worker = pool()
    worker.database_writes = native
    expected = conclusive_result(DatabaseWriteOperation.UPSERT_USER)

    async def handler(item, context):
        context.context["prepare_profile_completion"](expected)
        await context.database_writes.submit(
            DatabaseWriteOperation.UPSERT_USER,
            {"user_id": 1},
            site="onlyfans",
            command_id="final-profile",
        )
        with pytest.raises(ValueError, match="only one write"):
            await context.database_writes.submit(
                DatabaseWriteOperation.UPSERT_USER,
                {"user_id": 1},
                site="onlyfans",
                command_id="unexpected-second-write",
            )
        return expected

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, handler)
    submit(ledger, [profile_task()])
    ledger.tick()
    await execute(worker, ledger, claim(ledger))
    assert ledger.task("job-test", "task-a")["state"] == "completed"
    assert len(native.commands) == 1
    assert effects(ledger)["mutations"] == effects(ledger)["receipts"] == 1


async def test_canonical_profile_releases_fetch_slot_during_pending_write(
    ledger, monkeypatch
):
    native = NativeWrites(ledger)
    worker = pool()
    worker.database_writes = native
    acknowledged = asyncio.Event()
    expected = conclusive_result(DatabaseWriteOperation.UPSERT_USER)

    async def wait_for_ack(command_id, **kwargs):
        await acknowledged.wait()
        return native.results[command_id]

    native.wait_for_result = wait_for_ack

    async def handler(item, context):
        callback = context.context.get("prepare_profile_completion")
        if callback is not None:
            callback(expected)
        context.context["release_fetch_capacity"]()
        await context.database_writes.submit(
            DatabaseWriteOperation.UPSERT_USER,
            {"user_id": 1},
            site="onlyfans",
            command_id="final-profile",
        )
        return expected

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, handler)
    submit(ledger, [profile_task()])
    ledger.tick()
    running = asyncio.create_task(execute(worker, ledger, claim(ledger)))
    try:
        await asyncio.wait_for(native.accepted.wait(), 2)
        assert ("job-test", "task-a") in worker._ledger_persisting_tasks
        assert worker_claim_capacity(worker, 1, 1, 1) == (1, 2)
    finally:
        acknowledged.set()
        await asyncio.wait_for(running, 2)
    assert not worker._ledger_persisting_tasks
    assert ledger.task("job-test", "task-a")["state"] == "completed"


@pytest.mark.parametrize("flag", ["non_mps", "download", "paid", "subtask"])
async def test_generic_or_multi_stage_tasks_do_not_declare_final_profile(ledger, flag):
    item = profile_task()
    if flag == "non_mps":
        item.mps_task_manifest = None
    elif flag == "download":
        item.payload.download_media = True
    elif flag == "paid":
        item.payload.paid_content_feed = True
    else:
        item.subtasks = [task("child")]
    owned = SimpleNamespace(task={})
    writer = FencedWriter(None, ledger, owned, SimpleNamespace(task=item))
    writer.prepare_profile_completion(
        conclusive_result(DatabaseWriteOperation.UPSERT_USER)
    )
    assert writer._profile_result is None


@pytest.mark.parametrize(
    "operation",
    [DatabaseWriteOperation.UPSERT_USER, DatabaseWriteOperation.UPSERT_INVALID_USER],
)
async def test_lost_ack_and_heartbeat_outage_does_not_repeat_profile_lookup(
    ledger, monkeypatch, operation
):
    ledger.limits = replace(ledger.limits, lease_seconds=0.3)
    native = NativeWrites(ledger, lost_ack=True)
    worker = pool()
    worker.database_writes = native
    expected = conclusive_result(operation)
    calls = []

    async def handler(item, context):
        calls.append(item.task_id)
        callback = context.context.get("prepare_profile_completion")
        if callback is not None:
            callback(expected)
        await context.database_writes.submit(
            operation, {"user_id": 1}, site="onlyfans", command_id="final-profile"
        )
        return expected

    original = ledger.renew

    def unavailable(owned):
        if native.accepted.is_set():
            raise OperationalError(
                None, None, psycopg.errors.ProtocolViolation("server conn crashed?")
            )
        return original(owned)

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.SCRAPE, handler)
    monkeypatch.setattr(ledger, "renew", unavailable)
    submit(ledger, [profile_task()])
    ledger.tick()
    owned = claim(ledger)
    with pytest.raises(OperationalError):
        await execute(worker, ledger, owned)
    assert effects(ledger)["mutations"] == effects(ledger)["receipts"] == 1
    monkeypatch.setattr(ledger, "renew", original)
    expire(ledger)
    assert ledger.recover_expired() == 1
    assert ledger.task("job-test", "task-a")["state"] == "completed"
    assert calls == ["task-a"] and claim(ledger) is None
    assert effects(ledger)["mutations"] == effects(ledger)["receipts"] == 1
