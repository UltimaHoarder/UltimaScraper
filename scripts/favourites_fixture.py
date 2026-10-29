"""Isolated PostgreSQL fixture shared by favourites tests and benchmarks."""
import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates.postgres_site import merged_metadata
from ultima_scraper_db_archive.favourites_models import SITES

TABLES = ("users", "user_infos", "user_aliases", "user_profile_media", "favorite_users", "subscriptions", "x_mass_messages", "x_posts", "x_stories", "x_messages", "media", "content_media_asso")


def assert_isolated(conn):
    directory = conn.execute(text("SELECT current_setting('data_directory')")).scalar()
    if directory != "/tmp/ultima-favourites-pg":
        raise RuntimeError("Fixture writes require the dedicated /tmp/ultima-favourites-pg cluster")


def initialize(engine):
    with engine.begin() as conn:
        assert_isolated(conn)
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS management"))
        for site in SITES:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {site}"))
            merged_metadata.create_all(conn, tables=[merged_metadata.tables[f"{site}.{table}"] for table in TABLES])
        if not conn.execute(text("SELECT to_regclass('management.favourites')")).scalar():
            revision = importlib.import_module("ultima_scraper_db_archive.migrations.alembic.versions.ce84a19f027b_add_unified_favourites")
            with Operations.context(MigrationContext.configure(conn)):
                revision.upgrade()
        if conn.execute(text("SELECT data_type FROM information_schema.columns WHERE table_schema='management' AND table_name='favourites' AND column_name='id'")).scalar() == "uuid":
            revision = importlib.import_module("ultima_scraper_db_archive.migrations.alembic.versions.d8f4b2a19c60_favourite_integer_ids_and_timestamps")
            with Operations.context(MigrationContext.configure(conn)):
                revision.upgrade()


def reset(engine):
    with engine.begin() as conn:
        assert_isolated(conn)
        for site in SITES:
            conn.execute(text(f"DROP TRIGGER IF EXISTS capture_favourites_flag ON {site}.users"))
            conn.execute(text(f"DROP TRIGGER IF EXISTS capture_favourites_rows ON {site}.favorite_users"))
        conn.execute(text("TRUNCATE management.favourites_identity_audit,management.favourites_migration,management.favourites," + ",".join(f"{site}.{table}" for site in SITES for table in TABLES) + " RESTART IDENTITY CASCADE"))


def seed(engine):
    with engine.begin() as conn:
        for site in SITES:
            conn.execute(text(f"""INSERT INTO {site}.users(id,username,favorite,join_date) VALUES
                (1,'creator',true,'2023-06-15 10:30:00+05:30'),(2,'receiver',true,NULL),(3,'retained',false,'2024-01-01+00')"""))
            conn.execute(text(f"INSERT INTO {site}.user_infos(user_id,name) VALUES (1,'Creator Name'),(2,'Receiver')"))
            conn.execute(text(f"INSERT INTO {site}.user_aliases(user_id,username) VALUES (1,'old_handle')"))
            conn.execute(text(f"INSERT INTO {site}.x_posts(id,user_id,text,created_at) VALUES (1,1,'needle post',now()),(2,3,'retained post',now())"))
            conn.execute(text(f"INSERT INTO {site}.x_stories(id,user_id,created_at,expires_at) VALUES (1,1,now(),now()-interval '1 day')"))
            conn.execute(text(f"INSERT INTO {site}.x_messages(id,user_id,receiver_id,text,created_at) VALUES (1,1,2,'needle message',now())"))
            conn.execute(text(f"INSERT INTO {site}.media(id,user_id,category,created_at) VALUES (1,3,'image',now())"))
            conn.execute(text(f"INSERT INTO {site}.content_media_asso(post_id,media_id) VALUES (1,1),(2,1)"))
