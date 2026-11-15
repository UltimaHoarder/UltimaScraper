from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from ultima_scraper_backend.config import DownloadPathSetup, Drive
from ultima_scraper_backend.job_system import consolidation

PERFORMER = Path("OnlyFans/T/tester")
OLD = time.time() - 3600


def _setup(*drives: tuple[Path, int]) -> DownloadPathSetup:
    return DownloadPathSetup(
        drives=[Drive(directories=[root], priority=priority) for root, priority in drives]
    )


def _write(path: Path, size: int, mtime: float = OLD) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def _free_space(monkeypatch: pytest.MonkeyPatch, free: dict[Path, int]) -> None:
    def disk_usage(path: str | Path) -> SimpleNamespace:
        path = Path(path)
        root = next(root for root in free if path == root or root in path.parents)
        return SimpleNamespace(free=free[root])

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage", disk_usage
    )


def _only_split(setup: DownloadPathSetup) -> consolidation.SplitPerformer:
    (performer,) = consolidation.find_split_performers(setup, "OnlyFans")
    return performer


def test_a_performer_folder_on_two_drives_is_split(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "Posts/Free/Images/1.jpg", 10)
    _write(b / PERFORMER / "Posts/Free/Images/2.jpg", 10)
    _write(a / "OnlyFans/O/only_here/Posts/1.jpg", 10)

    performer = _only_split(_setup((a, 0), (b, 0)))

    assert performer.relative_path == PERFORMER
    assert [folder.root for folder in performer.folders] == [a, b]


def test_one_folder_seen_through_two_mounts_is_not_split(tmp_path: Path) -> None:
    real = tmp_path / "real"
    _write(real / PERFORMER / "Posts/1.jpg", 10)
    (tmp_path / "second_mount").symlink_to(real)

    assert consolidation.find_split_performers(_setup((real, 0), (tmp_path / "second_mount", 0)), "OnlyFans") == []


def test_find_only_site_folders_are_not_consolidated(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / "OnlyFansImages/T/tester/1.jpg", 10)
    _write(b / "OnlyFansImages/T/tester/2.jpg", 10)
    setup = _setup((a, 0), (b, 0))
    setup.site_directory_aliases = {"onlyfans": ["OnlyFansImages"]}
    setup.find_only_site_directories = {"onlyfans": ["OnlyFansImages"]}

    assert consolidation.find_split_performers(setup, "OnlyFans") == []


def test_the_highest_priority_drive_with_room_is_the_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "big.mp4", 100)
    _write(b / PERFORMER / "small.jpg", 10)
    _free_space(monkeypatch, {a: 10**6, b: 10**6})

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 5))))

    assert plan.target is not None and plan.target.root == b
    assert [move.target for move in plan.of_kind("move")] == [b / PERFORMER / "big.mp4"]


def test_equal_priorities_keep_the_drive_holding_the_most(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "small.jpg", 10)
    _write(b / PERFORMER / "big.mp4", 100)
    _free_space(monkeypatch, {a: 10**6, b: 10**6})

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 0))))

    assert plan.target is not None and plan.target.root == b


def test_a_priority_drive_without_room_is_passed_over(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "big.mp4", 100)
    _write(b / PERFORMER / "small.jpg", 10)
    _free_space(monkeypatch, {a: 10**6, b: 50})

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 5))))

    assert plan.target is not None and plan.target.root == a


def test_no_drive_with_room_leaves_the_performer_split(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "big.mp4", 100)
    _write(b / PERFORMER / "big2.mp4", 100)
    _free_space(monkeypatch, {a: 10, b: 10})

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 0))))

    assert plan.target is None and plan.no_space
    assert "free space" in plan.reason
    assert consolidation.execute_consolidation(plan, lambda pairs: None).moved == 0


def test_a_chosen_drive_is_the_target_even_below_a_higher_priority_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "big.mp4", 100)
    _write(b / PERFORMER / "small.jpg", 10)
    _free_space(monkeypatch, {a: 10**6, b: 10**6})
    performer = _only_split(_setup((a, 0), (b, 5)))

    assert consolidation.plan_consolidation(performer).target.root == b
    plan = consolidation.plan_consolidation(performer, target_root=str(a))

    assert plan.target is not None and plan.target.root == a
    assert [move.target for move in plan.of_kind("move")] == [a / PERFORMER / "small.jpg"]


def test_a_chosen_drive_without_room_is_not_swapped_for_another(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "big.mp4", 100)
    _write(b / PERFORMER / "small.jpg", 10)
    _free_space(monkeypatch, {a: 10**6, b: 50})

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 5))), target_root=b)

    assert plan.target is None and plan.no_space
    assert plan.reason == f"{b} has 50 bytes free; this needs 100"


def test_a_chosen_drive_may_use_its_reserve_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "big.mp4", 100)
    _write(b / PERFORMER / "small.jpg", 20)
    # a keeps 50 bytes in reserve, so 20 more fit only by using some of it.
    _free_space(monkeypatch, {a: 60, b: 10**6})
    setup = _setup((a, 0), (b, 0))
    setup.drives[0].minimum_space = 50

    plan = consolidation.plan_consolidation(_only_split(setup), target_root=a)

    assert plan.target is not None and plan.target.root == a, plan.reason
    assert plan.into_reserve and not plan.no_space
    assert plan.needed == 20
    assert (plan.folder_free[a], plan.folder_reserve[a]) == (60, 50)
    assert [move.size for move in plan.of_kind("move")] == [20]


def test_the_best_drive_is_one_that_keeps_its_reserve(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "big.mp4", 100)
    _write(b / PERFORMER / "small.jpg", 20)
    # a has priority but would dip into its reserve; b keeps its own.
    _free_space(monkeypatch, {a: 60, b: 10**6})
    setup = _setup((a, 5), (b, 0))
    setup.drives[0].minimum_space = 50

    plan = consolidation.plan_consolidation(_only_split(setup))

    assert plan.target is not None and plan.target.root == b
    assert not plan.into_reserve


def test_a_reserve_is_used_when_no_drive_can_keep_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "big.mp4", 100)
    _write(b / PERFORMER / "small.jpg", 20)
    _free_space(monkeypatch, {a: 60, b: 50})
    setup = _setup((a, 0), (b, 0))
    setup.drives[0].minimum_space = 50
    setup.drives[1].minimum_space = 10**6

    plan = consolidation.plan_consolidation(_only_split(setup))

    # b lacks the 100 bytes outright; a has them, inside its reserve.
    assert plan.target is not None and plan.target.root == a
    assert plan.into_reserve


def test_duplicates_need_no_room(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    # The same 100 bytes on both drives, plus 30 new ones on b; a has 40 free.
    _write(a / PERFORMER / "Posts/same.mp4", 100)
    _write(b / PERFORMER / "Posts/same.mp4", 100)
    _write(b / PERFORMER / "Posts/new.jpg", 30)
    _free_space(monkeypatch, {a: 40, b: 0})

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 0))), target_root=a)

    assert plan.target is not None and plan.target.root == a, plan.reason
    assert plan.needed == 30 and not plan.into_reserve
    assert plan.folder_needed == {a: 30, b: 0}
    assert [move.kind for move in sorted(plan.moves, key=lambda move: move.size)] == ["move", "duplicate"]


def test_files_left_behind_need_no_room(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "Posts/clash.mp4", 10)
    _write(b / PERFORMER / "Posts/clash.mp4", 100)
    _write(b / PERFORMER / "Posts/fresh.mp4", 100, mtime=time.time())
    _free_space(monkeypatch, {a: 0, b: 10**6})

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 0))), target_root=a)

    # A name clash and a file still arriving stay where they are.
    assert plan.target is not None and plan.target.root == a, plan.reason
    assert plan.needed == 0
    assert sorted(move.kind for move in plan.moves) == ["conflict", "recent"]


def test_an_empty_copy_needs_no_room(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "big.mp4", 100)
    (b / PERFORMER).mkdir(parents=True)
    _free_space(monkeypatch, {a: 0, b: 10**6})
    setup = _setup((a, 0), (b, 0))
    performer = consolidation.SplitPerformer(
        relative_path=PERFORMER,
        folders=[
            consolidation.PerformerFolder(root=a, relative_path=PERFORMER, drive=setup.drives[0]),
            consolidation.PerformerFolder(root=b, relative_path=PERFORMER, drive=setup.drives[1]),
        ],
    )

    plan = consolidation.plan_consolidation(performer, target_root=a)

    assert plan.target is not None and plan.target.root == a, plan.reason
    assert plan.of_kind("move") == []


def test_a_drive_not_holding_the_performer_cannot_be_chosen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    _write(a / PERFORMER / "big.mp4", 100)
    _write(b / PERFORMER / "small.jpg", 10)
    c.mkdir()
    _free_space(monkeypatch, {a: 10**6, b: 10**6, c: 10**6})

    plan = consolidation.plan_consolidation(
        _only_split(_setup((a, 0), (b, 5), (c, 9))), target_root=c
    )

    assert plan.target is None
    assert "does not hold" in plan.reason
    assert consolidation.execute_consolidation(plan, lambda pairs: None).moved == 0


def test_consolidating_moves_files_drops_duplicates_and_leaves_clashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(b / PERFORMER / "Posts/same.jpg", 10)
    _write(b / PERFORMER / "Posts/clash.jpg", 10)
    _write(b / PERFORMER / "Posts/keep.mp4", 500)
    moving = _write(a / PERFORMER / "Posts/Videos/new.mp4", 30)
    duplicate = _write(a / PERFORMER / "Posts/same.jpg", 10)
    clash = _write(a / PERFORMER / "Posts/clash.jpg", 20)
    recent = _write(a / PERFORMER / "Posts/arriving.mp4", 5, mtime=time.time())
    _free_space(monkeypatch, {a: 10**6, b: 10**6})
    updates: list[tuple[str, str]] = []

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 0))))
    result = consolidation.execute_consolidation(plan, updates.extend)

    target = b / PERFORMER
    assert (target / "Posts/Videos/new.mp4").read_bytes() == b"x" * 30
    assert not moving.exists() and not duplicate.exists()
    assert clash.exists() and recent.exists()
    assert result.moved == 1 and result.moved_bytes == 30
    assert result.duplicates == 1
    assert result.conflicts == [str(clash)]
    assert result.skipped == 1
    assert sorted(updates) == sorted(
        [
            (str(moving), str(target / "Posts/Videos/new.mp4")),
            (str(duplicate), str(target / "Posts/same.jpg")),
        ]
    )
    assert not (a / PERFORMER / "Posts/Videos").exists()


def test_a_folder_emptied_by_consolidation_is_removed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "Posts/Images/1.jpg", 10)
    _write(b / PERFORMER / "Posts/Images/2.jpg", 100)
    _free_space(monkeypatch, {a: 10**6, b: 10**6})

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 0))))
    consolidation.execute_consolidation(plan, lambda pairs: None)

    assert not (a / PERFORMER).exists()
    assert (b / PERFORMER / "Posts/Images/1.jpg").exists()


def test_a_letter_folder_emptied_by_consolidation_is_removed_but_not_the_site_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "Posts/Images/1.jpg", 10)
    _write(b / PERFORMER / "Posts/Images/2.jpg", 100)
    _free_space(monkeypatch, {a: 10**6, b: 10**6})

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 0))))
    consolidation.execute_consolidation(plan, lambda pairs: None)

    assert not (a / "OnlyFans/T").exists()
    assert (a / "OnlyFans").is_dir()


def test_a_letter_folder_holding_another_performer_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "Posts/Images/1.jpg", 10)
    _write(b / PERFORMER / "Posts/Images/2.jpg", 100)
    _write(a / "OnlyFans/T/other/Posts/3.jpg", 10)
    _free_space(monkeypatch, {a: 10**6, b: 10**6})

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 0))))
    consolidation.execute_consolidation(plan, lambda pairs: None)

    assert not (a / PERFORMER).exists()
    assert (a / "OnlyFans/T/other/Posts/3.jpg").exists()


def test_a_folder_left_with_a_clash_keeps_its_parents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "Posts/same.mp4", 10)
    _write(b / PERFORMER / "Posts/same.mp4", 100)
    _write(b / PERFORMER / "Posts/big.mp4", 1000)
    _free_space(monkeypatch, {a: 10**6, b: 10**6})

    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 0))))
    result = consolidation.execute_consolidation(plan, lambda pairs: None)

    assert result.conflicts == [str(a / PERFORMER / "Posts/same.mp4")]
    assert (a / PERFORMER / "Posts/same.mp4").exists()


def test_a_file_seen_through_two_paths_is_never_deleted_as_a_duplicate(tmp_path: Path) -> None:
    real = _write(tmp_path / "real/file.jpg", 10)
    (tmp_path / "alias").symlink_to(tmp_path / "real")

    assert consolidation._move_file(real, tmp_path / "alias/file.jpg") == "same_file"
    assert real.exists()


def test_moving_to_another_filesystem_copies_under_a_temporary_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _write(tmp_path / "a/file.mp4", 40)
    target = tmp_path / "b/file.mp4"

    def cross_device(*_args: object) -> None:
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(consolidation.os, "rename", cross_device)

    assert consolidation._move_file(source, target) == "move"
    assert target.read_bytes() == b"x" * 40
    assert os.stat(target).st_mtime == pytest.approx(OLD)
    assert not source.exists()
    assert list(target.parent.iterdir()) == [target]


async def test_the_routes_scan_preview_and_consolidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio

    import httpx
    from fastapi import FastAPI
    from ultima_scraper_backend.api import dependencies
    from ultima_scraper_backend.api.routes import consolidation as routes
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "Posts/1.jpg", 10)
    _write(b / PERFORMER / "Posts/2.mp4", 100)
    _free_space(monkeypatch, {a: 10**6, b: 10**6})
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = _setup((a, 0), (b, 0))
    updates: list[tuple[str, str]] = []
    monkeypatch.setattr(routes.consolidation, "database_path_updater", lambda site: updates.extend)
    monkeypatch.setattr(routes, "_local_status", {})

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[dependencies.get_config] = lambda: config
    app.dependency_overrides[dependencies.get_backend_instance] = lambda: SimpleNamespace(
        redis=None, instance_id="test"
    )

    async def settle() -> None:
        while routes._tasks:
            await asyncio.gather(*routes._tasks)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.post("/consolidation/scan")).status_code == 202
        await settle()
        split = (await client.get("/consolidation/split")).json()
        assert [p["relative_path"] for p in split["performers"]] == ["OnlyFans/T/tester"]

        preview = (await client.post("/consolidation/preview", json={"relative_path": "OnlyFans/T/tester"})).json()
        assert preview["target_root"] == str(b)
        assert preview["move_files"] == 1

        assert (
            await client.post("/consolidation/run", json={"relative_paths": ["OnlyFans/T/tester"]})
        ).status_code == 202
        await settle()
        status = (await client.get("/consolidation/status")).json()
        # Consolidated, so no longer listed, without scanning again.
        after = (await client.get("/consolidation/split")).json()

    assert after["performers"] == []
    assert status["running"] is False
    assert status["performers"][0]["moved"] == 1
    assert (b / PERFORMER / "Posts/1.jpg").exists()
    assert updates == [(str(a / PERFORMER / "Posts/1.jpg"), str(b / PERFORMER / "Posts/1.jpg"))]


async def test_the_routes_preview_and_consolidate_to_a_chosen_drive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio

    import httpx
    from fastapi import FastAPI
    from ultima_scraper_backend.api import dependencies
    from ultima_scraper_backend.api.routes import consolidation as routes
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "Posts/1.jpg", 10)
    _write(b / PERFORMER / "Posts/2.mp4", 100)
    _free_space(monkeypatch, {a: 10**6, b: 10**6})
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = _setup((a, 0), (b, 0))
    monkeypatch.setattr(routes.consolidation, "database_path_updater", lambda site: lambda pairs: None)
    monkeypatch.setattr(routes, "_local_status", {})

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[dependencies.get_config] = lambda: config
    app.dependency_overrides[dependencies.get_backend_instance] = lambda: SimpleNamespace(
        redis=None, instance_id="test"
    )

    async def settle() -> None:
        while routes._tasks:
            await asyncio.gather(*routes._tasks)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.post("/consolidation/scan")).status_code == 202
        await settle()

        # b holds the most, so it is picked unless a is chosen.
        preview = (
            await client.post(
                "/consolidation/preview",
                json={"relative_path": "OnlyFans/T/tester", "target_root": str(a)},
            )
        ).json()
        assert preview["target_root"] == str(a)
        assert preview["move_bytes"] == 100
        assert preview["needed_bytes"] == 100
        assert (preview["into_reserve"], preview["no_space"]) == (False, False)
        assert {folder["root"]: folder["free_bytes"] for folder in preview["folders"]} == {
            str(a): 10**6,
            str(b): 10**6,
        }

        assert (
            await client.post(
                "/consolidation/run",
                json={"relative_paths": ["OnlyFans/T/tester"], "targets": {"OnlyFans/T/tester": str(a)}},
            )
        ).status_code == 202
        await settle()
        status = (await client.get("/consolidation/status")).json()

    assert status["performers"][0]["target_root"] == str(a)
    assert (a / PERFORMER / "Posts/2.mp4").exists()
    assert not (b / PERFORMER / "Posts/2.mp4").exists()


def test_a_scan_checkpoint_can_cancel_it(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "1.jpg", 10)
    _write(b / PERFORMER / "2.jpg", 10)
    seen: list[tuple[Path, int]] = []

    def checkpoint(root: Path, roots_done: int) -> None:
        seen.append((root, roots_done))
        if root == b:
            raise consolidation.ScanCancelled

    with pytest.raises(consolidation.ScanCancelled):
        consolidation.find_split_performers(_setup((a, 0), (b, 0)), "OnlyFans", checkpoint=checkpoint)
    assert seen[0] == (a, 0) and seen[-1] == (b, 1)


async def test_a_running_scan_can_be_paused_resumed_and_cancelled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio
    import threading

    import httpx
    from fastapi import FastAPI
    from ultima_scraper_backend.api import dependencies
    from ultima_scraper_backend.api.routes import consolidation as routes
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = _setup((tmp_path / "a", 0))
    monkeypatch.setattr(routes, "_HEARTBEAT_SECONDS", 0.01)
    # The earlier scan's performer still has both folders, so it stays listed.
    copies = [tmp_path / "a" / "x", tmp_path / "b" / "x"]
    for copy in copies:
        copy.mkdir(parents=True)
    folders = [{"root": str(copy.parent), "path": str(copy), "priority": 0} for copy in copies]
    previous = {
        "site_name": "OnlyFans",
        "scanning": False,
        "scanned_at": 1.0,
        "performers": [{"relative_path": "x", "folders": folders}],
    }
    monkeypatch.setattr(routes, "_local_status", {})
    checkpoints = threading.Event()

    def endless_scan(setup, site_name, *, checkpoint):
        while True:
            checkpoint(tmp_path / "a", 0)
            checkpoints.set()
            time.sleep(0.01)

    monkeypatch.setattr(routes.consolidation, "find_split_performers", endless_scan)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[dependencies.get_config] = lambda: config
    backend = SimpleNamespace(redis=None, instance_id="test")
    app.dependency_overrides[dependencies.get_backend_instance] = lambda: backend
    routes._local_status[routes._scan_key(backend, "OnlyFans")] = previous

    async def until(predicate) -> dict:
        for _ in range(500):
            scan = (await client.get("/consolidation/split")).json()
            if predicate(scan):
                return scan
            await asyncio.sleep(0.01)
        raise AssertionError(scan)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.post("/consolidation/scan/pause")).status_code == 409
        await client.post("/consolidation/scan")
        await until(lambda scan: scan["scanning"])
        assert (await client.post("/consolidation/scan")).json() == {"started": False}

        await client.post("/consolidation/scan/pause")
        await until(lambda scan: scan["paused"])
        await asyncio.sleep(0.05)
        checkpoints.clear()
        await asyncio.sleep(0.05)
        assert not checkpoints.is_set()

        await client.post("/consolidation/scan/resume")
        await until(lambda scan: not scan["paused"])
        await asyncio.to_thread(checkpoints.wait, 2)

        await client.post("/consolidation/scan/cancel")
        scan = await until(lambda scan: not scan["scanning"])
        while routes._tasks:
            await asyncio.gather(*routes._tasks)

    assert scan["cancelled_at"] and scan["scanned_at"] == 1.0
    assert scan["performers"] == previous["performers"]


async def test_a_scan_lost_to_a_restart_shows_as_interrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from fastapi import FastAPI
    from ultima_scraper_backend.api import dependencies
    from ultima_scraper_backend.api.routes import consolidation as routes

    backend = SimpleNamespace(redis=None, instance_id="test")
    monkeypatch.setattr(
        routes,
        "_local_status",
        {routes._scan_key(backend, "OnlyFans"): {"scanning": True, "heartbeat_at": time.time() - 600, "performers": []}},
    )
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[dependencies.get_backend_instance] = lambda: backend

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        scan = (await client.get("/consolidation/split")).json()
        cancelled = await client.post("/consolidation/scan/cancel")

    assert scan["scanning"] is False and scan["interrupted"] is True
    assert cancelled.status_code == 200


def _split_with_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, count: int
) -> tuple[consolidation.ConsolidationPlan, Path]:
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a / PERFORMER / "Posts/keep.jpg", 1000)
    for index in range(count):
        _write(b / PERFORMER / f"Posts/{index}.jpg", 10)
    _free_space(monkeypatch, {a: 10**6, b: 10**6})
    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 0))))
    assert plan.target is not None and plan.target.root == a
    return plan, a


def _tracked_moves(monkeypatch: pytest.MonkeyPatch, fail=None):
    """Wraps _move_file to record how many run at once and at which targets."""
    import threading

    real = consolidation._move_file
    state = {"active": 0, "most": 0, "calls": 0, "targets": set(), "overlap": False}
    lock = threading.Lock()

    def tracked(source: Path, target: Path):
        with lock:
            state["calls"] += 1
            call = state["calls"]
            state["active"] += 1
            state["most"] = max(state["most"], state["active"])
            state["overlap"] |= target in state["targets"]
            state["targets"].add(target)
        try:
            time.sleep(0.02)
            if fail is not None:
                fail(call)
            return real(source, target)
        finally:
            with lock:
                state["active"] -= 1
                state["targets"].discard(target)

    monkeypatch.setattr(consolidation, "_move_file", tracked)
    return state


def test_files_are_moved_several_at_a_time(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plan, a = _split_with_files(monkeypatch, tmp_path, 24)
    state = _tracked_moves(monkeypatch)
    updates: list[tuple[str, str]] = []

    result = consolidation.execute_consolidation(plan, updates.extend, batch_size=5, workers=4)

    assert result.moved == 24 and not result.failed
    assert 1 < state["most"] <= 4
    assert sorted(new for _, new in updates) == sorted(str(a / PERFORMER / f"Posts/{i}.jpg") for i in range(24))
    assert all((a / PERFORMER / f"Posts/{i}.jpg").exists() for i in range(24))


def test_copies_of_one_file_never_move_to_it_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    _write(a / PERFORMER / "Posts/big.mp4", 1000)
    for index in range(6):
        _write(b / PERFORMER / f"Posts/{index}.jpg", 10)
        _write(c / PERFORMER / f"Posts/{index}.jpg", 10)
    _free_space(monkeypatch, {a: 10**6, b: 10**6, c: 10**6})
    plan = consolidation.plan_consolidation(_only_split(_setup((a, 0), (b, 0), (c, 0))))
    state = _tracked_moves(monkeypatch)

    result = consolidation.execute_consolidation(plan, lambda pairs: None, workers=8)

    assert not state["overlap"]
    assert (result.moved, result.duplicates) == (6, 6)
    assert not (b / PERFORMER).exists() and not (c / PERFORMER).exists()


def test_a_full_drive_stops_new_moves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import errno

    plan, _ = _split_with_files(monkeypatch, tmp_path, 40)

    def no_space(call: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    state = _tracked_moves(monkeypatch, fail=no_space)

    result = consolidation.execute_consolidation(plan, lambda pairs: None, workers=4)

    # Only the moves already started when the drive filled up were tried.
    assert state["calls"] <= 4
    assert len(result.failed) == state["calls"] and result.moved == 0


def test_moved_files_reach_the_database_even_when_a_move_crashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan, a = _split_with_files(monkeypatch, tmp_path, 30)

    def crash(call: int) -> None:
        if call == 15:
            raise RuntimeError("boom")

    _tracked_moves(monkeypatch, fail=crash)
    updates: list[tuple[str, str]] = []

    with pytest.raises(RuntimeError):
        consolidation.execute_consolidation(plan, updates.extend, batch_size=1000, workers=4)

    moved = sorted(str(path) for path in (a / PERFORMER / "Posts").glob("[0-9]*.jpg"))
    assert moved and sorted(new for _, new in updates) == moved


async def test_folders_gone_since_the_scan_are_not_listed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio
    import shutil

    import httpx
    from fastapi import FastAPI
    from ultima_scraper_backend.api import dependencies
    from ultima_scraper_backend.api.routes import consolidation as routes
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    for root in (a, b, c):
        _write(root / PERFORMER / f"Posts/{root.name}.jpg", 10)
    _free_space(monkeypatch, {a: 10**6, b: 10**6, c: 10**6})
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = _setup((a, 0), (b, 0), (c, 0))
    monkeypatch.setattr(routes, "_local_status", {})

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[dependencies.get_config] = lambda: config
    app.dependency_overrides[dependencies.get_backend_instance] = lambda: SimpleNamespace(
        redis=None, instance_id="test"
    )

    async def settle() -> None:
        while routes._tasks:
            await asyncio.gather(*routes._tasks)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.post("/consolidation/scan")).status_code == 202
        await settle()

        # One of three copies deleted by hand: still split, across the other two.
        shutil.rmtree(c / PERFORMER)
        listed = (await client.get("/consolidation/split")).json()["performers"]
        assert [folder["root"] for folder in listed[0]["folders"]] == [str(a), str(b)]

        # Down to one copy: no longer split, and can't be previewed.
        shutil.rmtree(b / PERFORMER)
        assert (await client.get("/consolidation/split")).json()["performers"] == []
        preview = await client.post(
            "/consolidation/preview", json={"relative_path": "OnlyFans/T/tester"}
        )
        assert preview.status_code == 404
