"""The System page can restart or stop only the launcher that owns this API."""

import os
import signal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from ultima_scraper_backend.api.routes import system as system_module


def _owned_by(monkeypatch, *ancestor_pids):
    monkeypatch.setattr(system_module.psutil, "Process", lambda: SimpleNamespace(
        parents=lambda: [SimpleNamespace(pid=pid) for pid in ancestor_pids]))


@pytest.fixture
def scheduled(monkeypatch):
    calls = []
    loop = SimpleNamespace(call_later=lambda delay, *call: calls.append((delay, call)))
    monkeypatch.setattr(system_module.asyncio, "get_running_loop", lambda: loop)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("action,signum", [
    ("restart", signal.SIGUSR1),
    ("shutdown", signal.SIGTERM),
])
async def test_power_action_signals_the_owning_launcher_after_responding(
    monkeypatch, scheduled, action, signum,
):
    monkeypatch.setenv(system_module.SUPERVISOR_PID_ENV, "4242")
    _owned_by(monkeypatch, 4300, 4242, 1)

    response = await system_module.control_runtime_power(
        system_module.RuntimePowerRequest(action=action))

    assert response.supervisor_pid == 4242
    assert response.action == action
    assert scheduled == [(system_module.POWER_SIGNAL_DELAY_SECONDS, (os.kill, 4242, signum))]


@pytest.mark.asyncio
@pytest.mark.parametrize("pid", [None, "not-a-pid", "1", "4242"])
async def test_power_action_refuses_a_launcher_that_does_not_own_this_api(
    monkeypatch, scheduled, pid,
):
    # 4242 is a live PID here but not an ancestor (reused or foreign process).
    if pid is None:
        monkeypatch.delenv(system_module.SUPERVISOR_PID_ENV, raising=False)
    else:
        monkeypatch.setenv(system_module.SUPERVISOR_PID_ENV, pid)
    _owned_by(monkeypatch, 4300, 1)

    with pytest.raises(HTTPException) as caught:
        await system_module.control_runtime_power(
            system_module.RuntimePowerRequest(action="shutdown"))

    assert caught.value.status_code == 409
    assert scheduled == []
