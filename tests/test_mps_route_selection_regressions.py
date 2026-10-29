import json
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ultima_scraper_api import ContentType

from ultima_scraper_backend.api.routes.jobs import _build_task_from_payload
from ultima_scraper_backend.api.routes.mps import _build_mps_task_payloads
from ultima_scraper_backend.job_system import mps_tasks
from ultima_scraper_backend.job_system.handlers.scrape import handler
from ultima_scraper_backend.job_system.job_builder import build_task
from ultima_scraper_backend.job_system.models import Task, TaskRunContext, TaskType
from ultima_scraper_backend.job_system.payloads import ScrapeTaskPayload


def test_partial_geo_metadata_does_not_concentrate_on_first_known_route():
    known = [f"http://us-{i}:8080" for i in range(7)]
    pool = ([f"http://unknown-{i}:8080" for i in range(100)] + known
            + [f"http://unknown-{i}:8080" for i in range(100, 200)])
    counts = Counter()
    for index in range(len(pool) * 3):
        primary, fallbacks, direct = mps_tasks._resolve_mps_task_routes(
            task_index=index, proxy_pool=pool, proxy_start_index=0,
            proxy_geo_map=dict.fromkeys(known, "US"),
        )
        assert primary == pool[index % len(pool)]
        assert direct is None
        assert len({primary, *fallbacks}) == 3
        counts.update(url for url in fallbacks if url in known)
    assert set(counts) == set(known)
    assert max(counts.values()) - min(counts.values()) <= 6


@pytest.mark.parametrize("include_direct", [False, True])
@pytest.mark.parametrize("hops", [1, 2, 3, 5])
def test_configured_hop_limit_includes_direct(include_direct, hops):
    primary, fallbacks, direct = mps_tasks._resolve_mps_task_routes(
        task_index=7, proxy_pool=[f"http://p{i}:8080" for i in range(10)],
        proxy_start_index=3, include_direct=include_direct, max_route_hops=hops,
        proxy_geo_map={},
    )
    routes = handler._build_guest_proxy_routes(
        guest_proxy_url=primary, guest_fallback_proxy_urls=fallbacks,
        guest_direct_route_index=direct,
    )
    assert len(routes) == hops
    assert len(set(routes)) == hops
    assert (None in routes) == include_direct


def test_alternatives_stay_in_country_pool_and_replay_across_windows():
    pool = [f"http://us-{i}:8080" for i in range(8)] + ["http://gb:8080", "http://unknown:8080"]
    geo = {url: "US" for url in pool[:8]} | {pool[8]: "GB"}
    kwargs = dict(job_id="job-route-selection", site_display="OnlyFans",
                  proxy_pool=pool, proxy_geo_map=geo, include_direct=True)
    full = mps_tasks._build_mps_task_batch(target_user_ids=[100, 101, 102, 103], candidate_offset=5, **kwargs)
    split = (mps_tasks._build_mps_task_batch(target_user_ids=[100, 101], candidate_offset=5, **kwargs)
             + mps_tasks._build_mps_task_batch(target_user_ids=[102, 103], candidate_offset=7, **kwargs))
    assert [(task.task_id, task.payload.model_dump()) for task in full] == [
        (task.task_id, task.payload.model_dump()) for task in split
    ]
    for task in full:
        payload = task.payload
        assert isinstance(payload, ScrapeTaskPayload)
        selected = {payload.guest_proxy_url, *payload.guest_fallback_proxy_urls}
        assert payload.guest_proxy_alternatives
        for original, alternatives in payload.guest_proxy_alternatives.items():
            assert original in selected
            assert len(alternatives) <= 3
            assert not selected.intersection(alternatives)
            assert len(set(alternatives)) == len(alternatives)
            assert all(geo[url] == geo[original] for url in alternatives)
            assert set(alternatives) <= set(pool)
        restored = Task.from_dict(json.loads(json.dumps(task.to_dict())))
        assert restored.payload.guest_proxy_alternatives == payload.guest_proxy_alternatives


@pytest.mark.asyncio
async def test_legacy_payload_conversion_preserves_alternatives():
    pool = [f"http://us-{i}:8080" for i in range(7)]
    legacy = _build_mps_task_payloads(site_display="OnlyFans", target_user_ids=[100],
        proxy_pool=pool, proxy_geo_map=dict.fromkeys(pool, "US"))
    task = await _build_task_from_payload(legacy[0], SimpleNamespace())
    assert isinstance(task, Task)
    assert task.payload.guest_proxy_alternatives == legacy[0].params["guest_proxy_alternatives"]
    assert task.payload.guest_proxy_alternatives


def test_pre_lookup_substitution_keeps_slots_unique_and_direct():
    api = SimpleNamespace()
    routes = ["http://slow-1:8080", None, "http://slow-2:8080", "http://assigned:8080"]
    for route in routes[:1] + routes[2:3] + ["http://also-slow:8080"]:
        for _ in range(3):
            handler._record_mps_guest_route_outcome(api, route, "lookup_timeout")
    alternatives = {
        routes[0]: [routes[3], "http://also-slow:8080", "http://healthy-1:8080"],
        routes[2]: ["http://healthy-1:8080", "http://healthy-2:8080"],
    }
    selected = handler._select_mps_guest_routes(api, routes, alternatives)
    assert selected == ["http://healthy-1:8080", None, "http://healthy-2:8080", routes[3]]
    assert routes[0] == "http://slow-1:8080"
    assert len(set(selected)) == len(routes)


def test_unavailable_alternatives_and_expired_deferral_keep_original(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(handler.time, "monotonic", lambda: now[0])
    api = SimpleNamespace()
    original, reserve = "http://slow:8080", "http://reserve:8080"
    for route in [original, reserve]:
        for _ in range(3):
            handler._record_mps_guest_route_outcome(api, route, "lookup_timeout")
    assert handler._select_mps_guest_routes(api, [original], {}) == [original]
    assert handler._select_mps_guest_routes(api, [original], {original: [reserve]}) == [original]
    now[0] += handler.MPS_GUEST_ROUTE_TIMEOUT_DEFER_SECONDS + 1
    assert handler._select_mps_guest_routes(api, [original], {original: [reserve]}) == [original]


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_reserve", [False, True])
async def test_handler_substitutes_once_and_counts_distinct_misses(monkeypatch, retry_reserve):
    api = SimpleNamespace()
    slow, reserve, gb, de = [f"http://{name}:8080" for name in ["slow", "reserve", "gb", "de"]]
    for _ in range(3):
        handler._record_mps_guest_route_outcome(api, slow, "lookup_timeout")
    attempts, lookups = [], Counter()
    async def auth(site_api, proxy_url, worker_id):
        attempts.append(proxy_url)
        return SimpleNamespace(proxy_url=proxy_url, release_user=Mock())
    async def lookup(authed, **kwargs):
        lookups[authed.proxy_url] += 1
        if retry_reserve and authed.proxy_url == reserve and lookups[reserve] == 1:
            raise TimeoutError()
        return None
    mark_invalid = AsyncMock()
    monkeypatch.setattr(handler, "_resolve_guest_auth", auth)
    monkeypatch.setattr(handler, "_resolve_scrape_user", lookup)
    monkeypatch.setattr(handler, "_mark_user_invalid", mark_invalid)
    monkeypatch.setattr(handler, "MPS_GUEST_LOOKUP_HEDGE_DELAY_SECONDS", 0)
    monkeypatch.setattr(handler, "MPS_GUEST_ROUTE_RETRY_DELAY_SECONDS", 0)
    task = build_task(TaskType.SCRAPE, site_name="OnlyFans", user_id=8800, user_username="8800",
        content_type=ContentType.PROFILE, use_guest_auth=True, guest_proxy_url=slow,
        guest_fallback_proxy_urls=[gb, de], guest_proxy_alternatives={slow: [reserve]},
        conclusive_miss_threshold=3, max_route_hops=3, track_invalid_user=True, max_items=1)
    context = TaskRunContext(job=SimpleNamespace(job_id="route-substitution"),
        storage=SimpleNamespace(persist_task=AsyncMock()), previous_output=None,
        context={"site_api": api, "worker_id": "test-worker", "db_managers": {"onlyfans": SimpleNamespace()},
                 "database_writes": SimpleNamespace(submit=AsyncMock())})
    result = await handler.scrape_task_handler(task, context)
    assert result.success
    assert set(attempts) == {reserve, gb, de}
    assert attempts == [reserve, gb, de] + ([reserve] if retry_reserve else [])
    assert task.payload.guest_proxy_url == slow
    mark_invalid.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("pooled", [True, False])
async def test_handler_retries_a_429_on_another_session_of_the_same_route(monkeypatch, pooled):
    from ultima_scraper_api.apis.onlyfans.classes.auth_model import UserLookupError

    api = SimpleNamespace()
    if pooled:
        api._guest_session_pool = SimpleNamespace()
    primary, gb, de = [f"http://{name}:8080" for name in ["primary", "gb", "de"]]
    attempts, sessions = [], iter(range(100))

    async def auth(site_api, proxy_url, worker_id):
        attempts.append(proxy_url)
        return SimpleNamespace(proxy_url=proxy_url, session=next(sessions), release_user=Mock())

    async def lookup(authed, **kwargs):
        if authed.session == 0:  # the first visitor session's window is spent
            raise UserLookupError(429)
        return None

    mark_invalid = AsyncMock()
    monkeypatch.setattr(handler, "_resolve_guest_auth", auth)
    monkeypatch.setattr(handler, "_resolve_scrape_user", lookup)
    monkeypatch.setattr(handler, "_mark_user_invalid", mark_invalid)
    monkeypatch.setattr(handler, "MPS_GUEST_LOOKUP_HEDGE_DELAY_SECONDS", 0)
    monkeypatch.setattr(handler, "MPS_GUEST_ROUTE_RETRY_DELAY_SECONDS", 0)
    task = build_task(TaskType.SCRAPE, site_name="OnlyFans", user_id=8801, user_username="8801",
        content_type=ContentType.PROFILE, use_guest_auth=True, guest_proxy_url=primary,
        guest_fallback_proxy_urls=[gb, de], conclusive_miss_threshold=3, max_route_hops=3,
        track_invalid_user=True, max_items=1)
    context = TaskRunContext(job=SimpleNamespace(job_id="session-retry"),
        storage=SimpleNamespace(persist_task=AsyncMock()), previous_output=None,
        context={"site_api": api, "worker_id": "test-worker", "db_managers": {"onlyfans": SimpleNamespace()},
                 "database_writes": SimpleNamespace(submit=AsyncMock())})
    await handler.scrape_task_handler(task, context)
    if pooled:
        # The 429 costs no route hop: the same route answers on another session.
        assert attempts[:2] == [primary, primary]
        assert set(attempts) == {primary, gb, de}
        mark_invalid.assert_awaited_once()
    else:
        # Without a pool there is no other session on the route to move to.
        assert attempts[:2] != [primary, primary]
