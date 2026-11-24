from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ultima_scraper_backend import object_storage
from ultima_scraper_backend.api import dependencies
from ultima_scraper_backend.api.routes import object_storage as routes
from ultima_scraper_backend.object_storage import (
    MediaInfo,
    StorageTarget,
    ThumbnailRequest,
    ThumbnailToolMissing,
    parse_probe,
    upload_file,
)

TARGET = {"endpoint": "https://s3.test", "bucket": "hot", "key_id": "id", "secret_key": "very-secret"}


class FakeStore:
    def __init__(self, fail: set[str] | None = None) -> None:
        self.uploaded: dict[str, tuple[str, int]] = {}
        self.deleted: list[str] = []
        self.fail = fail or set()

    def upload(self, key: str, path: str, content_type: str) -> None:
        if key in self.fail:
            raise RuntimeError("bucket said no")
        self.uploaded[key] = (content_type, Path(path).stat().st_size)

    def delete(self, key: str) -> None:
        if key in self.fail:
            raise RuntimeError("bucket said no")
        self.deleted.append(key)


class FakeThumbs:
    def __init__(self, *, error: Exception | None = None, info: MediaInfo | None = None) -> None:
        self.error = error
        self.info = info or MediaInfo(width=1080, height=1920, duration_seconds=12.5)
        self.calls: list[tuple[int, int]] = []

    def make(self, source: str, content_type: str, dest: str, *, width: int, max_height: int) -> MediaInfo | None:
        self.calls.append((width, max_height))
        if self.error:
            raise self.error
        if not content_type.startswith(("image/", "video/")):
            return None
        Path(dest).write_bytes(b"RIFF....WEBP" + b"x" * 20)
        return self.info


@pytest.fixture()
def media(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"v" * 300)
    return path


def test_upload_with_thumbnail_reports_its_size(media: Path) -> None:
    store, thumbs = FakeStore(), FakeThumbs()
    result = upload_file(
        store, media, "onlyfans/1", "video/mp4", thumbnail=ThumbnailRequest(key="thumbs/onlyfans/1.webp"), thumbnails=thumbs
    )
    assert store.uploaded == {"onlyfans/1": ("video/mp4", 300), "thumbs/onlyfans/1.webp": ("image/webp", 32)}
    assert thumbs.calls == [(480, 1920)]
    assert (result.state, result.size_bytes, result.thumbnail_state, result.thumbnail_bytes) == ("uploaded", 300, "ready", 32)
    assert (result.width, result.height, result.duration_seconds) == (1080, 1920, 12.5)


@pytest.mark.parametrize(
    ("thumbs", "content_type", "state"),
    [
        (FakeThumbs(), "audio/mpeg", "none"),
        (FakeThumbs(error=OSError("cannot identify image file")), "image/jpeg", "failed"),
        (FakeThumbs(error=ThumbnailToolMissing("ffmpeg and ffprobe must be on PATH")), "image/jpeg", "unavailable"),
    ],
)
def test_thumbnail_outcomes_keep_the_upload(media: Path, thumbs: FakeThumbs, content_type: str, state: str) -> None:
    store = FakeStore()
    result = upload_file(store, media, "k", content_type, thumbnail=ThumbnailRequest(key="t"), thumbnails=thumbs)
    assert result.state == "uploaded" and result.thumbnail_state == state
    assert list(store.uploaded) == ["k"]


def test_failed_thumbnail_upload_is_retryable(media: Path) -> None:
    result = upload_file(
        FakeStore(fail={"t"}), media, "k", "video/mp4", thumbnail=ThumbnailRequest(key="t"), thumbnails=FakeThumbs()
    )
    assert result.thumbnail_state == "unavailable" and "Thumbnail upload failed" in str(result.thumbnail_error)


def test_probe_swaps_quarter_turned_video() -> None:
    data = {
        "streams": [{"codec_type": "video", "width": 1920, "height": 1080, "side_data_list": [{"rotation": -90}]}],
        "format": {"duration": "61.5"},
    }
    assert parse_probe(data) == MediaInfo(width=1080, height=1920, duration_seconds=61.5)
    assert parse_probe({"streams": [{"codec_type": "audio"}], "format": {"duration": "3"}}) == MediaInfo(
        duration_seconds=3.0
    )


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")
def test_ffmpeg_thumbnails_are_small_webp(tmp_path: Path) -> None:
    image, clip = tmp_path / "wide.png", tmp_path / "clip.mp4"
    common = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i"]
    subprocess.run([*common, "testsrc=size=1280x720", "-frames:v", "1", str(image)], check=True)
    subprocess.run([*common, "testsrc=size=640x360:duration=3:rate=10", str(clip)], check=True)
    thumbs = object_storage.FfmpegThumbnails()

    def size(path: Path) -> tuple[int, int]:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, check=True
        )
        stream = json.loads(out.stdout)["streams"][0]
        return stream["width"], stream["height"]

    info = thumbs.make(str(image), "image/png", str(tmp_path / "a.webp"), width=480, max_height=1920)
    assert info == MediaInfo(width=1280, height=720) and size(tmp_path / "a.webp") == (480, 270)
    info = thumbs.make(str(clip), "video/mp4", str(tmp_path / "b.webp"), width=480, max_height=1920)
    assert info is not None and (info.width, info.height) == (640, 360) and info.duration_seconds
    assert size(tmp_path / "b.webp") == (480, 270)
    # Never enlarged.
    thumbs.make(str(clip), "video/mp4", str(tmp_path / "c.webp"), width=1000, max_height=4000)
    assert size(tmp_path / "c.webp") == (640, 360)


# --------------------------------------------------------------------------- routes


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch, media: Path) -> tuple[TestClient, dict[str, Any]]:
    """The routes with targets in a dict instead of the settings table, and a fake bucket."""
    targets: dict[str, StorageTarget] = {}
    state: dict[str, Any] = {"targets": targets, "store": FakeStore(), "files": {("onlyfans", 1): media}}
    monkeypatch.setattr(object_storage, "save_target", lambda name, target: targets.__setitem__(name, target))
    monkeypatch.setattr(object_storage, "load_target", lambda name: targets.get(name))
    monkeypatch.setattr(object_storage, "delete_target", lambda name: targets.pop(name, None) is not None)
    monkeypatch.setattr(object_storage, "list_targets", lambda: {n: t.public() for n, t in targets.items()})
    monkeypatch.setattr(routes, "_store_for", lambda target: state["store"])

    async def resolve(site: str, media_id: int, config: object) -> Path | None:
        return state["files"].get((site.lower(), media_id))

    monkeypatch.setattr(routes, "resolve_local_media_file", resolve)
    monkeypatch.setattr(object_storage, "FfmpegThumbnails", lambda: FakeThumbs())
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[dependencies.get_config] = lambda: object()
    return TestClient(app), state


def test_targets_hide_their_secret(api: tuple[TestClient, dict[str, Any]]) -> None:
    client, state = api
    response = client.put("/api/v1/object-storage/targets/usweb-hot", json=TARGET)
    assert response.status_code == 200 and "secret_key" not in response.json()
    assert state["targets"]["usweb-hot"].secret_key == "very-secret"
    listed = client.get("/api/v1/object-storage/targets").json()
    assert listed == {"usweb-hot": {"endpoint": "https://s3.test", "bucket": "hot", "key_id": "id", "region": None}}
    assert client.put("/api/v1/object-storage/targets/Bad Name", json=TARGET).status_code == 422
    assert client.delete("/api/v1/object-storage/targets/usweb-hot").status_code == 204
    assert client.delete("/api/v1/object-storage/targets/usweb-hot").status_code == 404


def test_upload_route(api: tuple[TestClient, dict[str, Any]]) -> None:
    client, state = api
    body = {"site": "OnlyFans", "media_id": 1, "key": "onlyfans/1", "thumbnail": {"key": "thumbs/onlyfans/1.webp"}}
    assert client.post("/api/v1/object-storage/targets/nope/uploads", json=body).status_code == 404
    client.put("/api/v1/object-storage/targets/hot", json=TARGET)

    done = client.post("/api/v1/object-storage/targets/hot/uploads", json=body).json()
    assert done["state"] == "uploaded" and done["size_bytes"] == 300 and done["content_type"] == "video/mp4"
    assert done["thumbnail_state"] == "ready" and done["duration_seconds"] == 12.5
    assert set(state["store"].uploaded) == {"onlyfans/1", "thumbs/onlyfans/1.webp"}

    missing = client.post("/api/v1/object-storage/targets/hot/uploads", json={**body, "media_id": 2}).json()
    assert missing["state"] == "missing"

    state["store"] = FakeStore(fail={"onlyfans/1"})
    refused = client.post("/api/v1/object-storage/targets/hot/uploads", json=body)
    assert refused.status_code == 502 and "bucket said no" in refused.json()["detail"]


def test_thumbnail_only_upload_leaves_the_original(api: tuple[TestClient, dict[str, Any]]) -> None:
    client, state = api
    client.put("/api/v1/object-storage/targets/hot", json=TARGET)
    body = {"site": "onlyfans", "media_id": 1, "key": "onlyfans/1", "upload_original": False, "thumbnail": {"key": "t/1.webp"}}
    done = client.post("/api/v1/object-storage/targets/hot/uploads", json=body).json()
    assert done["thumbnail_state"] == "ready" and list(state["store"].uploaded) == ["t/1.webp"]


def test_delete_route_reports_each_key(api: tuple[TestClient, dict[str, Any]]) -> None:
    client, state = api
    client.put("/api/v1/object-storage/targets/hot", json=TARGET)
    state["store"] = FakeStore(fail={"b"})
    result = client.post("/api/v1/object-storage/targets/hot/deletes", json={"keys": ["a", "b"]}).json()
    assert result == {"deleted": ["a"], "failed": {"b": "bucket said no"}}
