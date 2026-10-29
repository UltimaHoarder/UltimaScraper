"""Test BackendManager database integration."""

from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.schema import CreateTable
from sqlmodel import Session, create_engine, select

from ultima_scraper_backend.manager import BackendManager
from ultima_scraper_db_archive import (
    BoughtContentModel,
    ContentMediaAssoModel,
    ContentMentionModel,
    DRMManifestModel,
    LinkedPostModel,
    MassMessageModel,
    MediaModel,
    MessageModel,
    PostModel,
    UserModel,
)


def _require_reachable_postgres(engine: object) -> None:
    """Skip integration-only assertions when the configured Postgres DB is down."""
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1")).scalar()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"requires reachable postgres database: {exc}")


@pytest.fixture
def temp_user_data(monkeypatch, tmp_path, requires_configured_postgres):
    """Create temporary user data directory."""
    user_data = tmp_path / "__user_data__"
    user_data.mkdir()

    # Patch the default user data path
    monkeypatch.chdir(tmp_path)
    return user_data


def test_backend_manager_db_initialization(temp_user_data):
    """BackendManager should initialize site managers for supported runtimes."""
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    assert manager.db_managers is not None
    assert len(manager.db_managers) > 0
    assert "onlyfans" in manager.db_managers
    assert "fansly" in manager.db_managers
    assert manager.multi_site_db_manager is not None


def test_backend_manager_db_managers_are_site_keyed(temp_user_data):
    """Configured managers should remain accessible by lowercase site key."""
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_manager = manager.db_managers.get("onlyfans")
    fansly_manager = manager.db_managers.get("fansly")

    assert onlyfans_manager is not None
    assert onlyfans_manager.site == "onlyfans"
    assert fansly_manager is not None
    assert fansly_manager.site == "fansly"


def test_backend_manager_site_engines_still_available(temp_user_data):
    """Per-site database managers should still expose live engines."""
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_manager = manager.db_managers["onlyfans"]
    assert onlyfans_manager.engine is not None


class _FakeAuthor:
    def __init__(self, site: str) -> None:
        self.site = site

    def get_authed(self):
        return None


class _FakeLinkedUser:
    def __init__(self, user_id: int, username: str) -> None:
        self.id = user_id
        self.username = username
        self.name = username


class _FakePost:
    def __init__(
        self,
        post_id: int,
        *,
        text: str,
        site: str = "onlyfans",
        linked_users: list[object] | None = None,
        linked_posts: list[object] | None = None,
    ) -> None:
        self.id = post_id
        self.text = text
        self.price = 0.0
        self.media = []
        self.created_at = datetime.now(timezone.utc)
        self.isArchived = False
        self.linkedUsers = linked_users or []
        self.linkedPosts = linked_posts or []
        self._author = _FakeAuthor(site)

    def get_author(self):
        return self._author


class _FakeMedia:
    def __init__(
        self,
        media_id: int,
        *,
        media_type: str = "photo",
        created_at: datetime | None = None,
    ) -> None:
        self.id = media_id
        self.type = media_type
        self.canView = True
        self.size = 123
        self.files = None
        self.created_at = created_at


class _FakeMessage:
    def __init__(
        self,
        message_id: int,
        *,
        text: str,
        site: str = "onlyfans",
        media: list[object] | None = None,
        response_type: str | None = None,
        queue_id: int | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.id = message_id
        self.text = text
        self.price = 0.0
        self.paid = True
        self.media = media or []
        self.created_at = created_at or datetime.now(timezone.utc)
        self._author = _FakeAuthor(site)
        if response_type is not None:
            self.responseType = response_type
        if queue_id is not None:
            self.queueId = queue_id

    def get_author(self):
        return self._author

    def url_picker(self, media: object):
        return urlparse(f"https://example.com/media/{getattr(media, 'id', 'unknown')}")

    def preview_url_picker(self, media: object):
        return self.url_picker(media)


class _FakePreviewMessage(_FakeMessage):
    def preview_url_picker(self, media: object):
        return urlparse(
            f"https://example.com/media/{getattr(media, 'id', 'unknown')}/preview"
        )


class _FakeMassMessage:
    def __init__(
        self,
        mass_message_id: int,
        *,
        text: str,
        site: str = "onlyfans",
        media_count: int = 0,
    ) -> None:
        self.id = mass_message_id
        self.text = text
        self.price = 0.0
        self.media_count = media_count
        self.created_at = datetime.now(timezone.utc)
        self.expires_at = datetime.now(timezone.utc)
        self._author = _FakeAuthor(site)

    def get_author(self):
        return self._author


@pytest.mark.asyncio
async def test_new_content_insert_saves_post() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE x_posts (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
                "text TEXT, price REAL DEFAULT 0, deleted BOOL DEFAULT 0, "
                "archived BOOL DEFAULT 0, paid BOOL, media_count INTEGER DEFAULT 0, "
                "expires_at DATETIME, created_at DATETIME NOT NULL, external_id TEXT)"
            )
        )
        # The post path ensures the owner row; no PostgreSQL-only indexes here.
        connection.execute(CreateTable(UserModel.__table__))

    manager = object.__new__(BackendManager)
    post = _FakePost(808, text="authoritative insert")
    with Session(engine) as session:
        result = await manager.save_content(
            post,
            42,
            site="onlyfans",
            db_session=session,
        )
        assert result.success, result.message
        session.commit()
        assert session.get(PostModel, 808) is not None


@pytest.mark.asyncio
async def test_save_content_keeps_linked_post_and_user_writes_in_shared_session(
    temp_user_data,
):
    """Saving posts inside a shared nested session should keep link writes usable."""
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 101
    linked_user_id = 202
    linked_post_id = 303
    outer_post_id = 404

    onlyfans_db.create_or_update_user({"id": creator_id, "username": "creator"})

    linked_post = _FakePost(linked_post_id, text="linked post")
    outer_post = _FakePost(
        outer_post_id,
        text="outer post",
        linked_users=[_FakeLinkedUser(linked_user_id, "linked-user")],
        linked_posts=[linked_post],
    )

    assert onlyfans_db.engine is not None
    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                outer_post,
                creator_id,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    with Session(onlyfans_db.engine) as session:
        assert session.get(PostModel, outer_post_id) is not None
        assert session.get(PostModel, linked_post_id) is not None
        assert session.get(UserModel, linked_user_id) is not None

        linked_user_row = session.exec(
            select(ContentMentionModel).where(
                ContentMentionModel.post_id == outer_post_id,
                ContentMentionModel.mentioned_user_id == linked_user_id,
            )
        ).first()
        linked_post_row = session.exec(
            select(LinkedPostModel).where(
                LinkedPostModel.post_id == outer_post_id,
                LinkedPostModel.linked_post_id == linked_post_id,
            )
        ).first()

        assert linked_user_row is not None
        assert linked_post_row is not None


@pytest.mark.asyncio
async def test_save_content_keeps_message_media_writes_in_shared_session(
    temp_user_data,
):
    """Saving messages with media inside a nested session should not close it early."""
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 10_101
    message_id = 10_202
    media_id = 10_303

    onlyfans_db.create_or_update_user({"id": creator_id, "username": "msg-creator"})

    message = _FakeMessage(
        message_id,
        text="paid message",
        media=[_FakeMedia(media_id)],
    )

    assert onlyfans_db.engine is not None
    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                message,
                creator_id,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    with Session(onlyfans_db.engine) as session:
        assert session.get(MessageModel, message_id) is not None
        assert session.get(MediaModel, media_id) is not None

        media_link = session.exec(
            select(ContentMediaAssoModel).where(
                ContentMediaAssoModel.message_id == message_id,
                ContentMediaAssoModel.media_id == media_id,
            )
        ).first()

        assert media_link is not None


@pytest.mark.asyncio
async def test_save_content_media_created_at_prefers_existing_earliest_and_falls_back_to_content(
    temp_user_data,
):
    """Media created_at should use content.created_at when missing and only move earlier."""
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 10_401
    message_id = 10_402
    media_id = 10_403
    content_created_at = datetime(2026, 3, 12, 18, 0, tzinfo=timezone.utc)
    later_content_created_at = datetime(2026, 3, 12, 19, 0, tzinfo=timezone.utc)
    earlier_media_created_at = datetime(2026, 3, 12, 17, 30, tzinfo=timezone.utc)

    onlyfans_db.create_or_update_user({"id": creator_id, "username": "media-created"})

    first_message = _FakeMessage(
        message_id,
        text="message one",
        media=[_FakeMedia(media_id, created_at=None)],
        created_at=content_created_at,
    )
    second_message = _FakeMessage(
        message_id,
        text="message two",
        media=[_FakeMedia(media_id, created_at=None)],
        created_at=later_content_created_at,
    )
    third_message = _FakeMessage(
        message_id,
        text="message three",
        media=[_FakeMedia(media_id, created_at=earlier_media_created_at)],
        created_at=later_content_created_at,
    )

    assert onlyfans_db.engine is not None
    for message in (first_message, second_message, third_message):
        with Session(onlyfans_db.engine) as session:
            with session.begin_nested():
                result = await manager.save_content(
                    message,
                    creator_id,
                    db_session=session,
                )
                assert result.success, result.message
            session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_media = session.get(MediaModel, media_id)
        assert saved_media is not None
        assert saved_media.created_at == earlier_media_created_at


@pytest.mark.asyncio
async def test_save_content_marks_preview_media_in_db_without_downgrading_url(
    temp_user_data,
):
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 10_411
    message_id = 10_412
    media_id = 10_413

    onlyfans_db.create_or_update_user({"id": creator_id, "username": "preview-ids"})

    media = _FakeMedia(media_id)
    media.canView = True
    message = _FakePreviewMessage(
        message_id,
        text="message with preview ids",
        media=[media],
    )
    message.previews = [media_id]

    assert onlyfans_db.engine is not None
    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                message,
                creator_id,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_media = session.get(MediaModel, media_id)
        assert saved_media is not None
        assert saved_media.preview is True
        assert saved_media.url == f"https://example.com/media/{media_id}"


@pytest.mark.asyncio
async def test_save_content_marks_preview_only_media_without_downgrading_url(
    temp_user_data,
):
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 10_416
    message_id = 10_417
    media_id = 10_418

    onlyfans_db.create_or_update_user({"id": creator_id, "username": "preview-only"})

    media = _FakeMedia(media_id)
    media.canView = False
    message = _FakePreviewMessage(
        message_id,
        text="message with preview-only media",
        media=[media],
    )
    message.previews = [media_id]

    assert onlyfans_db.engine is not None
    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                message,
                creator_id,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_media = session.get(MediaModel, media_id)
        assert saved_media is not None
        assert saved_media.preview is True
        assert saved_media.url == f"https://example.com/media/{media_id}"


@pytest.mark.asyncio
async def test_save_content_promotes_existing_media_to_preview_when_seen_later(
    temp_user_data,
):
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 10_421
    message_id = 10_422
    media_id = 10_423

    onlyfans_db.create_or_update_user(
        {"id": creator_id, "username": "preview-promote-later"}
    )

    media = _FakeMedia(media_id)
    media.canView = True
    full_message = _FakePreviewMessage(
        message_id,
        text="full media first",
        media=[media],
    )
    preview_message = _FakePreviewMessage(
        message_id,
        text="preview scrape later",
        media=[media],
    )
    preview_message.previews = [media_id]

    assert onlyfans_db.engine is not None
    for message in (full_message, preview_message):
        with Session(onlyfans_db.engine) as session:
            with session.begin_nested():
                result = await manager.save_content(
                    message,
                    creator_id,
                    db_session=session,
                )
                assert result.success, result.message
            session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_media = session.get(MediaModel, media_id)
        assert saved_media is not None
        assert saved_media.preview is True
        assert saved_media.url == f"https://example.com/media/{media_id}"


@pytest.mark.asyncio
async def test_save_content_keeps_existing_preview_media_preview(
    temp_user_data,
):
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 10_431
    message_id = 10_432
    media_id = 10_433

    onlyfans_db.create_or_update_user(
        {"id": creator_id, "username": "preview-sticky-true"}
    )

    media = _FakeMedia(media_id)
    preview_message = _FakePreviewMessage(
        message_id,
        text="preview media first",
        media=[media],
    )
    preview_message.previews = [media_id]
    full_message = _FakePreviewMessage(
        message_id,
        text="full media later",
        media=[media],
    )

    assert onlyfans_db.engine is not None
    for message in (preview_message, full_message):
        with Session(onlyfans_db.engine) as session:
            with session.begin_nested():
                result = await manager.save_content(
                    message,
                    creator_id,
                    db_session=session,
                )
                assert result.success, result.message
            session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_media = session.get(MediaModel, media_id)
        assert saved_media is not None
        assert saved_media.preview is True
        assert saved_media.url == f"https://example.com/media/{media_id}"


@pytest.mark.asyncio
async def test_save_content_persists_mass_message_model(
    temp_user_data,
):
    """Mass message parents should save into x_mass_messages."""
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 91_900_001
    mass_message_id = 91_900_002

    onlyfans_db.create_or_update_user({"id": creator_id, "username": "mass-creator"})

    mass_message = _FakeMassMessage(
        mass_message_id,
        text="mass parent",
        media_count=3,
    )

    assert onlyfans_db.engine is not None
    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                mass_message,
                creator_id,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_mass_message = session.get(MassMessageModel, mass_message_id)
        assert saved_mass_message is not None
        assert saved_mass_message.user_id == creator_id
        assert saved_mass_message.media_count == 3


@pytest.mark.asyncio
async def test_save_content_persists_drm_manifest_for_media(
    temp_user_data,
):
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 91_910_001
    message_id = 91_910_002
    media_id = 91_910_003

    onlyfans_db.create_or_update_user({"id": creator_id, "username": "drm-creator"})

    media = _FakeMedia(media_id, media_type="video")
    media.files = SimpleNamespace(
        full=None,
        drm=SimpleNamespace(
            dash=SimpleNamespace(
                manifest_url="https://cdn3.onlyfans.com/dash/files/a/b/example.mpd",
                key_pair_id="dash-key",
                policy="dash-policy",
                signature="dash-signature",
            ),
            hls=SimpleNamespace(
                manifest_url="https://cdn3.onlyfans.com/hls/files/a/b/example.m3u8",
                key_pair_id="hls-key",
                policy="hls-policy",
                signature="hls-signature",
            ),
        ),
    )
    message = _FakeMessage(
        message_id,
        text="drm message",
        media=[media],
    )

    assert onlyfans_db.engine is not None
    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                message,
                creator_id,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_media = session.get(MediaModel, media_id)
        saved_manifest = session.exec(
            select(DRMManifestModel).where(DRMManifestModel.media_id == media_id)
        ).first()

        assert saved_media is not None
        assert saved_media.drm is True
        assert saved_manifest is not None
        assert saved_manifest.dash_manifest == media.files.drm.dash.manifest_url
        assert saved_manifest.dash_key_pair_id == media.files.drm.dash.key_pair_id
        assert saved_manifest.hls_manifest == media.files.drm.hls.manifest_url


@pytest.mark.asyncio
async def test_save_content_refreshes_existing_drm_manifest_from_media_object(
    temp_user_data,
):
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 91_920_001
    buyer_id = 91_920_002
    message_id = 91_920_003
    media_id = 91_920_004

    onlyfans_db.create_or_update_user(
        {"id": creator_id, "username": "paid-drm-creator"}
    )

    initial_media = _FakeMedia(media_id, media_type="video")
    initial_media.files = SimpleNamespace(
        full=None,
        drm=SimpleNamespace(
            dash=SimpleNamespace(
                manifest_url="https://cdn3.onlyfans.com/dash/files/a/b/original.mpd",
                key_pair_id="dash-key-old",
                policy="dash-policy-home-ip",
                signature="dash-signature-old",
            ),
            hls=SimpleNamespace(
                manifest_url="https://cdn3.onlyfans.com/hls/files/a/b/original.m3u8",
                key_pair_id="hls-key-old",
                policy="hls-policy-home-ip",
                signature="hls-signature-old",
            ),
        ),
    )
    refreshed_media = _FakeMedia(media_id, media_type="video")
    refreshed_media.files = SimpleNamespace(
        full=None,
        drm=SimpleNamespace(
            dash=SimpleNamespace(
                manifest_url="https://cdn3.onlyfans.com/dash/files/a/b/refreshed.mpd",
                key_pair_id="dash-key-proxy",
                policy="dash-policy-proxy-ip",
                signature="dash-signature-proxy",
            ),
            hls=SimpleNamespace(
                manifest_url="https://cdn3.onlyfans.com/hls/files/a/b/refreshed.m3u8",
                key_pair_id="hls-key-proxy",
                policy="hls-policy-proxy-ip",
                signature="hls-signature-proxy",
            ),
        ),
    )

    initial_message = _FakeMessage(
        message_id,
        text="paid drm message",
        media=[initial_media],
        response_type="message",
    )
    refreshed_message = _FakeMessage(
        message_id,
        text="paid drm message refreshed",
        media=[refreshed_media],
        response_type="message",
    )

    assert onlyfans_db.engine is not None
    for message in (initial_message, refreshed_message):
        with Session(onlyfans_db.engine) as session:
            with session.begin_nested():
                result = await manager.save_content(
                    message,
                    creator_id,
                    auth_user_id=buyer_id,
                    db_session=session,
                )
                assert result.success, result.message
            session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_media = session.get(MediaModel, media_id)
        saved_manifest = session.exec(
            select(DRMManifestModel).where(DRMManifestModel.media_id == media_id)
        ).first()

        assert saved_media is not None
        assert saved_media.drm is True
        assert saved_manifest is not None
        assert (
            saved_manifest.dash_manifest == refreshed_media.files.drm.dash.manifest_url
        )
        assert (
            saved_manifest.dash_key_pair_id
            == refreshed_media.files.drm.dash.key_pair_id
        )
        assert saved_manifest.dash_policy == refreshed_media.files.drm.dash.policy
        assert saved_manifest.dash_signature == refreshed_media.files.drm.dash.signature
        assert saved_manifest.hls_manifest == refreshed_media.files.drm.hls.manifest_url
        assert (
            saved_manifest.hls_key_pair_id == refreshed_media.files.drm.hls.key_pair_id
        )
        assert saved_manifest.hls_policy == refreshed_media.files.drm.hls.policy
        assert saved_manifest.hls_signature == refreshed_media.files.drm.hls.signature


@pytest.mark.asyncio
async def test_save_content_refreshes_existing_drm_manifest_from_raw_media_payload(
    temp_user_data,
):
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 91_930_001
    buyer_id = 91_930_002
    message_id = 91_930_003
    media_id = 91_930_004

    onlyfans_db.create_or_update_user(
        {"id": creator_id, "username": "paid-drm-raw-refresh-creator"}
    )

    initial_media = _FakeMedia(media_id, media_type="video")
    initial_media.files = SimpleNamespace(
        full=None,
        drm=SimpleNamespace(
            dash=SimpleNamespace(
                manifest_url="https://cdn3.onlyfans.com/dash/files/a/b/original-raw.mpd",
                key_pair_id="dash-key-old",
                policy="dash-policy-home-ip",
                signature="dash-signature-old",
            ),
            hls=SimpleNamespace(
                manifest_url="https://cdn3.onlyfans.com/hls/files/a/b/original-raw.m3u8",
                key_pair_id="hls-key-old",
                policy="hls-policy-home-ip",
                signature="hls-signature-old",
            ),
        ),
    )

    refreshed_media = _FakeMedia(media_id, media_type="video")
    refreshed_media.files = None
    refreshed_media.__raw__ = {
        "files": {
            "drm": {
                "manifest": {
                    "dash": "https://cdn3.onlyfans.com/dash/files/a/b/refreshed-raw.mpd",
                    "hls": "https://cdn3.onlyfans.com/hls/files/a/b/refreshed-raw.m3u8",
                },
                "signature": {
                    "dash": {
                        "CloudFront-Key-Pair-Id": "dash-key-proxy",
                        "CloudFront-Policy": "dash-policy-proxy-ip",
                        "CloudFront-Signature": "dash-signature-proxy",
                    },
                    "hls": {
                        "CloudFront-Key-Pair-Id": "hls-key-proxy",
                        "CloudFront-Policy": "hls-policy-proxy-ip",
                        "CloudFront-Signature": "hls-signature-proxy",
                    },
                },
            }
        }
    }

    initial_message = _FakeMessage(
        message_id,
        text="paid drm message",
        media=[initial_media],
        response_type="message",
    )
    refreshed_message = _FakeMessage(
        message_id,
        text="paid drm message refreshed from raw",
        media=[refreshed_media],
        response_type="message",
    )

    assert onlyfans_db.engine is not None
    for message in (initial_message, refreshed_message):
        with Session(onlyfans_db.engine) as session:
            with session.begin_nested():
                result = await manager.save_content(
                    message,
                    creator_id,
                    auth_user_id=buyer_id,
                    db_session=session,
                )
                assert result.success, result.message
            session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_media = session.get(MediaModel, media_id)
        saved_manifest = session.exec(
            select(DRMManifestModel).where(DRMManifestModel.media_id == media_id)
        ).first()

        assert saved_media is not None
        assert saved_media.drm is True
        assert saved_manifest is not None
        assert (
            saved_manifest.dash_manifest
            == refreshed_media.__raw__["files"]["drm"]["manifest"]["dash"]
        )
        assert saved_manifest.dash_key_pair_id == "dash-key-proxy"
        assert saved_manifest.dash_policy == "dash-policy-proxy-ip"
        assert saved_manifest.dash_signature == "dash-signature-proxy"
        assert (
            saved_manifest.hls_manifest
            == refreshed_media.__raw__["files"]["drm"]["manifest"]["hls"]
        )
        assert saved_manifest.hls_key_pair_id == "hls-key-proxy"
        assert saved_manifest.hls_policy == "hls-policy-proxy-ip"
        assert saved_manifest.hls_signature == "hls-signature-proxy"


@pytest.mark.asyncio
async def test_update_drm_stream_urls_persists_stream_sizes(temp_user_data):
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 91_940_001
    message_id = 91_940_002
    media_id = 91_940_003

    onlyfans_db.create_or_update_user(
        {"id": creator_id, "username": "drm-stream-size-creator"}
    )

    media = _FakeMedia(media_id, media_type="video")
    media.files = SimpleNamespace(
        full=None,
        drm=SimpleNamespace(
            dash=SimpleNamespace(
                manifest_url="https://cdn3.onlyfans.com/dash/files/a/b/size-test.mpd",
                key_pair_id="dash-key",
                policy="dash-policy",
                signature="dash-signature",
            ),
            hls=SimpleNamespace(
                manifest_url="https://cdn3.onlyfans.com/hls/files/a/b/size-test.m3u8",
                key_pair_id="hls-key",
                policy="hls-policy",
                signature="hls-signature",
            ),
        ),
    )
    message = _FakeMessage(
        message_id,
        text="drm sizes",
        media=[media],
    )

    assert onlyfans_db.engine is not None
    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                message,
                creator_id,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    assert onlyfans_db.update_drm_stream_urls(
        media_id,
        "https://video.example/stream.mp4",
        "https://audio.example/stream.mp4",
        video_size=987654,
        audio_size=123456,
    )

    with Session(onlyfans_db.engine) as session:
        saved_manifest = session.exec(
            select(DRMManifestModel).where(DRMManifestModel.media_id == media_id)
        ).first()

        assert saved_manifest is not None
        assert saved_manifest.video_url == "https://video.example/stream.mp4"
        assert saved_manifest.audio_url == "https://audio.example/stream.mp4"
        assert saved_manifest.video_size == 987654
        assert saved_manifest.audio_size == 123456


@pytest.mark.asyncio
async def test_save_content_creates_bought_content_and_receiver_for_paid_messages(
    temp_user_data,
):
    """Paid message saves should link buyer/supplier rows and populate receiver_id."""
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 92_001_001
    buyer_id = 92_001_002
    message_id = 92_001_003

    onlyfans_db.create_or_update_user(
        {"id": creator_id, "username": "paid-message-creator"}
    )

    message = _FakeMessage(
        message_id,
        text="paid message for bought content",
        response_type="message",
    )

    assert onlyfans_db.engine is not None
    for _ in range(2):
        with Session(onlyfans_db.engine) as session:
            with session.begin_nested():
                result = await manager.save_content(
                    message,
                    creator_id,
                    auth_user_id=buyer_id,
                    record_bought_content=True,
                    db_session=session,
                )
                assert result.success, result.message
            session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_message = session.get(MessageModel, message_id)
        assert saved_message is not None
        assert saved_message.receiver_id == buyer_id
        assert session.get(UserModel, buyer_id) is not None

        purchases = session.exec(
            select(BoughtContentModel).where(
                BoughtContentModel.buyer_id == buyer_id,
                BoughtContentModel.message_id == message_id,
            )
        ).all()

        assert len(purchases) == 1
        assert purchases[0].supplier_id == creator_id


@pytest.mark.asyncio
async def test_save_content_does_not_create_bought_content_for_normal_message_saves(
    temp_user_data,
):
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 92_001_101
    auth_id = 92_001_102
    message_id = 92_001_103

    onlyfans_db.create_or_update_user(
        {"id": creator_id, "username": "normal-message-creator"}
    )

    message = _FakeMessage(
        message_id,
        text="normal message should not be bought content",
        response_type="message",
    )

    assert onlyfans_db.engine is not None
    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                message,
                creator_id,
                auth_user_id=auth_id,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_message = session.get(MessageModel, message_id)
        assert saved_message is not None
        assert saved_message.receiver_id == auth_id

        purchases = session.exec(
            select(BoughtContentModel).where(
                BoughtContentModel.buyer_id == auth_id,
                BoughtContentModel.message_id == message_id,
            )
        ).all()

        assert purchases == []


@pytest.mark.asyncio
async def test_save_content_keeps_paid_status_true_once_confirmed(
    temp_user_data,
):
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 92_001_201
    buyer_id = 92_001_202
    message_id = 92_001_203

    onlyfans_db.create_or_update_user(
        {"id": creator_id, "username": "paid-sticky-creator"}
    )

    bought_message = _FakeMessage(
        message_id,
        text="bought first",
        response_type="message",
    )
    bought_message.paid = None

    later_locked_view = _FakeMessage(
        message_id,
        text="later scrape looked locked",
        response_type="message",
    )
    later_locked_view.paid = False

    assert onlyfans_db.engine is not None
    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                bought_message,
                creator_id,
                auth_user_id=buyer_id,
                record_bought_content=True,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                later_locked_view,
                creator_id,
                auth_user_id=buyer_id,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_message = session.get(MessageModel, message_id)
        assert saved_message is not None
        assert saved_message.paid is True


@pytest.mark.asyncio
async def test_save_content_ignores_missing_mass_message_queue_reference(
    temp_user_data,
):
    """Messages should save even when queueId points to an unseen mass message."""
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 92_002_001
    buyer_id = 92_002_002
    message_id = 92_002_003
    missing_queue_id = 92_002_004

    onlyfans_db.create_or_update_user({"id": creator_id, "username": "queue-creator"})

    message = _FakeMessage(
        message_id,
        text="queue linked message",
        response_type="message",
        queue_id=missing_queue_id,
    )

    assert onlyfans_db.engine is not None
    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                message,
                creator_id,
                auth_user_id=buyer_id,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_message = session.get(MessageModel, message_id)
        assert saved_message is not None
        assert saved_message.queue_id is None


@pytest.mark.asyncio
async def test_save_content_keeps_existing_mass_message_queue_reference(
    temp_user_data,
):
    """Messages should retain queue_id when the referenced mass message exists."""
    manager = BackendManager(
        auto_create=True,
        enable_redis=False,
    )

    onlyfans_db = manager.db_managers["onlyfans"]
    onlyfans_db.auto_create = True
    _require_reachable_postgres(onlyfans_db.engine)
    creator_id = 92_003_001
    buyer_id = 92_003_002
    queue_id = 92_003_003
    message_id = 92_003_004

    onlyfans_db.create_or_update_user(
        {"id": creator_id, "username": "queue-parent-creator"}
    )

    assert onlyfans_db.engine is not None
    with Session(onlyfans_db.engine) as session:
        session.add(
            MassMessageModel(
                id=queue_id,
                user_id=creator_id,
                text="parent mass message",
                price=19.99,
                media_count=0,
                expires_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    message = _FakeMessage(
        message_id,
        text="queue linked message with parent",
        response_type="message",
        queue_id=queue_id,
    )

    with Session(onlyfans_db.engine) as session:
        with session.begin_nested():
            result = await manager.save_content(
                message,
                creator_id,
                auth_user_id=buyer_id,
                db_session=session,
            )
            assert result.success, result.message
        session.commit()

    with Session(onlyfans_db.engine) as session:
        saved_message = session.get(MessageModel, message_id)
        assert saved_message is not None
        assert saved_message.queue_id == queue_id
