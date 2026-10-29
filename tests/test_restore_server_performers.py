import os
from pathlib import Path

import pytest

from scripts.maintenance.restore_server_performers import apply_plan, make_plan, scan


def fixture_archive(tmp_path: Path):
    server = tmp_path / "server" / "OnlyFans Vault"
    target = server / "S" / "samplecreator"
    target.mkdir(parents=True)
    drive = tmp_path / "drive"
    source = drive / "OnlyFans" / "S" / "SampleCreator"
    source.mkdir(parents=True)
    return server, target, drive, source


def test_scan_matches_server_roster_case_insensitively(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    (drive / "OnlyFans" / "U" / "unrelated").mkdir(parents=True)
    result = scan(server, [drive, server.parent], ["OnlyFans", "OnlyFans Vault"])
    assert result["matches"] == [
        {
            "performer": "SampleCreator",
            "source": str(source),
            "destinations": [str(target)],
        }
    ]


def test_move_verifies_content_and_preserves_nanosecond_times(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    folder = source / "Messages"
    folder.mkdir()
    file = folder / "photo.jpg"
    file.write_bytes(b"media")
    timestamp = 1_700_000_000_123_456_789
    os.utime(file, ns=(timestamp, timestamp))
    os.utime(folder, ns=(timestamp, timestamp))
    os.utime(target, ns=(timestamp, timestamp))
    inventory = scan(server, [drive], ["OnlyFans"])
    plan = make_plan(inventory, ["samplecreator"])
    apply_plan(plan, tmp_path / "journal.jsonl")
    moved = target / "Messages" / "photo.jpg"
    assert moved.read_bytes() == b"media"
    assert moved.stat().st_mtime_ns == timestamp
    assert moved.parent.stat().st_mtime_ns == timestamp
    assert target.stat().st_mtime_ns == timestamp
    assert folder.stat().st_mtime_ns == timestamp
    assert not file.exists()


def test_duplicates_and_conflicts_are_retained(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    for root in (target, source):
        (root / "same").write_bytes(b"same")
        os.utime(root / "same", ns=(1000000000, 1000000000))
    (target / "conflict").write_bytes(b"server")
    (source / "conflict").write_bytes(b"local")
    plan = make_plan(scan(server, [drive], ["OnlyFans"]), ["samplecreator"])
    assert {e["action"] for e in plan["entries"]} == {"collision", "conflict"}
    apply_plan(plan, tmp_path / "journal")
    assert (source / "same").exists()
    assert (source / "conflict").read_bytes() == b"local"
    assert (target / "conflict").read_bytes() == b"server"
    hashed = make_plan(
        scan(server, [drive], ["OnlyFans"]), ["samplecreator"], hash_collisions=True
    )
    assert {e["action"] for e in hashed["entries"]} == {"duplicate", "conflict"}


def test_changed_source_aborts_before_any_move(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    (source / "file").write_bytes(b"original")
    plan = make_plan(scan(server, [drive], ["OnlyFans"]), ["samplecreator"])
    (source / "file").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed since review"):
        apply_plan(plan, tmp_path / "journal")
    assert not (target / "file").exists()


def test_source_retained_on_copy_failure(tmp_path, monkeypatch):
    server, target, drive, source = fixture_archive(tmp_path)
    (source / "file").write_bytes(b"original")
    plan = make_plan(scan(server, [drive], ["OnlyFans"]), ["samplecreator"])

    def fail(*args, **kwargs):
        raise OSError("connection interrupted")

    monkeypatch.setattr(
        "ultima_scraper_backend.services.server_restore_files.shutil.copyfileobj", fail
    )
    with pytest.raises(OSError):
        apply_plan(plan, tmp_path / "journal")
    assert (source / "file").read_bytes() == b"original"
    assert not (target / "file").exists()


def test_symlink_refused(tmp_path):
    server, _target, drive, source = fixture_archive(tmp_path)
    (source / "link").symlink_to(tmp_path / "external")
    with pytest.raises(ValueError, match="regular file"):
        make_plan(scan(server, [drive], ["OnlyFans"]), ["samplecreator"])


def test_destination_appearing_after_review_is_not_overwritten(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    (source / "file").write_bytes(b"local")
    plan = make_plan(scan(server, [drive], ["OnlyFans"]), ["samplecreator"])
    (target / "file").write_bytes(b"new server file")
    with pytest.raises(ValueError, match="appeared since review"):
        apply_plan(plan, tmp_path / "journal")
    assert (target / "file").read_bytes() == b"new server file"
    assert (source / "file").read_bytes() == b"local"


def test_competing_source_drives_do_not_overwrite_each_other(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    other_drive = tmp_path / "other_drive"
    other = other_drive / "OnlyFans" / "S" / "samplecreator"
    other.mkdir(parents=True)
    (source / "file").write_bytes(b"first")
    (other / "file").write_bytes(b"second")
    plan = make_plan(scan(server, [drive, other_drive], ["OnlyFans"]), ["samplecreator"])
    assert [e["action"] for e in plan["entries"]] == ["move", "conflict"]
    apply_plan(plan, tmp_path / "journal")
    assert (target / "file").read_bytes() == b"first"
    assert (other / "file").read_bytes() == b"second"


def test_destination_whole_second_rounding_allows_move(tmp_path, monkeypatch):
    server, target, drive, source = fixture_archive(tmp_path)
    (source / "file").write_bytes(b"media")
    os.utime(source / "file", ns=(1700000000123456789, 1700000000123456789))
    plan = make_plan(scan(server, [drive], ["OnlyFans"]), ["samplecreator"])
    original_utime = os.utime

    def rounded(path, *args, **kwargs):
        if Path(path) == target / "file" and "ns" in kwargs:
            kwargs["ns"] = tuple(t // 1000000000 * 1000000000 for t in kwargs["ns"])
        return original_utime(path, *args, **kwargs)

    monkeypatch.setattr(
        "ultima_scraper_backend.services.server_restore_files.os.utime", rounded
    )
    apply_plan(plan, tmp_path / "journal")
    assert not (source / "file").exists()
    assert (target / "file").read_bytes() == b"media"
    assert (target / "file").stat().st_mtime_ns == 1700000000000000000


def test_verified_cleanup_repairs_stub_and_removes_empty_source(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    timestamp = 1700000000123456789
    for root in (target, source):
        (root / "same").write_bytes(b"same media")
        os.utime(root / "same", ns=(timestamp, timestamp))
    (target / "repair").write_bytes(b"")
    (source / "repair").write_bytes(b"complete media")
    os.utime(source / "repair", ns=(timestamp, timestamp))
    os.utime(target, ns=(timestamp, timestamp))
    plan = make_plan(
        scan(server, [drive], ["OnlyFans"]),
        ["samplecreator"],
        remove_duplicates=True,
        repair_zero_bytes=True,
        cleanup_empty=True,
    )
    assert {e["action"] for e in plan["entries"]} == {
        "remove_duplicate",
        "repair_zero_byte",
    }
    apply_plan(plan, tmp_path / "journal")
    assert not source.exists()
    assert (target / "same").read_bytes() == b"same media"
    assert (target / "repair").read_bytes() == b"complete media"
    assert (target / "repair").stat().st_mtime_ns == timestamp
    assert target.stat().st_mtime_ns == timestamp
    assert all("backup" not in entry for entry in plan["entries"])
    assert not list(target.glob("*.zero-byte-backup"))


def test_cleanup_does_not_remove_conflicting_files_or_new_files(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    (source / "file").write_bytes(b"local")
    (target / "file").write_bytes(b"server")
    plan = make_plan(
        scan(server, [drive], ["OnlyFans"]),
        ["samplecreator"],
        remove_duplicates=True,
        cleanup_empty=True,
    )
    assert plan["entries"][0]["action"] == "conflict"
    (source / "new").write_bytes(b"new")
    apply_plan(plan, tmp_path / "journal")
    assert (source / "file").read_bytes() == b"local"
    assert (source / "new").read_bytes() == b"new"


def test_duplicate_server_change_blocks_deletion(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    for root in (target, source):
        (root / "same").write_bytes(b"same")
        os.utime(root / "same", ns=(1000000000, 1000000000))
    plan = make_plan(
        scan(server, [drive], ["OnlyFans"]), ["samplecreator"], remove_duplicates=True, hash_collisions=True
    )
    (target / "same").write_bytes(b"bad!")
    os.utime(target / "same", ns=(1000000000, 1000000000))
    with pytest.raises(ValueError, match="Destination changed"):
        apply_plan(plan, tmp_path / "journal")
    assert (source / "same").read_bytes() == b"same"


def test_size_only_duplicate_removal_does_not_hash_and_deletes_source(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    (source / "same").write_bytes(b"media file content")
    (target / "same").write_bytes(b"media file content")
    plan = make_plan(
        scan(server, [drive], ["OnlyFans"]), ["samplecreator"], remove_duplicates=True, cleanup_empty=True
    )
    assert plan["entries"][0]["action"] == "remove_duplicate"
    assert plan["entries"][0]["reason"] == "verified_duplicate"
    assert "sha256" not in plan["entries"][0]["source_snapshot"]
    assert "sha256" not in plan["entries"][0]["destination_snapshot"]
    apply_plan(plan, tmp_path / "journal")
    assert not (source / "same").exists()
    assert (target / "same").read_bytes() == b"media file content"
    assert not source.exists()
    assert not source.parent.exists()


def test_failed_repair_copy_keeps_stub_and_source(tmp_path, monkeypatch):
    server, target, drive, source = fixture_archive(tmp_path)
    (source / "file").write_bytes(b"complete")
    (target / "file").write_bytes(b"")
    plan = make_plan(
        scan(server, [drive], ["OnlyFans"]), ["samplecreator"], repair_zero_bytes=True
    )

    def fail(*args, **kwargs):
        raise OSError("copy interrupted")

    monkeypatch.setattr(
        "ultima_scraper_backend.services.server_restore_files.shutil.copyfileobj", fail
    )
    with pytest.raises(OSError):
        apply_plan(plan, tmp_path / "journal")
    assert (source / "file").read_bytes() == b"complete"
    assert (target / "file").stat().st_size == 0


def test_server_file_changed_during_repair_is_not_overwritten(tmp_path, monkeypatch):
    from ultima_scraper_backend.services import server_restore_files as engine

    server, target, drive, source = fixture_archive(tmp_path)
    (source / "file").write_bytes(b"complete")
    (target / "file").write_bytes(b"")
    plan = make_plan(
        scan(server, [drive], ["OnlyFans"]), ["samplecreator"], repair_zero_bytes=True
    )
    copy = engine.shutil.copyfileobj

    def changed(*args, **kwargs):
        copy(*args, **kwargs)
        (target / "file").write_bytes(b"new server contents")

    monkeypatch.setattr(engine.shutil, "copyfileobj", changed)
    with pytest.raises(ValueError, match="repair target changed"):
        apply_plan(plan, tmp_path / "journal")
    assert (source / "file").read_bytes() == b"complete"
    assert (target / "file").read_bytes() == b"new server contents"


def test_duplicate_removal_with_mtime_mismatch_removes_source_and_empty_parent(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    (source / "file").write_bytes(b"content")
    (target / "file").write_bytes(b"content")
    os.utime(source / "file", ns=(1_000_000_000, 1_000_000_000))
    os.utime(target / "file", ns=(2_000_000_000, 2_000_000_000))
    plan = make_plan(
        scan(server, [drive], ["OnlyFans"]),
        ["samplecreator"],
        remove_duplicates=True,
        cleanup_empty=True,
    )
    assert plan["entries"][0]["action"] == "remove_duplicate"
    assert plan["entries"][0]["reason"] == "verified_duplicate"
    apply_plan(plan, tmp_path / "journal")
    assert not (source / "file").exists()
    assert not source.exists()
    assert not source.parent.exists()


def test_ignore_db_and_json_files_leaves_them_on_source_and_preserves_folder(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    (source / "media.mp4").write_bytes(b"video data")
    (source / "user_data.db").write_bytes(b"sqlite data")
    (source / "posts.json").write_bytes(b'{"posts": []}')
    plan = make_plan(
        scan(server, [drive], ["OnlyFans"]),
        ["samplecreator"],
        cleanup_empty=True,
    )
    assert len(plan["entries"]) == 1
    assert plan["entries"][0]["destination"] == str(target / "media.mp4")
    assert not any(e["source"].endswith((".db", ".json")) for e in plan["entries"])
    apply_plan(plan, tmp_path / "journal")
    assert (target / "media.mp4").read_bytes() == b"video data"
    assert not (source / "media.mp4").exists()
    assert (source / "user_data.db").read_bytes() == b"sqlite data"
    assert (source / "posts.json").read_bytes() == b'{"posts": []}'
    assert source.exists()


def test_disable_ignore_db_and_json_files_includes_them_in_plan(tmp_path):
    server, target, drive, source = fixture_archive(tmp_path)
    (source / "media.mp4").write_bytes(b"video data")
    (source / "user_data.db").write_bytes(b"sqlite data")
    (source / "posts.json").write_bytes(b'{"posts": []}')
    plan = make_plan(
        scan(server, [drive], ["OnlyFans"]),
        ["samplecreator"],
        ignore_db_json=False,
    )
    assert len(plan["entries"]) == 3
    destinations = {e["destination"] for e in plan["entries"]}
    assert str(target / "media.mp4") in destinations
    assert str(target / "user_data.db") in destinations
    assert str(target / "posts.json") in destinations

