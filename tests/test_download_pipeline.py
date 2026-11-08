from __future__ import annotations

import asyncio
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import ultima_scraper_backend.job_system.download_manager as download_manager_module
import ultima_scraper_backend.job_system.handlers.download.handler as download_handler_module
from ultima_scraper_backend.config import (
    DownloadPathSetup,
    DownloadSettings,
    Proxy,
    StagingDirectory,
    StagingPolicy,
    StagingUsage,
    UltimaScraperCollectionConfig,
)
from ultima_scraper_backend.job_system.download_manager import (
    DownloadItem,
    DownloadManager,
    DRMMediaSettings,
    ResourceManager,
)
from ultima_scraper_backend.job_system.handlers.download.handler import (
    _build_download_items,
    _process_download_result,
    _process_drm_items,
)
from ultima_scraper_backend.job_system.metadata_models import (
    ContentMetadata,
    MediaMetadata,
)
from ultima_scraper_backend.job_system.models import (
    Job,
    Task,
    TaskResult,
    TaskRunContext,
    TaskType,
)
from ultima_scraper_backend.job_system.path_formatter import (
    FormatAttributes,
    PathFormatter,
)
from ultima_scraper_backend.job_system.payloads import DownloadTaskPayload


def _build_config() -> UltimaScraperCollectionConfig:
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        filename_format=Path("{content_id}_{media_id}.{ext}"),
        date_format="%Y-%m-%d",
        text_length=255,
    )
    return config


def _build_staging_directory(
    path: Path,
    *,
    usage: list[StagingUsage] | None = None,
    policy: list[StagingPolicy] | None = None,
) -> StagingDirectory:
    return StagingDirectory(
        path=path,
        usage=usage or [StagingUsage.DOWNLOADS],
        policy=policy or [],
    )


def _build_api_user(config: UltimaScraperCollectionConfig, username: str = "creator"):
    api = SimpleNamespace(config=config, site_name="OnlyFans")
    authed = SimpleNamespace(username="buyer", get_api=lambda: api)
    return SimpleNamespace(
        id=2468,
        get_usernames=lambda: [username],
        get_authed=lambda: authed,
    )


def _build_drm_media_metadata(
    *,
    media_id: int,
    content_id: int,
    manifest_url: str,
    created_at: datetime,
    drm_media: object,
    drm_key: str = "",
) -> MediaMetadata:
    return MediaMetadata(
        media_id=media_id,
        media_type="videos",
        urls=[manifest_url],
        content_id=content_id,
        user_id=2468,
        created_at=created_at,
        drm=True,
        drm_key=drm_key,
        drm_media=drm_media,
    )


def test_media_metadata_to_download_item_uses_download_setup_formats(tmp_path) -> None:
    config = _build_config()
    api_user = _build_api_user(config)
    created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    content = ContentMetadata(
        content_id=111,
        api_type="posts",
        user_id=2468,
        created_at=created_at,
        text="paid clip",
        price=10.0,
        paid=True,
    )
    media = MediaMetadata(
        media_id=222,
        media_type="videos",
        urls=["https://cdn3.onlyfans.com/files/example/clip.mp4"],
        content_id=111,
        user_id=2468,
        created_at=created_at,
        content_metadata=content,
    )
    base_directory = tmp_path / "OnlyFans" / "c" / "creator"

    item = media.to_download_item(api_user=api_user, base_directory=base_directory)

    assert item.directory == base_directory / "Posts" / "Paid" / "Videos"
    assert item.filename == "111_222.mp4"


def test_media_metadata_to_download_item_uses_alt_directory_format_override(
    tmp_path,
) -> None:
    config = _build_config()
    api_user = _build_api_user(config)
    created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    content = ContentMetadata(
        content_id=111,
        api_type="posts",
        user_id=2468,
        created_at=created_at,
        text="paid clip",
        price=10.0,
        paid=True,
    )
    media = MediaMetadata(
        media_id=222,
        media_type="videos",
        urls=["https://cdn3.onlyfans.com/files/example/clip.mp4"],
        content_id=111,
        user_id=2468,
        created_at=created_at,
        content_metadata=content,
    )
    base_directory = tmp_path / "OnlyFans Vault" / "C" / "creator"
    alt_directory_format = Path(
        "{site_name} Vault/{first_username_letter}/{user_username}/Library/{media_type}/{content_type}/{value}"
    )

    item = media.to_download_item(
        api_user=api_user,
        base_directory=base_directory,
        directory_format_override=alt_directory_format,
    )

    assert item.directory == base_directory / "Library" / "Videos" / "Posts" / "Paid"
    assert item.filename == "111_222.mp4"


def test_media_metadata_to_download_item_supports_full_alt_directory_render(
    tmp_path,
) -> None:
    config = _build_config()
    api_user = _build_api_user(config)
    created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    content = ContentMetadata(
        content_id=111,
        api_type="posts",
        user_id=2468,
        created_at=created_at,
        text="paid clip",
        price=10.0,
        paid=True,
    )
    media = MediaMetadata(
        media_id=222,
        media_type="videos",
        urls=["https://cdn3.onlyfans.com/files/example/clip.mp4"],
        content_id=111,
        user_id=2468,
        created_at=created_at,
        content_metadata=content,
    )
    alt_directory_format = Path(
        "{site_name} Vault/{content_type}/{user_username}/{value}/{media_type}"
    )

    item = media.to_download_item(
        api_user=api_user,
        base_directory=tmp_path,
        directory_format_override=alt_directory_format,
        render_full_directory_format=True,
    )

    assert (
        item.directory
        == tmp_path / "OnlyFans Vault" / "Posts" / "creator" / "Paid" / "Videos"
    )
    assert item.filename == "111_222.mp4"


def test_media_metadata_to_download_item_preserves_alias_selected_base_directory(
    tmp_path,
) -> None:
    config = _build_config()
    api = SimpleNamespace(config=config, site_name="OnlyFans")
    authed = SimpleNamespace(username="buyer", get_api=lambda: api)
    api_user = SimpleNamespace(
        id=2468,
        username="lunadiaz12",
        get_usernames=lambda: ["lunadiaz12", "mxgroup"],
        get_authed=lambda: authed,
    )
    created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    content = ContentMetadata(
        content_id=111,
        api_type="posts",
        user_id=2468,
        created_at=created_at,
        text="paid clip",
        price=10.0,
        paid=True,
    )
    media = MediaMetadata(
        media_id=222,
        media_type="videos",
        urls=["https://cdn3.onlyfans.com/files/example/clip.mp4"],
        content_id=111,
        user_id=2468,
        created_at=created_at,
        content_metadata=content,
    )
    base_directory = tmp_path / "OnlyFans" / "M" / "mxgroup"

    item = media.to_download_item(api_user=api_user, base_directory=base_directory)

    assert item.directory == base_directory / "Posts" / "Paid" / "Videos"
    assert item.filename == "111_222.mp4"


def test_process_download_result_keeps_existing_mismatched_file_not_rewritten(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filepath = tmp_path / "OnlyFans" / "M" / "mxgroup" / "Stories" / "Free" / "Images"
    filepath.mkdir(parents=True)
    target = filepath / "1080x2001.jpg"
    target.write_bytes(b"x" * 20)

    item = DownloadItem(
        url="https://cdn.onlyfans.test/1080x2001.jpg",
        filename=target.name,
        directory=filepath,
        media_id=2451109556,
        content_id=11574192,
        size=10,
    )

    async def _inline_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        return func(*args, **kwargs)

    monkeypatch.setattr(
        download_handler_module.asyncio,
        "to_thread",
        _inline_to_thread,
    )
    written: list[dict[str, object]] = []
    result = asyncio.run(_process_download_result(item, written))

    assert result.status == "failed"
    assert result.has_error(download_handler_module.DownloadFailureReason.SIZE_MISMATCH)
    assert target.exists()
    assert target.stat().st_size == 20


def test_process_download_result_deletes_mismatched_file_written_this_run(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filepath = tmp_path / "OnlyFans" / "M" / "mxgroup" / "Stories" / "Free" / "Images"
    filepath.mkdir(parents=True)
    target = filepath / "1080x2001.jpg"
    target.write_bytes(b"x" * 20)

    item = DownloadItem(
        url="https://cdn.onlyfans.test/1080x2001.jpg",
        filename=target.name,
        directory=filepath,
        media_id=2451109556,
        content_id=11574192,
        size=10,
        downloaded_this_run=True,
    )

    async def _inline_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        return func(*args, **kwargs)

    monkeypatch.setattr(
        download_handler_module.asyncio,
        "to_thread",
        _inline_to_thread,
    )
    written: list[dict[str, object]] = []
    result = asyncio.run(_process_download_result(item, written))

    assert result.status == "failed"
    assert result.has_error(download_handler_module.DownloadFailureReason.SIZE_MISMATCH)
    assert not target.exists()


def test_media_metadata_render_target_filename_matches_download_item_format(
    tmp_path,
) -> None:
    config = _build_config()
    config.settings.download_setup.filename_format = Path(
        "{content_id}_{filename}.{ext}"
    )
    api_user = _build_api_user(config)
    created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    content = ContentMetadata(
        content_id=111,
        api_type="posts",
        user_id=2468,
        created_at=created_at,
        text="paid clip",
        price=10.0,
        paid=True,
    )
    media = MediaMetadata(
        media_id=222,
        media_type="videos",
        urls=["https://cdn3.onlyfans.com/files/example/clip.mp4"],
        content_id=111,
        user_id=2468,
        created_at=created_at,
        content_metadata=content,
    )
    base_directory = tmp_path / "OnlyFans" / "c" / "creator"

    item = media.to_download_item(
        filename="clip_source.mp4",
        api_user=api_user,
        base_directory=base_directory,
    )
    rendered_filename = media.render_target_filename(
        "clip_source.mp4",
        api_user=api_user,
        directory_hint=base_directory,
    )

    assert rendered_filename == "111_clip_source.mp4"
    assert item.filename == rendered_filename


def test_build_download_items_skips_media_without_urls(tmp_path) -> None:
    config = _build_config()
    api_user = _build_api_user(config)
    created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    content = ContentMetadata(
        content_id=111,
        api_type="messages",
        user_id=2468,
        created_at=created_at,
        text="missing media url",
        price=0.0,
        paid=False,
    )
    media = MediaMetadata(
        media_id=222,
        media_type="images",
        urls=[],
        content_id=111,
        user_id=2468,
        created_at=created_at,
        content_metadata=content,
    )
    content.medias.append(media)

    items = _build_download_items(
        [content],
        api_user,
        tmp_path / "OnlyFans" / "c" / "creator",
        [],
    )

    assert items == []


def test_build_download_items_renders_with_the_backend_download_settings(tmp_path) -> None:
    """A worker's site API carries the slimmer API config, with no download settings."""
    config = _build_config()
    api_user = _build_api_user(config)
    api_user.get_authed().get_api().config = SimpleNamespace(settings=SimpleNamespace())
    created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    content = ContentMetadata(
        content_id=111, api_type="posts", user_id=2468, created_at=created_at, text="hi", price=0.0, paid=False
    )
    media = MediaMetadata(
        media_id=222,
        media_type="images",
        urls=["https://cdn2.onlyfans.com/files/a/b/photo.jpg"],
        content_id=111,
        user_id=2468,
        created_at=created_at,
        content_metadata=content,
    )
    content.medias.append(media)

    items = _build_download_items(
        [content],
        api_user,
        tmp_path / "OnlyFans" / "c" / "creator",
        [],
        download_setup=config.settings.download_setup,
    )

    assert [item.media_id for item in items] == [222]
    assert items[0].get_filepath().is_relative_to(tmp_path)


@pytest.mark.asyncio
async def test_download_handler_falls_back_to_db_user_when_api_user_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _build_config()
    db_user = SimpleNamespace(id=242986290, username="deletedcreator")

    async def fake_get_user(_: str) -> None:
        return None

    authed = SimpleNamespace(id=10001, get_user=fake_get_user)
    site_api = SimpleNamespace(
        find_auth=lambda auth_id: authed, auths={10001: authed}
    )
    db_manager = SimpleNamespace(
        get_user=lambda identifier: (
            db_user if str(identifier) in {"242986290", "deletedcreator"} else None
        ),
        get_user_auth=lambda auth_id: SimpleNamespace(user_id=auth_id),
    )
    captured: dict[str, object] = {}

    async def fake_profile_download(**kwargs) -> TaskResult:
        user = kwargs["user"]
        captured["username"] = user.username
        captured["usernames"] = user.get_usernames()
        captured["authed"] = user.get_authed()
        return TaskResult(success=True, message="ok")

    monkeypatch.setattr(
        download_handler_module,
        "_handle_profile_download",
        fake_profile_download,
    )

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(download_handler_module.asyncio, "to_thread", fake_to_thread)

    task = Task(
        user_id=242986290,
        task_type=TaskType.DOWNLOAD,
        content_type="profile",
        site_name="onlyfans",
        auth_id=10001,
        payload=DownloadTaskPayload(),
    )
    job = Job(name="test download", created_by="pytest", tasks=[task])
    context = TaskRunContext(
        job=job,
        storage=SimpleNamespace(),
        previous_output=None,
        context={
            "site_api": site_api,
            "db_managers": {"onlyfans": db_manager},
            "config": config,
            "database_writes": object(),
        },
    )

    result = await download_handler_module.download_task_handler(task, context)

    assert result.success is True
    assert captured["username"] == "deletedcreator"
    assert captured["authed"] is authed
    assert "deletedcreator" in captured["usernames"]


def test_path_formatter_capitalizes_first_username_letter_token() -> None:
    formatter = PathFormatter(
        directory_format=Path("{site_name}/{first_username_letter}/{user_username}"),
        filename_format=Path("{content_id}.{ext}"),
    )
    attrs = FormatAttributes()
    attrs.site_name = "OnlyFans"
    attrs.user_username = "creator"
    attrs.user_id = "2468"

    formatted = formatter.format_path(attrs, str(formatter.directory_format))

    assert formatted == "OnlyFans/C/creator"


def test_download_manager_uses_configured_resource_limits() -> None:
    config = _build_config()
    config.settings.network.downloads.max_concurrency = 3
    config.settings.network.downloads.per_domain_concurrency = 2
    config.settings.network.downloads.head_concurrency = 4
    config.settings.network.downloads.buffer_size_bytes = 2048

    manager = DownloadManager(config=config)

    assert manager.resource_manager.get_current_concurrency() == 3
    assert manager.resource_manager.get_file_concurrency() == 3
    assert manager.resource_manager.get_per_domain_concurrency() == 2
    assert manager.resource_manager.get_head_concurrency() == 4
    assert manager.resource_manager.get_current_buffer_size() == 2048
    assert manager.semaphore._value == 3
    assert manager.head_semaphore._value == 4


def test_resource_manager_uses_matching_proxy_download_limits() -> None:
    config = _build_config()
    config.settings.network.proxies = [
        Proxy(
            url="socks5://proxy.test:1080",
            username="proxy-user",
            password="proxy-password",
            downloads=DownloadSettings(
                max_concurrency=7,
                max_file_concurrency=11,
                per_domain_concurrency=5,
                head_concurrency=6,
                buffer_size_bytes=4096,
            ),
        )
    ]

    resources = ResourceManager.from_config(
        config,
        "socks5://proxy-user:proxy-password@proxy.test:1080",
    )

    assert resources.get_current_concurrency() == 7
    assert resources.get_file_concurrency() == 11
    assert resources.get_per_domain_concurrency() == 5
    assert resources.get_head_concurrency() == 6
    assert resources.get_current_buffer_size() == 4096



def test_resource_manager_uses_network_download_limits_for_a_proxy_without_its_own() -> None:
    config = _build_config()
    config.settings.network.downloads.per_domain_concurrency = 16
    config.settings.network.proxies = [Proxy(url="http://proxy.test:8022")]

    resources = ResourceManager.from_config(config, "http://proxy.test:8022")

    # The Network page's Download Concurrency is the only place the WebUI edits.
    assert config.settings.network.proxies[0].downloads is None
    assert resources.get_per_domain_concurrency() == 16


def test_a_saved_proxy_keeps_no_download_settings_of_its_own() -> None:
    saved = Proxy(url="http://proxy.test:8022").model_dump(mode="json")

    # Left out rather than null, which backends from before this reject.
    assert "downloads" not in saved
    assert Proxy.model_validate(saved).downloads is None
    assert "downloads" in Proxy(url="http://proxy.test:8022", downloads=DownloadSettings()).model_dump()

@pytest.mark.asyncio
async def test_download_admission_bounds_large_stream_and_cancels_before_close(
    tmp_path, monkeypatch
) -> None:
    saturated = asyncio.Event()
    cancelled: list[str] = []
    admitted: list[str] = []
    source_closed = False

    class Session:
        async def close(self):
            assert len(cancelled) == 2

    monkeypatch.setattr(
        download_manager_module.aiohttp, "ClientSession", lambda **kwargs: Session()
    )
    manager = DownloadManager(
        config=_build_config(),
        resource_manager=ResourceManager(max_concurrency=7, max_file_concurrency=2),
    )

    async def items():
        nonlocal source_closed
        try:
            for index in range(1_000_000):
                yield DownloadItem(
                    url=f"https://example.test/{index}",
                    directory=tmp_path,
                    filename=str(index),
                    size=10,
                )
        finally:
            source_closed = True

    async def download(item):
        admitted.append(item.filename)
        if len(admitted) == 2:
            saturated.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(item.filename)

    monkeypatch.setattr(manager, "download", download)
    run = asyncio.create_task(manager.bulk_download(items()))
    try:
        await asyncio.wait_for(saturated.wait(), timeout=1)
        assert admitted == ["0", "1"]
        assert manager.total == 2
        assert manager._expected_transfer_bytes() == 20
        assert len(manager._expected_bytes_by_item) == 2
    finally:
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
    assert source_closed
    assert manager.session is None
    assert not manager._expected_bytes_by_item
    assert not manager._processed_parts_by_item


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_download_progress_releases_items_and_keeps_exact_totals(
    tmp_path, monkeypatch, streaming
) -> None:
    manager = DownloadManager(
        config=_build_config(),
        resource_manager=ResourceManager(max_concurrency=2, max_file_concurrency=3),
        session=object(),
    )
    items = [
        DownloadItem(
            url=f"https://example.test/{index}",
            directory=tmp_path,
            filename=str(index),
            size=10,
        )
        for index in range(1000)
    ]

    async def download(item):
        assert len(manager._expected_bytes_by_item) <= 3
        assert len(manager._processed_parts_by_item) <= 3
        manager._record_expected_bytes(item, 12)
        manager._record_part_processed(item, 0, 3, 6)
        manager._record_part_processed(item, 0, 6, 6)
        manager._record_part_processed(item, 0, 2, 6)  # Retried/resumed bytes.
        manager._record_part_processed(item, 1, 6, 6)
        return await manager._complete_download(item, 12)

    monkeypatch.setattr(manager, "download", download)
    result = await manager.bulk_download(iter(items) if streaming else items)
    assert result == {
        "total": 1000, "completed": 1000, "failed": 0, "success_rate": 100.0
    }
    assert manager._expected_transfer_bytes() == 12_000
    assert manager._processed_transfer_bytes() == 12_000
    assert not manager._expected_bytes_by_item
    assert not manager._processed_parts_by_item


@pytest.mark.parametrize("value", [0, -1, 1.5, True])
def test_invalid_download_resource_settings_are_rejected(value) -> None:
    with pytest.raises(ValueError):
        DownloadSettings(max_file_concurrency=value)
    with pytest.raises(ValueError):
        ResourceManager(max_file_concurrency=value)


@pytest.mark.asyncio
async def test_bulk_download_emits_in_flight_byte_progress(
    tmp_path,
    monkeypatch,
) -> None:
    class FakeContent:
        async def iter_chunked(self, _: int):
            yield b"abc"
            yield b"def"

    class FakeResponse:
        def __init__(self, *, status: int, content_length: int) -> None:
            self.status = status
            self.content_length = content_length
            self.content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeSession:
        def head(self, *args, **kwargs):
            return FakeResponse(status=200, content_length=6)

        def get(self, *args, **kwargs):
            return FakeResponse(status=206, content_length=6)

    class FakeAsyncFile:
        def __init__(self, path: Path, mode: str) -> None:
            self.path = path
            self.mode = mode
            self.file = None

        async def __aenter__(self):
            self.file = self.path.open(self.mode)
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            assert self.file is not None
            self.file.close()

        async def write(self, data: bytes | bytearray) -> None:
            assert self.file is not None
            self.file.write(data)
            self.file.flush()

    async def inline_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    # Releases that append each part to its own file write through aiofiles.
    if hasattr(download_manager_module, "aiofiles"):
        monkeypatch.setattr(
            download_manager_module.aiofiles,
            "open",
            lambda path, mode: FakeAsyncFile(Path(path), mode),
        )
    monkeypatch.setattr(
        download_manager_module.asyncio,
        "to_thread",
        inline_to_thread,
    )

    manager = DownloadManager(
        config=_build_config(),
        resource_manager=ResourceManager(
            max_concurrency=1,
            buffer_size=1024,
            per_domain_concurrency=1,
            head_concurrency=1,
        ),
        session=FakeSession(),
    )
    manager.progress_update_interval = 0.0
    progress_events: list[dict[str, object]] = []
    manager.on_progress.append(progress_events.append)
    item = DownloadItem(
        url="https://cdn.onlyfans.test/example.jpg",
        filename="example.jpg",
        directory=tmp_path,
    )

    result = await asyncio.wait_for(
        manager.bulk_download([item], create_session=False),
        timeout=2.0,
    )

    assert result == {"total": 1, "completed": 1, "failed": 0, "success_rate": 100.0}
    assert (tmp_path / "example.jpg").read_bytes() == b"abcdef"
    assert any(
        event["status"] == "progress" and int(event["bytes"]) > 0
        for event in progress_events
    )
    assert sum(int(event["bytes"]) for event in progress_events) == 6
    assert progress_events[-1]["status"] == "completed"
    assert progress_events[-1]["processed_bytes"] == 6
    assert progress_events[-1]["expected_bytes"] == 6
    assert progress_events[-1]["completed"] == 1
    # The file's own bytes travel beside the batch's.
    assert progress_events[-1]["item_processed_bytes"] == 6
    assert progress_events[-1]["item_expected_bytes"] == 6


@pytest.mark.asyncio
async def test_bulk_download_session_uses_post_handshake_auth_ssl_context(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeSession:
        def __init__(self, *, timeout, connector) -> None:
            captured["timeout"] = timeout
            captured["connector"] = connector

        async def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(download_manager_module.aiohttp, "ClientSession", FakeSession)

    manager = DownloadManager(config=_build_config())
    result = await manager.bulk_download([], create_session=True)

    assert result["total"] == 0
    assert captured["closed"] is True
    connector = captured["connector"]
    assert isinstance(connector, download_manager_module.aiohttp.TCPConnector)
    assert connector._ssl is not None
    assert connector._ssl.post_handshake_auth is True


def test_content_metadata_from_db_record_reconstructs_drm_download_item(
    tmp_path,
) -> None:
    config = _build_config()
    api_user = _build_api_user(config)
    created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    drm_manifest = SimpleNamespace(
        dash_manifest="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
        dash_key_pair_id="key-pair",
        dash_policy="policy",
        dash_signature="signature",
        video_url=None,
        audio_url=None,
        video_size=456,
        audio_size=123,
    )
    db_media = SimpleNamespace(
        id=4280309597,
        category="video",
        url="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
        size=123,
        drm=True,
        preview=False,
        created_at=created_at,
        drm_manifest=drm_manifest,
        media_urls=[],
    )
    db_content = SimpleNamespace(
        id=2253445423,
        user_id=2468,
        created_at=created_at,
        text="paid clip",
        price=10.0,
        paid=True,
        archived=False,
        expires_at=None,
        receiver_id=None,
        queue_id=None,
        media=[db_media],
    )

    content = ContentMetadata.from_db_record(db_content, content_type="posts")
    media = content.medias[0]
    item = media.to_download_item(
        api_user=api_user,
        base_directory=tmp_path / "OnlyFans" / "c" / "creator",
    )

    assert media.drm is True
    assert media.drm_media is not None
    assert media.drm_media.manifest_url == drm_manifest.dash_manifest
    assert media.drm_media.key_pair_id == drm_manifest.dash_key_pair_id
    assert media.drm_media.policy == drm_manifest.dash_policy
    assert media.drm_media.signature == drm_manifest.dash_signature
    assert media.drm_media.video_size == drm_manifest.video_size
    assert media.drm_media.audio_size == drm_manifest.audio_size
    assert item.media_metadata is media
    assert item.media_metadata.drm_media is not None
    assert not isinstance(item.media_metadata.drm_media, bool)
    assert item.filename == "2253445423_4280309597.mp4"
    assert (
        item.directory
        == tmp_path / "OnlyFans" / "c" / "creator" / "Posts" / "Paid" / "Videos"
    )


def test_content_metadata_from_db_record_uses_drm_stream_filename_template(
    tmp_path,
) -> None:
    config = _build_config()
    config.settings.download_setup.filename_format = Path("{filename}.{ext}")
    api_user = _build_api_user(config)
    created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    drm_manifest = SimpleNamespace(
        dash_manifest="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
        dash_key_pair_id="key-pair",
        dash_policy="policy",
        dash_signature="signature",
        video_url="https://cdn3.onlyfans.com/dash/files/a/b/clip_source.mp4",
        audio_url="https://cdn3.onlyfans.com/dash/files/a/b/clip_audio.m4a",
        video_size=456,
        audio_size=123,
    )
    db_media = SimpleNamespace(
        id=4280309597,
        category="video",
        url="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
        size=123,
        drm=True,
        preview=False,
        created_at=created_at,
        drm_manifest=drm_manifest,
        media_urls=[],
    )
    db_content = SimpleNamespace(
        id=2253445423,
        user_id=2468,
        created_at=created_at,
        text="paid clip",
        price=10.0,
        paid=True,
        archived=False,
        expires_at=None,
        receiver_id=None,
        queue_id=None,
        media=[db_media],
    )

    content = ContentMetadata.from_db_record(db_content, content_type="posts")
    item = content.medias[0].to_download_item(
        api_user=api_user,
        base_directory=tmp_path / "OnlyFans" / "c" / "creator",
    )

    assert item.filename == "clip_source.mp4"


@pytest.mark.parametrize(
    ("raw_media_type", "expected_media_type"),
    [
        ("photo", "images"),
        ("gif", "gifs"),
        ("stream", "videos"),
        ("application", "videos"),
        ("audio", "audio"),
    ],
)
def test_media_metadata_from_api_media_uses_usapi_media_type_mapping(
    raw_media_type: str,
    expected_media_type: str,
) -> None:
    media = MediaMetadata.from_api_media(
        media_item={
            "id": 123,
            "type": raw_media_type,
            "url": "https://cdn3.onlyfans.com/files/example/media.bin",
            "createdAt": "2026-03-12T18:00:00+00:00",
        },
        content_id=456,
        user_id=789,
        api_type="posts",
    )

    assert media.media_type == expected_media_type


def test_media_metadata_to_download_item_places_gifs_in_gifs_folder(tmp_path) -> None:
    config = _build_config()
    api_user = _build_api_user(config)
    created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    content = ContentMetadata(
        content_id=333,
        api_type="posts",
        user_id=2468,
        created_at=created_at,
        text="gif post",
        price=0.0,
        paid=False,
    )
    media = MediaMetadata(
        media_id=444,
        media_type="gifs",
        urls=["https://cdn3.onlyfans.com/files/example/clip.gif"],
        content_id=333,
        user_id=2468,
        created_at=created_at,
        content_metadata=content,
    )
    base_directory = tmp_path / "OnlyFans" / "c" / "creator"

    item = media.to_download_item(api_user=api_user, base_directory=base_directory)

    assert item.directory == base_directory / "Posts" / "Free" / "Gifs"
    assert item.filename == "333_444.gif"


@pytest.mark.asyncio
async def test_download_manager_uses_drm_stream_download_flow(
    tmp_path, monkeypatch
) -> None:
    class FakeDrmMedia:
        manifest_url = "https://cdn3.onlyfans.com/dash/files/a/b/example.mpd"

        def get_cookies(self) -> str:
            return "cookie=1"

    class FakeOnlyDrm:
        async def resolve_drm(self, drm_media: object) -> tuple[str, str, str]:
            assert isinstance(drm_media, FakeDrmMedia)
            return (
                "https://video.example/stream.mp4",
                "https://audio.example/stream.mp4",
                "secret-key",
            )

    database_writes = SimpleNamespace(submit=AsyncMock(return_value={"updated": True}))
    fake_user = SimpleNamespace(
        get_authed=lambda: SimpleNamespace(drm=FakeOnlyDrm()),
    )
    config = _build_config()
    config.settings.download_setup.staging_directories = [
        _build_staging_directory(
            tmp_path / "__drm__",
            usage=[
                StagingUsage.DOWNLOADS,
                StagingUsage.DRM,
                StagingUsage.MERGE,
            ],
        )
    ]
    manager = DownloadManager(
        config=config,
        database_writes=database_writes,
        database_write_site="onlyfans",
        database_write_scope="task-drm",
    )
    manager.session = object()
    media_metadata = _build_drm_media_metadata(
        media_id=99,
        content_id=1,
        manifest_url="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
        created_at=datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc),
        drm_media=FakeDrmMedia(),
    )

    async def fake_head_request(item: DownloadItem):
        return SimpleNamespace(content_length=3)

    async def fake_download_part(
        item: DownloadItem,
        start_byte: int,
        end_byte: int,
        part_num: int,
    ):
        path = tmp_path / f"{item.filename}.part"
        path.write_bytes(b"abc")
        return path

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(manager, "head_request", fake_head_request)
    monkeypatch.setattr(manager, "download_part", fake_download_part)
    monkeypatch.setattr(download_manager_module.asyncio, "to_thread", fake_to_thread)

    item = DownloadItem(
        url="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
        filename="example.mp4",
        directory=tmp_path,
        media_id=99,
        user=fake_user,
        media_metadata=media_metadata,
    )

    success = await manager.download(item)

    assert success is True
    assert item.media_metadata is not None
    assert item.media_metadata.drm_key == "secret-key"
    assert item.drm_media_settings.drm_temp_directory == tmp_path / "__drm__"
    assert (
        item.drm_media_settings.drm_video_path
        == tmp_path / "__drm__" / "example_video.enc.mp4"
    )
    assert (
        item.drm_media_settings.drm_audio_path
        == tmp_path / "__drm__" / "example_audio.enc.mp4"
    )
    assert item.drm_media_settings.drm_video_path.exists()
    assert item.drm_media_settings.drm_audio_path.exists()
    database_writes.submit.assert_awaited_once()
    assert database_writes.submit.await_args.args[1] == {
        "media_id": 99,
        "video_url": "https://video.example/stream.mp4",
        "audio_url": "https://audio.example/stream.mp4",
        "video_size": 3,
        "audio_size": 3,
    }
    assert database_writes.submit.await_args.kwargs["site"] == "onlyfans"


@pytest.mark.asyncio
async def test_download_manager_updates_drm_filename_from_resolved_stream(
    tmp_path, monkeypatch
) -> None:
    class FakeDrmMedia:
        manifest_url = "https://cdn3.onlyfans.com/dash/files/a/b/example.mpd"

        def get_cookies(self) -> str:
            return "cookie=1"

        def resolve_filename(self) -> str:
            return "clip_source.mp4"

    class FakeOnlyDrm:
        async def resolve_drm(self, drm_media: object) -> tuple[str, str, str]:
            assert isinstance(drm_media, FakeDrmMedia)
            return (
                "https://video.example/clip_source.mp4",
                "https://audio.example/clip_audio.m4a",
                "secret-key",
            )

    config = _build_config()
    config.settings.download_setup.filename_format = Path("{filename}.{ext}")
    config.settings.download_setup.staging_directories = [
        _build_staging_directory(
            tmp_path / "__drm__",
            usage=[
                StagingUsage.DOWNLOADS,
                StagingUsage.DRM,
                StagingUsage.MERGE,
            ],
        )
    ]
    api = SimpleNamespace(config=config, site_name="OnlyFans")
    authed = SimpleNamespace(
        username="buyer",
        drm=FakeOnlyDrm(),
        get_api=lambda: api,
    )
    fake_user = SimpleNamespace(
        id=2468,
        get_usernames=lambda: ["creator"],
        get_authed=lambda: authed,
    )
    manager = DownloadManager(
        config=config,
        database_writes=SimpleNamespace(
            submit=AsyncMock(return_value={"updated": True})
        ),
        database_write_site="onlyfans",
        database_write_scope="task-filename-drm",
    )
    manager.session = object()
    created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    content = ContentMetadata(
        content_id=1,
        api_type="posts",
        user_id=2468,
        created_at=created_at,
        text="paid clip",
        price=10.0,
        paid=True,
    )
    media_metadata = MediaMetadata(
        media_id=99,
        media_type="videos",
        urls=["https://cdn3.onlyfans.com/dash/files/a/b/example.mpd"],
        content_id=1,
        user_id=2468,
        created_at=created_at,
        drm=True,
        drm_media=FakeDrmMedia(),
        content_metadata=content,
    )

    async def fake_head_request(item: DownloadItem):
        return SimpleNamespace(content_length=3)

    async def fake_download_part(
        item: DownloadItem,
        start_byte: int,
        end_byte: int,
        part_num: int,
    ):
        path = tmp_path / f"{item.filename}.part"
        path.write_bytes(b"abc")
        return path

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(manager, "head_request", fake_head_request)
    monkeypatch.setattr(manager, "download_part", fake_download_part)
    monkeypatch.setattr(download_manager_module.asyncio, "to_thread", fake_to_thread)

    item = DownloadItem(
        url="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
        filename="example.mp4",
        directory=tmp_path,
        media_id=99,
        user=fake_user,
        media_metadata=media_metadata,
    )

    success = await manager.download(item)

    assert success is True
    assert item.filename == "clip_source.mp4"
    assert (
        item.drm_media_settings.drm_video_path
        == tmp_path / "__drm__" / "clip_source_video.enc.mp4"
    )
    assert (
        item.drm_media_settings.drm_audio_path
        == tmp_path / "__drm__" / "clip_source_audio.enc.mp4"
    )


@pytest.mark.asyncio
async def test_download_manager_covers_full_file_when_part_count_hits_cap(
    tmp_path, monkeypatch
) -> None:
    manager = DownloadManager(config=_build_config())
    manager.session = object()
    recorded_ranges: list[tuple[int, int, int]] = []
    file_size = 700 * 1024 * 1024

    async def fake_head_request(item: DownloadItem):
        return SimpleNamespace(content_length=file_size)

    async def fake_download_part(
        item: DownloadItem,
        start_byte: int,
        end_byte: int,
        part_num: int,
    ):
        recorded_ranges.append((start_byte, end_byte, part_num))
        path = tmp_path / f"part_{part_num}.bin"
        path.write_bytes(b"x")
        return path

    async def fake_merge_parts(dest_path: Path, part_paths: list[Path]) -> bool:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"merged")
        return True

    monkeypatch.setattr(manager, "head_request", fake_head_request)
    monkeypatch.setattr(manager, "download_part", fake_download_part)
    monkeypatch.setattr(manager, "merge_parts", fake_merge_parts)

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(download_manager_module.asyncio, "to_thread", fake_to_thread)

    item = DownloadItem(
        url="https://cdn3.onlyfans.com/files/example/large.mp4",
        filename="large.mp4",
        directory=tmp_path,
    )

    success = await manager.download(item)

    assert success is True
    assert len(recorded_ranges) == 64
    assert recorded_ranges[0][0] == 0
    assert recorded_ranges[-1][1] == file_size - 1
    assert all(
        next_start == current_end + 1
        for (_, current_end, _), (next_start, _, _) in zip(
            recorded_ranges, recorded_ranges[1:], strict=False
        )
    )


@pytest.mark.asyncio
async def test_download_manager_supports_audio_only_drm(tmp_path, monkeypatch) -> None:
    class FakeDrmMedia:
        manifest_url = "https://cdn3.onlyfans.com/dash/files/a/b/audio-only.mpd"

        def get_cookies(self) -> str:
            return "cookie=1"

    class FakeOnlyDrm:
        async def resolve_drm(
            self, drm_media: object
        ) -> tuple[str | None, str | None, str]:
            assert isinstance(drm_media, FakeDrmMedia)
            return (None, "https://audio.example/stream.m4a", "secret-key")

    database_writes = SimpleNamespace(submit=AsyncMock(return_value={"updated": True}))
    fake_user = SimpleNamespace(
        get_authed=lambda: SimpleNamespace(drm=FakeOnlyDrm()),
    )
    config = _build_config()
    config.settings.download_setup.staging_directories = [
        _build_staging_directory(
            tmp_path / "__drm__",
            usage=[
                StagingUsage.DOWNLOADS,
                StagingUsage.DRM,
                StagingUsage.MERGE,
            ],
        )
    ]
    manager = DownloadManager(
        config=config,
        database_writes=database_writes,
        database_write_site="onlyfans",
        database_write_scope="task-audio-drm",
    )
    manager.session = object()
    media_metadata = _build_drm_media_metadata(
        media_id=100,
        content_id=1,
        manifest_url="https://cdn3.onlyfans.com/dash/files/a/b/audio-only.mpd",
        created_at=datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc),
        drm_media=FakeDrmMedia(),
    )

    async def fake_head_request(item: DownloadItem):
        return SimpleNamespace(content_length=3)

    async def fake_download_part(
        item: DownloadItem,
        start_byte: int,
        end_byte: int,
        part_num: int,
    ):
        path = tmp_path / f"{item.filename}.part"
        path.write_bytes(b"abc")
        return path

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(manager, "head_request", fake_head_request)
    monkeypatch.setattr(manager, "download_part", fake_download_part)
    monkeypatch.setattr(download_manager_module.asyncio, "to_thread", fake_to_thread)

    item = DownloadItem(
        url="https://cdn3.onlyfans.com/dash/files/a/b/audio-only.mpd",
        filename="audio-only.mp4",
        directory=tmp_path,
        media_id=100,
        user=fake_user,
        media_metadata=media_metadata,
    )

    success = await manager.download(item)

    assert success is True
    assert item.media_metadata is not None
    assert item.media_metadata.drm_key == "secret-key"
    assert item.drm_media_settings.drm_temp_directory == tmp_path / "__drm__"
    assert item.drm_media_settings.drm_video_path is None
    assert (
        item.drm_media_settings.drm_audio_path
        == tmp_path / "__drm__" / "audio-only_audio.enc.m4a"
    )
    assert item.drm_media_settings.drm_audio_path.exists()
    database_writes.submit.assert_awaited_once()
    assert database_writes.submit.await_args.args[1] == {
        "media_id": 100,
        "video_url": None,
        "audio_url": "https://audio.example/stream.m4a",
        "video_size": None,
        "audio_size": 3,
    }


@pytest.mark.asyncio
async def test_process_drm_items_merges_then_publishes_the_final_file(
    tmp_path, monkeypatch
) -> None:
    class FakeOnlyDrm:
        def __init__(self) -> None:
            self.decrypt_calls: list[Path | None] = []
            self.merge_targets: list[Path] = []

        async def decrypt_file_async(
            self,
            filepath: Path,
            key: str,
            temp_output_path: Path | None = None,
        ) -> Path:
            assert key == "secret-key"
            self.decrypt_calls.append(temp_output_path)
            output_path = (temp_output_path or filepath.parent) / filepath.name.replace(
                ".enc", ".dec"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"dec")
            return output_path

        async def merge_media(
            self, output_filepath: Path, media_paths: list[Path]
        ) -> bool:
            self.merge_targets.append(output_filepath)
            output_filepath.parent.mkdir(parents=True, exist_ok=True)
            output_filepath.write_bytes(b"merged")
            return True

    drm_temp_directory = tmp_path / "__drm__"
    only_drm = FakeOnlyDrm()
    authed = SimpleNamespace(drm=only_drm)
    media_metadata = _build_drm_media_metadata(
        media_id=101,
        content_id=1,
        manifest_url="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
        created_at=datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc),
        drm_media=object(),
        drm_key="secret-key",
    )
    item = DownloadItem(
        url="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
        filename="final.mp4",
        directory=tmp_path / "library",
        media_id=101,
        user=SimpleNamespace(get_authed=lambda: authed),
        media_metadata=media_metadata,
        drm_media_settings=DRMMediaSettings(
            drm_video_path=drm_temp_directory / "final_video.enc.mp4",
            drm_audio_path=drm_temp_directory / "final_audio.enc.mp4",
            drm_temp_directory=drm_temp_directory,
        ),
    )
    assert item.drm_media_settings.drm_video_path is not None
    assert item.drm_media_settings.drm_audio_path is not None
    item.drm_media_settings.drm_video_path.parent.mkdir(parents=True, exist_ok=True)
    item.drm_media_settings.drm_video_path.write_bytes(b"enc-video")
    item.drm_media_settings.drm_audio_path.write_bytes(b"enc-audio")

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.download.handler.asyncio.to_thread",
        fake_to_thread,
    )

    await _process_drm_items([item])

    assert only_drm.decrypt_calls == [drm_temp_directory, drm_temp_directory]
    if hasattr(download_handler_module, "_merge_target"):
        # Merged beside the final file, then renamed: no copy out of staging.
        assert only_drm.merge_targets == [tmp_path / "library" / "final.mp4.tmp"]
    else:
        assert only_drm.merge_targets == [drm_temp_directory / "final.mp4.tmp"]
    assert (tmp_path / "library" / "final.mp4").exists()
    assert not (tmp_path / "library" / "final.mp4.tmp").exists()
    assert not (drm_temp_directory / "final.mp4").exists()
    assert not (drm_temp_directory / "final.mp4.tmp").exists()


@pytest.mark.asyncio
async def test_process_drm_items_emits_progress_updates(tmp_path, monkeypatch) -> None:
    class FakeOnlyDrm:
        async def decrypt_file_async(
            self,
            filepath: Path,
            key: str,
            temp_output_path: Path | None = None,
        ) -> Path:
            assert key == "secret-key"
            output_path = (temp_output_path or filepath.parent) / filepath.name.replace(
                ".enc", ".dec"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"dec")
            return output_path

        async def merge_media(
            self, output_filepath: Path, media_paths: list[Path]
        ) -> bool:
            output_filepath.parent.mkdir(parents=True, exist_ok=True)
            output_filepath.write_bytes(b"merged")
            return True

    drm_temp_directory = tmp_path / "__drm__"
    authed = SimpleNamespace(drm=FakeOnlyDrm())
    media_metadata = _build_drm_media_metadata(
        media_id=202,
        content_id=2,
        manifest_url="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
        created_at=datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc),
        drm_media=object(),
        drm_key="secret-key",
    )
    item = DownloadItem(
        url="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
        filename="final.mp4",
        directory=tmp_path / "library",
        media_id=202,
        user=SimpleNamespace(get_authed=lambda: authed),
        media_metadata=media_metadata,
        drm_media_settings=DRMMediaSettings(
            drm_video_path=drm_temp_directory / "final_video.enc.mp4",
            drm_audio_path=drm_temp_directory / "final_audio.enc.mp4",
            drm_temp_directory=drm_temp_directory,
        ),
    )
    assert item.drm_media_settings.drm_video_path is not None
    assert item.drm_media_settings.drm_audio_path is not None
    item.drm_media_settings.drm_video_path.parent.mkdir(parents=True, exist_ok=True)
    item.drm_media_settings.drm_video_path.write_bytes(b"enc-video")
    item.drm_media_settings.drm_audio_path.write_bytes(b"enc-audio")

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.handlers.download.handler.asyncio.to_thread",
        fake_to_thread,
    )

    progress_events: list[dict[str, object]] = []

    async def capture_progress(event: dict[str, object]) -> None:
        progress_events.append(event)

    await _process_drm_items([item], on_progress=capture_progress)

    assert [event["stage"] for event in progress_events] == [
        "started",
        "decrypting",
        "merging",
        "completed",
        "finished",
    ]
    assert progress_events[1]["media_id"] == 202
    assert progress_events[2]["current"] == 0
    assert progress_events[3]["current"] == 1
    assert progress_events[4]["total"] == 1


def test_select_staging_directory_allows_drm_only_for_drm_items_and_uses_free_space(
    tmp_path, monkeypatch
) -> None:
    regular_path = tmp_path / "regular"
    drm_only_path = tmp_path / "drm-only"
    config = _build_config()
    config.settings.download_setup.staging_directories = [
        _build_staging_directory(
            regular_path,
            usage=[
                StagingUsage.DOWNLOADS,
                StagingUsage.DRM,
                StagingUsage.MERGE,
            ],
        ),
        _build_staging_directory(
            drm_only_path,
            usage=[
                StagingUsage.DOWNLOADS,
                StagingUsage.DRM,
                StagingUsage.MERGE,
            ],
            policy=[StagingPolicy.DRM_ONLY],
        ),
    ]
    manager = DownloadManager(config=config)

    monkeypatch.setattr(
        download_manager_module,
        "_free_space_bytes",
        lambda path: 100 if path == regular_path else 500,
    )

    selected_directory, warning = manager._select_staging_directory(
        [
            StagingUsage.DOWNLOADS,
            StagingUsage.DRM,
            StagingUsage.MERGE,
        ]
    )

    assert warning is None
    assert selected_directory == drm_only_path


def test_select_staging_directory_skips_drm_only_for_non_drm_items(
    tmp_path, monkeypatch
) -> None:
    regular_path = tmp_path / "regular"
    drm_only_path = tmp_path / "drm-only"
    config = _build_config()
    config.settings.download_setup.staging_directories = [
        _build_staging_directory(
            regular_path,
            usage=[StagingUsage.DOWNLOADS],
        ),
        _build_staging_directory(
            drm_only_path,
            usage=[StagingUsage.DOWNLOADS, StagingUsage.MERGE, StagingUsage.DRM],
            policy=[StagingPolicy.DRM_ONLY],
        ),
    ]
    manager = DownloadManager(config=config)

    monkeypatch.setattr(
        download_manager_module,
        "_free_space_bytes",
        lambda path: 100 if path == regular_path else 500,
    )

    selected_directory, warning = manager._select_staging_directory(
        [StagingUsage.DOWNLOADS]
    )

    assert warning is None
    assert selected_directory == regular_path


def test_select_staging_directory_requires_single_directory_covering_all_operations(
    tmp_path,
) -> None:
    config = _build_config()
    config.settings.download_setup.staging_directories = [
        _build_staging_directory(
            tmp_path / "downloads-only",
            usage=[StagingUsage.DOWNLOADS],
        ),
        _build_staging_directory(
            tmp_path / "drm-only",
            usage=[StagingUsage.DRM, StagingUsage.MERGE],
        ),
    ]
    manager = DownloadManager(config=config)

    selected_directory, warning = manager._select_staging_directory(
        [
            StagingUsage.DOWNLOADS,
            StagingUsage.DRM,
            StagingUsage.MERGE,
        ]
    )

    assert selected_directory is None
    assert warning is not None


def test_preferred_staging_tier_overflows_by_reservation_and_refills_on_release(
    tmp_path, monkeypatch
) -> None:
    ram_path = tmp_path / "ram"
    nvme_path = tmp_path / "nvme"
    config = _build_config()
    config.settings.download_setup.staging_directories = [
        StagingDirectory(
            path=ram_path,
            usage=[StagingUsage.DOWNLOADS],
            policy=[StagingPolicy.PREFER],
            min_free_bytes=100,
        ),
        _build_staging_directory(nvme_path, usage=[StagingUsage.DOWNLOADS]),
    ]
    manager = DownloadManager(config=config)
    monkeypatch.setattr(
        download_manager_module,
        "_staging_free_bytes",
        lambda path: 1000 if path == ram_path else 5000,
    )

    def item(name: str) -> DownloadItem:
        return DownloadItem(url="https://cdn.test/f", filename=name, directory=tmp_path)

    first, second, third = item("a"), item("b"), item("c")
    operations = [StagingUsage.DOWNLOADS]

    assert manager._prepare_item_workspace(first, operations, 600) == ram_path
    # 1000 free - 100 headroom - 600 promised leaves too little for another.
    assert manager._prepare_item_workspace(second, operations, 600) == nvme_path
    manager.release_workspace(first)
    manager.release_workspace(first)
    assert manager._prepare_item_workspace(third, operations, 600) == ram_path
    assert manager._staging_reserved == {ram_path: 600, nvme_path: 600}


def test_tmpfs_staging_space_is_capped_by_available_memory(monkeypatch) -> None:
    monkeypatch.setattr(download_manager_module, "_free_space_bytes", lambda path: 10**12)
    monkeypatch.setattr(download_manager_module, "_memory_available_bytes", lambda: 5000)

    monkeypatch.setattr(download_manager_module, "_is_tmpfs", lambda path: True)
    assert download_manager_module._staging_free_bytes(Path("/dev/shm")) == 5000
    monkeypatch.setattr(download_manager_module, "_is_tmpfs", lambda path: False)
    assert download_manager_module._staging_free_bytes(Path("/mnt/nvme")) == 10**12


def _build_staged_drm_item(tmp_path: Path, media_id: int, only_drm: object) -> DownloadItem:
    work = tmp_path / f"__drm{media_id}__"
    work.mkdir()
    (work / "v.enc.mp4").write_bytes(b"enc-video")
    (work / "a.enc.mp4").write_bytes(b"enc-audio")
    authed = SimpleNamespace(drm=only_drm)
    return DownloadItem(
        url=f"https://cdn3.onlyfans.com/dash/files/{media_id}.mpd",
        filename=f"{media_id}.mp4",
        directory=tmp_path / "library",
        media_id=media_id,
        user=SimpleNamespace(get_authed=lambda: authed),
        media_metadata=_build_drm_media_metadata(
            media_id=media_id,
            content_id=media_id,
            manifest_url=f"https://cdn3.onlyfans.com/dash/files/{media_id}.mpd",
            created_at=datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc),
            drm_media=object(),
            drm_key="secret-key",
        ),
        drm_media_settings=DRMMediaSettings(
            drm_video_path=work / "v.enc.mp4",
            drm_audio_path=work / "a.enc.mp4",
            drm_temp_directory=work,
        ),
    )


class _BarrierOnlyDrm:
    """Decrypt blocks until `parties` decrypts are in flight at once."""

    def __init__(self, parties: int) -> None:
        self.parties = parties
        self.in_flight = 0
        self.ready = asyncio.Event()
        self.merged: list[Path] = []

    async def decrypt_file_async(self, filepath, key, temp_output_path=None):
        self.in_flight += 1
        if self.in_flight >= self.parties:
            self.ready.set()
        await self.ready.wait()
        output = temp_output_path / filepath.name.replace(".enc", ".dec")
        output.write_bytes(b"dec")
        return output

    async def merge_media(self, output_filepath, media_paths):
        output_filepath.write_bytes(b"merged")
        self.merged.append(output_filepath)
        return True


async def test_process_drm_items_decrypts_items_and_streams_concurrently(
    tmp_path,
) -> None:
    # Two items x (video + audio): a serial loop would never reach 4 in flight.
    only_drm = _BarrierOnlyDrm(parties=4)
    items = [_build_staged_drm_item(tmp_path, media_id, only_drm) for media_id in (1, 2)]

    await asyncio.wait_for(_process_drm_items(items), timeout=5)

    assert all(item.get_filepath().read_bytes() == b"merged" for item in items)
    assert all(item.downloaded_this_run for item in items)


async def test_download_pipeline_decrypts_before_bulk_download_finishes(
    tmp_path,
) -> None:
    only_drm = _BarrierOnlyDrm(parties=1)
    item = _build_staged_drm_item(tmp_path, 7, only_drm)
    released: list[DownloadItem] = []

    class Manager:
        on_downloaded: list = []

        def release_workspace(self, released_item):
            released.append(released_item)

        async def bulk_download(self, items, create_session=True):
            for downloaded in items:
                for callback in self.on_downloaded:
                    callback(downloaded)
            # Later downloads keep running while the first item is processed.
            async with asyncio.timeout(5):
                while not item.get_filepath().exists():
                    await asyncio.sleep(0.01)
            return {"total": 1, "completed": 1, "failed": 0, "success_rate": 100}

    manager = Manager()
    stats = await download_handler_module._run_download_pipeline(manager, [item])

    assert stats["completed"] == 1
    assert released == [item]
    assert manager.on_downloaded == []


@pytest.mark.asyncio
async def test_regular_download_uses_staging_directory_then_moves_to_final(
    tmp_path, monkeypatch
) -> None:
    staging_directory = tmp_path / "__staging__"
    config = _build_config()
    config.settings.download_setup.staging_directories = [
        _build_staging_directory(
            staging_directory,
            usage=[StagingUsage.DOWNLOADS],
        )
    ]
    manager = DownloadManager(config=config)
    manager.session = object()

    async def fake_head_request(item: DownloadItem):
        return SimpleNamespace(content_length=3)

    async def fake_download_part(
        item: DownloadItem,
        start_byte: int,
        end_byte: int,
        part_num: int,
    ):
        part_dir = item.get_workspace_directory() / "__parts__"
        part_dir.mkdir(parents=True, exist_ok=True)
        part_path = part_dir / f"{item.filename}.part"
        part_path.write_bytes(b"abc")
        return part_path

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(manager, "head_request", fake_head_request)
    monkeypatch.setattr(manager, "download_part", fake_download_part)
    monkeypatch.setattr(download_manager_module.asyncio, "to_thread", fake_to_thread)

    final_directory = tmp_path / "library"
    item = DownloadItem(
        url="https://cdn3.onlyfans.com/files/example/final.mp4",
        filename="final.mp4",
        directory=final_directory,
    )

    success = await manager.download(item)

    assert success is True
    assert item.drm_media_settings.selected_staging_directory == staging_directory
    assert (final_directory / "final.mp4").read_bytes() == b"abc"
    assert not (staging_directory / "final.mp4").exists()


@pytest.mark.asyncio
async def test_regular_download_warns_and_falls_back_when_no_staging_directory_matches(
    tmp_path, caplog, monkeypatch
) -> None:
    config = _build_config()
    config.settings.download_setup.staging_directories = [
        _build_staging_directory(
            tmp_path / "__drm__",
            usage=[StagingUsage.DRM, StagingUsage.MERGE],
        )
    ]
    manager = DownloadManager(config=config)
    manager.session = object()

    async def fake_head_request(item: DownloadItem):
        return SimpleNamespace(content_length=3)

    async def fake_download_part(
        item: DownloadItem,
        start_byte: int,
        end_byte: int,
        part_num: int,
    ):
        part_dir = item.get_workspace_directory() / "__parts__"
        part_dir.mkdir(parents=True, exist_ok=True)
        part_path = part_dir / f"{item.filename}.part"
        part_path.write_bytes(b"abc")
        return part_path

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(manager, "head_request", fake_head_request)
    monkeypatch.setattr(manager, "download_part", fake_download_part)
    monkeypatch.setattr(download_manager_module.asyncio, "to_thread", fake_to_thread)

    item = DownloadItem(
        url="https://cdn3.onlyfans.com/files/example/fallback.mp4",
        filename="fallback.mp4",
        directory=tmp_path / "library",
    )

    with caplog.at_level("WARNING"):
        success = await manager.download(item)

    assert success is True
    assert item.drm_media_settings.selected_staging_directory is None
    assert item.drm_media_settings.staging_fallback_reason is not None
    assert "No staging directory matched required operations" in caplog.text


@pytest.mark.asyncio
async def test_merge_parts_writes_tmp_then_renames_to_final(
    tmp_path, monkeypatch
) -> None:
    manager = DownloadManager(config=_build_config())
    dest_path = tmp_path / "merged.mp4"
    part_dir = tmp_path / "__parts__"
    part_dir.mkdir()
    part_a = part_dir / "merged_part0.mp4"
    part_b = part_dir / "merged_part1.mp4"
    part_a.write_bytes(b"abc")
    part_b.write_bytes(b"def")

    async def fake_to_thread(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(download_manager_module.asyncio, "to_thread", fake_to_thread)

    success = await manager.merge_parts(dest_path, [part_a, part_b])

    assert success is True
    assert dest_path.read_bytes() == b"abcdef"
    assert not (tmp_path / "merged.mp4.tmp").exists()


def test_concurrent_merges_can_remove_the_same_parts_folder(
    tmp_path, monkeypatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    part_dir = tmp_path / "__parts__"
    part_dir.mkdir()
    parts = [part_dir / "first.part", part_dir / "second.part"]
    for part, data in zip(parts, [b"first", b"second"], strict=True):
        part.write_bytes(data)
    renamed, cleaning = Barrier(2), Barrier(2)
    real_rename = download_manager_module.os.rename
    real_rmdir = Path.rmdir

    def rename(source, target):
        real_rename(source, target)
        renamed.wait(timeout=5)

    def rmdir(path):
        if path == part_dir:
            cleaning.wait(timeout=5)
        real_rmdir(path)

    monkeypatch.setattr(download_manager_module.os, "rename", rename)
    monkeypatch.setattr(Path, "rmdir", rmdir)
    destinations = [tmp_path / "first.mp4", tmp_path / "second.mp4"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(download_manager_module._merge_parts_sync, dest, [part], 1024)
            for dest, part in zip(destinations, parts, strict=True)
        ]
        assert [future.result(timeout=10) for future in futures] == [None, None]
    assert [dest.read_bytes() for dest in destinations] == [b"first", b"second"]
    assert not part_dir.exists()


@pytest.fixture
def inline_merge_io(monkeypatch):
    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(download_manager_module.asyncio, "to_thread", inline)


@pytest.mark.asyncio
async def test_merge_preserves_parts_of_another_download(
    tmp_path, inline_merge_io
) -> None:
    manager = DownloadManager(config=_build_config())
    part_dir = tmp_path / "__parts__"
    part_dir.mkdir()
    own_part, other_part = part_dir / "own.part", part_dir / "other.part"
    own_part.write_bytes(b"completed")
    other_part.write_bytes(b"still downloading")
    destination = tmp_path / "merged.mp4"

    assert await manager.merge_parts(destination, [own_part]) is True
    assert destination.read_bytes() == b"completed"
    assert other_part.read_bytes() == b"still downloading"


@pytest.mark.asyncio
async def test_merge_cleanup_permission_error_warns_after_success(
    tmp_path, monkeypatch, caplog, inline_merge_io
) -> None:
    manager = DownloadManager(config=_build_config())
    part_dir = tmp_path / "__parts__"
    part_dir.mkdir()
    part = part_dir / "own.part"
    part.write_bytes(b"completed")
    destination = tmp_path / "merged.mp4"

    def denied(path):
        raise PermissionError("cleanup denied")

    monkeypatch.setattr(Path, "rmdir", denied)
    assert await manager.merge_parts(destination, [part]) is True
    assert destination.read_bytes() == b"completed"
    assert "could not clean up" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_part", "write", "rename"])
async def test_real_merge_errors_still_fail(
    tmp_path, monkeypatch, failure, inline_merge_io
) -> None:
    manager = DownloadManager(config=_build_config())
    part_dir = tmp_path / "__parts__"
    part_dir.mkdir()
    part = part_dir / "own.part"
    destination = tmp_path / "merged.mp4"
    if failure != "missing_part":
        part.write_bytes(b"completed")

    if failure == "write":
        real_open = Path.open

        def denied_open(path, *args, **kwargs):
            if path == destination.with_suffix(".mp4.tmp"):
                raise OSError("merge write denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", denied_open)
    elif failure == "rename":

        def denied(source, target):
            raise PermissionError("rename denied")

        monkeypatch.setattr(download_manager_module.os, "rename", denied)

    assert await manager.merge_parts(destination, [part]) is False
    assert not destination.exists()
    assert not destination.with_suffix(".mp4.tmp").exists()


# ---- Parts written in place ------------------------------------------------

writes_in_place = pytest.mark.skipif(
    not hasattr(download_manager_module, "_download_target"),
    reason="this backend release joins part files instead",
)


class _RangeSession:
    """Serves `body` with ranges, recording each range asked for."""

    def __init__(self, body: bytes, *, honour_ranges: bool = True) -> None:
        self.body = body
        self.honour_ranges = honour_ranges
        self.ranges: list[str] = []

    def head(self, *args, **kwargs):
        return self._response(200, self.body)

    def get(self, url, *, headers, **kwargs):
        wanted = headers["Range"]
        self.ranges.append(wanted)
        if not self.honour_ranges:
            return self._response(200, self.body)
        start, end = (int(x) for x in wanted.removeprefix("bytes=").split("-"))
        return self._response(206, self.body[start : end + 1])

    @staticmethod
    def _response(status: int, data: bytes):
        class Content:
            async def iter_chunked(self, size: int):
                for offset in range(0, len(data), 7):
                    yield data[offset : offset + 7]

        class Response:
            content = Content()
            content_length = len(data)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc) -> None:
                return None

        Response.status = status
        return Response()


def _in_place_manager(session: _RangeSession) -> DownloadManager:
    return DownloadManager(
        config=_build_config(),
        resource_manager=ResourceManager(
            max_concurrency=8, buffer_size=10, per_domain_concurrency=8, head_concurrency=1
        ),
        session=session,
    )


@writes_in_place
async def test_parts_are_written_in_place_and_published_by_rename(tmp_path) -> None:
    body = bytes(range(256)) * 3
    session = _RangeSession(body)
    manager = _in_place_manager(session)
    item = DownloadItem(url="https://cdn.example/file.mp4", filename="file.mp4", directory=tmp_path)

    assert await manager.bulk_download([item], create_session=False) == {
        "total": 1, "completed": 1, "failed": 0, "success_rate": 100.0,
    }

    assert (tmp_path / "file.mp4").read_bytes() == body
    assert len(session.ranges) == 8
    # Nothing left behind: no part files, shared file or ledger.
    assert sorted(path.name for path in tmp_path.iterdir()) == ["file.mp4"]


@writes_in_place
async def test_a_restart_downloads_only_the_ranges_not_finished(tmp_path) -> None:
    body = b"0123456789" * 8
    target = download_manager_module._download_target(tmp_path / "file.mp4")
    # A first run finished the first range before it stopped.
    download_manager_module._prepare_download_target(target, len(body))
    target.write_bytes(body[:10])
    download_manager_module._record_range(target, "0-9")
    session = _RangeSession(body)
    manager = _in_place_manager(session)
    item = DownloadItem(url="https://cdn.example/file.mp4", filename="file.mp4", directory=tmp_path)

    assert (await manager.bulk_download([item], create_session=False))["completed"] == 1

    assert (tmp_path / "file.mp4").read_bytes() == body
    assert "bytes=0-9" not in session.ranges and len(session.ranges) == 7


@writes_in_place
async def test_a_different_file_at_the_same_name_starts_again(tmp_path) -> None:
    body = b"abcdefghij" * 4
    target = download_manager_module._download_target(tmp_path / "file.mp4")
    # Left by an earlier download of another size, with its first range done.
    download_manager_module._prepare_download_target(target, 999)
    target.write_bytes(b"x" * 999)
    download_manager_module._record_range(target, "0-9")
    session = _RangeSession(body)
    item = DownloadItem(url="https://cdn.example/file.mp4", filename="file.mp4", directory=tmp_path)

    assert (await _in_place_manager(session).bulk_download([item], create_session=False))["completed"] == 1

    assert (tmp_path / "file.mp4").read_bytes() == body
    assert "bytes=0-9" in session.ranges


@writes_in_place
async def test_a_server_ignoring_ranges_fails_the_download(tmp_path) -> None:
    session = _RangeSession(b"abcdefghij" * 4, honour_ranges=False)
    item = DownloadItem(url="https://cdn.example/file.mp4", filename="file.mp4", directory=tmp_path)

    stats = await _in_place_manager(session).bulk_download([item], create_session=False)

    assert stats["failed"] == 1 and not (tmp_path / "file.mp4").exists()


# ---- Decrypting and merging in one pass --------------------------------------

decrypts_in_one_pass = pytest.mark.skipif(
    not hasattr(download_handler_module, "_decrypt_and_merge"),
    reason="this backend release decrypts with mp4decrypt, then merges",
)


class _FormatterOnlyDrm:
    """The DRM module with a real media formatter; mp4decrypt only if it falls back."""

    def __init__(self, formatter) -> None:
        self.media_formatter = formatter
        self.decrypted: list[Path] = []

    async def decrypt_file_async(self, filepath, key, temp_output_path=None):
        self.decrypted.append(filepath)
        output = temp_output_path / filepath.name.replace(".enc", ".dec")
        output.write_bytes(b"dec")
        return output

    async def merge_media(self, output_filepath, media_paths):
        output_filepath.write_bytes(b"merged")
        return True


def _real_drm_item(tmp_path: Path, only_drm: object, kid: str, key: str) -> DownloadItem:
    from test_offload import _encrypted_streams

    item = _build_staged_drm_item(tmp_path, 9, only_drm)
    work = item.drm_media_settings.drm_temp_directory
    streams = _encrypted_streams(work, kid, key)
    item.drm_media_settings.drm_video_path = streams["video"]
    item.drm_media_settings.drm_audio_path = streams["audio"]
    assert item.media_metadata is not None
    item.media_metadata.drm_key = f"{kid}:{key}"
    return item


@decrypts_in_one_pass
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_drm_streams_are_decrypted_and_merged_in_one_ffmpeg_pass(tmp_path) -> None:
    from ultima_scraper_api.apis.onlyfans.classes.only_drm import MediaFormatter

    formatter = MediaFormatter(max_workers=1)
    only_drm = _FormatterOnlyDrm(formatter)
    kid, key = "a1b2c3d4e5f60718293a4b5c6d7e8f90", "0123456789abcdef0123456789abcdef"
    item = _real_drm_item(tmp_path, only_drm, kid, key)
    streams = [item.drm_media_settings.drm_video_path, item.drm_media_settings.drm_audio_path]

    await _process_drm_items([item])

    final = item.get_filepath()
    probe = await asyncio.to_thread(
        subprocess.run,
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(final)],
        check=True, capture_output=True, text=True,
    )
    assert sorted(probe.stdout.split()) == ["audio", "video"]
    assert only_drm.decrypted == []  # mp4decrypt never ran
    assert not any(stream.exists() for stream in streams)
    assert not final.with_name(final.name + ".tmp").exists()
    await formatter.shutdown()


@decrypts_in_one_pass
async def test_mp4decrypt_takes_over_when_ffmpeg_cannot_decrypt(tmp_path) -> None:
    class FailingFormatter:
        async def run_process(self, args, *, stdout_consumer=None):
            Path(args[-1]).write_bytes(b"half")  # a partial output is removed
            return SimpleNamespace(returncode=1, stderr=b"Invalid data found")

    only_drm = _FormatterOnlyDrm(FailingFormatter())
    item = _build_staged_drm_item(tmp_path, 10, only_drm)
    assert item.media_metadata is not None
    item.media_metadata.drm_key = "a1b2c3d4e5f60718293a4b5c6d7e8f90:0123456789abcdef0123456789abcdef"

    await _process_drm_items([item])

    assert len(only_drm.decrypted) == 2
    assert item.get_filepath().read_bytes() == b"merged"


@pytest.mark.asyncio
async def test_head_request_retries_a_dropped_proxy_connection(
    tmp_path, monkeypatch
) -> None:
    import aiohttp

    calls: list[str] = []

    class FakeResponse:
        status = 200
        content_length = 3

        async def __aenter__(self):
            if len(calls) <= 2:
                raise aiohttp.ClientConnectionError("Cannot connect to host")
            return self

        async def __aexit__(self, *exc) -> None:
            return None

    class FakeSession:
        def head(self, url, **kwargs):
            calls.append(url)
            return FakeResponse()

    async def no_sleep(seconds) -> None:
        return None

    manager = DownloadManager(config=_build_config())
    manager.session = FakeSession()
    monkeypatch.setattr(download_manager_module.asyncio, "sleep", no_sleep)
    item = DownloadItem(
        url="https://cdn2.onlyfans.com/files/example/photo.jpg",
        filename="photo.jpg",
        directory=tmp_path,
    )

    response = await manager.head_request(item)

    # Two drops, then the size: the file isn't failed for a dropped connection.
    assert response is not None and response.content_length == 3
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_head_request_gives_up_after_its_attempts(tmp_path, monkeypatch) -> None:
    import aiohttp

    calls: list[str] = []

    class FakeSession:
        def head(self, url, **kwargs):
            calls.append(url)
            raise aiohttp.ClientConnectionError("Cannot connect to host")

    async def no_sleep(seconds) -> None:
        return None

    manager = DownloadManager(config=_build_config())
    manager.session = FakeSession()
    monkeypatch.setattr(download_manager_module.asyncio, "sleep", no_sleep)
    item = DownloadItem(
        url="https://cdn2.onlyfans.com/files/example/photo.jpg",
        filename="photo.jpg",
        directory=tmp_path,
    )

    assert await manager.head_request(item) is None
    assert len(calls) == download_manager_module.HEAD_ATTEMPTS


def _two_slot_manager() -> DownloadManager:
    manager = DownloadManager(
        config=_build_config(),
        resource_manager=ResourceManager(
            max_concurrency=2,
            buffer_size=1024,
            per_domain_concurrency=2,
            head_concurrency=1,
        ),
    )
    manager.progress_update_interval = 0.0
    return manager


@pytest.mark.asyncio
async def test_progress_names_every_file_in_flight_with_its_destination(tmp_path: Path) -> None:
    manager = _two_slot_manager()
    events: list[dict[str, Any]] = []
    manager.on_progress.append(events.append)
    first = DownloadItem(url="https://cdn.test/a.mp4", filename="a.mp4", directory=tmp_path, media_id=1, size=100)
    second = DownloadItem(url="https://cdn.test/b.mp4", filename="b.mp4", directory=tmp_path, media_id=2, size=200)
    manager._begin_item_progress(first, expected_precounted=False)
    manager._begin_item_progress(second, expected_precounted=False)

    await manager._record_download_chunk(first, 10)
    assert events[-1]["path"] == str(tmp_path / "a.mp4")
    await manager._record_download_chunk(second, 20)

    assert events[-1]["status"] == "progress"
    assert events[-1]["active_transfers"] == [
        {"media_id": 1, "path": str(tmp_path / "a.mp4"), "processed_bytes": 0, "expected_bytes": 100},
        {"media_id": 2, "path": str(tmp_path / "b.mp4"), "processed_bytes": 0, "expected_bytes": 200},
    ]

    await manager._complete_download(first, 100)
    # The file this report finishes is no longer in flight.
    assert [row["media_id"] for row in events[-1]["active_transfers"]] == [2]

    manager._finish_item_progress(first)
    await manager._record_download_chunk(second, 20)
    assert [row["media_id"] for row in events[-1]["active_transfers"]] == [2]


@pytest.mark.asyncio
async def test_a_file_without_a_destination_does_not_break_its_progress() -> None:
    manager = _two_slot_manager()
    events: list[dict[str, Any]] = []
    manager.on_progress.append(events.append)
    item = DownloadItem(url="https://cdn.test/a.mp4", media_id=1)

    await manager._record_download_chunk(item, 10)

    assert events[-1]["path"] is None
    assert events[-1]["active_transfers"][0]["path"] is None

