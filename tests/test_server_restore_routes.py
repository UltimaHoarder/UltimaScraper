import asyncio
import fcntl
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from ultima_scraper_backend.api.routes import server_restore as routes
from ultima_scraper_backend.config import DownloadPathSetup, Drive
from ultima_scraper_backend.services import server_restore_workspace as workspace, archive_write_guard


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "ROOT", tmp_path / "reviews")
    monkeypatch.setattr(routes, "_tasks", {}, raising=False)
    monkeypatch.setattr(archive_write_guard, "LOCK_ROOT", tmp_path / "writer-locks")
    def launch(store, identifier, global_lock, review_lock):
        async def run():
            try:
                await asyncio.to_thread(workspace.run, store, identifier)
            finally:
                review_lock.close()
                global_lock.close()
        routes._tasks[identifier] = asyncio.create_task(run())
    monkeypatch.setattr(routes, "_launcher", launch)
    server = tmp_path / "server" / "OnlyFans Vault"
    (server / "S" / "samplecreator").mkdir(parents=True)
    source = tmp_path / "drive" / "OnlyFans" / "S" / "samplecreator"
    source.mkdir(parents=True)
    (source / "file").write_bytes(b"media")
    setup = DownloadPathSetup(
        drives=[Drive(directories=[server.parent, tmp_path / "drive"])],
        site_directory_aliases={"onlyfans": ["OnlyFans Vault"]},
    )
    return (
        server,
        source,
        SimpleNamespace(settings=SimpleNamespace(download_setup=setup)),
    )


async def finish():
    await asyncio.gather(*list(routes._tasks.values()))


@pytest.mark.asyncio
async def test_scan_plan_review_and_explicit_apply(storage, monkeypatch):
    server, source, config = storage
    scanned = await routes.create_scan(routes.ScanRequest(server=str(server)), config)
    await finish()
    assert routes.state(scanned["id"])["summary"]["matched_performers"] == 1
    planned = await routes.create_plan(
        routes.PlanRequest(scan_id=scanned["id"], performers=["samplecreator"])
    )
    await finish()
    review = routes.state(planned["id"])
    assert review["summary"]["counts"] == {"move": 1}
    page = await routes.rows(planned["id"], offset=0, limit=50)
    assert page["total"] == 1
    assert Path(page["rows"][0]["source"]).parent == source
    called = []
    monkeypatch.setattr(workspace, "apply_plan", lambda plan, journal, **kwargs: None if kwargs.get("validate_only") else called.append(plan))
    with pytest.raises(HTTPException, match="409"):
        await routes.apply_review(
            routes.ApplyRequest(
                plan_id=planned["id"], approved_sha256="wrong", writers_paused=True
            )
        )
    with pytest.raises(HTTPException, match="409"):
        await routes.apply_review(
            routes.ApplyRequest(
                plan_id=planned["id"],
                approved_sha256=review["sha256"],
                writers_paused=False,
            )
        )
    assert not called
    applied = await routes.apply_review(
        routes.ApplyRequest(
            plan_id=planned["id"], approved_sha256=review["sha256"], writers_paused=True
        )
    )
    await finish()
    assert routes.state(applied["id"])["status"] == "completed"
    assert len(called) == 1
    with pytest.raises(HTTPException, match="409"):
        await routes.apply_review(
            routes.ApplyRequest(
                plan_id=planned["id"],
                approved_sha256=review["sha256"],
                writers_paused=True,
            )
        )


@pytest.mark.asyncio
async def test_scan_rejects_unconfigured_root(storage):
    _server, source, config = storage
    with pytest.raises(HTTPException, match="400"):
        await routes.create_scan(routes.ScanRequest(server=str(source)), config)


@pytest.mark.asyncio
async def test_busy_operation_and_interrupted_review(storage):
    server, _source, config = storage
    await routes.create_scan(routes.ScanRequest(server=str(server)), config)
    with pytest.raises(HTTPException, match="409"):
        await routes.create_scan(routes.ScanRequest(server=str(server)), config)
    await finish()
    routes._tasks.clear()
    identifier = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    routes.save(
        routes.directory(identifier) / "state.json",
        {"id": identifier, "kind": "plan", "status": "running"},
    )
    assert routes.state(identifier)["status"] == "interrupted"
    with pytest.raises(HTTPException, match="409"):
        routes.load_result(identifier, "plan")


@pytest.mark.asyncio
async def test_other_worker_observes_active_review_and_cannot_start(storage, monkeypatch):
    server, _source, config = storage
    identifier = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
    routes.save(routes.directory(identifier) / "state.json", {
        "id": identifier, "kind": "plan", "status": "running",
    })
    with (routes.ROOT / "operation.lock").open("a") as global_lock, (routes.directory(identifier) / "operation.lock").open("a") as review_lock:
        fcntl.flock(global_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(review_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert routes.state(identifier)["status"] == "running"
        with pytest.raises(HTTPException, match="409"):
            await routes.create_scan(routes.ScanRequest(server=str(server)), config)
    assert routes.state(identifier)["status"] == "interrupted"
    scanned = await routes.create_scan(routes.ScanRequest(server=str(server)), config)
    await finish()
    assert routes.state(scanned["id"])["status"] == "completed"
    assert not workspace.locked(routes.ROOT / "operation.lock")


@pytest.mark.asyncio
async def test_stop_is_durable_without_overwriting_worker_state(storage):
    identifier = "cccccccc-cccc-4ccc-cccc-cccccccccccc"
    original = {"id": identifier, "kind": "scan", "status": "running", "progress": "Scanning a root"}
    routes.save(routes.directory(identifier) / "state.json", original)
    with (routes.directory(identifier) / "operation.lock").open("a") as review_lock:
        fcntl.flock(review_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        response = await routes.stop_review(identifier)
        assert response["status"] == "running"
        assert (routes.directory(identifier) / "stop.json").exists()
        assert routes.state(identifier) == original
    with pytest.raises(HTTPException, match="409"):
        await routes.stop_review(identifier)


def test_review_id_cannot_escape_storage(storage):
    with pytest.raises(HTTPException, match="400"):
        routes.directory("../../outside")


@pytest.mark.asyncio
async def test_duplicate_only_plan_can_be_applied(storage, monkeypatch):
    server, source, config = storage
    destination = server / "S" / "samplecreator" / "file"
    destination.write_bytes(b"media")
    import os

    for path in (destination, source / "file"):
        os.utime(path, ns=(1000000000, 1000000000))
    scanned = await routes.create_scan(routes.ScanRequest(server=str(server)), config)
    await finish()
    planned = await routes.create_plan(
        routes.PlanRequest(
            scan_id=scanned["id"],
            performers=["samplecreator"],
            remove_duplicates=True,
            cleanup_empty=True,
        )
    )
    await finish()
    review = routes.state(planned["id"])
    assert review["summary"]["counts"] == {"remove_duplicate": 1}
    assert review["summary"]["move_bytes"] == 0
    called = []
    monkeypatch.setattr(workspace, "apply_plan", lambda plan, journal, **kwargs: None if kwargs.get("validate_only") else called.append(plan))
    await routes.apply_review(
        routes.ApplyRequest(
            plan_id=planned["id"], approved_sha256=review["sha256"], writers_paused=True
        )
    )
    await finish()
    assert len(called) == 1


@pytest.mark.asyncio
async def test_performer_failure_does_not_stop_other_performers(storage, monkeypatch):
    server, source, config = storage
    (server / "S" / "second").mkdir()
    second = source.parent / "second"
    second.mkdir()
    (second / "file").write_bytes(b"media")
    scanned = await routes.create_scan(routes.ScanRequest(server=str(server)), config)
    await finish()
    planned = await routes.create_plan(routes.PlanRequest(scan_id=scanned["id"], performers=["samplecreator", "second"]))
    await finish()
    called = []
    def apply(subset, journal, **kwargs):
        if kwargs.get("validate_only"):
            return
        called.append(subset["entries"][0]["performer"])
        if len(called) == 1:
            raise ValueError("test failure")
    monkeypatch.setattr(workspace, "apply_plan", apply)
    job = await routes.apply_review(routes.ApplyRequest(plan_id=planned["id"], approved_sha256=routes.state(planned["id"])["sha256"], writers_paused=True))
    await finish()
    result = routes.state(job["id"])
    assert len(called) == 2
    assert [item["status"] for item in result["outcomes"]] == ["failed", "completed"]
    assert result["scan_id"] == scanned["id"]


@pytest.mark.asyncio
async def test_session_preflight_filtering_and_exact_timestamp_evidence(storage):
    server, source, config = storage
    listed = await routes.archives(config)
    assert str(server) in {item["path"] for item in listed["archives"]}
    scanned = await routes.create_scan(routes.ScanRequest(server=str(server)), config)
    await finish()
    planned = await routes.create_plan(routes.PlanRequest(scan_id=scanned["id"], performers=["samplecreator"]))
    await finish()
    page = await routes.performers(planned["id"], offset=0, limit=50, search="SAMPLE")
    assert page["total"] == 1 and page["rows"][0]["counts"] == {"restore": 1}
    files = await routes.rows(planned["id"], offset=0, limit=50, performer="SAMPLECREATOR", action="restore")
    assert files["total"] == 1
    assert files["rows"][0]["source_snapshot"]["mtime_ns_exact"] == str((source / "file").stat().st_mtime_ns)
    ready = await routes.create_preflight(routes.PreflightRequest(plan_id=planned["id"], approved_sha256=routes.state(planned["id"])["sha256"]))
    await finish()
    assert routes.state(ready["id"])["summary"]["ready"]
    sessions = await routes.sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == scanned["id"]
    assert {item["kind"] for item in sessions[0]["reviews"]} == {"scan", "plan", "preflight"}


@pytest.mark.asyncio
async def test_failed_preflight_cannot_authorize_application(storage):
    server, source, config = storage
    scanned = await routes.create_scan(routes.ScanRequest(server=str(server)), config)
    await finish()
    planned = await routes.create_plan(routes.PlanRequest(scan_id=scanned["id"], performers=["samplecreator"]))
    await finish()
    (source / "file").write_bytes(b"changed since review")
    digest = routes.state(planned["id"])["sha256"]
    checked = await routes.create_preflight(routes.PreflightRequest(plan_id=planned["id"], approved_sha256=digest))
    await finish()
    assert not routes.state(checked["id"])["summary"]["ready"]
    with pytest.raises(HTTPException, match="409"):
        await routes.apply_review(routes.ApplyRequest(plan_id=planned["id"], approved_sha256=digest, writers_paused=True, preflight_id=checked["id"]))
    assert (source / "file").exists()


@pytest.mark.asyncio
async def test_excluded_root_stays_visible_and_is_not_searched(storage):
    server, source, config = storage
    root = source.parents[2]
    scanned = await routes.create_scan(routes.ScanRequest(server=str(server), excluded_roots=[str(root)]), config)
    await finish()
    summary = routes.state(scanned["id"])["summary"]
    assert summary["matched_performers"] == 0
    assert {"path": str(root), "status": "excluded", "matched_folders": 0} in summary["roots"]
