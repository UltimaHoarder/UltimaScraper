"""Alias deduplication and overlapping refreshes on disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, text
from sqlmodel import Session
from test_content_write_resources import content_engine, postgres_engine
from ultima_scraper_backend.database.helpers.user_sync import (
    record_user_alias,
    sync_user_from_api,
)
from ultima_scraper_db_archive import UserAliasModel, UserModel

__all__ = ["content_engine", "postgres_engine"]


def test_profile_claimants_match_literal_handles_and_deduplicate_ids(content_engine):
    from ultima_scraper_backend.api.routes.users import (
        _conflicting_profile_claimant_ids,
    )

    with Session(content_engine) as session:
        session.add_all([
            UserModel(id=276022110, username="morbidly_sweet"),
            UserModel(id=276022111, username="MORBIDLY_SWEET"),
            UserModel(id=276022112, username="morbidlyXsweet"),
            UserModel(id=276022113, username="other"),
        ])
        session.flush()
        session.add_all([
            UserAliasModel(user_id=276022111, username="morbidly_sweet"),
            UserAliasModel(user_id=276022113, username="Morbidly_Sweet"),
            UserAliasModel(user_id=276022112, username="morbidly%sweet"),
            UserAliasModel(user_id=276022113, username="percent%_handle"),
        ])
        session.commit()
    site_db = SimpleNamespace(get_session=lambda: Session(content_engine))
    assert _conflicting_profile_claimant_ids(
        site_db, "@morbidly_sweet", exclude_user_id=276022110,
    ) == [276022111, 276022113]
    assert _conflicting_profile_claimant_ids(
        site_db, "percent%_handle", exclude_user_id=276022110,
    ) == [276022113]


@pytest.mark.parametrize("existing_user", [True, False])
async def test_profile_refresh_deduplicates_previous_and_observed_aliases(
    content_engine, existing_user
):
    user_id = 276022099 if existing_user else 276022100
    if existing_user:
        with Session(content_engine) as session:
            session.add(UserModel(id=user_id, username="onlyfans"))
            session.commit()
    with Session(content_engine, autoflush=False) as session:
        assert await sync_user_from_api(
            SimpleNamespace(),
            SimpleNamespace(id=user_id, username="loveisel"),
            session=session,
            observed_aliases=("onlyfans", "@onlyfans", "LOVEISLUKKAEW"),
            _defer_flush=True,
        )
        session.commit()
    with Session(content_engine) as session:
        assert session.get(UserModel, user_id).username == "loveisel"
        assert session.execute(
            select(UserAliasModel.username).where(UserAliasModel.user_id == user_id)
        ).scalars().all() == ["onlyfans"]


def test_overlapping_alias_inserts_do_not_abort_refresh_transactions(content_engine):
    ready = Barrier(2)

    def before_insert(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO user_aliases"):
            ready.wait(timeout=5)

    def record():
        with Session(content_engine, autoflush=False) as session:
            inserted = record_user_alias(session, 7, "concurrent-alias")
            session.commit()
            assert session.scalar(text("SELECT 1")) == 1
            return inserted

    event.listen(content_engine, "before_cursor_execute", before_insert)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(record) for _ in range(2)]
            assert sorted(future.result(timeout=10) for future in futures) == [
                False,
                True,
            ]
    finally:
        event.remove(content_engine, "before_cursor_execute", before_insert)
    with Session(content_engine) as session:
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM user_aliases WHERE user_id=7 AND username='concurrent-alias'"
                )
            )
            == 1
        )


def test_alias_insert_keeps_new_user_atomic_and_supports_rollback_reuse(content_engine):
    with Session(content_engine, autoflush=False) as session:
        session.add(UserModel(id=276022101, username="current"))
        assert record_user_alias(session, 276022101, "retired")
        session.rollback()
        assert session.get(UserModel, 276022101) is None
        assert (
            session.scalar(
                text("SELECT count(*) FROM user_aliases WHERE user_id=276022101")
            )
            == 0
        )
        session.add(UserModel(id=276022101, username="current"))
        assert record_user_alias(session, 276022101, "retired")
        session.commit()
    with Session(content_engine) as session:
        assert session.get(UserModel, 276022101).username == "current"
        assert (
            session.scalar(
                text("SELECT count(*) FROM user_aliases WHERE user_id=276022101")
            )
            == 1
        )
