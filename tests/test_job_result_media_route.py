from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from ultima_scraper_backend.api.routes import jobs as jobs_module


def _config_with_download_root(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        settings=SimpleNamespace(
            download_setup=SimpleNamespace(
                drives=[SimpleNamespace(directories=[root])],
            )
        )
    )


def _download_task(path: Path) -> jobs_module.TaskDetail:
    return jobs_module.TaskDetail(
        task_id="task-profile",
        task_type="download_media",
        status="completed",
        site="onlyfans",
        username="alice",
        content_type="Profile",
        result={
            "output": {
                "download_results": [
                    {
                        "media_id": 11240751,
                        "status": "downloaded",
                        "path": str(path),
                    }
                ]
            }
        },
    )


@pytest.mark.asyncio
async def test_stream_job_task_download_file_serves_retained_profile_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    download_root = tmp_path / "downloads"
    profile_image = download_root / "alice" / "Profile" / "Avatars" / "avatar.jpg"
    profile_image.parent.mkdir(parents=True)
    profile_image.write_bytes(b"profile-image")
    fetch_task = AsyncMock(return_value=_download_task(profile_image))
    monkeypatch.setattr(jobs_module, "_fetch_job_task_detail", fetch_task)

    response = await jobs_module.stream_job_task_download_file(
        "job-profile",
        "task-profile",
        0,
        backend=SimpleNamespace(redis=None),
        config=_config_with_download_root(download_root),
    )

    assert isinstance(response, FileResponse)
    assert Path(str(response.path)) == profile_image
    assert response.media_type == "image/jpeg"
    fetch_task.assert_awaited_once_with(
        "job-profile", "task-profile", SimpleNamespace(redis=None)
    )


@pytest.mark.asyncio
async def test_stream_job_task_download_file_rejects_path_outside_download_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    download_root = tmp_path / "downloads"
    download_root.mkdir()
    outside_file = tmp_path / "private.jpg"
    outside_file.write_bytes(b"not-download-data")
    monkeypatch.setattr(
        jobs_module,
        "_fetch_job_task_detail",
        AsyncMock(return_value=_download_task(outside_file)),
    )

    with pytest.raises(HTTPException) as exc_info:
        await jobs_module.stream_job_task_download_file(
            "job-profile",
            "task-profile",
            0,
            backend=SimpleNamespace(redis=None),
            config=_config_with_download_root(download_root),
        )

    assert exc_info.value.status_code == 404
