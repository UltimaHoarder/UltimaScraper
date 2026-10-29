"""Resource snapshots remain bounded and timestamped while status updates continue."""

from types import SimpleNamespace

from ultima_scraper_backend.workers import worker_pool


def test_resource_snapshot_refreshes_after_one_second_and_is_not_mutable(monkeypatch):
    now = [100.0]
    scans = []

    class Process:
        def __init__(self, pid):
            scans.append(pid)

        def memory_info(self):
            return SimpleNamespace(rss=123, vms=456)

        def memory_percent(self):
            return 1.0

    monkeypatch.setattr(worker_pool.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(worker_pool.psutil, "Process", Process)
    worker = worker_pool.Worker.__new__(worker_pool.Worker)
    worker.apis = {"onlyfans": SimpleNamespace(auths={})}
    worker.ultima_scraper_api = None
    first = worker._collect_memory_telemetry()
    sampled_at = first["memory_sampled_at"]
    first["auth_count"] = 999
    worker.apis["onlyfans"].auths[1] = SimpleNamespace(guest=True, users={})
    now[0] += 0.999
    cached = worker._collect_memory_telemetry()
    assert cached["auth_count"] == 0
    assert cached["memory_sampled_at"] == sampled_at
    assert len(scans) == 1
    now[0] += 0.001
    fresh = worker._collect_memory_telemetry()
    assert fresh["auth_count"] == fresh["guest_auth_count"] == 1
    assert len(scans) == 2
