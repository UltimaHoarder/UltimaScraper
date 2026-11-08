"""A subscribed toast brings a saved subscription that has lapsed back to life."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from ultima_scraper_backend import websocket_actions

AUTH_ID = 1000
PERFORMER_ID = 2000


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value


class _Session:
    """Answers the user lookup, then the subscription lookups, in query order."""

    def __init__(self, *results: Any) -> None:
        self.results = list(results)
        self.added: list[Any] = []
        self.commits = 0

    def __call__(self, _engine: Any) -> _Session:
        return self

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def exec(self, _statement: Any) -> _Result:
        return _Result(self.results.pop(0))

    def add(self, row: Any) -> None:
        self.added.append(row)

    def commit(self) -> None:
        self.commits += 1


async def _save(
    monkeypatch: pytest.MonkeyPatch,
    session: _Session,
    *,
    subscribed_by: bool = True,
    subscribed_on: bool = False,
) -> None:
    handler = websocket_actions.WebSocketActionHandler(SimpleNamespace(database_writes=object()))
    handler.engine = object()
    handler.redis = None
    monkeypatch.setattr(websocket_actions, "Session", session)
    await handler._save_toast_subscription_to_db(
        authed_id=AUTH_ID,
        related_user={"id": PERFORMER_ID, "username": "performer"},
        subscribed_by=subscribed_by,
        subscribed_on=subscribed_on,
        site_name="onlyfans",
    )


def _renewed(row: SimpleNamespace) -> bool:
    return row.active is True and row.expires_at > datetime.now(timezone.utc) + timedelta(days=29)


@pytest.mark.asyncio
async def test_a_subscribed_toast_renews_an_expired_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SimpleNamespace(active=False, expires_at=datetime(2026, 8, 13, 21, 27, tzinfo=timezone.utc))
    session = _Session(SimpleNamespace(id=PERFORMER_ID), row)

    await _save(monkeypatch, session)

    assert _renewed(row)
    assert session.commits == 1
    assert session.added == []


@pytest.mark.asyncio
async def test_an_active_row_past_its_date_is_renewed_even_when_naive(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SimpleNamespace(active=True, expires_at=datetime(2026, 8, 13, 21, 27))
    session = _Session(SimpleNamespace(id=PERFORMER_ID), row)

    await _save(monkeypatch, session)

    assert _renewed(row)


@pytest.mark.asyncio
async def test_a_current_subscription_keeps_its_real_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(days=200)
    row = SimpleNamespace(active=True, expires_at=expires_at)
    session = _Session(SimpleNamespace(id=PERFORMER_ID), row)

    await _save(monkeypatch, session)

    assert row.active is True
    assert row.expires_at == expires_at


@pytest.mark.asyncio
async def test_a_subscribed_on_toast_renews_the_fans_expired_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SimpleNamespace(active=False, expires_at=datetime(2026, 8, 13, 21, 27, tzinfo=timezone.utc))
    session = _Session(SimpleNamespace(id=PERFORMER_ID), row)

    await _save(monkeypatch, session, subscribed_by=False, subscribed_on=True)

    assert _renewed(row)


@pytest.mark.asyncio
async def test_a_toast_without_a_subscribed_flag_leaves_the_row_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session(SimpleNamespace(id=PERFORMER_ID))

    await _save(monkeypatch, session, subscribed_by=False)

    assert session.added == []
    assert session.results == []
