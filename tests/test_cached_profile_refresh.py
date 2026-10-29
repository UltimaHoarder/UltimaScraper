"""Cached list delivery, bounded card reads, and post-response refresh scheduling."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from ultima_scraper_backend.services import profile_refresh
from ultima_scraper_backend.api.routes import users, favourites, websocket_topics


def test_only_stale_qualified_users_are_scheduled_after_response(monkeypatch):
    now = datetime.now(timezone.utc)
    background = BackgroundTasks()
    rows = [
        {'site': 'OnlyFans', 'user_id': 1, 'last_checked_at': None},
        {'site': 'onlyfans', 'user_id': 1, 'last_checked_at': None},
        {'site': 'fansly', 'user_id': 1, 'last_checked_at': (now-timedelta(days=8)).isoformat()},
        {'site': 'onlyfans', 'user_id': 2, 'last_checked_at': now.isoformat()},
    ]
    refresh = AsyncMock()
    monkeypatch.setattr(profile_refresh, 'refresh_cached_profiles', refresh)
    profile_refresh.queue_cached_profile_refresh(background, rows)
    refresh.assert_not_called()
    assert len(background.tasks) == 1
    assert background.tasks[0].args == ([('fansly', 1), ('onlyfans', 1)],)


async def test_refresh_scheduler_reuses_existing_per_user_dispatch(monkeypatch):
    calls = []
    site_db = object()
    from ultima_scraper_backend.database import factory
    monkeypatch.setattr(factory, 'MultiSiteDatabaseManager', lambda: SimpleNamespace(
        get_or_create_manager=lambda site: site_db))
    monkeypatch.setattr(users, '_ensure_profile_refresh_started', lambda *args: calls.append(args))
    await profile_refresh.refresh_cached_profiles([('onlyfans', 7), ('fansly', 7)])
    assert calls == [('onlyfans', 7, site_db), ('fansly', 7, site_db)]


def test_card_reads_are_bounded_and_validate_qualified_keys():
    users.UserCardsRequest(keys=[{'site': 'onlyfans', 'user_id': i+1} for i in range(200)])
    with pytest.raises(ValidationError):
        users.UserCardsRequest(keys=[{'site': 'onlyfans', 'user_id': i+1} for i in range(201)])
    with pytest.raises(ValidationError):
        users.UserCardsRequest(keys=[{'site': 'onlyfans', 'user_id': 0}])


def test_card_endpoint_returns_cached_profile_before_refresh_callback(monkeypatch):
    from ultima_scraper_db_archive import global_db
    @contextmanager
    def session():
        yield object()
    monkeypatch.setattr(global_db, 'global_session', session)
    profile = {'site': 'onlyfans', 'user_id': 7, 'last_checked_at': None, 'name': 'Cached name'}
    received = []
    def metadata(session, keys, **kwargs):
        received.append((keys, kwargs))
        return {('onlyfans', 'user', 7): profile}
    monkeypatch.setattr(users.favourites_service, 'resolve_metadata', metadata)
    async def inline(call, *args, **kwargs):
        return call(*args, **kwargs)
    monkeypatch.setattr(users, 'run_database_call', inline)
    refreshed = []
    async def refresh(keys):
        assert 'http.response.body' in sent
        refreshed.extend(keys)
    monkeypatch.setattr(profile_refresh, 'refresh_cached_profiles', refresh)
    sent = []
    class CaptureResponse:
        def __init__(self, app): self.app = app
        async def __call__(self, scope, receive, send):
            async def record(message):
                sent.append(message['type'])
                await send(message)
            await self.app(scope, receive, record)
    app = FastAPI()
    app.include_router(users.router)
    with TestClient(CaptureResponse(app)) as client:
        response = client.post('/users/cards', json={'keys': [{'site': 'OnlyFans', 'user_id': 7}]})
        assert response.status_code == 200
        assert response.json()['users'][0]['name'] == 'Cached name'
        assert refreshed == [('onlyfans', 7)]
        assert client.post('/users/cards', json={'keys': [{'site': 'invalid', 'user_id': 7}]}).status_code == 422
    assert received == [([{'site': 'onlyfans', 'entity_type': 'user', 'entity_id': 7}], {'favourite_users': False})]


def test_favourites_queues_only_user_previews(monkeypatch):
    @contextmanager
    def session(): yield object()
    monkeypatch.setattr(favourites, 'global_session', session)
    monkeypatch.setattr(favourites.service, 'ensure_active', lambda *args: None)
    cached = {'items': [
        {'entity_type': 'user', 'entity': {'site': 'onlyfans', 'user_id': 7, 'last_checked_at': None}},
        {'entity_type': 'post', 'entity': {'site': 'onlyfans', 'user_id': 9}},
        {'entity_type': 'user', 'entity': None},
    ]}
    monkeypatch.setattr(favourites.service, 'list_favourites', lambda *args: cached)
    background = BackgroundTasks()
    assert favourites.list_favourites(background, search='', limit=50, cursor=None) is cached
    assert background.tasks[0].args == ([('onlyfans', 7)],)


def test_profile_hints_route_to_profile_subscribers():
    assert websocket_topics.event_topics({'type': 'user_profile_updated', 'site': 'onlyfans', 'user_id': 7}) == ('profiles',)
    assert websocket_topics.valid_topics(['profiles', 'bogus']) == frozenset({'profiles'})


async def test_worker_job_identity_is_stable_for_a_profile_version_and_isolated_by_site():
    from ultima_scraper_backend.manager import BackendManager
    from ultima_scraper_backend.job_system.models import TaskState
    manager = BackendManager.__new__(BackendManager)
    async def prepared(job, **kwargs): return job
    prepare = AsyncMock(side_effect=prepared)
    manager._job_manager = SimpleNamespace(prepare_job=prepare, activate_job=AsyncMock())
    manager._job_storage = SimpleNamespace(fetch_task=AsyncMock(return_value=SimpleNamespace(
        state=TaskState.COMPLETED, result=SimpleNamespace(success=True, message='done', output={'lookups':{}}))))
    for site, version in [('onlyfans','missing'),('onlyfans','missing'),('fansly','missing'),('onlyfans','new')]:
        result = await manager._submit_worker_api_command(site, 'refresh_profile', {'user_id':7}, None,
            guest=True, idempotency_key=f'profile:{site}:7:{version}')
        assert result.success
    jobs = [call.args[0] for call in prepare.await_args_list]
    assert jobs[0].job_id == jobs[1].job_id
    assert jobs[0].tasks[0].task_id == jobs[1].tasks[0].task_id
    assert len({job.job_id for job in jobs}) == 3
    assert all(job.metadata['admission_idempotent'] for job in jobs)
