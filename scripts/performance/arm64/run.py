"""Guest controller: run real jobs and reject incomplete resource evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import time
from collections import deque
from pathlib import Path

ROOT = Path("/srv/usr")
GIB = 1024**3


def source_identity():
    manifest = json.loads((ROOT / "source-manifest.json").read_text())
    for relative, expected in manifest["files"].items():
        assert (
            hashlib.sha256((ROOT / "project" / relative).read_bytes()).hexdigest()
            == expected
        ), relative
    return manifest["identity"]


def assess(output, *, sustained):
    result = json.loads((output / "result.json").read_text())
    initial = result["initial_cgroup"]
    final = json.loads((output / "shutdown-cgroup.json").read_text())
    assert result["target_met"] and result["admission_stop"] is None, result
    assert result["completed_profiles"] > 0
    assert result["runtime_environment"]["architecture"] == "aarch64"
    assert 3.5 * GIB < result["runtime_environment"]["memory_total_bytes"] <= 4 * GIB
    live = result["settings"]["workload"] == "guest-onlyfans"
    iterations = result["completed_iterations"]
    if live:
        assert result["completed_profiles"] == 1
        assert result["verification"]["files_verified"] > 0
        network = result["verification"]["network"]
        assert network["auths"] and all(
            row["guest"] for row in network["auths"].values()
        )
        assert len(network["performers"]) == 1 and all(
            row["username"].casefold() == "onlyfans"
            for row in network["performers"].values()
        )
        assert result["verification"]["stored_auths"] == 0
    else:
        assert (
            result["verification"]["files_verified"]
            == iterations * result["settings"]["files"]
        )
    assert result["verification"]["history"]["jobs_verified"] == iterations
    assert result["platform_requests"] == result["verification"]["files_verified"]
    assert result["platform_peak_active"] == result["settings"]["file_concurrency"]
    assert not result["dashboard"]["errors"] and not result["websocket"]["errors"]
    assert final["memory.events"]["oom"] == initial["memory.events"]["oom"]
    assert final["memory.events"]["oom_kill"] == initial["memory.events"]["oom_kill"]
    assert final["memory.swap.current"] == 0
    assert not Path((output / "owned-root.txt").read_text().strip()).exists()
    workload_start = None
    minimum_available = None
    early_pss = []
    late_pss = deque()
    peak_service_pss = 0
    last = None
    with (output / "samples.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            assert row["cgroup"]["guest_data_disk_stat"] is not None
            assert row["cgroup"]["memory.swap.current"] == 0
            for metric in ("pswpin", "pswpout", "oom_kill"):
                assert (
                    row["cgroup"]["guest_vmstat"][metric]
                    == initial["guest_vmstat"][metric]
                )
            peak_service_pss = max(
                peak_service_pss, sum(role["pss"] for role in row["totals"].values())
            )
            if row["phase"] == "workload" and workload_start is None:
                workload_start = row["elapsed"]
            if (
                workload_start is not None
                and row["elapsed"]
                >= workload_start + result["settings"]["warmup_seconds"]
            ):
                available = row["host_memory_available_bytes"]
                minimum_available = (
                    available
                    if minimum_available is None
                    else min(minimum_available, available)
                )
                pss = sum(row["totals"][role]["pss"] for role in ("api", "worker"))
                if (
                    row["elapsed"]
                    <= workload_start + result["settings"]["warmup_seconds"] + 600
                ):
                    early_pss.append(pss)
                late_pss.append((row["elapsed"], pss))
                while late_pss[0][0] < row["elapsed"] - 600:
                    late_pss.popleft()
            last = row
    assert (
        last and last["queue_depth"] == last["queue_bytes"] == last["active_http"] == 0
    )
    assert minimum_available is not None and minimum_available >= GIB, minimum_available
    early = statistics.median(early_pss)
    late = statistics.median(value for _, value in late_pss)
    if sustained:
        assert late - early <= max(64 * 1024**2, early * 0.10), (early, late)
    verdict = {
        "passed": True,
        "scope": "sustained" if sustained else "smoke",
        "completed_profiles": result["completed_profiles"],
        "completed_iterations": iterations,
        "workload": result["settings"]["workload"],
        "authentication": "guest" if live else "synthetic stored auth",
        "performer": "onlyfans" if live else "synthetic performers",
        "verified_files": result["verification"]["files_verified"],
        "verified_bytes": result["verification"]["bytes_verified"],
        "peak_file_downloads": result["platform_peak_active"],
        "workload_seconds": result["workload_seconds"],
        "iterations_per_hour": iterations / result["workload_seconds"] * 3600,
        "minimum_available_bytes": minimum_available,
        "peak_service_pss_bytes": peak_service_pss,
        "early_api_worker_pss_bytes": early,
        "late_api_worker_pss_bytes": late,
        "oom_kills": 0,
        "swap_activity": 0,
        "queues_drained": True,
        "settings": result["settings"],
    }
    (output / "assessment.json").write_text(json.dumps(verdict, indent=2) + "\n")
    return verdict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=["smoke", "sustained", "diagnostic"], required=True
    )
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument("--duration", type=int, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--max-posts", type=int, required=True)
    parser.add_argument("--downloads", type=int)
    parser.add_argument(
        "--workload", choices=["guest-onlyfans", "offline-fixture"], required=True
    )
    args = parser.parse_args()
    if not 4 <= args.max_posts <= 100:
        parser.error("Max posts must be between 4 and 100")
    if args.downloads is not None and not 1 <= args.downloads <= 100:
        parser.error("Downloads must be between 1 and 100")
    concurrencies = (
        [args.downloads]
        if args.downloads is not None
        else {"smoke": [2], "sustained": [2, 4], "diagnostic": [4]}[args.mode]
    )
    if args.workload == "guest-onlyfans" and max(concurrencies) > args.max_posts:
        parser.error("Max posts must be at least the selected downloads")
    if args.workload == "offline-fixture" and max(concurrencies) > 20:
        parser.error("The offline fixture supports at most 20 concurrent downloads")
    assert args.name.replace("-", "").isalnum()
    assert os.uname().machine == "aarch64"
    environment = json.loads((ROOT / "environment.json").read_text())
    assert 3.5 * GIB < environment["memory_total_bytes"] <= 4 * GIB
    assert environment["swap_total_bytes"] == 0
    identity = source_identity()
    output = ROOT / "runs" / args.name
    output.mkdir(exist_ok=False)
    (output / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
    report = {
        "source_identity": identity,
        "mode": args.mode,
        "workload": args.workload,
        "download_concurrencies": concurrencies,
        "cases": [],
        "passed": False,
        "acceptance": args.mode != "diagnostic",
    }
    path = output / "report.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    # A sustained command always proves the actual current source in a short
    # guest run first. The warm-up/drain of that run is not throughput evidence.
    smoke_concurrency = concurrencies[0]
    cases = [(f"smoke-{smoke_concurrency}", smoke_concurrency, 0)]
    if args.mode == "sustained":
        cases += [
            (f"sustained-{concurrency}", concurrency, args.duration)
            for concurrency in concurrencies
        ]
    elif args.mode == "diagnostic":
        cases = [(f"diagnostic-{concurrencies[0]}", concurrencies[0], args.duration)]
    for name, concurrency, duration in cases:
        case = output / name
        capacity = (shutil.disk_usage(ROOT).free - 6 * GIB) // (20 * 1024**2)
        profiles = (
            (1000000 if duration else 1)
            if args.workload == "guest-onlyfans"
            else int(capacity)
            if duration
            else 5
        )
        assert profiles > 0
        settings = {
            "workload": args.workload,
            "output": str(case),
            "data_parent": str(ROOT / "tmp"),
            "profiles": profiles,
            "active_profiles": 1,
            "files": args.max_posts if args.workload == "guest-onlyfans" else 20,
            "file_concurrency": concurrency,
            "part_concurrency": 4,
            "batch_size": 20,
            "workers": 1,
            "control_workers": 1,
            "shared_buffers_mb": 128,
            "media_bytes": 1024**2,
            "response_delay": 0.2,
            "idle_seconds": 10 if not duration else 60,
            "warmup_seconds": 0 if not duration else min(300, duration // 4),
            "drain_seconds": 40 if not duration else 120,
            "timeout_seconds": max(1800, duration + 1800),
            "stall_seconds": 120,
            "redis_aof": "yes",
            "require_memory_max_bytes": 3 * GIB,
            "minimum_workload_seconds": duration,
            "catalog_media": 10000 if not duration else 100000,
            "catalog_users": 1000,
            "seed_batch": 10000,
            "statistics_interval": 60,
            "maintenance_interval": 300,
            "checkpoint_timeout_seconds": 180,
            "startup_timeout_seconds": 600,
            "minimum_free_bytes": 4 * GIB,
            "minimum_catalog_bytes": 0,
            "minimum_available_bytes": GIB,
            "low_headroom_seconds": 60,
            "retention_seconds": 10,
            "retention_batch_size": 64,
            "reconcile_interval_seconds": 30,
        }
        unit = f"usr-arm64-{time.time_ns()}"
        command = [
            "systemd-run",
            "--user",
            "--wait",
            "--pipe",
            "--collect",
            f"--unit={unit}",
            "--property=MemoryMax=3G",
            "--property=MemorySwapMax=0",
            "--property=OOMPolicy=kill",
            "--setenv=PATH=/usr/lib/postgresql/18/bin:/usr/local/bin:/usr/bin:/bin",
            f"--property=RuntimeMaxSec={settings['timeout_seconds'] + 1800}",
            str(ROOT / "project/UltimaScraper/.venv/bin/python"),
            "-B",
            str(Path(__file__).with_name("benchmark.py")),
        ]
        for key, value in settings.items():
            command += ["--" + key.replace("_", "-"), str(value)]
        if args.diagnostics or args.mode == "diagnostic":
            command.append("--diagnostics")
        (output / f"{name}-command.json").write_text(
            json.dumps(command, indent=2) + "\n"
        )
        active = ROOT / "active-run.json"
        temporary = active.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "run": args.name,
                    "case": name,
                    "source_identity": identity,
                    "status_path": str(case / "status.json"),
                }
            )
            + "\n"
        )
        temporary.replace(active)
        print(json.dumps({"event": "case_start", "case": name}), flush=True)
        outcome = subprocess.run(command, check=False)
        try:
            if outcome.returncode:
                raise RuntimeError(f"{name} failed: {outcome.returncode}; see {case}")
            assert source_identity() == identity, "Source changed between cases"
            verdict = assess(
                case, sustained=bool(duration) and args.mode != "diagnostic"
            )
        except Exception as error:
            failure_path = case / "failure.json"
            failure = (
                json.loads(failure_path.read_text())
                if failure_path.exists()
                else {
                    "type": type(error).__name__,
                    "message": str(error),
                    "returncode": outcome.returncode,
                }
            )
            report["cases"].append({"name": name, "passed": False, "failure": failure})
            path.write_text(json.dumps(report, indent=2) + "\n")
            raise
        if args.mode == "diagnostic":
            verdict["scope"] = "diagnostic"
            (case / "assessment.json").write_text(json.dumps(verdict, indent=2) + "\n")
        report["cases"].append({"name": name, **verdict})
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "event": "case_passed",
                    "case": name,
                    "files": verdict["verified_files"],
                    "minimum_available_bytes": verdict["minimum_available_bytes"],
                }
            ),
            flush=True,
        )
    report["passed"] = True
    path.write_text(json.dumps(report, indent=2) + "\n")
    (ROOT / "active-run.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
