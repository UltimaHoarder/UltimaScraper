from __future__ import annotations

import asyncio
from dataclasses import asdict
from threading import Event, get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ultima_scraper_backend.ultima_control import system_stats_reporter as module


@pytest.fixture
def counters(monkeypatch):
    state = {
        "now": 0.0,
        "disks": {"sda1": (100, 200)},
        "network": {"eth0": (1000, 2000)},
        "mounts": [("sda1", "/data")],
        "unreadable": set(),
    }

    def disk_usage(mount):
        if mount in state["unreadable"]:
            raise PermissionError(mount)
        return SimpleNamespace(total=1000, used=400, free=600, percent=40.0)

    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: state["now"]))
    monkeypatch.setattr(
        module,
        "psutil",
        SimpleNamespace(
            disk_partitions=lambda **_: [
                SimpleNamespace(device="/dev/" + d, mountpoint=m)
                for d, m in state["mounts"]
            ],
            disk_usage=disk_usage,
            disk_io_counters=lambda **_: {
                name: SimpleNamespace(read_bytes=v[0], write_bytes=v[1])
                for name, v in state["disks"].items()
            },
            net_io_counters=lambda **_: {
                name: SimpleNamespace(bytes_sent=v[0], bytes_recv=v[1])
                for name, v in state["network"].items()
            },
            cpu_percent=lambda **_: 10.0,
            cpu_count=lambda: 4,
            virtual_memory=lambda: SimpleNamespace(
                total=4096, used=1024, available=3072, percent=25.0
            ),
        ),
    )
    return state


def reporter():
    return module.SystemStatsReporter(
        SimpleNamespace(set=AsyncMock()), "fixture", enable_network=True
    )


def test_disk_and_network_use_independent_monotonic_sample_intervals(counters):
    monitor = reporter()
    assert monitor._collect_disk_stats()[0].read_bytes_per_sec == 0
    counters["now"] = 0.001
    assert monitor._collect_network_stats()[0].bytes_sent_per_sec == 0
    counters["disks"] = {"sda1": (1100, 2200)}
    counters["network"] = {"eth0": (6000, 12000)}
    counters["now"] = 5.0
    disk = monitor._collect_disk_stats()[0]
    counters["now"] = 5.001
    net = monitor._collect_network_stats()[0]
    assert disk.read_bytes_per_sec == pytest.approx(200.0)
    assert disk.write_bytes_per_sec == pytest.approx(400.0)
    assert net.bytes_sent_per_sec == pytest.approx(1000.0)
    assert net.bytes_recv_per_sec == pytest.approx(2000.0)
    counters["now"] = 10.001
    counters["network"] = {"eth0": (11000, 22000)}
    assert monitor._collect_network_stats()[0].bytes_sent_per_sec == pytest.approx(
        1000.0
    )


def test_multiple_mounts_of_one_device_share_the_same_rate(counters):
    monitor = reporter()
    counters["mounts"].append(("sda1", "/bind"))
    assert len(monitor._collect_disk_stats()) == 2
    counters["now"] = 5.0
    counters["disks"] = {"sda1": (5100, 10200)}
    stats = monitor._collect_disk_stats()
    assert [
        (disk.mount_point, disk.read_bytes_per_sec, disk.write_bytes_per_sec)
        for disk in stats
    ] == [
        ("/data", 1000.0, 2000.0),
        ("/bind", 1000.0, 2000.0),
    ]


def test_removed_devices_and_interfaces_do_not_accumulate(counters):
    monitor = reporter()
    for number in range(2000):
        counters["now"] = float(number)
        counters["mounts"] = [(f"disk-{number}", "/data")]
        counters["disks"] = {f"disk-{number}": (10, 20)}
        counters["network"] = {f"veth-{number}": (100, 200)}
        assert len(monitor._collect_disk_stats()) == 1
        assert len(monitor._collect_network_stats()) == 1
        assert set(monitor._prev_disk_io) == {f"disk-{number}"}
        assert set(monitor._prev_network_io) == {f"veth-{number}"}
    counters["mounts"] = []
    counters["network"] = {}
    monitor._collect_disk_stats()
    monitor._collect_network_stats()
    assert monitor._prev_disk_io == {} and monitor._prev_network_io == {}


def test_counter_reset_and_nonpositive_interval_start_a_new_baseline(counters):
    monitor = reporter()
    monitor._collect_stats()
    counters["now"] = 5.0
    counters["disks"] = {"sda1": (10, 20)}
    counters["network"] = {"eth0": (100, 200)}
    stats = monitor._collect_stats()
    assert stats.disks[0].read_bytes_per_sec == 0
    assert stats.network[0].bytes_sent_per_sec == 0
    counters["disks"] = {"sda1": (20, 40)}
    counters["network"] = {"eth0": (200, 400)}
    assert monitor._collect_stats().network[0].bytes_sent_per_sec == 0
    counters["now"] = 10.0
    counters["disks"] = {"sda1": (30, 60)}
    counters["network"] = {"eth0": (300, 600)}
    stats = monitor._collect_stats()
    assert stats.disks[0].read_bytes_per_sec == 2
    assert stats.network[0].bytes_sent_per_sec == 20


def test_disabled_unreadable_and_failed_counters_drop_stale_baselines(
    counters, monkeypatch
):
    monitor = reporter()
    monitor._collect_stats()
    monitor.enable_network = False
    counters["unreadable"] = {"/data"}
    stats = monitor._collect_stats()
    assert stats.disks == [] and stats.network == []
    assert monitor._prev_disk_io == {} and monitor._prev_network_io == {}
    assert monitor._prev_network_timestamp is None
    monitor.enable_network = True
    counters["unreadable"] = set()
    counters["now"] = 10.0
    monitor._collect_stats()

    def fail(**_):
        raise OSError("fixture inaccessible")

    monkeypatch.setattr(module.psutil, "net_io_counters", fail)
    monkeypatch.setattr(module.psutil, "disk_io_counters", fail)
    stats = monitor._collect_stats()
    assert stats.disks[0].read_bytes_per_sec == 0
    assert stats.network == []
    assert monitor._prev_disk_io == {} and monitor._prev_network_io == {}


def test_serialization_preserves_nested_payload_without_duplicate_conversion(
    monkeypatch,
):
    snapshot = module.SystemStats(
        "fixture",
        disks=[module.DiskStats("sda1", "/data", 1000, 400, 600, 40.0)],
        network=[module.NetworkStats("eth0", 100, 200)],
    )
    expected = asdict(snapshot)
    monkeypatch.setattr(
        module.DiskStats, "to_dict", lambda _: pytest.fail("second nested conversion")
    )
    monkeypatch.setattr(
        module.NetworkStats,
        "to_dict",
        lambda _: pytest.fail("second nested conversion"),
    )
    assert snapshot.to_dict() == expected
    assert module.SystemStats.from_json(snapshot.to_json()).to_dict() == expected


@pytest.mark.asyncio
async def test_collection_and_serialization_stay_off_the_event_loop(monkeypatch):
    loop_thread = get_ident()
    thread_ids = []
    published = asyncio.Event()
    monitor = reporter()

    def collect():
        thread_ids.append(get_ident())
        return module.SystemStats("fixture")

    original_json = module.SystemStats.to_json

    def encode(stats):
        thread_ids.append(get_ident())
        return original_json(stats)

    async def publish(*_, **__):
        assert get_ident() == loop_thread
        published.set()

    monkeypatch.setattr(monitor, "_collect_stats", collect)
    monkeypatch.setattr(module.SystemStats, "to_json", encode)
    monitor.redis.set = publish
    try:
        await monitor.start()
        await asyncio.wait_for(published.wait(), timeout=2)
    finally:
        await monitor.stop()
    assert len(thread_ids) == 2 and thread_ids[0] == thread_ids[1] != loop_thread


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_reporter", [False, True])
async def test_shutdown_waits_for_sampling_and_does_not_publish_after_stop(
    monkeypatch, cancel_reporter
):
    monitor = reporter()
    entered = asyncio.Event()
    release = Event()
    finished = Event()
    loop = asyncio.get_running_loop()

    def collect():
        loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(timeout=5)
            return module.SystemStats("fixture")
        finally:
            finished.set()

    monkeypatch.setattr(monitor, "_collect_stats", collect)
    stop = None
    try:
        await monitor.start()
        await asyncio.wait_for(entered.wait(), timeout=2)
        active = monitor._task
        if cancel_reporter:
            active.cancel()
        stop = asyncio.create_task(monitor.stop())
        for _ in range(10):
            await asyncio.sleep(0)
        assert not active.done() and not stop.done() and not finished.is_set()
        release.set()
        await asyncio.wait_for(stop, timeout=2)
        assert finished.is_set() and monitor._task is None and not monitor.is_running
        monitor.redis.set.assert_not_awaited()
    finally:
        release.set()
        if stop is not None:
            await stop
        await monitor.stop()


@pytest.mark.asyncio
async def test_cancelled_stop_waits_and_restart_cannot_overlap_sampling(monkeypatch):
    monitor = reporter()
    entered = asyncio.Event()
    second = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()
    calls = 0
    sampling = False

    def collect():
        nonlocal calls, sampling
        assert not sampling
        sampling = True
        calls += 1
        try:
            if calls == 1:
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(timeout=5)
            else:
                loop.call_soon_threadsafe(second.set)
            return module.SystemStats("fixture")
        finally:
            sampling = False

    monkeypatch.setattr(monitor, "_collect_stats", collect)
    stop = restart = None
    try:
        await monitor.start()
        await asyncio.wait_for(entered.wait(), timeout=2)
        stop = asyncio.create_task(monitor.stop())
        while monitor.is_running:
            await asyncio.sleep(0)
        stop.cancel()
        restart = asyncio.create_task(monitor.start())
        for _ in range(10):
            await asyncio.sleep(0)
            stop.cancel()
        assert not stop.done() and not restart.done() and calls == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(stop, timeout=2)
        await asyncio.wait_for(restart, timeout=2)
        await asyncio.wait_for(second.wait(), timeout=2)
    finally:
        release.set()
        if stop is not None:
            try:
                await stop
            except asyncio.CancelledError:
                pass
        if restart is not None:
            await restart
        await monitor.stop()
    assert monitor._prev_disk_io == {} and monitor._prev_network_io == {}


@pytest.mark.asyncio
async def test_grace_timeout_cancels_reporter_but_keeps_native_sample_owned(
    monkeypatch,
):
    monitor = reporter()
    entered = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()

    async def short_grace(awaitable, timeout):
        return await asyncio.wait_for(awaitable, timeout=min(timeout, 0.01))

    monkeypatch.setattr(
        module,
        "asyncio",
        SimpleNamespace(
            **{
                name: getattr(asyncio, name)
                for name in (
                    "Lock",
                    "Event",
                    "Task",
                    "create_task",
                    "shield",
                    "TimeoutError",
                    "CancelledError",
                )
            },
            wait_for=short_grace,
        ),
    )

    def collect():
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(timeout=5)
        return module.SystemStats("fixture")

    monkeypatch.setattr(monitor, "_collect_stats", collect)
    stop = None
    try:
        await monitor.start()
        await asyncio.wait_for(entered.wait(), timeout=2)
        active = monitor._task
        stop = asyncio.create_task(monitor.stop())

        async def cancelled():
            while not active.cancelling():
                await asyncio.sleep(0)

        await asyncio.wait_for(cancelled(), timeout=2)
        assert not active.done() and not stop.done()
        release.set()
        await asyncio.wait_for(stop, timeout=2)
        assert monitor._task is None and not monitor.is_running
    finally:
        release.set()
        if stop is not None:
            await stop
        await monitor.stop()
