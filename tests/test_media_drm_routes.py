"""Tests for DRM browser-playback routes (manifest rewrite, segment, license)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from ultima_scraper_backend.api.routes import media as media_module


class _FakeExecResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def first(self) -> object | None:
        return self._value


class _FakeSession:
    def __init__(self, media: object | None) -> None:
        self._media = media

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def exec(self, _query: object) -> _FakeExecResult:
        return _FakeExecResult(self._media)


class _FakeSiteDB:
    def __init__(self, media: object | None) -> None:
        self._media = media

    def get_session(self) -> _FakeSession:
        return _FakeSession(self._media)


class _FakeDBManager:
    def __init__(self, media: object | None) -> None:
        self._media = media

    def get_or_create_manager(self, _site: str) -> _FakeSiteDB:
        return _FakeSiteDB(self._media)


def _make_drm_media(**overrides: Any) -> SimpleNamespace:
    base = dict(
        id=4385399549,
        user_id=1,
        url=None,
        category="video",
        media_urls=[SimpleNamespace(auth_id=42, url=None)],
        drm_manifest=SimpleNamespace(
            dash_manifest=(
                "https://cdn3.onlyfans.com/dash/files/9/9a/xxxx/0ibvf8g1wqq8yyo2hed3s.mpd"
            ),
            dash_key_pair_id="K1JM1KV0NHNR73",
            dash_policy="valid-policy",
            dash_signature="sig",
            video_url=None,
            audio_url=None,
            video_size=None,
            audio_size=None,
        ),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeContentResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        text: str = "",
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.status = status
        self._text = text
        self._body = body
        self.headers = headers or {}
        self.content_type = content_type

        async def _iter(_chunk_size: int):
            yield self._body

        self.content = SimpleNamespace(iter_chunked=lambda _cs: _iter(_cs))

    async def text(self) -> str:
        return self._text

    async def read(self) -> bytes:
        return self._body


@pytest.fixture(autouse=True)
def _patch_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``_is_drm_policy_usable`` decodes a signed CloudFront policy. The fixture
    # short-circuits that so tests can use synthetic policy strings.
    monkeypatch.setattr(media_module, "_is_drm_policy_usable", lambda _p: True)
    # ``_primary_content_info`` walks association tables; fake a post row.
    monkeypatch.setattr(
        media_module, "_primary_content_info", lambda _s, _m: ("post", 9001)
    )

    async def run_inline(function: object, *args: object, **kwargs: object) -> object:
        return function(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(media_module.asyncio, "to_thread", run_inline)


def _make_request(headers: dict[str, str] | None = None) -> Any:
    return SimpleNamespace(headers=headers or {}, body=AsyncMock(return_value=b""))


@pytest.mark.asyncio
async def test_drm_manifest_rewrites_base_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_xml = """<?xml version="1.0"?>
<MPD>
  <Period><AdaptationSet>
    <Representation><BaseURL>0ibvf8g1wqq8yyo2hed3s_source.mp4</BaseURL></Representation>
    <Representation><BaseURL>0ibvf8g1wqq8yyo2hed3s_audio.mp4</BaseURL></Representation>
  </AdaptationSet></Period>
</MPD>""".strip()

    monkeypatch.setattr(
        media_module,
        "MultiSiteDatabaseManager",
        lambda: _FakeDBManager(_make_drm_media()),
    )
    fetch_mock = AsyncMock(
        return_value=_FakeContentResponse(status=200, text=manifest_xml)
    )
    monkeypatch.setattr(media_module, "_fetch_via_auth", fetch_mock)

    backend_manager = SimpleNamespace()
    response = await media_module.get_drm_manifest(
        "OnlyFans",
        4385399549,
        _make_request(),
        backend_manager=backend_manager,
    )

    body = bytes(response.body).decode()
    assert "<BaseURL>segment/0ibvf8g1wqq8yyo2hed3s_source.mp4</BaseURL>" in body
    assert "<BaseURL>segment/0ibvf8g1wqq8yyo2hed3s_audio.mp4</BaseURL>" in body
    assert response.media_type == "application/dash+xml"
    assert response.headers.get("cache-control") == "no-store"
    fetch_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_drm_manifest_rejects_traversal(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_xml = (
        "<MPD><Period><AdaptationSet><Representation>"
        "<BaseURL>../../../etc/passwd</BaseURL>"
        "</Representation></AdaptationSet></Period></MPD>"
    )
    monkeypatch.setattr(
        media_module,
        "MultiSiteDatabaseManager",
        lambda: _FakeDBManager(_make_drm_media()),
    )
    monkeypatch.setattr(
        media_module,
        "_fetch_via_auth",
        AsyncMock(return_value=_FakeContentResponse(status=200, text=manifest_xml)),
    )

    response = await media_module.get_drm_manifest(
        "OnlyFans", 4385399549, _make_request(), backend_manager=SimpleNamespace()
    )
    # Unsafe BaseURL is left untouched (not rewritten through the proxy).
    body = bytes(response.body).decode()
    assert "segment/" not in body
    assert "../../../etc/passwd" in body


@pytest.mark.asyncio
async def test_drm_segment_proxies_range_and_preserves_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_response = _FakeContentResponse(
        status=206,
        body=b"encrypted-chunk",
        headers={
            "Content-Length": "15",
            "Content-Range": "bytes 0-14/82757852",
            "Content-Type": "video/mp4",
        },
        content_type="video/mp4",
    )
    monkeypatch.setattr(
        media_module,
        "MultiSiteDatabaseManager",
        lambda: _FakeDBManager(_make_drm_media()),
    )

    auth_session = SimpleNamespace(request=AsyncMock(return_value=fake_response))
    backend_manager = SimpleNamespace(
        get_authed_session=AsyncMock(
            return_value=SimpleNamespace(auth_session=auth_session)
        )
    )

    request = _make_request({"range": "bytes=0-14"})
    response = await media_module.proxy_drm_segment(
        "OnlyFans",
        4385399549,
        "0ibvf8g1wqq8yyo2hed3s_source.mp4",
        request,
        backend_manager=backend_manager,
    )

    assert response.status_code == 206
    assert response.headers["content-length"] == "15"
    assert response.headers["content-range"] == "bytes 0-14/82757852"
    assert response.headers["accept-ranges"] == "bytes"

    auth_session.request.assert_awaited_once()
    call = auth_session.request.await_args
    assert call.kwargs["range_header"] == {"Range": "bytes=0-14"}
    assert call.kwargs["custom_cookies"]  # CloudFront cookies forwarded


@pytest.mark.asyncio
async def test_drm_segment_rejects_traversal() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await media_module.proxy_drm_segment(
            "OnlyFans",
            4385399549,
            "../../secret.mp4",
            _make_request(),
            backend_manager=SimpleNamespace(),
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_drm_license_forwards_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    challenge_body = b"\x08\x01\x12widevine-challenge"
    license_bytes = b"\x08\x02\x12widevine-license"

    monkeypatch.setattr(
        media_module,
        "MultiSiteDatabaseManager",
        lambda: _FakeDBManager(_make_drm_media()),
    )
    fetch_mock = AsyncMock(
        return_value=_FakeContentResponse(status=200, body=license_bytes)
    )
    monkeypatch.setattr(media_module, "_fetch_via_auth", fetch_mock)

    request = SimpleNamespace(
        headers={},
        body=AsyncMock(return_value=challenge_body),
    )
    response = await media_module.proxy_drm_license(
        "OnlyFans",
        4385399549,
        request,
        backend_manager=SimpleNamespace(),
    )
    assert bytes(response.body) == license_bytes
    assert response.media_type == "application/octet-stream"

    fetch_mock.assert_awaited_once()
    call = fetch_mock.await_args
    assert call.kwargs["method"] == "POST"
    assert call.kwargs["data"] == challenge_body
    assert "/drm/" in call.args[0]
    assert "type=widevine" in call.args[0]


@pytest.mark.asyncio
async def test_drm_license_rejects_oversized_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        media_module,
        "MultiSiteDatabaseManager",
        lambda: _FakeDBManager(_make_drm_media()),
    )
    oversized = b"x" * (media_module._MAX_DRM_LICENSE_BYTES + 1)
    request = SimpleNamespace(
        headers={},
        body=AsyncMock(return_value=oversized),
    )
    with pytest.raises(HTTPException) as exc_info:
        await media_module.proxy_drm_license(
            "OnlyFans",
            4385399549,
            request,
            backend_manager=SimpleNamespace(),
        )
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_drm_manifest_missing_drm_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = SimpleNamespace(id=1, media_urls=[], drm_manifest=None)
    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(media)
    )
    with pytest.raises(HTTPException) as exc_info:
        await media_module.get_drm_manifest(
            "OnlyFans", 1, _make_request(), backend_manager=SimpleNamespace()
        )
    assert exc_info.value.status_code == 404
