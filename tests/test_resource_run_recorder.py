from __future__ import annotations

import argparse
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tracemalloc

import pytest

from scripts import record_resource_run as recorder


def write_stat(directory: Path, *, start: int = 200) -> None:
    fields = ["S", *[str(number) for number in range(1, 50)]]
    fields[19] = str(start)
    (directory / "stat").write_text("123 (name with ) parenthesis) " + " ".join(fields))


@pytest.fixture
def sampler(tmp_path):
    proc = tmp_path / "proc"
    pid = proc / "123"
    pid.mkdir(parents=True)
    write_stat(pid)
    (pid / "status").write_text("Name:\tapplication\nVmRSS:\t30 kB\nThreads:\t2\n")
    (proc / "meminfo").write_text("MemTotal: 4096 kB\nMemAvailable: 1024 kB\n")
    (proc / "vmstat").write_text("pswpin 12\npswpout 15\noom_kill 0\n")
    group = tmp_path / "group"
    group.mkdir()
    (group / "memory.current").write_text("1000\n")
    (group / "memory.events").write_text("high 0\nmax 0\noom 0\noom_kill 0\n")
    return recorder.Sampler(
        pids=[123], cgroups=[group], storage=[tmp_path], pss=True, proc=proc
    )


def test_proc_fields_are_not_shifted_by_process_names(sampler):
    sample = sampler.sample()
    process = sample["processes"]["123"]
    assert process["stat"] == {
        "start_ticks": 200,
        "user_ticks": 11,
        "system_ticks": 12,
        "threads": 17,
    }
    assert process["status"]["VmRSS"] == 30 * 1024
    assert sample["system"]["memory"]["MemAvailable"] == 1024 * 1024
    assert sample["system"]["vmstat"]["pswpin"] == 12
    assert process["io"] is None
    assert process["smaps_rollup"] is None
    assert sample["unavailable"]
    assert next(iter(sample["storage"].values()))["available_bytes"] > 0


@pytest.mark.parametrize("during_read", [False, True])
def test_pid_reuse_never_attributes_new_process_usage(
    sampler, monkeypatch, during_read
):
    directory = sampler.proc / "123"
    if during_read:
        original = recorder.read_metric

        def replacement(path, parser, errors):
            if path.name == "status":
                write_stat(directory, start=201)
            return original(path, parser, errors)

        monkeypatch.setattr(recorder, "read_metric", replacement)
    else:
        write_stat(directory, start=201)
    sample = sampler.sample()
    assert sample["processes"]["123"] is None
    assert sample["unavailable"][str(directory)] == "ExitedOrReplaced"


def test_recreated_cgroup_and_changed_mount_are_reported_as_unavailable(sampler):
    group = next(iter(sampler.cgroups))
    group.rename(group.with_name("previous-group"))
    group.mkdir()
    (group / "memory.current").write_text("90000000")
    path = next(iter(sampler.storage))
    sampler.storage[path] += 1
    sample = sampler.sample()
    assert sample["cgroups"][str(group)] is None
    assert sample["storage"][str(path)] is None
    assert str(group) in sample["unavailable"]
    assert str(path) in sample["unavailable"]


def test_pressure_and_io_keep_units_and_exact_counters():
    assert recorder.pressure(
        "some avg10=1.23 avg60=0.45 avg300=0.02 total=123456789012345\n"
    ) == {
        "some": {"avg10": 1.23, "avg60": 0.45, "avg300": 0.02, "total": 123456789012345}
    }
    assert recorder.device_io("8:0 rbytes=100 wbytes=200 rios=2 wios=3\n") == {
        "8:0": {"rbytes": 100, "wbytes": 200, "rios": 2, "wios": 3}
    }


def test_host_cpu_block_and_network_field_positions():
    cpu = recorder.cpu_ticks("cpu 1 2 3 4 5 6 7 8 9 10\ncpu0 1 2 3 4\nintr 123 456\n")
    assert cpu["cpu"]["guest_nice"] == 10
    assert cpu["cpu0"]["idle"] == 4
    assert "intr" not in cpu
    disk = recorder.disk_stats("8 0 sda " + " ".join(str(n) for n in range(1, 18)))
    assert disk["8:0/sda"]["sectors_read"] == 3
    assert disk["8:0/sda"]["in_progress"] == 9
    assert disk["8:0/sda"]["flush_ms"] == 17
    network = recorder.network_stats(
        "Inter-| Receive | Transmit\neth0: " + " ".join(str(n) for n in range(1, 17))
    )
    assert network["eth0"]["rx_bytes"] == 1
    assert network["eth0"]["tx_bytes"] == 9
    assert network["eth0"]["tx_dropped"] == 12


def test_later_interfaces_cannot_grow_the_retained_summary():
    summary = recorder.Summary()
    sample = {
        "system": {},
        "processes": {},
        "cgroups": {},
        "storage": {},
        "unavailable": {},
    }
    summary.add(sample)
    for number in range(1000):
        sample["system"] = {"network": {f"ephemeral-{number}": {"rx_bytes": 1}}}
        summary.add(sample)
    assert summary.metrics == {}
    assert summary.unaggregated_numeric_readings == 1000


def test_summary_memory_does_not_scale_with_run_duration():
    summary = recorder.Summary()
    sample = {
        "system": {"memory": {"MemAvailable": 20}},
        "processes": {},
        "cgroups": {},
        "storage": {},
        "unavailable": {},
    }
    tracemalloc.start()
    try:
        for number in range(100_000):
            sample["system"]["memory"]["MemAvailable"] = None if number % 2 else number
            summary.add(sample)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert summary.samples == 100_000
    assert summary.metrics == {
        "system/memory/MemAvailable": {
            "samples": 50_000,
            "first": 0,
            "last": 99_998,
            "min": 0,
            "max": 99_998,
        }
    }
    assert peak < 100_000


@pytest.mark.parametrize("interrupted", [False, True])
def test_record_streams_samples_and_finishes_interruptible_wait(sampler, interrupted):
    output = StringIO()
    now = 0.0

    def sleep(seconds):
        nonlocal now
        if interrupted:
            raise KeyboardInterrupt
        now += seconds

    result = recorder.record(
        sampler,
        output,
        duration=100,
        interval=50,
        context={"workload": "test"},
        stop=lambda: False,
        clock=lambda: now,
        sleep=sleep,
    )
    lines = [json.loads(line) for line in output.getvalue().splitlines()]
    assert lines[0]["type"] == "metadata"
    assert lines[-1] == result
    assert result["samples"] == (1 if interrupted else 3)
    assert result["reason"] == ("interrupted" if interrupted else "completed")
    assert result["samples_with_unavailable"] == result["samples"]
    assert "processes/123/io/read_bytes" not in result["metrics"]


@pytest.mark.parametrize("value", ["0", "-1", "inf", "nan"])
def test_invalid_timing_is_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        recorder.positive_seconds(value)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux procfs recorder")
def test_real_cli_records_host_and_preserves_existing_output(tmp_path):
    path = tmp_path / "run.jsonl"
    command = [
        sys.executable,
        "-S",
        "-B",
        str(Path(recorder.__file__)),
        "--output",
        str(path),
        "--duration",
        "0.04",
        "--interval",
        "0.02",
        "--pid",
        str(os.getpid()),
        "--storage-path",
        str(tmp_path),
        "--workload",
        "owned smoke",
        "--setting",
        "downloads=operator-selected",
    ]
    run = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stderr
    original = path.read_bytes()
    rows = [json.loads(line) for line in original.splitlines()]
    assert rows[0]["context"]["settings"] == ["downloads=operator-selected"]
    assert rows[-1]["reason"] == "completed"
    assert rows[-1]["samples"] >= 2
    assert rows[1]["system"]["memory"]["MemTotal"] > 0
    duplicate = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert duplicate.returncode != 0
    assert path.read_bytes() == original


def test_slow_samples_skip_deadlines_without_a_catchup_queue(sampler):
    now = 0.0
    original = sampler.sample

    def sample():
        nonlocal now
        result = original()
        now += 0.3
        return result

    sampler.sample = sample
    waits = []
    result = recorder.record(
        sampler,
        StringIO(),
        duration=1,
        interval=0.1,
        context={},
        stop=lambda: False,
        clock=lambda: now,
        sleep=waits.append,
    )
    assert result["samples"] == 4
    assert result["interval_overruns"] == 3
    assert result["elapsed_seconds"] == pytest.approx(1.2)
    assert waits == []


@pytest.mark.skipif(sys.platform != "linux", reason="Linux procfs recorder")
def test_sigterm_interrupts_a_long_sample_wait_and_preserves_summary(tmp_path):
    path = tmp_path / "interrupted.jsonl"
    command = [
        sys.executable,
        "-S",
        "-B",
        str(Path(recorder.__file__)),
        "--output",
        str(path),
        "--duration",
        "3600",
        "--interval",
        "600",
        "--workload",
        "owned interruption test",
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        deadline = time.monotonic() + 5
        while not path.exists() or '"type": "sample"' not in path.read_text():
            assert process.poll() is None, process.communicate()
            assert time.monotonic() < deadline
            time.sleep(0.01)
        process.terminate()
        output, error = process.communicate(timeout=5)
        assert process.returncode == 130, error
        assert json.loads(output)["reason"] == "interrupted"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert rows[-1]["reason"] == "interrupted"
        assert rows[-1]["samples"] == 1
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
