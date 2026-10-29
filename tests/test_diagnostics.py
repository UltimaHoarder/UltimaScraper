from __future__ import annotations

from types import SimpleNamespace

from ultima_scraper_backend.job_system.diagnostics import (
    RouteAuditCompiler,
    compile_route_audit,
    audit_routes,
    DIRECT_ROUTE_KEY,
)


def test_route_audit_excludes_direct_when_include_direct_connection_is_false():
    job = SimpleNamespace(
        metadata={"include_direct_connection": False},
        job_id="job-test-exclude-direct",
    )

    # 464 pure proxies + some tasks with direct or null proxies
    proxies = [f"http://192.168.1.{i}:8080" for i in range(464)]
    tasks = [
        # Task that used a proxy
        SimpleNamespace(
            payload={"guest_proxy_url": proxies[0]},
            status="completed",
            started_at="2026-09-16T12:00:00Z",
            completed_at="2026-09-16T12:00:01Z",
        ),
        # Task that has no guest_proxy_url (defaulted to direct)
        SimpleNamespace(
            payload={"guest_proxy_url": None},
            status="completed",
            started_at="2026-09-16T12:00:00Z",
            completed_at="2026-09-16T12:00:06.43Z",
        ),
    ]

    audit = compile_route_audit(job, proxies=proxies, tasks=tasks)

    # Verification: Section 4 lists 464 pure proxy routes with no direct (Default) entry present
    assert DIRECT_ROUTE_KEY not in audit
    assert len(audit) == 464
    assert all(route != DIRECT_ROUTE_KEY for route in audit.keys())


def test_route_audit_excludes_direct_by_default_when_flag_absent():
    job = SimpleNamespace(
        metadata={},
        job_id="job-test-flag-absent",
    )
    proxies = ["http://proxy1:8080", "http://proxy2:8080"]
    tasks = [
        SimpleNamespace(
            payload={"params": {"guest_proxy_url": None}},
            status="failed",
            error="Connection timeout",
            started_at="2026-09-16T12:00:00Z",
            completed_at="2026-09-16T12:00:06.43Z",
        ),
    ]

    audit = compile_route_audit(job, proxies=proxies, tasks=tasks)

    assert DIRECT_ROUTE_KEY not in audit
    assert len(audit) == 2


def test_route_audit_includes_direct_when_include_direct_connection_is_true():
    job = SimpleNamespace(
        metadata={"include_direct_connection": True},
        job_id="job-test-include-direct",
    )
    proxies = ["http://proxy1:8080"]
    tasks = [
        SimpleNamespace(
            payload={"guest_proxy_url": None},
            status="completed",
            started_at="2026-09-16T12:00:00Z",
            completed_at="2026-09-16T12:00:02Z",
        ),
    ]

    audit = compile_route_audit(job, proxies=proxies, tasks=tasks)

    assert DIRECT_ROUTE_KEY in audit
    assert len(audit) == 2
    assert audit[DIRECT_ROUTE_KEY]["total_attempts"] == 1
    assert audit[DIRECT_ROUTE_KEY]["avg_latency_sec"] == 2.0


def test_route_audit_compiler_class_and_alias():
    compiler = RouteAuditCompiler()
    job = {"metadata": {"include_direct_connection": False}}
    proxies = ["http://p1:8080"]

    res1 = compiler.compile(job, proxies=proxies)
    res2 = audit_routes(job, proxies=proxies)

    assert DIRECT_ROUTE_KEY not in res1
    assert DIRECT_ROUTE_KEY not in res2
    assert "http://p1:8080" in res1


def test_throughput_diagnostics_detects_worker_deficit_and_idle_routes():
    from ultima_scraper_backend.job_system.diagnostics import (
        ThroughputDiagnosticsCompiler,
    )

    job = SimpleNamespace(
        metadata={
            "proxy_capacity": 464,
            "target_concurrency": 4,
            "duration_seconds": 100.0,
        },
        task_stats={"completed": 5000, "failed": 0, "total": 5000},
        job_id="job-mps-464",
    )

    # 8 workers * 4 concurrency = 32 slots demand vs 464 proxy capacity
    compiler = ThroughputDiagnosticsCompiler()
    diag = compiler.compile(job, worker_pool_size=8, default_median_latency=1.5)

    assert diag["proxy_capacity"] == 464
    assert diag["worker_pool_size"] == 8
    assert diag["worker_concurrency_demand"] == 32
    assert diag["theoretical_proxy_max_items_per_sec"] == round(464 / 1.5, 1)  # ~309.3
    assert diag["theoretical_worker_max_items_per_sec"] == round(32 / 1.5, 1)  # ~21.3
    assert diag["governing_bottleneck"] == "worker_concurrency"
    assert diag["idle_proxy_routes"] > 300
    assert diag["recommended_worker_concurrency"] == 58  # ceil(464 / 8)

    # Verify loss factor identifying the deficit
    deficit_factors = [f for f in diag["loss_factors"] if f["factor"] == "Worker Concurrency Deficit"]
    assert len(deficit_factors) == 1
    assert deficit_factors[0]["severity"] == "critical"
    assert "demand (32 slots: 8 workers × 4) is below proxy fleet capacity (464 routes)" in deficit_factors[0]["description"]


def test_throughput_diagnostics_calculates_tail_latency_drag_and_errors():
    from ultima_scraper_backend.job_system.diagnostics import compile_throughput_diagnostics

    job = {
        "metadata": {"proxy_capacity": 100, "duration_seconds": 200.0},
        "task_stats": {"completed": 4000, "failed": 10, "total": 4010},
    }

    # Tasks with a long tail and some 429 errors
    tasks = []
    # 90 tasks fast (~1.0s)
    for i in range(90):
        tasks.append(
            SimpleNamespace(
                status="completed",
                started_at="2026-09-16T12:00:00Z",
                completed_at="2026-09-16T12:00:01Z",
            )
        )
    # 10 tasks slow (~6.0s)
    for i in range(10):
        tasks.append(
            SimpleNamespace(
                status="completed",
                started_at="2026-09-16T12:00:00Z",
                completed_at="2026-09-16T12:00:06Z",
            )
        )
    # 5 tasks with 429
    for i in range(5):
        tasks.append(
            SimpleNamespace(
                status="failed",
                error="HTTP 429 Too Many Requests",
                started_at="2026-09-16T12:00:00Z",
                completed_at="2026-09-16T12:00:02Z",
            )
        )

    diag = compile_throughput_diagnostics(job, tasks=tasks, worker_pool_size=10)

    assert diag["latency_percentiles"]["p50"] == 1.0
    assert diag["latency_percentiles"]["p95"] == 6.0
    assert diag["latency_spread_ratio"] == 6.0
    assert diag["tail_latency_drag_percent"] > 0

    factor_names = [f["factor"] for f in diag["loss_factors"]]
    assert "Tail Latency Drag" in factor_names
    assert "Upstream Rate Limiting (HTTP 429)" in factor_names
    rate_limit = next(
        factor
        for factor in diag["loss_factors"]
        if factor["factor"] == "Upstream Rate Limiting (HTTP 429)"
    )
    assert rate_limit["severity"] == "moderate"
    assert rate_limit["estimated_loss_items_per_sec"] == 0


def test_throughput_diagnostics_reports_error_incidence_without_invented_loss():
    from ultima_scraper_backend.job_system.diagnostics import (
        compile_throughput_diagnostics,
    )

    job = {
        "metadata": {"proxy_capacity": 1656, "duration_seconds": 136.8},
        "task_stats": {"completed": 12819, "failed": 71, "total": 12890},
    }
    tasks = [
        SimpleNamespace(status="failed", error="HTTP 429 Too Many Requests"),
        *[
            SimpleNamespace(status="failed", error="Connection timed out")
            for _ in range(68)
        ],
    ]

    diag = compile_throughput_diagnostics(job, tasks=tasks, worker_pool_size=8)
    factors = {factor["factor"]: factor for factor in diag["loss_factors"]}

    assert factors["Upstream Rate Limiting (HTTP 429)"]["severity"] == "low"
    assert factors["Upstream Rate Limiting (HTTP 429)"]["estimated_loss_items_per_sec"] == 0
    assert "0.01% observed incidence" in factors["Upstream Rate Limiting (HTTP 429)"]["description"]
    assert factors["Connection Timeouts"]["severity"] == "moderate"
    assert factors["Connection Timeouts"]["estimated_loss_items_per_sec"] == 0
    assert "0.53% observed incidence" in factors["Connection Timeouts"]["description"]


def test_throughput_diagnostics_prefers_complete_runtime_aggregate():
    from ultima_scraper_backend.job_system.diagnostics import (
        compile_throughput_diagnostics,
    )

    job = SimpleNamespace(
        metadata={
            "proxy_capacity": 100,
            "duration_seconds": 10.0,
            "runtime_telemetry": {
                "task_count": 100,
                "active_window_ms": 10_000,
                "mean_task_duration_ms": 2_000,
                "route_active_sum_ms": 100_000,
                "route_attempts": 200,
                "time_weighted_inflight": 20,
                "time_weighted_active_routes": 10,
                "mean_queue_wait_ms": 100,
                "mean_handler_ms": 1_600,
                "mean_writer_ms": 1_000,
                "steady_throughput": 10,
                "steady_mean_task_duration_ms": 2_000,
                "ready_nonempty_ratio": 1,
                "workers_seen": 10,
                "expected_workers": 10,
            },
        },
        task_stats={"completed": 100, "failed": 0, "total": 100},
        job_id="job-runtime-aggregate",
    )

    diag = compile_throughput_diagnostics(
        job, worker_pool_size=10, default_median_latency=0.5
    )

    assert diag["runtime_telemetry_complete"] is True
    # Capacity uses total route-active time per task (1.0s), not the
    # per-attempt mean (0.5s), so retries consume route capacity.
    assert diag["theoretical_proxy_max_items_per_sec"] == 100.0
    assert diag["active_window_throughput"] == 10.0
    assert diag["efficiency_percent"] == 20.0
    assert diag["active_concurrency"] == 20
    assert diag["active_routes"] == 10
    assert diag["proxy_utilization_percent"] == 10.0
    assert diag["steady_state_efficiency_percent"] == 20.0
    # Completion-time samples cannot isolate a sub-90% steady-state gap, so the
    # backend reports the gap without naming a bottleneck.
    assert diag["occupancy_gap_classification"] == "insufficient_data"
    assert diag["capacity_realization_bottleneck"] is None
    assert diag["dominant_service_phase"] == "Database Writer Wait"
    assert diag["loss_factors"][0]["factor"] == "Database Writer Wait"

    intermittent_job = SimpleNamespace(
        metadata={
            **job.metadata,
            "runtime_telemetry": {
                **job.metadata["runtime_telemetry"],
                "ready_nonempty_ratio": 0.605,
                "mean_claim_wait_ms": 9.58,
            },
        },
        task_stats={"completed": 100, "failed": 0, "total": 100},
        job_id="job-intermittent-ready-supply",
    )
    intermittent_diag = compile_throughput_diagnostics(
        intermittent_job,
        worker_pool_size=10,
        default_median_latency=0.5,
    )
    # Intermittent ready supply is classified client-side from runtime samples.
    assert intermittent_diag["occupancy_gap_classification"] == "insufficient_data"
    assert intermittent_diag["capacity_realization_observation"] == "insufficient_data"
    assert intermittent_diag["capacity_realization_bottleneck"] is None
    assert "cannot be isolated" in intermittent_diag["occupancy_gap_explanation"]
