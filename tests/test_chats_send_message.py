from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from ultima_scraper_backend.api.routes import chats as chats_module


@pytest.mark.asyncio
async def test_a_sent_message_is_reported_for_an_account_without_a_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = SimpleNamespace(
        id=53348944,
        username=None,
        send_message=AsyncMock(return_value={"id": 5}),
    )
    monkeypatch.setattr(chats_module, "_get_db_engine", lambda *_args: None)

    response = await chats_module.send_message(
        site="onlyfans",
        user_id=13372411,
        request=chats_module.SendMessageRequest(text="hello"),
        auth_id=53348944,
        backend_manager=SimpleNamespace(
            get_authed_session=AsyncMock(return_value=auth)
        ),
    )

    assert response.success is True
    assert response.message.from_username == "user_53348944"
