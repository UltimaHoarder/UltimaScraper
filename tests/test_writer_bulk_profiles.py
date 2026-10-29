"""Set-based profile writes store exactly what the per-profile ORM path stores."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import MetaData, create_engine, text
from sqlmodel import Session
from test_mps_manifest import postgres_engine
from ultima_scraper_backend.database import write_receipts
from ultima_scraper_backend.database.helpers import profile_bulk
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.database.write_queue import (
    WRITE_TIMING_KEY,
    DatabaseWriteCommand,
    DatabaseWriteOperation,
)
from ultima_scraper_db_archive import (
    HistoUserInfoModel,
    SocialModel,
    UserAliasModel,
    UserInfoModel,
    UserModel,
    UserProfileMediaModel,
    WebsiteModel,
)

__all__ = ["postgres_engine"]

_MODELS = (
    UserModel,
    UserInfoModel,
    HistoUserInfoModel,
    UserProfileMediaModel,
    WebsiteModel,
    SocialModel,
    UserAliasModel,
)
_GENERATED = {"id", "created_at", "updated_at", "last_checked_at"}


def _create_schema(engine, schema):
    metadata = MetaData()
    tables = [model.__table__.to_metadata(metadata, schema=schema) for model in _MODELS]
    for table in tables:
        # Index shapes (trigram ops) are not what this test compares.
        table.indexes.clear()
    with engine.begin() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {schema}"))
        metadata.create_all(connection)
        connection.execute(text(f"""
            SET LOCAL search_path={schema};
            INSERT INTO users (id, username, balance, performer, active, join_date)
            VALUES (1, 'same', 2.5, false, true, '2020-01-01T00:00:00Z'),
                   (2, NULL, 0, false, true, NULL),
                   (3, 'OldName', 0, true, true, NULL),
                   (4, 'Casey', 0, false, false, NULL),
                   (5, 'five', 1, false, true, NULL),
                   (6, 'six', 0, false, true, NULL);
            INSERT INTO user_infos (user_id, name, description, price, promotion, post_count, website)
            VALUES (1, 'Same', 'bio', 0, false, 3, 'https://same.example'),
                   (2, 'Before', NULL, 4.99, true, 0, NULL),
                   (3, 'Old', 'old bio', 0, false, 0, NULL),
                   (5, 'Five', NULL, 0, false, 9, 'https://five.example');
            INSERT INTO user_profile_media (user_id, avatar_url, header_url)
            VALUES (1, 'a1', 'h1'), (2, 'old-avatar', NULL);
            INSERT INTO websites (user_id, url) VALUES (1, 'https://same.example');
            INSERT INTO socials (user_id, site, identifier) VALUES (6, 'Twitter', 'six');
        """))


def _profile(user_id, **values):
    user = dict.fromkeys(
        ("username", "name", "about", "subscribePrice", "postsCount", "mediasCount",
         "photosCount", "videosCount", "avatar", "header", "location", "website",
         "promotions", "credit_balance", "is_performer", "active", "join_date"),
    )
    user.update(id=user_id, socials=[])
    socials = values.pop("socials", [])
    aliases = values.pop("observed_aliases", [])
    user.update(values, socials=socials)
    return {"user": user, "sync_socials": True, "observed_aliases": aliases}


def _batches():
    first = [
        # Unchanged existing user: only the check times move.
        _profile(1, username="same", name="Same", about="bio", subscribePrice=0,
                 postsCount=3, avatar="a1", header="h1", website="https://same.example",
                 credit_balance=2.5, is_performer=False, active=True),
        # A username for a user stored without one is not an alias.
        _profile(2, username="Second", name="After", about="now", subscribePrice="9.99",
                 avatar="new-avatar", promotions=True, join_date="1700000000"),
        # A non-trivial rename keeps the ORM path (alias row).
        _profile(3, username="NewName", name="New", about="new bio"),
        # Case-only rename and a trivial observed alias.
        _profile(4, username="casey", observed_aliases=["@Casey", " casey "]),
        # A non-trivial observed alias keeps the ORM path.
        _profile(5, username="five", observed_aliases=["other-five"]),
        # Socials: one known (different case), one new, one duplicate, one invalid.
        _profile(6, username="six", socials=[
            {"socialMedia": "twitter", "username": "SIX"},
            {"socialMedia": "Instagram", "username": " six_ig "},
            {"site": "instagram", "url": "six_ig"},
            {"socialMedia": "", "username": "x"},
        ]),
        # New users: full payload, sparse payload and odd values.
        _profile(10, username="brand_new", name="Mañana \x00🎉", about="", subscribePrice=3,
                 postsCount="12", mediasCount=4.0, photosCount=1, videosCount=2,
                 avatar="av", header="hd", location="Here", website="  https://new.example ",
                 promotions=1, credit_balance="5.5", is_performer="true", active="false",
                 join_date="2021-05-01T10:00:00Z",
                 socials=[{"provider": "Reddit", "link": "u/new"}]),
        _profile(11),
        _profile(12, username="ms", join_date=1_600_000_000_000, header="only-header"),
        # A repeated user ID keeps the ORM path for both commands.
        _profile(13, username="twice", name="One"),
        _profile(13, username="twice", name="Two"),
    ]
    second = [
        _profile(1, username="same", name="Renamed", about="bio", avatar="a2", header="h1",
                 website="https://other.example"),
        _profile(10, username="brand_new", name="Mañana \x00🎉", about="changed",
                 postsCount=13, avatar="av", header="hd"),
        _profile(11, name="Now named", credit_balance=1),
        _profile(6, username="six", socials=[{"socialMedia": "Instagram", "username": "SIX_IG"}]),
    ]
    return first, second


def _command(index, payload):
    return DatabaseWriteCommand(
        command_id=f"cmd-{index}", operation=DatabaseWriteOperation.UPSERT_USER,
        site="onlyfans", payload=payload, producer_id="test",
        created_at="2026-10-21T00:00:00+00:00",
    )


async def _write(engine, schema, batches, monkeypatch, *, bulk):
    @contextmanager
    def receipts(_session, commands, _results, timing=None):
        yield list(commands)

    monkeypatch.setattr(write_receipts, "receipt_batch", receipts)
    monkeypatch.setenv("ULTIMA_WRITER_BULK_PROFILES", "1" if bulk else "0")
    applied = []
    original = profile_bulk.apply_bulk_profiles
    monkeypatch.setattr(
        profile_bulk,
        "apply_bulk_profiles",
        lambda session, plan: (applied.append(sorted(plan.indices)), original(session, plan)),
    )
    scoped = create_engine(engine.url, connect_args={"options": f"-c search_path={schema}"})
    executor = PostgreSQLWriteExecutor.__new__(PostgreSQLWriteExecutor)
    executor._site_manager = lambda site: SimpleNamespace(get_session=lambda: Session(scoped))
    try:
        for number, batch in enumerate(batches):
            commands = [_command(f"{number}-{i}", payload) for i, payload in enumerate(batch)]
            results = await executor._upsert_users(commands, "onlyfans")
            assert set(results) == {command.command_id for command in commands}
            assert all(result["synced"] for result in results.values())
            assert all("flush_ms" in result[WRITE_TIMING_KEY] for result in results.values())
    finally:
        scoped.dispose()
    return applied


def _snapshot(engine, schema):
    snapshot = {}
    with engine.connect() as connection:
        for model in _MODELS:
            table = model.__tablename__
            rows = connection.execute(text(f"SELECT * FROM {schema}.{table}")).mappings().all()
            snapshot[table] = sorted(
                (tuple(sorted((key, value) for key, value in row.items() if key not in _GENERATED))
                 for row in rows),
                key=repr,
            )
            if table == "users":
                checked = {row["id"]: row["last_checked_at"] for row in rows}
                snapshot["users_checked"] = sorted(user_id for user_id, at in checked.items() if at)
                snapshot["users_touched"] = sorted(row["id"] for row in rows if row["updated_at"])
    return snapshot


@pytest.mark.asyncio
async def test_bulk_profiles_store_the_same_rows_as_the_orm_path(postgres_engine, monkeypatch):
    first, second = _batches()
    _create_schema(postgres_engine, "eq_orm")
    _create_schema(postgres_engine, "eq_bulk")

    assert await _write(postgres_engine, "eq_orm", [first, second], monkeypatch, bulk=False) == []
    applied = await _write(postgres_engine, "eq_bulk", [first, second], monkeypatch, bulk=True)

    # Users 3 (rename), 5 (observed alias) and 13 (repeated) stay on the ORM path.
    assert applied == [[0, 1, 3, 5, 6, 7, 8], [0, 1, 2, 3]]
    orm, bulk = _snapshot(postgres_engine, "eq_orm"), _snapshot(postgres_engine, "eq_bulk")
    for table in orm:
        assert bulk[table] == orm[table], table
    # The comparison covers rows each path had to write.
    assert len(orm["histo_user_infos"]) >= 3
    assert len(orm["user_aliases"]) == 2
    assert len(orm["socials"]) == 3
    assert orm["users_checked"] == [1, 2, 3, 4, 5, 6, 10, 11, 12, 13]


@pytest.mark.asyncio
async def test_unchanged_profile_info_is_not_rewritten(postgres_engine, monkeypatch):
    first, _ = _batches()
    _create_schema(postgres_engine, "eq_quiet")
    await _write(postgres_engine, "eq_quiet", [first[:1]], monkeypatch, bulk=True)
    with postgres_engine.connect() as connection:
        before = connection.execute(text("SELECT xmin::text FROM eq_quiet.user_infos WHERE user_id=1")).scalar()
    await _write(postgres_engine, "eq_quiet", [first[:1]], monkeypatch, bulk=True)
    with postgres_engine.connect() as connection:
        after = connection.execute(text("SELECT xmin::text FROM eq_quiet.user_infos WHERE user_id=1")).scalar()
    assert after == before
