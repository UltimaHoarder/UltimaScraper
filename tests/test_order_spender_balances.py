from __future__ import annotations

import asyncio
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


@pytest.mark.asyncio
async def test_a_spenders_session_has_its_real_balance_before_an_order_buys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=53348944, credit_balance=8.75)

    async def get_me() -> Any:
        # The site has the top-up that this API process's session missed.
        user.credit_balance = 79.05
        return user

    authed = SimpleNamespace(get_me=AsyncMock(side_effect=get_me))
    backend_manager = SimpleNamespace(get_authed_session=AsyncMock(return_value=authed))
    monkeypatch.setattr(
        orders_module,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(get_or_create_manager=lambda site: object()),
    )
    monkeypatch.setattr(orders_module, "sync_user_from_api", AsyncMock())
    auth_cache: dict[int, Any] = {}

    for _ in range(2):
        session = await orders_module._get_cached_authed_session(
            site="onlyfans",
            auth_id=53348944,
            backend_manager=backend_manager,
            auth_cache=auth_cache,
        )

    assert session is authed
    assert user.credit_balance == 79.05
    # Once per order: each purchase refreshes it again afterwards.
    authed.get_me.assert_awaited_once()


@pytest.mark.asyncio
async def test_choosing_a_spender_for_one_item_sees_a_top_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=53348944, credit_balance=8.75)

    async def get_me() -> Any:
        user.credit_balance = 79.05
        return user

    authed = SimpleNamespace(
        get_me=AsyncMock(side_effect=get_me),
        get_authed_user=AsyncMock(return_value=user),
    )
    monkeypatch.setattr(
        orders_module,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(get_or_create_manager=lambda site: object()),
    )
    monkeypatch.setattr(orders_module, "sync_user_from_api", AsyncMock())
    monkeypatch.setattr(
        orders_module, "_get_candidate_auth_ids", lambda site, price: [(53348944, "paid")]
    )

    selection = await orders_module._select_spender(
        "onlyfans",
        19.99,
        SimpleNamespace(get_authed_session=AsyncMock(return_value=authed)),
    )

    assert selection == (authed, 53348944, 79.05)


def _payment_methods(percent: float) -> dict[str, Any]:
    return {
        "cards": [
            {"isInternal": False, "vatPercent": 21.0},
            {"isInternal": True, "vatPercent": percent, "taxPercent": 0, "mediaTaxPercent": 0},
        ]
    }


@pytest.mark.parametrize(
    ("balance", "tax_percent", "spendable"),
    [(10.77, 8.25, 9.94), (10.77, 0.0, 10.77), (10.77, None, 10.77), (0.0, 8.25, 0.0)],
)
def test_a_balance_is_what_it_can_pay_once_tax_is_added(
    balance: float, tax_percent: float | None, spendable: float
) -> None:
    assert orders_module._after_tax(balance, tax_percent) == spendable


@pytest.mark.asyncio
async def test_the_spenders_tax_is_read_from_the_site_and_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = SimpleNamespace(id=53348944, wallet_tax_percent=None)
    session = SimpleNamespace(get=lambda model, key: stored, add=lambda row: None, commit=lambda: None)

    class _Context:
        def __enter__(self) -> Any:
            return session

        def __exit__(self, *_args: Any) -> None:
            return None

    site_db = SimpleNamespace(get_session=_Context)
    monkeypatch.setattr(
        orders_module,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(get_or_create_manager=lambda site: site_db),
    )
    requester = SimpleNamespace(json_request=AsyncMock(return_value=_payment_methods(8.25)))
    authed = SimpleNamespace(get_requester=lambda: requester)

    percent = await orders_module._refresh_spender_tax(
        site="onlyfans", authed=authed, auth_id=53348944
    )

    assert percent == 8.25
    assert stored.wallet_tax_percent == 8.25
    assert "methods-vat" in requester.json_request.await_args.args[0]


@pytest.mark.asyncio
async def test_other_sites_ask_for_no_tax() -> None:
    authed = SimpleNamespace(get_requester=AsyncMock())

    percent = await orders_module._refresh_spender_tax(
        site="fansly", authed=authed, auth_id=1
    )

    assert percent is None
    authed.get_requester.assert_not_called()


@pytest.mark.asyncio
async def test_the_chat_balance_asks_for_a_tax_it_does_not_have(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orders_module, "_get_stored_tax_percents", lambda site, ids: {})
    monkeypatch.setattr(orders_module, "_refresh_spender_tax", AsyncMock(return_value=8.25))

    spendable = await orders_module._spendable_balance(
        site="onlyfans", authed=SimpleNamespace(), auth_id=53348944, balance=10.77
    )

    assert spendable == 9.94


def test_a_spender_that_cant_cover_the_tax_is_not_chosen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        orders_module, "_get_stored_tax_percents", lambda site, ids: {53348944: 8.25}
    )
    monkeypatch.setattr(
        orders_module, "_get_candidate_auth_ids", lambda site, price: [(53348944, "paid")]
    )
    user = SimpleNamespace(id=53348944, credit_balance=10.77)
    authed = SimpleNamespace(
        get_me=AsyncMock(return_value=user), get_authed_user=AsyncMock(return_value=user)
    )
    monkeypatch.setattr(
        orders_module,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(get_or_create_manager=lambda site: None),
    )

    selection = asyncio.run(
        orders_module._select_spender(
            "onlyfans", 9.99, SimpleNamespace(get_authed_session=AsyncMock(return_value=authed))
        )
    )

    assert selection is None
