"""Observe the real dashboard HTTP paths during a task-owned offline run."""

import json
import math
import statistics
import threading
import time
import urllib.request
from datetime import UTC, datetime

BACKEND = "/api/v1/system/backend"
JOBS = "/api/v1/jobs?page=1&page_size=200&include_tasks=false"
ACTIVE = "/api/v1/jobs/active-tasks?limit_jobs=120&limit_tasks=250"
QUEUE = "/api/v1/admin/queue-stats"
HEALTH = "/api/v1/admin/health"
MEMORY = "/api/v1/system/memory"


def distribution(values):
    values = sorted(values)
    return {
        "n": len(values),
        "median": statistics.median(values),
        "p95": values[math.ceil(0.95 * len(values)) - 1],
        "maximum": max(values),
    }


class DashboardObserver:
    def __init__(self, port, output, started_event):
        self.port = port
        self.output = output
        self.started_event = started_event
        self.stop_event = threading.Event()
        self.errors = []
        self.active_jobs = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        if not self.started_event.wait(900):
            return
        started = time.monotonic()
        intervals = {BACKEND: 5, JOBS: 4, ACTIVE: 10, QUEUE: 10, HEALTH: 15, MEMORY: 10}
        due = dict.fromkeys(intervals, 0.0)
        with (self.output / "dashboard.jsonl").open("w") as output:
            while not self.stop_event.is_set():
                for path, interval in intervals.items():
                    now = time.monotonic() - started
                    if now < due[path]:
                        continue
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{self.port}{path}",
                        headers={"X-USR-Admin-Token": "fixture-local-only"},
                    )
                    at = time.monotonic()
                    try:
                        with urllib.request.urlopen(request, timeout=30) as response:
                            body = response.read()
                            status = response.status
                        payload = json.loads(body)
                        assert status == 200 and payload.get("success") is not False
                        record = {
                            "path": path,
                            "elapsed": now,
                            "seconds": time.monotonic() - at,
                            "response_bytes": len(body),
                            "response": payload,
                        }
                        if path == BACKEND and payload.get("system_stats"):
                            stamp = datetime.fromisoformat(
                                payload["system_stats"]["timestamp"]
                            )
                            record["telemetry_age_seconds"] = (
                                datetime.now(UTC) - stamp
                            ).total_seconds()
                        if path == JOBS:
                            self.active_jobs = any(
                                job["status"] in ("running", "pending")
                                for job in payload["jobs"]
                            )
                            intervals[ACTIVE] = 2.5 if self.active_jobs else 10
                        output.write(json.dumps(record) + "\n")
                        output.flush()
                    except Exception as exc:  # noqa: BLE001 - retain every observer failure
                        self.errors.append({"path": path, "error": repr(exc)})
                        output.write(
                            json.dumps({"elapsed": now, "error": self.errors[-1]})
                            + "\n"
                        )
                        output.flush()
                        return
                    due[path] = now + interval
                self.stop_event.wait(0.1)

    def stop(self):
        self.stop_event.set()
        self.started_event.set()
        self.thread.join(timeout=45)
        assert not self.thread.is_alive(), "Owned dashboard observer did not stop"

    def verify(self):
        # Stream captured pages so verification doesn't retain a two-hour HTTP archive.
        assert not self.errors, self.errors
        paths = (BACKEND, JOBS, ACTIVE, QUEUE, HEALTH, MEMORY)
        latencies = {path: [] for path in paths}
        largest = dict.fromkeys(paths, 0)
        ages = []
        worker_seen = active_seen = worker_memory_seen = False
        first_timestamp = None
        timestamp_changed = False
        max_jobs = max_active = max_workers = max_disks = busy = memory_count = 0
        with (self.output / "dashboard.jsonl").open() as source:
            for line in source:
                row = json.loads(line)
                assert "error" not in row, row
                path = row["path"]
                payload = row["response"]
                latencies[path].append(row["seconds"] * 1000)
                largest[path] = max(largest[path], row["response_bytes"])
                if path == BACKEND and payload.get("system_stats"):
                    stats = payload["system_stats"]
                    assert payload["backend_id"] == "runtime-fixture"
                    assert stats["cpu_count"] > 0 and stats["memory_total"] > 0
                    age = row["telemetry_age_seconds"]
                    assert 0 <= age < 15, age
                    ages.append(age)
                    stamp = stats["timestamp"]
                    if first_timestamp is None:
                        first_timestamp = stamp
                    timestamp_changed |= stamp != first_timestamp
                    worker_seen |= payload["worker_count"] == 1
                    active_seen |= payload["active_workers"] == 1
                    max_workers = max(max_workers, payload["worker_count"])
                    max_disks = max(max_disks, len(stats["disks"]))
                    busy += payload["active_workers"] > 0
                elif path == JOBS:
                    max_jobs = max(max_jobs, len(payload["jobs"]))
                elif path == ACTIVE:
                    max_active = max(max_active, len(payload["tasks"]))
                elif path == MEMORY:
                    for worker in payload["workers"]:
                        memory_count += 1
                        worker_memory_seen |= worker["rss_bytes"] > 0
        assert all(latencies.values()), {
            path: len(rows) for path, rows in latencies.items()
        }
        assert len(ages) >= 2 and timestamp_changed
        assert worker_seen and active_seen and worker_memory_seen
        result = {
            "endpoints": {
                path: {
                    "latency_ms": distribution(latencies[path]),
                    "largest_response_bytes": largest[path],
                }
                for path in paths
            },
            "populated_backend_samples": len(ages),
            "backend_samples": len(latencies[BACKEND]),
            "telemetry_age_seconds": distribution(ages),
            "largest_job_page": max_jobs,
            "largest_active_task_page": max_active,
            "largest_worker_count": max_workers,
            "largest_disk_count": max_disks,
            "busy_backend_samples": busy,
            "worker_memory_samples": memory_count,
            "errors": self.errors,
        }
        (self.output / "dashboard-verification.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        return result
