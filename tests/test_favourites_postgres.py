"""Opt-in real PostgreSQL validation; never touches the configured live DB."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from ultima_scraper_db_archive import UserModel
from ultima_scraper_db_archive import global_db
from ultima_scraper_db_archive import favourites_migration as migration
from ultima_scraper_db_archive.favourites_models import SITES
from ultima_scraper_backend.services import favourites_service as service
from ultima_scraper_backend.api.routes import favourites
from ultima_scraper_backend.api.dependencies import get_backend_instance
from scripts.favourites_fixture import initialize, reset, seed


@pytest.fixture(scope="module")
def pg_engine():
    url = os.environ.get("FAVOURITES_TEST_DATABASE_URL")
    if not url: pytest.skip("Set FAVOURITES_TEST_DATABASE_URL for the isolated PostgreSQL suite")
    engine = create_engine(url)
    initialize(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def archive(pg_engine, monkeypatch):
    reset(pg_engine)
    seed(pg_engine)
    monkeypatch.setattr(global_db, "_postgres_engine", pg_engine)
    with pg_engine.begin() as conn:
        for site in SITES:
            conn.execute(text("INSERT INTO management.favourites_migration(site,complete,validated,active) VALUES (:site,true,true,true)"), {"site": site})
    return pg_engine


@pytest.mark.parametrize("descending", [True, False])
@pytest.mark.parametrize("paid_only", [True, False])
def test_ordered_profile_probe_preserves_page_filters_and_missing_profiles(archive, descending, paid_only):
    from sqlalchemy import select, or_, exists
    from ultima_scraper_db_archive import UserInfoModel, SubscriptionModel
    from ultima_scraper_backend.api.routes.users import _paginate_user_query

    with archive.begin() as conn:
        conn.execute(text("UPDATE onlyfans.users SET active=true,performer=true"))
        conn.execute(text("UPDATE onlyfans.user_infos SET price=5,video_count=1"))
        conn.execute(text("INSERT INTO onlyfans.users(id,username,active,performer) VALUES (4,'subscribed',true,true)"))
        conn.execute(text("INSERT INTO onlyfans.user_infos(user_id,price,video_count) VALUES (4,5,1)"))
        conn.execute(text("INSERT INTO onlyfans.subscriptions(id,user_id,subscriber_id,active) VALUES (1,4,1,true)"))
        sort = UserModel.id.desc() if descending else UserModel.id.asc()
        query = (select(UserModel, UserInfoModel)
                 .outerjoin(UserInfoModel, UserModel.id == UserInfoModel.user_id)
                 .where(UserModel.active.is_(True), UserModel.performer.is_(True),
                        or_(UserInfoModel.sex.in_([0, 2]), UserInfoModel.sex.is_(None)),
                        ~exists(select(1).where(SubscriptionModel.user_id == UserModel.id,
                                                SubscriptionModel.active.is_(True))))
                 .order_by(sort))
        if paid_only:
            query = query.where(UserInfoModel.price >= 1, UserInfoModel.video_count >= 1)
        conn = conn.execution_options(schema_translate_map={None: "onlyfans"})
        expected = conn.execute(query.offset(1).limit(2)).all()
        actual = conn.execute(_paginate_user_query(query, sort, 1, 2, profile_probe=True)).all()
        assert actual == expected
        assert len(actual) <= 2
        if not paid_only:
            assert any(row._mapping["user_id"] is None for row in conn.execute(
                _paginate_user_query(query, sort, 0, 3, profile_probe=True)).all())


@pytest.mark.parametrize("kind", ["user","post","story","message"])
def test_create_remove_duplicate_and_site_isolation(archive, kind):
    with Session(archive) as session:
        first = service.set_state(session,"onlyfans",kind,1,True)
        again = service.set_state(session,"onlyfans",kind,1,True)
        assert again == first
        assert first["created_at_source"] == "added"
        assert not service.state(session,"fansly",kind,1)["favourited"]
        assert not service.set_state(session,"onlyfans",kind,1,False)["favourited"]
        assert session.execute(text(f"SELECT count(*) FROM onlyfans.{service.TARGETS[kind]} WHERE id=1")).scalar() == 1
        session.commit()


def test_native_fk_and_direct_duplicates(archive):
    with archive.begin() as conn:
        conn.execute(text("INSERT INTO management.favourites(site,entity_type,entity_id) VALUES ('onlyfans','user',1)"))
    with pytest.raises(IntegrityError), archive.begin() as conn:
        conn.execute(text("INSERT INTO management.favourites(site,entity_type,entity_id) VALUES ('onlyfans','user',1)"))
    with pytest.raises(IntegrityError), archive.begin() as conn:
        conn.execute(text("INSERT INTO management.favourites(site,entity_type,entity_id) VALUES ('onlyfans','post',999)"))


def test_favourites_autogeneration_keeps_owned_sequence_and_detects_actual_default_changes(archive):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from ultima_scraper_db_archive.favourites_alembic import compare_favourites_server_default
    from ultima_scraper_db_archive.favourites_models import FavouriteModel

    metadata = MetaData()
    FavouriteModel.__table__.to_metadata(metadata)
    with archive.connect() as conn:
        context = MigrationContext.configure(conn, opts={
            'include_schemas': True,
            'compare_server_default': compare_favourites_server_default,
            'include_object': lambda obj, name, kind, reflected, compare: kind != 'table'
                or (obj.schema == 'management' and name == 'favourites'),
        })
        before = conn.execute(text('SELECT last_value,is_called FROM management.favourites_id_seq')).one()
        assert compare_metadata(context, metadata) == []
        assert conn.execute(text('SELECT last_value,is_called FROM management.favourites_id_seq')).one() == before

        # A missing default must still require a repair, despite Alembic also
        # representing the legitimate owned sequence as a missing default.
        conn.execute(text('ALTER TABLE management.favourites ALTER COLUMN id DROP DEFAULT'))
        missing = compare_metadata(context, metadata)
        assert any(op[0] == 'modify_default' and op[2:4] == ('favourites', 'id')
                   for group in missing for op in group)

        # A different sequence is a real change; comparing it must not consume
        # either sequence while generating a preview.
        conn.execute(text('CREATE SEQUENCE management.favourites_wrong_id_seq'))
        conn.execute(text("ALTER TABLE management.favourites ALTER COLUMN id SET DEFAULT nextval('management.favourites_wrong_id_seq')"))
        wrong = compare_metadata(context, metadata)
        assert any(op[0] == 'modify_default' and op[2:4] == ('favourites', 'id')
                   for group in wrong for op in group)
        assert conn.execute(text('SELECT is_called FROM management.favourites_wrong_id_seq')).scalar() is False
        assert conn.execute(text('SELECT last_value,is_called FROM management.favourites_id_seq')).one() == before
        conn.rollback()


def test_cascades_soft_deleted_receiver_and_shared_media(archive):
    with Session(archive) as session:
        for kind in service.TARGETS: service.set_state(session,"onlyfans",kind,1,True)
        service.set_state(session,"onlyfans","post",2,True)
        session.execute(text("UPDATE onlyfans.x_posts SET deleted=true WHERE id=1"))
        assert service.state(session,"onlyfans","post",1)["favourited"]
        assert service.list_favourites(session,site="onlyfans",entity_type="post")["items"][0]["availability"] in {"available","deleted"}
        session.execute(text("DELETE FROM onlyfans.users WHERE id=2"))
        assert not service.state(session,"onlyfans","message",1)["favourited"]
        session.execute(text("DELETE FROM onlyfans.users WHERE id=1"))
        assert service.counts(session,site="onlyfans")["total"] == 1
        assert session.execute(text("SELECT count(*) FROM onlyfans.media WHERE id=1")).scalar() == 1
        assert service.state(session,"onlyfans","post",2)["favourited"]
        session.commit()


def test_cursor_search_counts_and_bounded_hydration(archive):
    with Session(archive) as session:
        for site in SITES:
            for kind in service.TARGETS: service.set_state(session,site,kind,1,True)
        session.execute(text("UPDATE management.favourites SET created_at='2025-01-01+00'"))
        session.commit()
        for order in ("asc","desc"):
            seen, cursor = [], None
            while True:
                page = service.list_favourites(session,order=order,limit=3,cursor=cursor)
                seen.extend(item["id"] for item in page["items"])
                if not page["has_more"]: break
                cursor = page["next_cursor"]
            assert len(set(seen)) == len(seen) == 12
        assert service.counts(session,search="old_handle")["total"] == 12
        assert service.counts(session,search="needle")["total"] == 6
        assert service.counts(session,search="%_")["total"] == 0
        with pytest.raises(HTTPException): service.list_favourites(session,site="fansly",cursor=cursor)
        statements = []
        def record(*args): statements.append(args[2])
        event.listen(archive,"before_cursor_execute",record)
        try:
            page = service.list_favourites(session,limit=100)
        finally: event.remove(archive,"before_cursor_execute",record)
        assert len(statements) == 3  # page + union metadata + union media
        assert any(item["entity"].get("media") for item in page["items"])
        assert any(item["availability"] == "expired" for item in page["items"])


def test_concurrent_add_and_toggle_precondition(archive):
    def add(_):
        with Session(archive) as session:
            result = service.set_state(session,"onlyfans","post",1,True)
            session.commit()
            return result["favourite_id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert len(set(pool.map(add,range(16)))) == 1
    with Session(archive) as session:
        with pytest.raises(HTTPException) as error: service.set_state(session,"onlyfans","post",1,True,expected=False)
        assert error.value.status_code == 409
        assert error.value.detail["state"]["favourited"]


def test_add_delete_race_cannot_orphan(archive):
    def add():
        with Session(archive) as session:
            try: service.set_state(session,"onlyfans","post",1,True); session.commit()
            except HTTPException as exc: assert exc.status_code == 404
    def delete():
        with archive.begin() as conn: conn.execute(text("DELETE FROM onlyfans.x_posts WHERE id=1"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda fn: fn(),[add,delete]))
    with Session(archive) as session: assert not service.state(session,"onlyfans","post",1)["favourited"]


def test_migration_resume_capture_timestamps_and_projection(archive):
    with archive.begin() as conn:
        conn.execute(text("TRUNCATE management.favourites_migration"))
        conn.execute(text("INSERT INTO onlyfans.favorite_users(user_id,notification) VALUES (3,false)"))
    with archive.connect() as conn:
        migration.prepare(conn)
        assert migration.copy_batch(conn,"onlyfans",1)
    # Resume on another connection, with legacy changes during the interruption.
    with archive.begin() as conn:
        conn.execute(text("UPDATE onlyfans.users SET favorite=false WHERE id=1"))
        conn.execute(text("UPDATE onlyfans.users SET favorite=true WHERE id=3"))
        conn.execute(text("DELETE FROM onlyfans.favorite_users WHERE user_id=3"))
        conn.execute(text("INSERT INTO fansly.favorite_users(user_id) VALUES (3)"))
    with archive.connect() as conn:
        for site in SITES:
            while migration.copy_batch(conn,site,1): pass
        report = migration.finish(conn)
        assert report["onlyfans"]["source_count"] == report["onlyfans"]["canonical_count"] == 2
        assert report['onlyfans']['duplicates'] == 0
        assert report['onlyfans']['validated_target_foreign_keys'] == 4
        migration.finish(conn,activate=True)
    with Session(archive) as session:
        assert not service.state(session,"onlyfans","user",1)["favourited"]
        fallback = service.state(session,"onlyfans","user",2)
        assert fallback["created_at_source"] == "migration_fallback"
        migration_time = session.execute(text("SELECT started_at FROM management.favourites_migration WHERE site='onlyfans'")).scalar()
        assert datetime.fromisoformat(fallback["created_at"]) == migration_time
        historical = service.state(session,"loyalfans","user",1)
        assert datetime.fromisoformat(historical["created_at"]) == datetime(2023,6,15,5,0,tzinfo=timezone.utc)
        assert service.state(session,"onlyfans","user",3)["created_at_source"] == "added"
        service.set_state(session,"onlyfans","user",3,False)
        session.commit()
    with archive.connect() as conn:
        migration.rollback_projection(conn)
        assert conn.execute(text("SELECT favorite FROM onlyfans.users WHERE id=3")).scalar() is False
        conn.rollback()


def test_migration_idempotency_and_capture_union(archive):
    with archive.begin() as conn:
        conn.execute(text("TRUNCATE management.favourites_migration"))
        conn.execute(text("INSERT INTO onlyfans.favorite_users(user_id,notification) VALUES (1,false),(3,true)"))
        conn.execute(text("INSERT INTO management.favourites(site,entity_type,entity_id,created_at,created_at_source) VALUES ('onlyfans','post',1,'2021-06-15T04:03:02.123456+05:30','legacy_favourite')"))
    with archive.connect() as conn:
        migration.prepare(conn)
        migration.prepare(conn)
        assert conn.execute(text('SELECT count(DISTINCT started_at) FROM management.favourites_migration')).scalar() == 1
        conn.rollback()
        for site in SITES:
            while migration.copy_batch(conn,site,2): pass
        before = conn.execute(text("SELECT site,entity_id,created_at FROM management.favourites ORDER BY site,entity_id")).all()
        conn.rollback()
        for site in SITES: assert not migration.copy_batch(conn,site,2)
        after = conn.execute(text("SELECT site,entity_id,created_at FROM management.favourites ORDER BY site,entity_id")).all()
        assert after == before
        conn.rollback()
    with archive.begin() as conn:
        conn.execute(text("UPDATE onlyfans.users SET favorite=false WHERE id=1"))
        assert conn.execute(text("SELECT count(*) FROM management.favourites WHERE site='onlyfans' AND entity_type='user' AND entity_id=1")).scalar() == 1
        conn.execute(text("DELETE FROM onlyfans.favorite_users WHERE user_id=1"))
        assert conn.execute(text("SELECT count(*) FROM management.favourites WHERE site='onlyfans' AND entity_type='user' AND entity_id=1")).scalar() == 0


def test_api_contract_batch_bounds_gate_and_legacy_adapter(archive):
    app = FastAPI()
    app.include_router(favourites.router,prefix="/api/v1")
    app.dependency_overrides[get_backend_instance] = lambda: SimpleNamespace(redis=None)
    with TestClient(app) as client:
        path = '/api/v1/favourites/onlyfans/post/1'
        assert client.put(path).json()["favourited"]
        assert client.get(path).json()["favourited"]
        assert client.post(path+'/toggle',json={"expected":False}).status_code == 409
        assert client.delete(path).json()["favourited"] is False
        assert client.put('/api/v1/favourites/onlyfans/post/999').status_code == 404
        assert client.post('/api/v1/favourites/states',json={"keys":[{"site":"onlyfans","entity_type":"user","entity_id":1}]*201}).status_code == 422
        assert client.get('/api/v1/favourites?entity_type=user').status_code == 200
    with Session(archive) as session:
        session.execute(text("SET LOCAL search_path=onlyfans,public"))
        user = session.get(UserModel,1)
        assert user.favorite is True  # retained recovery column
        assert service.user_state(session,"onlyfans",user) is False
        service.set_user_state(session,"onlyfans",user,True)
        assert service.user_state(session,"onlyfans",user) is True


def test_capture_insert_and_relationship_move(archive):
    with archive.begin() as conn:
        conn.execute(text("TRUNCATE management.favourites_migration"))
    with archive.connect() as conn:
        migration.prepare(conn)
    with archive.begin() as conn:
        conn.execute(text("INSERT INTO onlyfans.users(id,username,favorite) VALUES (4,'new_user',true)"))
        conn.execute(text("INSERT INTO onlyfans.favorite_users(user_id,notification) VALUES (3,true)"))
        conn.execute(text("UPDATE onlyfans.favorite_users SET user_id=4 WHERE user_id=3"))
        assert conn.execute(text("SELECT count(*) FROM management.favourites WHERE site='onlyfans' AND entity_id=3")).scalar() == 0
        assert conn.execute(text("SELECT created_at_source FROM management.favourites WHERE site='onlyfans' AND entity_id=4")).scalar() == 'added'
        assert conn.execute(text("SELECT notification FROM onlyfans.favorite_users WHERE user_id=4")).scalar() is True


def test_interrupted_batch_rolls_back_records_and_checkpoint(archive):
    with archive.begin() as conn:
        conn.execute(text("TRUNCATE management.favourites_migration"))
    with archive.connect() as conn:
        migration.prepare(conn)
        def fail_checkpoint(connection, cursor, statement, *args):
            if 'SET last_user_id=' in statement:
                raise RuntimeError('simulated interruption')
        event.listen(archive, 'before_cursor_execute', fail_checkpoint)
        try:
            with pytest.raises(RuntimeError, match='simulated interruption'):
                migration.copy_batch(conn, 'onlyfans', 1)
        finally:
            event.remove(archive, 'before_cursor_execute', fail_checkpoint)
        assert conn.execute(text("SELECT last_user_id FROM management.favourites_migration WHERE site='onlyfans'")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM management.favourites")).scalar() == 0
        conn.rollback()
        assert migration.copy_batch(conn, 'onlyfans', 1)


def test_concurrent_unfavourite_is_not_undone_by_stale_candidate(archive):
    with archive.begin() as conn:
        conn.execute(text("TRUNCATE management.favourites_migration"))
    with archive.connect() as conn:
        migration.prepare(conn)
        changed = False
        def unfavourite_before_lock(connection, cursor, statement, *args):
            nonlocal changed
            if not changed and statement.startswith('SELECT id FROM onlyfans.users WHERE id=ANY'):
                changed = True
                with archive.begin() as writer:
                    writer.execute(text("UPDATE onlyfans.users SET favorite=false WHERE id=1"))
        event.listen(archive, 'before_cursor_execute', unfavourite_before_lock)
        try:
            assert migration.copy_batch(conn, 'onlyfans', 1)
        finally:
            event.remove(archive, 'before_cursor_execute', unfavourite_before_lock)
        assert changed
        assert conn.execute(text("SELECT count(*) FROM management.favourites WHERE site='onlyfans' AND entity_id=1")).scalar() == 0
        conn.rollback()


def test_gate_and_cutover_reject_active_requests(archive, monkeypatch):
    with Session(archive) as request:
        service.ensure_active(request)
        with archive.connect() as migration_conn:
            with pytest.raises(ValueError, match='requests are active'):
                migration.rollback_projection(migration_conn)
            with pytest.raises(ValueError, match='requests are active'):
                migration.finish(migration_conn, activate=True)
    with archive.begin() as conn:
        conn.execute(text("UPDATE management.favourites_migration SET active=false WHERE site='onlyfans'"))
    with Session(archive) as session:
        with pytest.raises(HTTPException) as error:
            service.ensure_active(session, 'onlyfans')
        assert error.value.status_code == 503


def test_cutover_freezes_table_access_before_validation_and_trigger_removal(archive, monkeypatch):
    with archive.begin() as conn:
        conn.execute(text("TRUNCATE management.favourites_migration"))
    with archive.connect() as conn:
        migration.prepare(conn)
        for site in SITES:
            while migration.copy_batch(conn, site, 10):
                pass

    validate = migration.validation
    checked = []

    def validate_with_competing_reader(conn, site):
        # A writer may read a user before attempting its update. Block that
        # initial read now, rather than upgrading a weaker lock at DROP TRIGGER
        # while the competing transaction holds its read lock and awaits ours.
        with pytest.raises(OperationalError) as failure, archive.begin() as reader:
            reader.execute(text("SET LOCAL lock_timeout='100ms'"))
            reader.execute(text(f"SELECT id FROM {site}.users LIMIT 1"))
        assert failure.value.orig.sqlstate == '55P03'
        checked.append(site)
        return validate(conn, site)

    monkeypatch.setattr(migration, 'validation', validate_with_competing_reader)
    with archive.connect() as conn:
        migration.finish(conn, activate=True)
    assert checked == list(SITES)
    with archive.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM management.favourites_migration WHERE active")).scalar() == len(SITES)
        assert conn.execute(text("SELECT count(*) FROM management.favourites")).scalar() == 6
        assert conn.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname IN ('capture_favourites_flag','capture_favourites_rows')")).scalar() == 0
        assert conn.execute(text("SELECT id FROM onlyfans.users LIMIT 1")).scalar() is not None


def test_bulk_cascade_and_independent_content(archive):
    with Session(archive) as session:
        for kind in service.TARGETS:
            service.set_state(session, 'onlyfans', kind, 1, True)
        service.set_state(session, 'onlyfans', 'post', 2, True)
        session.execute(text("DELETE FROM onlyfans.users WHERE id=ANY(ARRAY[1,2]::bigint[])"))
        session.commit()
        assert service.counts(session, site='onlyfans')['total'] == 1
        assert service.state(session, 'onlyfans', 'post', 2)['favourited']


def test_preflight_rejects_cross_database_mapping(archive, monkeypatch):
    monkeypatch.setattr(migration, 'archive_database_url', lambda site=None:
                        'postgresql://localhost/other_archive' if site == 'fansly'
                        else 'postgresql://localhost/ultima_archive')
    with archive.connect() as conn:
        with pytest.raises(ValueError, match='different archive connection'):
            migration.preflight(conn, str(archive.url))


@pytest.mark.asyncio
async def test_legacy_profile_request_commits_canonical_state_despite_missed_hint(archive, monkeypatch):
    from sqlmodel import Session as SQLModelSession
    from ultima_scraper_backend.api import dependencies
    from ultima_scraper_backend.api.routes import users as users_route

    site_db = SimpleNamespace(get_session=lambda: SQLModelSession(
        archive.execution_options(schema_translate_map={None: 'onlyfans'})))
    monkeypatch.setattr(users_route, 'MultiSiteDatabaseManager',
                        lambda: SimpleNamespace(get_or_create_manager=lambda site: site_db))
    async def failed_notification_backend():
        raise RuntimeError('notification unavailable')
    monkeypatch.setattr(dependencies, 'get_backend_instance', failed_notification_backend)
    response = await users_route.update_user_profile(
        1, users_route.UserUpdateRequest(favorite=True), site='onlyfans')
    assert response.success and response.favorite
    response = await users_route.update_user_profile(
        1, users_route.UserUpdateRequest(favorite=False), site='onlyfans')
    assert response.success and not response.favorite
    with Session(archive) as session:
        assert not service.state(session, 'onlyfans', 'user', 1)['favourited']
        assert session.execute(text('SELECT favorite FROM onlyfans.users WHERE id=1')).scalar() is True


@pytest.mark.asyncio
async def test_user_pages_remain_bounded_when_exact_totals_fail(archive, monkeypatch):
    from contextlib import contextmanager
    from sqlmodel import Session as SQLModelSession
    from ultima_scraper_backend.api.routes import users as users_route, orders
    from ultima_scraper_backend.services.user_stats_cache import user_stats_cache
    bind = archive.execution_options(schema_translate_map={None: 'onlyfans'})
    site_db = SimpleNamespace(get_session=lambda: SQLModelSession(bind))
    monkeypatch.setattr(users_route, 'MultiSiteDatabaseManager', lambda:
                        SimpleNamespace(get_or_create_manager=lambda site: site_db))
    @contextmanager
    def no_orders():
        yield SimpleNamespace(query=lambda *args: SimpleNamespace(filter=lambda *args:
                              SimpleNamespace(all=lambda: [])))
    monkeypatch.setattr(orders, 'create_orders_session', no_orders)
    user_stats_cache.invalidate_site('onlyfans')
    aggregates = []
    def fail_totals(connection, cursor, statement, *args):
        if 'count(' in statement.lower() and 'user_infos' in statement:
            aggregates.append(statement)
            raise RuntimeError('simulated statement timeout')
    event.listen(archive, 'before_cursor_execute', fail_totals)
    try:
        first = await users_route.list_users(site='onlyfans', include_stats=False, limit=1, offset=0)
        assert first.success and len(first.users) == 1 and first.has_more
        assert first.total is None and first.avg_price is None
        assert aggregates == []
        totals = await users_route.list_users(site='onlyfans', stats_only=True)
        assert not totals.success and 'timeout' in totals.error
        last = await users_route.list_users(site='onlyfans', include_stats=False, limit=1, offset=2)
        assert last.success and len(last.users) == 1 and last.has_more is False
        assert len(aggregates) == 1
    finally:
        event.remove(archive, 'before_cursor_execute', fail_totals)
    totals = await users_route.list_users(site='onlyfans', stats_only=True)
    assert totals.success and totals.users == [] and totals.total == 3
    cached = await users_route.list_users(site='onlyfans', stats_only=True, limit=2, offset=1)
    assert cached.total == totals.total
    legacy = await users_route.list_users(site='onlyfans', limit=1)
    assert legacy.success and legacy.total == 3 and len(legacy.users) == 1


def test_batched_user_card_metadata_uses_canonical_state_and_latest_profile(archive):
    checked = datetime(2026, 10, 13, 20, 0, tzinfo=timezone.utc)
    with archive.begin() as conn:
        conn.execute(text("UPDATE onlyfans.users SET last_checked_at=:checked,active=true WHERE id=1"), {'checked':checked})
        conn.execute(text("UPDATE onlyfans.user_infos SET name='Fresh profile',post_count=37 WHERE user_id=1"))
        conn.execute(text("INSERT INTO onlyfans.user_profile_media(user_id,avatar_url,header_url,created_at) VALUES (1,'old-avatar','old-header','2025-01-01'),(1,'new-avatar','new-header','2026-10-13')"))
        conn.execute(text("INSERT INTO management.favourites(site,entity_type,entity_id) VALUES ('onlyfans','user',1)"))
    keys = [{'site':site, 'entity_type':'user', 'entity_id':user_id}
            for site in ('onlyfans','fansly') for user_id in (1,2,3)]
    statements = []
    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(archive, 'before_cursor_execute', count)
    try:
        with Session(archive) as session:
            metadata = service.resolve_metadata(session, keys*30, favourite_users=False)
    finally:
        event.remove(archive, 'before_cursor_execute', count)
    assert len(statements) == 1
    assert len(metadata) == 6
    updated = metadata[('onlyfans','user',1)]
    assert updated['name'] == 'Fresh profile'
    assert updated['post_count'] == 37
    assert datetime.fromisoformat(updated['last_checked_at']) == checked
    assert updated['avatar_url'] == 'new-avatar'
    assert updated['header_url'] == 'new-header'
    assert updated['favorite'] is True
    # The inactive legacy flags are true on both users; only management state counts.
    assert metadata[('onlyfans','user',2)]['favorite'] is False
    assert metadata[('fansly','user',1)]['favorite'] is False


@pytest.mark.parametrize("kind", ["user", "post", "story", "message"])
def test_creator_filters_apply_before_pagination_and_match_counts(archive, kind):
    with Session(archive) as session:
        session.execute(text("UPDATE onlyfans.users SET active=true,performer=true WHERE id=1"))
        session.execute(text("UPDATE onlyfans.user_infos SET price=8,post_count=12,image_count=20,video_count=4,sex=1,partner_sex=0,gender=1,partner_gender=0,profile_type=1,sexual_content=3 WHERE user_id=1"))
        session.execute(text("INSERT INTO onlyfans.subscriptions(id,user_id,subscriber_id,active) VALUES (1,1,2,true)"))
        for site in SITES:
            service.set_state(session,site,kind,1,True)
        options = dict(active_only=True,performer="include",subscribed="include",
                       sex=[0],gender=[0],profile_type=[1],sexual_content=[3],
                       min_price=8,max_price=8,min_post_count=12,max_post_count=12,
                       min_image_count=20,max_image_count=20,min_video_count=4,max_video_count=4)
        statements = []
        def record(*args): statements.append(args[2])
        event.listen(archive,"before_cursor_execute",record)
        try:
            page = service.list_favourites(session,entity_type=kind,limit=1,advanced=options)
        finally: event.remove(archive,"before_cursor_execute",record)
        assert [(item["site"],item["entity_type"]) for item in page["items"]] == [("onlyfans",kind)]
        assert not page["has_more"]
        assert service.counts(session,entity_type=kind,advanced=options)["total"] == 1
        assert len(statements) <= 3
        options["subscribed"] = "exclude"
        assert service.counts(session,advanced=options)["total"] == 0
        options["subscribed"] = "include"
        options["performer"] = "exclude"
        assert service.counts(session,advanced=options)["total"] == 0


def test_availability_null_identity_and_filtered_cursors(archive):
    with Session(archive) as session:
        for site in SITES:
            for kind in service.TARGETS: service.set_state(session,site,kind,1,True)
        session.execute(text("UPDATE onlyfans.users SET active=false WHERE id=1"))
        session.execute(text("UPDATE onlyfans.x_posts SET deleted=true,expires_at=now()-interval '1 day' WHERE id=1"))
        for status in ("available","inactive","deleted","expired","unavailable"):
            page = service.list_favourites(session,advanced={"availability":status})
            assert all(item["availability"] == status for item in page["items"])
            assert len(page["items"]) == service.counts(session,advanced={"availability":status})["total"]
        assert service.counts(session,site="onlyfans",advanced={"availability":"deleted"})["total"] == 1
        options = {"sex":[-1],"gender":[-1]}
        first = service.list_favourites(session,advanced=options,limit=2)
        second = service.list_favourites(session,advanced=options,limit=2,cursor=first["next_cursor"])
        assert len(first["items"]) == len(second["items"]) == 2
        assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
        with pytest.raises(HTTPException):
            service.list_favourites(session,advanced={"sex":[0]},cursor=first["next_cursor"])


def test_filter_query_contract_and_validation(archive, monkeypatch):
    monkeypatch.setattr(favourites,"queue_cached_profile_refresh",lambda *args: None)
    with Session(archive) as session:
        service.set_state(session,"onlyfans","user",1,True)
        session.execute(text("UPDATE onlyfans.user_infos SET sex=NULL,price=0 WHERE user_id=1"))
        session.commit()
    app = FastAPI()
    app.include_router(favourites.router,prefix="/api/v1")
    with TestClient(app) as client:
        params = [("site","onlyfans"),("sex","-1"),("sex","0"),("max_price","0")]
        page = client.get("/api/v1/favourites",params=params)
        assert page.status_code == 200
        assert len(page.json()["items"]) == 1
        assert client.get("/api/v1/favourites/counts",params=params).json()["total"] == 1
        for path in ("/api/v1/favourites","/api/v1/favourites/counts"):
            for invalid in ({"sex":9},{"availability":"wrong"},{"performer":"yes"},{"min_price":-1},
                            {"min_post_count":1.5},{"min_price":9,"max_price":2},{"max_price":"nan"}):
                assert client.get(path,params=invalid).status_code == 422


def test_empty_sites_activate_and_legacy_sites_wait_for_cutover(archive):
    with archive.begin() as conn:
        conn.execute(text("TRUNCATE management.favourites_migration"))
        conn.execute(text("UPDATE fansly.users SET favorite=false"))
        conn.execute(text("DELETE FROM fansly.favorite_users"))
    with archive.connect() as conn:
        assert migration.activate_empty_sites(conn) == ["fansly"]
        # A site with a row, active or not, is never touched again.
        assert migration.activate_empty_sites(conn) == []
    with archive.connect() as conn:
        rows = dict(conn.execute(text("SELECT site,active FROM management.favourites_migration")).all())
    assert rows == {"fansly": True}
    with Session(archive) as session:
        service.ensure_active(session, "fansly")
        with pytest.raises(HTTPException) as error:
            service.ensure_active(session, "onlyfans")
        assert error.value.status_code == 503
