"""Regression coverage for username aliases discovered during user resolution."""

import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlmodel import Session

from ultima_scraper_backend.database.helpers.user_sync import (
    record_user_alias,
    sync_user_from_api,
)
from ultima_scraper_db_archive import UserAliasModel, UserModel


class _Result:
    def __init__(self, value=None):
        self.value = value

    def first(self):
        return self.value


class _Session:
    def __init__(self, existing_user: UserModel | None = None):
        self.user = existing_user
        self.added: list[object] = []

    def get(self, model, user_id: int):
        if model is UserModel and self.user and self.user.id == user_id:
            return self.user
        return None

    def exec(self, statement):
        return _Result()

    def add(self, value: object):
        self.added.append(value)
        if isinstance(value, UserModel):
            self.user = value

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


class _SiteDB:
    def __init__(self, session: _Session):
        self.session = session

    def get_session(self):
        return self.session


def _create_user_subscription_tables(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, "
                "balance REAL NOT NULL DEFAULT 0, spend BOOL NOT NULL DEFAULT 0, "
                "wallet_tax_percent REAL, "
                "spender_type VARCHAR(32), performer BOOL NOT NULL DEFAULT 0, "
                "favorite BOOL NOT NULL DEFAULT 0, watched BOOL NOT NULL DEFAULT 0, "
                "ignored BOOL NOT NULL DEFAULT 0, active BOOL NOT NULL DEFAULT 1, "
                "downloaded_at DATETIME, last_checked_at DATETIME, join_date DATETIME, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME, external_id TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE subscriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER NOT NULL, subscriber_id INTEGER NOT NULL, "
                "paid_content BOOL NOT NULL DEFAULT 0, active BOOL NOT NULL DEFAULT 1, "
                "downloaded_at DATETIME, expires_at DATETIME, renewed_at DATETIME, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )


@pytest.mark.parametrize("autoflush", [True, False])
def test_alias_checks_include_pending_rows_with_case_and_at_prefix(autoflush):
    engine = create_engine("sqlite://")
    _create_user_subscription_tables(engine)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE user_aliases (id INTEGER PRIMARY KEY, user_id BIGINT NOT NULL, "
            "username TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
            "UNIQUE(user_id,username))"
        ))
    try:
        with Session(engine, autoflush=autoflush) as session:
            session.add(UserModel(id=42, username="current"))
            session.commit()
            assert record_user_alias(session, 42, "@retired", canonical_username="current")
            assert not record_user_alias(session, 42, "RETIRED", canonical_username="current")
            assert not record_user_alias(session, 42, "@CURRENT", canonical_username="current")
            session.commit()
            assert not record_user_alias(session, 42, "retired", canonical_username="current")
            assert session.scalar(text("SELECT count(*) FROM user_aliases")) == 1
    finally:
        engine.dispose()


async def test_sync_records_the_handle_that_resolved_to_a_new_username() -> None:
    session = _Session()
    user = SimpleNamespace(id=42, username="current_handle")
    timing: dict[str, float] = {}

    synced = await sync_user_from_api(
        _SiteDB(session),
        user,
        observed_aliases=("retired_handle",),
        timing=timing,
    )

    assert synced is True
    assert session.user is not None
    assert session.user.username == "current_handle"
    aliases = [item for item in session.added if isinstance(item, UserAliasModel)]
    assert [(alias.user_id, alias.username) for alias in aliases] == [
        (42, "retired_handle")
    ]
    assert set(timing) == {
        "payload_ms",
        "user_row_ms",
        "alias_ms",
        "authority_ms",
        "profile_ms",
        "social_ms",
        "flush_ms",
    }
    assert all(value >= 0 for value in timing.values())


async def test_sync_keeps_the_previous_canonical_username_as_an_alias() -> None:
    previous = UserModel(id=42, username="retired_handle")
    session = _Session(previous)
    user = SimpleNamespace(id=42, username="current_handle")

    synced = await sync_user_from_api(_SiteDB(session), user)

    assert synced is True
    assert previous.username == "current_handle"
    aliases = [item for item in session.added if isinstance(item, UserAliasModel)]
    assert [(alias.user_id, alias.username) for alias in aliases] == [
        (42, "retired_handle")
    ]


async def test_scheduled_profile_sync_keeps_upstream_io_on_loop_and_sql_off_loop(monkeypatch):
    import asyncio
    from threading import get_ident
    from ultima_scraper_backend.database.helpers import user_sync as module

    caller_loop = asyncio.get_running_loop()
    caller_thread = get_ident()
    observed = {}
    socials = [{"site": "instagram", "username": "creator"}]

    async def get_socials():
        assert asyncio.get_running_loop() is caller_loop
        return socials

    async def persist(manager, user, **kwargs):
        assert get_ident() != caller_thread
        observed.update(kwargs)
        observed["name"] = user.name
        observed["promotions"] = user.promotions
        observed["socials"] = await user.get_socials()
        return True

    monkeypatch.setattr(module, "sync_user_from_api", persist)
    task = module.schedule_user_sync(
        SimpleNamespace(id=42, username="current", name="Creator", promotions=[{"price": 1}],
                        get_socials=get_socials),
        "OnlyFans", db_manager=_SiteDB(_Session()), sync_socials=True,
        observed_aliases=("retired",),
    )
    assert task is not None
    assert await task
    assert observed == {
        "site": "onlyfans", "sync_socials": True, "observed_aliases": ["retired"],
        "name": "Creator", "promotions": [{"price": 1}], "socials": socials,
    }


async def test_each_synced_profile_logs_only_at_debug(caplog) -> None:
    # MPS syncs thousands of profiles per second; an INFO line per profile
    # serialized every writer lane on the log handlers' locks.
    name = "ultima_scraper_backend.database.helpers.user_sync"
    caplog.set_level(logging.INFO, logger=name)
    assert await sync_user_from_api(
        _SiteDB(_Session()), SimpleNamespace(id=7, username="probe"), site="onlyfans"
    )
    assert not [record for record in caplog.records if "Synced user" in record.getMessage()]

    caplog.clear()
    caplog.set_level(logging.DEBUG, logger=name)
    assert await sync_user_from_api(
        _SiteDB(_Session()), SimpleNamespace(id=8, username="probe2"), site="onlyfans"
    )
    assert [
        record.levelno for record in caplog.records
        if record.getMessage() == "Synced user 8 for site onlyfans"
    ] == [logging.DEBUG]
