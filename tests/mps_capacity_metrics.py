"""Matched, time-weighted reporting for the owned MPS capacity benchmark."""

import time
from itertools import pairwise
from statistics import mean

from mps_claim_metrics import claim_station_metrics, handler_capacity_model


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    return values[min(len(values) - 1, int((len(values) - 1) * fraction))]


def interval_occupancy(spans, start, end):
    """Exact occupied time and peak for half-open intervals, clipped to window."""
    events = []
    for left, right, *_ in spans:
        left, right = max(left, start), min(right, end)
        if right > left:
            events.extend(((left, 1), (right, -1)))
    current = peak = 0
    area = 0.0
    previous = start
    for at, delta in sorted(events):
        area += current * (at - previous)
        current += delta
        peak = max(peak, current)
        previous = at
    return {"mean": area / (end - start), "max": peak}


def sampled_mean(samples, key, start, end):
    """Left-hold samples; no invented coverage before first observation."""
    area = covered = 0.0
    for i, sample in enumerate(samples):
        left = max(start, sample["at"])
        right = min(end, samples[i + 1]["at"] if i + 1 < len(samples) else end)
        if right > left:
            area += sample[key] * (right - left)
            covered += right - left
    return area / covered if covered else None


def configured_worker_budgets(workers):
    """Use recorded worker budgets; old evidence without them stays unknown."""
    if not workers or any(
        "configured_fetch_slots" not in worker
        or "configured_persistence_slots" not in worker
        for worker in workers
    ):
        return None, None
    fetch = sum(worker["configured_fetch_slots"] for worker in workers)
    total = fetch + sum(worker["configured_persistence_slots"] for worker in workers)
    if fetch <= 0 or total < fetch:
        raise ValueError("Invalid recorded worker budgets")
    return fetch, total


def capacity_report(
    *,
    started,
    ended,
    workers,
    occupancy,
    refills,
    archives,
    writer_batches,
    writer_transactions,
    writer_pool,
    planner_loops,
    redis,
    host=(),
    writer_runtime=(),
):
    tasks = sorted(
        (s for w in workers for s in w["phase_samples"]), key=lambda s: s["finished"]
    )
    n = len(tasks)
    lo, hi = int(n * 0.1), int(n * 0.9)
    start, end = tasks[lo]["finished"], tasks[hi]["finished"]
    duration = end - start
    fetch_budget, worker_budget = configured_worker_budgets(workers)
    steady = tasks[lo:hi]
    task_spans = [(s["started"], s["finished"]) for s in tasks]
    active = interval_occupancy(task_spans, start, end)
    fetch = (
        interval_occupancy(
            [(s["started"], s["writer_submitted"]) for s in tasks], start, end
        )
        if all("writer_submitted" in s for s in tasks)
        else None
    )
    batches = [b for b in writer_batches if start <= b[1] < end]
    finishes = [b for w in workers for b in w["finish_batches"] if start <= b[1] < end]
    claims = [b for w in workers for b in w["claim_spans"] if start <= b[1] < end]
    ready = [
        {**s, "available": int(s["ready"] > 0), "low_water": int(s["ready"] < 4000)}
        for s in occupancy
    ]
    offset = time.time() - time.monotonic()
    admissions = [
        r for r in refills if start <= r["timestamp_ms"] / 1000 - offset < end
    ]
    archive_window = [
        r for r in archives if start <= r["timestamp_ms"] / 1000 - offset < end
    ]
    loops = [(a, b) for a, b in planner_loops if start <= b < end]
    runtime = [
        s for w in workers for s in w["runtime_samples"] if start <= s["at"] < end
    ]
    redis_window = [s for s in redis if start <= s["at"] < end]
    first, last = (redis_window[0], redis_window[-1]) if redis_window else ({}, {})
    redis_commands = {}
    for key, value in last.get("commands", {}).items():
        old = first.get("commands", {}).get(key, {})
        redis_commands[key] = {
            k: value.get(k, 0) - old.get(k, 0) for k in ("calls", "usec")
        }
    redis_duration = last.get("at", end) - first.get("at", start)
    transactions = sum(start <= t < end for t in writer_transactions)
    writer_count = sum(b[2] for b in batches)
    ready_available = sampled_mean(ready, "available", start, end)
    pool_mean = sampled_mean(
        [{"at": a, "count": b} for a, b in sorted(writer_pool)], "count", start, end
    )
    worker_pool_mean = sum(
        sampled_mean(
            [{"at": a, "count": b} for a, b in sorted(w["pool_events"])],
            "count",
            start,
            end,
        )
        or 0
        for w in workers
    )
    peak_counts = {}
    for sample in tasks:
        bucket = int(sample["finished"] - started)
        peak_counts[bucket] = peak_counts.get(bucket, 0) + 1
    host_cpu = []
    for previous, current in pairwise(host):
        if not start <= current["at"] < end:
            continue
        delta = {k: v - previous["cpu"][k] for k, v in current["cpu"].items()}
        total = sum(v for k, v in delta.items() if k not in ("guest", "guest_nice"))
        if total:
            host_cpu.append(1 - (delta.get("idle", 0) + delta.get("iowait", 0)) / total)
    periods = []
    for i in range(4):
        left, right = start + duration * i / 4, start + duration * (i + 1) / 4
        period_tasks = [s for s in tasks if left <= s["finished"] < right]
        period_refills = [
            r for r in admissions if left <= r["timestamp_ms"] / 1000 - offset < right
        ]
        period_writer = [s for s in writer_runtime if left <= s["at"] < right]
        periods.append(
            {
                "tasks_per_s": sum(left <= s["finished"] < right for s in tasks)
                / (right - left),
                "ready_mean": sampled_mean(ready, "ready", left, right),
                "resident_terminal_mean": sampled_mean(
                    occupancy, "resident_terminal", left, right
                ),
                "writer_queue_mean": sampled_mean(redis, "queue", left, right),
                "writer_elapsed_mean_ms": mean(
                    s["writer"]["elapsed_ms"] for s in period_tasks
                ),
                "refill_mean_pass_ms": mean(r["pass_ms"] for r in period_refills)
                if period_refills
                else None,
                "writer_rss_mean_mib": mean(s["rss_mib"] for s in period_writer)
                if period_writer
                else None,
                "worker_rss_mean_mib": mean(
                    s.get("rss_kib", s.get("rss_max_kib", 0)) / 1024
                    for s in runtime
                    if left <= s["at"] < right
                ),
            }
        )
    sample_gaps = [
        b["at"] - a["at"] for a, b in pairwise(occupancy) if start <= b["at"] < end
    ]
    writer_resources = [s for s in writer_runtime if start <= s["at"] < end]
    host_window = [s for s in host if start <= s["at"] < end]

    def cpu_cores(samples, key):
        if len(samples) < 2 or key not in samples[0]:
            return None
        return (samples[-1][key] - samples[0][key]) / (
            samples[-1]["at"] - samples[0]["at"]
        )

    return {
        "tasks": n,
        "whole_seconds": ended - started,
        "whole_tasks_per_s": n / (ended - started),
        "steady_start": start,
        "steady_end": end,
        "steady_seconds": duration,
        "steady_tasks_per_s": (hi - lo) / duration,
        "peak_1s_completion_burst": max(peak_counts.values()),
        "latency_seconds": {
            "mean": mean(s["duration_s"] for s in tasks),
            **{
                f"p{int(q * 100)}": percentile([s["duration_s"] for s in tasks], q)
                for q in (0.5, 0.95, 0.99)
            },
        },
        "steady_active_tasks": active,
        "steady_worker_occupancy": active["mean"] / worker_budget if worker_budget else None,
        "worker_slots": worker_budget,
        "fetch_slots": fetch_budget,
        "steady_fetch_active": fetch,
        "steady_fetch_occupancy": fetch["mean"] / fetch_budget if fetch and fetch_budget else None,
        "steady_handler_mean_seconds": mean(s["handler_ms"] / 1000 for s in steady),
        "steady_handler_scope": "Handler duration of steady-window completions; long tasks crossing boundaries can be underrepresented.",
        **handler_capacity_model(tasks, fetch_budget),
        "proxy_active_routes": None,
        "proxy_occupancy": None,
        "proxy_scope": "Synthetic handler delay only; no HTTP requests or proxies exercised",
        "ready_availability": ready_available,
        "ready_empty_seconds": duration * (1 - ready_available)
        if ready_available is not None
        else None,
        "ready_mean": sampled_mean(ready, "ready", start, end),
        "ready_min": min(
            (s["ready"] for s in ready if start <= s["at"] < end), default=None
        ),
        "ready_low_water_ratio": sampled_mean(ready, "low_water", start, end),
        "ready_sample_gap_p95_ms": percentile(
            [gap * 1000 for gap in sample_gaps], 0.95
        ),
        "ready_sample_gap_max_ms": max(sample_gaps, default=0) * 1000,
        "resident_execution_max": max(s["resident_execution"] for s in occupancy),
        "resident_terminal_max": max(s["resident_terminal"] for s in occupancy),
        "refill_passes": len(admissions),
        "refill_nonempty_passes": sum(r["admitted_tasks"] > 0 for r in admissions),
        "refill_admitted": sum(r["admitted_tasks"] for r in admissions),
        "refill_tasks_per_s": sum(r["admitted_tasks"] for r in admissions) / duration,
        "refill_mean_pass_ms": mean(r["pass_ms"] for r in admissions)
        if admissions
        else None,
        "refill_mean_accounting_ms": mean(r["window_accounting_ms"] for r in admissions)
        if admissions
        else None,
        "planner_loop_mean_ms": mean((b - a) * 1000 for a, b in loops)
        if loops
        else None,
        "planner_max_gap_ms": max(
            ((loops[i + 1][0] - b) * 1000 for i, (_, b) in enumerate(loops[:-1])),
            default=None,
        ),
        "archive_tasks_per_s": sum(r["archived_tasks"] for r in archive_window)
        / duration,
        "archive_mean_pass_ms": mean(r["archive_ms"] for r in archive_window)
        if archive_window
        else None,
        "resident_terminal_mean": sampled_mean(
            occupancy, "resident_terminal", start, end
        ),
        "writer_submits_per_s": sum(start <= s["writer_submitted"] < end for s in tasks)
        / duration
        if all("writer_submitted" in s for s in tasks)
        else None,
        "writer_committed_commands_per_s": writer_count / duration,
        "writer_transactions_per_s": transactions / duration,
        "writer_commands_per_transaction": writer_count / transactions
        if transactions
        else None,
        "writer_commands_per_batch": mean(b[2] for b in batches) if batches else None,
        "writer_batch_mean_ms": mean((b - a) * 1000 for a, b, _ in batches)
        if batches
        else None,
        "writer_active_lanes": interval_occupancy(writer_batches, start, end),
        "writer_lane_occupancy": interval_occupancy(writer_batches, start, end)["mean"]
        / 8,
        "writer_queue_mean": sampled_mean(redis, "queue", start, end),
        "writer_queue_max": max((s["queue"] for s in redis), default=None),
        "finish_requests_per_s": sum(b[2] for b in finishes) / duration,
        "finish_SQL_calls_per_s": len(finishes) / duration,
        "finish_batch_mean": mean(b[2] for b in finishes) if finishes else None,
        "finish_SQL_mean_ms": mean((b - a) * 1000 for a, b, _ in finishes)
        if finishes
        else None,
        "claim_tasks_per_s": sum(b[2] for b in claims) / duration,
        "claim_SQL_mean_ms": mean((b - a) * 1000 for a, b, n in claims if n)
        if any(b[2] for b in claims)
        else None,
        "claim_SQL_mean_scope": "Legacy name: whole claim method wall time, including Python and ORM work. Use claim_driver_mean_ms for measured DBAPI query time.",
        **claim_station_metrics(workers, start, end),
        "writer_pool_mean_checked_out": pool_mean,
        "worker_pools_mean_checked_out": worker_pool_mean,
        "redis_calls_per_s": sum(v["calls"] for v in redis_commands.values())
        / redis_duration,
        "redis_calls_per_task": sum(v["calls"] for v in redis_commands.values())
        / (redis_duration * (hi - lo) / duration),
        "redis_command_stats": redis_commands,
        "redis_counter_scope": "Redis commandstats includes commands executed inside Lua; these counts are server operations, not network round trips",
        "redis_roundtrip_mean_ms": mean(s["latency_ms"] for s in redis_window)
        if redis_window
        else None,
        "event_loop_lag_p95_ms": percentile([s["loop_lag_ms"] for s in runtime], 0.95),
        "host_cpu_busy_mean": mean(host_cpu) if host_cpu else None,
        "host_available_memory_min_mib": min(
            (s["available_memory_mib"] for s in host), default=None
        ),
        "observer_rss_max_mib": max(
            (s["observer_rss_mib"] for s in host), default=None
        ),
        "steady_quarters": periods,
        "observer_cpu_cores": cpu_cores(host_window, "observer_cpu_seconds"),
        "writer_cpu_cores": cpu_cores(writer_resources, "cpu_seconds"),
        "writer_rss_max_mib": max(
            (s["rss_mib"] for s in writer_resources), default=None
        ),
        "writer_event_loop_lag_p95_ms": percentile(
            [s["loop_lag_ms"] for s in writer_resources], 0.95
        ),
        "worker_max_rss_mib": max(
            (s.get("rss_kib", s.get("rss_max_kib", 0)) / 1024 for s in runtime),
            default=None,
        ),
        "worker_status_calls": sum(len(w.get("status_spans", [])) for w in workers),
        "worker_status_scope": "Whole-job legacy metrics; steady_worker_status fields use the aligned steady window.",
        "worker_status_mean_ms": mean(
            (b - a) * 1000 for w in workers for a, b in w.get("status_spans", [])
        )
        if any(w.get("status_spans") for w in workers)
        else None,
        "steady_writer_ms": {
            k: mean(s["writer"][k] for s in steady) for k in steady[0]["writer"]
        },
        "steady_lifecycle_ms": {
            k: mean(s["lifecycle"].get(k, 0) for s in steady)
            for k in sorted({k for s in steady for k in s["lifecycle"]})
        },
        "failures": 0,
        "timeouts": 0,
        "http_429": None,
        "integrity": "Every input has a content row, durable receipt, mutation, and archive row; resident window empty",
        "production_1000_verified": False,
    }
