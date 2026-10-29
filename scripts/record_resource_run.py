"""Record a Linux workload without changing its services or resource settings.

Uses the standard library only. Samples stream to an operator-selected JSONL
file; retained state depends on monitored metrics, not recording duration.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import resource
import signal
import sys
import time
from typing import Any


def numeric_fields(value: str, *, kib: bool = False) -> dict[str, int]:
    result = {}
    for line in value.splitlines():
        parts = line.replace(":", " ", 1).split()
        if len(parts) >= 2:
            try:
                number = int(parts[1])
            except ValueError:
                continue
            result[parts[0]] = number * (1024 if kib and parts[2:] == ["kB"] else 1)
    return result


def process_stat(value: str) -> dict[str, int]:
    # comm can itself contain spaces and parentheses. Fields after its closing
    # parenthesis have the stable proc(5) positions used below.
    fields = value.rsplit(")", 1)[1].split()
    return {
        "start_ticks": int(fields[19]),
        "user_ticks": int(fields[11]),
        "system_ticks": int(fields[12]),
        "threads": int(fields[17]),
    }


def pressure(value: str) -> dict[str, dict[str, int | float]]:
    result = {}
    for line in value.splitlines():
        name, *fields = line.split()
        result[name] = {
            key: int(number) if key == "total" else float(number)
            for key, number in (field.split("=", 1) for field in fields)
        }
    return result


def device_io(value: str) -> dict[str, dict[str, int]]:
    result = {}
    for line in value.splitlines():
        device, *fields = line.split()
        result[device] = {
            key: int(number)
            for key, number in (field.split("=", 1) for field in fields)
        }
    return result


def cpu_ticks(value: str) -> dict[str, dict[str, int]]:
    names = (
        "user",
        "nice",
        "system",
        "idle",
        "iowait",
        "irq",
        "softirq",
        "steal",
        "guest",
        "guest_nice",
    )
    result = {}
    for line in value.splitlines():
        name, *numbers = line.split()
        if name == "cpu" or (name.startswith("cpu") and name[3:].isdigit()):
            if len(numbers) < 4:
                raise ValueError("Incomplete CPU counters")
            result[name] = dict(zip(names, map(int, numbers)))
    return result


def disk_stats(value: str) -> dict[str, dict[str, int]]:
    names = (
        "reads",
        "reads_merged",
        "sectors_read",
        "read_ms",
        "writes",
        "writes_merged",
        "sectors_written",
        "write_ms",
        "in_progress",
        "io_ms",
        "weighted_io_ms",
        "discards",
        "discards_merged",
        "sectors_discarded",
        "discard_ms",
        "flushes",
        "flush_ms",
    )
    result = {}
    for line in value.splitlines():
        major, minor, name, *numbers = line.split()
        if len(numbers) < 11:
            raise ValueError("Incomplete block device counters")
        result[f"{major}:{minor}/{name}"] = dict(zip(names, map(int, numbers)))
    return result


def network_stats(value: str) -> dict[str, dict[str, int]]:
    result = {}
    for line in value.splitlines():
        if ":" not in line:
            continue
        name, raw = line.split(":", 1)
        numbers = [int(item) for item in raw.split()]
        if len(numbers) != 16:
            raise ValueError("Incomplete network counters")
        result[name.strip()] = {
            "rx_bytes": numbers[0],
            "rx_packets": numbers[1],
            "rx_errors": numbers[2],
            "rx_dropped": numbers[3],
            "tx_bytes": numbers[8],
            "tx_packets": numbers[9],
            "tx_errors": numbers[10],
            "tx_dropped": numbers[11],
        }
    return result


def read_metric(
    path: Path, parser: Callable[[str], Any], errors: dict[str, str]
) -> Any:
    try:
        return parser(path.read_text())
    except (OSError, ValueError, IndexError) as exc:
        errors[str(path)] = type(exc).__name__
        return None


class Sampler:
    def __init__(
        self,
        *,
        pids: list[int],
        cgroups: list[Path],
        storage: list[Path],
        pss: bool,
        proc: Path = Path("/proc"),
        sensors: tuple[Path, ...] = (),
    ):
        self.proc = proc
        self.pss = pss
        self.pids = {
            pid: process_stat((proc / str(pid) / "stat").read_text())["start_ticks"]
            for pid in pids
        }
        self.cgroups = {path: self.identity(path) for path in cgroups}
        self.storage = {path: path.stat().st_dev for path in storage}
        self.sensors = sensors

    @staticmethod
    def identity(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_dev, stat.st_ino

    def sample(self) -> dict[str, Any]:
        errors: dict[str, str] = {}
        system = {
            "cpu_ticks": read_metric(self.proc / "stat", cpu_ticks, errors),
            "disks": read_metric(self.proc / "diskstats", disk_stats, errors),
            "network": read_metric(self.proc / "net" / "dev", network_stats, errors),
            "sensors": {
                str(path): read_metric(path, int, errors) for path in self.sensors
            },
            "memory": read_metric(
                self.proc / "meminfo", lambda s: numeric_fields(s, kib=True), errors
            ),
            "vmstat": read_metric(self.proc / "vmstat", numeric_fields, errors),
            "pressure": {
                name: read_metric(self.proc / "pressure" / name, pressure, errors)
                for name in ("cpu", "io", "memory")
            },
        }
        processes = {}
        for pid, expected in self.pids.items():
            directory = self.proc / str(pid)
            stat = read_metric(directory / "stat", process_stat, errors)
            if stat is None or stat["start_ticks"] != expected:
                errors[str(directory)] = "ExitedOrReplaced"
                processes[str(pid)] = None
                continue
            value = {
                "stat": stat,
                "status": read_metric(
                    directory / "status", lambda s: numeric_fields(s, kib=True), errors
                ),
                "io": read_metric(directory / "io", numeric_fields, errors),
            }
            if self.pss:
                value["smaps_rollup"] = read_metric(
                    directory / "smaps_rollup",
                    lambda s: numeric_fields(s, kib=True),
                    errors,
                )
            # Refuse a PID reused while the other files were being read.
            after = read_metric(directory / "stat", process_stat, errors)
            if after is None or after["start_ticks"] != expected:
                errors[str(directory)] = "ExitedOrReplaced"
                value = None
            processes[str(pid)] = value

        groups = {}
        for directory, expected in self.cgroups.items():
            try:
                if self.identity(directory) != expected:
                    raise ValueError("Replaced cgroup")
                values = {
                    name: read_metric(directory / name, int, errors)
                    for name in (
                        "memory.current",
                        "memory.swap.current",
                        "pids.current",
                    )
                }
                for name in ("memory.stat", "memory.events", "cpu.stat"):
                    values[name] = read_metric(directory / name, numeric_fields, errors)
                for name in ("cpu.pressure", "io.pressure", "memory.pressure"):
                    values[name] = read_metric(directory / name, pressure, errors)
                values["io.stat"] = read_metric(
                    directory / "io.stat", device_io, errors
                )
                if self.identity(directory) != expected:
                    raise ValueError("Replaced cgroup")
            except (OSError, ValueError) as exc:
                errors[str(directory)] = type(exc).__name__
                values = None
            groups[str(directory)] = values

        storage = {}
        for path, expected_device in self.storage.items():
            try:
                observed_device = path.stat().st_dev
                usage = os.statvfs(path)
                if (
                    observed_device != expected_device
                    or path.stat().st_dev != expected_device
                ):
                    raise ValueError("Changed storage device")
                storage[str(path)] = {
                    "available_bytes": usage.f_bavail * usage.f_frsize,
                    "free_bytes": usage.f_bfree * usage.f_frsize,
                    "total_bytes": usage.f_blocks * usage.f_frsize,
                    "available_inodes": usage.f_favail,
                }
            except (OSError, ValueError) as exc:
                errors[str(path)] = type(exc).__name__
                storage[str(path)] = None
        return {
            "system": system,
            "processes": processes,
            "cgroups": groups,
            "storage": storage,
            "unavailable": errors,
        }


class Summary:
    """Extrema for the first sample's scalar paths; later metrics stay in JSONL.

    Freezing this catalog prevents device/interface churn from retaining an
    unbounded history of metric names. Unavailable readings are never zeroes.
    """

    def __init__(self):
        self.samples = 0
        self.samples_with_unavailable = 0
        self.unaggregated_numeric_readings = 0
        self.metrics: dict[str, dict[str, int | float]] = {}

    def add(self, sample: dict[str, Any]) -> None:
        self.samples += 1
        self.samples_with_unavailable += bool(sample["unavailable"])

        for group in ("system", "processes", "cgroups", "storage"):
            self._visit(sample[group], group)

    def _visit(self, value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                self._visit(child, f"{path}/{key}")
        elif type(value) in (int, float) and math.isfinite(value):
            item = self.metrics.get(path)
            if item is None:
                if self.samples > 1:
                    self.unaggregated_numeric_readings += 1
                    return
                self.metrics[path] = {
                    "samples": 1,
                    "first": value,
                    "last": value,
                    "min": value,
                    "max": value,
                }
            else:
                item.update(
                    samples=item["samples"] + 1,
                    last=value,
                    min=min(item["min"], value),
                    max=max(item["max"], value),
                )


def record(
    sampler: Sampler,
    output: Any,
    *,
    duration: float,
    interval: float,
    context: dict[str, Any],
    stop: Callable[[], bool],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    def write(value: dict[str, Any]) -> None:
        output.write(json.dumps(value, allow_nan=False) + "\n")
        output.flush()

    started = clock()
    cpu_started = time.process_time()
    summary = Summary()
    write(
        {
            "type": "metadata",
            "version": 1,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "clock_ticks_per_second": os.sysconf("SC_CLK_TCK"),
            "page_size_bytes": os.sysconf("SC_PAGE_SIZE"),
            "duration_seconds": duration,
            "interval_seconds": interval,
            "context": context,
            "pid_start_ticks": sampler.pids,
            "cgroup_identities": {
                str(path): value for path, value in sampler.cgroups.items()
            },
            "storage_devices": {
                str(path): value for path, value in sampler.storage.items()
            },
        }
    )
    maximum_sample_seconds = 0.0
    overruns = 0
    interrupted = False
    try:
        while True:
            sample_started = clock()
            sample = sampler.sample()
            sample_seconds = clock() - sample_started
            maximum_sample_seconds = max(maximum_sample_seconds, sample_seconds)
            summary.add(sample)
            write(
                {
                    "type": "sample",
                    "elapsed_seconds": sample_started - started,
                    "sample_seconds": sample_seconds,
                    **sample,
                }
            )
            if stop() or clock() - started >= duration:
                break
            # Skip missed deadlines; never build a backlog of scheduled samples.
            delay = min(started + duration, sample_started + interval) - clock()
            if delay <= 0:
                overruns += 1
            else:
                sleep(delay)
    except KeyboardInterrupt:
        interrupted = True
    result = {
        "type": "summary",
        "reason": "interrupted" if interrupted or stop() else "completed",
        "elapsed_seconds": clock() - started,
        "samples": summary.samples,
        "samples_with_unavailable": summary.samples_with_unavailable,
        "unaggregated_numeric_readings": summary.unaggregated_numeric_readings,
        "maximum_sample_seconds": maximum_sample_seconds,
        "interval_overruns": overruns,
        "recorder_cpu_seconds": time.process_time() - cpu_started,
        "recorder_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * 1024,
        "metrics": summary.metrics,
    }
    write(result)
    return result


def positive_seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Use a finite positive number of seconds")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New JSONL file on selected external storage",
    )
    parser.add_argument("--duration", type=positive_seconds, required=True)
    parser.add_argument("--interval", type=positive_seconds, required=True)
    parser.add_argument(
        "--workload", required=True, help="Run label, such as idle or sustained scrape"
    )
    parser.add_argument(
        "--setting",
        action="append",
        default=[],
        help="Record one explicitly selected non-secret NAME=VALUE; repeat as needed",
    )
    parser.add_argument(
        "--pid",
        type=int,
        action="append",
        default=[],
        help="Exact PID to observe, not its descendants; repeat as needed",
    )
    parser.add_argument(
        "--cgroup",
        type=Path,
        action="append",
        default=[],
        help="Existing cgroup v2 service directory; includes descendants",
    )
    parser.add_argument(
        "--storage-path",
        type=Path,
        action="append",
        default=[],
        help="Existing external data directory; repeat as needed",
    )
    parser.add_argument(
        "--pss",
        action="store_true",
        help="Read smaps_rollup for each explicit PID when permitted",
    )
    parser.add_argument(
        "--sensor",
        type=Path,
        action="append",
        default=[],
        help="Optional existing numeric sysfs temperature/frequency file; native units are retained",
    )
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This recorder uses Linux procfs and optional cgroup v2 metrics")
    if any(pid <= 0 for pid in args.pid):
        parser.error("PIDs must be positive")
    if any("=" not in item or not item.split("=", 1)[0] for item in args.setting):
        parser.error("Each setting must have the form NAME=VALUE")
    stopped = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal stopped
        stopped = True
        raise KeyboardInterrupt

    previous = {
        sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        sampler = Sampler(
            pids=args.pid,
            cgroups=[p.resolve(strict=True) for p in args.cgroup],
            storage=[p.resolve(strict=True) for p in args.storage_path],
            pss=args.pss,
            sensors=tuple(p.resolve(strict=True) for p in args.sensor),
        )
        # Exclusive creation preserves previous runs; no service files are opened
        # for writing. The parent directory must already exist.
        with args.output.open("x") as output:
            result = record(
                sampler,
                output,
                duration=args.duration,
                interval=args.interval,
                context={"workload": args.workload, "settings": args.setting},
                stop=lambda: stopped,
            )
        print(
            json.dumps(
                {key: value for key, value in result.items() if key != "metrics"}
            )
        )
        return 130 if stopped else 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
