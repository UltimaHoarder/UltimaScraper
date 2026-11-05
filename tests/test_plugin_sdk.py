"""Native plugin persistence, recovery, leases, and ledger execution."""

from __future__ import annotations

import asyncio
import importlib.util
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import ultima_scraper_db_archive

import pytest
import yaml
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_execution_ledger import ledger_engine  # noqa: F401
from test_mps_manifest import postgres_engine  # noqa: F401
from ultima_scraper_backend.plugin_system.platform import PluginPlatform
from ultima_scraper_backend.plugin_system.postgres_repository import (
    PostgresPluginRepository,
)
from ultima_scraper_db_archive.plugin_models import PLUGIN_TABLES


def manifest(**updates):
    data = {
        "manifest_schema_version": 2,
        "plugin_id": "sdk-test",
        "plugin_version": "1.0.0",
        "display_name": "SDK Test",
        "capabilities": ["jobs.submit", "events.read", "webui.extend", "webui.native"],
        "sdk": {
            "access": {
                "task_types": ["sdk-test.predict"],
                "outbound_domains": ["plugin.example"],
            },
            "ui": [],
        },
        "task_types": [
            {
                "task_type": "sdk-test.predict",
                "input_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
                "handler": {"kind": "http", "url": "https://plugin.example/predict"},
            }
        ],
        "event_subscriptions": [
            {
                "event_family": "job.lifecycle",
                "event_types": ["job.completed"],
                "delivery_target": "events",
            }
        ],
        "outbound_deliveries": [
            {"target_name": "events", "url": "https://plugin.example/events"}
        ],
        "operational_policy": {
            "retry_policy": {"initial_backoff_seconds": 1, "max_retries": 2}
        },
        "webui": {"mode": "native", "entry": "webui.js"},
    }
    data.update(updates)
    return data


@pytest.fixture(scope="module")
def plugin_engine(ledger_engine):  # noqa: F811
    from ultima_scraper_db_archive.global_db import BackendInventoryModel, SettingsModel

    migration_path = (
        Path(ultima_scraper_db_archive.__file__).parent / "migrations/alembic/versions/d2a70c16f493_add_plugin_runtime.py"
    )
    spec = importlib.util.spec_from_file_location("plugin_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with ledger_engine.begin() as connection:
        SettingsModel.__table__.create(connection, checkfirst=True)
        BackendInventoryModel.__table__.create(connection, checkfirst=True)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
    return ledger_engine


@pytest.fixture
def repository(plugin_engine):
    with plugin_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE management.execution_outbox, management.execution_resources, management.execution_attempts, management.execution_work, management.execution_runs, management.execution_definitions, management.mps_retry_tasks, management.mps_task_definitions, management.mps_candidate_ranges, management.mps_plans, management.job_tasks, management.jobs, management.database_write_receipts CASCADE"
            )
        )
        connection.execute(text("UPDATE management.execution_feed SET next_sequence=1"))
        for table in reversed(PLUGIN_TABLES):
            if table.name != "plugin_repository_meta":
                connection.execute(table.delete())
        connection.execute(
            text(
                "DELETE FROM management.plugin_repository_meta WHERE key != 'schema_version'"
            )
        )

    @contextmanager
    def sessions():
        with Session(plugin_engine) as session:
            yield session

    return PostgresPluginRepository(sessions)


@pytest.fixture
def platform(repository, tmp_path):
    directory = tmp_path / "sdk-test"
    directory.mkdir()
    (directory / "manifest.yaml").write_text(yaml.safe_dump(manifest()))
    (directory / "webui.js").write_text("window.testPluginVersion = 1;")
    platform = PluginPlatform(tmp_path, repository=repository)
    platform.load_all()
    platform.enable_plugin("sdk-test")
    return platform


def envelope(identity="event-1"):
    return {
        "event_id": identity,
        "event_family": "job.lifecycle",
        "event_type": "job.completed",
        "plugin_id": "sdk-test",
        "body": {"job_id": "job-a"},
    }


def enqueue(platform, identity="event-1", **kwargs):
    return platform.repository.enqueue_deliveries(
        "sdk-test",
        [("events", envelope(identity))],
        manifest=platform.registry.get("sdk-test").manifest.model_dump(mode="json"),
        **kwargs,
    )


def test_delivery_fanout_deduplicates_and_commits_cursor_atomically(platform):
    repository = platform.repository
    assert repository.cursor("sdk-test") == 0
    assert enqueue(platform, sequence=12, expected_cursor=0)
    assert repository.cursor("sdk-test") == 12
    enqueue(platform)
    assert repository.queue_health("sdk-test")["pending"] == 1


def test_backlog_rolls_back_cursor_and_entire_fanout(platform):
    from ultima_scraper_backend.plugin_system.durable_repository import (
        PluginBacklogFull,
    )

    data = manifest()
    data["operational_policy"]["max_pending_deliveries"] = 1
    platform.repository.cursor("sdk-test")
    with pytest.raises(PluginBacklogFull):
        platform.repository.enqueue_deliveries(
            "sdk-test",
            [("events", envelope("a")), ("events", envelope("b"))],
            data,
            sequence=2,
            expected_cursor=0,
        )
    assert platform.repository.cursor("sdk-test") == 0
    assert platform.repository.queue_health("sdk-test")["pending"] == 0


def test_two_supervisors_cannot_claim_the_same_delivery(platform):
    enqueue(platform)
    with ThreadPoolExecutor(max_workers=2) as workers:
        claims = list(
            workers.map(
                lambda _: platform.repository.claim_delivery("sdk-test"), range(2)
            )
        )
    assert sum(claim is not None for claim in claims) == 1


def test_restart_resumes_retry_and_rejects_old_claim(platform):
    repository = platform.repository
    enqueue(platform)
    old = repository.claim_delivery("sdk-test")
    with repository._connect() as connection:
        connection.execute(
            "UPDATE plugin_delivery_queue SET lease_until=?",
            ((repository.now() - timedelta(seconds=1)).isoformat(),),
        )
    restarted = PostgresPluginRepository(repository.session_factory)
    new = restarted.claim_delivery("sdk-test")
    assert new["lease_token"] != old["lease_token"]
    assert not repository.finish_delivery(old["delivery_id"], old["lease_token"])
    assert restarted.finish_delivery(
        new["delivery_id"],
        new["lease_token"],
        error="Unavailable",
        retry_at=restarted.now().isoformat(),
    )
    assert (
        PostgresPluginRepository(repository.session_factory).claim_delivery("sdk-test")[
            "attempts"
        ]
        == 3
    )


def test_expired_supervisor_cannot_renew_after_takeover(repository):
    old = repository.acquire_lease("runtime", "old")
    assert repository.acquire_lease("runtime", "new") is None
    with repository._connect() as connection:
        connection.execute(
            "UPDATE plugin_runtime_leases SET lease_until=?",
            ((repository.now() - timedelta(seconds=1)).isoformat(),),
        )
    new = repository.acquire_lease("runtime", "new")
    assert new is not None
    assert repository.acquire_lease("runtime", "old", token=old) is None
    repository.release_lease("runtime", old)
    assert repository.acquire_lease("runtime", "new", token=new) == new


@pytest.mark.asyncio
async def test_coordinator_stops_owned_work_after_postgres_lease_takeover(
    repository, tmp_path
):
    from types import SimpleNamespace

    from ultima_scraper_backend.plugin_system.runtime_owner import (
        PluginRuntimeCoordinator,
        PluginRuntimeOwnershipLost,
    )

    started = asyncio.Event()
    stopped = asyncio.Event()
    platform = SimpleNamespace(repository=repository, _runtime_started=False)

    async def start_runtime():
        platform._runtime_started = True
        started.set()

    async def stop_runtime():
        platform._runtime_started = False
        stopped.set()

    platform.start_runtime = start_runtime
    platform.stop_runtime = stop_runtime
    coordinator = PluginRuntimeCoordinator(platform, tmp_path, election_interval=0.01)
    renewal_entered = asyncio.Event()
    renewal_allowed = threading.Event()
    loop = asyncio.get_running_loop()
    acquire = coordinator.ownership.try_acquire
    acquisitions = 0

    def gated_renewal():
        nonlocal acquisitions
        if acquisitions:
            loop.call_soon_threadsafe(renewal_entered.set)
            assert renewal_allowed.wait(5)
        acquisitions += 1
        return acquire()

    coordinator.ownership.try_acquire = gated_renewal
    coordinator.start()
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        await asyncio.wait_for(renewal_entered.wait(), timeout=5)
        with repository._connect() as connection:
            connection.execute(
                "UPDATE plugin_runtime_leases SET lease_until=? WHERE resource_key='plugin-supervisor'",
                ((repository.now() - timedelta(seconds=1)).isoformat(),),
            )
        takeover = repository.acquire_lease("plugin-supervisor", "replacement")
        assert takeover is not None
        renewal_allowed.set()
        with pytest.raises(PluginRuntimeOwnershipLost):
            await asyncio.wait_for(coordinator._task, timeout=5)
        assert stopped.is_set()
        assert not platform._runtime_started
        assert (
            repository.acquire_lease("plugin-supervisor", "replacement", token=takeover)
            == takeover
        )
    finally:
        renewal_allowed.set()
        await asyncio.gather(coordinator.stop(), return_exceptions=True)


def test_disable_revokes_identity_and_pauses_deliveries(platform):
    token = platform.repository.issue_api_token("sdk-test")
    assert platform.repository.authenticate_api_token(token) == "sdk-test"
    enqueue(platform)
    platform.disable_plugin("sdk-test")
    assert platform.repository.authenticate_api_token(token) is None
    assert platform.repository.claim_delivery("sdk-test") is None
    assert platform.repository.queue_health("sdk-test")["pending"] == 1


def test_upgrade_requires_permission_review_and_preserves_pinned_assets(platform):
    old = platform.package_digest(platform.registry.get("sdk-test"))
    source = platform._plugins_dir / "sdk-test" / "webui.js"
    source.write_text("window.testPluginVersion = 2;")
    updated = manifest(plugin_version="2.0.0")
    updated["sdk"]["access"]["outbound_domains"].append("second.example")
    staged = platform.stage_upgrade("sdk-test", updated)
    assert staged["scope_changes"]
    assert platform.package_digest(platform.registry.get("sdk-test")) == old
    with pytest.raises(PermissionError):
        platform.activate_upgrade("sdk-test", staged["package_digest"])
    platform.activate_upgrade(
        "sdk-test", staged["package_digest"], approve_permissions=True
    )
    assert platform.registry.get("sdk-test").manifest.plugin_version == "2.0.0"
    assert (
        (platform.package_directory("sdk-test", old) / "webui.js")
        .read_text()
        .endswith("= 1;")
    )
    platform.rollback_package("sdk-test")
    assert platform.registry.get("sdk-test").manifest.plugin_version == "1.0.0"


def test_plugin_job_is_real_and_idempotent(platform):
    first = platform.submit_execution(
        "sdk-test", "sdk-test.predict", {"value": 7}, idempotency_key="same"
    )
    second = platform.submit_execution(
        "sdk-test", "sdk-test.predict", {"value": 7}, idempotency_key="same"
    )
    assert first["job_id"] == second["job_id"] and second["reused"]
    with pytest.raises(ValueError, match="Idempotency"):
        platform.submit_execution(
            "sdk-test", "sdk-test.predict", {"value": 9}, idempotency_key="same"
        )
    from ultima_scraper_backend.job_system.ledger import ExecutionLedger

    ledger = ExecutionLedger(platform.repository.session_factory)
    assert ledger.job(first["job_id"]) is not None


def test_missing_plugin_schema_has_an_actionable_error(plugin_engine):
    from ultima_scraper_backend.plugin_system.postgres_repository import (
        PluginSchemaNotReady,
    )

    with plugin_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE management.plugin_repository_meta RENAME TO plugin_repository_meta_saved"
            )
        )
    try:

        @contextmanager
        def sessions():
            with Session(plugin_engine) as session:
                yield session

        with pytest.raises(PluginSchemaNotReady, match="d2a70c16f493"):
            PostgresPluginRepository(sessions)
    finally:
        with plugin_engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE management.plugin_repository_meta_saved RENAME TO plugin_repository_meta"
                )
            )


def test_activation_uses_database_authority_when_catalog_write_fails(
    platform, monkeypatch
):
    token = platform.repository.issue_api_token("sdk-test")
    candidate = manifest(plugin_version="1.1.0")
    candidate["operational_policy"]["state_quota_bytes"] = 4096
    candidate["task_types"][0]["handler"]["auth_scope"] = "predict-service"
    staged = platform.stage_upgrade("sdk-test", candidate)

    def deny_write(*_args):
        raise OSError("read-only source catalog")

    monkeypatch.setattr(platform, "_write_manifest_atomically", deny_write)
    platform.activate_upgrade("sdk-test", staged["package_digest"])
    assert platform.repository.authenticate_api_token(token) is None
    assert platform.repository.get_quota("sdk-test", 0) == 4096
    assert platform.secrets.get_raw_secret("sdk-test", "task", "predict-service")
    active_yaml = platform.get_plugin_manifest_yaml("sdk-test")["manifest_yaml"]
    assert yaml.safe_load(active_yaml)["plugin_version"] == "1.1.0"
    restarted = PluginPlatform(platform._plugins_dir, repository=platform.repository)
    restarted.load_all()
    assert restarted.registry.get("sdk-test").manifest.plugin_version == "1.1.0"


def test_package_snapshot_preserves_executable_mode_and_reserves_manifest(platform):
    source = platform._plugins_dir / "sdk-test" / "runner.sh"
    source.write_text("#!/bin/sh\nexit 0\n")
    source.chmod(0o644)
    first = platform.stage_upgrade("sdk-test", manifest())["package_digest"]
    source.chmod(0o755)
    second = platform.stage_upgrade("sdk-test", manifest())["package_digest"]
    assert first != second
    packaged = platform.package_directory("sdk-test", second) / "runner.sh"
    assert packaged.stat().st_mode & 0o111
    assert not packaged.stat().st_mode & 0o222
    (source.parent / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="reserved"):
        platform.stage_upgrade("sdk-test", manifest())


@pytest.mark.asyncio
async def test_complete_plugin_job_through_sql_attempt_and_archive(platform):
    from ultima_scraper_backend.database.threads import run_database_call
    from ultima_scraper_backend.job_system.ledger import ExecutionLedger
    from ultima_scraper_backend.plugin_system.execution import PluginTaskRunner
    from ultima_scraper_backend.plugin_system.http_transport import HTTPResponse

    async def request(*args, **kwargs):
        return HTTPResponse(200, b'{"value":8}')

    platform._http_request = request
    platform._uses_default_http_transport = False
    submitted = platform.submit_execution(
        "sdk-test", "sdk-test.predict", {"value": 7}, idempotency_key="archive"
    )
    ledger = ExecutionLedger(platform.repository.session_factory)
    await run_database_call(ledger.tick)
    claim = await run_database_call(
        ledger.claim,
        owner="plugin-worker",
        backend_id="default",
        capabilities=["plugin", "plugin:sdk-test"],
        lane="plugin",
    )
    assert claim is not None
    await PluginTaskRunner(platform, ledger=ledger).execute(claim)
    await run_database_call(ledger.tick)
    archived = ledger.task(submitted["job_id"], claim.task_id)
    assert archived["result"]["output"] == {"value": 8}


def test_sqlite_import_retains_original_and_encrypted_secret(repository, tmp_path):
    from ultima_scraper_backend.plugin_system.repository import PluginRepository

    local = PluginRepository(tmp_path / "plugin-runtime.sqlite3")
    local.set_plugin_enabled("legacy-plugin", True)
    local.replace_grants("legacy-plugin", {"events.read"})
    local.upsert_secret_payload(
        {
            "plugin_id": "legacy-plugin",
            "scope_kind": "outbound",
            "scope_name": "events",
            "active_secret_value": "enc:v1:test",
        }
    )
    imported = PostgresPluginRepository(
        repository.session_factory, legacy_runtime_dir=tmp_path
    )
    assert imported.list_enabled_plugins() == {"legacy-plugin"}
    assert (
        imported.list_secret_payloads("legacy-plugin")[0]["active_secret_value"]
        == "enc:v1:test"
    )
    assert local.database_path.is_file()
    assert PostgresPluginRepository(
        repository.session_factory, legacy_runtime_dir=tmp_path
    ).get_grants("legacy-plugin") == {"events.read"}


@pytest.mark.asyncio
async def test_revoked_task_scope_blocks_a_pinned_package(platform):
    from ultima_scraper_backend.plugin_system.execution import invoke_task

    digest = platform.package_digest(platform.registry.get("sdk-test"))
    grants = platform.repository.get_document("plugin_scope_grants", "sdk-test")
    grants["task_types"] = []
    platform.repository.set_document("plugin_scope_grants", "sdk-test", grants)
    with pytest.raises(PermissionError, match="approved scope"):
        await invoke_task(
            platform, "sdk-test", "sdk-test.predict", {"value": 8}, digest=digest
        )


def test_runtime_token_cannot_impersonate_or_access_ungranted_state(platform):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ultima_scraper_backend.plugin_system.api_routes import router

    candidate = manifest()
    candidate["capabilities"] += ["state.read", "state.write"]
    candidate["sdk"]["access"]["state_keys"] = ["checkpoint"]
    staged = platform.stage_upgrade("sdk-test", candidate)
    platform.activate_upgrade(
        "sdk-test", staged["package_digest"], approve_permissions=True
    )
    app = FastAPI()
    app.state.plugin_platform = platform
    app.include_router(router)
    headers = {
        "Authorization": "Bearer " + platform.repository.issue_api_token("sdk-test")
    }
    with TestClient(app) as client:
        assert (
            client.put(
                "/plugins/runtime/state",
                headers=headers,
                json={"key": "checkpoint", "value": {"offset": 4}},
            ).status_code
            == 200
        )
        assert client.get("/plugins/runtime/state/checkpoint", headers=headers).json()[
            "value"
        ] == {"offset": 4}
        assert (
            client.get("/plugins/runtime/state/private", headers=headers).status_code
            == 403
        )
        assert (
            client.post(
                "/plugins/runtime/jobs",
                headers=headers,
                json={
                    "plugin_id": "another",
                    "task_type": "sdk-test.predict",
                    "payload": {"value": 8},
                },
            ).status_code
            == 403
        )
        assert client.get("/plugins/runtime/state/checkpoint").status_code == 401
        platform.disable_plugin("sdk-test")
        assert (
            client.get("/plugins/runtime/state/checkpoint", headers=headers).status_code
            == 401
        )
    assert platform.get_state_audit("sdk-test")[-1]["actor"] == "plugin:sdk-test"


def test_profile_broker_projects_only_approved_fields(platform, plugin_engine):
    candidate = manifest()
    candidate["capabilities"] += ["profiles.read"]
    candidate["sdk"]["access"]["profile_fields"] = ["name", "site"]
    staged = platform.stage_upgrade("sdk-test", candidate)
    platform.activate_upgrade(
        "sdk-test", staged["package_digest"], approve_permissions=True
    )
    with plugin_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS onlyfans.user_infos (user_id bigint PRIMARY KEY, name text, description text)"
            )
        )
        connection.execute(
            text("INSERT INTO onlyfans.users(id) VALUES(112) ON CONFLICT DO NOTHING")
        )
        connection.execute(
            text(
                "INSERT INTO onlyfans.user_infos(user_id,name,description) VALUES(112,'Creator','private bio') ON CONFLICT DO NOTHING"
            )
        )
    assert platform.scoped_profile("sdk-test", "onlyfans", 112) == {
        "name": "Creator",
        "site": "onlyfans",
    }
    with pytest.raises(ValueError, match="Unknown"):
        platform.scoped_profile("sdk-test", 'onlyfans"; DROP TABLE users', 112)


@pytest.mark.asyncio
async def test_delivery_runtime_retries_with_same_identity_after_restart(platform):
    from ultima_scraper_backend.plugin_system.durable_delivery import (
        DurableDeliveryRuntime,
    )

    statuses = [503, 204]
    headers = []

    async def post(url, body, request_headers):
        headers.append(request_headers)
        return statuses.pop(0)

    platform.delivery._http_post = post
    platform._uses_default_http_transport = False
    enqueue(platform)
    await DurableDeliveryRuntime(platform).deliver_once()
    assert platform.repository.queue_health("sdk-test")["counts"]["retry"] == 1
    with platform.repository._connect() as connection:
        connection.execute(
            "UPDATE plugin_delivery_queue SET available_at=?",
            (platform.repository.now().isoformat(),),
        )
    await DurableDeliveryRuntime(platform).deliver_once()
    assert platform.repository.queue_health("sdk-test")["counts"]["delivered"] == 1
    assert headers[0]["Idempotency-Key"] == headers[1]["Idempotency-Key"]


@pytest.mark.asyncio
async def test_durable_feed_keeps_cursor_when_fanout_is_full(platform):
    from types import SimpleNamespace

    from ultima_scraper_backend.plugin_system.durable_delivery import (
        DurableDeliveryRuntime,
    )

    data = manifest()
    data["operational_policy"]["max_pending_deliveries"] = 1
    staged = platform.stage_upgrade("sdk-test", data)
    platform.activate_upgrade("sdk-test", staged["package_digest"])
    enqueue(platform)
    raw = {
        "sequence": 7,
        "event_id": "ledger-event-7",
        "event_type": "job_completed",
        "job_id": "job-b",
        "data": {"job_id": "job-b"},
    }
    runtime = DurableDeliveryRuntime(
        platform,
        ledger=SimpleNamespace(event_head=lambda: 7, events=lambda **kwargs: [raw]),
    )
    platform._normalize_local_job_event = lambda event: {
        "lifecycle_event": "completed",
        "job_id": event["job_id"],
    }
    await runtime.consume_once()
    assert platform.repository.cursor("sdk-test") == 0
    item = platform.repository.claim_delivery("sdk-test")
    platform.repository.finish_delivery(item["delivery_id"], item["lease_token"])
    await runtime.consume_once()
    assert platform.repository.cursor("sdk-test") == 7
    assert platform.repository.queue_health("sdk-test")["pending"] == 1


@pytest.mark.asyncio
async def test_durable_feed_advances_past_undelivered_events_in_one_commit(platform):
    from types import SimpleNamespace

    from ultima_scraper_backend.plugin_system.durable_delivery import (
        DurableDeliveryRuntime,
    )

    data = manifest()
    staged = platform.stage_upgrade("sdk-test", data)
    platform.activate_upgrade("sdk-test", staged["package_digest"])
    enqueue(platform)
    # Only sequence 6 is a lifecycle event this plugin receives.
    events = [
        {"sequence": n, "event_id": f"ledger-event-{n}", "job_id": "job-b",
         "event_type": "job_completed" if n == 6 else "task_completed"}
        for n in range(1, 9)
    ]
    runtime = DurableDeliveryRuntime(
        platform,
        ledger=SimpleNamespace(event_head=lambda: 8, events=lambda **kwargs: events),
    )
    platform._normalize_local_job_event = lambda event: (
        {"lifecycle_event": "completed", "job_id": event["job_id"]}
        if event["event_type"] == "job_completed" else None
    )
    commits = []
    original = platform.repository.enqueue_deliveries

    def counted(plugin_id, deliveries, manifest_json, **kwargs):
        commits.append((len(deliveries), kwargs["sequence"]))
        return original(plugin_id, deliveries, manifest_json, **kwargs)

    platform.repository.enqueue_deliveries = counted
    assert await runtime.consume_once() is False  # 8 events is not a full page
    assert [sequence for _, sequence in commits] == [5, 6, 8]
    assert commits[1][0] > 0 and commits[0][0] == commits[2][0] == 0
    assert platform.repository.cursor("sdk-test") == 8


@pytest.mark.asyncio
async def test_trusted_process_uses_pinned_code_and_revokes_its_broker_token(
    platform, monkeypatch
):
    import sys

    from ultima_scraper_backend.plugin_system.execution import invoke_task

    source = platform._plugins_dir / "sdk-test" / "runner.py"
    source.write_text(
        "import json, os, sys\nrequest = json.loads(sys.stdin.readline())\nassert 'HOST_PRIVATE_CREDENTIAL' not in os.environ\nassert request['broker']['token']\nprint(json.dumps({'value': 1}))\n"
    )
    monkeypatch.setenv("HOST_PRIVATE_CREDENTIAL", "fake-host-credential")
    candidate = manifest(plugin_version="1.1.0")
    candidate["capabilities"].append("runtime.process")
    candidate["task_types"][0]["handler"] = {
        "kind": "process",
        "command": [sys.executable, "runner.py"],
        "timeout_seconds": 1,
    }
    staged = platform.stage_upgrade("sdk-test", candidate)
    platform.activate_upgrade(
        "sdk-test", staged["package_digest"], approve_permissions=True
    )
    old = staged["package_digest"]
    source.write_text("import json; print(json.dumps({'value': 2}))")
    candidate["plugin_version"] = "1.2.0"
    updated = platform.stage_upgrade("sdk-test", candidate)
    platform.activate_upgrade("sdk-test", updated["package_digest"])
    assert await invoke_task(
        platform, "sdk-test", "sdk-test.predict", {"value": 8}, digest=old
    ) == {"value": 1}
    with platform.repository._connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS total FROM plugin_api_tokens"
            ).fetchone()["total"]
            == 0
        )


@pytest.mark.asyncio
async def test_process_deadline_cleans_up_broker_identity(platform):
    import sys

    from ultima_scraper_backend.plugin_system.execution import invoke_task

    candidate = manifest()
    candidate["capabilities"].append("runtime.process")
    candidate["task_types"][0]["handler"] = {
        "kind": "process",
        "command": [sys.executable, "-c", "import time; time.sleep(30)"],
        "timeout_seconds": 1,
    }
    staged = platform.stage_upgrade("sdk-test", candidate)
    platform.activate_upgrade(
        "sdk-test", staged["package_digest"], approve_permissions=True
    )
    with pytest.raises(TimeoutError):
        await invoke_task(platform, "sdk-test", "sdk-test.predict", {"value": 8})
    with platform.repository._connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS total FROM plugin_api_tokens"
            ).fetchone()["total"]
            == 0
        )


@pytest.mark.asyncio
async def test_process_spawn_failure_revokes_broker_identity(platform):
    from ultima_scraper_backend.plugin_system.execution import invoke_task

    candidate = manifest()
    candidate["capabilities"].append("runtime.process")
    candidate["task_types"][0]["handler"] = {
        "kind": "process",
        "command": ["./missing-plugin-runner"],
    }
    staged = platform.stage_upgrade("sdk-test", candidate)
    platform.activate_upgrade(
        "sdk-test", staged["package_digest"], approve_permissions=True
    )
    with pytest.raises(FileNotFoundError):
        await invoke_task(platform, "sdk-test", "sdk-test.predict", {"value": 8})
    with platform.repository._connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS total FROM plugin_api_tokens"
            ).fetchone()["total"]
            == 0
        )


@pytest.mark.asyncio
async def test_http_transport_enforces_an_overall_deadline_and_closes_stream(
    monkeypatch,
):
    import asyncio

    import httpx
    from ultima_scraper_backend.plugin_system.http_transport import default_http_request

    closed = []

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(30)
            yield b"{}"

        async def aclose(self):
            closed.append(True)

    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=SlowStream())
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )
    with pytest.raises(TimeoutError):
        await default_http_request(
            "POST", "https://plugin.example/predict", b"{}", {}, timeout=0.02
        )
    assert closed == [True]


@pytest.mark.asyncio
async def test_http_transport_does_not_follow_redirects_and_bounds_response(
    monkeypatch,
):
    import httpx
    from ultima_scraper_backend.plugin_system.http_transport import default_http_request

    original = httpx.AsyncClient
    responses = [
        httpx.Response(302, headers={"Location": "https://elsewhere.example"}),
        httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)),
    ]
    requests = []

    def response(request):
        requests.append(request)
        return responses.pop(0)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(response), **kwargs),
    )
    result = await default_http_request(
        "POST", "https://plugin.example/predict", b"{}", {}
    )
    assert result.status_code == 302 and len(requests) == 1
    with pytest.raises(ValueError, match="response exceeds"):
        await default_http_request("POST", "https://plugin.example/predict", b"{}", {})
