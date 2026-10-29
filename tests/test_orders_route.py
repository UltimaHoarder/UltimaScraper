from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call

import pytest

from ultima_scraper_backend.api.routes import orders as orders_module


class _FakeOrdersRouteResult:
    def __init__(
        self,
        *,
        scalar_one_or_none_value: Any = None,
        scalars_all_value: list[Any] | None = None,
    ) -> None:
        self._scalar_one_or_none_value = scalar_one_or_none_value
        self._scalars_all_value = (
            scalars_all_value if scalars_all_value is not None else []
        )

    def scalar_one_or_none(self) -> Any:
        return self._scalar_one_or_none_value

    def scalars(self) -> _FakeOrdersRouteResult:
        return self

    def all(self) -> list[Any]:
        return list(self._scalars_all_value)


class _FakeOrdersRouteSession:
    def __init__(self, results: list[_FakeOrdersRouteResult]) -> None:
        self._results = results
        self.deleted: list[Any] = []

    def __enter__(self) -> _FakeOrdersRouteSession:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, _statement: Any) -> _FakeOrdersRouteResult:
        if not self._results:
            raise AssertionError("Unexpected execute call")
        return self._results.pop(0)

    def delete(self, value: Any) -> None:
        self.deleted.append(value)

    def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_build_live_spender_list_skips_auths_without_sessions() -> None:
    live_auth = SimpleNamespace(id=9001)
    backend_manager = SimpleNamespace(
        get_authed_session=AsyncMock(side_effect=[None, live_auth])
    )
    auth_cache: dict[int, object | None] = {}

    live_spenders = await orders_module._build_live_spender_list(
        site="onlyfans",
        candidates=[(9002, "all"), (9001, "all")],
        stored_balances={9002: 50.0, 9001: 25.0},
        backend_manager=backend_manager,
        auth_cache=auth_cache,
        require_positive_balance=True,
    )

    assert live_spenders == [(9001, 25.0)]
    assert auth_cache[9002] is None
    assert auth_cache[9001] is live_auth
    backend_manager.get_authed_session.assert_has_awaits(
        [call("onlyfans", 9002), call("onlyfans", 9001)]
    )


@pytest.mark.asyncio
async def test_get_cached_authed_session_caches_failed_lookup() -> None:
    backend_manager = SimpleNamespace(get_authed_session=AsyncMock(return_value=None))
    auth_cache: dict[int, object | None] = {}

    first = await orders_module._get_cached_authed_session(
        site="onlyfans",
        auth_id=41900816,
        backend_manager=backend_manager,
        auth_cache=auth_cache,
    )
    second = await orders_module._get_cached_authed_session(
        site="onlyfans",
        auth_id=41900816,
        backend_manager=backend_manager,
        auth_cache=auth_cache,
    )

    assert first is None
    assert second is None
    backend_manager.get_authed_session.assert_awaited_once_with("onlyfans", 41900816)


@pytest.mark.asyncio
async def test_calculate_order_skips_completed_items_in_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    order = orders_module.OrderModel(
        id=77,
        site_id=3,
        status="incomplete",
        total_price=25.0,
        created_at=now,
    )
    site = orders_module.SiteModel(id=3, name="onlyfans", created_at=now)
    completed_item = orders_module.OrderedPerformerModel(
        id=1,
        order_id=order.id,
        site_id=site.id,
        user_id=1001,
        username="done",
        price=10.0,
        status="completed",
        created_at=now,
    )
    pending_item = orders_module.OrderedPerformerModel(
        id=2,
        order_id=order.id,
        site_id=site.id,
        user_id=1002,
        username="todo",
        price=15.0,
        status="pending",
        created_at=now,
    )

    results = [
        _FakeOrdersRouteResult(scalar_one_or_none_value=order),
        _FakeOrdersRouteResult(scalar_one_or_none_value=site),
        _FakeOrdersRouteResult(scalars_all_value=[completed_item, pending_item]),
    ]

    monkeypatch.setattr(orders_module, "ensure_orders_schema", lambda: None)
    monkeypatch.setattr(
        orders_module,
        "create_orders_session",
        lambda: _FakeOrdersRouteSession(list(results)),
    )
    monkeypatch.setattr(
        orders_module,
        "_get_candidate_auth_ids",
        lambda site_name, price: [(999, "paid")] if price > 0 else [],
    )
    monkeypatch.setattr(
        orders_module,
        "_get_stored_user_balances",
        lambda site_name, auth_ids: {999: 100.0},
    )
    monkeypatch.setattr(
        orders_module,
        "_knapsack_optimize",
        lambda paid_items, spender_balances: {999: list(paid_items)},
    )
    monkeypatch.setattr(
        orders_module,
        "_resolve_spender_usernames",
        lambda site_name, auth_ids: {999: "spender"},
    )

    response = await orders_module.calculate_order(
        order_id=order.id,
        backend_manager=SimpleNamespace(),
    )

    assert response.success is True
    assert response.total_cost == pytest.approx(15.0)
    assert response.unassigned_count == 0
    assert len(response.spenders) == 1
    assert response.spenders[0].auth_id == 999
    assert response.spenders[0].assigned_count == 1
    assert response.spenders[0].assigned_cost == pytest.approx(15.0)

    response_items = {item.id: item for item in response.items}
    assert response_items[completed_item.id].spender_user_id is None
    assert response_items[pending_item.id].spender_user_id == 999


@pytest.mark.asyncio
async def test_calculate_order_includes_failed_items_in_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    order = orders_module.OrderModel(
        id=78,
        site_id=3,
        status="incomplete",
        total_price=28.0,
        created_at=now,
    )
    site = orders_module.SiteModel(id=3, name="onlyfans", created_at=now)
    failed_item = orders_module.OrderedPerformerModel(
        id=1,
        order_id=order.id,
        site_id=site.id,
        user_id=1001,
        username="failed",
        price=23.0,
        status="failed",
        created_at=now,
    )
    pending_item = orders_module.OrderedPerformerModel(
        id=2,
        order_id=order.id,
        site_id=site.id,
        user_id=1002,
        username="todo",
        price=5.0,
        status="pending",
        created_at=now,
    )

    results = [
        _FakeOrdersRouteResult(scalar_one_or_none_value=order),
        _FakeOrdersRouteResult(scalar_one_or_none_value=site),
        _FakeOrdersRouteResult(scalars_all_value=[failed_item, pending_item]),
    ]

    monkeypatch.setattr(orders_module, "ensure_orders_schema", lambda: None)
    monkeypatch.setattr(
        orders_module,
        "create_orders_session",
        lambda: _FakeOrdersRouteSession(list(results)),
    )
    monkeypatch.setattr(
        orders_module,
        "_get_candidate_auth_ids",
        lambda site_name, price: [(999, "paid")] if price > 0 else [],
    )
    monkeypatch.setattr(
        orders_module,
        "_get_stored_user_balances",
        lambda site_name, auth_ids: {999: 100.0},
    )
    monkeypatch.setattr(
        orders_module,
        "_knapsack_optimize",
        lambda paid_items, spender_balances: {999: list(paid_items)},
    )
    monkeypatch.setattr(
        orders_module,
        "_resolve_spender_usernames",
        lambda site_name, auth_ids: {999: "spender"},
    )

    response = await orders_module.calculate_order(
        order_id=order.id,
        backend_manager=SimpleNamespace(),
    )

    assert response.success is True
    assert response.total_cost == pytest.approx(28.0)
    assert response.unassigned_count == 0

    assert len(response.spenders) == 1
    assert response.spenders[0].assigned_count == 2
    assert response.spenders[0].assigned_cost == pytest.approx(28.0)

    response_items = {item.id: item for item in response.items}
    assert response_items[failed_item.id].spender_user_id == 999
    assert response_items[pending_item.id].spender_user_id == 999


@pytest.mark.asyncio
async def test_execute_order_retries_existing_failed_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    order = orders_module.OrderModel(
        id=79,
        site_id=3,
        status="incomplete",
        total_price=23.0,
        created_at=now,
    )
    site = orders_module.SiteModel(id=3, name="onlyfans", created_at=now)
    failed_item = orders_module.OrderedPerformerModel(
        id=1,
        order_id=order.id,
        site_id=site.id,
        user_id=1001,
        username="failed",
        price=23.0,
        status="failed",
        error_message="Insufficient Credit Balance",
        created_at=now,
    )

    results = [
        _FakeOrdersRouteResult(scalar_one_or_none_value=order),
        _FakeOrdersRouteResult(scalar_one_or_none_value=site),
        _FakeOrdersRouteResult(scalars_all_value=[failed_item]),
    ]

    monkeypatch.setattr(orders_module, "ensure_orders_schema", lambda: None)
    monkeypatch.setattr(
        orders_module,
        "create_orders_session",
        lambda: _FakeOrdersRouteSession(list(results)),
    )
    monkeypatch.setattr(
        orders_module,
        "_get_candidate_auth_ids",
        lambda site_name, price: [(999, "paid")] if price > 0 else [],
    )
    monkeypatch.setattr(
        orders_module,
        "_get_stored_user_balances",
        lambda site_name, auth_ids: {999: 100.0},
    )
    monkeypatch.setattr(
        orders_module,
        "_get_cached_authed_session",
        AsyncMock(return_value=SimpleNamespace(id=999)),
    )
    monkeypatch.setattr(
        orders_module,
        "_knapsack_optimize",
        lambda paid_items, spender_balances: {999: list(paid_items)},
    )
    monkeypatch.setattr(
        orders_module,
        "_execute_subscription",
        AsyncMock(return_value=(True, None, 23.0)),
    )
    monkeypatch.setattr(
        orders_module,
        "_refresh_spender_balance_after_purchase",
        AsyncMock(),
    )
    monkeypatch.setattr(
        orders_module,
        "_upsert_subscription_after_purchase",
        AsyncMock(),
    )
    monkeypatch.setattr(
        orders_module, "_add_to_watch_list", lambda site_name, user_id: None
    )
    monkeypatch.setattr(
        orders_module,
        "_create_scrape_download_job",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        orders_module,
        "spawn_background_task",
        lambda coro: coro.close(),
    )

    response = await orders_module.execute_order(
        order_id=order.id,
        backend_manager=SimpleNamespace(),
    )

    assert response.success is True
    assert response.order is not None
    assert response.order.status == "completed"
    assert response.order.total_price == pytest.approx(23.0)
    assert response.items[0].status == "completed"
    assert response.items[0].error_message is None
    assert response.items[0].spender_user_id == 999


@pytest.mark.asyncio
async def test_execute_order_refreshes_spender_balance_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    order = orders_module.OrderModel(
        id=80,
        site_id=3,
        status="pending",
        total_price=None,
        created_at=now,
    )
    site = orders_module.SiteModel(id=3, name="onlyfans", created_at=now)
    pending_item = orders_module.OrderedPerformerModel(
        id=1,
        order_id=order.id,
        site_id=site.id,
        user_id=1002,
        username="todo",
        price=15.0,
        status="pending",
        created_at=now,
    )

    results = [
        _FakeOrdersRouteResult(scalar_one_or_none_value=order),
        _FakeOrdersRouteResult(scalar_one_or_none_value=site),
        _FakeOrdersRouteResult(scalars_all_value=[pending_item]),
    ]

    authed = SimpleNamespace(id=999)
    refresh_balance = AsyncMock()

    monkeypatch.setattr(orders_module, "ensure_orders_schema", lambda: None)
    monkeypatch.setattr(
        orders_module,
        "create_orders_session",
        lambda: _FakeOrdersRouteSession(list(results)),
    )
    monkeypatch.setattr(
        orders_module,
        "_get_candidate_auth_ids",
        lambda site_name, price: [(999, "paid")] if price > 0 else [],
    )
    monkeypatch.setattr(
        orders_module,
        "_get_stored_user_balances",
        lambda site_name, auth_ids: {999: 100.0},
    )
    monkeypatch.setattr(
        orders_module,
        "_get_cached_authed_session",
        AsyncMock(return_value=authed),
    )
    monkeypatch.setattr(
        orders_module,
        "_knapsack_optimize",
        lambda paid_items, spender_balances: {999: list(paid_items)},
    )
    monkeypatch.setattr(
        orders_module,
        "_execute_subscription",
        AsyncMock(return_value=(True, None, 15.0)),
    )
    monkeypatch.setattr(
        orders_module,
        "_refresh_spender_balance_after_purchase",
        refresh_balance,
    )
    monkeypatch.setattr(
        orders_module,
        "_upsert_subscription_after_purchase",
        AsyncMock(),
    )
    monkeypatch.setattr(
        orders_module, "_add_to_watch_list", lambda site_name, user_id: None
    )
    monkeypatch.setattr(
        orders_module,
        "_create_scrape_download_job",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        orders_module,
        "spawn_background_task",
        lambda coro: coro.close(),
    )

    response = await orders_module.execute_order(
        order_id=order.id,
        backend_manager=SimpleNamespace(),
    )

    assert response.success is True
    assert response.order is not None
    assert response.order.status == "completed"
    refresh_balance.assert_awaited_once_with(
        site="onlyfans",
        authed=authed,
        auth_id=999,
    )


@pytest.mark.asyncio
async def test_delete_ordered_performer_recomputes_parent_order_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)
    order = orders_module.OrderModel(
        id=74,
        site_id=3,
        status="incomplete",
        total_price=15.0,
        created_at=now,
    )
    deleted_item = orders_module.OrderedPerformerModel(
        id=9,
        order_id=order.id,
        site_id=3,
        user_id=1009,
        username="failed",
        price=5.0,
        status="failed",
        created_at=now,
    )
    remaining_item = orders_module.OrderedPerformerModel(
        id=10,
        order_id=order.id,
        site_id=3,
        user_id=1010,
        username="done",
        price=10.0,
        status="completed",
        created_at=now,
    )

    fake_session = _FakeOrdersRouteSession(
        [
            _FakeOrdersRouteResult(scalar_one_or_none_value=deleted_item),
            _FakeOrdersRouteResult(scalar_one_or_none_value=order),
            _FakeOrdersRouteResult(scalars_all_value=[remaining_item]),
        ]
    )

    monkeypatch.setattr(orders_module, "ensure_orders_schema", lambda: None)
    monkeypatch.setattr(
        orders_module,
        "create_orders_session",
        lambda: fake_session,
    )

    response = await orders_module.delete_ordered_performer(deleted_item.id)

    assert response.success is True
    assert response.order is not None
    assert response.order.status == "completed"
    assert response.order.total_price == pytest.approx(10.0)
    assert [item.id for item in response.items] == [remaining_item.id]
    assert fake_session.deleted == [deleted_item]
