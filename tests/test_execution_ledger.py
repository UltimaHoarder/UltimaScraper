"""Real SQL execution/recovery tests against an owned empty PostgreSQL cluster."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import ultima_scraper_db_archive
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from test_mps_manifest import postgres_engine  # noqa: F401
from ultima_scraper_backend.database.task_admission import create_task_plan
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteCommand,
    DatabaseWriteOperation,
)
from ultima_scraper_backend.database.write_receipts import receipt_batch
from ultima_scraper_backend.database.receipt_retention import ReceiptQueueSnapshot
from ultima_scraper_backend.job_system.ledger import (
    ExecutionLedger,
    Limits,
    StaleAttempt,
    validate_write_attempt,
)
from ultima_scraper_backend.job_system.models import (
    Job,
    Task,
    TaskRegistry,
    TaskResult,
    TaskState,
    TaskType,
)
from ultima_scraper_db_archive.execution_models import (
    EXECUTION_MODELS,
    ExecutionDefinitionModel,
    ExecutionRunModel,
    ExecutionWorkModel,
)


@pytest.fixture(scope="module")
def ledger_engine(postgres_engine):  # noqa: F811 - imported pytest fixture
    migration_path = (
        Path(ultima_scraper_db_archive.__file__).parent / "migrations/alembic/versions/f6b83a9021c4_add_execution_ledger.py"
    )
    spec = importlib.util.spec_from_file_location("ledger_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with postgres_engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
            index_path = migration_path.with_name(
                "c7d2e84a19b6_index_execution_claim_order.py"
            )
            index_spec = importlib.util.spec_from_file_location(
                "ledger_claim_index_migration", index_path
            )
            index_migration = importlib.util.module_from_spec(index_spec)
            index_spec.loader.exec_module(index_migration)
            index_migration.upgrade()
            index_migration.downgrade()
            index_migration.upgrade()
            queue_path = migration_path.with_name("9e7c3a1d6b20_narrow_execution_queue.py")
            queue_spec = importlib.util.spec_from_file_location("ledger_queue_migration", queue_path)
            queue_migration = importlib.util.module_from_spec(queue_spec)
            queue_spec.loader.exec_module(queue_migration)
            queue_migration.upgrade()
        from ultima_scraper_db_archive.global_db import (
            TaskMediaPlanModel, TaskMediaSelectionModel, TaskMediaEvidenceModel,
        )
        for model in (TaskMediaPlanModel, TaskMediaSelectionModel, TaskMediaEvidenceModel):
            model.__table__.create(connection, checkfirst=True)
        for model in EXECUTION_MODELS:
            assert connection.dialect.has_table(
                connection, model.__tablename__, schema="management"
            )
    return postgres_engine


@pytest.fixture
def ledger(ledger_engine, monkeypatch):
    monkeypatch.delenv("ULTIMA_JOB_ENGINE", raising=False)
    with ledger_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE management.execution_outbox, management.execution_resources, management.execution_attempts, management.execution_work, management.execution_runs, management.execution_definitions, management.mps_retry_tasks, management.mps_task_definitions, management.mps_candidate_ranges, management.mps_plans, management.job_tasks, management.jobs, management.database_write_receipts CASCADE"
            )
        )
        connection.execute(text("UPDATE management.execution_feed SET next_sequence=1"))
        connection.execute(text("TRUNCATE onlyfans.users, onlyfans.invalid_users"))

    @contextmanager
    def sessions():
        with Session(ledger_engine) as session:
            session.execute(text("SET LOCAL search_path=onlyfans,management,public"))
            yield session

    return ExecutionLedger(sessions, limits=Limits(tasks=4, global_tasks=8, batch=4))


def task(identity="task-a", *, kind=TaskType.SCRAPE, dependencies=(), user_id=1):
    return Task(
        task_id=identity,
        user_id=user_id,
        task_type=kind,
        site_name="onlyfans",
        depends_on=list(dependencies),
        capabilities=["onlyfans"],
    )


def submit(ledger, tasks, *, identity="job-test", schedule=None):
    job = Job.create(name="Ledger test", created_by="test", tasks=[])
    job.job_id = identity
    if schedule:
        job.schedule.scheduled_for = schedule
    with ledger.session_factory() as session:
        config = create_task_plan(
            session,
            job_id=identity,
            job_type="test",
            site="onlyfans",
            job_config=job.to_dict(),
            args_payload={},
            tasks=tasks,
            batch_size=4,
            max_bytes=65536,
        )
        session.commit()
    return config


def claim(ledger, owner="worker-a", **kwargs):
    return ledger.claim(
        owner=owner,
        backend_id="backend-a",
        capabilities=["onlyfans", "api_commands"],
        **kwargs,
    )


def finish(ledger, owned, *, success=True, children=()):
    item = Task.from_dict(owned.task)
    item.state = TaskState.COMPLETED if success else TaskState.FAILED
    item.result = TaskResult(
        success=success, output={"value": 7}, new_tasks=list(children)
    )
    item.completed_at = item.result.completed_at
    ledger.finish(owned, item)
    return item


def test_admission_claim_completion_archive_and_receipt_replay(ledger):
    config = submit(ledger, [task()])
    assert config["metadata"]["execution_engine"] == "ledger"
    assert ledger.tick() == "job-test"
    owned = claim(ledger)
    assert owned.number == 1
    assert claim(ledger, "worker-b") is None
    item = finish(ledger, owned)
    ledger.finish(owned, item)
    assert ledger.stats("job-test")["completed"] == 1
    ledger.tick()
    assert ledger.job("job-test")["state"] == "completed"
    assert ledger.task("job-test", item.task_id)["result"]["output"] == {"value": 7}
    assert ledger.stats("job-test")["total"] == 1


def test_expired_attempt_cannot_finish_renew_or_write(ledger):
    submit(ledger, [task()])
    ledger.tick()
    old = claim(ledger)
    with ledger.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.execution_work SET lease_until=clock_timestamp()-interval '1 second'"
            )
        )
        session.execute(
            text(
                "UPDATE management.execution_resources SET lease_until=clock_timestamp()-interval '1 second'"
            )
        )
        session.commit()
    assert ledger.recover_expired() == 1
    new = claim(ledger, "worker-b")
    assert new.number == 2 and new.token != old.token
    with pytest.raises(StaleAttempt):
        ledger.renew(old)
    with pytest.raises(StaleAttempt):
        finish(ledger, old)
    with ledger.session_factory() as session, pytest.raises(StaleAttempt):
        validate_write_attempt(
            session,
            {key: getattr(old, key) for key in ("run_id", "task_id", "token", "owner")},
        )
    finish(ledger, new)
    ledger.tick()
    assert [row["state"] for row in ledger.attempts("job-test")] == [
        "expired",
        "completed",
    ]


def test_concurrent_claims_have_distinct_ownership(ledger):
    submit(ledger, [task(f"task-{index}", user_id=index + 1) for index in range(4)])
    ledger.tick()
    with ThreadPoolExecutor(max_workers=4) as executor:
        first = list(
            executor.map(lambda index: claim(ledger, f"worker-{index}"), range(4))
        )
    obtained = [row for row in first if row is not None]
    while len(obtained) < 4:
        row = claim(ledger, f"worker-{len(obtained)}")
        assert row is not None
        obtained.append(row)
    assert len({row.task_id for row in obtained}) == 4
    assert len({row.token for row in obtained}) == 4


@pytest.mark.parametrize('complete_last_attempt', [False, True])
def test_profile_command_survives_two_lost_workers_with_bounded_budget(ledger, complete_last_attempt):
    from ultima_scraper_backend.job_system.api_command_policy import PROFILE_REFRESH_MAX_ATTEMPTS
    from ultima_scraper_backend.job_system.payloads import APICommandTaskPayload

    item = task(kind=TaskType.API_COMMAND)
    item.payload = APICommandTaskPayload(command='refresh_profile', args={'user_id': 1})
    item.max_attempts = PROFILE_REFRESH_MAX_ATTEMPTS
    submit(ledger, [item])
    ledger.tick()
    for number in range(1, 4):
        owned = claim(ledger, f'worker-{number}')
        assert owned.number == number
        if number == 3 and complete_last_attempt:
            finish(ledger, owned)
            break
        with ledger.session_factory() as session:
            session.execute(text("UPDATE management.execution_work SET lease_until=clock_timestamp()-interval '1 second'"))
            session.commit()
        assert ledger.recover_expired() == 1
        with pytest.raises(StaleAttempt):
            ledger.renew(owned)
    ledger.tick()
    assert ledger.job('job-test')['state'] == ('completed' if complete_last_attempt else 'failed')
    assert len(ledger.attempts('job-test')) == 3
    assert claim(ledger) is None
    if not complete_last_attempt:
        assert ledger.task('job-test', item.task_id)['result']['output']['error_code'] == 'worker_lease_expired'


def test_shared_deduplication_across_runs(ledger):
    submit(ledger, [task()], identity="job-a")
    submit(ledger, [task("task-b")], identity="job-b")
    ledger.tick()
    ledger.tick()
    first = claim(ledger)
    assert claim(ledger, "worker-b") is None
    finish(ledger, first)
    assert claim(ledger, "worker-b") is not None


def test_running_claims_share_the_run_fence_with_active_writers(ledger):
    submit(ledger, [task(f"task-{i}", user_id=i + 1) for i in range(4)])
    ledger.tick()
    first = claim(ledger)
    with ledger.session_factory() as writing:
        validate_write_attempt(
            writing,
            {
                key: getattr(first, key)
                for key in ("run_id", "task_id", "token", "owner")
            },
        )
        remaining = ledger.claim_many(
            owner="worker-b", backend_id="backend-a", capabilities=["onlyfans"], count=3
        )
        assert len(remaining) == 3
        assert len({row.token for row in remaining}) == 3


def test_claim_batch_preserves_deduplication_and_revocation(ledger):
    inputs = [task(f"task-{i}", user_id=i + 1) for i in range(4)]
    inputs[1].user_id = inputs[0].user_id
    submit(ledger, inputs)
    ledger.tick()
    batch = ledger.claim_many(
        owner="worker-a", backend_id="backend-a", capabilities=["onlyfans"], count=4
    )
    assert len(batch) == 3
    assert ledger.stats("job-test")["inflight"] == 3
    ledger.control("job-test", "cancel")
    for owned in batch:
        with pytest.raises(StaleAttempt):
            finish(ledger, owned)


def test_pause_stops_new_claims_and_cancel_revokes_running_attempt(ledger):
    submit(ledger, [task("task-a"), task("task-b", user_id=2)])
    ledger.tick()
    first = claim(ledger)
    ledger.control("job-test", "pause")
    assert claim(ledger, "worker-b") is None
    assert ledger.renew(first)
    ledger.control("job-test", "resume")
    assert claim(ledger, "worker-b") is not None
    ledger.control("job-test", "cancel")
    with pytest.raises(StaleAttempt):
        finish(ledger, first)
    assert ledger.job("job-test")["state"] == "cancelled"
    assert ledger.tick() is None


def test_spawned_definitions_and_dependencies_commit_before_admission(ledger):
    submit(ledger, [task("task-parent")])
    ledger.tick()
    parent = claim(ledger)
    finish(
        ledger,
        parent,
        children=[task("task-child", dependencies=["task-parent"], user_id=2)],
    )
    assert claim(ledger) is None
    ledger.tick()
    child = claim(ledger)
    assert child.task_id == "task-child"
    assert ledger.output("job-test", "task-parent") == {"value": 7}
    finish(ledger, child)
    ledger.tick()
    assert ledger.stats("job-test")["total"] == 2
    assert ledger.stats("job-test")["completed"] == 2


def test_failed_dependency_is_terminal_without_handler_execution(ledger):
    submit(
        ledger,
        [
            task("task-parent"),
            task("task-child", dependencies=["task-parent"], user_id=2),
        ],
    )
    ledger.tick()
    finish(ledger, claim(ledger), success=False)
    ledger.tick()
    assert claim(ledger) is None
    ledger.tick()
    assert ledger.stats("job-test")["failed"] == 2


def test_scheduled_inputs_wait_for_due_time(ledger):
    submit(ledger, [task()], schedule="2099-01-01T00:00:00+00:00")
    assert ledger.tick() is None
    assert claim(ledger) is None


def test_interactive_lane_and_capabilities(ledger):
    submit(
        ledger,
        [
            task("task-bulk", user_id=1),
            task("task-api", kind=TaskType.API_COMMAND, user_id=2),
        ],
    )
    ledger.tick()
    assert claim(ledger, lane="interactive").task_id == "task-api"
    assert (
        ledger.claim(
            owner="wrong-site", backend_id="backend-a", capabilities=["fansly"]
        )
        is None
    )


def test_transactional_outbox_rollback_and_replay(ledger):
    submit(ledger, [task()])
    received = []

    def failed(payload):
        received.append(payload)
        raise ConnectionError("relay disconnected")

    with pytest.raises(ConnectionError):
        ledger.relay(failed)
    assert ledger.events() == []
    assert ledger.relay(received.append) == 1
    assert received[0]["event_id"] == received[1]["event_id"]
    assert [row["sequence"] for row in ledger.events()] == [1]
    assert ledger.relay(received.append) == 0


def test_batch_outbox_publication_rolls_back_and_replays_in_order(ledger):
    # Job-level events are the durable ones; task events are published live.
    for index in range(4):
        submit(ledger, [task(f"task-{index}", user_id=index + 1)], identity=f"job-{index}")
    batches = []

    def failed(payloads):
        batches.append(payloads)
        raise ConnectionError("partially published pipeline")

    with pytest.raises(ConnectionError):
        ledger.relay(publish_many=failed)
    assert ledger.event_head() == 0
    assert ledger.events() == []
    assert ledger.relay(publish_many=batches.append) == 4
    assert len(batches) == 2
    assert batches[0] == batches[1]
    assert [row["sequence"] for row in ledger.events()] == [1, 2, 3, 4]
    assert ledger.relay(publish_many=batches.append) == 0


def test_planner_can_prepare_refill_during_an_active_writer_fence(ledger, monkeypatch):
    from threading import Event

    submit(ledger, [task(f"task-{index}", user_id=index + 1) for index in range(12)])
    ledger.tick()
    owned = claim(ledger)
    ledger.limits = replace(ledger.limits, tasks=8, global_tasks=16)
    preparing = Event()
    original = ledger._source_page

    def source_page(*args, **kwargs):
        preparing.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(ledger, "_source_page", source_page)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with ledger.session_factory() as session:
            validate_write_attempt(
                session,
                {
                    key: getattr(owned, key)
                    for key in ("run_id", "task_id", "token", "owner")
                },
            )
            pending = executor.submit(ledger.tick)
            reached = preparing.wait(2)
            result = pending.result(timeout=2)
            session.commit()
        assert result == "job-test"
        assert reached, "The planner skipped a run while its writer was active"
    assert ledger.stats("job-test")["ready"] == 7
    assert ledger.stats("job-test")["inflight"] == 1


def test_existing_run_claim_carries_exact_total_for_steady_telemetry(ledger):
    submit(ledger, [task(f"task-{index}", user_id=index + 1) for index in range(12)])
    ledger.tick()
    with ledger.session_factory() as session:
        run = session.get(ExecutionRunModel, "job-test")
        config = json.loads(run.config_json)
        config["metadata"].pop("total_tasks_count_override", None)
        run.config_json = json.dumps(config)
        session.commit()
    assert Job.from_dict(claim(ledger).job).total_tasks == 12


def test_persisted_windows_apply_live_with_one_planner_connection(
    ledger, ledger_engine, monkeypatch
):
    from ultima_scraper_db_archive.global_db import BackendInventoryModel, SettingsModel

    from ultima_scraper_backend import config_settings_sync

    monkeypatch.setenv("ULTIMA_LEDGER_PLANNER_BATCH", "128")

    for name in (
        "ULTIMA_LEDGER_TASKS",
        "ULTIMA_LEDGER_GLOBAL_TASKS",
        "ULTIMA_LEDGER_BYTES",
        "ULTIMA_LEDGER_GLOBAL_BYTES",
        "ULTIMA_JOB_WINDOW_MAX_TASKS",
        "ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS",
        "ULTIMA_JOB_WINDOW_MAX_BYTES",
        "ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("BACKEND_ID", "ledger-window-test")
    SettingsModel.__table__.create(ledger_engine, checkfirst=True)
    BackendInventoryModel.__table__.create(ledger_engine, checkfirst=True)
    with Session(ledger_engine) as session:
        host = SettingsModel(
            backend="ledger-window-test",
            key="config",
            value=json.dumps(
                {
                    "settings": {"job_execution": {"window_max_tasks": 100}},
                }
            ),
        )
        shared = SettingsModel(
            backend="ledger-window-shared",
            key="config",
            value=json.dumps(
                {
                    "settings": {"job_execution": {"window_max_tasks": 20000}},
                }
            ),
        )
        session.add_all([host, shared])
        session.flush()
        shared_id = shared.id
        session.add(
            BackendInventoryModel(
                backend_name="Window test",
                hostname="ledger-window-test",
                settings_id=shared_id,
            )
        )
        session.commit()
    job = Job.create(name="MPS window", created_by="test", tasks=[])
    ledger.manifests.create(
        job_id=job.job_id,
        site="onlyfans",
        job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": 50000, "max_profiles": None},
        proxy_pool=[],
        site_session_factory=ledger.session_factory,
    )
    nested = Mock(
        side_effect=AssertionError("Window config requested a second connection")
    )
    monkeypatch.setattr(config_settings_sync, "get_global_session", nested)
    engine = create_engine(
        ledger_engine.url, pool_size=1, max_overflow=0, pool_timeout=0.1
    )
    checkouts = []
    event.listen(engine, "checkout", lambda *args: checkouts.append(True))

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    planner = ExecutionLedger(sessions)
    try:
        observations = []
        for _ in range(3):
            assert planner.tick(diagnostics=observations) == job.job_id
        assert len(checkouts) == 3
        assert ledger.stats(job.job_id)["ready"] == 384
        assert observations[-1]["controls"]["window_tasks"] == 20000
        assert observations[-1]["controls"]["global_tasks"] == 20000
        assert observations[-1]["controls"]["resident_tasks"] == 384
        nested.assert_not_called()
        with Session(ledger_engine) as session:
            row = session.get(SettingsModel, shared_id)
            row.value = json.dumps(
                {"settings": {"job_execution": {"window_max_tasks": 500}}}
            )
            session.commit()
        assert planner.tick() == job.job_id
        assert ledger.stats(job.job_id)["ready"] == 500
        assert planner.tick() is None
        monkeypatch.setenv("ULTIMA_LEDGER_TASKS", "600")
        monkeypatch.setenv("ULTIMA_LEDGER_GLOBAL_TASKS", "600")
        assert planner.tick() == job.job_id
        assert ledger.stats(job.job_id)["ready"] == 600
        # The existing environment controls take precedence over saved controls.
        monkeypatch.setenv("ULTIMA_LEDGER_TASKS", "")
        monkeypatch.setenv("ULTIMA_LEDGER_GLOBAL_TASKS", "")
        monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "700")
        assert planner.tick() == job.job_id
        assert ledger.stats(job.job_id)["ready"] == 700
    finally:
        engine.dispose()


def test_guarded_writer_envelope_and_receipt_transaction(ledger):
    submit(ledger, [task()])
    ledger.tick()
    owned = claim(ledger)
    identity = {
        key: getattr(owned, key) for key in ("run_id", "task_id", "token", "owner")
    }
    command = DatabaseWriteCommand(
        command_id="guarded-command",
        operation=DatabaseWriteOperation.UPSERT_USER,
        site="onlyfans",
        payload={},
        producer_id="test",
        created_at=datetime.now(UTC).isoformat(),
        version=2,
        execution_attempt=identity,
    )
    assert DatabaseWriteCommand.from_json(command.to_json()) == command
    results = {}
    with ledger.session_factory() as session:
        with receipt_batch(session, [command], results) as pending:
            assert pending == [command]
            session.execute(text("INSERT INTO onlyfans.users (id) VALUES (11)"))
            results[command.command_id] = {"saved": True}
        session.commit()
    ledger.control("job-test", "cancel")
    # Previously committed writes may replay their receipt after cancellation.
    with (
        ledger.session_factory() as session,
        receipt_batch(session, [command], {}) as pending,
    ):
        assert pending == []
    stale = replace(command, command_id="another-command")
    with (
        ledger.session_factory() as session,
        pytest.raises(StaleAttempt),
        receipt_batch(session, [stale], {}),
    ):
        pytest.fail("A revoked writer reached its mutation")


def test_committed_mutation_replays_across_replacement_attempts(ledger):
    submit(ledger, [task()])
    ledger.tick()
    old = claim(ledger)
    identity = {
        key: getattr(old, key) for key in ("run_id", "task_id", "token", "owner")
    }
    command = DatabaseWriteCommand(
        command_id="old-transport",
        operation=DatabaseWriteOperation.UPSERT_USER,
        site="onlyfans",
        payload={},
        producer_id="test",
        created_at=datetime.now(UTC).isoformat(),
        version=2,
        execution_attempt=identity,
        execution_key="logical-profile-save",
    )
    assert DatabaseWriteCommand.from_json(command.to_json()) == command
    results = {}
    with ledger.session_factory() as session:
        with receipt_batch(session, [command], results) as pending:
            assert pending == [command]
            session.execute(text("INSERT INTO onlyfans.users (id) VALUES (21)"))
            results[command.command_id] = {"saved": True}
        session.commit()
    with ledger.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.execution_work SET lease_until=clock_timestamp()-interval '1 second'"
            )
        )
        session.commit()
    ledger.recover_expired()
    new = claim(ledger)
    assert new.number == 2
    replay = replace(
        command,
        command_id="new-transport",
        execution_attempt={
            key: getattr(new, key) for key in ("run_id", "task_id", "token", "owner")
        },
    )
    results = {}
    with ledger.session_factory() as session:
        with receipt_batch(session, [replay], results) as pending:
            assert pending == []
        session.commit()
        assert (
            session.scalar(text("SELECT count(*) FROM onlyfans.users WHERE id=21")) == 1
        )
    assert results[replay.command_id] == {"saved": True}
    with ledger.session_factory() as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.database_write_receipts WHERE command_id='new-transport'"
                )
            )
            == 1
        )


def test_exact_mps_plan_executes_in_bounded_windows(ledger):
    job = Job.create(
        name="MPS", created_by="test", tasks=[], metadata={"mps_manifest": True}
    )
    plan = ledger.manifests.create(
        job_id=job.job_id,
        site="onlyfans",
        job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": 1000000, "max_profiles": None},
        proxy_pool=[],
        site_session_factory=ledger.session_factory,
    )
    assert plan["total"] == 1000000
    ledger.tick()
    assert ledger.stats(job.job_id)["total"] == 1000000
    assert ledger.stats(job.job_id)["ready"] == 4
    with ledger.session_factory() as session:
        assert len(list(session.execute(select(ExecutionWorkModel)).scalars())) == 4
    owned = claim(ledger)
    finish(ledger, owned)
    ledger.tick()
    retained = ledger.task(job.job_id, owned.task_id)
    assert retained["content_type"] == owned.task["content_type"]
    assert retained["payload"] == owned.task["payload"]
    assert retained["result"]["output"] == {"value": 7}


def test_mps_geo_refresh_uses_planner_connection_with_one_connection_pool(
    ledger, ledger_engine, monkeypatch
):
    from ultima_scraper_backend.job_system import mps_tasks
    from ultima_scraper_db_archive import global_db

    proxies = [
        "http://us.example:8080",
        "http://gb.example:8080",
        "http://de.example:8080",
    ]
    geo = dict(zip(proxies, ["US", "GB", "DE"]))
    model = global_db.ProxyGeolocationModel
    model.__table__.create(ledger_engine, checkfirst=True)
    with ledger_engine.begin() as connection:
        connection.execute(model.__table__.delete())
        connection.execute(
            model.__table__.insert(),
            [
                {
                    "ip": f"203.0.113.{index + 1}",
                    "proxy_url": proxy,
                    "country_code": country,
                }
                for index, (proxy, country) in enumerate(geo.items())
            ],
        )
    job = Job.create(name="MPS", created_by="test", tasks=[])
    ledger.manifests.create(
        job_id=job.job_id,
        site="onlyfans",
        job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": 8, "max_profiles": None},
        proxy_pool=proxies,
        site_session_factory=ledger.session_factory,
    )
    nested_checkouts = []

    def forbid_nested_checkout():
        nested_checkouts.append(True)
        raise AssertionError("Geo refresh borrowed another database connection")

    monkeypatch.setattr(global_db, "get_global_session", forbid_nested_checkout)
    monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP", {})
    monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP_AT", 0.0)
    engine = create_engine(
        ledger_engine.url, pool_size=1, max_overflow=0, pool_timeout=0.1
    )
    checkouts, geo_queries = [], []
    event.listen(engine, "checkout", lambda *args: checkouts.append(True))

    def record_sql(connection, cursor, statement, parameters, context, executemany):
        if "FROM management.proxy_geolocation" in statement:
            geo_queries.append(True)

    event.listen(engine, "before_cursor_execute", record_sql)

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    planner = ExecutionLedger(sessions, limits=ledger.limits)
    try:
        assert planner.tick() == job.job_id
        assert len(checkouts) == 1
        assert len(geo_queries) == 1
        assert nested_checkouts == []
        with ledger.session_factory() as session:
            actual = [
                json.loads(row.payload_json)
                for row in session.scalars(
                    select(ExecutionWorkModel).order_by(ExecutionWorkModel.candidate)
                )
            ]
        expected = mps_tasks._build_mps_task_batch(
            job_id=job.job_id,
            site_display="OnlyFans",
            target_user_ids=[1, 2, 3, 4],
            proxy_pool=proxies,
            candidate_offset=0,
            proxy_geo_map=geo,
        )
        assert [row["payload"] for row in actual] == [
            row.to_dict()["payload"] for row in expected
        ]
        for index in range(4):
            finish(
                ledger,
                claim(ledger),
                children=[task("task-child", user_id=9)] if index == 0 else (),
            )
        # Expiry must also be safe while archiving and refilling an active run.
        monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP_AT", 0.0)
        checkouts.clear()
        geo_queries.clear()
        assert planner.tick() == job.job_id
        assert len(checkouts) == 1
        assert len(geo_queries) == 1
        assert nested_checkouts == []
        assert ledger.stats(job.job_id)["completed"] == 4
        assert ledger.stats(job.job_id)["ready"] == 4
        # A hybrid retry rebuilds candidate tasks inside another locked SQL
        # transaction and must follow the same connection ownership rule.
        retry = planner.retry(job.job_id)
        monkeypatch.setattr(mps_tasks, "_CACHED_GEO_MAP_AT", 0.0)
        checkouts.clear()
        geo_queries.clear()
        assert planner.tick() == retry["job_id"]
        assert len(checkouts) == 1
        assert len(geo_queries) == 1
        assert nested_checkouts == []
    finally:
        engine.dispose()


def test_cancel_archives_committed_result_and_its_child_count(ledger):
    submit(ledger, [task()])
    ledger.tick()
    finish(ledger, claim(ledger), children=[task("task-child", user_id=2)])
    ledger.control("job-test", "cancel")
    stats = ledger.stats("job-test")
    assert (stats["total"], stats["completed"], stats["cancelled"]) == (2, 1, 1)
    assert ledger.task("job-test", "task-a")["state"] == "completed"
    assert ledger.task("job-test", "task-child")["state"] == "cancelled"


def test_metadata_edits_create_immutable_revisions(ledger):
    submit(ledger, [task()])
    original = ledger.job("job-test")
    updated = ledger.control("job-test", "update", name="Renamed", priority=-5)
    assert updated["metadata"]["execution_revision"] == 2
    assert original["name"] == "Ledger test"
    with ledger.session_factory() as session:
        definition = session.get(
            ExecutionDefinitionModel,
            (original["metadata"]["execution_definition_id"], 1),
        )
        assert '"name":"Ledger test"' in definition.config_json
    ledger.tick()
    owned = claim(ledger)
    assert owned.job["name"] == "Renamed"
    with pytest.raises(ValueError, match="started run"):
        ledger.control(
            "job-test",
            "update",
            schedule={"scheduled_for": "2099-01-01T00:00:00+00:00"},
        )


def test_retry_freezes_failures_and_has_its_own_attempt_history(ledger):
    submit(ledger, [task("task-a"), task("task-b", user_id=2)])
    ledger.tick()
    failed = claim(ledger)
    finish(ledger, failed, success=False)
    finish(ledger, claim(ledger))
    ledger.tick()
    retried = ledger.retry("job-test")
    assert retried["metadata"]["retry_of"] == "job-test"
    for _ in range(5):
        ledger.tick()
    assert ledger.stats(retried["job_id"])["total"] == 1
    owned = claim(ledger)
    assert owned.run_id == retried["job_id"] and owned.number == 1
    finish(ledger, owned)
    ledger.tick()
    assert ledger.job(retried["job_id"])["state"] == "completed"
    assert ledger.stats("job-test")["failed"] == 1


def test_retry_revokes_running_source_before_new_work_can_start(ledger):
    submit(ledger, [task()])
    ledger.tick()
    old = claim(ledger)
    retried = ledger.retry("job-test")
    with pytest.raises(StaleAttempt):
        ledger.renew(old)
    assert retried is not None
    assert ledger.job("job-test")["state"] == "cancelled"


def test_task_pages_include_unadmitted_definitions_and_have_stable_cursors(ledger):
    submit(ledger, [task(f"task-{index}", user_id=index + 1) for index in range(10)])
    ledger.tick()
    first = ledger.task_page("job-test", limit=3)
    second = ledger.task_page(
        "job-test", after=first["next_cursor"].removeprefix("ledger:"), limit=20
    )
    ids = [row["task_id"] for row in first["tasks"] + second["tasks"]]
    assert ids == [f"task-{index}" for index in range(10)]
    assert second["has_more"] is False


def test_global_window_count_and_input_bytes_are_hard_caps(ledger):
    ledger.limits = replace(ledger.limits, global_tasks=3)
    submit(
        ledger,
        [task(f"task-a-{index}", user_id=index + 1) for index in range(5)],
        identity="job-a",
    )
    submit(
        ledger,
        [task(f"task-b-{index}", user_id=index + 20) for index in range(5)],
        identity="job-b",
    )
    for _ in range(4):
        ledger.tick()
    with ledger.session_factory() as session:
        assert (
            session.scalar(text("SELECT count(*) FROM management.execution_work")) == 3
        )
        size = session.scalar(
            text("SELECT min(payload_bytes) FROM management.execution_work")
        )
    ledger.control("job-a", "cancel")
    ledger.control("job-b", "cancel")
    ledger.limits = replace(
        ledger.limits, bytes=2 * size, global_bytes=2 * size, global_tasks=8
    )
    submit(
        ledger,
        [task(f"task-c-{index}", user_id=index + 40) for index in range(5)],
        identity="job-c",
    )
    ledger.tick()
    with ledger.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT sum(payload_bytes) FROM management.execution_work")
            )
            <= 2 * size
        )


def test_global_byte_budget_refills_another_run_with_integer_diagnostics(ledger):
    ledger.limits = replace(ledger.limits, batch=1)
    submit(ledger, [task("task-a")], identity="job-a")
    submit(ledger, [task("task-b", user_id=2)], identity="job-b")
    assert ledger.tick() == "job-a"
    with ledger.session_factory() as session:
        used = session.scalar(
            text("SELECT sum(payload_bytes) FROM management.execution_work")
        )
        # PostgreSQL SUM(bigint) returns numeric, which psycopg exposes as Decimal.
        assert isinstance(used, Decimal) and used > 0
    ledger.limits = replace(
        ledger.limits, bytes=8 * int(used), global_bytes=4 * int(used)
    )
    observations = []
    assert ledger.tick(diagnostics=observations) == "job-b"
    assert ledger.stats("job-b")["ready"] == 1
    assert isinstance(observations[-1]["controls"]["global_used_bytes"], int)
    json.dumps(observations)
    with ledger.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT sum(payload_bytes) FROM management.execution_work")
            )
            <= ledger.limits.global_bytes
        )


@pytest.mark.parametrize("scope", ["run", "global"])
def test_partial_byte_budget_waits_for_space_then_refills(ledger, scope):
    ledger.limits = replace(ledger.limits, batch=2)
    first_tasks = [task("task-a"), task("task-b", user_id=2)]
    if scope == "run":
        submit(ledger, [*first_tasks, task("task-c", user_id=3)])
    else:
        submit(ledger, first_tasks, identity="job-a")
        submit(ledger, [task("task-c", user_id=3)], identity="job-b")
    ledger.tick()
    with ledger.session_factory() as session:
        used = int(
            session.scalar(
                text("SELECT sum(payload_bytes) FROM management.execution_work")
            )
        )
    ledger.limits = replace(
        ledger.limits,
        bytes=used + 1 if scope == "run" else 8 * used,
        global_bytes=used + 1 if scope == "global" else 8 * used,
    )
    # One byte is positive, but cannot fit the next task. Do not fail or
    # consume the durable input while existing work owns the byte budget.
    assert ledger.tick() is None
    owned = claim(ledger)
    finish(ledger, owned)
    first_job_id = "job-test" if scope == "run" else "job-a"
    assert ledger.tick() == first_job_id
    assert ledger.stats(first_job_id)["completed"] == 1
    # Archive progress commits even when the next definition still cannot fit.
    owned = claim(ledger)
    finish(ledger, owned)
    for _ in range(4):
        ledger.tick()
    job_id = "job-test" if scope == "run" else "job-b"
    assert ledger.stats(job_id)["ready"] == 1
    with ledger.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT sum(payload_bytes) FROM management.execution_work")
            )
            <= ledger.limits.global_bytes
        )


def test_definition_larger_than_full_byte_window_still_fails(ledger):
    from ultima_scraper_backend.database.mps_definitions import (
        MPSDefinitionBudgetExceeded,
    )

    submit(ledger, [task()])
    ledger.limits = replace(ledger.limits, bytes=1)
    with pytest.raises(MPSDefinitionBudgetExceeded):
        ledger.tick()


@pytest.mark.parametrize("old_value", [None, "legacy", "ledger", "invalid"])
def test_admission_always_uses_ledger(ledger, monkeypatch, old_value):
    if old_value is not None:
        monkeypatch.setenv("ULTIMA_JOB_ENGINE", old_value)
    config = submit(ledger, [task()])
    assert config["metadata"]["execution_engine"] == "ledger"
    with ledger.session_factory() as session:
        assert session.scalar(select(ExecutionRunModel.run_id)) == "job-test"


@pytest.mark.parametrize("schedule", [{"interval_seconds": 60}, {"cron": "0 * * * *"}])
def test_recurring_jobs_fail_atomically_without_a_legacy_fallback(ledger, schedule):
    job = Job.create(name="Recurring", created_by="test", tasks=[])
    job.schedule = type(job.schedule).from_dict(schedule)
    with ledger.session_factory() as session:
        with pytest.raises(ValueError, match="Recurring schedules are not supported"):
            create_task_plan(
                session,
                job_id=job.job_id,
                job_type="test",
                site="onlyfans",
                job_config=job.to_dict(),
                args_payload={},
                tasks=[task()],
                batch_size=4,
                max_bytes=65536,
            )
        session.rollback()
        assert session.get(ExecutionRunModel, job.job_id) is None
        assert session.scalar(text("SELECT count(*) FROM management.mps_plans")) == 0
        assert session.scalar(text("SELECT count(*) FROM management.job_tasks")) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("distributed", [False, True])
async def test_api_submission_admits_sql_run_without_dispatch(ledger, monkeypatch, distributed):
    from contextlib import asynccontextmanager
    from ultima_scraper_backend.api.routes import jobs
    from ultima_scraper_db_archive import global_db

    monkeypatch.setattr(global_db, "global_session", ledger.session_factory)
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())

    @asynccontextmanager
    async def prepared(request, *args):
        item = task()
        job = Job.create(name=request.job_name, created_by="test", tasks=[item])
        yield job, [item], "onlyfans", 1, {"scrape"}, False

    monkeypatch.setattr(jobs, "_prepare_created_job", prepared)
    queue = SimpleNamespace(enqueue=AsyncMock(side_effect=AssertionError("Local queue used")))
    backend = SimpleNamespace(redis=SimpleNamespace(is_connected=True),
        distributed_mode=distributed, instance_id="owned-backend", active_queue=queue)
    request = jobs.CreateJobRequest(job_name="Default SQL engine", created_by="test", tasks=[])
    response = await jobs.create_job(request, backend=backend, backend_manager=SimpleNamespace())
    config = ledger.job(response.job_id)
    assert response.execution_engine == config["metadata"]["execution_engine"] == "ledger"
    assert config["metadata"].get("dispatch_backend_id") == (None if distributed else "owned-backend")
    assert ledger.stats(response.job_id)["total"] == 1
    queue.enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_recurring_schedule_returns_validation_error_and_rolls_back(ledger, monkeypatch):
    from contextlib import asynccontextmanager
    from fastapi import HTTPException
    from ultima_scraper_backend.api.routes import job_schemas, jobs
    from ultima_scraper_db_archive import global_db

    monkeypatch.setattr(global_db, "global_session", ledger.session_factory)

    @asynccontextmanager
    async def prepared(request, *args):
        item = task()
        job = Job.create(name=request.job_name, created_by="test", tasks=[item])
        yield job, [item], "onlyfans", 1, {"scrape"}, False

    monkeypatch.setattr(jobs, "_prepare_created_job", prepared)
    request = jobs.CreateJobRequest(job_name="Recurring", created_by="test", tasks=[],
        schedule=job_schemas.JobScheduleRequest(interval_seconds=60))
    backend = SimpleNamespace(redis=SimpleNamespace(is_connected=True), distributed_mode=True)
    with pytest.raises(HTTPException) as error:
        await jobs.create_job(request, backend=backend, backend_manager=SimpleNamespace())
    assert error.value.status_code == 400
    assert "Recurring schedules are not supported" in error.value.detail
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.jobs")) == 0
        assert session.scalar(select(ExecutionRunModel.run_id)) is None


@pytest.mark.asyncio
async def test_job_submission_rejects_disconnected_transport_instead_of_local_execution():
    from fastapi import HTTPException
    from ultima_scraper_backend.api.routes import jobs, mps

    backend = SimpleNamespace(redis=None)
    with pytest.raises(HTTPException) as ordinary:
        await jobs.create_job(jobs.CreateJobRequest(job_name="Offline", tasks=[], created_by="test"),
            backend=backend, backend_manager=SimpleNamespace())
    assert ordinary.value.status_code == 503
    with pytest.raises(HTTPException) as profiles:
        await mps.create_mps_job(None, backend=backend, backend_manager=SimpleNamespace())
    assert profiles.value.status_code == 503


def test_delete_revokes_attempt_and_does_not_leave_executable_work(ledger):
    submit(ledger, [task()])
    ledger.tick()
    old = claim(ledger)
    assert ledger.delete("job-test", receipt_queue=ReceiptQueueSnapshot())
    assert ledger.job("job-test") is None
    with pytest.raises(StaleAttempt):
        ledger.renew(old)
    assert ledger.tick() is None
    assert ledger.delete("job-test", receipt_queue=ReceiptQueueSnapshot()) is False


def pool():
    return SimpleNamespace(
        redis=None,
        worker_id="worker-a",
        apis={"onlyfans": object()},
        db_managers={},
        user_manager=None,
        config=None,
        database_writes=None,
        _refresh_storage_config_before_task=AsyncMock(),
        _ensure_auth_loaded_for_task=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_worker_waits_for_queued_writer_acknowledgement(ledger, monkeypatch):
    from ultima_scraper_backend.job_system.ledger_runtime import execute

    accepted, acknowledge = asyncio.Event(), asyncio.Event()
    worker = pool()
    identities = []

    async def enqueue(operation, payload, **kwargs):
        identities.append(kwargs["execution_attempt"])
        accepted.set()
        return kwargs["command_id"], 1

    async def wait_for_result(command_id):
        await acknowledge.wait()
        with ledger.session_factory() as session:
            validate_write_attempt(session, identities[-1])
        return {"saved": True}

    worker.database_writes = SimpleNamespace(
        enqueue=enqueue, wait_for_result=wait_for_result
    )

    async def handler(item, context):
        await context.database_writes.enqueue(
            DatabaseWriteOperation.UPSERT_USER, {"user_id": 1}
        )
        return TaskResult(success=True, output={"saved": True})

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, handler)
    submit(ledger, [task(kind=TaskType.API_COMMAND)])
    ledger.tick()
    owned = claim(ledger)
    execution = asyncio.create_task(execute(worker, ledger, owned))
    await asyncio.wait_for(accepted.wait(), 2)
    assert ledger.stats("job-test")["completed"] == 0
    assert ledger.task("job-test", "task-a")["state"] == "saving_db"
    acknowledge.set()
    assert await asyncio.wait_for(execution, 3) == (True, False, None)
    assert ledger.stats("job-test")["completed"] == 1
    assert identities[0]["token"] == owned.token


@pytest.mark.asyncio
async def test_worker_cancels_handler_after_sql_revocation(ledger, monkeypatch):
    from ultima_scraper_backend.job_system.ledger_runtime import execute

    entered, stopped = asyncio.Event(), asyncio.Event()
    ledger.limits = replace(ledger.limits, lease_seconds=0.3)

    async def handler(item, context):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, handler)
    submit(ledger, [task(kind=TaskType.API_COMMAND)])
    ledger.tick()
    execution = asyncio.create_task(execute(pool(), ledger, claim(ledger)))
    await asyncio.wait_for(entered.wait(), 2)
    ledger.control("job-test", "cancel")
    await asyncio.wait_for(execution, 3)
    assert stopped.is_set()
    assert ledger.stats("job-test")["cancelled"] == 1


@pytest.mark.parametrize('expires_during_outage', [False, True])
async def test_worker_retries_transient_renewal_without_reviving_expired_claim(ledger, monkeypatch, expires_during_outage):
    import psycopg
    from sqlalchemy.exc import OperationalError
    from ultima_scraper_backend.job_system import ledger_runtime

    ledger.limits = replace(ledger.limits, lease_seconds=0.9)
    renewed, stopped = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    original_renew = ledger.renew
    calls = 0

    def renew(owned):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError(None, None, psycopg.errors.ConnectionFailure('temporary disconnect'))
        original_renew(owned)
        loop.call_soon_threadsafe(renewed.set)

    async def backoff(self, error):
        if expires_during_outage:
            with ledger.session_factory() as session:
                session.execute(text("UPDATE management.execution_work SET lease_until=clock_timestamp()-interval '1 second'"))
                session.commit()

    async def handler(item, context):
        try:
            await renewed.wait()
            return TaskResult(success=True)
        finally:
            stopped.set()

    monkeypatch.setattr(ledger, 'renew', renew)
    monkeypatch.setattr(ledger_runtime._ServiceRetry, 'failed', backoff)
    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, handler)
    submit(ledger, [task(kind=TaskType.API_COMMAND)])
    ledger.tick()
    await asyncio.wait_for(ledger_runtime.execute(pool(), ledger, claim(ledger)), 3)
    assert calls == 2 and stopped.is_set()
    if expires_during_outage:
        assert ledger.recover_expired() == 1
        assert ledger.task('job-test', 'task-a')['state'] == 'pending'
    else:
        assert ledger.stats('job-test')['completed'] == 1


@pytest.mark.asyncio
async def test_worker_retries_transient_failures_with_recorded_attempt(
    ledger, monkeypatch
):
    from ultima_scraper_backend.job_system.ledger_runtime import execute

    async def handler(item, context):
        raise ConnectionError("temporary disconnect")

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, handler)
    submit(ledger, [task(kind=TaskType.API_COMMAND)])
    ledger.tick()
    await execute(pool(), ledger, claim(ledger))
    assert ledger.task("job-test", "task-a")["state"] == "pending"
    assert claim(ledger) is None
    assert ledger.attempts("job-test")[0]["state"] == "failed"


@pytest.mark.parametrize("lost_checkpoint_ack", [False, True])
@pytest.mark.asyncio
async def test_worker_recovers_server_disconnect_at_writer_checkpoint(
    ledger, monkeypatch, lost_checkpoint_ack
):
    import psycopg
    from sqlalchemy.exc import OperationalError
    from ultima_scraper_backend.job_system.ledger_runtime import execute

    worker = pool()
    original_checkpoint = ledger.checkpoint_batch
    failed = False
    writes = []

    def checkpoint(requests):
        nonlocal failed
        if not failed:
            failed = True
            if lost_checkpoint_ack:
                original_checkpoint(requests)
            raise OperationalError(None, None, psycopg.errors.ProtocolViolation("server conn crashed?"))
        return original_checkpoint(requests)

    def write(operation, payload, **kwargs):
        command = DatabaseWriteCommand(
            command_id=kwargs["command_id"], operation=operation, payload=payload,
            site="onlyfans", producer_id="test", created_at=datetime.now(UTC).isoformat(),
            version=2,
            execution_attempt=kwargs["execution_attempt"],
            execution_key=kwargs["execution_key"],
        )
        results = {}
        with ledger.session_factory() as session:
            with receipt_batch(session, [command], results) as pending:
                assert len(pending) == 1
                results[command.command_id] = {"saved": True}
                session.execute(text("INSERT INTO onlyfans.users (id) VALUES (1)"))
            session.commit()
        writes.append(command)
        return results[command.command_id]

    results_by_id = {}

    async def enqueue(operation, payload, **kwargs):
        results_by_id[kwargs["command_id"]] = write(operation, payload, **kwargs)
        return kwargs["command_id"], {}

    async def wait_for_result(command_id, **kwargs):
        return dict(results_by_id[command_id])

    worker.database_writes = SimpleNamespace(enqueue=enqueue, wait_for_result=wait_for_result)

    async def handler(item, context):
        await context.database_writes.submit(DatabaseWriteOperation.UPSERT_USER, {"user_id": 1})
        return TaskResult(success=True)

    monkeypatch.setattr(ledger, "checkpoint_batch", checkpoint)
    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, handler)
    submit(ledger, [task(kind=TaskType.API_COMMAND)])
    ledger.tick()
    first = claim(ledger)
    await execute(worker, ledger, first)
    assert ledger.task("job-test", "task-a")["state"] == "pending"
    assert writes == []
    assert claim(ledger) is None  # SQL exponential retry delay still applies.
    with ledger.session_factory() as session:
        session.execute(text("UPDATE management.execution_work SET available_at=clock_timestamp() WHERE run_id='job-test'"))
        session.commit()
    second = claim(ledger)
    assert second.number == first.number + 1 and second.token != first.token
    await execute(worker, ledger, second)
    assert ledger.task("job-test", "task-a")["state"] == "completed"
    assert [attempt["state"] for attempt in ledger.attempts("job-test")] == ["failed", "completed"]
    assert len(writes) == 1
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.execution_mutations")) == 1
        assert session.scalar(text("SELECT count(*) FROM management.database_write_receipts")) == 1
        assert session.scalar(text("SELECT count(*) FROM onlyfans.users WHERE id=1")) == 1
        with pytest.raises(StaleAttempt):
            validate_write_attempt(session, {
                "run_id": first.run_id, "task_id": first.task_id,
                "owner": first.owner, "token": first.token,
            })


@pytest.mark.asyncio
async def test_repeated_database_disconnect_stops_at_task_attempt_limit(ledger, monkeypatch):
    import psycopg
    from sqlalchemy.exc import OperationalError
    from ultima_scraper_backend.job_system.ledger_runtime import execute

    async def handler(item, context):
        raise OperationalError(None, None, psycopg.errors.ProtocolViolation("server conn crashed?"))

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, handler)
    item = task(kind=TaskType.API_COMMAND)
    item.max_attempts = 3
    submit(ledger, [item])
    ledger.tick()
    worker = pool()
    for number in range(1, 4):
        owned = claim(ledger)
        assert owned.number == number
        await execute(worker, ledger, owned)
        assert ledger.task("job-test", "task-a")["state"] == ("pending" if number < 3 else "failed")
        with ledger.session_factory() as session:
            session.execute(text("UPDATE management.execution_work SET available_at=clock_timestamp() WHERE run_id='job-test'"))
            session.commit()
    assert claim(ledger) is None
    assert [attempt["state"] for attempt in ledger.attempts("job-test")] == ["failed"] * 3


@pytest.mark.asyncio
async def test_ledger_worker_retains_phases_and_publishes_only_after_ack(
    ledger, monkeypatch
):
    import inspect
    import json

    from ultima_scraper_backend.database.write_queue import WRITE_TIMING_KEY
    from ultima_scraper_backend.job_system.ledger_runtime import execute
    from ultima_scraper_backend.job_system.storage import JobStorage

    worker = pool()
    worker.worker_count = 8
    worker.worker_registry = SimpleNamespace(
        start_task=AsyncMock(), complete_task=AsyncMock()
    )
    worker.task_job_storage = SimpleNamespace(record_task_runtime_telemetry=AsyncMock())
    waits = []

    async def enqueue(operation, payload, **kwargs):
        assert kwargs["execution_attempt"]["token"] == owned.token
        assert kwargs["_include_timing"]
        return kwargs["command_id"], {}

    async def wait_for_result(command_id, **kwargs):
        waits.append(command_id)
        worker.task_job_storage.record_task_runtime_telemetry.assert_not_awaited()
        return {"saved": True, WRITE_TIMING_KEY: {"execution_ms": 2, "commit_ms": 1}}

    worker.database_writes = SimpleNamespace(
        enqueue=enqueue, wait_for_result=wait_for_result
    )

    async def handler(item, context):
        hooks = context.context
        hooks["record_handler_timing"]("initial_lookup", 20)
        hooks["record_handler_timing"]("guest_auth_login", 5)
        hooks["record_route_timing"](25)
        hooks["record_route_observation"]("direct", 25, 5, 20, True, "found")
        await context.database_writes.submit(
            DatabaseWriteOperation.UPSERT_USER, {"user_id": 1}
        )
        return TaskResult(success=True)

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, handler)
    submit(ledger, [task(kind=TaskType.API_COMMAND)])
    ledger.tick()
    owned = claim(ledger)
    await execute(
        worker, ledger, owned, claim_wait_ms=7, effective_worker_concurrency=100
    )
    assert len(waits) == 1
    call = worker.task_job_storage.record_task_runtime_telemetry.await_args
    inspect.signature(JobStorage.record_task_runtime_telemetry).bind(
        None, *call.args, **call.kwargs
    )
    assert call.kwargs["claim_wait_ms"] == 7
    assert call.kwargs["effective_worker_concurrency"] == 100
    assert call.kwargs["writer_timed_submits"] == 1
    assert call.kwargs["route_attempts"] == 1
    assert call.kwargs["handler_initial_lookup_ms"] == 20
    assert call.kwargs["post_ms"] > 0
    assert json.loads(call.kwargs["guest_auth_stats_json"])["login"]["count"] == 1
    worker.worker_registry.complete_task.assert_awaited_once_with(
        success=True, task_id=owned.task_id
    )
    assert ledger.attempts("job-test")[0]["timings"]["handler_initial_lookup_ms"] == 20


def test_active_tasks_match_task_payloads_in_one_query(ledger, monkeypatch):
    submit(ledger, [task("task-a"), task("task-b"), task("task-c")])
    ledger.tick()
    owned = claim(ledger)
    expected = {
        identity: ledger.task("job-test", identity)
        for identity in ("task-a", "task-b", "task-c")
    }
    assert expected[owned.task_id]["state"] == "running"
    assert expected[owned.task_id]["worker_id"] == "worker-a"
    monkeypatch.setattr(ledger, "task", lambda *args: pytest.fail("Hydrated a task"))
    rows = ledger.active()
    # Running work is listed before queued work.
    assert rows[0]["task"]["task_id"] == owned.task_id
    assert {row["task"]["task_id"]: row["task"] for row in rows} == expected
    assert {row["job_id"] for row in rows} == {"job-test"}
    assert {row["job_name"] for row in rows} == {"Ledger test"}
    assert {row["job_total_tasks"] for row in rows} == {3}


def test_task_page_hydrates_live_and_archived_tasks_as_a_batch(ledger, monkeypatch):
    submit(ledger, [task("task-a"), task("task-b"), task("task-c")])
    ledger.tick()
    finish(ledger, claim(ledger))
    ledger.tick()
    expected = [ledger.task("job-test", identity) for identity in ("task-a", "task-b", "task-c")]
    assert {item["state"] for item in expected} == {"completed", "pending"}
    assert any(item["result"] for item in expected if item["state"] == "completed")
    monkeypatch.setattr(ledger, "task", lambda *args: pytest.fail("Hydrated a task"))
    assert ledger.task_page("job-test", limit=10)["tasks"] == expected


def test_diagnostic_run_discovery_does_not_hydrate_tasks(ledger, monkeypatch):
    submit(ledger, [task()])
    ledger.tick()
    monkeypatch.setattr(ledger, "task", lambda *args: pytest.fail("Hydrated a task"))
    assert ledger.active_run_ids() == ["job-test"]


def test_job_headers_reuse_one_checkout_for_a_full_page(ledger, ledger_engine, monkeypatch):
    """The session-pooled deployment must not pay two handshakes per row."""
    import ultima_scraper_backend.job_system.ledger as ledger_module
    from ultima_scraper_backend.api.routes import jobs
    from ultima_scraper_db_archive import global_db

    identities = [f"header-{index}" for index in range(200)]
    for identity in identities:
        submit(ledger, [task(f"task-{identity}")], identity=identity)
    expected = {identity: ledger.job(identity) for identity in identities}
    monkeypatch.setattr(ledger_module, "ExecutionLedger", lambda: ledger)
    monkeypatch.setattr(global_db, "global_session", ledger.session_factory)
    counts = {"checkouts": 0, "queries": 0}

    def checkout(*args):
        counts["checkouts"] += 1

    def query(*args):
        counts["queries"] += 1

    event.listen(ledger_engine, "checkout", checkout)
    event.listen(ledger_engine, "before_cursor_execute", query)
    try:
        headers = jobs._fetch_durable_headers_sync(identities)
    finally:
        event.remove(ledger_engine, "checkout", checkout)
        event.remove(ledger_engine, "before_cursor_execute", query)
    assert {key: row["config"] for key, row in headers.items()} == expected
    assert counts == {"checkouts": 1, "queries": 4}  # SET LOCAL + 3 set reads
    assert jobs._fetch_durable_headers_sync([]) == {}
    with pytest.raises(ValueError, match="256"):
        ledger.jobs_many([str(index) for index in range(257)])


@pytest.mark.asyncio
async def test_sql_api_pages_and_controls_do_not_require_redis_runtime(
    ledger, monkeypatch
):
    import ultima_scraper_backend.job_system.ledger as ledger_module
    from ultima_scraper_backend.api.routes import jobs
    from ultima_scraper_db_archive import global_db

    monkeypatch.setattr(ledger_module, "ExecutionLedger", lambda: ledger)
    monkeypatch.setattr(global_db, "global_session", ledger.session_factory)
    submit(ledger, [task()])
    ledger.tick()
    finish(ledger, claim(ledger))
    headers = jobs._fetch_durable_headers_sync(["job-test"])
    assert jobs._durable_task_stats(headers["job-test"]).completed == 1
    page = await jobs.get_job_tasks(
        "job-test", backend=SimpleNamespace(redis=None), limit=10
    )
    assert page.tasks[0].status == "completed"
    paused = await jobs.pause_execution("job-test")
    assert paused.status.value == "paused" and paused.execution_engine == "ledger"
    resumed = await jobs.resume_execution("job-test")
    assert resumed.status.value == "pending"
    ledger.relay(lambda event: None)
    replay = await jobs.execution_events(after=0, limit=500)
    assert replay["events"] and replay["next_cursor"] == ledger.event_head()


def test_pending_replacement_commits_a_new_ledger_revision(ledger, monkeypatch):
    from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
    from ultima_scraper_db_archive import global_db

    monkeypatch.setattr(global_db, "global_session", ledger.session_factory)
    submit(ledger, [task()])
    ledger.tick()

    def command(identity, operation, payload):
        return DatabaseWriteCommand(
            command_id=identity,
            operation=operation,
            site=None,
            payload={
                "job_id": "job-test",
                "manifest_id": "replacement-input",
                **payload,
            },
            producer_id="test",
            created_at="2026-10-03T00:00:00+00:00",
        )

    PostgreSQLWriteExecutor._replace_mps_definitions(
        [
            command(
                "edit-begin",
                DatabaseWriteOperation.BEGIN_MPS_REPLACEMENT,
                {"name": "Edited"},
            )
        ]
    )
    PostgreSQLWriteExecutor._replace_mps_definitions(
        [
            command(
                "edit-page",
                DatabaseWriteOperation.APPEND_MPS_REPLACEMENT,
                {"offset": 0, "tasks": [task("task-new").to_dict()]},
            )
        ]
    )
    PostgreSQLWriteExecutor._replace_mps_definitions(
        [
            command(
                "edit-commit",
                DatabaseWriteOperation.COMMIT_MPS_REPLACEMENT,
                {"total": 1},
            )
        ]
    )
    assert ledger.job("job-test")["metadata"]["execution_revision"] == 2
    ledger.tick()
    owned = claim(ledger)
    assert owned.task_id == "task-new" and owned.job["name"] == "Edited"


def test_attempt_cursor_does_not_skip_a_second_attempt_for_the_same_task(ledger):
    submit(ledger, [task()])
    ledger.tick()
    old = claim(ledger)
    with ledger.session_factory() as session:
        session.execute(
            text(
                "UPDATE management.execution_work SET lease_until=clock_timestamp()-interval '1 second'"
            )
        )
        session.commit()
    ledger.recover_expired()
    finish(ledger, claim(ledger))
    first = ledger.attempts("job-test", limit=1)[0]
    second = ledger.attempts(
        "job-test", after_task=first["task_id"], after_attempt=first["attempt"], limit=1
    )[0]
    assert (first["attempt"], second["attempt"]) == (old.number, old.number + 1)


def test_late_outbox_commit_is_not_skipped_by_sequence_cursor(ledger):
    from ultima_scraper_backend.job_system.ledger import _event

    submit(ledger, [task()])
    ledger.relay(lambda event: None)
    with ledger.session_factory() as slow:
        _event(slow, "job-test", "slow_event")
        slow.flush()
        with ledger.session_factory() as fast:
            _event(fast, "job-test", "fast_event")
            fast.commit()
        ledger.relay(lambda event: None)
        head = ledger.event_head()
        assert ledger.events(after=1)[0]["event"] == "fast_event"
        slow.commit()
    ledger.relay(lambda event: None)
    assert ledger.events(after=head)[0]["event"] == "slow_event"


def test_busy_deduplication_keys_do_not_starve_other_ready_work(ledger):
    ledger.limits = replace(ledger.limits, tasks=20, global_tasks=40, batch=20)
    submit(
        ledger,
        [task(f"task-{index:02}") for index in range(12)] + [task("task-z", user_id=2)],
    )
    ledger.tick()
    assert claim(ledger).task_id == "task-00"
    assert claim(ledger, "worker-b").task_id == "task-z"


def test_delete_purges_history_in_batches_and_can_resume(ledger):
    from ultima_scraper_db_archive.execution_models import (
        ExecutionAttemptModel, ExecutionMutationModel, ExecutionOutboxModel,
    )
    submit(ledger, [task(f"task-{i}") for i in range(3)])
    ledger.tick()
    for _ in range(3):
        finish(ledger, claim(ledger))
    updates = []

    def interrupt(table, rows):
        updates.append((table, rows))
        if rows >= 2:
            raise RuntimeError("interrupted purge")

    with pytest.raises(RuntimeError, match="interrupted purge"):
        ledger.delete("job-test", batch_size=1, progress=interrupt, receipt_queue=ReceiptQueueSnapshot())
    assert ledger.job("job-test")["state"] == "cancelled"
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT status FROM management.jobs WHERE job_id='job-test'")) == "deleting"
    assert updates[0] == ("cancelled", 0)
    with pytest.raises(ValueError, match="deletion is in progress"):
        ledger.retry("job-test")
    assert ledger.delete("job-test", batch_size=1, receipt_queue=ReceiptQueueSnapshot())
    with ledger.session_factory() as session:
        for model in (ExecutionRunModel, ExecutionWorkModel, ExecutionAttemptModel,
                      ExecutionMutationModel, ExecutionOutboxModel):
            assert session.scalar(select(model).limit(1)) is None
    assert len(updates) >= 2


@pytest.mark.asyncio
async def test_delete_uses_sql_without_redis_projection(ledger, monkeypatch):
    from ultima_scraper_backend.api.routes import jobs
    from ultima_scraper_db_archive import global_db
    submit(ledger, [task()])
    monkeypatch.setattr(global_db, "global_session", ledger.session_factory)
    monkeypatch.setattr(jobs, "publish_ws_event", AsyncMock())
    response = await jobs.delete_job("job-test", backend=SimpleNamespace(redis=None))
    assert response["status"] == "deleting"
    assert ledger.job("job-test")["state"] == "cancelled"
    from ultima_scraper_backend.services.job_deletion import cleanup_pending
    assert cleanup_pending(ledger.session_factory, receipt_queue=ReceiptQueueSnapshot()) == ["job-test"]
    assert ledger.job("job-test") is None


def test_background_deletion_finishes_jobs_in_request_order(ledger, monkeypatch):
    from ultima_scraper_backend.services import job_deletion

    for identity in ("job-first", "job-second", "job-third"):
        submit(ledger, [task(f"{identity}-task")], identity=identity)
        assert ledger.begin_delete(identity)
    picked = []
    monkeypatch.setattr(job_deletion, "ExecutionLedger", lambda _: SimpleNamespace(
        delete=lambda job_id, **_: picked.append(job_id)))

    def next_job():
        job_deletion._cleanup_pass(ledger.session_factory, receipt_queue=ReceiptQueueSnapshot())
        return picked[-1]

    # Progress checkpoints must not rotate the queue.
    assert next_job() == "job-first"
    ledger._save_deletion_progress("job-first", {"rows": 512, "completed_stages": 1})
    assert next_job() == "job-first"
    # A blocked job yields until its retry delay passes.
    ledger._save_deletion_progress("job-first", {"rows": 512, "error": "Waiting for writer lock"})
    assert next_job() == "job-second"
    monkeypatch.setattr(job_deletion, "BLOCKED_RETRY_SECONDS", -60)
    assert next_job() == "job-first"


def test_deletion_indexes_migration_roundtrip(ledger_engine):
    path = (Path(ultima_scraper_db_archive.__file__).parent / "migrations/alembic/versions/a6d901fe7823_index_execution_deletion.py")
    spec = importlib.util.spec_from_file_location("deletion_indexes", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with ledger_engine.connect() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
        names = set(connection.execute(text(
            "SELECT indexname FROM pg_indexes WHERE schemaname='management'"
        )).scalars())
        assert {"idx_execution_outbox_run", "idx_execution_resources_run"} <= names


def test_deletion_waits_for_relay_owned_rows_without_cascading(ledger):
    from threading import Event
    from ultima_scraper_db_archive.execution_models import ExecutionOutboxModel

    submit(ledger, [task()])
    # Keep the run terminal so cancellation does not introduce extra events.
    ledger.control('job-test', 'cancel')
    publishing = Event()
    release = Event()
    skipped = Event()

    def publish(rows):
        assert rows
        publishing.set()
        assert release.wait(10)

    def progress(table, removed):
        if table == 'execution_outbox' and removed == 0:
            skipped.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        relay = executor.submit(ledger.relay, publish_many=publish)
        deletion = None
        try:
            assert publishing.wait(5)
            deletion = executor.submit(ledger.delete, 'job-test', 1, progress, receipt_queue=ReceiptQueueSnapshot())
            assert skipped.wait(5)
            assert not deletion.done()
            with ledger.session_factory() as session:
                assert session.get(ExecutionRunModel, 'job-test') is not None
        finally:
            release.set()
        assert relay.result(timeout=10) > 0
        assert deletion.result(timeout=10)
    with ledger.session_factory() as session:
        assert session.scalar(select(ExecutionOutboxModel.event_id).limit(1)) is None


def test_deletion_retries_deadlock_after_rolling_back_batch(ledger, monkeypatch):
    from psycopg.errors import DeadlockDetected
    from sqlalchemy.exc import OperationalError

    submit(ledger, [task()])
    execute = Session.execute
    attempts = 0

    def fail_once(session, statement, *args, **kwargs):
        nonlocal attempts
        if getattr(statement, 'is_delete', False) and statement.table.name == 'execution_outbox':
            attempts += 1
            if attempts == 1:
                raise OperationalError('DELETE', {}, DeadlockDetected('deadlock detected'))
        return execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, 'execute', fail_once)
    assert ledger.delete('job-test', batch_size=1, receipt_queue=ReceiptQueueSnapshot())
    assert attempts >= 2
    assert ledger.job('job-test') is None


def test_deletion_removes_only_its_task_media_graph(ledger):
    submit(ledger, [task()])
    with ledger.session_factory() as session:
        for sid, jid in [('selection-deleted', 'job-test'), ('selection-retained', 'other-job')]:
            session.execute(text("INSERT INTO management.task_media_plans (selection_id,job_id,task_id,site) VALUES (:sid,:jid,'task-a','onlyfans')"), {'sid': sid, 'jid': jid})
            session.execute(text("INSERT INTO management.task_media_selections (selection_id,user_id,content_type,media_id,content_id,content_created_at) VALUES (:sid,1,'posts',1,1,now())"), {'sid': sid})
            session.execute(text("INSERT INTO management.task_media_evidence (selection_id,kind,ordinal,payload_json) VALUES (:sid,'download',0,'{}')"), {'sid': sid})
        session.commit()
    assert ledger.delete('job-test', batch_size=1, receipt_queue=ReceiptQueueSnapshot())
    with ledger.session_factory() as session:
        for table in ('task_media_plans', 'task_media_selections', 'task_media_evidence'):
            assert session.execute(text(f'SELECT selection_id FROM management.{table}')).scalars().all() == ['selection-retained']


def test_deletion_checkpoint_resumes_with_a_new_ledger_instance(ledger):
    from ultima_scraper_backend.job_system.ledger import ExecutionLedger
    submit(ledger, [task()])
    assert ledger.begin_delete("job-test")
    assert ledger.job("job-test")["metadata"]["deletion_pending"]
    assert ledger.delete("job-test", batch_size=1, time_budget=0, receipt_queue=ReceiptQueueSnapshot()) is None
    saved = ledger.job("job-test")["metadata"]["deletion_progress"]
    assert saved["rows"] > 0 and saved["table"] == "execution_outbox"
    with pytest.raises(ValueError, match="deletion is in progress"):
        ledger.retry("job-test")
    fresh = ExecutionLedger(ledger.session_factory)
    assert fresh.delete("job-test", batch_size=1, receipt_queue=ReceiptQueueSnapshot())
    assert fresh.job("job-test") is None


def test_idle_outcomes_do_not_confuse_lock_contention_or_full_windows(ledger, ledger_engine):
    outcome = []
    assert ledger.tick(refill_only=True, outcome=outcome) is None
    assert outcome == ["idle"]
    assert ledger.archive_tick(outcome=outcome) is None
    assert outcome == ["idle"]
    assert ledger.relay(publish=lambda payload: None, outcome=outcome) == 0
    assert outcome == ["idle"]
    with ledger_engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('execution-window-budget',0))"))
        assert ledger.tick(refill_only=True, outcome=outcome) is None
        assert outcome == ["deferred"]
    submit(ledger, [task(f"task-{index}") for index in range(8)])
    assert ledger.tick(refill_only=True, outcome=outcome) == "job-test"
    assert ledger.tick(refill_only=True, outcome=outcome) is None
    assert outcome == ["deferred"]


def test_refill_rotation_skips_fully_admitted_runs(ledger):
    # Single-task runs sort before the large run. Once admitted they only
    # await the archiver and must not take refill turns from the large run.
    planner = ExecutionLedger(
        ledger.session_factory,
        limits=Limits(tasks=16, global_tasks=32, batch=2, planner_batch=2),
    )
    for identity in ("api-a", "api-b", "api-c"):
        submit(planner, [task(f"{identity}-task")], identity=identity)
    submit(planner, [task(f"big-{index}") for index in range(8)], identity="job-big")
    planned = [planner.tick(refill_only=True) for _ in range(7)]
    assert planned == ["api-a", "api-b", "api-c", *["job-big"] * 4]
    outcome = []
    assert planner.tick(refill_only=True, outcome=outcome) is None
    assert outcome == ["idle"]


def test_archive_diagnostics_break_down_each_phase(ledger):
    submit(ledger, [task("a"), task("b")])
    ledger.tick(refill_only=True)
    finish(ledger, claim(ledger))
    finish(ledger, claim(ledger))
    observations = []
    assert ledger.archive_tick(diagnostics=observations) == "job-test"
    entry = observations[-1]
    assert entry["stage"] == "ledger_archive" and entry["archived_tasks"] == 2
    phases = entry["phases_ms"]
    assert set(phases) == {
        "select_run", "select_terminal", "lock_rows", "build_rows",
        "plan_lock", "evidence", "prefetch", "history_insert", "definitions",
        "checkpoint", "delete_work", "commit",
    }
    assert all(value >= 0 for value in phases.values())
    # Phases tile the pass without overlap: their sum never exceeds it.
    assert sum(phases.values()) <= entry["archive_ms"] + 1
    # The job detail API keeps the breakdown when serializing the trace.
    from ultima_scraper_backend.api.routes.job_schemas import MPSRefillTraceEvent

    published = {key: value for key, value in entry.items() if key != "job_id"}
    assert MPSRefillTraceEvent.model_validate(published).model_dump()["phases_ms"] == phases
    # Archiving without diagnostics records nothing and still succeeds.
    submit(ledger, [task("c")], identity="job-quiet")
    ledger.tick(refill_only=True)
    finish(ledger, claim(ledger))
    assert ledger.archive_tick() == "job-quiet"


def test_bulk_admission_rows_equal_the_orm_path(ledger):
    from ultima_scraper_backend.job_system.ledger import (
        Work,
        _insert_admitted_work,
        _work_lane,
    )

    submit(ledger, [task("seed-orm")], identity="eq-orm")
    submit(ledger, [task("seed-bulk")], identity="eq-bulk")
    kinds = [TaskType.SCRAPE, TaskType.DOWNLOAD, TaskType.API_COMMAND, TaskType.PLUGIN]
    rows, candidates = [], {}
    for index, kind in enumerate(kinds * 2):
        item = task(f"eq-{index}", kind=kind, user_id=index + 1)
        item.capabilities = [] if index == 3 else ["onlyfans", f"cap-{index}"]
        if index == 5:
            item.state = TaskState.FAILED
        # Non-ASCII payloads: payload_size (UTF-8 bytes) differs from payload_bytes (chars).
        encoded = json.dumps({**item.to_dict(), "note": "é" * index + "😀"}, ensure_ascii=False)
        rows.append((item, encoded, len(encoded)))
        if index % 2 == 0:
            candidates[item.task_id] = 1000 + index

    with ledger.session_factory() as session:  # the previous per-task ORM path
        for item, encoded, size in rows:
            session.add(Work(
                run_id="eq-orm", task_id=item.task_id,
                state="failed" if item.state == TaskState.FAILED else "queued",
                lane=_work_lane(item), site=item.site_name.lower(),
                capabilities=list(item.capabilities), dedup_key=item.dedup_key,
                payload_json=encoded, payload_bytes=size,
                candidate=candidates.get(item.task_id),
            ))
        session.commit()
    with ledger.session_factory() as session:
        _insert_admitted_work(session, "eq-bulk", rows, candidates)
        session.commit()

    def snapshot(run_id):
        with ledger.session_factory() as session:
            work = session.execute(text(
                "SELECT * FROM management.execution_work WHERE run_id=:run AND task_id LIKE 'eq-%' ORDER BY task_id"
            ), {"run": run_id}).mappings().all()
            payloads = dict(session.execute(text(
                "SELECT task_id, payload_json FROM management.execution_work_payloads WHERE run_id=:run AND task_id LIKE 'eq-%'"
            ), {"run": run_id}).all())
        result = []
        for row in work:
            row = dict(row)
            assert row["available_at"] == row["created_at"] is not None
            result.append({k: v for k, v in row.items()
                           if k not in {"run_id", "available_at", "created_at"}})
        return result, payloads

    orm_rows, orm_payloads = snapshot("eq-orm")
    bulk_rows, bulk_payloads = snapshot("eq-bulk")
    assert len(bulk_rows) == 8 and bulk_rows == orm_rows
    assert bulk_payloads == orm_payloads
    lanes = {row["task_id"]: row["lane"] for row in bulk_rows}
    assert {lanes["eq-0"], lanes["eq-1"], lanes["eq-2"], lanes["eq-3"]} == {
        "scrape", "download", "interactive", "plugin"}
    assert any(row["payload_size"] != row["payload_bytes"] for row in bulk_rows)


def test_refill_diagnostics_break_down_each_phase(ledger):
    submit(ledger, [task(f"phase-{index}") for index in range(3)])
    observations = []
    assert ledger.tick(refill_only=True, diagnostics=observations) == "job-test"
    entry = observations[-1]
    assert entry["stage"] == "ledger_refill" and entry["admitted_tasks"] == 3
    phases = entry["phases_ms"]
    assert set(phases) == {
        "budget_lock", "select_run", "snapshot", "limits", "archive", "accounting",
        "plan_refresh", "source_page", "encode", "insert", "commit",
    }
    assert all(value >= 0 for value in phases.values())
    assert sum(phases.values()) <= entry["pass_ms"] + 1
    with ledger.session_factory() as session:
        assert session.scalar(text(
            "SELECT count(*) FROM management.execution_work_payloads WHERE run_id='job-test'"
        )) == 3


def _churn_queue(ledger, cycles=6, rows=4000, keep=50):
    """Insert and delete queue rows so their indexes hold mostly dead entries."""
    submit(ledger, [task("churn-seed")], identity="job-churn")
    with ledger.session_factory() as session:
        for cycle in range(cycles):
            session.execute(text("""
                INSERT INTO management.execution_work
                    (run_id, task_id, state, lane, site, capabilities, dedup_key, payload_bytes, payload_size)
                SELECT 'job-churn', 'churn-' || :cycle || '-' || g, 'queued', 'scrape', 'onlyfans',
                    ARRAY['onlyfans'], 'churn:' || :cycle || ':' || g, 10, 10
                FROM generate_series(1, :rows) g
            """), {"cycle": cycle, "rows": rows})
            session.execute(text("""
                DELETE FROM management.execution_work
                WHERE run_id='job-churn' AND task_id LIKE 'churn-' || :cycle || '-%'
                  AND split_part(task_id, '-', 3)::int > :keep
            """), {"cycle": cycle, "keep": keep})
            session.commit()


def _queue_indexes(ledger):
    with ledger.session_factory() as session:
        return {name: (size, valid) for name, size, valid in session.execute(text("""
            SELECT i.relname, pg_relation_size(i.oid), x.indisvalid
            FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
            JOIN pg_class t ON t.oid = x.indrelid
            WHERE t.relname IN ('execution_work','execution_work_payloads','execution_resources')
        """))}


def test_bloated_queue_indexes_are_rebuilt_online(ledger):
    _churn_queue(ledger)
    before = _queue_indexes(ledger)
    pkey = before["execution_work_pkey"][0]
    assert pkey > 512 * 1024
    # Below the threshold nothing happens; 0 disables rebuilds entirely.
    assert ledger.reindex_bloated_queue_indexes(threshold_bytes=pkey * 4) == []
    assert ledger.reindex_bloated_queue_indexes(threshold_bytes=0) == []

    rebuilt = ledger.reindex_bloated_queue_indexes(threshold_bytes=256 * 1024, limit=10)
    names = {item["index"] for item in rebuilt}
    assert "execution_work_pkey" in names
    assert all(item["after_bytes"] < item["before_bytes"] for item in rebuilt)
    after = _queue_indexes(ledger)
    assert set(after) == set(before) and all(valid for _, valid in after.values())
    assert after["execution_work_pkey"][0] < pkey / 2
    with ledger.session_factory() as session:
        session.execute(text("SET LOCAL enable_seqscan=off"))
        assert session.scalar(text(
            "SELECT count(*) FROM management.execution_work WHERE run_id='job-churn' AND state='queued'"
        )) == 6 * 50


def test_failed_queue_rebuild_drops_its_invalid_copy(ledger, ledger_engine):
    _churn_queue(ledger, cycles=3)
    # The pass rebuilds the largest bloated index; its interrupted copy is the target.
    target = max(_queue_indexes(ledger).items(), key=lambda item: item[1][0])[0]
    leftover = f"{target}_ccnew"
    with ledger_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        # A failed unique build leaves an invalid index, like an interrupted
        # REINDEX CONCURRENTLY leaves its *_ccnew copy.
        with pytest.raises(Exception):
            connection.exec_driver_sql(
                f'CREATE UNIQUE INDEX CONCURRENTLY "{leftover}" '
                "ON management.execution_work (site)"
            )
    assert _queue_indexes(ledger)[leftover][1] is False

    def fail_reindex(conn, cursor, statement, *args):
        if statement.startswith("REINDEX"):
            raise RuntimeError("simulated rebuild failure")

    event.listen(ledger_engine, "before_cursor_execute", fail_reindex)
    try:
        with pytest.raises(RuntimeError, match="simulated rebuild failure"):
            ledger.reindex_bloated_queue_indexes(threshold_bytes=256 * 1024)
    finally:
        event.remove(ledger_engine, "before_cursor_execute", fail_reindex)
    indexes = _queue_indexes(ledger)
    assert leftover not in indexes
    assert indexes[target][1] is True


def test_queue_reindex_threshold_reads_environment(monkeypatch):
    from ultima_scraper_backend.job_system.ledger import queue_reindex_threshold

    monkeypatch.delenv("ULTIMA_LEDGER_QUEUE_REINDEX_BYTES", raising=False)
    assert queue_reindex_threshold() == 64 * 1024 * 1024
    monkeypatch.setenv("ULTIMA_LEDGER_QUEUE_REINDEX_BYTES", "0")
    assert queue_reindex_threshold() == 0
    monkeypatch.setenv("ULTIMA_LEDGER_QUEUE_REINDEX_BYTES", "-1")
    with pytest.raises(ValueError):
        queue_reindex_threshold()


async def test_queue_maintenance_loop_waits_for_leadership_and_logs(caplog):
    from ultima_scraper_backend.job_system.ledger_runtime import maintain_queue_indexes

    calls = []

    class Ledger:
        def reindex_bloated_queue_indexes(self):
            calls.append("reindex")
            return [{"index": "execution_work_pkey", "before_bytes": 300 * 1048576,
                     "after_bytes": 2 * 1048576, "ms": 850.0}] if len(calls) == 1 else []

    class Coordination:
        waits = 0

        async def wait(self):
            Coordination.waits += 1

    caplog.set_level("INFO")
    await maintain_queue_indexes(Ledger(), Coordination(), interval=0, passes=2)
    assert calls == ["reindex", "reindex"] and Coordination.waits == 2
    assert [r.getMessage() for r in caplog.records if "Rebuilt queue index" in r.getMessage()] == [
        "Rebuilt queue index execution_work_pkey online: 300.0 MB -> 2.0 MB in 850 ms"
    ]


def test_batched_statistics_match_individual_states_and_missing_runs(ledger):
    submit(ledger, [task("a"), task("b")], identity="job-first")
    submit(ledger, [task("c")], identity="job-second")
    ledger.tick(refill_only=True)
    ledger.tick(refill_only=True)
    owned = claim(ledger)
    finish(ledger, owned)
    batched = ledger.stats_many(["job-first", "job-second", "missing"])
    assert set(batched) == {"job-first", "job-second"}
    assert sum(row["total"] for row in batched.values()) == 3
    assert sum(row["completed"] for row in batched.values()) == 1
    for identity, value in batched.items():
        assert value == ledger.stats(identity)
    ledger.archive_tick()
    assert ledger.stats_many(list(batched)) == batched


def _finished_archive_tasks():
    from ultima_scraper_backend.job_system.payloads import ScrapeTaskPayload

    def done(item, *, success=True, **result):
        item.state = TaskState.COMPLETED if success else TaskState.FAILED
        item.started_at = "2026-10-21T10:00:00Z"
        item.result = TaskResult(success=success, **result)
        item.completed_at = item.result.completed_at
        return item

    routed = task("sql-routed", user_id=4242)
    routed.user_username = "Mañana"
    routed.payload = ScrapeTaskPayload(
        guest_proxy_url="http://p1:8080",
        guest_fallback_proxy_urls=["http://p2:8080", "http://p3:8080"],
        guest_proxy_alternatives={"US": ["http://p4:8080"]},
        track_invalid_user=True,
    )
    named = task("sql-named", user_id="named-user")
    named.mps_task_manifest = "manifest-1"
    nested = task("sql-subtasks")
    nested.subtasks = [done(task("sql-child"), output={"value": 1})]
    return [
        done(routed, output={"items_saved": "3", "result": {"result": None}},
             metrics={"items_processed": 2.9, "items_total": "5", "handler_ms": 12.5},
             message="saved ✓"),
        done(task("sql-failed"), success=False, errors=["404 \"missing\"", "later"],
             metrics={"processed": True, "count": "x"}),
        done(named, output=[1, 2], message="list output"),
        done(task("sql-plain"), output=None),
        done(nested, output={"value": 2}),
    ]


def test_sql_archive_rows_equal_the_python_rows(ledger):
    from ultima_scraper_backend.job_system.ledger import (
        _LOCK_ARCHIVE_ROWS,
        _archive_history_row,
        _dump,
        _python_history_row,
    )

    finished = _finished_archive_tasks()
    submitted = [Task.from_dict(item.to_dict(include_result=False)) for item in finished]
    for item in submitted:
        item.subtasks = []  # Subtasks only appear in the finished payload below.
    # The fixture's window holds four tasks; admit all five in one pass.
    ledger = ExecutionLedger(ledger.session_factory, limits=Limits(tasks=8, global_tasks=8, batch=8))
    submit(ledger, submitted)
    ledger.tick(refill_only=True)
    # Workers finish a task decoded from its claimed payload, so a finished
    # payload is the canonical encoding of a decoded task.
    payloads = {
        item.task_id: _dump(Task.from_dict(item.to_dict()).to_dict()) for item in finished
    }
    # Written another way (separators, an untyped payload), a row keeps its
    # own encoding; it restores to the same task.
    payloads["sql-plain"] = json.dumps(finished[3].to_dict())
    with ledger.session_factory() as session:
        for task_id, payload in payloads.items():
            session.execute(text(
                "UPDATE management.execution_work_payloads SET payload_json=:payload "
                "WHERE run_id='job-test' AND task_id=:task_id"
            ), {"payload": payload, "task_id": task_id})
        rows = session.execute(
            _LOCK_ARCHIVE_ROWS, {"run_id": "job-test", "ids": sorted(payloads)}
        ).all()
        session.rollback()
    assert sorted(row.task_id for row in rows) == sorted(payloads)
    by_id = {row.task_id: row for row in rows}
    # Subtasks keep their own results, so that row takes the Python path.
    assert by_id["sql-subtasks"].definition is None
    assert by_id["sql-subtasks"].payload_json == payloads["sql-subtasks"]
    for task_id, payload in payloads.items():
        built = _archive_history_row(by_id[task_id], "job-test")
        expected = _python_history_row(payload, "job-test")
        if task_id == "sql-plain":
            assert built["definition_json"] != expected["definition_json"]
            assert {**built, "definition_json": None} == {**expected, "definition_json": None}
            restored = [
                Task.from_dict(json.loads(row["definition_json"])).to_dict()
                for row in (built, expected)
            ]
            assert restored[0] == restored[1]
        else:
            assert built == expected, task_id


def test_archive_pass_stores_the_same_history_with_sql_rows(ledger, monkeypatch):
    def archived(identity, sql_rows):
        monkeypatch.setenv("ULTIMA_ARCHIVE_SQL_ROWS", "1" if sql_rows else "0")
        tasks = [task(f"{identity}-{index}", user_id=100 + index) for index in range(4)]
        submit(ledger, tasks, identity=identity)
        ledger.tick(refill_only=True)
        while (owned := claim(ledger)) is not None:
            finish(ledger, owned, success=not owned.task["task_id"].endswith("-2"))
        assert ledger.archive_tick() == identity
        with ledger.session_factory() as session:
            rows = session.execute(text(
                "SELECT task_id, task_type, status, site, user_id, username, items_processed,"
                " items_total, error, message, result_json, definition_json"
                " FROM management.job_tasks WHERE job_id=:job ORDER BY task_id"
            ), {"job": identity}).mappings().all()
        assert len(rows) == 4
        normalized = []
        for row in rows:
            row = dict(row)
            row["task_id"] = row["task_id"].removeprefix(identity)
            definition = json.loads(row.pop("definition_json"))
            assert definition["result"] is None
            # Identities and times differ between the two jobs by construction.
            for key in ("task_id", "job_id", "mps_task_manifest", "created_at",
                        "updated_at", "started_at", "completed_at", "worker_id"):
                definition.pop(key, None)
            result = json.loads(row.pop("result_json"))
            result.pop("completed_at")
            normalized.append({**row, "definition": definition, "result": result})
        return normalized

    assert archived("job-sqlrows", True) == archived("job-ormrows", False)


def test_archive_lock_probes_payloads_by_key_not_by_scan(ledger):
    from ultima_scraper_backend.job_system.ledger import _LOCK_ARCHIVE_ROWS

    # A scan of the whole payload table stalled production passes for 8-43 s
    # once the table bloated during a run.
    submit(ledger, [task("seed")])
    ledger.tick(refill_only=True)
    with ledger.session_factory() as session:
        session.execute(text("""
            INSERT INTO management.execution_work
                (run_id, task_id, state, lane, site, capabilities, dedup_key,
                 payload_bytes, payload_size, attempt, available_at, created_at)
            SELECT run_id, 'bulk-' || g, 'completed', lane, site, capabilities,
                'dedup-' || g, payload_bytes, payload_size, 0, available_at, created_at
            FROM management.execution_work, generate_series(1, 20000) g
            WHERE task_id = 'seed'
        """))
        session.execute(text("""
            INSERT INTO management.execution_work_payloads (run_id, task_id, payload_json)
            SELECT run_id, 'bulk-' || g, payload_json
            FROM management.execution_work_payloads, generate_series(1, 20000) g
            WHERE task_id = 'seed'
        """))
        session.execute(text("ANALYZE management.execution_work"))
        session.execute(text("ANALYZE management.execution_work_payloads"))
        plan = "\n".join(session.execute(
            text("EXPLAIN " + _LOCK_ARCHIVE_ROWS.text),
            {"run_id": "job-test", "ids": [f"bulk-{g}" for g in range(1, 2049)]},
        ).scalars())
        session.rollback()
    assert "Seq Scan on execution_work_payloads" not in plan
    assert "Index Scan using execution_work_payloads_pkey" in plan
