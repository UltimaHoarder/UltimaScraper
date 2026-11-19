"""Privacy, DarkFans and Fansly reach the backend the way OnlyFans does:
sign-in fields, curl import, worker login, site lists and downloads."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ultima_scraper_backend import sites
from ultima_scraper_backend.api.routes import curl_parser
from ultima_scraper_backend.config import Sites, UltimaScraperCollectionConfig
from ultima_scraper_backend.job_system import download_manager as download_module
from ultima_scraper_backend.job_system.download_manager import DownloadItem, DownloadManager
from ultima_scraper_backend.job_system.metadata_models import MediaMetadata
from ultima_scraper_backend.usapi_initializer import (
    USAPIInitializer,
    login_site_api,
    site_auth_json,
)

CREATED = datetime(2026, 11, 18, tzinfo=timezone.utc)
ROW = SimpleNamespace(
    user_id=42,
    username="me",
    cookie="BEARER=jwt; refresh_token=rt",
    x_bc="xbc",
    authorization="Bearer token",
    user_agent="UA",
    email="me@example.invalid",
    password="secret",
)


def test_each_site_signs_in_with_its_own_stored_fields():
    assert site_auth_json("onlyfans", ROW) == {
        "id": 42, "username": "me", "cookie": ROW.cookie, "x_bc": "xbc",
        "user_agent": "UA", "email": ROW.email, "password": "secret",
    }
    for site in ("fansly", "privacy"):
        auth = site_auth_json(site, ROW)
        assert auth["authorization"] == "Bearer token"
        assert "cookie" not in auth and "x_bc" not in auth
    darkfans = site_auth_json("DarkFans", ROW)
    assert darkfans["cookie"] == ROW.cookie and "authorization" not in darkfans
    assert "password" not in darkfans
    # Every field each site reads is one its API's AuthDetails accepts.
    import ultima_scraper_api

    for site in ("onlyfans", "fansly", "privacy", "darkfans"):
        api = ultima_scraper_api.select_api(site)
        details = api.create_auth_details(site_auth_json(site, ROW))
        assert details.id == 42


@pytest.mark.asyncio
async def test_ignore_auth_errors_goes_only_to_apis_that_take_it():
    seen: list[dict[str, Any]] = []

    class Strict:
        async def login(self, auth_json=None, guest=False):
            seen.append({"auth_json": auth_json})
            return "authed"

    class Lenient:
        async def login(self, auth_json=None, guest=False, ignore_auth_errors=False):
            seen.append({"ignore": ignore_auth_errors})
            return "authed"

    assert await login_site_api(Strict(), {"id": 1}, ignore_auth_errors=True) == "authed"
    assert await login_site_api(Lenient(), {"id": 1}, ignore_auth_errors=True) == "authed"
    assert seen == [{"auth_json": {"id": 1}}, {"ignore": True}]


@pytest.mark.asyncio
async def test_initialize_auth_logs_in_a_site_without_websockets():
    authed = SimpleNamespace(username="me", subscriptions=[])

    class API:
        async def login(self, auth_json=None, guest=False):
            assert auth_json["cookie"] == ROW.cookie
            return authed

    initializer = USAPIInitializer(engine=None)  # type: ignore[arg-type]
    result = await initializer.initialize_auth(
        "darkfans", 42, API(), site_auth_json("darkfans", ROW)  # type: ignore[arg-type]
    )
    # No WebSocket to start and no OnlyFans-shaped stored subscriptions.
    assert result is authed


def test_site_lists_include_the_new_sites():
    assert {"onlyfans", "fansly", "privacy", "darkfans"} <= set(sites.ENABLED_SITE_KEYS)
    assert "loyalfans" in sites.SUPPORTED_SITE_KEYS
    assert sites.site_title("darkfans") == "DarkFans"
    assert sites.site_title("PRIVACY") == "Privacy"
    assert sites.site_title("nowhere") == "nowhere"
    settings = Sites()
    assert settings.get_settings("DarkFans") is settings.darkfans
    usapi = settings.to_usapi_sites()
    assert usapi.privacy is not None and usapi.darkfans is not None
    assert {"privacy", "darkfans"} <= set(UltimaScraperCollectionConfig().settings.worker_pool.sites)


def test_curl_import_reads_privacy_and_darkfans_commands():
    darkfans = curl_parser.parse_darkfans_curl(
        "curl 'https://darkfans.com/api/v1/user/info' -H 'user-agent: UA' "
        "-b 'OS-USER=x; BEARER=jwt; refresh_token=rt'"
    )
    assert darkfans.success and darkfans.cookie == "BEARER=jwt; refresh_token=rt"
    assert darkfans.user_agent == "UA"
    assert not curl_parser.parse_darkfans_curl("curl 'https://darkfans.com/' -b 'x=1'").success

    privacy = curl_parser.parse_privacy_curl(
        "curl 'https://service.privacy.com.br/profile/me' -H 'authorization: Bearer tok' -H 'user-agent: UA'"
    )
    assert privacy.success and privacy.site == "privacy" and privacy.authorization == "Bearer tok"

    auth_json, api = curl_parser._build_auth_login_request("darkfans", darkfans, "http://proxy:1")
    assert api is not None and api.site_name == "DarkFans"
    assert auth_json is not None
    assert auth_json["cookie"] == darkfans.cookie and auth_json["proxy_url"] == "http://proxy:1"
    # The id is learnt from the test sign-in, so none is sent.
    assert "id" not in auth_json


@pytest.mark.asyncio
@pytest.mark.parametrize("site", curl_parser._LOCAL_LOGIN_SITES)
async def test_import_sign_in_reaches_each_sites_authenticator(site):
    """The import's test sign-in sends no account id; every site's API must
    still get as far as its authenticator (Fansly once raised KeyError 'id')."""
    parsed = curl_parser.ParsedCurlData(
        success=True, site=site, cookie="BEARER=jwt; refresh_token=rt",
        authorization="Bearer tok", user_agent="UA",
    )
    auth_json, api = curl_parser._build_auth_login_request(site, parsed)
    assert auth_json is not None and api is not None
    reached: list[str] = []

    class Authenticator:
        def __init__(self, _api, details, guest=False):
            reached.append(site)

        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            pass

    api.authenticator = Authenticator
    async with api.login_context(auth_json) as authed:
        assert authed is None
    assert reached == [site]


@pytest.mark.asyncio
async def test_parse_endpoint_dispatches_every_site():
    response = await curl_parser.parse_curl(
        curl_parser.CurlParseRequest(
            curl_command="curl 'https://darkfans.com/api/v1/user/info' -b 'BEARER=a'", site="DarkFans"
        )
    )
    assert response.success and response.site == "darkfans"
    unknown = await curl_parser.parse_curl(
        curl_parser.CurlParseRequest(curl_command="curl 'https://x.test/'", site="nowhere")
    )
    assert not unknown.success and "darkfans" in (unknown.error or "")


def _item(tmp_path: Path, url: str, authed: Any, *, drm: bool = False) -> DownloadItem:
    metadata = MediaMetadata(
        media_id=7,
        media_type="videos",
        urls=[url],
        content_id=1,
        user_id=2,
        created_at=CREATED,
        drm=drm,
    )
    return DownloadItem(
        user=SimpleNamespace(get_authed=lambda: authed),
        url=url,
        filename="clip.mp4",
        directory=tmp_path,
        media_metadata=metadata,
    )


@pytest.mark.asyncio
async def test_site_saves_files_a_plain_get_cannot_fetch(tmp_path):
    saved: list[Path] = []

    async def save(destination: Path) -> Path:
        destination.write_bytes(b"video")
        saved.append(destination)
        return destination

    authed = SimpleNamespace(stream_downloader=lambda url: save if url.endswith(".m3u8") else None)
    manager = DownloadManager(config=UltimaScraperCollectionConfig(), session=object())  # type: ignore[arg-type]

    async def no_head(_item):
        raise AssertionError("a playlist's size says nothing about the saved video")

    manager.head_request = no_head  # type: ignore[method-assign]
    item = _item(tmp_path, "https://video.test/f1/hls/master.m3u8", authed)
    assert await manager.download(item)
    assert saved == [tmp_path / "clip.mp4"] and item.size == 5 and item.downloaded_this_run
    # Once saved, the file counts as done without asking the server.
    again = _item(tmp_path, "https://video.test/f1/hls/master.m3u8", authed)
    assert await manager.download(again)
    assert len(saved) == 1
    # Direct files still go the regular way.
    assert download_module._site_stream_downloader(_item(tmp_path, "https://cdn.test/a.jpg", authed)) is None


@pytest.mark.asyncio
async def test_drm_without_a_decryptor_fails_with_a_reason(tmp_path):
    authed = SimpleNamespace(drm=None, api=SimpleNamespace(site_name="DarkFans"))
    manager = DownloadManager(config=UltimaScraperCollectionConfig(), session=object())  # type: ignore[arg-type]
    item = _item(tmp_path, "https://cdn.test/master.mpd", authed, drm=True)
    item.media_metadata.drm_media = SimpleNamespace(manifest_url=item.url)  # type: ignore[union-attr]
    assert not await manager.download(item)
    assert item.failure_message == "No DRM decryption available for DarkFans videos"


def test_playlist_media_are_named_as_the_mp4_they_become():
    metadata = MediaMetadata(
        media_id=7, media_type="videos", urls=["https://video.test/f1/hls/clip--1.m3u8"],
        content_id=1, user_id=2, created_at=CREATED,
    )
    assert metadata.extract_filename_from_url() == "clip--1.mp4"


@pytest.mark.asyncio
async def test_refresh_updates_the_stored_account(monkeypatch):
    """Refresh signs in like Test, then keeps what the sign-in learnt: the
    profile, a changed username and DarkFans' renewed session cookie."""
    from contextlib import asynccontextmanager

    import ultima_scraper_api
    from ultima_scraper_backend.api.routes import auths as auths_route
    from ultima_scraper_backend.database.helpers import user_sync

    row = SimpleNamespace(
        id=9, site="darkfans", user_id=42, username="old", cookie="BEARER=old; refresh_token=rt",
        x_bc=None, authorization=None, user_agent="UA", email="", password="", proxy_id=None,
        status="unknown", last_tested_at=None, is_age_verified=None, age_verification_required=None,
        touch=lambda: None,
    )

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def exec(self, _query):
            return SimpleNamespace(first=lambda: row)

        def add(self, _obj):
            pass

        def commit(self):
            pass

    site_db = SimpleNamespace(get_session=Session)
    authed = SimpleNamespace(
        username="new",
        is_authed=lambda: True,
        get_auth_details=lambda: SimpleNamespace(cookie="BEARER=renewed; refresh_token=rt"),
    )

    @asynccontextmanager
    async def login_context(auth_json):
        assert auth_json["cookie"] == "BEARER=old; refresh_token=rt"
        yield authed

    api = SimpleNamespace(
        login_context=login_context,
        websocket_manager=SimpleNamespace(close_all_connections=lambda: None),
    )
    synced: list[Any] = []

    async def fake_sync(db, auth, *, site=None):
        synced.append((db, auth, site))
        return True

    published: list[tuple] = []

    async def fake_publish(_manager, account_id, *, username=None, site="onlyfans"):
        published.append((account_id, username, site))

    monkeypatch.setattr(
        auths_route, "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(get_or_create_manager=lambda _site: site_db),
    )
    monkeypatch.setattr(ultima_scraper_api, "select_api", lambda _site: api)
    monkeypatch.setattr(user_sync, "sync_authed_user_from_api", fake_sync)
    monkeypatch.setattr(auths_route, "publish_auth_updated", fake_publish)

    # Test alone leaves the stored account as it was.
    tested = await auths_route.test_auth(9, site="darkfans", refresh=False, backend_manager=None)
    assert tested.success and tested.message == "Authentication is valid"
    assert (row.username, row.cookie, synced) == ("old", "BEARER=old; refresh_token=rt", [])

    refreshed = await auths_route.test_auth(9, site="darkfans", refresh=True, backend_manager=None)
    assert refreshed.success and refreshed.message == "Account refreshed"
    assert (refreshed.username, refreshed.profile_updated) == ("new", True)
    assert row.status == "valid" and row.username == "new"
    assert row.cookie == "BEARER=renewed; refresh_token=rt"
    assert synced == [(site_db, authed, "darkfans")]
    assert published == [(42, "new", "darkfans")]


def test_media_that_says_it_has_no_drm_is_not_drm():
    """Privacy media carry "drm": False; that once counted as DRM, so every
    Privacy file went to the DRM downloader and failed."""
    from ultima_scraper_backend.content_persistence import ContentPersistenceMixin

    extract = ContentPersistenceMixin._extract_drm_manifest_payload
    assert extract({"id": 1, "url": "https://cdn.test/a.jpg", "drm": False}) == (False, {})
    assert extract({"id": 1, "url": "https://cdn.test/a.jpg"}) == (False, {})
    assert extract({"id": 1, "drm": True}) == (True, {})
    has_drm, payload = extract(
        {"files": {"drm": {"manifest": {"dash": "https://cdn.test/v.mpd"}}}}
    )
    assert has_drm and payload == {"dash_manifest": "https://cdn.test/v.mpd"}


def test_image_handler_urls_save_under_the_file_they_ask_for():
    import base64
    import json

    from ultima_scraper_backend.job_system.metadata_models import url_filename

    request = {
        "bucket": "images",
        "key": "2026-9-7/51accbee-63924--creator.jpg",
        "edits": {"resize": {"height": 1080}},
    }
    encoded = base64.b64encode(json.dumps(request).encode()).decode()
    assert url_filename(f"https://image.test/{encoded}") == "51accbee-63924--creator.jpg"
    assert url_filename("https://cdn.test/a/photo.jpg?sig=1") == "photo.jpg"
    assert url_filename("https://cdn.test/eyJub3QganNvbg") == "eyJub3QganNvbg"
    metadata = MediaMetadata(
        media_id=7, media_type="images", urls=[f"https://image.test/{encoded}"],
        content_id=1, user_id=2, created_at=CREATED,
    )
    assert metadata.extract_filename_from_url() == "51accbee-63924--creator.jpg"


def test_uploads_named_by_their_folder_save_under_distinct_names():
    """DarkFans keeps every upload as <upload id>/originalWatermarked.webp:
    two uploads must not save, or be looked up, under the same name."""
    from ultima_scraper_backend.api.routes.files import _extract_filename_from_url
    from ultima_scraper_backend.job_system.metadata_models import url_filename

    base = "https://cdn.test/uploads/production/5e7cc513-0000-0000-00ac-64e7366ef31c"
    first = f"{base}/81633b6f-0bf5-47b8-ab89-3751027432c3/originalWatermarked.webp?Expires=1"
    second = f"{base}/0d4c2a8e-7b1f-4c55-9e0a-2f6b8d1c3e47/originalWatermarked.webp?Expires=1"
    assert url_filename(first) == "81633b6f-0bf5-47b8-ab89-3751027432c3.webp"
    assert url_filename(second) == "0d4c2a8e-7b1f-4c55-9e0a-2f6b8d1c3e47.webp"
    # Serving a downloaded file looks for the name the download used.
    assert _extract_filename_from_url(first) == url_filename(first)
    # Other sites' folders aren't upload ids, so their names are kept.
    assert url_filename("https://cdn3.test/100000000000000001/100000000000000002.png") == (
        "100000000000000002.png"
    )
    assert url_filename("https://video.test/a/hls/clip-1.m3u8") == "clip-1.m3u8"


def test_a_stored_fastevo_video_becomes_a_drm_download():
    """DarkFans keeps a video's Fastevo play token as its manifest's
    signature (no CloudFront cookies): it still reads back as DRM media,
    named by the video's id and sent without cookies."""
    from types import SimpleNamespace

    from ultima_scraper_backend.job_system.metadata_models import ContentMetadata

    manifest = "https://media.fastevo.test/65f0c0ffee00000000000001/processed/video/content/media/master.mpd"
    db_media = SimpleNamespace(
        id=11, category="video", url=None, size=0, drm=True, preview=False,
        created_at=CREATED, media_urls=[],
        drm_manifest=SimpleNamespace(
            dash_manifest=manifest, dash_key_pair_id=None, dash_policy=None,
            dash_signature="v4.local.play-token", video_url=None, audio_url=None,
            video_size=None, audio_size=None,
        ),
    )
    db_content = SimpleNamespace(
        id=5, user_id=2, created_at=CREATED, text="", price=0.0, paid=False,
        archived=False, expires_at=None, receiver_id=None, queue_id=None, media=[db_media],
    )

    media = ContentMetadata.from_db_record(db_content, content_type="posts").medias[0]

    assert media.drm and media.drm_media is not None
    assert media.drm_media.is_fastevo
    assert media.drm_media.signature == "v4.local.play-token"
    assert media.drm_media.get_cookies() == ""
    assert media.filename == "65f0c0ffee00000000000001.mp4"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("ffmpeg", "mp4decrypt")), reason="needs ffmpeg and Bento4"
)
async def test_tracks_with_their_own_keys_decrypt_with_one_key_string(tmp_path):
    """A Fastevo video's tracks may each have a key: the key string lists
    every KID:KEY, the one-pass ffmpeg decrypt declines it, and mp4decrypt
    decrypts each track with its own."""
    import subprocess

    from ultima_scraper_api.apis.onlyfans.classes.only_drm import (
        MediaFormatter,
        mp4decrypt_key_arguments,
    )
    from ultima_scraper_backend.job_system.handlers.download.handler import _decrypt_and_merge

    keys = {
        "video": ("a1b2c3d4e5f60718293a4b5c6d7e8f90", "0123456789abcdef0123456789abcdef"),
        "audio": ("0f1e2d3c4b5a69788796a5b4c3d2e1f0", "fedcba9876543210fedcba9876543210"),
    }
    sources = {
        "video": ["-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10", "-c:v", "libx264", "-an"],
        "audio": ["-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac", "-vn"],
    }
    streams = {}
    for name, (kid, key) in keys.items():
        streams[name] = tmp_path / f"{name}.enc.mp4"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", *sources[name], "-encryption_scheme", "cenc-aes-ctr",
             "-encryption_key", key, "-encryption_kid", kid, str(streams[name])],
            check=True,
        )
    drm_key = " ".join(f"{kid}:{key}" for kid, key in keys.values())

    formatter = MediaFormatter(max_workers=1)
    try:
        holder = SimpleNamespace(media_formatter=formatter)
        assert not await _decrypt_and_merge(holder, list(streams.values()), drm_key, tmp_path / "out.mp4")
        for name, stream in streams.items():
            # With every pair given, each track decrypts exactly as with its own key.
            both = tmp_path / f"{name}.both.mp4"
            own = tmp_path / f"{name}.own.mp4"
            subprocess.run(
                ["mp4decrypt", *mp4decrypt_key_arguments(drm_key), str(stream), str(both)], check=True
            )
            subprocess.run(
                ["mp4decrypt", "--key", ":".join(keys[name]), str(stream), str(own)], check=True
            )
            assert both.read_bytes() == own.read_bytes()
            assert b"encv" not in both.read_bytes() and b"enca" not in both.read_bytes()
            assert both.read_bytes() != stream.read_bytes()
    finally:
        await formatter.shutdown()


@pytest.mark.asyncio
async def test_streams_a_site_decrypts_itself_skip_the_one_pass_ffmpeg_decrypt(tmp_path):
    """Fastevo's cbcs tracks go to its own decrypt (Shaka), even with one key."""
    from ultima_scraper_backend.job_system.handlers.download.handler import _decrypt_and_merge

    class Formatter:
        async def run_process(self, args):
            raise AssertionError("ffmpeg must not decrypt these streams")

    own = SimpleNamespace(media_formatter=Formatter(), decrypts_own_streams=True)
    stream = tmp_path / "v.enc.mp4"
    stream.write_bytes(b"x")
    single_key = "a1b2c3d4e5f60718293a4b5c6d7e8f90:0123456789abcdef0123456789abcdef"
    assert not await _decrypt_and_merge(own, [stream], single_key, tmp_path / "out.mp4")


@pytest.mark.asyncio
async def test_a_server_that_refuses_head_still_serves_the_whole_file(tmp_path):
    """Privacy's image handler answers HEAD with 403, honours ranges and
    refuses requests without the site's Referer: the file is fetched with
    the headers the site's auth names, without a known size, and all of it."""
    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    body = bytes(range(256)) * 40
    seen_ranges: list[str | None] = []

    async def image(request: web.Request) -> web.Response:
        if request.method == "HEAD" or request.headers.get("Referer") != "https://site.test/":
            return web.Response(status=403)
        wanted = request.headers.get("Range")
        seen_ranges.append(wanted)
        if wanted:
            start, _, end = wanted.removeprefix("bytes=").partition("-")
            chunk = body[int(start): int(end) + 1 if end else None]
            return web.Response(status=206, body=chunk)
        return web.Response(body=body)

    app = web.Application()
    app.router.add_route("*", "/{name}", image)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            manager = DownloadManager(config=UltimaScraperCollectionConfig(), session=session)
            url = str(server.make_url("/eyJrZXkiOiJhLmpwZyJ9"))
            authed = SimpleNamespace(
                stream_downloader=lambda _url: None,
                media_request_headers=lambda _url: {"Referer": "https://site.test/"},
            )
            item = _item(tmp_path, url, authed)
            item.filename = "a.jpg"
            assert await manager.download(item)
    finally:
        await server.close()
    assert (tmp_path / "a.jpg").read_bytes() == body
    assert seen_ranges == ["bytes=0-"]
