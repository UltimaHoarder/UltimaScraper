"""Real, isolated PostgreSQL checks for the one-time UUID-to-integer revision."""
import importlib
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from scripts.favourites_fixture import assert_isolated, initialize, reset, seed
from ultima_scraper_backend.api.dependencies import get_backend_instance
from ultima_scraper_backend.api.routes import favourites
from ultima_scraper_backend.services import favourites_service as service
from ultima_scraper_db_archive import favourites_migration, global_db

revision = importlib.import_module(
    "ultima_scraper_db_archive.migrations.alembic.versions.d8f4b2a19c60_favourite_integer_ids_and_timestamps")


@pytest.fixture
def old_archive(monkeypatch):
    url = os.environ.get("FAVOURITES_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requires the dedicated temporary PostgreSQL cluster")
    engine = create_engine(url)
    initialize(engine)
    reset(engine)
    seed(engine)
    with engine.begin() as conn:
        assert_isolated(conn)
        conn.execute(text("DROP TABLE management.favourites_identity_audit"))
        conn.execute(text("DROP TABLE management.favourites CASCADE"))
        conn.execute(text("DROP TABLE management.favourites_migration"))
        original = importlib.import_module(
            "ultima_scraper_db_archive.migrations.alembic.versions.ce84a19f027b_add_unified_favourites")
        with Operations.context(MigrationContext.configure(conn)):
            original.upgrade()
        for site in service.SITES:
            conn.execute(text(f"UPDATE {site}.users SET downloaded_at='2024-06-15T10:30:00.123456+05:30' WHERE id=1"))
            conn.execute(text(f"INSERT INTO management.favourites(site,entity_type,entity_id,created_at) VALUES ('{site}','user',1,'2026-01-01+00'),('{site}','user',2,'2020-01-01+00')"))
            conn.execute(text("INSERT INTO management.favourites_migration(site,complete,validated) VALUES (:site,true,true)"), {"site":site})
        conn.execute(text("UPDATE onlyfans.users SET favorite=true,join_date='2010-01-01+00' WHERE id=3"))
        conn.execute(text("INSERT INTO management.favourites(site,entity_type,entity_id,created_at) VALUES ('onlyfans','user',3,'2025-01-01+00')"))
        for kind in ("post", "story", "message"):
            conn.execute(text("INSERT INTO management.favourites(site,entity_type,entity_id,created_at,created_at_source) VALUES ('onlyfans',:kind,1,'2021-01-01+00','legacy_favourite')"), {"kind":kind})
    monkeypatch.setattr(global_db, "_postgres_engine", engine)
    yield engine
    # Restore the current schema even when an intentionally interrupted test
    # leaves the atomic revision unapplied. Never runs against configured live DB.
    initialize(engine)
    engine.dispose()


def upgrade(engine):
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        revision.upgrade()


def test_existing_dates_order_audit_and_future_webui_defaults(old_archive):
    upgrade(old_archive)
    with old_archive.begin() as conn:
        rows = conn.execute(text("SELECT * FROM management.favourites ORDER BY created_at,site,entity_type,entity_id")).mappings().all()
        assert [row["id"] for row in rows] == list(range(1, 11))
        assert (rows[0]['site'],rows[0]['entity_type'],rows[0]['entity_id']) == ('onlyfans','user',3)
        assert rows[0]['created_at'] == datetime(2010,1,1,tzinfo=timezone.utc)
        assert [row['site'] for row in rows if row['entity_type']=='user' and row['entity_id']==2] == ['fansly','loyalfans','onlyfans']
        for row in rows:
            if row['entity_type']=='user' and row['entity_id']==1:
                assert row['created_at'] == datetime(2024,6,15,5,0,0,123456,tzinfo=timezone.utc)
                assert row['created_at_source'] == 'user_downloaded_at'
            elif row['entity_type']!='user':
                assert row['created_at'] == datetime(2021,1,1,tzinfo=timezone.utc)
                assert row['created_at_source'] == 'legacy_favourite'
            elif row['entity_id']==2:
                assert row['created_at'] == datetime(2020,1,1,tzinfo=timezone.utc)
                assert row['created_at_source'] == 'added'
        assert conn.execute(text("SELECT count(*) FROM management.favourites_identity_audit")).scalar() == 10
        assert conn.execute(text("SELECT count(*) FROM management.favourites_identity_audit WHERE created_at IS DISTINCT FROM coalesce(source_downloaded_at,source_join_date,previous_created_at)")).scalar() == 0
        # A later scrape must not re-date a migrated relationship or invalidate
        # its migration snapshot when activation compares legacy state.
        conn.execute(text("UPDATE onlyfans.users SET downloaded_at='2000-01-01+00',join_date='2000-01-01+00' WHERE id=1"))
        assert favourites_migration.validation(conn,'onlyfans')['timestamp_mismatches'] == 0
        conn.execute(text("INSERT INTO onlyfans.users(id,username,join_date,downloaded_at) VALUES (4,'new','2008-01-01+00','2009-01-01+00')"))
        conn.execute(text("UPDATE management.favourites_migration SET active=true"))
    app = FastAPI()
    app.include_router(favourites.router)
    app.dependency_overrides[get_backend_instance] = lambda: SimpleNamespace(redis=None)
    with TestClient(app) as client:
        before = datetime.now(timezone.utc)
        response = client.put('/favourites/onlyfans/user/4')
        assert response.status_code == 200
        added = response.json()
        assert type(added['favourite_id']) is int and added['favourite_id'] == 11
        assert added['created_at_source'] == 'added'
        assert before <= datetime.fromisoformat(added['created_at']) <= datetime.now(timezone.utc)
        assert client.put('/favourites/onlyfans/user/4').json() == added
        states = client.post('/favourites/states',json={'keys':[{'site':'onlyfans','entity_type':'user','entity_id':4}]}).json()['states']
        assert states[0] == added
        page = client.get('/favourites',params={'order':'asc','limit':3}).json()
        assert [item['id'] for item in page['items']] == [1,2,3]
        assert client.get('/favourites',params={'order':'asc','limit':3,'cursor':page['next_cursor']}).json()['items'][0]['id'] == 4
    # Parent and direct leaf insertions share the same sequence; idempotent
    # WebUI additions did not consume another value.
    with old_archive.begin() as conn:
        new_id = conn.execute(text("INSERT INTO management.favourites_fansly_story(site,entity_type,entity_id) VALUES ('fansly','story',1) RETURNING id")).scalar()
        assert new_id == 12
    with Session(old_archive) as session:
        session.execute(text('DELETE FROM onlyfans.users WHERE id=2'))
        assert not service.state(session,'onlyfans','user',2)['favourited']
        session.rollback()


def test_interruption_rolls_back_schema_timestamps_and_id_mapping(old_archive):
    with old_archive.connect() as conn:
        original = conn.execute(text('SELECT site,entity_type,entity_id,id,created_at FROM management.favourites ORDER BY site,entity_type,entity_id')).all()
        conn.rollback()
        transaction = conn.begin()
        with Operations.context(MigrationContext.configure(conn)):
            revision.upgrade()
        transaction.rollback()
        assert conn.execute(text("SELECT data_type FROM information_schema.columns WHERE table_schema='management' AND table_name='favourites' AND column_name='id'")).scalar() == 'uuid'
        assert conn.execute(text("SELECT to_regclass('management.favourites_identity_audit')")).scalar() is None
        assert conn.execute(text('SELECT site,entity_type,entity_id,id,created_at FROM management.favourites ORDER BY site,entity_type,entity_id')).all() == original
    upgrade(old_archive)


def test_empty_table_starts_at_one_and_old_cursors_are_rejected(old_archive):
    with old_archive.begin() as conn:
        conn.execute(text('DELETE FROM management.favourites'))
    upgrade(old_archive)
    with Session(old_archive) as session:
        added = service.set_state(session,'onlyfans','user',1,True)
        assert added['favourite_id'] == 1
        assert added['created_at_source'] == 'added'
        import base64,json
        for bad_id in ('1','550e8400-e29b-41d4-a716-446655440000',True,1.5,0,-1):
            cursor = base64.urlsafe_b64encode(json.dumps({'filters':[None,None,'','desc'],'created_at':added['created_at'],'id':bad_id,'site':'onlyfans','entity_type':'user'}).encode()).decode()
            with pytest.raises(HTTPException) as error:
                service.list_favourites(session,cursor=cursor)
            assert error.value.status_code == 400
