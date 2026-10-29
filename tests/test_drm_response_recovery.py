import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import ClientConnectionError, ClientPayloadError

from ultima_scraper_api.apis.onlyfans.classes import only_drm


def response(body=b"manifest", error=None):
    return SimpleNamespace(
        read=AsyncMock(return_value=body, side_effect=error),
        raise_for_status=Mock(),
        release=Mock(),
    )


def resolver(responses, attempts=3):
    requester = SimpleNamespace(
        request=AsyncMock(side_effect=responses),
        get_session_manager=lambda: SimpleNamespace(max_attempts=attempts),
    )
    drm = object.__new__(only_drm.OnlyDRM)
    drm.authed = SimpleNamespace(get_requester=lambda: requester)
    return drm, requester


@pytest.mark.parametrize("error", [ClientConnectionError("Connection closed"), ClientPayloadError("Incomplete body")])
def test_interrupted_body_reissues_request_and_releases_responses(monkeypatch, error):
    first, second = response(error=error), response()
    drm, requester = resolver([first, second])
    sleep = AsyncMock()
    monkeypatch.setattr(only_drm.asyncio, "sleep", sleep)
    assert asyncio.run(drm._read_drm_response("https://example.test", custom_cookies="cookie")) == b"manifest"
    assert requester.request.await_count == 2
    first.release.assert_called_once()
    second.release.assert_called_once()
    sleep.assert_awaited_once_with(1)


def test_exhausted_reads_keep_original_exception(monkeypatch):
    error = ClientConnectionError("Connection closed")
    responses = [response(error=error) for _ in range(3)]
    drm, requester = resolver(responses)
    monkeypatch.setattr(only_drm.asyncio, "sleep", AsyncMock())
    with pytest.raises(ClientConnectionError, match="Connection closed"):
        asyncio.run(drm._read_drm_response("https://example.test"))
    assert requester.request.await_count == 3
    for item in responses:
        item.release.assert_called_once()


def test_http_rejection_is_not_retried():
    item = response()
    item.raise_for_status.side_effect = ValueError("HTTP rejected")
    drm, requester = resolver([item])
    with pytest.raises(ValueError, match="HTTP rejected"):
        asyncio.run(drm._read_drm_response("https://example.test"))
    assert requester.request.await_count == 1
    item.read.assert_not_awaited()
    item.release.assert_called_once()


def test_cancellation_releases_response_without_retry():
    item = response(error=asyncio.CancelledError())
    drm, requester = resolver([item])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(drm._read_drm_response("https://example.test"))
    assert requester.request.await_count == 1
    item.release.assert_called_once()


def test_download_exception_reaches_evidence_without_signed_url(tmp_path):
    from ultima_scraper_backend.job_system.download_manager import DownloadItem, DownloadManager
    from ultima_scraper_backend.job_system.handlers.download.handler import _process_download_result

    item = DownloadItem(
        url="https://example.test/video.mpd?Signature=secret",
        filename="video.mp4", directory=tmp_path, media_id=1, content_id=2,
        media_metadata=SimpleNamespace(drm=True),
    )
    manager = object.__new__(DownloadManager)
    manager.session = object()
    manager._download_drm = AsyncMock(side_effect=ClientConnectionError(
        "Connection closed https://example.test/video.mpd?Signature=secret"
    ))
    manager._fail_download = AsyncMock(return_value=False)

    async def run():
        assert await manager.download(item) is False
        return await _process_download_result(item, [])

    result = asyncio.run(run())
    assert result.status == "failed"
    assert len(result.errors) == 1
    assert "ClientConnectionError: Connection closed" in result.errors[0].message
    assert "secret" not in result.errors[0].message
    assert "<redacted URL>" in result.errors[0].message
