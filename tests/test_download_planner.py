"""The download planner settles a batch without network requests."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import ultima_scraper_backend.job_system.handlers.download.handler as handler_module
from ultima_scraper_backend.job_system.download_manager import DownloadItem
from ultima_scraper_backend.job_system.events import DownloadFailureReason, DownloadResultItem
from ultima_scraper_backend.job_system.handlers.download.planner import plan_downloads
from ultima_scraper_backend.job_system.shared_media import (
    SharedMediaCopies,
    performer_tail_format,
)


def _signed(expires_at: float, name: str = "clip.mp4") -> str:
    policy = {
        "Statement": [
            {
                "Resource": f"https://cdn2.onlyfans.com/files/{name}",
                "Condition": {"DateLessThan": {"AWS:EpochTime": int(expires_at)}},
            }
        ]
    }
    encoded = (
        base64.b64encode(json.dumps(policy).encode())
        .decode()
        .replace("+", "-")
        .replace("=", "_")
        .replace("/", "~")
    )
    return f"https://cdn2.onlyfans.com/files/{name}?Policy={encoded}&Signature=x&Key-Pair-Id=k"


def _item(performer: Path, name: str, media_id: int, *, url: str | None = None) -> DownloadItem:
    content = SimpleNamespace(api_type="Stories", content_id=media_id + 1000, expires_at=None)
    return DownloadItem(
        url=url if url is not None else _signed(time.time() + 3600, name),
        filename=name,
        directory=performer / "Stories" / "Free" / "Videos",
        media_id=media_id,
        content_id=media_id + 1000,
        media_metadata=SimpleNamespace(content_metadata=content, drm=False, drm_media=None),  # type: ignore[arg-type]
    )


class _Selection:
    directory_format = None
    requires_full_directory_render = False

    def kept_directories_for(self, directory, base):
        return []

    def kept_directory_for(self, directory, base):
        return None


def _plan(monkeypatch, items, failures=(), shared=None):
    def build(*_args, failures: list[DownloadResultItem] | None = None, **_kwargs):
        if failures is not None:
            failures.extend(failures_to_add)
        return list(items)

    failures_to_add = list(failures)
    monkeypatch.setattr(handler_module, "_build_download_items", build)
    return plan_downloads(
        [],
        SimpleNamespace(),
        Path("/unused"),
        [],
        destination_selection=_Selection(),  # type: ignore[arg-type]
        shared_copies=shared,
    )


def test_plan_settles_existing_shared_expired_and_missing_links(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    performer = tmp_path / "tester"
    posted = performer / "Posts" / "Free" / "Videos" / "shared.mp4"
    posted.parent.mkdir(parents=True)
    posted.write_bytes(b"video")
    on_disk = _item(performer, "present.mp4", 1)
    on_disk.get_filepath().parent.mkdir(parents=True, exist_ok=True)
    on_disk.get_filepath().write_bytes(b"here")
    shared = _item(performer, "shared.mp4", 2)
    expired = _item(performer, "expired.mp4", 3, url=_signed(time.time() - 60, "expired.mp4"))
    no_link = _item(performer, "nolink.mp4", 4, url="")
    fresh = _item(performer, "fresh.mp4", 5)
    broken = DownloadResultItem(media_id=6, status="failed")
    finder = SharedMediaCopies(
        tail_format=performer_tail_format(
            "{site_name}/{user_username}/{content_type}/{content_value}/{media_type}"
        ),
        associations=lambda ids: {media_id: frozenset({"post", "story"}) for media_id in ids},
    )

    plan = _plan(
        monkeypatch, [on_disk, shared, expired, no_link, fresh], failures=[broken], shared=finder
    )

    assert plan.valid_items == [fresh]
    reasons = {
        result.media_id: [error.reason for error in result.errors] for result in plan.skipped_items
    }
    assert reasons[1] == [DownloadFailureReason.ALREADY_EXISTS]
    assert reasons[2] == [DownloadFailureReason.ALREADY_EXISTS]
    assert reasons[3] == [DownloadFailureReason.URL_EXPIRED]
    assert reasons[4] == [DownloadFailureReason.NO_URL]
    assert broken in plan.skipped_items
    assert plan.expired_items == [expired]
    assert plan.reused_copies == {"linked": 1}
    assert os.stat(shared.get_filepath()).st_ino == os.stat(posted).st_ino
    assert plan.total_items == 6


def test_replan_moves_refreshed_items_out_of_the_skipped_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    performer = tmp_path / "tester"
    expired = _item(performer, "a.mp4", 1, url=_signed(time.time() - 60, "a.mp4"))
    still_expired = _item(performer, "b.mp4", 2, url=_signed(time.time() - 60, "b.mp4"))
    plan = _plan(monkeypatch, [expired, still_expired])
    assert plan.valid_items == []

    expired.url = _signed(time.time() + 3600, "a.mp4")
    plan.replan([expired, still_expired])

    assert plan.valid_items == [expired]
    assert plan.expired_items == [still_expired]
    assert [result.media_id for result in plan.skipped_items] == [2]
