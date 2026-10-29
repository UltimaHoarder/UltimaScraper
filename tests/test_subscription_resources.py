from __future__ import annotations

import asyncio
import gc
import weakref
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from ultima_scraper_api.apis.onlyfans.classes.auth_model import OnlyFansAuthModel
from ultima_scraper_api.apis.onlyfans.classes.user_model import UserModel
from ultima_scraper_backend.job_system.handlers.scrape import subscriptions as handler


def subscription_data(identifier):
    return {
        "id": identifier,
        "username": f"profile_{identifier}",
        "subscribedBy": True,
        "subscribedByData": {},
        "subscribedByExpire": False,
        "subscribedByExpireDate": "2099-01-01T00:00:00+00:00",
        "subscribedByAutoprolong": False,
        "subscribedIsExpiredNow": False,
        "currentSubscribePrice": 0,
        "subscribedOn": False,
        "subscribedOnData": {},
        "subscribedOnExpiredNow": False,
        "subscribedOnDuration": "0",
        "subscribePrice": 0,
    }


@pytest.fixture
def subscription_auth(monkeypatch):
    from ultima_scraper_api.managers import redis

    monkeypatch.setattr(redis, "get_redis", lambda: None)
    monkeypatch.delenv("ULTIMA_SUBSCRIPTION_HYDRATION_CONCURRENCY", raising=False)
    monkeypatch.setattr(handler, "runtime_env_value", lambda _: None)

    class ContentCache:
        def __init__(self):
            for name in ("Posts", "Messages", "MassMessages", "Stories", "Highlights"):
                setattr(self, name, {})

    class Auth:
        id = 99
        username = "subscriber"
        user = SimpleNamespace(id=99)
        total = 205

        def __init__(self):
            self.users = {}
            self.subscriptions = []
            self.page_requests = []
            self.hydrated = []
            self.cache_activations = []
            self.api = SimpleNamespace(CategorizedContent=ContentCache)
            self.auth_session = SimpleNamespace(
                get_session_manager=lambda: SimpleNamespace(max_threads=2),
                session_manager=SimpleNamespace(max_threads=2),
                json_request=self.json_request,
            )
            self.cache = SimpleNamespace(
                subscriptions=SimpleNamespace(is_released=lambda: True),
                users=lambda identifier: SimpleNamespace(
                    is_released=lambda: True,
                    activate=lambda: self.cache_activations.append(identifier),
                ),
            )

        def get_api(self):
            return self.api

        def find_user(self, identifier):
            return self.users.get(identifier)

        def add_user(self, user):
            self.users[user.id] = user

        async def get_subscription_count(self):
            return SimpleNamespace(
                subscriptions=SimpleNamespace(
                    all=self.total, active=self.total, expired=0
                )
            )

        async def json_request(self, url, **kwargs):
            if kwargs.get("method") == "POST":
                return {}
            parsed = urlparse(url)
            if parsed.path.endswith("/subscriptions/subscribes"):
                query = parse_qs(parsed.query)
                offset, limit = int(query["offset"][0]), int(query["limit"][0])
                self.page_requests.append((offset, limit, query))
                return {
                    "list": [
                        subscription_data(i)
                        for i in range(offset, min(offset + limit, self.total))
                    ],
                    "hasMore": offset + limit < self.total,
                }
            identifier = int(parsed.path.rsplit("/", 1)[-1])
            self.hydrated.append(identifier)
            await asyncio.sleep(0)
            return {
                "id": identifier,
                "username": f"profile_{identifier}",
                "about": "fresh",
            }

        resolve_user = OnlyFansAuthModel.resolve_user
        get_user = OnlyFansAuthModel.get_user
        iter_subscriptions = OnlyFansAuthModel.iter_subscriptions
        get_subscriptions = OnlyFansAuthModel.get_subscriptions

    return Auth()


@pytest.mark.asyncio
async def test_subscription_stream_preserves_canonical_user_and_releases_old_pages(
    subscription_auth,
):
    auth = subscription_auth
    auth.total = 10_000
    canonical = UserModel({"id": 1, "username": "canonical"}, auth)
    refs = weakref.WeakSet()
    count = 0
    async with aclosing(auth.iter_subscriptions()) as stream:
        async for subscription in stream:
            assert subscription.id == count
            assert subscription.user.about == "fresh"
            refs.add(subscription.user)
            count += 1
            if count % 100 == 0:
                gc.collect()
                assert len(refs) <= 101
                assert len(auth.page_requests) == count // 100
    del subscription
    gc.collect()
    assert len(refs) == 0
    assert count == auth.total
    assert auth.users == {1: canonical}
    assert canonical.username == "canonical"
    assert auth.cache_activations == []
    assert auth.subscriptions == []
    assert len(auth.hydrated) == auth.total


@pytest.mark.asyncio
async def test_subscription_hydration_admission_and_cancellation(subscription_auth):
    auth = subscription_auth
    entered = []
    closed = []
    saturated = asyncio.Event()

    async def blocked_user(identifier, **kwargs):
        entered.append(identifier)
        if len(entered) == 7:
            saturated.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(identifier)

    auth.get_user = blocked_user

    async def consume():
        async with aclosing(auth.iter_subscriptions(concurrency=7)) as stream:
            await anext(stream)

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(saturated.wait(), 2)
        assert entered == list(range(7))
        assert len(auth.page_requests) == 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert sorted(closed) == entered
    assert not auth.users


@pytest.mark.asyncio
async def test_subscription_filter_limit_and_compatibility_order(subscription_auth):
    auth = subscription_auth
    values = await auth.get_subscriptions(
        identifiers=["profile_101", 3, "profile_3"],
        limit=103,
        sub_type="active",
        filter_by="online",
    )
    assert [sub.id for sub in values] == [101, 3, 3]
    assert [sub.id for sub in auth.subscriptions] == [101, 3]
    assert sorted(auth.hydrated) == [3, 101]
    assert [(o, size) for o, size, _ in auth.page_requests] == [(0, 100), (100, 3)]
    assert all(
        query["type"] == ["active"] and query["filter[online]"] == ["1"]
        for _, _, query in auth.page_requests
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [-1, True, 1.5])
async def test_subscription_invalid_limit_never_requests(subscription_auth, limit):
    with pytest.raises(ValueError, match="limit"):
        await anext(subscription_auth.iter_subscriptions(limit=limit))
    assert not subscription_auth.page_requests


@pytest.mark.asyncio
async def test_subscription_zero_limit_does_no_work(subscription_auth):
    assert [sub async for sub in subscription_auth.iter_subscriptions(limit=0)] == []
    assert not subscription_auth.page_requests
    assert not subscription_auth.hydrated


@pytest.mark.asyncio
async def test_subscription_explicit_concurrency_overrides_environment(
    subscription_auth, monkeypatch
):
    monkeypatch.setenv("ULTIMA_SUBSCRIPTION_HYDRATION_CONCURRENCY", "invalid")
    async with aclosing(
        subscription_auth.iter_subscriptions(concurrency=257, limit=1)
    ) as stream:
        assert (await anext(stream)).id == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("setting", ["0", "-2", "1.5", "invalid"])
async def test_subscription_batch_budget_rejects_invalid_values(monkeypatch, setting):
    monkeypatch.setattr(handler, "runtime_env_value", lambda _: setting)
    with pytest.raises(ValueError, match="positive integer"):
        await anext(handler._subscription_batches([]))


@pytest.mark.asyncio
async def test_subscription_commit_backpressure_and_exact_counts(
    subscription_auth, monkeypatch
):
    auth = subscription_auth
    monkeypatch.setattr(handler, "runtime_env_value", lambda _: "17")
    monkeypatch.setattr(handler, "_persist_subscription_task_progress", AsyncMock())
    monkeypatch.setattr(handler, "publish_subscription_progress", AsyncMock())
    submissions = []
    committed = 0

    async def submit(operation, payload, **kwargs):
        nonlocal committed
        rows = payload["subscriptions"]
        assert len(rows) <= 17
        # Only the page that includes this batch's end may have been hydrated.
        assert len(auth.hydrated) <= min(
            ((committed + len(rows) - 1) // 100 + 1) * 100, auth.total
        )
        assert [row["user_id"] for row in rows] == list(
            range(committed, committed + len(rows))
        )
        assert all(row["user"]["user"]["about"] == "fresh" for row in rows)
        submissions.append(kwargs["command_id"])
        await asyncio.sleep(0)
        committed += len(rows)
        return {"processed": len(rows), "saved": len(rows), "updated": 0}

    result = await handler._save_subscriptions_to_db(
        auth.iter_subscriptions(),
        auth,
        SimpleNamespace(submit=submit),
        "onlyfans",
        SimpleNamespace(task_id="subscription-task"),
        SimpleNamespace(job_id="subscription-job"),
        "test",
        None,
    )
    assert result == {
        "success": True,
        "message": "Subscriptions saved",
        "errors": [],
        "count": 205,
        "processed": 205,
        "saved": 205,
        "updated": 0,
    }
    assert len(submissions) == 13
    assert len(set(submissions)) == len(submissions)
    assert len(auth.hydrated) == auth.total  # No second refresh in the write layer.
    assert not auth.users and not auth.cache_activations


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["writer", "source", "cancel"])
async def test_subscription_failure_closes_source_and_stops_discovery(
    monkeypatch, failure
):
    monkeypatch.setattr(handler, "runtime_env_value", lambda _: "3")
    monkeypatch.setattr(handler, "_persist_subscription_task_progress", AsyncMock())
    monkeypatch.setattr(handler, "publish_subscription_progress", AsyncMock())
    produced = []
    closed = []

    async def subscriptions():
        try:
            for i in range(1_000_000):
                if failure == "source" and i == 3:
                    raise RuntimeError("page failed")
                produced.append(i)
                yield SimpleNamespace(id=i, username=f"u{i}", profile_refreshed=True)
        finally:
            closed.append(True)

    async def submit(*args, **kwargs):
        if failure == "cancel":
            raise asyncio.CancelledError
        if failure == "writer":
            raise RuntimeError("writer failed")
        return {"processed": 3, "saved": 3, "updated": 0}

    call = handler._save_subscriptions_to_db(
        subscriptions(),
        SimpleNamespace(id=99),
        SimpleNamespace(submit=submit),
        "onlyfans",
        SimpleNamespace(task_id="task"),
        SimpleNamespace(job_id="job"),
        "test",
        None,
    )
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await call
    else:
        result = await call
        assert not result["success"]
        assert result["processed"] == (3 if failure == "source" else 0)
    assert produced == [0, 1, 2]
    assert closed == [True]


@pytest.mark.asyncio
async def test_subscription_no_save_stream_failure_returns_task_result(
    subscription_auth, monkeypatch
):
    monkeypatch.setattr(handler, "_persist_subscription_task_progress", AsyncMock())
    monkeypatch.setattr(handler, "publish_subscription_progress", AsyncMock())

    async def failed_stream(**kwargs):
        raise RuntimeError("upstream unavailable")
        yield

    subscription_auth.iter_subscriptions = failed_stream
    task = SimpleNamespace(
        user_id=99, payload=SimpleNamespace(save_to_db=False, reload_workers=False)
    )
    context = SimpleNamespace(
        worker_id="test",
        site="onlyfans",
        site_api=SimpleNamespace(auths=[subscription_auth]),
        job=SimpleNamespace(job_id="job"),
        storage=None,
    )
    result = await handler.handle_get_subscriptions(task, context)
    assert not result.success
    assert result.errors == ["upstream unavailable"]
