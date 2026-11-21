from __future__ import annotations

import errno
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import ultima_scraper_backend.job_system.shared_media as shared_media
from ultima_scraper_backend.job_system.download_manager import DownloadItem, DownloadManager
from ultima_scraper_backend.job_system.shared_media import (
    SharedMediaCopies,
    content_kind,
    performer_tail_format,
    place_existing_copy,
    reuse_shared_copies,
)

DEFAULT_FORMAT = (
    "{site_name}/{first_username_letter}/{user_username}/{content_type}/{content_value}/{media_type}"
)


def _item(performer: Path, content_type: str, *, media_id: int = 4357795507, size=None, drm=False):
    content = SimpleNamespace(api_type=content_type)
    metadata = SimpleNamespace(content_metadata=content, drm=drm)
    return DownloadItem(
        url="https://cdn.test/clip.mp4",
        filename="clip.mp4",
        directory=performer / content_type / "Free" / "Videos",
        media_id=media_id,
        size=size,
        media_metadata=metadata,  # type: ignore[arg-type]
    )


def _finder(performer: Path, kinds: set[str], queries: list[list[int]] | None = None) -> SharedMediaCopies:
    def associations(media_ids: list[int]) -> dict[int, frozenset[str]]:
        if queries is not None:
            queries.append(list(media_ids))
        return {media_id: frozenset(kinds) for media_id in media_ids}

    return SharedMediaCopies(
        tail_format=performer_tail_format(DEFAULT_FORMAT),
        associations=associations,
    )


def test_tail_format_is_only_reused_when_it_is_predictable() -> None:
    assert performer_tail_format(DEFAULT_FORMAT) == "{content_type}/{content_value}/{media_type}"
    assert performer_tail_format("{site_name}/{user_username}/{content_type}/{content_date}/{media_type}") is None
    assert performer_tail_format("{site_name}/{content_type}/{media_type}") is None
    assert performer_tail_format("{site_name}/{user_username}/{media_type}/{content_type}") is None


def test_content_kind_maps_highlights_to_stories() -> None:
    assert content_kind("Posts") == "post"
    assert content_kind("Archived/Posts") == "post"
    assert content_kind("Highlights") == "story"
    assert content_kind("Stories") == "story"
    assert content_kind("Messages") == "message"


def test_a_story_finds_the_copy_its_post_already_saved(tmp_path: Path) -> None:
    performer = tmp_path / "OnlyFans" / "T" / "tester"
    saved = performer / "Posts" / "Free" / "Videos" / "clip.mp4"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"video")

    story = _item(performer, "Stories")

    assert _finder(performer, {"post", "story"})(story) == saved


def test_media_in_one_kind_of_content_is_not_searched(tmp_path: Path) -> None:
    performer = tmp_path / "tester"
    own = performer / "Stories" / "Paid" / "Videos" / "clip.mp4"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"video")

    assert list(_finder(performer, {"story"}).candidates(_item(performer, "Stories"))) == []


def test_a_copy_of_another_size_is_not_reused(tmp_path: Path) -> None:
    performer = tmp_path / "tester"
    saved = performer / "Posts" / "Free" / "Videos" / "clip.mp4"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"short")

    assert _finder(performer, {"post", "story"})(_item(performer, "Stories", size=999)) is None
    # DRM sizes are of the encrypted streams, so only existence counts.
    drm_story = _item(performer, "Stories", size=999, drm=True)
    assert _finder(performer, {"post", "story"})(drm_story) == saved


def test_archived_posts_and_paid_messages_are_searched(tmp_path: Path) -> None:
    performer = tmp_path / "tester"
    archived = performer / "Archived" / "Posts" / "Free" / "Videos" / "clip.mp4"
    archived.parent.mkdir(parents=True)
    archived.write_bytes(b"video")
    paid = performer / "Messages" / "Paid" / "Videos" / "other.mp4"
    paid.parent.mkdir(parents=True)
    paid.write_bytes(b"video")

    assert _finder(performer, {"post", "story"})(_item(performer, "Stories")) == archived
    message_item = _item(performer, "Stories", media_id=2)
    message_item.filename = "other.mp4"
    assert _finder(performer, {"message", "story"})(message_item) == paid


def test_place_existing_copy_hardlinks_on_the_same_filesystem(tmp_path: Path) -> None:
    source = tmp_path / "Posts" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    dest = tmp_path / "Stories" / "Free" / "clip.mp4"

    assert place_existing_copy(source, dest) == ("linked", 5)
    assert os.stat(dest).st_ino == os.stat(source).st_ino


def test_place_existing_copy_copies_across_filesystems(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "a" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    dest = tmp_path / "b" / "clip.mp4"

    def cross_device(*_args):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(shared_media.os, "link", cross_device)

    assert place_existing_copy(source, dest) == ("copied", 5)
    assert dest.read_bytes() == b"video"
    assert os.stat(dest).st_ino != os.stat(source).st_ino
    assert not (tmp_path / "b" / "clip.mp4.copy").exists()


def test_place_existing_copy_keeps_a_file_that_appeared_meanwhile(tmp_path: Path) -> None:
    source = tmp_path / "a.mp4"
    source.write_bytes(b"video")
    dest = tmp_path / "b.mp4"
    dest.write_bytes(b"other")

    assert place_existing_copy(source, dest) == ("exists", 5)
    assert dest.read_bytes() == b"other"


@pytest.mark.asyncio
async def test_download_links_a_shared_copy_instead_of_fetching(tmp_path: Path) -> None:
    performer = tmp_path / "tester"
    saved = performer / "Posts" / "Free" / "Videos" / "clip.mp4"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"video")
    story = _item(performer, "Stories")
    manager = DownloadManager()
    manager.session = SimpleNamespace()  # type: ignore[assignment]  # any fetch would fail
    manager.find_existing_copy = _finder(performer, {"post", "story"})

    assert await manager.download(story) is True
    assert os.stat(story.get_filepath()).st_ino == os.stat(saved).st_ino
    assert manager.reused_copies == {"linked": 1}
    assert manager.completed == 1


def test_a_kept_folder_on_another_drive_is_searched(tmp_path: Path) -> None:
    performer = tmp_path / "drive1" / "tester"
    other_drive = tmp_path / "drive2" / "tester"
    saved = other_drive / "Posts" / "Free" / "Videos" / "clip.mp4"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"video")
    story = _item(performer, "Stories")
    story.kept_directories = [other_drive / "Stories" / "Free" / "Videos"]  # type: ignore[attr-defined]

    assert _finder(performer, {"post", "story"})(story) == saved


def test_batch_reuse_reads_associations_once_and_places_files_up_front(
    tmp_path: Path,
) -> None:
    performer = tmp_path / "tester"
    saved = performer / "Posts" / "Free" / "Videos" / "clip.mp4"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(b"video")
    shared = _item(performer, "Stories", media_id=1)
    missing = _item(performer, "Stories", media_id=2)
    missing.filename = "not-saved.mp4"
    present = _item(performer, "Stories", media_id=3)
    present.get_filepath().parent.mkdir(parents=True, exist_ok=True)
    present.filename = "present.mp4"
    present.get_filepath().write_bytes(b"here")
    queries: list[list[int]] = []
    finder = _finder(performer, {"post", "story"}, queries)

    counts = reuse_shared_copies([shared, missing, present], finder)

    assert counts == {"linked": 1}
    assert queries == [[1, 2]]
    assert os.stat(shared.get_filepath()).st_ino == os.stat(saved).st_ino
    assert not missing.get_filepath().exists()
    # A later per-item check reuses what the batch read.
    assert finder(missing) is None
    assert queries == [[1, 2]]
