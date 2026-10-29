from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from ultima_scraper_backend.helpers.user_refresh import needs_user_refresh
import pytest

import canonical_favourites_stub


@pytest.fixture(autouse=True)
def fake_canonical_favourites(monkeypatch):
    canonical_favourites_stub.install(monkeypatch)


@pytest.fixture(autouse=True)
def disable_live_profile_worker_dispatch(monkeypatch):
    from ultima_scraper_backend.api.routes import users
    monkeypatch.setattr(users, "get_backend_manager", lambda: None)
    monkeypatch.setattr(users, "_configured_profile_proxy_urls", lambda: ())
    from unittest.mock import AsyncMock
    monkeypatch.setattr(users, "_publish_profile_updated", AsyncMock())


def test_needs_user_refresh_when_last_checked_missing() -> None:
    assert needs_user_refresh(None)


def test_needs_user_refresh_after_more_than_seven_days() -> None:
    now = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    stale_last_checked = now - timedelta(days=7, seconds=1)

    assert needs_user_refresh(stale_last_checked, now=now) is True


def test_needs_user_refresh_false_at_exactly_seven_days() -> None:
    now = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)
    boundary_last_checked = now - timedelta(days=7)

    assert needs_user_refresh(boundary_last_checked, now=now) is False


class _FakeSession:
    def __init__(self, site_db):
        self.site_db = site_db

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, model, user_id):
        if self.site_db.user.id == user_id:
            return self.site_db.user
        return None

    def exec(self, statement):
        class _Result:
            def __init__(self, value):
                self.value = value

            def first(self):
                return self.value

        return _Result(self.site_db.latest_media)

    def add(self, obj):
        if (
            hasattr(obj, "avatar_url")
            and hasattr(obj, "header_url")
            and not hasattr(obj, "active")
        ):
            self.site_db.added_media.append(obj)
            self.site_db.latest_media = obj
        return None

    def commit(self):
        return None


class _FakeSiteDB:
    def __init__(self, user, latest_media=None):
        self.user = user
        self.latest_media = latest_media
        self.added_media = []

    def get_session(self):
        return _FakeSession(self)


class _FakeAuthed:
    def __init__(self, user):
        self.user = user

    async def get_user(self, user_id):
        return self.user


async def test_refresh_stale_existing_user_marks_inactive_when_upstream_missing(
    monkeypatch,
) -> None:
    from ultima_scraper_backend.api.routes import users as users_route
    from ultima_scraper_db_archive import UserModel

    stale_last_checked = datetime.now(timezone.utc) - timedelta(days=365)
    existing_user = UserModel(
        id=384937164,
        username="creator",
        active=True,
        last_checked_at=stale_last_checked,
    )
    site_db = _FakeSiteDB(existing_user)

    async def fake_get_guest_api(site: str, *, proxy_url: str | None = None):
        return _FakeAuthed(None)

    monkeypatch.setattr(users_route, "_get_guest_api", fake_get_guest_api)

    refreshed = await users_route._refresh_stale_existing_user(
        "384937164", "onlyfans", site_db
    )

    assert refreshed is False
    assert existing_user.active is False
    assert existing_user.last_checked_at is not None
    assert existing_user.last_checked_at > stale_last_checked


async def test_refresh_preserves_saved_user_when_proxy_route_fails(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import users as users_route
    from ultima_scraper_db_archive import UserModel

    stale_last_checked = datetime.now(timezone.utc) - timedelta(days=365)
    existing_user = UserModel(
        id=384937164,
        username="creator",
        active=True,
        last_checked_at=stale_last_checked,
    )
    site_db = _FakeSiteDB(existing_user)

    async def fake_get_guest_api(site: str, *, proxy_url: str | None = None):
        if proxy_url:
            raise OSError("proxy unavailable")
        return _FakeAuthed(None)

    monkeypatch.setattr(
        users_route,
        "_configured_profile_proxy_urls",
        lambda: ("http://unavailable.example:8080",),
    )
    monkeypatch.setattr(users_route, "_get_guest_api", fake_get_guest_api)

    refreshed = await users_route._refresh_stale_existing_user(
        "384937164", "onlyfans", site_db
    )

    assert refreshed is False
    assert existing_user.active is True
    assert existing_user.username == "creator"
    assert existing_user.last_checked_at == stale_last_checked


async def test_refresh_falls_back_to_username_when_numeric_id_was_replaced(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from ultima_scraper_backend.api.routes import users as users_route
    from ultima_scraper_db_archive import UserModel

    stale_user = UserModel(
        id=63027119,
        username="christinaxiong",
        active=True,
        last_checked_at=datetime.now(timezone.utc) - timedelta(days=365),
    )
    replacement_user = SimpleNamespace(id=777000111, username="christinaxiong")
    site_db = _FakeSiteDB(stale_user)
    lookups: list[int | str] = []

    async def fake_lookup(site: str, identifier: int | str, *, use_worker_pool=True):
        assert site == "onlyfans"
        lookups.append(identifier)
        if identifier == 63027119:
            return users_route.SiteUserLookupResult(
                user=None,
                conclusive_missing=False,
                attempted_routes=3,
                completed_routes=1,
            )
        assert identifier == "christinaxiong"
        return users_route.SiteUserLookupResult(
            user=replacement_user,
            conclusive_missing=False,
            attempted_routes=1,
            completed_routes=1,
        )

    synced: dict[str, object] = {}

    async def fake_schedule_user_sync(
        user,
        site: str,
        *,
        observed_aliases=(),
        wait: bool = False,
    ) -> bool:
        synced.update(
            user=user,
            site=site,
            observed_aliases=tuple(observed_aliases),
            wait=wait,
        )
        return True

    retired: list[int] = []
    monkeypatch.setattr(users_route, "_lookup_site_user", fake_lookup)
    monkeypatch.setattr(users_route, "_schedule_user_sync", fake_schedule_user_sync)
    monkeypatch.setattr(
        users_route,
        "_retire_missing_profile_claimant",
        lambda manager, user_id: retired.append(user_id),
    )

    refreshed = await users_route._refresh_stale_existing_user(
        "63027119", "onlyfans", site_db
    )

    assert refreshed is True
    assert lookups == [63027119, "christinaxiong"]
    assert synced == {
        "user": replacement_user,
        "site": "onlyfans",
        "observed_aliases": ("christinaxiong",),
        "wait": True,
    }
    assert retired == [63027119]


async def test_refresh_stale_existing_user_applies_minimal_status_when_sync_fails(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from ultima_scraper_backend.api.routes import users as users_route
    from ultima_scraper_db_archive import UserModel

    stale_last_checked = datetime.now(timezone.utc) - timedelta(days=365)
    existing_user = UserModel(
        id=384937164,
        username="old_name",
        active=False,
        last_checked_at=stale_last_checked,
    )
    site_db = _FakeSiteDB(existing_user)
    api_user = SimpleNamespace(username="fresh_name", active=True)

    async def fake_get_guest_api(site: str, *, proxy_url: str | None = None):
        return _FakeAuthed(api_user)

    async def fake_schedule_user_sync(
        user, site: str, *, observed_aliases=(), wait: bool = False
    ):
        return False

    monkeypatch.setattr(
        users_route, "_get_guest_api", fake_get_guest_api
    )
    monkeypatch.setattr(users_route, "_schedule_user_sync", fake_schedule_user_sync)

    refreshed = await users_route._refresh_stale_existing_user(
        "384937164", "onlyfans", site_db
    )

    assert refreshed is True
    assert existing_user.active is True
    assert existing_user.username == "fresh_name"
    assert existing_user.last_checked_at is not None
    assert existing_user.last_checked_at > stale_last_checked


async def test_search_user_persists_a_resolved_retired_handle_as_an_alias(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from ultima_scraper_backend.api.routes import users as users_route

    api_user = SimpleNamespace(id=384937164, username="current_handle")
    scheduled: dict[str, object] = {}

    class _Authed:
        async def get_user(self, identifier: str):
            assert identifier == "retired_handle"
            return api_user

    async def fake_get_guest_api(site: str, *, proxy_url: str | None = None):
        assert site == "OnlyFans"
        return _Authed()

    async def fake_schedule_user_sync(
        user,
        site: str,
        *,
        observed_aliases=(),
        wait: bool = False,
    ) -> bool:
        scheduled.update(
            user=user,
            site=site,
            observed_aliases=observed_aliases,
            wait=wait,
        )
        return True

    monkeypatch.setattr(users_route, "_get_guest_api", fake_get_guest_api)
    monkeypatch.setattr(users_route, "_schedule_user_sync", fake_schedule_user_sync)

    response = await users_route.search_user("@retired_handle", site="onlyfans")

    assert response.success is True
    assert response.user is not None
    assert response.user.username == "current_handle"
    assert scheduled["user"] is api_user
    assert scheduled["site"] == "onlyfans"
    assert scheduled["observed_aliases"] == ("retired_handle",)
    assert scheduled["wait"] is True


async def test_profile_identifier_resolves_one_local_alias_without_site_lookup(
    monkeypatch,
) -> None:
    from ultima_scraper_backend.api.routes import users as users_route

    candidate = users_route.UserIdentifierCandidate(
        user_id=384937164,
        username="current_handle",
        active=True,
        matched_by=["alias"],
    )

    class _SiteDB:
        pass

    class _MultiDB:
        def get_or_create_manager(self, site: str):
            assert site == "onlyfans"
            return _SiteDB()

    async def fail_if_site_lookup_happens(site: str):
        raise AssertionError("a unique local alias must not hit the site API")

    monkeypatch.setattr(users_route, "MultiSiteDatabaseManager", _MultiDB)
    monkeypatch.setattr(
        users_route,
        "_local_profile_identifier_candidates",
        lambda site_db, identifier: [candidate],
    )
    monkeypatch.setattr(users_route, "_get_guest_api", fail_if_site_lookup_happens)

    response = await users_route.resolve_profile_identifier(
        "@retired_handle", site="onlyfans", page=1, page_size=20
    )

    assert response.success is True
    assert response.status == "resolved"
    assert response.user_id == 384937164
    assert response.username == "current_handle"


async def test_profile_identifier_paginates_ambiguous_local_claims(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import users as users_route

    candidates = [
        users_route.UserIdentifierCandidate(
            user_id=user_id,
            username=f"creator_{user_id}",
            active=True,
            matched_by=["username" if user_id == 1 else "alias"],
        )
        for user_id in range(1, 4)
    ]

    class _SiteDB:
        pass

    class _MultiDB:
        def get_or_create_manager(self, site: str):
            return _SiteDB()

    monkeypatch.setattr(users_route, "MultiSiteDatabaseManager", _MultiDB)
    monkeypatch.setattr(
        users_route,
        "_local_profile_identifier_candidates",
        lambda site_db, identifier: candidates,
    )

    response = await users_route.resolve_profile_identifier(
        "duplicated_handle", site="onlyfans", page=2, page_size=2
    )

    assert response.success is True
    assert response.status == "ambiguous"
    assert response.total == 3
    assert [candidate.user_id for candidate in response.candidates] == [3]


async def test_profile_identifier_uses_site_api_for_a_missing_numeric_id(monkeypatch) -> None:
    from types import SimpleNamespace

    from ultima_scraper_backend.api.routes import users as users_route

    class _SiteDB:
        pass

    class _MultiDB:
        def get_or_create_manager(self, site: str):
            return _SiteDB()

    class _Authed:
        async def get_user(self, identifier: int):
            assert identifier == 333475350
            return SimpleNamespace(id=333475350, username="current_handle")

    async def fake_get_guest_api(site: str, *, proxy_url: str | None = None):
        assert site == "OnlyFans"
        return _Authed()

    captured_aliases: tuple[str, ...] | None = None

    async def fake_sync(site: str, user, *, observed_aliases=(), use_worker_pool=True):
        nonlocal captured_aliases
        assert site == "onlyfans"
        captured_aliases = tuple(observed_aliases)
        return True

    monkeypatch.setattr(users_route, "MultiSiteDatabaseManager", _MultiDB)
    monkeypatch.setattr(
        users_route, "_local_profile_identifier_candidates", lambda site_db, identifier: []
    )
    monkeypatch.setattr(users_route, "_get_guest_api", fake_get_guest_api)
    monkeypatch.setattr(users_route, "_sync_site_resolved_profile_user", fake_sync)

    response = await users_route.resolve_profile_identifier(
        "333475350", site="onlyfans", page=1, page_size=20
    )

    assert response.success is True
    assert response.status == "resolved"
    assert response.user_id == 333475350
    assert captured_aliases == ()


async def test_refresh_stale_existing_user_persists_avatar_and_header_on_minimal_refresh(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from ultima_scraper_backend.api.routes import users as users_route
    from ultima_scraper_db_archive import UserModel

    stale_last_checked = datetime.now(timezone.utc) - timedelta(days=365)
    existing_user = UserModel(
        id=384937164,
        username="old_name",
        active=False,
        last_checked_at=stale_last_checked,
    )
    site_db = _FakeSiteDB(existing_user)
    api_user = SimpleNamespace(
        username="fresh_name",
        active=True,
        avatar="https://example.com/avatar.jpg",
        header="https://example.com/header.jpg",
    )

    async def fake_get_guest_api(site: str, *, proxy_url: str | None = None):
        return _FakeAuthed(api_user)

    async def fake_schedule_user_sync(
        user, site: str, *, observed_aliases=(), wait: bool = False
    ):
        return False

    monkeypatch.setattr(
        users_route, "_get_guest_api", fake_get_guest_api
    )
    monkeypatch.setattr(users_route, "_schedule_user_sync", fake_schedule_user_sync)

    refreshed = await users_route._refresh_stale_existing_user(
        "384937164", "onlyfans", site_db
    )

    assert refreshed is True
    assert len(site_db.added_media) == 1
    assert site_db.added_media[0].avatar_url == "https://example.com/avatar.jpg"
    assert site_db.added_media[0].header_url == "https://example.com/header.jpg"


async def test_profile_background_refresh_is_deduplicated(monkeypatch) -> None:
    import asyncio

    from ultima_scraper_backend.api.routes import users as users_route

    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def fake_refresh(identifier: str, site: str, site_db) -> bool:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return True

    users_route._profile_refresh_tasks.clear()
    users_route._profile_refresh_errors.clear()
    monkeypatch.setattr(users_route, "_refresh_stale_existing_user", fake_refresh)

    try:
        assert users_route._ensure_profile_refresh_started("onlyfans", 123, object())
        await started.wait()
        assert users_route._ensure_profile_refresh_started("onlyfans", 123, object())
        assert users_route._profile_refresh_in_progress("onlyfans", 123)
        assert calls == 1

        release.set()
        task = users_route._profile_refresh_tasks[("onlyfans", 123)]
        await task
        await asyncio.sleep(0)
        assert not users_route._profile_refresh_in_progress("onlyfans", 123)
    finally:
        users_route._profile_refresh_tasks.clear()
        users_route._profile_refresh_errors.clear()


async def test_failed_profile_background_refresh_waits_for_operator_retry(
    monkeypatch,
) -> None:
    import asyncio

    from ultima_scraper_backend.api.routes import users as users_route

    calls = 0

    async def fake_refresh(identifier: str, site: str, site_db) -> bool:
        nonlocal calls
        calls += 1
        return False

    users_route._profile_refresh_tasks.clear()
    users_route._profile_refresh_errors.clear()
    monkeypatch.setattr(users_route, "_refresh_stale_existing_user", fake_refresh)

    try:
        assert users_route._ensure_profile_refresh_started("onlyfans", 123, object())
        task = users_route._profile_refresh_tasks[("onlyfans", 123)]
        await task
        await asyncio.sleep(0)

        assert not users_route._ensure_profile_refresh_started(
            "onlyfans", 123, object()
        )
        assert calls == 1
        assert (
            users_route._profile_refresh_errors[("onlyfans", 123)]
            == "The latest upstream profile refresh could not be completed."
        )

        assert users_route._ensure_profile_refresh_started(
            "onlyfans", 123, object(), force=True
        )
        retry_task = users_route._profile_refresh_tasks[("onlyfans", 123)]
        await retry_task
        assert calls == 2
    finally:
        users_route._profile_refresh_tasks.clear()
        users_route._profile_refresh_errors.clear()


async def test_forced_profile_refresh_joins_an_inflight_job(monkeypatch) -> None:
    import asyncio

    from ultima_scraper_backend.api.routes import users as users_route

    started = asyncio.Event()
    never = asyncio.Event()
    calls = 0

    async def fake_refresh(identifier: str, site: str, site_db) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await never.wait()
        return True

    users_route._profile_refresh_tasks.clear()
    users_route._profile_refresh_errors.clear()
    monkeypatch.setattr(users_route, "_refresh_stale_existing_user", fake_refresh)

    try:
        assert users_route._ensure_profile_refresh_started("onlyfans", 123, object())
        await started.wait()
        stalled_task = users_route._profile_refresh_tasks[("onlyfans", 123)]

        assert users_route._ensure_profile_refresh_started(
            "onlyfans", 123, object(), force=True
        )
        replacement_task = users_route._profile_refresh_tasks[("onlyfans", 123)]
        assert replacement_task is stalled_task
        never.set()
        await replacement_task
        await asyncio.sleep(0)

        assert not stalled_task.cancelled()
        assert calls == 1
    finally:
        for task in tuple(users_route._profile_refresh_tasks.values()):
            task.cancel()
        users_route._profile_refresh_tasks.clear()
        users_route._profile_refresh_errors.clear()


async def test_profile_refresh_timeout_is_reported(monkeypatch) -> None:
    import asyncio

    from ultima_scraper_backend.api.routes import users as users_route

    async def fake_refresh(identifier: str, site: str, site_db) -> bool:
        await asyncio.Event().wait()
        return True

    users_route._profile_refresh_tasks.clear()
    users_route._profile_refresh_errors.clear()
    monkeypatch.setattr(users_route, "PROFILE_REFRESH_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(users_route, "_refresh_stale_existing_user", fake_refresh)

    try:
        assert users_route._ensure_profile_refresh_started("onlyfans", 123, object())
        task = users_route._profile_refresh_tasks[("onlyfans", 123)]
        assert await task is False
        await asyncio.sleep(0)

        assert not users_route._profile_refresh_in_progress("onlyfans", 123)
        assert "timed out" in users_route._profile_refresh_errors[("onlyfans", 123)]
    finally:
        users_route._profile_refresh_tasks.clear()
        users_route._profile_refresh_errors.clear()


async def test_stale_profile_returns_saved_snapshot_without_waiting_for_api(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from ultima_scraper_backend.api.routes import users as users_route

    stale_last_checked = datetime.now(timezone.utc) - timedelta(days=365)
    user = SimpleNamespace(
        id=123,
        username="creator",
        active=True,
        last_checked_at=stale_last_checked,
        balance=0.0,
        spend=False,
        performer=True,
        favorite=False,
        join_date=None,
        downloaded_at=None,
        created_at=None,
    )
    info = SimpleNamespace(
        name="Creator",
        description=None,
        price=0.0,
        post_count=0,
        media_count=0,
        image_count=0,
        video_count=0,
        audio_count=0,
        stream_count=0,
        archived_post_count=0,
        subscribers_count=0,
        favourited_count=0,
        favourites_count=0,
        size=0,
        location=None,
        website=None,
        sex=None,
        gender=None,
        promotion=False,
        first_downloaded_at=None,
    )

    class Result:
        def __init__(self, value):
            self.value = value

        def first(self):
            return self.value

        def all(self):
            return self.value

    class Session:
        def __init__(self, responses):
            self.responses = iter(responses)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def exec(self, statement):
            return Result(next(self.responses))

    class SiteDB:
        def __init__(self):
            self.calls = 0

        def get_session(self):
            self.calls += 1
            if self.calls == 1:
                return Session([(user.id, user.last_checked_at)])
            return Session([(user, info), [], [], []])

    site_db = SiteDB()

    class MultiDB:
        def get_or_create_manager(self, site: str):
            return site_db

    refresh_calls: list[tuple[str, int]] = []

    def fake_start_refresh(site: str, user_id: int, manager) -> bool:
        refresh_calls.append((site, user_id))
        return True

    async def fail_if_api_called(site: str):
        raise AssertionError("stale saved profiles must not wait for the upstream API")

    def fake_resolve_size(**kwargs):
        return SimpleNamespace(
            size=0,
            display_size=0,
            estimated_size=None,
            size_source="unknown",
            statistics_bucket_date=None,
        )

    async def fake_statistics_availability(*args, **kwargs):
        return None

    monkeypatch.setattr(users_route, "MultiSiteDatabaseManager", MultiDB)
    monkeypatch.setattr(users_route, "_ensure_profile_refresh_started", fake_start_refresh)
    monkeypatch.setattr(users_route, "_profile_refresh_in_progress", lambda site, user_id: True)
    monkeypatch.setattr(users_route, "_get_guest_api", fail_if_api_called)
    monkeypatch.setattr(
        users_route.StatisticsService,
        "resolve_user_size_from_statistics",
        fake_resolve_size,
    )
    monkeypatch.setattr(
        users_route.StatisticsService,
        "get_statistics_availability",
        fake_statistics_availability,
    )

    response = await users_route.get_user_profile(
        123,
        site="onlyfans",
        backend=SimpleNamespace(redis=None),
    )

    assert response.success is True
    assert response.user is not None
    assert response.user.username == "creator"
    assert response.is_stale is True
    assert response.is_refreshing is True
    assert refresh_calls == [("onlyfans", 123)]


async def test_manual_profile_refresh_forces_a_background_retry(monkeypatch) -> None:
    from types import SimpleNamespace

    from ultima_scraper_backend.api.routes import users as users_route

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, model, user_id: int):
            return SimpleNamespace(id=user_id)

    class SiteDB:
        def get_session(self):
            return Session()

    class MultiDB:
        def get_or_create_manager(self, site: str):
            return SiteDB()

    calls: list[tuple[str, int, bool]] = []

    def fake_start(site: str, user_id: int, site_db, *, force: bool = False) -> bool:
        calls.append((site, user_id, force))
        return True

    monkeypatch.setattr(users_route, "MultiSiteDatabaseManager", MultiDB)
    monkeypatch.setattr(users_route, "_ensure_profile_refresh_started", fake_start)

    response = await users_route.refresh_user_profile(123, site="onlyfans")

    assert response.accepted is True
    assert response.is_refreshing is True
    assert calls == [("onlyfans", 123, True)]


class _FakeAuthResult:
    def __init__(self, auths):
        self.auths = auths

    def all(self):
        return self.auths


class _FakeAuthSession:
    def __init__(self, auths):
        self.auths = auths

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def exec(self, statement):
        return _FakeAuthResult(self.auths)


class _FakeAuthSiteDB:
    def __init__(self, auths):
        self.auths = auths

    def get_session(self):
        return _FakeAuthSession(self.auths)


class _FakeGuestAuthed:
    def __init__(self, guest: bool, proxy_url: str | None = None):
        self.guest = guest
        self.proxy_url = proxy_url

    def is_authed(self):
        return True

    def get_auth_details(self):
        return SimpleNamespace(proxy_url=self.proxy_url)


def _use_guest_site(monkeypatch, site_api) -> None:
    """Guest lookups resolve through the process's shared guest site API."""
    from ultima_scraper_backend.job_system import guest_sessions

    monkeypatch.setattr(guest_sessions, "_GUEST_SITE_APIS", {})
    guest_sessions.register_guest_site_api("OnlyFans", site_api)


def _guest_login_id(proxy_url=None) -> int:
    from ultima_scraper_backend.job_system import guest_sessions

    return guest_sessions._guest_seed_id(guest_sessions._guest_cache_key(proxy_url))


async def test_get_authenticated_api_falls_back_to_guest_when_no_active_auths(
    monkeypatch,
) -> None:
    from ultima_scraper_backend.api.routes import users as users_route

    login_calls: list[dict[str, object]] = []

    class FakeOnlyFansAPI:
        async def login(self, auth_json=None, guest: bool = False):
            login_calls.append(
                {
                    "guest": guest,
                    "auth_json": dict(auth_json or {}),
                }
            )
            return _FakeGuestAuthed(guest=guest)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str):
            return _FakeAuthSiteDB([])

    monkeypatch.setattr(users_route, "MultiSiteDatabaseManager", FakeMultiDB)
    monkeypatch.setattr(users_route, "OnlyFansAPI", FakeOnlyFansAPI)
    _use_guest_site(monkeypatch, FakeOnlyFansAPI())

    authed = await users_route._get_authenticated_api("onlyfans")

    assert authed is not None
    assert authed.guest is True
    assert login_calls == [{"guest": True, "auth_json": {"id": _guest_login_id()}}]


async def test_get_authenticated_api_falls_back_to_guest_when_auth_login_fails(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from ultima_scraper_backend.api.routes import users as users_route

    login_calls: list[dict[str, object]] = []
    auth_record = SimpleNamespace(
        user_id=42,
        username="auth_user",
        cookie="cookie",
        x_bc="xbc",
        user_agent="ua",
        authorization=None,
        proxy_id=None,
    )

    class FakeOnlyFansAPI:
        async def login(self, auth_json=None, guest: bool = False):
            login_calls.append(
                {
                    "guest": guest,
                    "auth_json": dict(auth_json or {}),
                }
            )
            if guest:
                return _FakeGuestAuthed(guest=True)
            return None

    class FakeMultiDB:
        def get_or_create_manager(self, site: str):
            return _FakeAuthSiteDB([auth_record])

    monkeypatch.setattr(users_route, "MultiSiteDatabaseManager", FakeMultiDB)
    monkeypatch.setattr(users_route, "OnlyFansAPI", FakeOnlyFansAPI)
    monkeypatch.setattr(
        users_route, "resolve_assigned_proxy_url", lambda proxy_id: None
    )
    _use_guest_site(monkeypatch, FakeOnlyFansAPI())

    authed = await users_route._get_authenticated_api("onlyfans")

    assert authed is not None
    assert authed.guest is True
    assert [call["guest"] for call in login_calls] == [False, True]
    assert login_calls[0]["auth_json"]["id"] == 42
    assert login_calls[1]["auth_json"] == {"id": _guest_login_id()}


async def test_profile_lookup_uses_configured_proxy_after_direct_miss(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from ultima_scraper_backend.api.routes import users as users_route

    resolved_user = SimpleNamespace(id=123, username="region_visible")
    routes: list[str | None] = []

    class FakeAuthed:
        def __init__(self, user):
            self.user = user

        async def get_user(self, identifier):
            assert identifier == 123
            return self.user

    async def fake_get_guest_api(site: str, *, proxy_url: str | None = None):
        routes.append(proxy_url)
        return FakeAuthed(resolved_user if proxy_url else None)

    async def fail_if_authenticated_account_is_loaded(site: str):
        raise AssertionError("profile resolution must remain guest-only")

    monkeypatch.setattr(
        users_route,
        "_configured_profile_proxy_urls",
        lambda: ("http://alternate.example:8080",),
    )
    monkeypatch.setattr(
        users_route, "_get_guest_api", fake_get_guest_api
    )
    monkeypatch.setattr(
        users_route,
        "_get_authenticated_api",
        fail_if_authenticated_account_is_loaded,
    )

    result = await users_route._lookup_site_user("onlyfans", 123)

    assert result.user is resolved_user
    assert result.conclusive_missing is False
    assert result.attempted_routes == 2
    assert result.completed_routes == 2
    assert routes == [None, "http://alternate.example:8080"]


async def test_profile_lookup_is_not_conclusive_when_a_proxy_route_fails(
    monkeypatch,
) -> None:
    from ultima_scraper_backend.api.routes import users as users_route

    class MissingAuthed:
        async def get_user(self, identifier):
            return None

    async def fake_get_guest_api(site: str, *, proxy_url: str | None = None):
        if proxy_url:
            raise OSError("proxy unavailable")
        return MissingAuthed()

    monkeypatch.setattr(
        users_route,
        "_configured_profile_proxy_urls",
        lambda: ("http://unavailable.example:8080",),
    )
    monkeypatch.setattr(
        users_route, "_get_guest_api", fake_get_guest_api
    )

    result = await users_route._lookup_site_user("onlyfans", "hidden_regionally")

    assert result.user is None
    assert result.conclusive_missing is False
    assert result.attempted_routes == 2
    assert result.completed_routes == 1


async def test_guest_api_applies_proxy_without_loading_saved_auths(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import users as users_route

    login_calls: list[dict[str, object]] = []

    class FakeOnlyFansAPI:
        async def login(self, auth_json=None, guest: bool = False):
            login_calls.append(
                {"auth_json": dict(auth_json or {}), "guest": guest}
            )
            return _FakeGuestAuthed(guest=guest, proxy_url=(auth_json or {}).get("proxy_url"))

    _use_guest_site(monkeypatch, FakeOnlyFansAPI())

    authed = await users_route._get_guest_api(
        "onlyfans",
        proxy_url="http://alternate.example:8080",
    )
    again = await users_route._get_guest_api(
        "onlyfans",
        proxy_url="http://alternate.example:8080",
    )

    assert authed is not None and again is authed  # One shared visitor per route.
    assert login_calls == [
        {
            "auth_json": {
                "id": _guest_login_id("http://alternate.example:8080"),
                "proxy_url": "http://alternate.example:8080",
            },
            "guest": True,
        }
    ]


class _FakeUpdateResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _FakeUpdateSession:
    def __init__(self, user, info=None, alias=None):
        self.user = user
        self.info = info
        self.alias = alias
        self.created_alias = None
        self.exec_calls = 0
        self.added_objects = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def exec(self, statement):
        self.exec_calls += 1
        if self.exec_calls == 1:
            return _FakeUpdateResult(self.user)
        if self.exec_calls == 2:
            return _FakeUpdateResult(self.info)
        if self.exec_calls == 3:
            return _FakeUpdateResult(self.alias)
        raise AssertionError(f"Unexpected query call {self.exec_calls}: {statement}")

    def add(self, obj):
        from ultima_scraper_db_archive import UserAliasModel, UserInfoModel

        self.added_objects.append(obj)
        if isinstance(obj, UserInfoModel):
            self.info = obj
        if isinstance(obj, UserAliasModel):
            self.alias = obj
            self.created_alias = obj

    def flush(self):
        return None

    def commit(self):
        return None

    def refresh(self, obj):
        return None


class _FakeUpdateSiteDB:
    def __init__(self, session):
        self.session = session

    def get_session(self):
        return self.session


async def test_update_user_profile_creates_normalized_alias(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import users as users_route
    from ultima_scraper_db_archive import UserModel

    user = UserModel(id=321, username="creator", favorite=False)
    fake_session = _FakeUpdateSession(user=user)
    site_db = _FakeUpdateSiteDB(fake_session)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str):
            return site_db

    monkeypatch.setattr(users_route, "MultiSiteDatabaseManager", FakeMultiDB)

    response = await users_route.update_user_profile(
        321,
        users_route.UserUpdateRequest(alias=" @shadow_name "),
        site="onlyfans",
    )

    assert response.success is True
    assert response.alias == "shadow_name"
    assert fake_session.created_alias is not None
    assert fake_session.created_alias.user_id == 321
    assert fake_session.created_alias.username == "shadow_name"
    assert fake_session.info is None


async def test_update_user_profile_keeps_the_previous_username_as_an_alias(
    monkeypatch,
) -> None:
    from ultima_scraper_backend.api.routes import users as users_route
    from ultima_scraper_db_archive import UserModel

    user = UserModel(id=321, username="retired_handle", favorite=False)
    fake_session = _FakeUpdateSession(user=user)
    site_db = _FakeUpdateSiteDB(fake_session)

    class FakeMultiDB:
        def get_or_create_manager(self, site: str):
            return site_db

    monkeypatch.setattr(users_route, "MultiSiteDatabaseManager", FakeMultiDB)

    response = await users_route.update_user_profile(
        321,
        users_route.UserUpdateRequest(username=" @current_handle "),
        site="onlyfans",
    )

    assert response.success is True
    assert response.username == "current_handle"
    assert user.username == "current_handle"
    assert fake_session.created_alias is not None
    assert fake_session.created_alias.user_id == 321
    assert fake_session.created_alias.username == "retired_handle"


async def test_automatic_profile_refresh_submits_one_complete_worker_command(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from ultima_scraper_backend.api.routes import users as users_route

    payload = {"lookups": {"123": {"user": {"id": 123}}}}
    submit = AsyncMock(return_value=SimpleNamespace(
        success=True, message="Completed", payload=payload
    ))
    monkeypatch.setattr(users_route, "get_backend_manager", lambda: SimpleNamespace(
        _submit_worker_api_command=submit
    ))
    local_refresh = AsyncMock(return_value=True)
    monkeypatch.setattr(users_route, "_refresh_stale_existing_user", local_refresh)
    async def inline(call, *args, **kwargs):
        return call(*args, **kwargs)
    monkeypatch.setattr(users_route, "run_database_call", inline)
    site_db = _FakeSiteDB(SimpleNamespace(id=123, username="creator"))

    assert await users_route._run_profile_refresh("onlyfans", 123, site_db)
    submit.assert_awaited_once_with(
        "onlyfans", "refresh_profile", {"user_id": 123, "username": "creator"}, None,
        guest=True, timeout_seconds=users_route.PROFILE_REFRESH_WORKER_WAIT_SECONDS,
        idempotency_key="profile:onlyfans:123:missing",
    )
    local_refresh.assert_awaited_once_with(
        "123", "onlyfans", site_db, lookup_results=payload["lookups"]
    )


async def test_profile_claimant_query_leaves_health_responsive(monkeypatch):
    import asyncio
    from threading import Event, get_ident
    from unittest.mock import AsyncMock, Mock

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from ultima_scraper_backend.api.routes import users as users_route

    entered, release = Event(), Event()
    thread_ids = []
    event_loop_thread = get_ident()

    def slow_claimants(*args, **kwargs):
        thread_ids.append(get_ident())
        entered.set()
        assert release.wait(2), "Test did not release the database query"
        return [999]

    monkeypatch.setattr(users_route, "_schedule_user_sync", AsyncMock(return_value=True))
    monkeypatch.setattr(users_route, "MultiSiteDatabaseManager", lambda: SimpleNamespace(
        get_or_create_manager=lambda site: object()
    ))
    monkeypatch.setattr(users_route, "_conflicting_profile_claimant_ids", slow_claimants)
    reconciled = Mock()
    monkeypatch.setattr(users_route, "_schedule_profile_claimant_reconciliation", reconciled)
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    refresh = asyncio.create_task(users_route._sync_site_resolved_profile_user(
        "onlyfans", SimpleNamespace(id=11767009, username="morbidly_sweet")
    ))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        assert thread_ids == [thread_ids[0]] and thread_ids[0] != event_loop_thread
        assert not refresh.done()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await asyncio.wait_for(client.get("/health"), 0.5)
        assert response.json() == {"status": "ok"}
        assert not refresh.done()
    finally:
        release.set()
        await refresh
    reconciled.assert_called_once_with("onlyfans", 999)


async def test_worker_profile_refresh_keeps_lookup_inside_worker(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from ultima_scraper_backend.api.routes import users as users_route
    from ultima_scraper_backend.database import factory
    from ultima_scraper_backend.job_system.handlers import api_command

    database = Mock(side_effect=AssertionError("Worker must not open profile database"))
    monkeypatch.setattr(factory, "MultiSiteDatabaseManager", database)
    user = SimpleNamespace(id=123, username="creator", is_performer=True)
    lookup = AsyncMock(return_value=users_route.SiteUserLookupResult(
        user=user, conclusive_missing=False, attempted_routes=1, completed_routes=1
    ))
    monkeypatch.setattr(users_route, "_lookup_site_user", lookup)
    result = await api_command._refresh_profile(
        None, SimpleNamespace(site="onlyfans"), {"user_id": 123, "username": "creator"}
    )
    assert result["lookups"]["123"]["user"]["id"] == 123
    lookup.assert_awaited_once_with("onlyfans", 123, use_worker_pool=False)
    database.assert_not_called()


async def test_refresh_persists_worker_snapshot_without_more_api_jobs(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from ultima_scraper_backend.api.routes import users as users_route

    site_db = _FakeSiteDB(SimpleNamespace(
        id=123, username="creator", last_checked_at=None
    ))
    async def inline(call, *args, **kwargs):
        return call(*args, **kwargs)
    monkeypatch.setattr(users_route, "run_database_call", inline)
    lookup = AsyncMock(side_effect=AssertionError("No extra API jobs"))
    monkeypatch.setattr(users_route, "_lookup_site_user", lookup)
    sync = AsyncMock(return_value=True)
    monkeypatch.setattr(users_route, "_sync_site_resolved_profile_user", sync)
    snapshots = {"123": {
        "user": {"id": 123, "username": "creator", "about": "Updated bio"},
        "socials": [{"site": "instagram", "username": "creator"}],
        "conclusive_missing": False, "attempted_routes": 1, "completed_routes": 1,
    }}
    assert await users_route._refresh_stale_existing_user(
        "123", "onlyfans", site_db, lookup_results=snapshots
    )
    saved_user = sync.await_args.args[1]
    assert saved_user.about == "Updated bio"
    assert saved_user.get_socials() == snapshots["123"]["socials"]
    lookup.assert_not_awaited()


async def test_worker_profile_lookup_outlives_legacy_refresh_timeout(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from ultima_scraper_backend.api.routes import users as users_route
    from ultima_scraper_backend.job_system.handlers import api_command

    monkeypatch.setattr(users_route, "PROFILE_REFRESH_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(users_route, "PROFILE_REFRESH_WORKER_TIMEOUT_SECONDS", 0.2)
    async def lookup(site, identifier, *, use_worker_pool):
        await asyncio.sleep(0.01)
        return users_route.SiteUserLookupResult(
            user=SimpleNamespace(id=123, username="creator"),
            conclusive_missing=False, attempted_routes=1, completed_routes=1,
        )
    monkeypatch.setattr(users_route, "_lookup_site_user", lookup)
    result = await api_command._refresh_profile(
        None, SimpleNamespace(site="onlyfans"), {"user_id": 123}
    )
    assert result["lookups"]["123"]["user"]["id"] == 123


def test_worker_wait_budget_covers_routes_and_queue():
    from ultima_scraper_backend.api.routes import users
    route_budget = 2 * (1 + users.PROFILE_LOOKUP_MAX_PROXY_ATTEMPTS) * 2 * users.PROFILE_LOOKUP_ROUTE_TIMEOUT_SECONDS
    assert users.PROFILE_REFRESH_WORKER_TIMEOUT_SECONDS > route_budget
    assert users.PROFILE_REFRESH_WORKER_WAIT_SECONDS > users.PROFILE_REFRESH_WORKER_TIMEOUT_SECONDS


async def test_unknown_username_lookup_uses_one_worker_job(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from ultima_scraper_backend.api.routes import users

    submit = AsyncMock(return_value=SimpleNamespace(success=True, payload={"lookups": {
        "onlyfans": {"user": {"id": 123, "username": "onlyfans"},
            "socials": [], "conclusive_missing": False,
            "attempted_routes": 2, "completed_routes": 1}
    }}))
    monkeypatch.setattr(users, "get_backend_manager", lambda: SimpleNamespace(
        _submit_worker_api_command=submit
    ))
    monkeypatch.setattr(users, "_configured_profile_proxy_urls", lambda: ())
    result = await users._lookup_site_user("onlyfans", "onlyfans")
    assert result.user.username == "onlyfans"
    submit.assert_awaited_once_with(
        "onlyfans", "refresh_profile", {"identifier": "onlyfans"}, None,
        guest=True, timeout_seconds=users.PROFILE_REFRESH_WORKER_WAIT_SECONDS,
    )
