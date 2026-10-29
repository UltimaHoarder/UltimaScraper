"""Real PostgreSQL regression for the canonical USR configuration and revisions."""

import importlib
import json
import os
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from ultima_scraper_backend.config import UltimaScraperCollectionConfig
from ultima_scraper_db_archive.global_db import BackendInventoryModel, SettingsModel

from ultima_scraper_backend import config_settings_sync


def test_canonical_config_revisions_across_workers(monkeypatch, tmp_path):
    target = os.getenv("USV_CONFIGURATION_TEST_DATABASE_URL")
    if not target:
        pytest.skip("Disposable configuration test database not configured")
    url = (
        make_url(target)
        .set(drivername="postgresql+psycopg")
        .update_query_dict({"client_encoding": "utf8"})
    )
    assert url.database and url.database.startswith("degen_test_")
    parent = create_engine(url, isolation_level="AUTOCOMMIT")
    name = f"degen_test_usrconfig_{uuid4().hex}"
    with parent.connect() as connection:
        assert connection.scalar(text("SELECT current_database()")) == url.database
        connection.execute(
            text(f"CREATE DATABASE \"{name}\" TEMPLATE template0 ENCODING 'UTF8'")
        )
    engine = create_engine(url.set(database=name))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("BACKEND_ID", "host-a")
    monkeypatch.setenv("REDIS_PASSWORD", "old-redis-password")
    for key in (
        "REDIS_URL",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_DB",
        "REDIS_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        config_settings_sync, "get_global_session", lambda: Session(engine)
    )
    monkeypatch.setattr(
        config_settings_sync,
        "archive_database_url",
        lambda: "postgresql://fixture.invalid/archive",
    )
    try:
        schema_revision = importlib.import_module(
            "ultima_scraper_db_archive.migrations.alembic.versions."
            "8b3e0d5a2c91_unique_config_authority"
        )
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA management"))
            SettingsModel.__table__.create(connection)
            BackendInventoryModel.__table__.create(connection)
            with Operations.context(MigrationContext.configure(connection)):
                schema_revision.downgrade()
                schema_revision.upgrade()
        initial = UltimaScraperCollectionConfig()
        initial.settings.hostname = "host-a"
        initial.settings.worker_pool.size = 5
        snapshot_initial = config_settings_sync.persist_config_snapshot(initial)
        assert snapshot_initial.version == 1
        snapshot_second = config_settings_sync.persist_config_snapshot(
            initial, expected_version=1
        )
        assert snapshot_second.version == 2
        with Session(engine) as session:
            rows = session.exec(select(SettingsModel)).all()
            assert len(rows) == 1
            assert "old-redis-password" not in rows[0].value
            mapping = session.exec(select(BackendInventoryModel)).one()
            assert mapping.settings_id == rows[0].id
        first = UltimaScraperCollectionConfig.load_or_create_default_config()
        second = UltimaScraperCollectionConfig.load_or_create_default_config()
        assert first.settings.worker_pool.size == 5
        assert first.settings.redis.password == "old-redis-password"
        assert first._settings_version == second._settings_version == 2
        first.settings.worker_pool.size = 6
        snapshot = config_settings_sync.persist_config_snapshot(
            first, expected_version=2
        )
        assert snapshot.version == 3
        with pytest.raises(config_settings_sync.ConfigVersionConflict):
            config_settings_sync.persist_config_snapshot(second, expected_version=2)
        fresh = UltimaScraperCollectionConfig.load_or_create_default_config()
        assert fresh.settings.worker_pool.size == 6
        config_settings_sync.rollback_config_snapshot(snapshot)
        assert (
            UltimaScraperCollectionConfig.load_or_create_default_config().settings.worker_pool.size
            == 5
        )
        with pytest.raises(IntegrityError), Session(engine) as session:
            session.add(SettingsModel(backend="host-a", key="config", value="{}"))
            session.commit()
        with Session(engine) as session:
            row = session.exec(select(SettingsModel)).one()
            row.value = "{invalid"
            session.add(row)
            session.commit()
        with pytest.raises(json.JSONDecodeError):
            UltimaScraperCollectionConfig.load_or_create_default_config()
    finally:
        engine.dispose()
        with parent.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}"'))
        parent.dispose()
