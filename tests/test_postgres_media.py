import os
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import pytest
from types import SimpleNamespace
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from ultima_scraper_backend.content_persistence import (
    _resolve_usapi_media_duration,
    _resolve_usapi_media_size,
)
from ultima_scraper_backend.manager import BackendManager
from ultima_scraper_db_archive import (
    ContentMediaAssoModel,
    MediaModel,
    PostModel,
    UserModel,
)
from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates.postgres_site import (
    metadata_obj,
)


class DummyMedia:
    def __init__(self, media_id: int):
        self.id = media_id
        self.type = "video"
        self.size = 1024
        self.duration = 42.75

    def has_drm(self) -> bool:
        return False


class DummyFullFile:
    def __init__(self, size: int | None):
        self.size = size


class DummyFiles:
    def __init__(self, size: int | None):
        self.full = DummyFullFile(size)


class DummySizedMedia:
    def __init__(self, top_level_size: int | None, nested_size: int | None):
        self.size = top_level_size
        self.files = DummyFiles(nested_size)


class DummyContent:
    def __init__(self, medias: list[DummyMedia]):
        self.media = medias
        self.created_at = datetime.now(timezone.utc)
        # previews list may be used by _save_media_for_content
        self.previews: list[int] = []

    def url_picker(self, media: DummyMedia):
        # always return a simple URL
        return urlparse(f"https://example.com/{media.id}")

    def preview_url_picker(self, media: DummyMedia):
        return urlparse(f"https://example.com/{media.id}/preview")

    def get_previews(self):
        return []


class DummySession:
    def __init__(self, existing_media: MediaModel | None = None):
        self.existing_media = existing_media
        self.added: list[object] = []
        self.executed: list[tuple[str, object]] = []

    def begin_nested(self):
        return nullcontext()

    def get(self, model: type[object], media_id: int):
        return self.existing_media

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        pass

    def exec(self, statement: object):
        # The writer loads existing media in one SELECT and iterates the rows;
        # every other lookup (DRM manifests, AI provenance) finds nothing here.
        descriptions = getattr(statement, "column_descriptions", None) or [{}]
        is_media_select = descriptions[0].get("entity") is MediaModel
        rows = [self.existing_media] if is_media_select and self.existing_media else []
        return _Rows(rows)

    def get_bind(self):
        # Not PostgreSQL: provenance checks use their portable path.
        return SimpleNamespace(dialect=SimpleNamespace(name="fixture"))

    def execute(self, statement: object, params: object = None):
        self.executed.append((str(statement), params))
        return _Rows([])


class _Rows(list):
    def first(self):
        return self[0] if self else None

    def close(self) -> None:
        pass


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="requires postgres database")
def test_save_media_to_postgres():
    """Regression: media items should be written when using PostgreSQL backend.

    Previously hardcoded imports from ``dbmini.site`` caused the SQLite model
    to be used even when DATABASE_URL pointed at Postgres.  The upsert would
    silently fail (caught by the generic exception) and no media rows were
    created.  This test exercises the exact helper and verifies a row exists.
    """

    base_url = os.getenv("DATABASE_URL")
    if not base_url:
        pytest.skip("requires postgres database")
    schema = "test_media_" + uuid.uuid4().hex[:8]

    probe_engine = create_engine(base_url)
    try:
        with probe_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"requires reachable postgres database: {exc}")
    finally:
        probe_engine.dispose()

    # inject search_path via connection options (same technique as
    # PostgreSQLDatabaseManager.connect)
    parsed = urlparse(base_url)
    qs = parse_qs(parsed.query)
    qs["options"] = [f"-c search_path={schema},public"]
    new_query = urlencode(qs, doseq=True)
    conn_str = urlunparse(parsed._replace(query=new_query))

    engine = create_engine(conn_str)

    # create the schema and install tables
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        conn.commit()
        # narrow search_path so metadata goes into our schema
        conn.execute(text(f"SET search_path TO {schema}"))
        metadata_obj.create_all(conn)
        conn.commit()

    media_id = 2289870111
    user_id = 42
    content_id = 999

    with Session(engine) as session:
        content = DummyContent([DummyMedia(media_id)])
        session.add(UserModel(id=user_id))
        session.flush()
        session.add(
            PostModel(
                id=content_id,
                user_id=user_id,
                created_at=content.created_at,
            )
        )
        session.flush()

        # ensure nothing already present
        assert (
            session.exec(select(MediaModel).where(MediaModel.id == media_id)).first()
            is None
        )

        manager = object.__new__(BackendManager)
        saved = manager._save_media_for_content(
            session, content, user_id, content_id, "post"
        )
        assert saved == 1, "_save_media_for_content returned wrong count"
        session.commit()

        db_media = session.exec(
            select(MediaModel).where(MediaModel.id == media_id)
        ).first()
        assert db_media is not None, "media row was not inserted"
        assert db_media.duration == 42.75
        association = session.exec(
            select(ContentMediaAssoModel).where(
                ContentMediaAssoModel.media_id == media_id
            )
        ).first()
        assert association is not None
        assert association.post_id == content_id


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="PostgreSQL required")
def test_package_imports_use_postgres_model():
    """Ensure ``from ultima_scraper_db_archive import MediaModel`` returns the
    PostgreSQL variant when a DATABASE_URL is configured.
    """

    # direct import of the sqlite/"site" module should differ
    import importlib

    from ultima_scraper_db_archive import MediaModel as root_model
    from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates.postgres_site import (
        MediaModel as pg_model,
    )

    site_mod = importlib.import_module("ultima_scraper_db_archive.site")
    assert root_model is pg_model
    assert root_model is not site_mod.MediaModel


def test_resolve_usapi_media_size_prefers_positive_values() -> None:
    assert _resolve_usapi_media_size(DummySizedMedia(2048, 4096)) == 2048
    assert _resolve_usapi_media_size(DummySizedMedia(0, 4096)) == 4096
    assert (
        _resolve_usapi_media_size({"size": None, "files": {"full": {"size": 512}}})
        == 512
    )


def test_resolve_usapi_media_size_ignores_zero_and_null() -> None:
    assert _resolve_usapi_media_size(DummySizedMedia(0, None)) is None
    assert (
        _resolve_usapi_media_size({"size": 0, "files": {"full": {"size": 0}}}) is None
    )


def test_resolve_usapi_media_duration_accepts_objects_and_mappings() -> None:
    assert _resolve_usapi_media_duration(DummyMedia(1)) == 42.75
    assert _resolve_usapi_media_duration({"duration": "125.5"}) == 125.5


def test_save_media_for_content_persists_and_backfills_duration() -> None:
    manager = object.__new__(BackendManager)
    content = DummyContent([DummyMedia(101)])
    new_session = DummySession()

    assert manager._save_media_for_content(new_session, content, 42, 99, "post") == 1
    association = next(params for sql, params in new_session.executed if "content_media_asso" in sql)
    assert association == {"media_ids": [101], "content_id": 99}
    inserted_media = next(
        value for value in new_session.added if isinstance(value, MediaModel)
    )
    assert inserted_media.duration == 42.75

    existing_media = MediaModel(
        id=101,
        user_id=42,
        category="video",
        preview=False,
        duration=None,
    )
    existing_session = DummySession(existing_media)

    assert (
        manager._save_media_for_content(existing_session, content, 42, 99, "post") == 1
    )
    assert existing_media.duration == 42.75


def test_new_media_insert_saves_media() -> None:
    manager = object.__new__(BackendManager)
    assert (
        manager._save_media_for_content(
            DummySession(),
            DummyContent([DummyMedia(303)]),
            42,
            99,
            "post",
        )
        == 1
    )


@pytest.mark.parametrize("duration", [None, 0, -1, "invalid", float("inf")])
def test_resolve_usapi_media_duration_ignores_invalid_values(duration: object) -> None:
    assert _resolve_usapi_media_duration({"duration": duration}) is None
