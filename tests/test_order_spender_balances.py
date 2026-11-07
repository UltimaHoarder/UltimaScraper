from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from ultima_scraper_backend.api.routes import orders as orders_module


class _Result:
    def __init__(self, value: Any = None, values: list[Any] | None = None) -> None:
        self._value = value
        self._values = values or []

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._values)


class _Session:
    def __init__(self, results: list[_Result]) -> None:
        self._results = results
        # Whether a transaction is open, as PgBouncer sees it.
        self.in_transaction = False

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.in_transaction = False

    def execute(self, _statement: Any) -> _Result:
        self.in_transaction = True
        return self._results.pop(0)


@pytest.mark.asyncio
async def test_refresh_prices_refreshes_every_spender_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    order = orders_module.OrderModel(id=85, site_id=3, status="pending", total_price=0.0, created_at=now)
    site = orders_module.SiteModel(id=3, name="onlyfans", created_at=now)
    session = _Session([_Result("onlyfans"), _Result(order), _Result(site), _Result(values=[])])
    sessions = {1: object(), 2: object()}
    open_during_refresh: list[bool] = []

    async def get_authed_session(site_name: str, auth_id: int) -> Any:
        if auth_id == 3:
            raise RuntimeError("no worker session")
        return sessions[auth_id]

    async def refresh(*, site: str, authed: Any, auth_id: int) -> float:
        open_during_refresh.append(session.in_transaction)
        assert authed is sessions[auth_id]
        return 50.0

    refresh_mock = AsyncMock(side_effect=refresh)
    monkeypatch.setattr(orders_module, "ensure_orders_schema", lambda: None)
    monkeypatch.setattr(orders_module, "create_orders_session", lambda: session)
    monkeypatch.setattr(
        orders_module,
        "_get_candidate_auth_ids",
        lambda site_name, price=None: [(1, "paid"), (3, "all"), (2, "free")],
    )
    monkeypatch.setattr(orders_module, "_refresh_spender_balance_after_purchase", refresh_mock)

    response = await orders_module.check_order(
        order_id=order.id,
        backend_manager=SimpleNamespace(get_authed_session=get_authed_session),
    )

    assert response.success is True
    # Every spender of the site, free and paid; one without a session is skipped.
    assert [c.kwargs["auth_id"] for c in refresh_mock.await_args_list] == [1, 2]
    assert open_during_refresh == [False, False]


@pytest.mark.asyncio
async def test_spender_balance_comes_from_the_accounts_own_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    me = SimpleNamespace(id=53348944, credit_balance=52.14)
    get_user = AsyncMock(return_value=SimpleNamespace(id=53348944, credit_balance=32.14))
    authed = SimpleNamespace(get_me=AsyncMock(return_value=me), get_user=get_user)
    sync = AsyncMock()
    monkeypatch.setattr(
        orders_module,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(get_or_create_manager=lambda site: object()),
    )
    monkeypatch.setattr(orders_module, "sync_user_from_api", sync)

    balance = await orders_module._refresh_spender_balance_after_purchase(
        site="onlyfans", authed=authed, auth_id=53348944
    )

    # /users/me has the top-up; the login profile and /users/{id} may not.
    assert balance == 52.14
    assert sync.await_args.args[1] is me
    get_user.assert_not_awaited()
