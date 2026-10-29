"""Replay MPS evidence with matched windows and explicit capacity uncertainty.

Configured slots and latency-derived capacity models are reported separately
from throughput efficiency. A finite run does not establish a sustainable
ceiling, so this collector cannot certify the efficiency objective by itself.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def held_samples(samples: list[dict], key: str, start: float, end: float) -> dict:
    """Time-weight observations, including the last observation before start.

    Report gaps and coverage instead of treating a fast poller as independent
    evidence or inventing a value before the first actual observation.
    """
    if end <= start:
        raise ValueError("Observation window must have positive duration")
    ordered = sorted(
        {float(row["timestamp_ms"]): row for row in samples if key in row}.items()
    )
    area = covered = longest_gap = 0.0
    for index, (at, row) in enumerate(ordered):
        following = ordered[index + 1][0] if index + 1 < len(ordered) else end
        left, right = max(start, at), min(end, following)
        if right > left:
            span = right - left
            area += float(row[key]) * span
            covered += span
            longest_gap = max(longest_gap, span)
    return {
        "mean": area / covered if covered else None,
        "coverage_ratio": covered / (end - start),
        "longest_held_interval_ms": longest_gap,
    }


def timestamp_ms(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Evidence timestamps must include a timezone")
    return parsed.timestamp() * 1000


def interval_mean(spans: list[dict], start: float, end: float) -> float:
    """Integrate all task intervals, including tasks spanning a window edge."""
    return sum(
        max(0.0, min(row["finished_ms"], end) - max(row["started_ms"], start))
        for row in spans
    ) / (end - start)


def assess(arm: Path) -> dict:
    submission = json.loads((arm / "submission.json").read_text())
    sql = json.loads((arm / "sql-final.json").read_text())
    final = json.loads((arm / "capture/job-final.json").read_text())
    telemetry = final["runtime_telemetry"]
    job_id = submission["job_id"]
    if sql["job_id"] != job_id or final["job_id"] != job_id:
        raise ValueError("Mixed job evidence")
    counts = {row["status"]: row["count"] for row in sql["counts"]}
    terminal = sum(counts.values())
    steady = sql["steady"]
    start, end = timestamp_ms(steady["start"]), timestamp_ms(steady["end"])
    samples = final["runtime_samples"]["samples"]
    ready = [{**row, "available": int(float(row["ready"]) > 0)} for row in samples]
    active_start = timestamp_ms(telemetry["first_started_at"])
    active_end = timestamp_ms(telemetry["last_finished_at"])
    active_seconds = (active_end - active_start) / 1000
    logs_path = arm / "http-log-summary.json"
    logs = json.loads(logs_path.read_text())["counts"] if logs_path.exists() else None
    audit = sql.get("mutation_task_audit")
    audit_fields = (
        "completed_missing_mutation", "completed_wrong_mutation_count",
        "failed_with_mutation", "mutations_missing_receipt",
    )
    audit_complete = bool(audit) and audit.get("terminal_tasks") == terminal
    audit_passed = audit_complete and all(audit.get(key) == 0 for key in audit_fields)
    intervals_path = arm / "sql-task-intervals.json"
    intervals = json.loads(intervals_path.read_text()) if intervals_path.exists() else None
    if intervals is not None and len(intervals) != terminal:
        raise ValueError("Incomplete SQL interval evidence")
    quarters = []
    if intervals:
        middle = intervals[len(intervals) // 10:len(intervals) * 9 // 10]
        for quarter in range(4):
            left = start + (end - start) * quarter / 4
            right = start + (end - start) * (quarter + 1) / 4
            tasks = [row for row in middle if left <= row["finished_ms"] and (
                row["finished_ms"] < right or quarter == 3 and row["finished_ms"] <= right
            )]
            quarters.append({
                "seconds": (right - left) / 1000,
                "terminal_tasks_per_second": len(tasks) * 1000 / (right - left),
                "successful_tasks_per_second": sum(row["status"] == "completed" for row in tasks) * 1000 / (right - left),
                "exact_SQL_task_occupancy": interval_mean(intervals, left, right),
                "sampled_ready": held_samples(samples, "ready", left, right),
            })
    qualified = (
        sql["state"] == "completed"
        and sql["unique_users"] == terminal == submission["selected_profiles"]
        and sql["resident_work"] == 0
        and audit_passed
        and logs is not None
        and logs.get("request_http_429", 0) == 0
        and sql.get("attempt_count_total") == terminal
    )
    return {
        "arm": arm.name,
        "job_id": job_id,
        "proxy_pool_sha256": submission["proxy"]["pool_sha256"],
        "terminal_tasks": terminal,
        "successful_tasks": counts.get("completed", 0),
        "inconclusive_tasks": counts.get("failed", 0),
        "correctness_audit_complete": audit_complete,
        "correctness_audit_passed": audit_passed,
        "basic_acceptance_gates_passed": qualified,
        "gate_scope": "Exact SQL mutation/receipt audit, unique terminal inputs, no resident work, no expired/replacement attempts, and logged request rate limits. Geography and upstream comparability require separate evidence.",
        "steady": {
            "basis": "SQL 10-90 percent of all terminal tasks",
            "timestamp_scope": "Archived task result-completion timestamps from task payloads; these are not physical SQL commit timestamps and precede the terminal finish await.",
            "seconds": (end - start) / 1000,
            "terminal_tasks_per_second": steady["terminal_tasks_per_second"],
            "successful_tasks_per_second": steady["successful_tasks_per_second"],
            "sampled_inflight": held_samples(samples, "inflight", start, end),
            "sampled_ready": held_samples(samples, "ready", start, end),
            "sampled_ready_availability": held_samples(ready, "available", start, end),
            "exact_SQL_task_occupancy": interval_mean(intervals, start, end) if intervals else None,
            "SQL_interval_scope": "Archived task started_at through task completed_at; excludes later terminal commit/publication work and differs from running/persisting reservation gauges.",
            "time_quarters": quarters,
            "occupancy_scope": "Left-held approximately one-second SQL runtime samples. Holds between samples do not prove sub-second availability; full-job worker capacity is not a steady-window denominator.",
        },
        "active_window": {
            "basis": "Runtime first task start through last task telemetry finish",
            "seconds": active_seconds,
            "terminal_tasks_per_second": terminal / active_seconds,
            "successful_tasks_per_second": counts.get("completed", 0) / active_seconds,
            "occupied_task_slots": telemetry["time_weighted_inflight"],
            "participating_configured_worker_slots": telemetry["time_weighted_effective_worker_capacity"],
            "occupied_route_attempts": telemetry["time_weighted_active_routes"],
            "littles_law_task_integral": terminal / active_seconds * telemetry["mean_task_duration_ms"] / 1000,
            "integral_scope": "Occupancy is derived from task wall-time integrals, not an independent slot gauge. Use all terminal tasks and the same runtime boundaries; successful throughput times whole-job mean duration is incompatible.",
        },
        "ramp_seconds": max(0.0, (start - active_start) / 1000),
        "drain_seconds": max(0.0, (active_end - end) / 1000),
        "whole_job": sql.get("whole_job"),
        "phase_means_ms": {
            "handler_including_writer_wait": telemetry["mean_handler_ms"],
            "writer_observation_overlaps_handler": telemetry["mean_writer_ms"],
            "terminal_finish_await": telemetry["mean_post_ms"],
        },
        "phase_scope": "run_handler times task.run and writer.drain together. Writer elapsed and drain are reported separately inside that interval, so these means cannot be summed or interpreted as exclusive upstream demand.",
        "capacity": {
            "configured": "Finite worker and proxy concurrency budgets; not measured service rates",
            "healthy_effective": None,
            "runnable": "Sampled ready depth and active attempts above; blocked-state station gauges are incomplete",
            "empirical_sustainable_successful_tasks_per_second": None,
            "throughput_efficiency": None,
            "target_demonstrated": False,
            "reason": "A matched independent saturation/plateau experiment with stable queues, healthy upstream outcomes, repeatable rates, and limiting-resource evidence is required. Slot models and best observed throughput cannot certify a ceiling.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arms", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = {"runs": [assess(arm) for arm in args.arms]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"runs": len(report["runs"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
