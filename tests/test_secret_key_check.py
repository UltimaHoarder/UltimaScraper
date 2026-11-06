"""Backends and workers sharing a database must share one USR_SECRET_KEY."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

import test_mps_manifest as fixtures

postgres_engine = fixtures.postgres_engine

KEY_A = "cluster-key-a"
KEY_B = "cluster-key-b"


@pytest.fixture
def cluster_engine(postgres_engine):
    host = postgres_engine.url.query["host"]
    with postgres_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(text('DROP DATABASE IF EXISTS "usr_secret_key_check"'))
        connection.execute(text('CREATE DATABASE "usr_secret_key_check"'))
    engine = create_engine(
        f"postgresql+psycopg://usr_test@/usr_secret_key_check?host={host}"
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA management"))
        connection.execute(
            text(
                "CREATE TABLE management.cluster ("
                "id smallint PRIMARY KEY DEFAULT 1, "
                "cluster_id uuid NOT NULL DEFAULT gen_random_uuid(), "
                "secret_key_check text)"
            )
        )
        connection.execute(text("CREATE SCHEMA onlyfans"))
        connection.execute(
            text("CREATE TABLE onlyfans.user_auths (id serial PRIMARY KEY, cookie text)")
        )
    yield engine
    engine.dispose()
    with postgres_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(
            text('DROP DATABASE IF EXISTS "usr_secret_key_check" WITH (FORCE)')
        )


@pytest.fixture
def use_key(monkeypatch):
    from ultima_scraper_db_archive.crypto import get_secret_crypto

    def use(key: str | None, previous: str | None = None) -> None:
        monkeypatch.setenv("USR_ENCRYPT_SECRETS", "true")
        for name, value in (("USR_SECRET_KEY", key), ("USR_SECRET_KEY_PREVIOUS", previous)):
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        get_secret_crypto.cache_clear()

    yield use
    get_secret_crypto.cache_clear()


def _verify(engine) -> None:
    from ultima_scraper_db_archive.secret_key_check import verify_secret_key_for_engine

    verify_secret_key_for_engine(engine)


def _stored_check(engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT secret_key_check FROM management.cluster WHERE id = 1")
        ).scalar()


def test_first_backend_records_its_key_and_a_second_must_match(cluster_engine, use_key):
    from ultima_scraper_db_archive.secret_key_check import SecretKeyMismatch

    use_key(KEY_A)
    _verify(cluster_engine)
    recorded = _stored_check(cluster_engine)
    assert recorded and recorded.startswith("enc:v1:")
    assert KEY_A not in recorded

    _verify(cluster_engine)
    assert _stored_check(cluster_engine) == recorded

    use_key(KEY_B)
    with pytest.raises(SecretKeyMismatch, match="same USR_SECRET_KEY"):
        _verify(cluster_engine)
    assert _stored_check(cluster_engine) == recorded


def test_existing_secrets_decide_the_key_on_a_database_without_a_check(
    cluster_engine, use_key
):
    from ultima_scraper_db_archive.crypto import encrypt_secret_value
    from ultima_scraper_db_archive.secret_key_check import SecretKeyMismatch

    use_key(KEY_A)
    with cluster_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO onlyfans.user_auths (cookie) VALUES (:cookie)"),
            {"cookie": encrypt_secret_value("sess=abc")},
        )

    use_key(KEY_B)
    with pytest.raises(SecretKeyMismatch, match="secrets already stored"):
        _verify(cluster_engine)
    assert _stored_check(cluster_engine) is None

    use_key(KEY_A)
    _verify(cluster_engine)
    assert _stored_check(cluster_engine) is not None


def test_rotation_moves_the_check_to_the_new_key(cluster_engine, use_key):
    from ultima_scraper_db_archive.secret_key_check import SecretKeyMismatch

    use_key(KEY_A)
    _verify(cluster_engine)
    old_check = _stored_check(cluster_engine)

    use_key(KEY_B, previous=KEY_A)
    _verify(cluster_engine)
    assert _stored_check(cluster_engine) != old_check

    use_key(KEY_B)
    _verify(cluster_engine)

    use_key(KEY_A)
    with pytest.raises(SecretKeyMismatch):
        _verify(cluster_engine)


def test_nothing_is_checked_without_encryption_or_before_the_schema(
    cluster_engine, use_key, monkeypatch
):
    use_key(KEY_A)
    monkeypatch.setenv("USR_ENCRYPT_SECRETS", "false")
    from ultima_scraper_db_archive.crypto import get_secret_crypto

    get_secret_crypto.cache_clear()
    _verify(cluster_engine)
    assert _stored_check(cluster_engine) is None

    use_key(KEY_A)
    with cluster_engine.begin() as connection:
        connection.execute(text("ALTER TABLE management.cluster DROP COLUMN secret_key_check"))
    _verify(cluster_engine)


def test_migrated_database_has_the_check_column():
    from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates.postgres_site import (
        ClusterModel,
    )

    assert "secret_key_check" in ClusterModel.__table__.columns


def test_launcher_refuses_to_start_with_another_key(cluster_engine, use_key, monkeypatch):
    import main
    from ultima_scraper_db_archive import global_db

    use_key(KEY_A)
    _verify(cluster_engine)

    use_key(KEY_B)
    monkeypatch.setattr(global_db, "is_setup_complete", lambda: True)
    monkeypatch.setattr(global_db, "get_global_engine", lambda: cluster_engine)
    with pytest.raises(SystemExit, match="same USR_SECRET_KEY"):
        main.verify_cluster_secret_key()

    use_key(KEY_A)
    main.verify_cluster_secret_key()
