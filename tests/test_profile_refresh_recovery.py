"""Profile reads recover lost workers without replaying unrelated API mutations."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from ultima_scraper_backend.api.routes import users
from ultima_scraper_backend.job_system.api_command_policy import WORKER_LEASE_EXHAUSTED
from ultima_scraper_backend.job_system.models import TaskState
from ultima_scraper_backend.manager import BackendManager


@pytest.mark.parametrize("command,attempts", [("refresh_profile", 3), ("invoke_api_method", 1)])
async def test_profile_reads_have_recovery_budget_but_other_commands_do_not(command, attempts):
    manager = BackendManager.__new__(BackendManager)
    prepare = AsyncMock(side_effect=lambda job, **kwargs: job)
    manager._job_manager = SimpleNamespace(prepare_job=prepare, activate_job=AsyncMock())
    manager._job_storage = SimpleNamespace(fetch_task=AsyncMock(return_value=SimpleNamespace(
        state=TaskState.COMPLETED,
        result=SimpleNamespace(success=True, message='done', output={}),
    )))
    await manager._submit_worker_api_command('onlyfans', command, {}, None, guest=True)
    assert prepare.await_args.args[0].tasks[0].max_attempts == attempts


@pytest.fixture
def refresh_setup(monkeypatch):
    saved = SimpleNamespace(username='creator', last_checked_at=datetime.now(UTC)-timedelta(days=30))
    @contextmanager
    def session():
        yield object()
    site_db = SimpleNamespace(get_session=session)
    monkeypatch.setattr(users, '_find_exact_existing_user', lambda *args: saved)
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(users, 'run_database_call', inline)
    persist = AsyncMock(return_value=True)
    monkeypatch.setattr(users, '_refresh_stale_existing_user', persist)
    monkeypatch.setattr(users, '_publish_profile_updated', AsyncMock())
    monkeypatch.setattr(users, '_profile_refresh_errors', {})
    return site_db, persist


@pytest.mark.parametrize('structured', [False, True])
async def test_expired_saved_job_joins_one_replacement_across_processes(monkeypatch, refresh_setup, structured):
    site_db, persist = refresh_setup
    expired = SimpleNamespace(success=False, message=WORKER_LEASE_EXHAUSTED,
                              payload={'error_code': 'worker_lease_expired'} if structured else {})
    completed = SimpleNamespace(success=True, message='done', payload={'lookups': {'123': {}}})
    submit = AsyncMock(side_effect=[expired, completed, expired, completed])
    monkeypatch.setattr(users, 'get_backend_manager', lambda: SimpleNamespace(_submit_worker_api_command=submit))
    assert await users._run_profile_refresh('onlyfans', 123, site_db)
    assert await users._run_profile_refresh('onlyfans', 123, site_db)
    identities = [call.kwargs['idempotency_key'] for call in submit.await_args_list]
    assert identities[0] == identities[2]
    assert identities[1] == identities[3] == identities[0]+':lease-recovery-v1'
    assert persist.await_count == 2


async def test_recovery_stops_at_replacement_budget_and_preserves_real_errors(monkeypatch, refresh_setup):
    site_db, persist = refresh_setup
    submit = AsyncMock(return_value=SimpleNamespace(success=False, message=WORKER_LEASE_EXHAUSTED, payload={}))
    monkeypatch.setattr(users, 'get_backend_manager', lambda: SimpleNamespace(_submit_worker_api_command=submit))
    assert not await users._run_profile_refresh('onlyfans', 123, site_db)
    assert submit.await_count == 2
    persist.assert_not_awaited()
    submit.reset_mock()
    submit.return_value = SimpleNamespace(success=False, message='Upstream rejected the request', payload={})
    assert not await users._run_profile_refresh('onlyfans', 123, site_db)
    submit.assert_awaited_once()
    assert users._profile_refresh_errors[('onlyfans', 123)] == 'Upstream rejected the request'


async def test_queue_timeout_keeps_waiting_for_same_job_instead_of_latching_failure(monkeypatch, refresh_setup):
    site_db, persist = refresh_setup
    submit = AsyncMock(side_effect=[
        SimpleNamespace(success=False, message='wait timed out', payload={'pending': True}),
        SimpleNamespace(success=True, message='done', payload={'lookups': {}}),
    ])
    monkeypatch.setattr(users, 'get_backend_manager', lambda: SimpleNamespace(_submit_worker_api_command=submit))
    assert await users._run_profile_refresh('onlyfans', 123, site_db, force=True)
    assert submit.await_count == 2
    assert submit.await_args_list[0].kwargs['idempotency_key'] == submit.await_args_list[1].kwargs['idempotency_key']
    persist.assert_awaited_once()
    assert users._profile_refresh_errors == {}
