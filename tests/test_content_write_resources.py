"""Actual content writer SQL and race checks in a disposable database."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlmodel import Session

import test_mps_manifest as postgres_fixtures

postgres_engine = postgres_fixtures.postgres_engine


@pytest.fixture(scope="module")
def content_engine(postgres_engine):
    from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates import (
        postgres_site,
    )

    database = "content_" + uuid4().hex
    with postgres_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(text(f"CREATE DATABASE {database}"))
    engine = create_engine(
        postgres_engine.url.set(database=database),
        connect_args={
            "options": "-c search_path=onlyfans,management,public -c statement_timeout=5000",
        },
    )
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA onlyfans"))
            connection.execute(text("CREATE SCHEMA management"))
            connection.execute(text("CREATE EXTENSION pg_trgm WITH SCHEMA public"))
            postgres_site.Base.metadata.create_all(connection)
            connection.execute(text("INSERT INTO onlyfans.users (id) VALUES (7), (99)"))
        yield engine
    finally:
        engine.dispose()
        with postgres_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.execute(text(f"DROP DATABASE {database}"))


@pytest.fixture
def manager(monkeypatch, tmp_path):
    from ultima_scraper_backend.manager import BackendManager

    return BackendManager.__new__(BackendManager)


class FixturePost:
    def __init__(self, identifier, media_ids):
        self.id = identifier
        self.text = "representative post"
        self.price = 0
        self.created_at = datetime(2026, 9, 5, tzinfo=timezone.utc)
        self.media = [
            SimpleNamespace(
                id=identifier,
                type="image",
                size=123,
                duration=None,
                files=None,
                created_at=self.created_at,
            )
            for identifier in media_ids
        ]

    def url_picker(self, media):
        return urlparse(f"https://fixture.invalid/{media.id}")


@pytest.mark.asyncio
async def test_associations_avoid_client_existence_reads_and_rescrape_sequence_churn(
    content_engine, manager, monkeypatch
):
    monkeypatch.setenv("ULTIMA_MEDIA_WRITE_BATCH_SIZE", "7")
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(content_engine, "before_cursor_execute", capture)
    try:
        post = FixturePost(1000, range(2000, 2020))
        with Session(content_engine) as session:
            result = await manager.save_content(post, 7, db_session=session)
            assert result.success, result.message
            session.commit()
        assert not any(
            sql.startswith("SELECT") and "content_media_asso" in sql
            for sql in statements
        )
        assert (
            sum(sql.startswith("INSERT INTO content_media_asso") for sql in statements)
            == 3
        )
        with content_engine.connect() as connection:
            sequence_before = connection.execute(
                text("SELECT last_value FROM onlyfans.content_media_asso_id_seq")
            ).scalar_one()
        with Session(content_engine) as session:
            result = await manager.save_content(post, 7, db_session=session)
            assert result.success, result.message
            session.commit()
        with content_engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM onlyfans.content_media_asso WHERE post_id=1000"
                    )
                ).scalar_one()
                == 20
            )
            assert (
                connection.execute(
                    text("SELECT last_value FROM onlyfans.content_media_asso_id_seq")
                ).scalar_one()
                == sequence_before
            )
    finally:
        event.remove(content_engine, "before_cursor_execute", capture)


def test_concurrent_association_creation_keeps_both_media_saves_successful(
    content_engine, manager
):
    post = FixturePost(3000, [4000, 4001, 4002])
    with content_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO x_posts (id,user_id,created_at) VALUES (3000,7,'2026-09-05')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO media(id,user_id,url,size,category,created_at) "
                "SELECT i,7,'https://fixture.invalid/' || i,123,'image','2026-09-05'::timestamptz "
                "FROM generate_series(4000,4002) i"
            )
        )
    ready = threading.Barrier(2, timeout=3)
    results = []
    errors = []

    def align(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO content_media_asso"):
            ready.wait()

    def save():
        try:
            with Session(content_engine) as session:
                results.append(
                    manager._save_media_for_content(session, post, 7, post.id, "post")
                )
                session.commit()
        except Exception as exc:
            errors.append(exc)

    event.listen(content_engine, "before_cursor_execute", align)
    try:
        threads = [threading.Thread(target=save) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=6)
        assert not any(thread.is_alive() for thread in threads)
        assert not errors
        assert results == [3, 3]
        with content_engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM content_media_asso WHERE post_id=3000")
                ).scalar_one()
                == 3
            )
    finally:
        event.remove(content_engine, "before_cursor_execute", align)


def test_association_failure_keeps_per_media_savepoint_rollback(
    content_engine, manager
):
    post = FixturePost(5000, [6000])  # Parent deliberately absent.
    with Session(content_engine) as session:
        assert manager._save_media_for_content(session, post, 7, 5000, "post") == 0
        session.commit()
        assert (
            session.execute(
                text("SELECT count(*) FROM media WHERE id=6000")
            ).scalar_one()
            == 0
        )
        assert (
            session.execute(
                text("SELECT count(*) FROM content_media_asso WHERE media_id=6000")
            ).scalar_one()
            == 0
        )


def test_conditional_association_lookup_uses_the_existing_pair_index(
    content_engine, manager
):
    with content_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO x_posts(id,user_id,created_at) VALUES (7000,7,'2026-09-05')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO media(id,user_id,category,created_at) "
                "SELECT i,7,'image','2026-09-05'::timestamptz FROM generate_series(100000,199999) i"
            )
        )
        connection.execute(
            text(
                "INSERT INTO content_media_asso(post_id,media_id) "
                "SELECT 7000,i FROM generate_series(100000,199999) i"
            )
        )
        connection.execute(text("ANALYZE content_media_asso"))
    captured = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO content_media_asso"):
            captured.append((statement, parameters))

    event.listen(content_engine, "before_cursor_execute", capture)
    try:
        with Session(content_engine) as session:
            assert (
                manager._save_media_for_content(
                    session,
                    FixturePost(7000, range(199980, 200000)),
                    7,
                    7000,
                    "post",
                    batch_size=20,
                )
                == 20
            )
            session.commit()
    finally:
        event.remove(content_engine, "before_cursor_execute", capture)
    assert len(captured) == 1
    sql, parameters = captured[0]
    with content_engine.begin() as connection:
        plan = connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, parameters
        ).scalar_one()[0]["Plan"]

    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    scans = [
        node
        for node in nodes(plan)
        if "Scan" in node["Node Type"]
        and node.get("Relation Name") == "content_media_asso"
    ]
    assert scans and all("Index" in node["Node Type"] for node in scans), plan
    assert all(node["Actual Rows"] <= 1 for node in scans), plan


@pytest.mark.parametrize("budget", [1, 7, 1000])
def test_media_writer_consumes_one_configured_batch_at_a_time(
    content_engine, manager, monkeypatch, budget
):
    # A large explicit batch remains authoritative over smaller environment values.
    monkeypatch.setenv("ULTIMA_MEDIA_WRITE_BATCH_SIZE", "2")
    monkeypatch.setenv("ULTIMA_CONTENT_BATCH_SIZE", "3")
    post_id = 200000 + budget
    start_id = post_id * 100
    post = FixturePost(post_id, [])
    with content_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO x_posts(id,user_id,created_at) VALUES (:id,7,'2026-09-05')"
            ),
            {"id": post_id},
        )
    produced = 0
    written = 0
    closed = False
    writes = []

    def source():
        nonlocal produced, closed
        try:
            for identifier in range(start_id, start_id + 167):
                produced += 1
                yield FixturePost(post_id, [identifier]).media[0]
        finally:
            closed = True

    post.media = source()

    def observe(conn, cursor, statement, parameters, context, executemany):
        nonlocal written
        if statement.startswith("INSERT INTO content_media_asso"):
            admitted = produced - written
            assert 0 < admitted <= budget
            writes.append(admitted)
            written = produced

    event.listen(content_engine, "before_cursor_execute", observe)
    try:
        with Session(content_engine) as session:
            assert (
                manager._save_media_for_content(
                    session,
                    post,
                    7,
                    post_id,
                    "post",
                    batch_size=budget,
                )
                == 167
            )
            assert not session.new and not session.dirty
            # SQLAlchemy retains no complete history of the streamed media.
            assert len(session.identity_map) <= budget
            session.commit()
    finally:
        event.remove(content_engine, "before_cursor_execute", observe)
    assert closed and produced == written == 167
    assert len(writes) == (167 + budget - 1) // budget


def test_failed_group_retries_valid_media_and_rolls_back_bad_associations(
    content_engine, manager
):
    post = FixturePost(8000, [8100, 21121, 8102])
    for media in post.media:
        media.drm = True
        media.drm_payload = {"dash_manifest": f"https://fixture.invalid/{media.id}.mpd"}
    with content_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO x_posts(id,user_id,created_at) VALUES (8000,7,'2026-09-05')"
            )
        )
        connection.execute(
            text("""
            CREATE FUNCTION reject_fixture_association() RETURNS trigger AS $$
            BEGIN
                IF NEW.media_id = 21121 THEN
                    RAISE EXCEPTION 'fixture media association rejected';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """)
        )
        connection.execute(
            text("""
            CREATE TRIGGER reject_fixture_association
            BEFORE INSERT ON content_media_asso
            FOR EACH ROW EXECUTE FUNCTION reject_fixture_association()
        """)
        )
    try:
        with Session(content_engine) as session:
            assert (
                manager._save_media_for_content(
                    session,
                    post,
                    7,
                    8000,
                    "post",
                    batch_size=3,
                )
                == 2
            )
            session.commit()
            for table in ("media", "drm_manifest", "content_media_asso"):
                column = "id" if table == "media" else "media_id"
                ids = (
                    session.execute(
                        text(
                            f"SELECT {column} FROM {table} WHERE {column} BETWEEN 8100 AND 8102 ORDER BY {column}"
                        )
                    )
                    .scalars()
                    .all()
                )
                assert ids == [8100, 8102], table
    finally:
        with content_engine.begin() as connection:
            connection.execute(
                text("DROP TRIGGER reject_fixture_association ON content_media_asso")
            )
            connection.execute(text("DROP FUNCTION reject_fixture_association()"))


@pytest.mark.asyncio
async def test_batched_rescrape_preserves_media_metadata_and_updates_manifests(
    content_engine, manager, monkeypatch
):
    monkeypatch.setenv("ULTIMA_MEDIA_WRITE_BATCH_SIZE", "10")
    from ultima_scraper_db_archive import DRMManifestModel, MediaModel
    from sqlmodel import select

    post = FixturePost(9000, [9100, 9101])
    post.preview = [9100]
    for media in post.media:
        media.duration = 12
        media.drm = True
        media.drm_payload = {"dash_manifest": "https://fixture.invalid/old.mpd"}
    with Session(content_engine) as session:
        result = await manager.save_content(post, 7, db_session=session)
        assert result.success, result.message
        session.commit()
    post.preview = []
    for media in post.media:
        media.size = None
        media.duration = 99
        media.created_at = datetime(2026, 9, 4, tzinfo=timezone.utc)
        media.drm_payload = {"dash_manifest": "https://fixture.invalid/new.mpd"}
    with Session(content_engine) as session:
        result = await manager.save_content(post, 7, db_session=session)
        assert result.success, result.message
        session.commit()
        for identifier in (9100, 9101):
            saved = session.get(MediaModel, identifier)
            assert saved.size == 123 and saved.duration == 12
            assert saved.preview is (identifier == 9100)
            assert saved.drm is True and saved.user_id == 7
            assert saved.created_at == post.media[0].created_at
        manifests = session.exec(
            select(DRMManifestModel).where(DRMManifestModel.media_id.in_([9100, 9101]))
        ).all()
        assert len(manifests) == 2
        assert all(
            row.dash_manifest == "https://fixture.invalid/new.mpd" for row in manifests
        )


def test_duplicate_media_ids_keep_input_order_and_outer_rollback(
    content_engine, manager
):
    from ultima_scraper_db_archive import MediaModel

    post = FixturePost(10000, [10100, 10100, 10101])
    post.media[1].size = 456
    with content_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO x_posts(id,user_id,created_at) VALUES (10000,7,'2026-09-05')"
            )
        )
    with Session(content_engine) as session:
        assert (
            manager._save_media_for_content(
                session,
                post,
                7,
                10000,
                "post",
                batch_size=3,
            )
            == 3
        )
        assert session.get(MediaModel, 10100).size == 456
        assert (
            session.execute(
                text("SELECT count(*) FROM content_media_asso WHERE post_id=10000")
            ).scalar_one()
            == 2
        )
        session.rollback()
    with content_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM media WHERE id IN (10100,10101)")
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM content_media_asso WHERE post_id=10000")
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "bad"])
def test_invalid_media_batch_budget_fails_before_reading_source(manager, value):
    post = FixturePost(1, [2])
    with pytest.raises(ValueError, match="ULTIMA_MEDIA_WRITE_BATCH_SIZE"):
        manager._save_media_for_content(None, post, 7, 1, "post", batch_size=value)
