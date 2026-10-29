"""Sites with string ids keep them in ``external_id`` beside the hashed key."""

from types import SimpleNamespace

import pytest
from test_user_sync_aliases import _Session, _SiteDB
from ultima_scraper_api.helpers.site_ids import native_id_to_db_id
from ultima_scraper_backend.database.helpers.profile_bulk import plan_bulk_profiles
from ultima_scraper_backend.database.helpers.user_sync import (
    _UserSyncProfileCache,
    sync_user_from_api,
)
from ultima_scraper_backend.database.write_executor import serialize_user_write_payload
from ultima_scraper_db_archive import UserModel

# Matches LOYALFANS_USER_ID in UltimaScraperAPI/tests/enviroment.py.
UID = "R7lFAVk8H-2BI52sd3rMQYosAN6W7VjX-2F7wpSBt-2B3vguA"


def _loyalfans_user(uid: str = UID, username: str = "someone") -> SimpleNamespace:
    return SimpleNamespace(id=native_id_to_db_id(uid), uid=uid, username=username)


def test_native_id_falls_back_to_the_integer_id():
    assert UserModel(id=42).native_id == "42"
    assert UserModel(id=native_id_to_db_id(UID), external_id=UID).native_id == UID


@pytest.mark.asyncio
async def test_new_user_stores_the_site_id():
    session = _Session()
    assert await sync_user_from_api(_SiteDB(session), _loyalfans_user())
    assert session.user.id == native_id_to_db_id(UID)
    assert session.user.external_id == UID


@pytest.mark.asyncio
async def test_integer_site_user_leaves_external_id_null():
    session = _Session()
    assert await sync_user_from_api(
        _SiteDB(session), SimpleNamespace(id=7, username="of")
    )
    assert session.user.external_id is None


@pytest.mark.asyncio
async def test_existing_user_gains_the_site_id():
    session = _Session(UserModel(id=native_id_to_db_id(UID), username="someone"))
    assert await sync_user_from_api(_SiteDB(session), _loyalfans_user())
    assert session.user.external_id == UID


@pytest.mark.asyncio
async def test_hash_collision_is_refused_not_merged():
    stored = UserModel(
        id=native_id_to_db_id(UID), external_id="other-uid", username="a"
    )
    session = _Session(stored)
    assert (
        await sync_user_from_api(_SiteDB(session), _loyalfans_user(username="b"))
        is False
    )
    assert stored.external_id == "other-uid"
    assert stored.username == "a"


@pytest.mark.asyncio
async def test_queued_payload_carries_the_site_id_to_the_bulk_plan():
    payload = await serialize_user_write_payload(_loyalfans_user())
    assert payload["user"]["uid"] == UID
    plan = await plan_bulk_profiles(None, [payload], _UserSyncProfileCache())
    assert plan.users_new[0]["id"] == native_id_to_db_id(UID)
    assert plan.users_new[0]["external_id"] == UID


@pytest.mark.asyncio
async def test_bulk_plan_leaves_a_collision_to_the_orm_path():
    payload = await serialize_user_write_payload(_loyalfans_user())
    cache = _UserSyncProfileCache()
    cache.users[native_id_to_db_id(UID)] = UserModel(
        id=native_id_to_db_id(UID), external_id="other-uid", username="someone"
    )
    plan = await plan_bulk_profiles(None, [payload], cache)
    assert plan.indices == set()
