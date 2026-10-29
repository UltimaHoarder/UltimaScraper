"""Selection transactions and paging against an owned disposable PostgreSQL."""

from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import test_mps_manifest as postgres_fixtures
from ultima_scraper_backend.database.media_selection import MediaSelectionStore
from ultima_scraper_db_archive.global_db import (
    TaskMediaEvidenceModel,
    TaskMediaPlanModel,
    TaskMediaSelectionModel,
)

postgres_engine = postgres_fixtures.postgres_engine


@pytest.fixture(scope="module")
def media_engine(postgres_engine):
    from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates import (
        postgres_site as models,
    )

    with postgres_engine.begin() as connection:
        connection.execute(text("SET LOCAL search_path = onlyfans, management, public"))
        connection.execute(
            text("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
        )
        for model in (
            TaskMediaPlanModel,
            TaskMediaSelectionModel,
            TaskMediaEvidenceModel,
            models.MediaModel,
            models.MediaUrlModel,
            models.DRMManifestModel,
            models.StoryModel,
            models.PostModel,
            models.MassMessageModel,
            models.MessageModel,
            models.ContentMediaAssoModel,
        ):
            model.__table__.create(connection)
        connection.execute(
            text("INSERT INTO onlyfans.users(id) VALUES (7), (8), (99), (100)")
        )
    return postgres_engine


@pytest.fixture
def store(media_engine):
    @contextmanager
    def sessions():
        with Session(media_engine) as session:
            session.execute(
                text("SET LOCAL search_path = onlyfans, management, public")
            )
            yield session

    return MediaSelectionStore(sessions)


def spec():
    return dict(
        selection_id=uuid4().hex,
        job_id=uuid4().hex,
        task_id=uuid4().hex,
        site="onlyfans",
        auth_id=99,
    )


def content(identifier, media_id, url, *, created="2026-09-01T00:00:00+00:00"):
    return {
        "id": identifier,
        "user_id": 7,
        "created_at": created,
        "media": [{"id": media_id, "url": url, "drm_payload": {}}],
    }


def test_selection_commit_deduplication_scope_and_immutable_publication(store):
    plan = spec()
    with store.session_factory() as session:
        store.add_content(session, plan, [content(10, 20, "https://old")], "Posts")
        session.rollback()
    with pytest.raises(ValueError, match="unavailable"):
        store.scope(plan["selection_id"], job_id=plan["job_id"])
    with store.session_factory() as session:
        store.add_content(session, plan, [content(10, 20, "https://old")], "Posts")
        store.add_content(
            session,
            plan,
            [content(11, 20, "https://new", created="2026-09-02T00:00:00+00:00")],
            "Posts",
        )
        store.add_content(
            session, plan, [content(9, 20, "https://fresh-for-proxy")], "Posts"
        )
        result = store.seal(session, plan)
        session.commit()
    assert result["total"] == 1
    rows = store.media_page(
        plan["selection_id"],
        user_id=7,
        content_type="posts",
        after=0,
        limit=10,
        max_bytes=4096,
    )
    assert rows[0]["content_id"] == 11
    assert rows[0]["url"] == "https://fresh-for-proxy"
    with (
        store.session_factory() as session,
        pytest.raises(ValueError, match="immutable"),
    ):
        store.add_content(session, plan, [content(12, 21, "https://late")], "Posts")
    with pytest.raises(ValueError, match="scope"):
        store.scope(plan["selection_id"], job_id=plan["job_id"], auth_id=100)
    with pytest.raises(ValueError, match="scope"):
        store.scope(plan["selection_id"], job_id=plan["job_id"], task_id="other")


def test_paid_target_paging_uses_late_compound_key_and_preserves_all_types(store):
    plan = spec()
    with store.session_factory() as session:
        store.ensure(session, plan)
        session.execute(
            text("""
            INSERT INTO management.task_media_selections
                (selection_id,user_id,content_type,media_id,content_id,content_created_at)
            SELECT :selection_id, i, kind, 1, 1, '2026-09-06'::timestamptz
            FROM generate_series(1,20000) i CROSS JOIN (VALUES ('messages'),('posts')) k(kind)
        """),
            {"selection_id": plan["selection_id"]},
        )
        store.seal(session, plan)
        session.execute(text("ANALYZE management.task_media_selections"))
        session.commit()
    assert store.download_target_page(
        plan["selection_id"], after=(19998, "messages"), limit=3
    ) == [
        (19998, "posts"),
        (19999, "messages"),
        (19999, "posts"),
    ]
    assert store.download_target_page(
        plan["selection_id"], after=(19999, "posts"), limit=257
    ) == [
        (20000, "messages"),
        (20000, "posts"),
    ]
    assert (
        store.download_target_page(
            plan["selection_id"], after=(20000, "posts"), limit=1
        )
        == []
    )
    with store.session_factory() as session:
        plan_json = session.scalar(
            text("""
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT DISTINCT user_id, content_type FROM management.task_media_selections
            WHERE selection_id=:selection_id AND (user_id,content_type) > (19998,'messages')
            ORDER BY user_id,content_type LIMIT 3
        """),
            {"selection_id": plan["selection_id"]},
        )

    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    scans = [
        node for node in nodes(plan_json[0]["Plan"]) if "Scan" in node["Node Type"]
    ]
    assert scans and all(node.get("Actual Rows", 0) <= 5 for node in scans)


def test_paid_download_totals_count_each_selected_owner_and_type(store):
    plan = spec()
    with store.session_factory() as session:
        session.execute(
            text(
                "INSERT INTO media(id,user_id,size,drm,created_at) VALUES (94001,7,23,false,'2026-09-06'),(94002,8,41,true,'2026-09-06')"
            )
        )
        first = content(94011, 94001, "https://fixture/one")
        second = {**content(94012, 94002, "https://fixture/two"), "user_id": 8}
        store.add_content(session, plan, [first], "posts")
        store.add_content(session, plan, [second], "messages")
        store.seal(session, plan)
        session.commit()
    assert store.feed_download_totals(plan["selection_id"]) == {
        "count": 2,
        "bytes": 64,
        "drm": 1,
    }
    assert store.download_target_page(plan["selection_id"], limit=7) == [
        (7, "posts"),
        (8, "messages"),
    ]


def test_text_byte_budget_selects_before_payload_and_preserves_continuation(store):
    plan = spec()
    with store.session_factory() as session:
        store.add_content(
            session,
            plan,
            [content(i, i, "https://" + "x" * 200) for i in range(1, 6)],
            "posts",
        )
        store.put_evidence(
            session, plan["selection_id"], "errors", 0, ["x" * 100, "y" * 100]
        )
        session.commit()
    page = store.media_page(
        plan["selection_id"],
        user_id=7,
        content_type="posts",
        after=0,
        limit=5,
        max_bytes=700,
    )
    assert [row["media_id"] for row in page] == [1, 2]
    next_page = store.media_page(
        plan["selection_id"],
        user_id=7,
        content_type="posts",
        after=page[-1]["media_id"],
        limit=5,
        max_bytes=700,
    )
    assert [row["media_id"] for row in next_page] == [3, 4]
    with pytest.raises(ValueError, match="text bytes"):
        store.media_page(
            plan["selection_id"],
            user_id=7,
            content_type="posts",
            after=0,
            limit=1,
            max_bytes=10,
        )
    evidence = store.evidence_page(
        plan["selection_id"], kind="errors", limit=10, max_bytes=110
    )
    assert evidence == {"items": ["x" * 100], "ordinals": [0], "next_cursor": 0}
    assert store.evidence_page(
        plan["selection_id"], kind="errors", after=0, limit=10, max_bytes=110
    ) == {"items": ["y" * 100], "ordinals": [1], "next_cursor": None}


def test_archive_staging_pages_dedup_and_metadata_use_selected_signatures(store):
    plan = spec()
    with store.session_factory() as session:
        session.execute(
            text(
                "INSERT INTO x_posts(id,user_id,text,created_at) VALUES "
                "(110,7,'older','2026-09-01'),(111,7,'newer','2026-09-02'),"
                "(112,7,'another','2026-09-03')"
            )
        )
        session.execute(
            text(
                "INSERT INTO media(id,user_id,url,size,created_at) VALUES "
                "(120,7,'https://global',256,'2026-09-01'),"
                "(121,7,'https://global2',512,'2026-09-01')"
            )
        )
        session.execute(
            text(
                "INSERT INTO media_urls(media_id,auth_id,url) VALUES "
                "(120,99,'https://auth'),(120,100,'https://other-auth')"
            )
        )
        session.execute(
            text(
                "INSERT INTO content_media_asso(post_id,media_id) VALUES (110,120),(111,120),(112,121)"
            )
        )
        cursor = None
        while True:
            page = store.archive_page(
                session, plan, user_id=7, content_type="posts", cursor=cursor, limit=1
            )
            if not page["count"]:
                break
            cursor = page["cursor"]
        store.add_content(session, plan, [content(110, 120, "https://fresh")], "posts")
        store.seal(session, plan)
        session.commit()
    assert store.download_totals(
        plan["selection_id"], user_id=7, content_type="posts", auth_id=99
    ) == {"count": 2, "bytes": 768, "drm": 0}
    items = store.download_page(
        plan["selection_id"],
        user_id=7,
        content_type="posts",
        auth_id=99,
        after=0,
        limit=1,
        max_bytes=4096,
    )
    assert len(items) == 1
    assert items[0].content_id == 111
    assert items[0].text == "newer"
    assert items[0].medias[0].urls == ["https://fresh"]
    assert items[0].medias[0].size == 256
    remaining = store.download_page(
        plan["selection_id"],
        user_id=7,
        content_type="posts",
        auth_id=99,
        after=120,
        limit=1,
        max_bytes=4096,
    )
    assert remaining[0].medias[0].media_id == 121


def test_copy_page_rejects_another_auth_and_preserves_empty_selection(store):
    source = spec()
    target = {**source, "selection_id": uuid4().hex, "task_id": uuid4().hex}
    with store.session_factory() as session:
        store.seal(session, source)
        session.commit()
    payload = {
        "action": "copy_page",
        "source_id": source["selection_id"],
        "source_task_id": source["task_id"],
        "user_id": 7,
        "content_type": "posts",
        "limit": 10,
        "max_bytes": 4096,
    }
    with store.session_factory() as session:
        assert store.mutate(session, target, payload) == {"cursor": None, "count": 0}
        assert store.seal(session, target)["total"] == 0
        session.commit()
    with store.session_factory() as session, pytest.raises(ValueError, match="scope"):
        store.mutate(
            session, {**target, "selection_id": uuid4().hex, "auth_id": 100}, payload
        )
    adopted = {**target, "selection_id": uuid4().hex}
    with store.session_factory() as session:
        result = store.mutate(session, adopted, {**payload, "action": "adopt"})
        assert result == {"selection_id": source["selection_id"], "total": 0}
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.task_media_selections WHERE selection_id=:id"
                ),
                {"id": adopted["selection_id"]},
            )
            == 0
        )
        session.commit()


def test_media_selection_migration_round_trip(postgres_engine, monkeypatch):
    import importlib.util
    from pathlib import Path
    import ultima_scraper_db_archive
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    path = (
        Path(ultima_scraper_db_archive.__file__).parent
        / "migrations/alembic/versions/c79e2b4a185d_add_task_media_selections.py"
    )
    module_spec = importlib.util.spec_from_file_location(
        "media_selection_migration_test", path
    )
    migration = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(migration)
    assert migration.down_revision == "bd61e4a92f07"
    database = "media_migration_" + uuid4().hex
    with postgres_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(text(f"CREATE DATABASE {database}"))
    engine = create_engine(postgres_engine.url.set(database=database))
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA management"))
            monkeypatch.setattr(
                migration, "op", Operations(MigrationContext.configure(connection))
            )
            migration.upgrade()
            for model in (
                TaskMediaPlanModel,
                TaskMediaSelectionModel,
                TaskMediaEvidenceModel,
            ):
                columns = inspect(connection).get_columns(
                    model.__tablename__, schema="management"
                )
                assert {column["name"] for column in columns} == set(
                    model.__table__.columns.keys()
                )
            migration.downgrade()
            assert not inspect(connection).get_table_names(schema="management")
    finally:
        engine.dispose()
        with postgres_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.execute(text(f"DROP DATABASE {database}"))


@pytest.mark.asyncio
async def test_writer_content_and_selection_commit_or_rollback_together(
    store, media_engine
):
    from types import SimpleNamespace
    from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
    from ultima_scraper_backend.database.write_queue import (
        DatabaseWriteCommand,
        DatabaseWriteOperation,
    )

    executor = PostgreSQLWriteExecutor.__new__(PostgreSQLWriteExecutor)
    executor._site_manager = lambda site: SimpleNamespace(engine=media_engine)
    mutations = 0

    async def save_content(content, user_id, *, db_session, **kwargs):
        nonlocal mutations
        mutations += 1
        db_session.execute(
            text(
                "INSERT INTO onlyfans.x_posts(id,user_id,text,created_at) "
                "VALUES (:id,7,'writer','2026-09-05')"
            ),
            {"id": content.id},
        )
        return SimpleNamespace(success=True, message="saved", payload={})

    executor.backend = SimpleNamespace(save_content=save_content)
    plan = spec()
    command = DatabaseWriteCommand(
        command_id=uuid4().hex,
        operation=DatabaseWriteOperation.UPSERT_CONTENT_BATCH,
        site="onlyfans",
        producer_id="fixture",
        created_at="2026-09-05T00:00:00+00:00",
        payload={
            "user_id": 7,
            "auth_user_id": 99,
            "items": [dict(content(210, 220, "https://signed"), kind="post")],
            "media_selection": plan,
            "selection_content_type": "posts",
            "error_offset": 0,
        },
    )
    result = await executor._upsert_content_batch([command], "onlyfans")
    assert result[command.command_id]["items_saved"] == 1
    assert (
        store.media_page(
            plan["selection_id"],
            user_id=7,
            content_type="posts",
            after=0,
            limit=1,
            max_bytes=4096,
        )[0]["url"]
        == "https://signed"
    )
    assert await executor._upsert_content_batch([command], "onlyfans") == result
    assert mutations == 1
    bad_plan = spec()
    invalid = DatabaseWriteCommand(
        command_id=uuid4().hex,
        operation=command.operation,
        site="onlyfans",
        producer_id="fixture",
        created_at=command.created_at,
        payload={
            **command.payload,
            "media_selection": bad_plan,
            "items": [
                dict(
                    content(211, 221, "https://signed", created="invalid-date"),
                    kind="post",
                )
            ],
        },
    )
    with pytest.raises(ValueError):
        await executor._upsert_content_batch([invalid], "onlyfans")
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM x_posts WHERE id=211")) == 0
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM management.database_write_receipts WHERE command_id=:id"
                ),
                {"id": invalid.command_id},
            )
            == 0
        )
    with pytest.raises(ValueError, match="unavailable"):
        store.scope(bad_plan["selection_id"], job_id=bad_plan["job_id"])


def test_late_page_of_large_selection_uses_primary_key_without_prefix_scan(
    store, media_engine
):
    from sqlalchemy import event

    plan = spec()
    with store.session_factory() as session:
        store.ensure(session, plan)
        session.execute(
            text("""INSERT INTO management.task_media_selections
            (selection_id,user_id,content_type,media_id,content_id,content_created_at,url)
            SELECT :selection,7,'posts',i,i,'2026-09-05'::timestamptz,'https://fixture/' || i
            FROM generate_series(1,100000) i"""),
            {"selection": plan["selection_id"]},
        )
        store.seal(session, plan)
        session.commit()
    captured = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT"):
            captured.append((statement, parameters))

    event.listen(media_engine, "before_cursor_execute", capture)
    try:
        rows = store.media_page(
            plan["selection_id"],
            user_id=7,
            content_type="posts",
            after=99996,
            limit=3,
            max_bytes=4096,
        )
    finally:
        event.remove(media_engine, "before_cursor_execute", capture)
    assert [row["media_id"] for row in rows] == [99997, 99998, 99999]
    assert len(captured) == 2

    def nodes(plan):
        yield plan
        for child in plan.get("Plans", []):
            yield from nodes(child)

    with store.session_factory() as session:
        for sql, params in captured:
            explained = (
                session.connection()
                .exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params
                )
                .scalar_one()[0]["Plan"]
            )
            scans = [node for node in nodes(explained) if "Scan" in node["Node Type"]]
            assert scans and all("Index" in node["Node Type"] for node in scans)
            assert all(node["Actual Rows"] <= 3 for node in scans)


def test_preview_is_a_prefix_and_never_skips_forward_after_byte_exhaustion():
    from ultima_scraper_backend.database.media_selection import BoundedPreview

    preview = BoundedPreview(limit=10, max_bytes=10)
    preview.extend(["a", "much too long for the configured preview", "b"])
    assert preview.values == ["a"]
    assert preview.count == 3


def test_task_scoped_drm_signatures_do_not_reuse_another_proxy_stream_url(store):
    plan = spec()
    item = content(310, 320, "https://cdn/manifest.mpd")
    item["media"][0]["drm_payload"] = {
        "dash_manifest": "https://cdn/manifest.mpd",
        "dash_key_pair_id": "task-key",
        "dash_policy": "task-policy",
        "dash_signature": "task-signature",
    }
    with store.session_factory() as session:
        session.execute(
            text(
                "INSERT INTO x_posts(id,user_id,created_at) VALUES (310,7,'2026-09-05')"
            )
        )
        session.execute(
            text(
                "INSERT INTO media(id,user_id,url,drm,created_at) VALUES (320,7,'https://cdn/manifest.mpd',true,'2026-09-05')"
            )
        )
        session.execute(
            text(
                "INSERT INTO drm_manifest(media_id,dash_manifest,dash_key_pair_id,dash_policy,dash_signature,video_url,audio_url) "
                "VALUES (320,'https://cdn/manifest.mpd','other-key','other-policy','other-signature','https://other/video','https://other/audio')"
            )
        )
        store.add_content(session, plan, [item], "posts")
        store.seal(session, plan)
        session.commit()
    page = store.download_page(
        plan["selection_id"],
        user_id=7,
        content_type="posts",
        auth_id=99,
        after=0,
        limit=1,
        max_bytes=4096,
    )
    drm = page[0].medias[0].drm_media
    assert drm.policy == "task-policy"
    assert drm.signature == "task-signature"
    assert drm.video_url is None and drm.audio_url is None


@pytest.mark.asyncio
async def test_paged_evidence_file_endpoint_keeps_task_and_path_scope(
    store, monkeypatch, tmp_path
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    from ultima_scraper_backend.api.routes import jobs
    from ultima_scraper_backend.database import media_selection
    from test_job_result_media_route import _config_with_download_root

    plan = spec()
    root = tmp_path / "archive"
    root.mkdir()
    allowed = root / "recorded.jpg"
    allowed.write_bytes(b"image")
    outside = tmp_path / "private.jpg"
    outside.write_bytes(b"private")
    with store.session_factory() as session:
        store.seal(session, plan)
        store.put_evidence(
            session,
            plan["selection_id"],
            "download_results",
            10,
            [{"path": str(allowed)}, {"path": str(outside)}],
        )
        session.commit()
    task = jobs.TaskDetail(
        task_id=plan["task_id"],
        task_type="download",
        status="completed",
        result={"output": {"media_evidence": plan, "download_results": []}},
    )
    monkeypatch.setattr(jobs, "_fetch_job_task_detail", AsyncMock(return_value=task))
    monkeypatch.setattr(media_selection, "MediaSelectionStore", lambda: store)
    backend = SimpleNamespace(redis=None)
    page = await jobs.get_task_media_evidence(
        plan["job_id"],
        plan["task_id"],
        plan["selection_id"],
        kind="download_results",
        after=-1,
        limit=1,
        backend=backend,
    )
    assert page["ordinals"] == [10]
    response = await jobs.stream_job_task_download_file(
        plan["job_id"],
        plan["task_id"],
        10,
        backend=backend,
        config=_config_with_download_root(root),
    )
    assert str(response.path) == str(allowed)
    for ordinal in (9, 11):
        with pytest.raises(HTTPException) as error:
            await jobs.stream_job_task_download_file(
                plan["job_id"],
                plan["task_id"],
                ordinal,
                backend=backend,
                config=_config_with_download_root(root),
            )
        assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        await jobs.get_task_media_evidence(
            plan["job_id"],
            "another-task",
            plan["selection_id"],
            kind="download_results",
            after=-1,
            limit=1,
            backend=backend,
        )
