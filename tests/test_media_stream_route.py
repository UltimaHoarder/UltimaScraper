from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from ultima_scraper_backend.api.routes import media as media_module


@pytest.fixture(autouse=True)
def _run_thread_offloads_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep route tests deterministic while production work uses threads."""

    async def run_inline(function: object, *args: object, **kwargs: object) -> object:
        return function(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(media_module.asyncio, "to_thread", run_inline)


class _FakeExecResult:
    def __init__(self, media: object | None) -> None:
        self._media = media

    def first(self) -> object | None:
        return self._media

    def all(self) -> list[object]:
        return []


class _FakeSession:
    def __init__(self, media: object | None) -> None:
        self._media = media

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
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

    def get_or_create_manager(self, _site_name: str) -> _FakeSiteDB:
        return _FakeSiteDB(self._media)


@pytest.mark.asyncio
async def test_content_lookup_by_media_id_uses_stable_archive_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = media_module.FilenameLookupResponse(media=[])
    captured: list[set[int]] = []

    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(34931)
    )
    monkeypatch.setattr(
        media_module,
        "_associated_content_for_media_ids",
        lambda _session, media_ids: captured.append(media_ids) or expected,
    )
    monkeypatch.setattr(
        media_module.asyncio,
        "to_thread",
        AsyncMock(side_effect=lambda function: function()),
    )

    result = await media_module.get_content_by_media_id(
        "OnlyFans", 34931, SimpleNamespace(redis=None)
    )

    assert result is expected
    assert captured == [{34931}]


@pytest.mark.asyncio
async def test_content_lookup_by_media_id_returns_redis_cache_without_database_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = media_module.FilenameLookupResponse(media=[])
    redis = SimpleNamespace(get=AsyncMock(return_value=expected.model_dump_json()))
    backend_manager = SimpleNamespace(redis=redis)
    monkeypatch.setattr(
        media_module,
        "MultiSiteDatabaseManager",
        lambda: pytest.fail("database should not be queried for a cache hit"),
    )

    result = await media_module.get_content_by_media_id(
        "OnlyFans", 34931, backend_manager
    )

    assert result == expected
    redis.get.assert_awaited_once_with(
        "ultimascraper:associated-content:v2:onlyfans:media:34931"
    )


@pytest.mark.asyncio
async def test_associated_content_cache_write_uses_a_month_ttl() -> None:
    redis = SimpleNamespace(set=AsyncMock(return_value=True))
    backend_manager = SimpleNamespace(redis=redis)
    response = media_module.FilenameLookupResponse(media=[])

    await media_module._cache_associated_content(backend_manager, "cache-key", response)

    redis.set.assert_awaited_once_with(
        "cache-key", response.model_dump_json(), ex=30 * 24 * 60 * 60
    )


@pytest.mark.asyncio
async def test_stream_local_media_prefers_remote_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy_response = StreamingResponse(iter([b"remote-bytes"]), media_type="image/jpeg")
    proxy_mock = AsyncMock(return_value=proxy_response)
    fake_media = SimpleNamespace(
        id=123,
        user_id=456,
        url="https://cdn.example.test/media.jpg",
        filepaths=[],
    )
    backend_manager = SimpleNamespace()

    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(fake_media)
    )
    monkeypatch.setattr(
        media_module,
        "_resolve_configured_media_file",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(media_module, "proxy_stream_url", proxy_mock)

    response = await media_module.stream_local_media(
        "OnlyFans",
        123,
        config=SimpleNamespace(),
        backend_manager=backend_manager,
    )

    assert response is proxy_response
    proxy_mock.assert_awaited_once_with(
        "https://cdn.example.test/media.jpg",
        "onlyfans",
        backend_manager,
        None,
        custom_cookies="",
    )


@pytest.mark.asyncio
async def test_stream_local_media_prefers_existing_disk_file_over_proxy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local_file = tmp_path / "media.mp4"
    local_file.write_bytes(b"local-bytes")
    proxy_mock = AsyncMock(
        side_effect=HTTPException(status_code=502, detail="bad gateway")
    )
    fake_media = SimpleNamespace(
        id=124,
        user_id=457,
        url="https://cdn.example.test/media-fallback.mp4",
        filepaths=[SimpleNamespace(filepath=str(local_file), preview=False)],
        category="video",
        created_at=None,
    )
    backend_manager = SimpleNamespace()

    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(fake_media)
    )
    monkeypatch.setattr(media_module, "proxy_stream_url", proxy_mock)

    response = await media_module.stream_local_media(
        "OnlyFans",
        124,
        config=SimpleNamespace(),
        backend_manager=backend_manager,
    )

    assert isinstance(response, FileResponse)
    assert Path(str(response.path)) == local_file
    assert response.media_type == "video/mp4"
    proxy_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_local_media_checks_configured_path_before_remote_proxy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local_file = tmp_path / "configured" / "media.mp4"
    local_file.parent.mkdir()
    local_file.write_bytes(b"local-bytes")
    proxy_mock = AsyncMock(
        side_effect=HTTPException(status_code=502, detail="remote should not run")
    )
    configured_resolver = AsyncMock(return_value=local_file)
    fake_media = SimpleNamespace(
        id=129,
        user_id=462,
        url="https://cdn.example.test/slow-or-expired.mp4",
        filepaths=[],
        media_urls=[],
        drm_manifest=None,
        category="video",
        created_at=None,
    )

    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(fake_media)
    )
    monkeypatch.setattr(
        media_module,
        "_resolve_configured_media_file",
        configured_resolver,
    )
    monkeypatch.setattr(media_module, "proxy_stream_url", proxy_mock)

    response = await media_module.stream_local_media(
        "OnlyFans",
        129,
        config=SimpleNamespace(),
        backend_manager=SimpleNamespace(),
    )

    assert isinstance(response, FileResponse)
    assert Path(str(response.path)) == local_file
    configured_resolver.assert_awaited_once()
    proxy_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_releases_database_session_before_storage_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local_file = tmp_path / "media.mp4"
    local_file.write_bytes(b"local-bytes")
    fake_media = SimpleNamespace(
        id=131,
        user_id=464,
        username="performer",
        aliases=[],
        url=None,
        media_urls=[],
        filepaths=[],
        drm_manifest=None,
        category="video",
        created_at=None,
    )
    session_state = {"closed": False}

    class TrackingSession(_FakeSession):
        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            session_state["closed"] = True

    class TrackingSiteDB(_FakeSiteDB):
        def get_session(self) -> TrackingSession:
            return TrackingSession(self._media)

    class TrackingDBManager(_FakeDBManager):
        def get_or_create_manager(self, _site_name: str) -> TrackingSiteDB:
            return TrackingSiteDB(self._media)

    async def resolve_after_close(*_args: object, **_kwargs: object) -> Path:
        assert session_state["closed"] is True
        return local_file

    monkeypatch.setattr(
        media_module,
        "MultiSiteDatabaseManager",
        lambda: TrackingDBManager(fake_media),
    )
    monkeypatch.setattr(
        media_module,
        "_resolve_stored_media_file",
        resolve_after_close,
    )

    response = await media_module.stream_local_media(
        "OnlyFans",
        131,
        config=SimpleNamespace(),
        backend_manager=SimpleNamespace(),
    )

    assert isinstance(response, FileResponse)
    assert Path(str(response.path)) == local_file


@pytest.mark.asyncio
async def test_thumbnail_resolves_stale_filepath_from_performer_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stale_file = tmp_path / "old" / "clip.mp4"
    resolved_file = tmp_path / "performer" / "renamed-clip.mp4"
    resolved_file.parent.mkdir()
    resolved_file.write_bytes(b"video-bytes")
    thumbnail_file = tmp_path / "thumbnails" / "large" / "clip.png"
    thumbnail_file.parent.mkdir(parents=True)
    thumbnail_file.write_bytes(b"png-bytes")
    fake_media = SimpleNamespace(
        id=127,
        user_id=460,
        url="https://cdn.example.test/clip.mp4",
        filepaths=[SimpleNamespace(filepath=str(stale_file), preview=False)],
        aliases=[SimpleNamespace(username="legacy_performer")],
        category="video",
        created_at=None,
    )
    config = SimpleNamespace(
        settings=SimpleNamespace(thumbnails_directory=tmp_path / "thumbnails")
    )
    thumbnail_calls: list[tuple[Path, Path, bool]] = []
    performer_usernames: list[str] = []

    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(fake_media)
    )
    monkeypatch.setattr(
        media_module,
        "find_performer_media_file",
        lambda *_args, **kwargs: (
            performer_usernames.extend(kwargs["usernames"]) or resolved_file
        ),
    )
    monkeypatch.setattr(
        media_module,
        "get_or_create_thumbnail",
        lambda source, directory, *, is_video: (
            thumbnail_calls.append((source, directory, is_video)) or thumbnail_file
        ),
    )

    async def run_inline(function: object, *args: object, **kwargs: object) -> object:
        return function(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(media_module.asyncio, "to_thread", run_inline)

    response = await media_module.get_media_thumbnail(
        "OnlyFans",
        127,
        config=config,
        backend_manager=SimpleNamespace(),
    )

    assert isinstance(response, FileResponse)
    assert Path(str(response.path)) == thumbnail_file
    assert thumbnail_calls == [
        (resolved_file, tmp_path / "thumbnails", True)
    ]
    assert performer_usernames == ["legacy_performer", "u460"]


@pytest.mark.asyncio
async def test_thumbnail_uses_remote_media_when_local_resolution_misses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    thumbnail_file = tmp_path / "thumbnails" / "large" / "remote.png"
    thumbnail_file.parent.mkdir(parents=True)
    thumbnail_file.write_bytes(b"png-bytes")
    fake_media = SimpleNamespace(
        id=128,
        user_id=461,
        url="https://cdn.example.test/remote.mp4",
        media_urls=[],
        filepaths=[],
        drm_manifest=None,
        category="video",
        created_at=None,
    )
    config = SimpleNamespace(
        settings=SimpleNamespace(thumbnails_directory=tmp_path / "thumbnails")
    )
    remote_calls: list[tuple[str, str, Path, bool, str]] = []

    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(fake_media)
    )
    monkeypatch.setattr(
        media_module,
        "_resolve_configured_media_file",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        media_module,
        "_remote_thumbnail_source_is_reachable",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(media_module, "validate_outbound_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        media_module,
        "get_or_create_remote_thumbnail",
        lambda url, cache_key, directory, *, is_video, custom_cookies, **_network: (
            remote_calls.append(
                (url, cache_key, directory, is_video, custom_cookies)
            )
            or thumbnail_file
        ),
    )

    async def run_inline(function: object, *args: object, **kwargs: object) -> object:
        return function(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(media_module.asyncio, "to_thread", run_inline)

    response = await media_module.get_media_thumbnail(
        "OnlyFans",
        128,
        config=config,
        backend_manager=SimpleNamespace(),
    )

    assert isinstance(response, FileResponse)
    assert Path(str(response.path)) == thumbnail_file
    assert remote_calls == [
        (
            "https://cdn.example.test/remote.mp4",
            "onlyfans:128",
            tmp_path / "thumbnails",
            True,
            "",
        )
    ]


@pytest.mark.asyncio
async def test_remote_thumbnail_head_probe_uses_stored_credentials_without_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeResponse:
        status = 204

        async def __aenter__(self) -> FakeResponse:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeClientSession:
        def __init__(self, **kwargs: object) -> None:
            observed["session"] = kwargs

        async def __aenter__(self) -> FakeClientSession:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def head(self, url: str, **kwargs: object) -> FakeResponse:
            observed["url"] = url
            observed["request"] = kwargs
            return FakeResponse()

    backend_manager = SimpleNamespace(
        get_account_request_context=MagicMock(
            return_value=media_module.AccountRequestContext(
                cookie="sess=stored",
                authorization="Bearer stored",
                user_agent="Stored Agent",
                proxy_url="http://proxy.example.test:8080",
            )
        ),
        get_authed_session=AsyncMock(),
    )
    candidate = media_module._RemoteStreamCandidate(
        "https://cdn.example.test/remote.mp4",
        auth_id=901,
        custom_cookies="CloudFront-Policy=policy",
    )
    monkeypatch.setattr(
        media_module,
        "validate_outbound_url",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(media_module.aiohttp, "ClientSession", FakeClientSession)

    reachable = await media_module._remote_thumbnail_source_is_reachable(
        backend_manager,
        "onlyfans",
        candidate,
    )

    assert reachable is True
    backend_manager.get_account_request_context.assert_called_once_with(
        "onlyfans", 901
    )
    backend_manager.get_authed_session.assert_not_awaited()
    assert observed["url"] == "https://cdn.example.test/remote.mp4"
    assert observed["request"] == {
        "headers": {
            "Cookie": "sess=stored; CloudFront-Policy=policy",
            "Authorization": "Bearer stored",
            "User-Agent": "Stored Agent",
        },
        "proxy": "http://proxy.example.test:8080",
        "allow_redirects": True,
    }


@pytest.mark.asyncio
async def test_remote_media_stream_uses_stored_credentials_without_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeContent:
        async def iter_chunked(self, _size: int):
            yield b"remote-video"

    class FakeResponse:
        status = 206
        content_type = "video/mp4"
        content_length = 12
        content = FakeContent()
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Range": "bytes 0-11/12",
        }

        def close(self) -> None:
            observed["response_closed"] = True

    class FakeClientSession:
        def __init__(self, **kwargs: object) -> None:
            observed["session"] = kwargs

        async def get(self, url: str, **kwargs: object) -> FakeResponse:
            observed["url"] = url
            observed["request"] = kwargs
            return FakeResponse()

        async def close(self) -> None:
            observed["session_closed"] = True

    backend_manager = SimpleNamespace(
        get_account_request_context=MagicMock(
            return_value=media_module.AccountRequestContext(
                cookie="sess=stored",
                user_agent="Stored Agent",
            )
        ),
        get_authed_session=AsyncMock(),
    )
    monkeypatch.setattr(
        media_module,
        "validate_outbound_url",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(media_module.aiohttp, "ClientSession", FakeClientSession)

    response = await media_module.proxy_stream_url(
        "https://cdn.example.test/remote.mp4",
        "onlyfans",
        backend_manager,
        901,
        custom_cookies="CloudFront-Policy=policy",
    )
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert body == b"remote-video"
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-11/12"
    backend_manager.get_account_request_context.assert_called_once_with(
        "onlyfans", 901
    )
    backend_manager.get_authed_session.assert_not_awaited()
    assert observed["request"] == {
        "headers": {
            "Cookie": "sess=stored; CloudFront-Policy=policy",
            "User-Agent": "Stored Agent",
        },
        "proxy": None,
    }
    assert observed["response_closed"] is True
    assert observed["session_closed"] is True


@pytest.mark.asyncio
async def test_remote_thumbnail_skips_ffmpeg_when_head_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_media = SimpleNamespace(
        id=129,
        user_id=462,
        url="https://cdn.example.test/stale.mp4",
        media_urls=[],
        filepaths=[],
        drm_manifest=None,
        category="video",
        created_at=None,
    )
    config = SimpleNamespace(
        settings=SimpleNamespace(thumbnails_directory=tmp_path / "thumbnails")
    )
    remote_thumbnail = AsyncMock()

    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(fake_media)
    )
    monkeypatch.setattr(
        media_module,
        "_resolve_configured_media_file",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        media_module,
        "_remote_thumbnail_source_is_reachable",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        media_module,
        "get_or_create_remote_thumbnail",
        remote_thumbnail,
    )

    with pytest.raises(HTTPException) as exc_info:
        await media_module.get_media_thumbnail(
            "OnlyFans",
            129,
            config=config,
            backend_manager=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    remote_thumbnail.assert_not_awaited()


@pytest.mark.asyncio
async def test_remote_only_thumbnail_generation_is_deferred_from_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_key = "onlyfans:131"
    thumbnail_file = media_module.get_remote_thumbnail_path(
        cache_key,
        tmp_path / "thumbnails",
    )
    fake_media = SimpleNamespace(
        id=131,
        user_id=464,
        url="https://cdn.example.test/remote.mp4",
        media_urls=[],
        filepaths=[],
        drm_manifest=None,
        category="video",
        created_at=None,
    )
    config = SimpleNamespace(
        settings=SimpleNamespace(thumbnails_directory=tmp_path / "thumbnails")
    )
    remote_calls: list[str] = []

    media_module._remote_thumbnail_jobs.pop(cache_key, None)
    media_module._remote_thumbnail_failures.pop(cache_key, None)
    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(fake_media)
    )
    monkeypatch.setattr(
        media_module,
        "_remote_thumbnail_source_is_reachable",
        AsyncMock(return_value=True),
    )

    def generate_remote_thumbnail(url: str, *_args: object, **_kwargs: object) -> Path:
        remote_calls.append(url)
        thumbnail_file.parent.mkdir(parents=True, exist_ok=True)
        thumbnail_file.write_bytes(b"png-bytes")
        return thumbnail_file

    monkeypatch.setattr(
        media_module,
        "get_or_create_remote_thumbnail",
        generate_remote_thumbnail,
    )

    async def run_inline(function: object, *args: object, **kwargs: object) -> object:
        return function(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(media_module.asyncio, "to_thread", run_inline)

    pending_response = await media_module.get_media_thumbnail(
        "OnlyFans",
        131,
        remote_only=True,
        config=config,
        backend_manager=SimpleNamespace(),
    )

    assert pending_response.status_code == 202
    task = media_module._remote_thumbnail_jobs[cache_key]
    await task
    ready_response = await media_module.get_media_thumbnail(
        "OnlyFans",
        131,
        remote_only=True,
        config=config,
        backend_manager=SimpleNamespace(),
    )
    assert isinstance(ready_response, FileResponse)
    assert Path(str(ready_response.path)) == thumbnail_file
    assert remote_calls == ["https://cdn.example.test/remote.mp4"]


@pytest.mark.asyncio
async def test_library_thumbnail_does_not_fall_back_to_remote_media(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_media = SimpleNamespace(
        id=130,
        user_id=463,
        username="performer",
        aliases=[],
        url="https://cdn.example.test/remote.mp4",
        media_urls=[],
        filepaths=[],
        drm_manifest=None,
        category="video",
        created_at=None,
    )
    config = SimpleNamespace(
        settings=SimpleNamespace(thumbnails_directory=tmp_path / "thumbnails")
    )
    proxy_thumbnail = AsyncMock()

    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(fake_media)
    )
    monkeypatch.setattr(
        media_module,
        "_resolve_configured_media_file",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        media_module,
        "_resolve_drm_stream_candidate",
        proxy_thumbnail,
    )

    with pytest.raises(HTTPException) as exc_info:
        await media_module.get_media_thumbnail(
            "OnlyFans",
            130,
            local_only=True,
            config=config,
            backend_manager=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    proxy_thumbnail.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_local_media_uses_valid_media_url_when_direct_url_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy_response = StreamingResponse(iter([b"remote-bytes"]), media_type="video/mp4")
    proxy_mock = AsyncMock(return_value=proxy_response)
    backend_manager = SimpleNamespace()
    fake_media = SimpleNamespace(
        id=125,
        user_id=458,
        url="https://cdn.example.test/expired.mp4",
        media_urls=[
            SimpleNamespace(
                auth_id=901,
                url="https://cdn.example.test/fresh.mp4",
                expires_at=None,
                is_expired=lambda: False,
            )
        ],
        drm_manifest=None,
        filepaths=[],
    )

    def fake_diagnose_url(url: str) -> SimpleNamespace:
        return SimpleNamespace(
            error=None,
            policy=SimpleNamespace(is_expired=url.endswith("expired.mp4")),
        )

    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(fake_media)
    )
    monkeypatch.setattr(
        media_module,
        "_resolve_configured_media_file",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(media_module, "proxy_stream_url", proxy_mock)
    monkeypatch.setattr(media_module, "diagnose_url", fake_diagnose_url)

    response = await media_module.stream_local_media(
        "OnlyFans",
        125,
        config=SimpleNamespace(),
        backend_manager=backend_manager,
    )

    assert response is proxy_response
    proxy_mock.assert_awaited_once_with(
        "https://cdn.example.test/fresh.mp4",
        "onlyfans",
        backend_manager,
        901,
        custom_cookies="",
    )


@pytest.mark.asyncio
async def test_stream_local_media_resolves_drm_stream_when_urls_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy_response = StreamingResponse(iter([b"drm-bytes"]), media_type="video/mp4")
    proxy_mock = AsyncMock(return_value=proxy_response)
    resolve_drm = AsyncMock(
        return_value=("https://cdn.example.test/drm-video.mp4", None, "key-id:key")
    )
    backend_manager = SimpleNamespace(
        get_authed_session=AsyncMock(
            return_value=SimpleNamespace(drm=SimpleNamespace(resolve_drm=resolve_drm))
        )
    )
    fake_media = SimpleNamespace(
        id=126,
        user_id=459,
        url=None,
        media_urls=[],
        category="video",
        filepaths=[],
        drm_manifest=SimpleNamespace(
            dash_manifest="https://cdn.example.test/manifest.mpd",
            dash_key_pair_id="keypair",
            dash_policy="valid-policy",
            dash_signature="signature",
            video_url=None,
            audio_url=None,
            video_size=None,
            audio_size=None,
        ),
    )

    monkeypatch.setattr(
        media_module, "MultiSiteDatabaseManager", lambda: _FakeDBManager(fake_media)
    )
    monkeypatch.setattr(
        media_module,
        "_resolve_configured_media_file",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(media_module, "proxy_stream_url", proxy_mock)
    monkeypatch.setattr(
        media_module,
        "_resolve_all_content_info",
        lambda _session, _media_id: [("posts", 777)],
    )
    monkeypatch.setattr(
        media_module,
        "decode_cloudfront_policy",
        lambda _policy: SimpleNamespace(is_expired=False),
    )
    monkeypatch.setattr(
        media_module,
        "diagnose_url",
        lambda _url: SimpleNamespace(error=None, policy=None),
    )

    response = await media_module.stream_local_media(
        "OnlyFans",
        126,
        config=SimpleNamespace(),
        backend_manager=backend_manager,
    )

    assert response is proxy_response
    backend_manager.get_authed_session.assert_awaited_once_with("onlyfans", None)
    resolve_drm.assert_awaited_once()
    proxy_mock.assert_awaited_once_with(
        "https://cdn.example.test/drm-video.mp4",
        "onlyfans",
        backend_manager,
        None,
        custom_cookies=(
            "CloudFront-Key-Pair-Id=keypair; "
            "CloudFront-Policy=valid-policy; "
            "CloudFront-Signature=signature;"
        ),
    )
