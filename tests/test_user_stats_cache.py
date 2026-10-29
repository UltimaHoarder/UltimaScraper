from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from ultima_scraper_backend.services.user_stats_cache import UserStatsCache


def test_exact_results_expire_and_are_bounded_and_site_isolated():
    now = [0.0]
    cache = UserStatsCache(ttl=30, capacity=2, clock=lambda: now[0])
    key = ('onlyfans', 'filtered')
    assert cache.get(key, lambda: 42) == 42
    assert cache.get(key, lambda: 99) == 42
    assert cache.get(('fansly', 'filtered'), lambda: 7) == 7
    now[0] = 31
    assert cache.get(key, lambda: 43) == 43
    cache.get(('onlyfans', 'another'), lambda: 1)
    assert len(cache.values) == 2


def test_identical_parallel_requests_execute_one_loader():
    cache = UserStatsCache()
    started, release = Event(), Event()
    calls = []
    def load():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return (42, 40, 2, 100, 3)
    with ThreadPoolExecutor(max_workers=8) as pool:
        first = pool.submit(cache.get, ('onlyfans', 'filter'), load)
        assert started.wait(5)
        followers = [pool.submit(cache.get, ('onlyfans', 'filter'), load) for _ in range(7)]
        release.set()
        assert first.result() == (42, 40, 2, 100, 3)
        assert all(f.result() == first.result() for f in followers)
    assert len(calls) == 1


def test_failed_load_is_not_cached():
    cache = UserStatsCache()
    def fail():
        raise RuntimeError('statement timeout')
    with pytest.raises(RuntimeError, match='statement timeout'):
        cache.get(('onlyfans', 'filter'), fail)
    assert cache.get(('onlyfans', 'filter'), lambda: 42) == 42


def test_invalidation_does_not_republish_inflight_old_totals():
    cache = UserStatsCache()
    started, release = Event(), Event()
    def old_load():
        started.set()
        assert release.wait(5)
        return 1
    with ThreadPoolExecutor() as pool:
        old = pool.submit(cache.get, ('onlyfans', 'filter'), old_load)
        assert started.wait(5)
        cache.invalidate_site('onlyfans')
        assert cache.get(('onlyfans', 'filter'), lambda: 2) == 2
        release.set()
        assert old.result() == 1
    assert cache.get(('onlyfans', 'filter'), lambda: 3) == 2
