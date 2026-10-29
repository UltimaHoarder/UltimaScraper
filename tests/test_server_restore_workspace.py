import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from ultima_scraper_backend.services import archive_write_guard as guard
from ultima_scraper_backend.services import server_restore_workspace as workspace
from ultima_scraper_backend.services import server_restore_files as restore_files
from ultima_scraper_backend.services.server_restore_files import apply_plan, fingerprint, make_plan, scan


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "LOCK_ROOT", tmp_path / "locks")
    server = tmp_path / "server" / "OnlyFans Vault"
    target = server / "S" / "samplecreator"
    source = tmp_path / "source" / "OnlyFans" / "S" / "SampleCreator"
    target.mkdir(parents=True)
    source.mkdir(parents=True)
    (source / "file").write_bytes(b"archive contents")
    inventory = scan(server, [server.parent, tmp_path / "source"], ["OnlyFans", "OnlyFans Vault"])
    return tmp_path, server, target, source, inventory


def saved_plan(archive, **options):
    tmp_path, server, _, _, inventory = archive
    store = workspace.Store(tmp_path / "reviews")
    scan_id, plan_id = str(uuid4()), str(uuid4())
    plan = make_plan(inventory, ["SampleCreator"], isolate_performers=True, **options)
    for identifier, kind, result in [(scan_id, "scan", inventory), (plan_id, "plan", plan)]:
        workspace.save(store.directory(identifier) / "state.json", {"id": identifier, "kind": kind, "status": "completed", "server": str(server), "created_at": "2026-10-02T00:00:00Z", "scan_id": scan_id, "sha256": workspace.digest(result), "summary": workspace.summary(result, kind)})
        workspace.save(store.directory(identifier) / "result.json", result)
    return store, scan_id, plan_id, plan


def inline(store, identifier, global_lock, review_lock):
    try:
        workspace.run(store, identifier)
    finally:
        review_lock.close()
        global_lock.close()


def execute(store, scan_id, plan_id, plan):
    return store.start("apply", {"plan_id": plan_id, "approved_sha256": workspace.digest(plan), "writers_paused": True}, launch=inline, server=plan["server"], scan_id=scan_id, plan_id=plan_id)


def test_ambiguous_performer_isolated_and_choice_is_roster_bound(archive):
    _, server, target, source, inventory = archive
    other_target = server / "X" / "SAMPLECREATOR"
    other_target.mkdir(parents=True)
    (server / "O" / "other").mkdir(parents=True)
    other_source = source.parent / "other"
    other_source.mkdir()
    (other_source / "file").write_bytes(b"other")
    inventory = scan(server, [Path(inventory["roots"][1]["path"])], ["OnlyFans"])
    plan = make_plan(inventory, ["SampleCreator", "other"], isolate_performers=True)
    assert [entry["performer"] for entry in plan["entries"]] == ["other"]
    assert plan["blocked_performers"][0]["performer"] == "samplecreator"
    chosen = make_plan(inventory, ["SampleCreator"], isolate_performers=True, destination_choices={"samplecreator": str(other_target)})
    assert chosen["entries"][0]["destination"] == str(other_target / "file")
    invalid = make_plan(inventory, ["SampleCreator"], isolate_performers=True, destination_choices={"samplecreator": str(target.parent / "outside")})
    assert not invalid["entries"]
    assert "not in the reviewed" in invalid["blocked_performers"][0]["error"]


def test_preferred_copy_is_explicit_and_other_copy_retained(archive):
    tmp_path, server, target, source, _ = archive
    other = tmp_path / "other" / "OnlyFans" / "S" / "SampleCreator"
    other.mkdir(parents=True)
    (other / "file").write_bytes(b"preferred contents")
    inventory = scan(server, [tmp_path / "source", tmp_path / "other"], ["OnlyFans"])
    plan = make_plan(inventory, ["SampleCreator"], isolate_performers=True, preferred_sources={str(target / "file"): str(other / "file")})
    assert [entry["action"] for entry in plan["entries"]] == ["retain", "move"]
    apply_plan(plan, tmp_path / "journal")
    assert (target / "file").read_bytes() == b"preferred contents"
    assert (source / "file").exists()
    assert not (other / "file").exists()


def test_collision_classification_keeps_hash_and_mtime_distinct(archive):
    _, _, target, source, inventory = archive
    (target / "file").write_bytes((source / "file").read_bytes())
    os.utime(source / "file", ns=(1_000_000_000, 1_000_000_000))
    os.utime(target / "file", ns=(2_000_000_000, 2_000_000_000))
    unverified = make_plan(inventory, ["SampleCreator"])["entries"][0]
    assert unverified["reason"] == "unverified"
    hashed = make_plan(inventory, ["SampleCreator"], hash_collisions=True)["entries"][0]
    assert hashed["action"] == "conflict" and hashed["reason"] == "mtime_mismatch"
    retained = make_plan(inventory, ["SampleCreator"], retained_sources=[str(source / "file")])["entries"][0]
    assert retained["action"] == "retain"


def test_unrelated_file_decisions_rejected(archive):
    _, _, _, _, inventory = archive
    with pytest.raises(ValueError, match="selected performer"):
        make_plan(inventory, ["SampleCreator"], isolate_performers=True, retained_sources=["/elsewhere/file"])


def test_preflight_rechecks_snapshots_space_and_writers(archive, monkeypatch):
    _, _, target, source, inventory = archive
    plan = make_plan(inventory, ["SampleCreator"])
    assert workspace.preflight(plan, inventory)["ready"]
    with guard.acquire(workspace.writer_roots(inventory, plan), exclusive=False):
        readiness = workspace.preflight(plan, inventory)
        assert not readiness["ready"]
        assert not next(c for c in readiness["checks"] if "writers" in c["name"])["ok"]
    monkeypatch.setattr(workspace.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    assert not workspace.preflight(plan, inventory)["ready"]
    monkeypatch.undo()
    (target / "file").write_bytes(b"new server data")
    assert not workspace.preflight(plan, inventory)["ready"]
    assert (source / "file").exists()


def test_worker_journals_copy_verification_and_removal(archive):
    store, scan_id, plan_id, plan = saved_plan(archive)
    job = execute(store, scan_id, plan_id, plan)
    state = store.state(job["id"])
    assert state["status"] == "completed"
    events = [json.loads(line)["event"] for line in (store.directory(job["id"]) / "performer-1.jsonl").read_text().splitlines()]
    assert events == ["copy_started", "copied", "verified_copy", "source_removed"]
    assert state["telemetry"]["completed_files"] == 1
    assert state["telemetry"]["completed_bytes"] == len(b"archive contents")
    assert store.state(plan_id)["apply_id"] == job["id"]


def test_stop_during_copy_finishes_current_file_and_reconciles_remaining_work(archive, monkeypatch):
    _, _, target, source, _ = archive
    (source / "second-file").write_bytes(b"remaining contents")
    store, scan_id, plan_id, plan = saved_plan(archive)
    copyfileobj = restore_files.shutil.copyfileobj
    def launch(store, identifier, global_lock, review_lock):
        def stop_during_copy(*args, **kwargs):
            copyfileobj(*args, **kwargs)
            workspace.save(store.directory(identifier) / "stop.json", {"requested": True})
        monkeypatch.setattr(restore_files.shutil, "copyfileobj", stop_during_copy)
        inline(store, identifier, global_lock, review_lock)
    job = store.start("apply", {"plan_id": plan_id, "approved_sha256": workspace.digest(plan), "writers_paused": True}, launch=launch, server=plan["server"], scan_id=scan_id, plan_id=plan_id)
    state = store.state(job["id"])
    assert state["status"] == "interrupted"
    assert state["telemetry"]["completed_files"] == 1
    assert (target / "file").read_bytes() == b"archive contents"
    assert not (source / "file").exists()
    assert (source / "second-file").exists()
    assert not (target / "second-file").exists()
    events = [json.loads(line)["event"] for line in (store.directory(job["id"]) / "performer-1.jsonl").read_text().splitlines()]
    assert events[-2:] == ["verified_copy", "source_removed"]
    with guard.acquire(workspace.writer_roots(archive[-1], plan), exclusive=False):
        pass
    recovered = workspace.recovery_plan(store, job["id"], lambda value: None)
    assert recovered["recovery"]["completed_files"] == 1
    assert [entry["source"] for entry in recovered["entries"]] == [str(source / "second-file")]


def test_stop_before_revalidation_changes_no_archive_files(archive):
    _, _, target, source, _ = archive
    store, scan_id, plan_id, plan = saved_plan(archive)
    def launch(store, identifier, global_lock, review_lock):
        workspace.save(store.directory(identifier) / "stop.json", {"requested": True})
        inline(store, identifier, global_lock, review_lock)
    job = store.start("apply", {"plan_id": plan_id, "approved_sha256": workspace.digest(plan), "writers_paused": True}, launch=launch, server=plan["server"], scan_id=scan_id, plan_id=plan_id)
    assert store.state(job["id"])["status"] == "interrupted"
    assert (source / "file").exists()
    assert not (target / "file").exists()
    assert not list(store.directory(job["id"]).glob("performer-*.jsonl"))


def test_recovery_finishes_verified_copy_after_source_removal_failure(archive, monkeypatch):
    tmp_path, _, target, source, _ = archive
    store, scan_id, plan_id, plan = saved_plan(archive)
    unlink = Path.unlink
    def interrupted(path, *args, **kwargs):
        if path == source / "file":
            raise OSError("interrupted before source removal")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", interrupted)
    job = execute(store, scan_id, plan_id, plan)
    assert store.state(job["id"])["status"] == "failed"
    monkeypatch.setattr(Path, "unlink", unlink)
    recovered = workspace.recovery_plan(store, job["id"], lambda value: None)
    assert recovered["entries"][0]["action"] == "finish_move"
    assert recovered["recovery"]["verified_copies_to_finish"] == 1
    assert (source / "file").exists()
    apply_plan(recovered, tmp_path / "recovery-journal")
    assert not (source / "file").exists()
    assert (target / "file").read_bytes() == b"archive contents"


def test_recovery_detects_lost_destination_after_completed_copy(archive):
    _, _, target, _, _ = archive
    store, scan_id, plan_id, plan = saved_plan(archive, cleanup_empty=True)
    job = execute(store, scan_id, plan_id, plan)
    recovered = workspace.recovery_plan(store, job["id"], lambda value: None)
    assert recovered["recovery"]["completed_files"] == 1
    assert not recovered["entries"]
    (target / "file").write_bytes(b"changed server data")
    changed = workspace.recovery_plan(store, job["id"], lambda value: None)
    assert changed["blocked_performers"]
    assert changed["recovery"]["completed_files"] == 0


def test_recovery_reports_partial_repair_temporary_without_deleting_it(archive):
    _, _, target, source, _ = archive
    (target / "file").write_bytes(b"")
    store, scan_id, plan_id, plan = saved_plan(archive, repair_zero_bytes=True)
    identifier = str(uuid4())
    temporary = target / ".restore-partial.tmp"
    temporary.write_bytes(b"partial")
    workspace.save(store.directory(identifier) / "state.json", {"id": identifier, "kind": "apply", "status": "interrupted", "scan_id": scan_id, "plan_id": plan_id})
    event = {**plan["entries"][0], "event": "copy_started", "temporary": str(temporary), "verified_source": fingerprint(source / "file")}
    (store.directory(identifier) / "performer-1.jsonl").write_text(json.dumps(event) + "\n")
    recovered = workspace.recovery_plan(store, identifier, lambda value: None)
    assert recovered["recovery"]["retained_temporary_files"] == [str(temporary)]
    assert recovered["entries"][0]["action"] == "repair_zero_byte"
    assert temporary.read_bytes() == b"partial"
    assert (source / "file").exists()
    assert (target / "file").stat().st_size == 0


def test_recovery_preserves_excluded_source_roots(archive):
    tmp_path, _, _, _, _ = archive
    store, scan_id, plan_id, plan = saved_plan(archive, cleanup_empty=True)
    excluded = tmp_path / "excluded"
    folder = excluded / "OnlyFans" / "S" / "SampleCreator"
    folder.mkdir(parents=True)
    (folder / "new-file").write_bytes(b"excluded contents")
    inventory = store.load(scan_id, "scan")
    inventory["roots"].append({"path": str(excluded), "status": "excluded", "matched_folders": 0})
    workspace.save(store.directory(scan_id) / "result.json", inventory)
    applied = execute(store, scan_id, plan_id, plan)
    recovered = workspace.recovery_plan(store, applied["id"], lambda value: None)
    assert not recovered["entries"]
    assert (folder / "new-file").exists()


@pytest.mark.asyncio
async def test_managed_writer_waits_for_restore_reservation_and_releases(archive):
    _, _, _, _, inventory = archive
    roots = [item["path"] for item in inventory["roots"]]
    config = SimpleNamespace(settings=SimpleNamespace(download_setup=SimpleNamespace(drives=[SimpleNamespace(directories=roots)])))
    entered = asyncio.Event()
    release = asyncio.Event()
    async def writer():
        async with guard.writer_guard(config):
            entered.set()
            await release.wait()
    reservation = guard.acquire(roots, exclusive=True)
    task = asyncio.create_task(writer())
    await asyncio.sleep(.01)
    assert not entered.is_set()
    reservation.close()
    await asyncio.wait_for(entered.wait(), 2)
    with pytest.raises(BlockingIOError):
        guard.acquire(roots, exclusive=True)
    release.set()
    await task
    with guard.acquire(roots, exclusive=True):
        pass


def test_reservation_intent_blocks_new_writers_while_current_writer_drains(archive):
    _, _, _, _, inventory = archive
    roots = [item["path"] for item in inventory["roots"]]
    current_writer = guard.acquire(roots, exclusive=False)
    waiting = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        reservation_task = executor.submit(guard.acquire, roots, exclusive=True, wait=True, progress=lambda message: waiting.set())
        try:
            assert waiting.wait(2)
            with pytest.raises(BlockingIOError):
                guard.acquire(roots, exclusive=False)
            current_writer.close()
            reservation = reservation_task.result(timeout=3)
            with pytest.raises(BlockingIOError):
                guard.acquire(roots, exclusive=False)
            reservation.close()
            with guard.acquire(roots, exclusive=False):
                pass
        finally:
            current_writer.close()
            reservation_task.result(timeout=3).close()


@pytest.mark.asyncio
@pytest.mark.parametrize("task_type", ["scrape", "download"])
async def test_task_handler_holds_writer_lease_through_execution(archive, monkeypatch, task_type):
    from ultima_scraper_backend.job_system.models import Job, Task, TaskRegistry, TaskResult, TaskType
    _, _, _, _, inventory = archive
    roots = [item["path"] for item in inventory["roots"]]
    config = SimpleNamespace(settings=SimpleNamespace(download_setup=SimpleNamespace(drives=[SimpleNamespace(directories=roots)])))
    entered, release = asyncio.Event(), asyncio.Event()
    async def handler(task, context):
        entered.set()
        await release.wait()
        return TaskResult(success=True)
    kind = TaskType(task_type)
    monkeypatch.setitem(TaskRegistry._handlers, kind, handler)
    task = Task(task_id="writer-task", task_type=kind, user_id=1, payload=None, site_name="OnlyFans")
    job = Job(name="Writer coordination", created_by="tests", tasks=[task])
    reservation = guard.acquire(roots, exclusive=True)
    execution = asyncio.create_task(task.run(job=job, storage=SimpleNamespace(persist_task=AsyncMock()), context={"config": config}))
    try:
        await asyncio.sleep(.01)
        assert not entered.is_set()
        reservation.close()
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(BlockingIOError):
            guard.acquire(roots, exclusive=True)
        release.set()
        assert (await execution).success
        with guard.acquire(roots, exclusive=True):
            pass
    finally:
        reservation.close()
        release.set()
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)


@pytest.mark.parametrize("kind", ["scan", "apply"])
def test_detached_worker_survives_dispatcher_exit(archive, monkeypatch, kind):
    tmp_path, server, target, source, inventory = archive
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "user-data"))
    root = tmp_path / "detached-reviews"
    request = {"server": str(server), "roots": [item["path"] for item in inventory["roots"]], "aliases": ["OnlyFans", "OnlyFans Vault"]}
    extra = {"server": str(server)}
    if kind == "apply":
        store, scan_id, plan_id, plan = saved_plan(archive)
        root = store.root
        request = {"plan_id": plan_id, "approved_sha256": workspace.digest(plan), "writers_paused": True}
        extra.update(scan_id=scan_id, plan_id=plan_id)
    script = "\n".join([
        "import json, os",
        "from pathlib import Path",
        "from ultima_scraper_backend.services.server_restore_workspace import Store",
        f"job = Store(Path({str(root)!r})).start({kind!r}, {request!r}, **{extra!r})",
        "print(json.dumps(job), flush=True)",
        "os._exit(0)",
    ])
    dispatched = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
    job = json.loads(dispatched.stdout)
    store = workspace.Store(root)
    deadline = time.monotonic() + 10
    while store.state(job["id"])["status"] == "running" and time.monotonic() < deadline:
        time.sleep(.02)
    assert store.state(job["id"])["status"] == "completed", (store.directory(job["id"]) / "worker.log").read_text()
    if kind == "scan":
        assert store.load(job["id"], "scan")["matches"][0]["performer"] == "SampleCreator"
    else:
        assert (target / "file").read_bytes() == b"archive contents"
        assert not (source / "file").exists()
        assert store.state(job["id"])["telemetry"]["completed_files"] == 1
