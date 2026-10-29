"""Frozen fallback assignment spreads load while retaining geographic evidence."""

from collections import Counter

from ultima_scraper_backend.job_system import mps_tasks


def weighted_pool():
    pool, geo = [], {}
    for index in range(20):
        url = f"http://us-{index}:8080"
        pool.extend([url] * 13)
        geo[url] = "US"
    for index in range(2):
        url = f"http://small-us-{index}:8080"
        pool.extend([url] * 4)
        geo[url] = "US"
    for index in range(20):
        url = f"http://country-{index}:8080"
        pool.extend([url] * 13)
        geo[url] = f"C{index}"
    return pool, geo


def test_clustered_weighted_pool_has_bounded_fallback_concentration():
    pool, geo = weighted_pool()
    groups = mps_tasks._group_mps_proxy_countries(pool, geo)
    weights = mps_tasks._weighted_country_counts(pool, geo)
    counts = Counter()
    for index in range(10000):
        primary, fallbacks, direct = mps_tasks._resolve_mps_task_routes(
            task_index=index,
            proxy_pool=pool,
            proxy_start_index=0,
            proxy_geo_map=geo,
            proxy_country_groups=groups,
            proxy_country_weights=weights,
        )
        routes = [primary, *fallbacks]
        assert primary == pool[index % len(pool)]
        assert len(routes) == len(set(routes)) == 3
        assert len({geo[url] for url in routes}) == 3
        assert sum(geo[url] == "US" for url in routes) == 1
        assert direct is None
        counts.update(routes)
    foreign_counts = [count for url, count in counts.items() if geo[url] != "US"]
    assert max(foreign_counts) < 1.3 * (sum(foreign_counts) / len(foreign_counts))
    large_us = sum(counts[f"http://us-{index}:8080"] for index in range(20)) / 20
    small_us = sum(counts[f"http://small-us-{index}:8080"] for index in range(2)) / 2
    assert 2.8 < large_us / small_us < 3.8


def test_route_plan_is_independent_of_materialization_batch_boundaries():
    pool, geo = weighted_pool()
    kwargs = {
        "job_id": "frozen-routing-test",
        "site_display": "OnlyFans",
        "proxy_pool": pool,
        "proxy_geo_map": geo,
        "conclusive_miss_threshold": 3,
    }
    user_ids = list(range(10000, 10100))
    whole = mps_tasks._build_mps_task_batch(
        target_user_ids=user_ids, candidate_offset=57, **kwargs
    )
    split = mps_tasks._build_mps_task_batch(
        target_user_ids=user_ids[:23], candidate_offset=57, **kwargs
    ) + mps_tasks._build_mps_task_batch(
        target_user_ids=user_ids[23:], candidate_offset=80, **kwargs
    )
    for original, resumed in zip(whole, split):
        assert original.task_id == resumed.task_id
        assert original.payload.model_dump() == resumed.payload.model_dump()
        assert original.payload.conclusive_miss_threshold == 3
