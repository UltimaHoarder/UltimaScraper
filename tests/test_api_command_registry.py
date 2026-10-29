from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ultima_scraper_backend.api.routes import api_requests as api_requests_module
from ultima_scraper_backend.job_system.handlers import (
    api_command as api_command_module,
)
from ultima_scraper_backend.manager import (
    API_COMMAND_MAP,
    API_COMMANDS,
    BackendManager,
    BackendResult,
)

_RECENTLY_MISSING_COMMANDS = (
    "get_mass_message_stats",
    "get_subscription_count",
    "blocked_users",
    "restricted_users",
)


@pytest.mark.parametrize("command_name", _RECENTLY_MISSING_COMMANDS)
def test_api_commands_are_registered_across_entrypoints(command_name: str) -> None:
    descriptor = API_COMMAND_MAP.get(command_name)

    assert descriptor is not None
    assert hasattr(BackendManager, descriptor.handler)
    assert command_name in api_command_module._API_COMMAND_HANDLERS
    assert command_name in api_requests_module.ALLOWED_METHODS


@pytest.mark.asyncio
async def test_api_request_method_catalog_tracks_backend_descriptors() -> None:
    response = await api_requests_module.list_methods()

    assert set(response["methods"]) == {descriptor.name for descriptor in API_COMMANDS}
    assert response["methods"]["get_transactions"]["args"]["limit"]["default"] == 20
    assert "filter_by" in response["methods"]["get_subscriptions"]["args"]


@pytest.mark.asyncio
async def test_run_api_command_executes_blocked_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = BackendManager.__new__(BackendManager)
    manager._api_command_map = API_COMMAND_MAP

    mock_submit = AsyncMock(
        return_value=BackendResult(
            True,
            "API command 'blocked_users' completed.",
            {
                "blocked_users": [
                    {
                        "id": 17,
                        "username": "blocked-user",
                        "name": "Blocked User",
                        "raw": {"id": 17, "username": "blocked-user"},
                    }
                ]
            },
        )
    )
    monkeypatch.setattr(manager, "_submit_worker_api_command", mock_submit)

    result = await manager.run_api_command(
        "onlyfans",
        "blocked_users",
        {"limit": 1, "offset": 0},
        account_id=77,
    )

    assert result.success is True
    mock_submit.assert_awaited_once_with(
        "onlyfans",
        "blocked_users",
        {"limit": 1, "offset": 0},
        77,
        priority=-10,
    )
    assert result.payload == {
        "blocked_users": [
            {
                "id": 17,
                "username": "blocked-user",
                "name": "Blocked User",
                "raw": {"id": 17, "username": "blocked-user"},
            }
        ]
    }


@pytest.mark.asyncio
async def test_api_command_task_handler_executes_blocked_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_user = SimpleNamespace(
        id=29,
        username="blocked-two",
        name="Blocked Two",
        raw={"id": 29, "username": "blocked-two"},
    )
    authed = SimpleNamespace(
        blocked_users=AsyncMock(return_value=[blocked_user]),
    )
    redis_client = SimpleNamespace(publish=AsyncMock())
    api = SimpleNamespace(find_auth=lambda account_id: authed)
    context = SimpleNamespace(
        worker_id="worker-1",
        site="onlyfans",
        site_api=api,
        job=SimpleNamespace(job_id="job-1"),
        storage=SimpleNamespace(redis=SimpleNamespace(client=redis_client)),
    )
    task = SimpleNamespace(
        payload=SimpleNamespace(
            command="blocked_users", args={"limit": 2, "offset": 0}
        ),
        auth_id=55,
        task_id="task-1",
    )

    monkeypatch.setattr(api_command_module, "publish_api_command_result", AsyncMock())

    result = await api_command_module.handle_api_command_task(task, context)

    assert result.success is True
    authed.blocked_users.assert_awaited_once_with(limit=2, offset=0)
    assert result.output == {
        "blocked_users": [
            {
                "id": 29,
                "username": "blocked-two",
                "name": "Blocked Two",
                "raw": {"id": 29, "username": "blocked-two"},
            }
        ],
        "count": 1,
    }
    redis_client.publish.assert_awaited_once()


def test_api_command_defaults_run_before_normal_ready_tasks():
    import inspect
    from ultima_scraper_backend.job_system.routing import BackendRouter

    for method in (BackendManager.run_api_command, BackendManager._submit_worker_api_command):
        priority = inspect.signature(method).parameters["priority"].default
        assert priority * BackendRouter.READY_SCORE_SCALE < 0
