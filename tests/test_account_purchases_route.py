from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from ultima_scraper_backend.api.routes.account_purchases import (
    AccountPurchaseRequest,
    _confirmed_balance_charge,
    _quote_purchase,
    _resolve_authed_account,
)


def test_confirmed_charge_requires_matching_refreshed_balance_delta() -> None:
    charge, confirmed = _confirmed_balance_charge(
        Decimal("100.00"),
        80,
        Decimal("20.00"),
        Decimal("20.00"),
    )
    assert charge == Decimal("20.00")
    assert confirmed is True

    stale_charge, stale_confirmed = _confirmed_balance_charge(
        Decimal("100.00"),
        100,
        Decimal("20.00"),
        Decimal("20.00"),
    )
    assert stale_charge == Decimal("0.00")
    assert stale_confirmed is False


@pytest.mark.asyncio
async def test_subscription_quote_treats_existing_access_as_zero_incremental_cost() -> None:
    class FakeAuthed:
        async def get_user(self, _identifier: object) -> object:
            return SimpleNamespace(subscription_price=20)

        async def get_subscription(self, _identifier: object) -> object:
            return object()

    payload = AccountPurchaseRequest(
        site="onlyfans",
        auth_record_id=1,
        site_account_user_id=2,
        required_proxy_id="socks5://chain.local:1080",
        purchase_type="subscription",
        creator_id="3",
        maximum_charge_usd=Decimal("20"),
    )

    quote, already_owned, error = await _quote_purchase(payload, FakeAuthed())

    assert quote == Decimal("0.00")
    assert already_owned is True
    assert error is None


@pytest.mark.asyncio
async def test_ppv_quote_treats_viewable_media_as_zero_incremental_cost() -> None:
    class FakeUser:
        async def get_post(self, *, identifier: int) -> object:
            assert identifier == 44
            return SimpleNamespace(price=9.99, canViewMedia=True)

    class FakeAuthed:
        def find_user(self, creator_id: int) -> object:
            assert creator_id == 3
            return FakeUser()

    payload = AccountPurchaseRequest(
        site="onlyfans",
        auth_record_id=1,
        site_account_user_id=2,
        required_proxy_id="socks5://chain.local:1080",
        purchase_type="ppv",
        creator_id="3",
        post_id=44,
        content_type="post",
        maximum_charge_usd=Decimal("9.99"),
    )

    quote, already_owned, error = await _quote_purchase(payload, FakeAuthed())

    assert quote == Decimal("0.00")
    assert already_owned is True
    assert error is None


@pytest.mark.asyncio
async def test_selected_account_refuses_a_changed_proxy_assignment(monkeypatch) -> None:
    import ultima_scraper_backend.api.routes.account_purchases as route_module

    auth_record = SimpleNamespace(
        id=1,
        site="onlyfans",
        user_id=2,
        active=True,
        proxy_id="socks5://unexpected.local:1080",
    )

    class FakeResult:
        def first(self) -> object:
            return auth_record

    class FakeSession:
        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def exec(self, _statement: object) -> FakeResult:
            return FakeResult()

    site_database = SimpleNamespace(get_session=lambda: FakeSession())
    database_manager = SimpleNamespace(
        get_or_create_manager=lambda _site: site_database
    )
    monkeypatch.setattr(
        route_module,
        "MultiSiteDatabaseManager",
        lambda: database_manager,
    )
    backend_manager = SimpleNamespace(
        get_authed_session=lambda *_args: pytest.fail(
            "session lookup must not occur after a proxy mismatch"
        )
    )
    payload = AccountPurchaseRequest(
        site="onlyfans",
        auth_record_id=1,
        site_account_user_id=2,
        required_proxy_id="socks5://verified.local:1080",
        purchase_type="subscription",
        creator_id="3",
        maximum_charge_usd=Decimal("20"),
    )

    authed, error = await _resolve_authed_account(payload, backend_manager)

    assert authed is None
    assert error == "proxy_assignment_mismatch"
