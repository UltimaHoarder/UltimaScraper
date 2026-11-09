"""Handing finished downloads to the backend that keeps them (phase 2)."""

from __future__ import annotations

import asyncio
import shutil
import os
import socket
import stat
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from ultima_scraper_api.job_events import DownloadFailureReason, DownloadResultItem
from ultima_scraper_core.tls import ensure_self_signed, fingerprint

from ultima_scraper_backend import peer_tokens
from ultima_scraper_backend.api.routes import offload as offload_routes
from ultima_scraper_backend.config import DownloadPathSetup, Drive
from ultima_scraper_backend.job_system import ledger_runtime
from ultima_scraper_backend.job_system.drive_selection import DriveSelectionError, UserDirectorySelection
from ultima_scraper_backend.job_system.handlers.download import handler, streaming
from ultima_scraper_backend.offload import store
from ultima_scraper_backend.offload.client import OffloadClient, OffloadError, Owner
from ultima_scraper_backend.offload.remote import RemoteStore

PEER = "usrp_pi-token"


def _setup(*roots: Path) -> DownloadPathSetup:
    return DownloadPathSetup(
        directory_format=Path("{site_name}/{user_username}"),
        filename_format=Path("{media_filename}.{media_ext}"),
        drives=[Drive(directories=list(roots))],
    )


# ---- the owner's store ------------------------------------------------------


@pytest.mark.parametrize(
    "root_name, relative",
    [
        ("elsewhere", "OnlyFans/a/b.mp4"),  # not one of the owner's drives
        ("drive", "../escape.mp4"),
        ("drive", "/etc/passwd"),
        ("drive", "OnlyFans/.b.mp4.offload.part"),
    ],
)
def test_store_refuses_paths_outside_its_drives(tmp_path, root_name, relative) -> None:
    drive = tmp_path / "drive"
    drive.mkdir()
    (tmp_path / "elsewhere").mkdir()

    with pytest.raises(store.OffloadRejected):
        store.resolve_target(_setup(drive), str(tmp_path / root_name), relative)


def test_store_resumes_and_commits_without_replacing(tmp_path) -> None:
    drive = tmp_path / "drive"
    target = store.resolve_target(_setup(drive), str(drive), "OnlyFans/t/tester/a.mp4")

    with store.open_part(target, 0, 4) as handle:
        handle.write(b"abcd")
    with pytest.raises(store.OffloadRejected):  # a gap after the 4 bytes received
        store.open_part(target, 6, 2)
    with pytest.raises(store.OffloadRejected):
        store.commit(target, 8)
    with store.open_part(target, 2, 6) as handle:  # resend from byte 2
        handle.write(b"cdefgh")

    committed = store.commit(target, 8)
    assert (committed.existing, target.read_bytes()) == (False, b"abcdefgh")
    assert not store.part_path(target).exists()

    with store.open_part(target, 0, 1) as handle:
        handle.write(b"z")
    assert store.commit(target, 1).existing  # the kept file stays as it is
    assert target.read_bytes() == b"abcdefgh"


# ---- the routes, over HTTPS, through the real client ---------------------------


class _Owner:
    """The offload routes served over HTTPS, as another backend would call them."""

    def __init__(self, tls_dir: Path) -> None:
        files = ensure_self_signed(tls_dir, common_name="UltimaScraper backend")
        self.fingerprint = fingerprint(files.cert_file)
        app = FastAPI()
        app.include_router(offload_routes.router, prefix="/api/v1")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=self.port,
                log_level="warning",
                ssl_certfile=str(files.cert_file),
                ssl_keyfile=str(files.key_file),
            )
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)

    def owner(self, fingerprint_value: str | None = None) -> Owner:
        return Owner("datahoarders", f"https://127.0.0.1:{self.port}", fingerprint_value or self.fingerprint)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture
def owner_side(tmp_path, monkeypatch):
    drive = tmp_path / "owner-drive"
    drive.mkdir()
    monkeypatch.setattr(offload_routes, "_setup", lambda: _setup(drive))
    monkeypatch.setattr(peer_tokens, "_active", {peer_tokens.hash_secret(PEER): "atlas-8be427"})
    selected = UserDirectorySelection(
        root=drive,
        performer_relative_path=Path("OnlyFans/T/tester"),
        directory_format=Path("{site_name}/{first_username_letter}/{user_username}"),
        performer_username="tester",
    )
    monkeypatch.setattr(offload_routes, "select_user_destination", lambda **kwargs: selected)
    monkeypatch.setattr(
        offload_routes.UltimaScraperCollectionConfig, "load_or_create_default_config", classmethod(lambda cls: None)
    )
    server = _Owner(tmp_path / "tls")
    yield server, drive
    server.stop()


@pytest.mark.asyncio
async def test_a_backend_without_drives_hands_files_to_the_owner(owner_side, tmp_path) -> None:
    server, drive = owner_side
    local = tmp_path / "pi" / "clip.mp4"
    local.parent.mkdir()
    local.write_bytes(b"x" * (3 * 1024 * 1024 + 5))

    async with OffloadClient(server.owner(), PEER) as client:
        answer = await client.destination(site_name="onlyfans", user_id=7, usernames=["tester"])
        assert (answer["root"], answer["performer_relative_path"]) == (str(drive), "OnlyFans/T/tester")

        # An earlier attempt got part of the file across; the upload resumes after it.
        target = drive / "OnlyFans/T/tester/Posts/clip.mp4"
        target.parent.mkdir(parents=True)
        store.part_path(target).write_bytes(b"x" * 1000)
        committed = await client.store(local, root=answer["root"], path="OnlyFans/T/tester/Posts/clip.mp4")

    assert committed == {"path": str(target), "size": local.stat().st_size, "existing": False}
    assert target.read_bytes() == local.read_bytes()


@pytest.mark.asyncio
async def test_owner_routes_need_a_peer_token_and_a_pinned_certificate(owner_side) -> None:
    server, _ = owner_side

    async with OffloadClient(server.owner(), "usrc_a-webui-client-token") as client:
        with pytest.raises(OffloadError, match="401"):
            await client.destination(site_name="onlyfans", usernames=["tester"])
    async with OffloadClient(server.owner("00:" * 31 + "00"), PEER) as client:
        with pytest.raises(OffloadError, match="unreachable"):
            await client.destination(site_name="onlyfans", usernames=["tester"])


# ---- peer tokens --------------------------------------------------------------


@pytest.fixture
def peer_database(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def attach(connection, _record):
        connection.execute("ATTACH DATABASE ':memory:' AS management")
        connection.create_function("now", 0, lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE management.backend_peers (backend_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_seen_at TIMESTAMP, revoked_at TIMESTAMP)"
            )
        )
    monkeypatch.setattr(peer_tokens, "_session", lambda: Session(engine))
    monkeypatch.setattr(peer_tokens, "token_path", lambda: tmp_path / "config" / "peer_token")
    monkeypatch.setattr(peer_tokens, "_active", {})
    monkeypatch.setattr(peer_tokens, "_own_token", None)
    return engine


def test_each_backend_issues_itself_one_token_until_revoked(peer_database, tmp_path) -> None:
    token = peer_tokens.ensure_own_token("atlas-8be427")
    path = tmp_path / "config" / "peer_token"

    assert token.startswith(peer_tokens.PEER_TOKEN_PREFIX)
    assert path.read_text() == token
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert peer_tokens.ensure_own_token("atlas-8be427") == token  # kept across restarts
    assert peer_tokens._load_active() == {peer_tokens.hash_secret(token): "atlas-8be427"}

    path.write_text("usrp_lost")  # a token the database does not know is replaced
    replacement = peer_tokens.ensure_own_token("atlas-8be427")
    assert replacement != token and peer_tokens._load_active() == {peer_tokens.hash_secret(replacement): "atlas-8be427"}

    assert peer_tokens.revoke("atlas-8be427")
    assert peer_tokens.peer_backend(replacement) is None
    assert peer_tokens._load_active() == {}
    with pytest.raises(peer_tokens.PeerRevoked):
        peer_tokens.ensure_own_token("atlas-8be427")


# ---- the download side ----------------------------------------------------------


class _Client:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.stored = fail, []

    async def store(self, local: Path, *, root: str, path: str) -> dict:
        if self.fail:
            raise OffloadError("datahoarders unreachable")
        self.stored.append((local.read_bytes(), root, path))
        return {"path": f"{root}/{path}", "size": local.stat().st_size, "existing": False}


def _remote(tmp_path, client) -> RemoteStore:
    local_root = tmp_path / "mirror"
    selection = UserDirectorySelection(root=local_root, performer_relative_path=Path("OnlyFans/T/tester"))
    return RemoteStore(client=client, owner_root="/mnt/media", local_root=local_root, selection=selection)


@pytest.mark.asyncio
async def test_finished_files_are_handed_over_and_recorded_at_the_owner(tmp_path) -> None:
    client = _Client()
    remote = _remote(tmp_path, client)
    local = remote.local_root / "OnlyFans/T/tester/Posts/a.jpg"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"abc")
    existing = DownloadResultItem(media_id=2, status="skipped", path=str(remote.local_root / "OnlyFans/T/tester/b.jpg"))
    existing.add_error(DownloadFailureReason.ALREADY_EXISTS, "already there")
    (remote.local_root / "OnlyFans/T/tester/b.jpg").write_bytes(b"b")
    results = [
        DownloadResultItem(media_id=1, status="downloaded", path=str(local)),
        existing,
        DownloadResultItem(media_id=3, status="failed", path=str(remote.local_root / "x.jpg")),
    ]

    await handler._hand_over(remote, results)

    assert [r.path for r in results[:2]] == ["/mnt/media/OnlyFans/T/tester/Posts/a.jpg", "/mnt/media/OnlyFans/T/tester/b.jpg"]
    assert client.stored[0] == (b"abc", "/mnt/media", "OnlyFans/T/tester/Posts/a.jpg")
    assert not local.exists() and not local.parent.exists()  # emptied folders go too
    assert results[2].status == "failed" and len(client.stored) == 2


@pytest.mark.asyncio
async def test_a_failed_hand_over_keeps_the_file_and_fails_recoverably(tmp_path) -> None:
    remote = _remote(tmp_path, _Client(fail=True))
    local = remote.local_root / "a.jpg"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"abc")
    result = DownloadResultItem(media_id=1, status="downloaded", path=str(local))

    await handler._hand_over(remote, [result])

    assert result.status == "failed" and result.is_recoverable
    assert local.exists()


@pytest.mark.asyncio
async def test_destination_comes_from_the_owner_only_without_local_drives(monkeypatch, tmp_path) -> None:
    local = UserDirectorySelection(root=tmp_path, performer_relative_path=Path("x"))
    monkeypatch.setattr(streaming, "select_user_destination", lambda **kwargs: local)
    request = dict(site_name="onlyfans", user_id=7, usernames=["tester"], user_manager=None, config=None,
                   required_space=10, ignore_space_requirements=False)

    assert await streaming._destination(None, **request) == (local, None)

    remote = _remote(tmp_path, _Client())

    class Offload:
        def __init__(self, fail):
            self.fail = fail

        async def destination(self, **kwargs):
            if self.fail:
                raise OffloadError("No backend can keep these files")
            return remote

    assert await streaming._destination(Offload(False), **request) == (remote.selection, remote)
    with pytest.raises(DriveSelectionError):
        await streaming._destination(Offload(True), **request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headroom, drive, owner, offered",
    [(True, True, False, True), (True, False, True, True), (True, False, False, False), (False, True, True, False)],
)
async def test_downloads_are_offered_with_room_and_somewhere_to_keep_them(headroom, drive, owner, offered) -> None:
    adapter = ledger_runtime.LedgerRouterAdapter.__new__(ledger_runtime.LedgerRouterAdapter)
    adapter.downloads = SimpleNamespace(has_headroom=lambda: headroom, drive_reachable=lambda: drive)

    async def owner_available():
        return owner

    adapter._owner_available = owner_available
    assert await adapter.offers_downloads() is offered


# ---- phase 3: where a DRM item is decrypted ----------------------------------------

import subprocess  # noqa: E402

from ultima_scraper_backend.offload import placement  # noqa: E402
from ultima_scraper_backend.offload.placement import Capacity, prefer_owner  # noqa: E402

MIB = 1024 * 1024


@pytest.mark.parametrize(
    "size, here, owner, expected",
    [
        # Small items never move.
        (10 * MIB, Capacity(1 * MIB, 5, 1), Capacity(200 * MIB, 0, 8), False),
        # A slow Pi against datahoarders: the owner finishes far sooner.
        (2000 * MIB, Capacity(30 * MIB, 0, 1), Capacity(200 * MIB, 0, 8), True),
        # Just faster is not enough: the margin keeps rough estimates from moving work.
        (2000 * MIB, Capacity(180 * MIB, 0, 1), Capacity(200 * MIB, 0, 1), False),
        # A fast owner with a long queue loses to an idle local slot.
        (2000 * MIB, Capacity(60 * MIB, 0, 1), Capacity(200 * MIB, 40, 2), False),
        # Unmeasured: only a full host hands work to a free one.
        (2000 * MIB, Capacity(None, 1, 1), Capacity(None, 0, 8), True),
        (2000 * MIB, Capacity(None, 0, 1), Capacity(None, 0, 8), False),
    ],
)
def test_the_owner_decrypts_only_when_clearly_sooner(size, here, owner, expected) -> None:
    assert prefer_owner(size, here, owner) is expected


def test_rate_meter_smooths_measurements_and_counts_the_queue(monkeypatch) -> None:
    monkeypatch.setenv("ULTIMA_MEDIA_PROCESS_CONCURRENCY", "1")
    meter = placement.RateMeter()
    clock = iter([0.0, 2.0, 10.0, 12.0, 14.0])
    monkeypatch.setattr(placement.time, "monotonic", lambda: next(clock))

    meter.finished(meter.started(), 200 * MIB, ok=True)
    assert meter.rate == 100 * MIB
    first, second = meter.started(), meter.started()
    assert meter.capacity().waiting == 1  # two in hand, one slot
    meter.finished(first, 0, ok=False)  # a failure measures nothing
    assert meter.rate == 100 * MIB


class _OwnerSide:
    def __init__(self, rate):
        self.rate, self.decrypted = rate, []

    async def capacity(self):
        return {"rate": self.rate, "waiting": 0, "slots": 8, "decrypts": True}

    async def decrypt(self, streams, *, key, root, path, drm_key, mtime):
        self.decrypted.append((sorted(streams), root, path, drm_key, mtime))
        return {"path": f"{root}/{path}", "size": 1234, "existing": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_rate, on_owner", [(500 * MIB, True), (1 * MIB, False)])
async def test_the_pipeline_follows_the_placement_rule(monkeypatch, tmp_path, owner_rate, on_owner) -> None:
    from test_download_pipeline import _BarrierOnlyDrm, _build_staged_drm_item

    monkeypatch.setattr(placement, "MIN_OFFLOAD_BYTES", 0)
    monkeypatch.setattr(placement.meter, "rate", 10 * MIB)
    only_drm = _BarrierOnlyDrm(parties=1)
    item = _build_staged_drm_item(tmp_path, 7, only_drm)
    owner_side = _OwnerSide(owner_rate)
    remote = RemoteStore(
        client=SimpleNamespace(capacity=owner_side.capacity, decrypt=owner_side.decrypt, owner=SimpleNamespace(backend_id="datahoarders")),
        owner_root="/mnt/media",
        local_root=tmp_path,
        selection=None,
    )
    pipeline = handler._DRMPipeline(1, remote_store=remote)

    assert await pipeline._process(item)

    if on_owner:
        assert item.offloaded_path == "/mnt/media/library/7.mp4" and item.size == 1234
        streams, root, path, drm_key, _ = owner_side.decrypted[0]
        assert (streams, root, path, drm_key) == (["audio", "video"], "/mnt/media", "library/7.mp4", "secret-key")
        assert not item.drm_media_settings.drm_video_path.exists()  # handed over, then dropped
        assert only_drm.merged == []
    else:
        assert item.offloaded_path is None and owner_side.decrypted == []
        assert item.get_filepath().read_bytes() == b"merged"


def _encrypted_streams(directory: Path, kid: str, key: str) -> dict[str, Path]:
    """A second of CENC-encrypted video and audio, as a CDN would serve them."""
    streams = {"video": directory / "video.enc.mp4", "audio": directory / "audio.enc.mp4"}
    sources = {
        "video": ["-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10", "-c:v", "libx264", "-an"],
        "audio": ["-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac", "-vn"],
    }
    for name, path in streams.items():
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", *sources[name], "-encryption_scheme", "cenc-aes-ctr",
             "-encryption_key", key, "-encryption_kid", kid, str(path)],
            check=True,
        )
    return streams


@pytest.mark.asyncio
@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe", "mp4decrypt")), reason="needs ffmpeg and Bento4"
)
async def test_the_owner_decrypts_merges_and_keeps_real_drm_streams(owner_side, tmp_path, monkeypatch) -> None:
    server, drive = owner_side
    staging = tmp_path / "owner-staging"
    monkeypatch.setattr(
        offload_routes,
        "_setup",
        lambda: DownloadPathSetup(
            directory_format=Path("{site_name}/{user_username}"),
            filename_format=Path("{media_filename}.{media_ext}"),
            drives=[Drive(directories=[drive])],
            staging_directories=[{"path": staging, "usage": ["drm"], "policy": []}],
        ),
    )
    kid, key = "a1b2c3d4e5f60718293a4b5c6d7e8f90", "0123456789abcdef0123456789abcdef"
    (tmp_path / "pi").mkdir()
    streams = _encrypted_streams(tmp_path / "pi", kid, key)

    async with OffloadClient(server.owner(), PEER) as client:
        assert (await client.capacity())["decrypts"]
        kept = await client.decrypt(
            streams, key="media-7-test-key", root=str(drive), path="OnlyFans/T/tester/Videos/7.mp4",
            drm_key=f"{kid}:{key}", mtime=1_700_000_000.0,
        )

    final = drive / "OnlyFans/T/tester/Videos/7.mp4"
    assert kept == {"path": str(final), "size": final.stat().st_size, "existing": False}
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(final)],
        check=True, capture_output=True, text=True,
    )
    assert sorted(probe.stdout.split()) == ["audio", "video"]
    assert final.stat().st_mtime == 1_700_000_000.0
    assert not (staging / "offload" / "media-7-test-key").exists()  # streams cleaned up


@pytest.mark.asyncio
async def test_a_host_that_cannot_decrypt_hands_drm_items_to_the_owner(tmp_path) -> None:
    from test_download_pipeline import _build_staged_drm_item

    item = _build_staged_drm_item(tmp_path, 8, None)  # no DRM module here, as without mp4decrypt
    owner_side = _OwnerSide(1)  # slower than here, still the only choice
    remote = RemoteStore(
        client=SimpleNamespace(capacity=owner_side.capacity, decrypt=owner_side.decrypt, owner=SimpleNamespace(backend_id="datahoarders")),
        owner_root="/mnt/media",
        local_root=tmp_path,
        selection=None,
    )

    assert await handler._DRMPipeline(1, remote_store=remote)._process(item)
    assert item.offloaded_path == "/mnt/media/library/8.mp4"


@pytest.mark.asyncio
async def test_profile_media_go_to_the_owner_from_a_backend_without_drives(monkeypatch, tmp_path) -> None:
    client = _Client()
    remote = _remote(tmp_path, client)

    class Offload:
        async def destination(self, **kwargs):
            return remote

    class Manager:
        def __init__(self, **kwargs):
            pass

        async def bulk_download(self, items, create_session):
            for item in items:
                item.directory.mkdir(parents=True, exist_ok=True)
                (item.directory / item.filename).write_bytes(b"avatar")

    profile = SimpleNamespace(id=4, avatar_url="https://public.example/files/a/ab/abc/abcdef/avatar.jpg", header_url=None)
    db_manager = SimpleNamespace(get_content=lambda **kwargs: [profile])
    monkeypatch.setattr(handler, "DownloadManager", Manager)
    monkeypatch.setattr(handler, "_resolve_proxy_url", lambda authed, db_manager: None)
    task = SimpleNamespace(user_id=7, site_name="onlyfans", payload=None, task_id="task-1")
    user = SimpleNamespace(get_usernames=lambda: ["tester"])

    result = await handler._handle_profile_download(
        task=task, context=SimpleNamespace(database_writes=None), user=user, db_user=None,
        db_manager=db_manager, authed=None, user_manager=None, config=None, offload=Offload(),
    )

    [(data, root, path)] = client.stored
    assert (data, root) == (b"avatar", "/mnt/media") and path.startswith("OnlyFans/T/tester/Profile/Avatars/")
    [kept] = result.output["download_results"]
    assert kept["status"] == "downloaded" and kept["path"] == f"/mnt/media/{path}"
    assert result.output["files"][0]["path"] == f"/mnt/media/{path}"


class _KeptClient:
    def __init__(self, state) -> None:
        self.state = state
        self.asked = []
        self.stored = []

    async def file_state(self, *, root, path):
        self.asked.append((root, path))
        return self.state

    async def store(self, local, *, root, path):
        self.stored.append((root, path))
        return {"path": f"{root}/{path}"}


def _kept_store(tmp_path, client) -> tuple[RemoteStore, Path]:
    local_root = tmp_path / "mirror"
    local = local_root / "OnlyFans" / "T" / "tester" / "Posts" / "clip.mp4"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"x" * 20)
    selection = UserDirectorySelection(root=local_root, performer_relative_path=Path("OnlyFans/T/tester"))
    return (
        RemoteStore(
            client=client,
            owner_root="/mnt/new",
            local_root=local_root,
            selection=selection,
            kept_root="/mnt/old",
            kept_relative_path="OnlyFansImages/T/tester",
        ),
        local,
    )


@pytest.mark.asyncio
async def test_a_file_the_owner_has_in_its_find_only_folder_is_not_stored_twice(tmp_path) -> None:
    client = _KeptClient({"exists": True, "size": 20})
    remote, local = _kept_store(tmp_path, client)

    path = await remote.keep(local)

    assert path == "/mnt/old/OnlyFansImages/T/tester/Posts/clip.mp4"
    assert client.asked == [("/mnt/old", "OnlyFansImages/T/tester/Posts/clip.mp4")]
    assert client.stored == []
    assert not local.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [{"exists": False, "size": None}, {"exists": True, "size": 19}])
async def test_a_file_the_find_only_folder_lacks_goes_to_the_owners_new_folder(tmp_path, state) -> None:
    client = _KeptClient(state)
    remote, local = _kept_store(tmp_path, client)

    path = await remote.keep(local)

    assert path == "/mnt/new/OnlyFans/T/tester/Posts/clip.mp4"
    assert client.stored == [("/mnt/new", "OnlyFans/T/tester/Posts/clip.mp4")]
