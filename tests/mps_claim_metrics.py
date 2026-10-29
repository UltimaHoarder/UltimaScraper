"""Window-aligned claim telemetry; method wall time is not SQL-only time."""

from statistics import mean


def handler_capacity_model(tasks, fetch_slots):
    """Use every completed input; steady completion cohorts bias long handlers."""
    workload_mean = mean(task["handler_ms"] / 1000 for task in tasks)
    return {
        "handler_workload_mean_seconds": workload_mean,
        "modeled_fetch_ceiling_tasks_per_s": fetch_slots / workload_mean
        if fetch_slots and workload_mean > 0 else None,
        "fetch_ceiling_scope": "Configured fetch slots / full-workload handler mean. Finite-workload model, not an independently measured sustainable capacity or efficiency denominator.",
    }


def claim_station_metrics(workers, start, end):
    claims = [s for w in workers for s in w.get("claim_spans", [])
              if start <= s[1] < end]
    positive = [s for s in claims if s[2]]
    status = [s for w in workers for s in w.get("status_spans", [])
              if start <= s[1] < end]
    details_present = bool(workers) and all("claim_details" in w for w in workers)
    details = [s for w in workers for s in w.get("claim_details", [])
               if start <= s["finished"] < end and s["tasks"]]
    queries = {}
    for sample in details:
        for name, value in sample["queries"].items():
            station = queries.setdefault(name, {"calls": 0, "seconds": 0.0})
            station["calls"] += value["calls"]
            station["seconds"] += value["seconds"]
    cores = []
    for worker in workers:
        samples = [s for s in worker.get("runtime_samples", [])
                   if start <= s["at"] < end]
        if len(samples) < 2 or any("cpu_seconds" not in s for s in samples):
            cores.append(None)
        else:
            cores.append((samples[-1]["cpu_seconds"] - samples[0]["cpu_seconds"])
                         / (samples[-1]["at"] - samples[0]["at"]))
    return {
        "claim_transaction_mean_ms": mean((b - a) * 1000 for a, b, _ in positive)
        if positive else None,
        "steady_claim_calls": len(claims),
        "steady_claim_empty_calls": sum(not s[2] for s in claims),
        "steady_claim_page_mean": mean(s[2] for s in positive) if positive else None,
        "claim_thread_cpu_mean_ms": mean(s["thread_cpu_seconds"] * 1000 for s in details)
        if details_present and details else None,
        "claim_driver_mean_ms": sum(v["seconds"] for v in queries.values()) * 1000 / len(details)
        if details_present and details else None,
        "claim_driver_stations": {
            name: {**value, "mean_ms_per_claim": value["seconds"] * 1000 / len(details)}
            for name, value in queries.items()
        } if details_present and details else None,
        "claim_timing_scope": "Same steady completion window. Transaction time covers the whole claim method. Thread CPU and DBAPI driver time overlap; do not add them.",
        "worker_cpu_cores": sum(cores) if cores and all(c is not None for c in cores) else None,
        "worker_cpu_cores_by_process": cores,
        "steady_worker_status_calls": len(status),
        "steady_worker_status_mean_ms": mean((b - a) * 1000 for a, b in status)
        if status else None,
    }
