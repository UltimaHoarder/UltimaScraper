from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import alembic.command
import pytest
import sqlalchemy.ext.asyncio
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex
from ultima_scraper_backend.api.routes import setup as setup_route
from ultima_scraper_db_archive.alembic_support import normalize_postgresql_reflection
from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates.postgres_site import (
    merged_metadata,
)


@pytest.fixture(autouse=True)
def migration_lock_for_test_loop(monkeypatch):
    monkeypatch.setattr(setup_route, "_migration_session_lock", asyncio.Lock())


def test_site_sort_indexes_are_declared_in_shared_metadata() -> None:
    expected_fragments = {
        "idx_users_created_at": "created_at DESC NULLS LAST",
        "idx_users_downloaded_at_present": (
            "downloaded_at DESC NULLS LAST) WHERE downloaded_at IS NOT NULL"
        ),
        "idx_users_last_checked_coalesce": (
            "coalesce(last_checked_at, updated_at) DESC NULLS LAST"
        ),
        "idx_user_infos_downloaded_at_present": (
            "downloaded_at DESC NULLS LAST) WHERE downloaded_at IS NOT NULL"
        ),
        "idx_user_infos_media_count": "media_count DESC NULLS LAST",
    }
    for schema in ("onlyfans", "fansly", "loyalfans"):
        schema_indexes = {
            index.name: str(
                CreateIndex(index).compile(dialect=postgresql.dialect())
            ).lower()
            for table_name in (f"{schema}.users", f"{schema}.user_infos")
            for index in merged_metadata.tables[table_name].indexes
            if index.name in expected_fragments
        }

        assert set(schema_indexes) == set(expected_fragments)
        for name, fragment in expected_fragments.items():
            assert fragment.lower() in schema_indexes[name]


def test_postgresql_reflection_resets_cached_default_schema() -> None:
    class FakeDialect:
        name = "postgresql"
        default_schema_name = "fansly"

    class FakeConnection:
        dialect = FakeDialect()
        statements: list[str] = []

        def in_transaction(self) -> bool:
            return True

        def exec_driver_sql(self, statement: str) -> None:
            self.statements.append(statement)

    connection = FakeConnection()

    normalize_postgresql_reflection(connection)  # type: ignore[arg-type]

    assert connection.statements == ["SET LOCAL search_path TO public"]
    assert connection.dialect.default_schema_name == "public"


def test_postgresql_reflection_requires_alembic_transaction() -> None:
    class FakeDialect:
        name = "postgresql"

    class FakeConnection:
        dialect = FakeDialect()

        def in_transaction(self) -> bool:
            return False

    with pytest.raises(RuntimeError, match="inside Alembic's transaction"):
        normalize_postgresql_reflection(FakeConnection())  # type: ignore[arg-type]


def test_migration_sanitizer_recognizes_archive_package_encrypted_text() -> None:
    source = (
        "from ultima_scraper_db_archive.crypto import EncryptedText\n"
        "column = ultima_scraper_db_archive.crypto.EncryptedText()\n"
    )

    normalized, changed = setup_route._sanitize_migration_script_text(source)

    assert changed is True
    assert "ultima_scraper_db_archive" not in normalized
    assert "column = sa.TEXT()" in normalized
    assert normalized.startswith("import sqlalchemy as sa\n")


@pytest.mark.asyncio
async def test_applied_revisions_uses_public_version_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []

    class FakeConnection:
        async def execute(self, statement: object) -> list[tuple[str]]:
            statements.append(str(statement))
            return [("d8f4c2a9e631",)]

    class FakeConnectionContext:
        async def __aenter__(self) -> FakeConnection:
            return FakeConnection()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeEngine:
        disposed = False

        def connect(self) -> FakeConnectionContext:
            return FakeConnectionContext()

        async def dispose(self) -> None:
            self.disposed = True

    engine = FakeEngine()
    monkeypatch.setattr(
        sqlalchemy.ext.asyncio,
        "create_async_engine",
        lambda _url: engine,
    )

    revisions = await setup_route._get_applied_revisions(
        "postgresql+asyncpg://unused"
    )

    assert revisions == {"d8f4c2a9e631"}
    assert statements == ["SELECT version_num FROM public.alembic_version"]
    assert engine.disposed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["no_changes", "ready", "requires_database"])
async def test_startup_preview_is_shared_by_concurrent_and_later_tabs(monkeypatch, tmp_path, status):
    monkeypatch.setattr(setup_route, "_migration_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(setup_route, "get_backend_startup_id", lambda: "shared-startup")
    monkeypatch.setattr(setup_route, "_resolve_async_database_url", lambda: "postgresql+asyncpg://unused")
    calls = []
    migration = tmp_path / "revision.py"
    migration.write_text("revision = 'one'\n")

    async def generate():
        calls.append(True)
        await asyncio.sleep(0.01)
        if status == "ready":
            setup_route._save_pending_startup_migration({
                "preview_id": "shared-preview", "file_path": str(migration),
                "delete_on_discard": False,
            })
        return setup_route.StartupMigrationPreviewResponse(
            status=status, message="Shared result", preview_id="shared-preview" if status == "ready" else None,
            diff="# Revision one\n# Revision two", can_apply=status == "ready",
        )

    monkeypatch.setattr(setup_route, "_generate_startup_preview_locked", generate)
    first, second = await asyncio.gather(
        setup_route.preview_startup_migration(), setup_route.preview_startup_migration()
    )
    setup_route._pending_startup_migration = None
    later = await setup_route.preview_startup_migration()
    assert len(calls) == 1
    assert first == second == later


@pytest.mark.asyncio
async def test_startup_result_refreshes_after_restart_target_change_and_explicit_regenerate(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_route, "_migration_runtime_dir", lambda: tmp_path)
    startup = ["startup-one"]
    target = ["postgresql+asyncpg://owner:secret-password@unused/one"]
    monkeypatch.setattr(setup_route, "get_backend_startup_id", lambda: startup[0])
    monkeypatch.setattr(setup_route, "_resolve_async_database_url", lambda: target[0])
    calls = []

    async def generate():
        calls.append(True)
        return setup_route.StartupMigrationPreviewResponse(status="no_changes", message="Checked")

    monkeypatch.setattr(setup_route, "_generate_startup_preview_locked", generate)
    await setup_route.preview_startup_migration()
    await setup_route.preview_startup_migration()
    assert len(calls) == 1
    assert "secret-password" not in setup_route._startup_migration_result_path().read_text()
    startup[0] = "startup-two"
    await setup_route.preview_startup_migration()
    assert len(calls) == 2
    target[0] = "postgresql+asyncpg://unused/two"
    await setup_route.preview_startup_migration()
    assert len(calls) == 3
    await setup_route.regenerate_startup_migration()
    await setup_route.preview_startup_migration()
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_failed_preview_can_be_retried(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_route, "_migration_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(setup_route, "get_backend_startup_id", lambda: "retry-startup")
    monkeypatch.setattr(setup_route, "_resolve_async_database_url", lambda: None)
    statuses = iter(["error", "no_changes"])

    async def generate():
        return setup_route.StartupMigrationPreviewResponse(status=next(statuses), message="Result")

    monkeypatch.setattr(setup_route, "_generate_startup_preview_locked", generate)
    assert (await setup_route.preview_startup_migration()).status == "error"
    assert (await setup_route.preview_startup_migration()).status == "no_changes"
    assert (await setup_route.preview_startup_migration()).status == "no_changes"


@pytest.mark.asyncio
async def test_cancelled_waiter_retains_generation_fence_and_publishes_result(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_route, "_migration_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(setup_route, "get_backend_startup_id", lambda: "cancel-startup")
    monkeypatch.setattr(setup_route, "_resolve_async_database_url", lambda: None)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def generate():
        calls.append(True)
        started.set()
        await release.wait()
        return setup_route.StartupMigrationPreviewResponse(status="no_changes", message="Checked")

    monkeypatch.setattr(setup_route, "_generate_startup_preview_locked", generate)
    first = asyncio.create_task(setup_route.preview_startup_migration())
    await started.wait()
    first.cancel()
    second = asyncio.create_task(setup_route.preview_startup_migration())
    await asyncio.sleep(0)
    assert not second.done()
    assert len(calls) == 1
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert (await second).status == "no_changes"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_skip_is_shared_without_regenerating_a_preview(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_route, "_migration_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(setup_route, "get_backend_startup_id", lambda: "skipped-startup")
    monkeypatch.setattr(setup_route, "_resolve_async_database_url", lambda: None)
    assert (await setup_route.discard_startup_migration()).success
    result = await setup_route.preview_startup_migration()
    assert result.status == "completed"
    assert result.outcome == "skipped"
    assert "skipped" in result.message


def test_separate_api_workers_share_one_schema_check(tmp_path):
    import json
    import subprocess
    import sys

    script = """
import asyncio, json, sys
from pathlib import Path
from ultima_scraper_backend.api.routes import setup
directory = Path(sys.argv[1])
setup._migration_runtime_dir = lambda: directory
setup.get_backend_startup_id = lambda: 'cross-worker-startup'
setup._resolve_async_database_url = lambda: None
async def generate():
    with (directory / 'checks.txt').open('a') as counter:
        counter.write('check\\n')
    await asyncio.sleep(0.1)
    return setup.StartupMigrationPreviewResponse(status='no_changes', message='Checked')
setup._generate_startup_preview_locked = generate
print(asyncio.run(setup.preview_startup_migration()).model_dump_json())
"""
    workers = [subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) for _ in range(2)]
    try:
        for worker in workers:
            output, errors = worker.communicate(timeout=15)
            assert worker.returncode == 0, errors
            assert json.loads(output.splitlines()[-1])["status"] == "no_changes"
        assert (tmp_path / "checks.txt").read_text().splitlines() == ["check"]
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.wait()


def test_pending_migration_state_survives_worker_local_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(setup_route, "_migration_runtime_dir", lambda: tmp_path)
    pending = {
        "preview_id": "preview-from-worker-one",
        "revision": "revision-one",
        "file_path": str(tmp_path / "revision_one.py"),
        "created_at": "2026-08-22T10:00:00+00:00",
        "delete_on_discard": False,
    }

    setup_route._save_pending_startup_migration(pending)
    setup_route._pending_startup_migration = None

    assert setup_route._load_pending_startup_migration() == pending


@pytest.mark.asyncio
async def test_schema_management_endpoints_are_disabled_for_runtime_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        setup_route,
        "runtime_env_value",
        lambda name: "false" if name == "USR_SCHEMA_MANAGEMENT_ENABLED" else None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await setup_route.apply_startup_migration(
            setup_route.StartupMigrationApplyRequest()
        )

    assert exc_info.value.status_code == 403
    assert "dedicated owner-role migration service" in str(exc_info.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [False, True])
async def test_apply_loads_preview_created_by_another_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stale: bool,
) -> None:
    monkeypatch.setattr(setup_route, "_migration_runtime_dir", lambda: tmp_path)
    migration_path = tmp_path / "revision_one.py"
    migration_path.write_text("revision = 'revision-one'\n", encoding="utf-8")
    setup_route._save_pending_startup_migration(
        {
            "preview_id": "preview-from-worker-one",
            "revision": "revision-one",
            "file_path": str(migration_path),
            "created_at": "2026-08-22T10:00:00+00:00",
            "delete_on_discard": True,
        }
    )

    if stale:
        pending = setup_route._load_pending_startup_migration()
        pending.update(review_hash="changed", review_base=[], review_files=[str(migration_path)])
        setup_route._save_pending_startup_migration(pending)

        async def get_applied(_):
            return set()

        monkeypatch.setattr(setup_route, "_get_applied_revisions", get_applied)

    # A different Uvicorn worker has an independent module global.
    setup_route._pending_startup_migration = None
    monkeypatch.setattr(
        setup_route,
        "_resolve_async_database_url",
        lambda: "postgresql+asyncpg://unused",
    )
    alembic_config = object()
    monkeypatch.setattr(
        setup_route,
        "_build_alembic_config",
        lambda _url: alembic_config,
    )
    upgrade_calls: list[tuple[object, str]] = []
    monkeypatch.setattr(
        alembic.command,
        "upgrade",
        lambda config, revision: upgrade_calls.append((config, revision)),
    )

    async def run_inline(function: Any, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    monkeypatch.setattr(setup_route.asyncio, "to_thread", run_inline)

    response = await asyncio.wait_for(
        setup_route.apply_startup_migration(
            setup_route.StartupMigrationApplyRequest(
                preview_id="preview-from-worker-one"
            )
        ),
        timeout=5,
    )

    if stale:
        assert response.success is False
        assert "Refresh preview" in response.message
        assert upgrade_calls == []
        assert setup_route._load_pending_startup_migration() is not None
        return
    assert response.success is True
    assert response.message == "Migration applied successfully."
    assert upgrade_calls == [(alembic_config, "revision-one")]
    assert setup_route._load_pending_startup_migration() is None
    completed = await setup_route.preview_startup_migration()
    assert completed.status == "completed"
    assert completed.outcome == "applied"
    assert upgrade_calls == [(alembic_config, "revision-one")]


@pytest.mark.parametrize("body, expected", [("pass", False), ('"docstring"\n    pass', False), ("perform_partitioning()", True)])
def test_migration_operations_classifies_upgrade_body(body, expected):
    assert setup_route._migration_has_changes(f"def upgrade():\n    {body}\n\ndef downgrade():\n    pass\n") is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("applied, has_changes, count", [({"rootrev"}, True, 3), ({"left", "right"}, False, 1), ({"right"}, True, 2)])
async def test_pending_preview_includes_complete_upgrade_chain(monkeypatch, tmp_path, applied, has_changes, count):
    from alembic.config import Config

    (tmp_path / "runtime").mkdir()
    versions = tmp_path / "versions"
    versions.mkdir()
    for revision, parent, body in [
        ("rootrev", None, "pass"),
        ("left", "rootrev", "perform_partitioning()"),
        ("right", "rootrev", "pass"),
        ("merge", ("left", "right"), "pass"),
    ]:
        (versions / f"{revision}.py").write_text(
            f"revision = {revision!r}\ndown_revision = {parent!r}\nbranch_labels = None\ndepends_on = None\ndef upgrade():\n    {body}\ndef downgrade():\n    pass\n"
        )
    config = Config()
    config.set_main_option("script_location", str(tmp_path))
    monkeypatch.setattr(setup_route, "_build_alembic_config", lambda _: config)
    monkeypatch.setattr(setup_route, "_migration_runtime_dir", lambda: tmp_path / "runtime")

    async def get_applied(_):
        return applied

    monkeypatch.setattr(setup_route, "_get_applied_revisions", get_applied)
    preview = await setup_route._preview_latest_unapplied_migration("unused", output=[])
    assert preview.status == "ready"
    assert preview.revision == "merge"
    assert preview.has_changes is has_changes
    assert preview.diff.count("# Revision ") == count
    assert "merge.py (revision bookkeeping only)" in preview.diff
    if has_changes:
        assert "perform_partitioning()" in preview.diff
        assert preview.diff.index("# Revision left") < preview.diff.index("# Revision merge")
    pending = setup_route._load_pending_startup_migration()
    assert len(pending["review_files"]) == count
    assert pending["review_base"] == sorted(applied)


def _generated_revision_setup(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """A revision the startup check generated, waiting for review."""
    versions = tmp_path / "package" / "versions"
    versions.mkdir(parents=True)
    monkeypatch.setattr(setup_route, "_migration_runtime_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(setup_route, "_get_versions_dir", lambda: versions)
    monkeypatch.setattr(setup_route, "_resolve_async_database_url", lambda: "postgresql+asyncpg://u@db/x")
    monkeypatch.setattr(setup_route, "_require_schema_management_enabled", lambda: None)
    monkeypatch.setattr(setup_route, "_build_alembic_config", lambda _url: object())
    generated = setup_route._pending_revisions_dir() / "abc123_startup_autogen.py"
    generated.write_text("revision = 'abc123'\n", encoding="utf-8")
    setup_route._save_pending_startup_migration(
        {"preview_id": "p1", "revision": "abc123", "file_path": str(generated), "delete_on_discard": True}
    )
    return generated, versions


def test_generated_revisions_wait_outside_the_package(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_route, "_migration_runtime_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(setup_route, "_get_versions_dir", lambda: tmp_path / "versions")

    config = setup_route._build_alembic_config("postgresql+asyncpg://u@db/x")

    locations = config.get_main_option("version_locations").split(":")
    assert locations == [str(tmp_path / "versions"), str(tmp_path / "state" / "pending-revisions")]


async def test_an_applied_revision_joins_the_package(monkeypatch, tmp_path):
    generated, versions = _generated_revision_setup(monkeypatch, tmp_path)
    seen: list[bool] = []
    monkeypatch.setattr(alembic.command, "upgrade", lambda _cfg, _target: seen.append((versions / generated.name).exists()))

    result = await setup_route.apply_startup_migration(setup_route.StartupMigrationApplyRequest(preview_id="p1"))

    assert result.success, result.message
    # In place before the upgrade ran, and not left behind in pending.
    assert seen == [True] and not generated.exists()


async def test_a_failed_apply_keeps_the_revision_out_of_the_package(monkeypatch, tmp_path):
    generated, versions = _generated_revision_setup(monkeypatch, tmp_path)

    def fail(_cfg, _target):
        raise RuntimeError("upgrade failed")

    monkeypatch.setattr(alembic.command, "upgrade", fail)

    result = await setup_route.apply_startup_migration(setup_route.StartupMigrationApplyRequest(preview_id="p1"))

    assert not result.success
    assert generated.exists() and not (versions / generated.name).exists()


async def test_read_only_migrations_refuse_a_generated_revision(monkeypatch, tmp_path):
    generated, versions = _generated_revision_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(alembic.command, "upgrade", lambda *_: pytest.fail("must not upgrade"))
    real_access = setup_route.os.access
    monkeypatch.setattr(setup_route.os, "access", lambda path, mode: False if Path(path) == versions else real_access(path, mode))

    result = await setup_route.apply_startup_migration(setup_route.StartupMigrationApplyRequest(preview_id="p1"))

    assert not result.success and "read-only" in result.message
    assert generated.exists()
