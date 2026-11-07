"""Tests for job system optimizations.

Covers:
- global_session() context manager (global_db.py)
- _sync_job_status_sqlite (storage.py)
- CONTENT_TYPE_MAP constant (jobs.py)
- deque for _processed_message_ids (websocket_actions.py)
- SQL LIMIT/OFFSET pagination (jobs.py)
"""

from __future__ import annotations

import json
import signal
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlmodel import Session, create_engine
import legacy_redis_runtime as legacy

# ---------------------------------------------------------------------------
# 1) global_db.py tests (no heavy mocking needed)
# ---------------------------------------------------------------------------


def _decode_redis_value(value: Any) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


def _require_configured_global_postgres(gdb: Any, base_directory: Path) -> None:
    """These tests write rows, so they only run against an explicitly configured DB."""
    try:
        gdb.get_global_engine(base_directory=base_directory)
    except RuntimeError as exc:
        pytest.skip(f"requires a disposable PostgreSQL database: {exc}")


def _require_reachable_global_postgres(gdb: Any) -> None:
    try:
        with gdb.global_session() as session:
            session.exec(text("SELECT 1")).scalar()
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"requires reachable postgres database: {exc}")


class TestGlobalSession:
    """Test the global session helpers using an injected engine."""

    def _install_test_engine(self):
        import ultima_scraper_db_archive.global_db as gdb

        gdb._postgres_engine = create_engine("sqlite://")
        return gdb

    def test_global_session_yields_session(self) -> None:
        gdb = self._install_test_engine()
        try:
            with gdb.global_session() as session:
                assert isinstance(session, Session)
                result = session.exec(text("SELECT 1"))
                assert result.scalar() == 1
        finally:
            gdb._postgres_engine = None

    def test_global_session_closes_on_normal_exit(self) -> None:
        gdb = self._install_test_engine()
        try:
            with gdb.global_session():
                pass
            with gdb.global_session() as session:
                result = session.exec(text("SELECT 1"))
                assert result.scalar() == 1
        finally:
            gdb._postgres_engine = None

    def test_global_session_closes_on_exception(self) -> None:
        gdb = self._install_test_engine()
        try:
            with pytest.raises(ValueError, match="test error"):
                with gdb.global_session():
                    raise ValueError("test error")
            with gdb.global_session() as session:
                result = session.exec(text("SELECT 1"))
                assert result.scalar() == 1
        finally:
            gdb._postgres_engine = None

    def test_get_global_engine_requires_postgres_configuration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ultima_scraper_db_archive.global_db as gdb

        gdb._postgres_engine = None
        monkeypatch.setattr(gdb, "bootstrap_from_env", lambda: False)

        with pytest.raises(RuntimeError, match="PostgreSQL is not configured"):
            gdb.get_global_engine()

    def test_set_sqlite_fallback_enable_is_rejected(self) -> None:
        import ultima_scraper_db_archive.global_db as gdb

        with pytest.raises(RuntimeError, match="removed"):
            gdb.set_sqlite_fallback_allowed(True)

    def test_set_postgres_url_uses_bounded_pgbouncer_client_pool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ultima_scraper_db_archive.global_db as gdb
        from sqlalchemy.pool import NullPool

        captured: dict[str, object] = {}
        engine = create_engine("sqlite://")

        def fake_create_engine(url: str, **kwargs: object) -> object:
            captured.update(url=url, **kwargs)
            return engine

        monkeypatch.setattr(gdb, "create_engine", fake_create_engine)
        monkeypatch.setattr(gdb, "set_postgres_engine", lambda value: None)
        monkeypatch.delenv("ULTIMA_DATABASE_PROCESS_ROLE", raising=False)
        monkeypatch.setattr(
            gdb,
            "_global_pool_int",
            lambda key, default: {
                "ULTIMA_PGBOUNCER_GLOBAL_POOL_SIZE": 2,
                "ULTIMA_PGBOUNCER_GLOBAL_MAX_OVERFLOW": 0,
            }.get(key, default),
        )

        gdb.set_postgres_url("postgresql://user:password@pgbouncer:6432/ultima_archive")

        assert captured["poolclass"] is NullPool
        assert "pool_size" not in captured
        assert "max_overflow" not in captured
        assert captured["connect_args"] == {"prepare_threshold": None}

    def test_get_global_session_uses_active_engine(self) -> None:
        gdb = self._install_test_engine()
        try:
            session = gdb.get_global_session()
            try:
                assert isinstance(session, Session)
                result = session.exec(text("SELECT 1"))
                assert result.scalar() == 1
            finally:
                session.close()
        finally:
            gdb._postgres_engine = None


# ---------------------------------------------------------------------------
# 2) JobStorage tests (using fakeredis)
# ---------------------------------------------------------------------------


class FakeRedisManager:
    """Minimal shim matching the RedisManager interface for testing."""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def get(self, key: str) -> Any:
        return await self.client.get(key)

    async def set(self, key: str, value: Any, **kwargs: Any) -> Any:
        return await self.client.set(key, value, **kwargs)

    async def delete(self, key: str) -> Any:
        return await self.client.delete(key)

    async def zadd(self, key: str, mapping: Any) -> Any:
        return await self.client.zadd(key, mapping)

    async def zrem(self, key: str, *members: str) -> Any:
        return await self.client.zrem(key, *members)

    async def zrange(self, key: str, start: int, end: int) -> Any:
        return await self.client.zrange(key, start, end)

    async def lrange(self, key: str, start: int, end: int) -> Any:
        return await self.client.lrange(key, start, end)

    async def hget(self, key: str, field: str) -> Any:
        return await self.client.hget(key, field)


@pytest.fixture
def fake_redis():
    """Create a fakeredis async client."""
    import fakeredis.aioredis

    return fakeredis.aioredis.FakeRedis(decode_responses=False)


@pytest.fixture
def storage(fake_redis: Any, no_ledger_runs: None):
    """Create a JobStorage instance backed by fakeredis (no SQL ledger runs)."""
    from ultima_scraper_backend.job_system.storage import JobStorage

    manager = FakeRedisManager(fake_redis)
    return JobStorage(manager)


@pytest.mark.asyncio
async def test_runtime_telemetry_aggregates_full_job_time_integrals(storage: Any):
    job_id = "job-runtime-telemetry"
    await storage._client().hset(
        storage.JOB_STATE_KEY.format(job_id=job_id), mapping={"ready_tasks": 50}
    )

    await storage.record_task_runtime_telemetry(
        job_id,
        started_ms=1_000,
        finished_ms=3_000,
        queue_wait_ms=500,
        setup_ms=100,
        handler_ms=1_500,
        writer_ms=400,
        post_ms=200,
        release_ms=200,
        route_active_ms=1_000,
        route_attempts=1,
        success=True,
        completed_count=20,
        total_tasks=100,
        claim_wait_ms=4,
        worker_id="worker-1",
        expected_workers=2,
        effective_worker_concurrency=10,
        writer_admission_ms=10,
        writer_queue_ms=100,
        writer_execution_ms=200,
        writer_commit_ms=50,
        writer_overhead_ms=25,
        writer_delivery_ms=15,
        writer_timed_submits=1,
        writer_timing_coverage=1,
        writer_connection_checkout_ms=2,
        writer_receipt_lookup_ms=4,
        writer_receipt_finalize_ms=6,
        writer_payload_ms=8,
        writer_user_row_ms=10,
        writer_alias_ms=12,
        writer_authority_ms=14,
        writer_authority_rows_examined=2,
        writer_authority_rows_skipped=1,
        writer_authority_rows_upserted=1,
        writer_profile_ms=16,
        writer_social_ms=18,
        writer_flush_ms=20,
        writer_queue_commands_sum=300,
        writer_queue_commands_max=300,
        writer_queue_bytes_sum=1_000,
        writer_queue_bytes_max=1_000,
        writer_active_lanes_sum=6,
        writer_active_lanes_max=6,
        writer_batch_commands_sum=50,
        writer_configured_concurrency=8,
        writer_configured_batch_size=100,
        writer_queue_max_commands=800,
        writer_queue_max_bytes=512_000,
        writer_refill_min_commands=50,
        handler_guest_init_ms=100,
        handler_guest_init_count=1,
        handler_initial_lookup_ms=600,
        handler_initial_lookup_count=1,
        handler_refresh_api_ms=200,
        handler_refresh_api_count=1,
        handler_fallback_retry_ms=0,
        handler_fallback_retry_count=0,
        handler_serialization_ms=20,
        handler_serialization_count=1,
        writer_admission_serialization_ms=10,
        writer_admission_capacity_wait_ms=500,
        writer_admission_redis_ms=20,
        writer_admission_overhead_detail_ms=5,
        writer_batch_fill_ratio_sum=0.5,
        writer_lane_idle_ms=30,
        writer_lane_predecessor_wait_ms=40,
        writer_refill_wait_ms=50,
        writer_window_commands=800,
        writer_refill_min_commands_per_lane=75,
        writer_result_publication_ms=30,
        writer_result_observation_ms=40,
        writer_result_delivery_residual_ms=5,
        writer_result_delivery_split_count=1,
        writer_batch_peer_work_ms=80,
        writer_operation_stats_json='{"upsert_user":{"count":1,"batch_commands_sum":50,"batch_wall_ms_sum":100}}',
        writer_domain_stats_json='{"user":{"count":1,"batch_commands_sum":50,"batch_wall_ms_sum":100}}',
        writer_split_missing_reasons_json='{"result_cache_miss":1}',
        writer_result_cache_hits=9,
        writer_receipt_fallbacks=1,
    )

    await storage._client().hset(
        storage.JOB_RUNTIME_TELEMETRY_KEY.format(job_id=job_id),
        mapping={
            "ready_queue_recovery_count": 1,
            "ready_queue_recovered_tasks": 76,
        },
    )
    await storage.record_task_runtime_telemetry(
        job_id,
        started_ms=2_000,
        finished_ms=4_000,
        queue_wait_ms=1_500,
        setup_ms=300,
        handler_ms=1_400,
        writer_ms=200,
        post_ms=200,
        release_ms=100,
        route_active_ms=500,
        route_attempts=2,
        success=False,
        completed_count=80,
        total_tasks=100,
        claim_wait_ms=6,
        worker_id="worker-2",
        expected_workers=2,
        effective_worker_concurrency=10,
        writer_admission_ms=20,
        writer_queue_ms=300,
        writer_execution_ms=400,
        writer_commit_ms=150,
        writer_overhead_ms=75,
        writer_delivery_ms=25,
        writer_timed_submits=1,
        writer_timing_coverage=1,
        writer_connection_checkout_ms=4,
        writer_receipt_lookup_ms=8,
        writer_receipt_finalize_ms=12,
        writer_payload_ms=16,
        writer_user_row_ms=20,
        writer_alias_ms=24,
        writer_authority_ms=28,
        writer_authority_rows_examined=4,
        writer_authority_rows_skipped=3,
        writer_authority_rows_upserted=1,
        writer_profile_ms=32,
        writer_social_ms=36,
        writer_flush_ms=40,
        writer_queue_commands_sum=500,
        writer_queue_commands_max=500,
        writer_queue_bytes_sum=2_000,
        writer_queue_bytes_max=2_000,
        writer_active_lanes_sum=8,
        writer_active_lanes_max=8,
        writer_batch_commands_sum=100,
        writer_configured_concurrency=8,
        writer_configured_batch_size=100,
        writer_queue_max_commands=800,
        writer_queue_max_bytes=512_000,
        writer_refill_min_commands=50,
        handler_guest_init_ms=300,
        handler_guest_init_count=2,
        handler_initial_lookup_ms=1_000,
        handler_initial_lookup_count=2,
        handler_refresh_api_ms=400,
        handler_refresh_api_count=1,
        handler_fallback_retry_ms=100,
        handler_fallback_retry_count=1,
        handler_serialization_ms=40,
        handler_serialization_count=1,
        writer_admission_serialization_ms=20,
        writer_admission_capacity_wait_ms=700,
        writer_admission_redis_ms=40,
        writer_admission_overhead_detail_ms=15,
        writer_batch_fill_ratio_sum=0.75,
        writer_lane_idle_ms=50,
        writer_lane_predecessor_wait_ms=60,
        writer_refill_wait_ms=70,
        writer_window_commands=800,
        writer_refill_min_commands_per_lane=75,
        writer_result_publication_ms=50,
        writer_result_observation_ms=60,
        writer_result_delivery_residual_ms=15,
        writer_result_delivery_split_count=1,
        writer_batch_peer_work_ms=120,
        writer_operation_stats_json='{"upsert_user":{"count":1,"batch_commands_sum":100,"batch_wall_ms_sum":200}}',
        writer_domain_stats_json='{"user":{"count":1,"batch_commands_sum":100,"batch_wall_ms_sum":200}}',
        writer_split_missing_reasons_json='{"result_cache_miss":2}',
        writer_result_cache_hits=8,
        writer_receipt_fallbacks=2,
    )

    telemetry = await storage.get_job_runtime_telemetry(job_id)

    assert telemetry is not None
    assert telemetry["scope"] == "full_job_aggregate"
    assert telemetry["task_count"] == 2
    assert telemetry["succeeded_tasks"] == 1
    assert telemetry["failed_tasks"] == 1
    assert telemetry["active_window_ms"] == 3_000
    assert telemetry["mean_task_duration_ms"] == 2_000
    assert telemetry["mean_queue_wait_ms"] == 1_000
    assert telemetry["mean_handler_exclusive_ms"] == 1_150
    assert telemetry["mean_writer_ms"] == 300
    assert telemetry["time_weighted_inflight"] == pytest.approx(4 / 3, abs=0.001)
    assert telemetry["route_attempts"] == 3
    assert telemetry["time_weighted_active_routes"] == 0.5
    assert telemetry["mean_claim_wait_ms"] == 5
    assert telemetry["mean_writer_admission_ms"] == 15
    assert telemetry["mean_writer_queue_ms"] == 200
    assert telemetry["mean_writer_execution_ms"] == 300
    assert telemetry["mean_writer_commit_ms"] == 100
    assert telemetry["mean_writer_overhead_ms"] == 50
    assert telemetry["mean_writer_delivery_ms"] == 20
    assert telemetry["writer_timing_coverage_ratio"] == 1
    assert telemetry["version"] == 14
    assert telemetry["mean_handler_guest_init_ms"] == 200
    assert telemetry["handler_guest_init_count"] == 3
    assert telemetry["mean_handler_initial_lookup_ms"] == 800
    assert telemetry["handler_initial_lookup_count"] == 3
    assert telemetry["mean_handler_refresh_api_ms"] == 300
    assert telemetry["handler_refresh_api_count"] == 2
    assert telemetry["mean_handler_fallback_retry_ms"] == 50
    assert telemetry["handler_fallback_retry_count"] == 1
    assert telemetry["mean_handler_serialization_ms"] == 30
    assert telemetry["handler_serialization_count"] == 2
    assert telemetry["mean_writer_admission_serialization_ms"] == 15
    assert telemetry["mean_writer_admission_capacity_wait_ms"] == 600
    assert telemetry["mean_writer_admission_redis_ms"] == 30
    assert telemetry["mean_writer_admission_overhead_detail_ms"] == 10
    assert telemetry["mean_writer_batch_fill_ratio"] == 0.625
    assert telemetry["mean_writer_lane_idle_ms"] == 40
    assert telemetry["mean_writer_lane_predecessor_wait_ms"] == 50
    assert telemetry["mean_writer_refill_wait_ms"] == 60
    assert telemetry["writer_window_commands"] == 800
    assert telemetry["writer_refill_min_commands_per_lane"] == 75
    assert telemetry["mean_writer_result_publication_ms"] == 40
    assert telemetry["mean_writer_result_observation_ms"] == 50
    assert telemetry["mean_writer_result_delivery_residual_ms"] == 10
    assert telemetry["writer_result_delivery_split_coverage_ratio"] == 1
    assert telemetry["mean_writer_batch_peer_work_ms"] == 100
    assert telemetry["writer_result_cache_hits"] == 17
    assert telemetry["writer_receipt_fallbacks"] == 3
    assert telemetry["writer_result_cache_hit_ratio"] == 0.85
    assert telemetry["writer_split_missing_reasons"] == {"result_cache_miss": 3}
    assert telemetry["writer_operation_stats"]["upsert_user"] == {
        "count": 2,
        "mean_batch_commands": 75,
        "mean_batch_wall_ms": 150,
    }
    assert telemetry["writer_domain_stats"]["user"] == {
        "count": 2,
        "mean_batch_commands": 75,
        "mean_batch_wall_ms": 150,
    }
    assert telemetry["mean_writer_connection_checkout_ms"] == 3
    assert telemetry["mean_writer_receipt_lookup_ms"] == 6
    assert telemetry["mean_writer_receipt_finalize_ms"] == 9
    assert telemetry["mean_writer_payload_ms"] == 12
    assert telemetry["mean_writer_user_row_ms"] == 15
    assert telemetry["mean_writer_alias_ms"] == 18
    assert telemetry["mean_writer_authority_ms"] == 21
    assert telemetry["writer_authority_rows_examined"] == 6
    assert telemetry["writer_authority_rows_skipped"] == 4
    assert telemetry["writer_authority_rows_upserted"] == 2
    assert telemetry["mean_writer_profile_ms"] == 24
    assert telemetry["mean_writer_social_ms"] == 27
    assert telemetry["mean_writer_flush_ms"] == 30
    assert telemetry["mean_writer_queue_commands_at_start"] == 400
    assert telemetry["max_writer_queue_commands_at_start"] == 500
    assert telemetry["mean_writer_queue_bytes_at_start"] == 1_500
    assert telemetry["max_writer_queue_bytes_at_start"] == 2_000
    assert telemetry["mean_writer_active_lanes"] == 7
    assert telemetry["max_writer_active_lanes"] == 8
    assert telemetry["mean_writer_batch_commands"] == 75
    assert telemetry["writer_configured_concurrency"] == 8
    assert telemetry["writer_configured_batch_size"] == 100
    assert telemetry["writer_queue_max_commands"] == 800
    assert telemetry["writer_queue_max_bytes"] == 512_000
    assert telemetry["writer_refill_min_commands"] == 50
    assert telemetry["ready_queue_recovery_count"] == 1
    assert telemetry["ready_queue_recovered_tasks"] == 76
    assert telemetry["max_worker_completion_gap_ms"] == 0
    assert telemetry["steady_task_count"] == 2
    assert telemetry["steady_window_ms"] == 1_000
    assert telemetry["steady_throughput"] == 60
    assert telemetry["steady_mean_task_duration_ms"] == 2_000
    assert telemetry["ready_nonempty_ratio"] == 1
    assert telemetry["mean_ready_depth"] == 50
    assert telemetry["workers_seen"] == 2
    assert telemetry["expected_workers"] == 2
    assert telemetry["time_weighted_participating_workers"] == pytest.approx(
        4 / 3, abs=0.001
    )
    assert telemetry["time_weighted_effective_worker_capacity"] == pytest.approx(
        40 / 3, abs=0.001
    )


@pytest.mark.asyncio
async def test_runtime_telemetry_tracks_largest_per_worker_completion_gap(
    storage: Any,
):
    job_id = "job-runtime-worker-gap"
    common = {
        "queue_wait_ms": 0,
        "setup_ms": 0,
        "handler_ms": 100,
        "writer_ms": 0,
        "post_ms": 0,
        "release_ms": 0,
        "route_active_ms": 0,
        "route_attempts": 0,
        "success": True,
        "worker_id": "worker-gap",
    }
    await storage.record_task_runtime_telemetry(
        job_id,
        started_ms=1_000,
        finished_ms=2_000,
        **common,
    )
    await storage.record_task_runtime_telemetry(
        job_id,
        started_ms=99_000,
        finished_ms=100_000,
        **common,
    )

    telemetry = await storage.get_job_runtime_telemetry(job_id)

    assert telemetry is not None
    assert telemetry["max_worker_completion_gap_ms"] == 98_000


@pytest.mark.asyncio
async def test_timed_database_writes_leaves_receipt_without_timing_unmeasured() -> None:
    from ultima_scraper_backend.database.write_queue import WRITE_TIMING_KEY
    from ultima_scraper_backend.workers.worker_pool import _TimedDatabaseWrites

    delegate = SimpleNamespace(
        enqueue=AsyncMock(return_value=("write-1", {})),
        wait_for_result=AsyncMock(
            return_value={
                "synced": True,
                WRITE_TIMING_KEY: {
                    "writer_timing_unavailable": True,
                    "writer_result_source": "receipt",
                    "writer_result_split_missing_reason": "result_cache_miss",
                },
            }
        ),
    )
    timed = _TimedDatabaseWrites(delegate)

    assert await timed.submit("upsert_user", {"id": 1}) == {"synced": True}
    assert timed.timed_submit_count == 1
    assert timed.timing_coverage_count == 0
    assert timed.receipt_fallbacks == 1
    assert timed.result_cache_hits == 0
    assert timed.result_split_missing_reasons == {"receipt_timing_unavailable": 1}
    assert timed.delivery_ms == timed.execution_ms == timed.commit_ms == 0
    assert timed.operation_stats == {}


@pytest.mark.asyncio
async def test_timed_database_writes_splits_complete_writer_timing() -> None:
    from ultima_scraper_backend.database.write_queue import WRITE_TIMING_KEY
    from ultima_scraper_backend.workers.worker_pool import _TimedDatabaseWrites

    now_ms = time.time() * 1000.0
    delegate = SimpleNamespace(
        enqueue=AsyncMock(
            return_value=(
                "write-1",
                {
                    "producer_serialization_ms": 1.0,
                    "producer_capacity_wait_ms": 2.0,
                    "producer_redis_enqueue_ms": 3.0,
                    "producer_admission_overhead_ms": 4.0,
                },
            )
        ),
        wait_for_result=AsyncMock(
            return_value={
                "synced": True,
                WRITE_TIMING_KEY: {
                    "writer_started_at_ms": now_ms - 20.0,
                    "writer_finished_at_ms": now_ms - 8.0,
                    "writer_result_publish_started_at_ms": 1_000.0,
                    "writer_result_available_at_ms": 1_003.0,
                    "writer_result_observed_at_ms": 1_008.0,
                    "writer_result_source": "cache",
                    "writer_total_ms": 12.0,
                    "writer_batch_peer_work_ms": 5.0,
                    "writer_batch_overhead_ms": 2.0,
                    "execution_ms": 7.0,
                    "execution_measured": True,
                    "commit_ms": 3.0,
                    "commit_measured": True,
                    "connection_checkout_ms": 1.0,
                    "receipt_lookup_ms": 2.0,
                    "receipt_finalize_ms": 3.0,
                    "payload_ms": 4.0,
                    "user_row_ms": 5.0,
                    "alias_ms": 6.0,
                    "authority_ms": 7.0,
                    "authority_rows_examined": 4.0,
                    "authority_rows_skipped": 3.0,
                    "authority_rows_upserted": 1.0,
                    "profile_ms": 8.0,
                    "social_ms": 9.0,
                    "flush_ms": 10.0,
                    "writer_queue_commands_at_start": 600,
                    "writer_queue_bytes_at_start": 2048,
                    "writer_active_lanes": 7,
                    "writer_batch_commands": 80,
                    "writer_batch_fill_ratio": 0.8,
                    "writer_operation": "upsert_user",
                    "writer_lane_domain": "user",
                    "writer_lane_idle_ms": 11,
                    "writer_lane_predecessor_wait_ms": 12,
                    "writer_refill_wait_ms": 13,
                    "writer_configured_concurrency": 8,
                    "writer_configured_batch_size": 100,
                    "writer_window_commands": 800,
                    "writer_queue_max_commands": 800,
                    "writer_queue_max_bytes": 4096,
                    "writer_refill_min_commands": 50,
                    "writer_refill_min_commands_per_lane": 75,
                },
            }
        ),
    )
    timed = _TimedDatabaseWrites(delegate)

    result = await timed.submit("upsert_user", {"id": 1}, timeout_seconds=5.0)

    assert result == {"synced": True}
    assert timed.timed_submit_count == 1
    assert timed.timing_coverage_count == 1
    assert timed.admission_ms >= 0.0
    assert timed.admission_serialization_ms == 1
    assert timed.admission_capacity_wait_ms == 2
    assert timed.admission_redis_ms == 3
    assert timed.admission_overhead_ms == 4
    assert timed.queue_ms >= 0.0
    assert timed.execution_ms == pytest.approx(7.0)
    assert timed.commit_ms == pytest.approx(3.0)
    assert timed.writer_overhead_ms == pytest.approx(2.0)
    assert timed.batch_peer_work_ms == pytest.approx(5.0)
    assert timed.delivery_ms == pytest.approx(8.0)
    assert timed.result_publication_ms == pytest.approx(3.0)
    assert timed.result_observation_ms == pytest.approx(5.0)
    assert timed.result_delivery_residual_ms == 0
    assert timed.result_delivery_split_count == 1
    assert timed.result_cache_hits == 1
    assert timed.receipt_fallbacks == 0
    assert timed.operation_stats["upsert_user"]["count"] == 1
    assert timed.domain_stats["user"]["batch_commands_sum"] == 80
    assert timed.connection_checkout_ms == 1
    assert timed.receipt_lookup_ms == 2
    assert timed.receipt_finalize_ms == 3
    assert timed.payload_ms == 4
    assert timed.user_row_ms == 5
    assert timed.alias_ms == 6
    assert timed.authority_ms == 7
    assert timed.authority_rows_examined == 4
    assert timed.authority_rows_skipped == 3
    assert timed.authority_rows_upserted == 1
    assert timed.profile_ms == 8
    assert timed.social_ms == 9
    assert timed.flush_ms == 10
    assert timed.queue_commands_sum == 600
    assert timed.queue_commands_max == 600
    assert timed.queue_bytes_sum == 2048
    assert timed.queue_bytes_max == 2048
    assert timed.active_lanes_sum == 7
    assert timed.active_lanes_max == 7
    assert timed.batch_commands_sum == 80
    assert timed.batch_fill_ratio_sum == pytest.approx(0.8)
    assert timed.lane_idle_ms == 11
    assert timed.lane_predecessor_wait_ms == 12
    assert timed.refill_wait_ms == 13
    assert timed.configured_concurrency == 8
    assert timed.configured_batch_size == 100
    assert timed.window_commands == 800
    assert timed.queue_max_commands == 800
    assert timed.queue_max_bytes == 4096
    assert timed.refill_min_commands == 50
    assert timed.refill_min_commands_per_lane == 75
    assert delegate.enqueue.await_args.kwargs["_include_timing"] is True
    delegate.wait_for_result.assert_awaited_once()
    assert delegate.wait_for_result.await_args.args == ("write-1",)
    assert delegate.wait_for_result.await_args.kwargs["include_timing"] is True
    assert delegate.wait_for_result.await_args.kwargs[
        "timeout_seconds"
    ] == pytest.approx(5.0, abs=0.05)


@pytest.mark.asyncio
async def test_persist_tasks_writes_bounded_batches(
    storage: Any, fake_redis: Any
) -> None:
    from ultima_scraper_backend.job_system.models import Task, TaskType

    tasks = [
        Task(
            task_id=f"task-batch-{index}",
            task_type=TaskType.SCRAPE,
            user_id=index,
            payload=None,
            site_name="OnlyFans",
        )
        for index in range(5)
    ]

    await storage.persist_tasks("job-batched", tasks, batch_size=2)

    assert await fake_redis.zcard(
        storage.TASK_INDEX_KEY.format(job_id="job-batched")
    ) == len(tasks)
    assert await legacy.list_tasks_for_job(storage, "job-batched") == [
        task.task_id for task in tasks
    ]
    for task in tasks:
        restored = await storage.fetch_task("job-batched", task.task_id)
        assert restored is not None
        assert restored.job_id == "job-batched"


@pytest.mark.asyncio
async def test_reserve_dedup_many_is_restart_idempotent(storage: Any) -> None:
    from ultima_scraper_backend.job_system.models import Task, TaskType

    original = Task(
        task_id="task-deterministic",
        task_type=TaskType.SCRAPE,
        user_id=123,
        payload=None,
        site_name="OnlyFans",
    )
    collision = Task(
        task_id="task-other-job",
        task_type=TaskType.SCRAPE,
        user_id=123,
        payload=None,
        site_name="OnlyFans",
    )

    assert await storage.reserve_dedup_many([original]) == [original.task_id]
    assert await storage.reserve_dedup_many([original]) == [original.task_id]
    assert await storage.reserve_dedup_many([collision]) == []


@pytest.mark.asyncio
async def test_task_run_persists_canonical_worker_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.job_system.models import (
        Job,
        Task,
        TaskRegistry,
        TaskResult,
        TaskType,
    )

    async def handler(_task: Task, _context: object) -> TaskResult:
        return TaskResult(success=True, message="done")

    monkeypatch.setitem(TaskRegistry._handlers, TaskType.API_COMMAND, handler)
    task = Task(
        task_id="task-owned",
        task_type=TaskType.API_COMMAND,
        user_id=1,
        payload=None,
        site_name="OnlyFans",
    )
    job = Job(name="Owned task", created_by="tests", tasks=[task])
    task_storage = SimpleNamespace(persist_task=AsyncMock())

    await task.run(
        job=job,
        storage=task_storage,
        context={"worker_id": "worker-canonical-7"},
    )

    assert task.worker_id == "worker-canonical-7"
    assert Task.from_dict(task.to_dict()).worker_id == "worker-canonical-7"
    assert task_storage.persist_task.await_count == 2


class TestAddTaskToJobLua:
    """Task publication requires Redis's atomic ownership checks."""

    @pytest.mark.asyncio
    async def test_add_task_to_job_fails_before_writing_when_eval_is_unavailable(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """A missing EVAL command must not bypass the edit ownership guard."""
        from redis.exceptions import ResponseError

        from ultima_scraper_backend.job_system.models import Task, TaskType

        job_id = "job-lua-1"
        config_key = storage.JOB_CONFIG_KEY.format(job_id=job_id)
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        task_key = storage.TASK_KEY.format(job_id=job_id, task_id="task-c")

        initial_config = {
            "job_id": job_id,
            "job_type": "scrape",
            "task_ids": ["task-a"],
        }
        await fake_redis.set(config_key, json.dumps(initial_config))
        await fake_redis.hset(state_key, mapping={"total_tasks": "1"})

        task = Task(
            task_id="task-c",
            task_type=TaskType.API_COMMAND,
            user_id=1,
            payload=None,
            site_name="OnlyFans",
        )

        with (
            patch.object(
                fake_redis,
                "eval",
                AsyncMock(side_effect=ResponseError("unknown command 'eval'")),
            ),
            patch.object(storage, "fetch_job_with_tasks", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ResponseError, match="unknown command"):
                await legacy.add_task_to_job(storage, job_id, task)

        assert await fake_redis.get(task_key) is None
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "total_tasks")) == "1"
        )

    @pytest.mark.asyncio
    async def test_add_task_to_job_raises_for_missing_job(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """Missing jobs should still raise ValueError."""
        from ultima_scraper_backend.job_system.models import Task, TaskType

        task = Task(
            task_id="task-x",
            task_type=TaskType.API_COMMAND,
            user_id=1,
            payload=None,
            site_name="OnlyFans",
        )

        with pytest.raises(ValueError, match="not found"):
            await legacy.add_task_to_job(storage, "nonexistent", task)

    @pytest.mark.asyncio
    async def test_add_task_to_job_persists_task_payload(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """Persisted task blobs should include the new task ID."""
        from ultima_scraper_backend.job_system.models import Task, TaskType

        job_id = "job-lua-2"
        config_key = storage.JOB_CONFIG_KEY.format(job_id=job_id)
        task_key = storage.TASK_KEY.format(job_id=job_id, task_id="task-first")

        initial_config = {"job_id": job_id, "job_type": "scrape"}
        await fake_redis.set(config_key, json.dumps(initial_config))
        task = Task(
            task_id="task-first",
            task_type=TaskType.API_COMMAND,
            user_id=1,
            payload=None,
            site_name="OnlyFans",
        )

        with patch.object(
            storage, "fetch_job_with_tasks", AsyncMock(return_value=None)
        ):
            await legacy.add_task_to_job(storage, job_id, task)

        raw_task = await fake_redis.get(task_key)
        assert raw_task is not None
        payload = json.loads(
            raw_task.decode() if isinstance(raw_task, bytes) else raw_task
        )
        assert payload["task_id"] == "task-first"

    @pytest.mark.asyncio
    async def test_fetch_task_page_empty_index_exhausts_tier(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """Stale state.total_tasks with an empty task index must not page forever.

        Legacy partial-cleanups can leave the state hash claiming ``total_tasks``
        while the task index zset is empty.  The previous implementation kept
        returning ``has_more=True, next_cursor="0"``, which prevented the
        ``get_job_tasks`` route from falling through to the central DB / event
        log fallbacks.
        """
        job_id = "job-orphan"
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        await fake_redis.hset(
            state_key,
            mapping={"status": "completed", "total_tasks": "8350"},
        )
        # Note: no task index zset, no task hashes.

        page = await storage.fetch_task_page(job_id, cursor="0", limit=100)

        assert page.tasks == []
        assert page.has_more is False
        assert page.next_cursor is None


class TestWorkerPoolRuntime:
    """Regression coverage for worker-pool job claiming and auth loading."""

    @staticmethod
    def _make_worker_pool_config(
        *,
        size: int,
        max_claimed_jobs: int,
        scope: str = "backend-test",
        enabled: bool = True,
        sites: list[str] | None = None,
    ) -> SimpleNamespace:
        from ultima_scraper_backend.config import ExecutionMode

        return SimpleNamespace(
            settings=SimpleNamespace(
                worker_pool=SimpleNamespace(
                    enabled=enabled,
                    size=size,
                    max_claimed_jobs=max_claimed_jobs,
                    sites=sites or ["onlyfans"],
                ),
                backend=SimpleNamespace(execution_mode=ExecutionMode.DISTRIBUTED),
                redis=SimpleNamespace(enabled=True, host="127.0.0.1"),
                get_backend_id=lambda: scope,
            )
        )

    def test_worker_pool_start_starts_sql_service_before_workers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ultima_scraper_backend.workers.worker_pool as worker_pool_module
        from ultima_scraper_backend.config import ExecutionMode

        config = SimpleNamespace(
            settings=SimpleNamespace(
                worker_pool=SimpleNamespace(sites=["onlyfans"], max_claimed_jobs=5),
                backend=SimpleNamespace(execution_mode=ExecutionMode.DISTRIBUTED),
                redis=SimpleNamespace(enabled=True, host="127.0.0.1"),
                get_backend_id=lambda: "backend-test",
            )
        )
        monkeypatch.setattr(
            worker_pool_module.UltimaScraperCollectionConfig,
            "load_or_create_default_config",
            lambda: config,
        )

        call_order: list[str] = []
        pool = worker_pool_module.WorkerPool(
            num_workers=2,
            redis_url="redis://localhost:6379",
            backend_id="backend-test",
        )
        monkeypatch.setattr(
            pool,
            "_start_job_service",
            lambda startup_timeout=15.0: call_order.append("ledger"),
        )
        monkeypatch.setattr(pool, "_start_runtime_control_listener", lambda: None)
        monkeypatch.setattr(
            pool,
            "_spawn_worker",
            lambda index: call_order.append(f"worker:{index}"),
        )
        monkeypatch.setattr(worker_pool_module.time, "sleep", lambda _seconds: None)

        pool.start()

        assert call_order == ["ledger", "worker:0", "worker:1"]

    def test_worker_pool_settings_updated_scales_up_live(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ultima_scraper_backend.workers.worker_pool as worker_pool_module

        configs = [
            self._make_worker_pool_config(size=2, max_claimed_jobs=10),
            self._make_worker_pool_config(size=4, max_claimed_jobs=10),
        ]
        load_count = {"value": 0}

        def load_config() -> SimpleNamespace:
            idx = min(load_count["value"], len(configs) - 1)
            load_count["value"] += 1
            return configs[idx]

        monkeypatch.setattr(
            worker_pool_module.UltimaScraperCollectionConfig,
            "load_or_create_default_config",
            load_config,
        )

        pool = worker_pool_module.WorkerPool(
            num_workers=2,
            redis_url="redis://localhost:6379",
            backend_id="backend-test",
        )
        scale_calls: list[tuple[int, bool]] = []
        monkeypatch.setattr(
            pool,
            "scale_to",
            lambda target, graceful=True: (
                scale_calls.append((target, graceful)),
                setattr(pool, "num_workers", target),
            ),
        )

        pool.enqueue_runtime_control_event(
            {"type": "settings_updated", "settings_scope": "backend-test", "version": 1}
        )

        assert pool.process_runtime_control_events() == 1
        assert scale_calls == [(4, True)]
        assert pool.num_workers == 4

    def test_worker_pool_settings_updated_scales_down_gracefully(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ultima_scraper_backend.workers.worker_pool as worker_pool_module

        configs = [
            self._make_worker_pool_config(size=4, max_claimed_jobs=10),
            self._make_worker_pool_config(size=2, max_claimed_jobs=10),
        ]
        load_count = {"value": 0}

        def load_config() -> SimpleNamespace:
            idx = min(load_count["value"], len(configs) - 1)
            load_count["value"] += 1
            return configs[idx]

        monkeypatch.setattr(
            worker_pool_module.UltimaScraperCollectionConfig,
            "load_or_create_default_config",
            load_config,
        )

        pool = worker_pool_module.WorkerPool(
            num_workers=4,
            redis_url="redis://localhost:6379",
            backend_id="backend-test",
        )
        scale_calls: list[tuple[int, bool]] = []
        monkeypatch.setattr(
            pool,
            "scale_to",
            lambda target, graceful=True: (
                scale_calls.append((target, graceful)),
                setattr(pool, "num_workers", target),
            ),
        )

        pool.enqueue_runtime_control_event(
            {"type": "settings_updated", "settings_scope": "backend-test", "version": 1}
        )

        assert pool.process_runtime_control_events() == 1
        assert scale_calls == [(2, True)]
        assert pool.num_workers == 2

    @pytest.mark.parametrize("new_limit", [2, 0])
    def test_worker_pool_settings_updated_updates_max_claimed_jobs_live(
        self,
        monkeypatch: pytest.MonkeyPatch,
        new_limit: int,
    ) -> None:
        import ultima_scraper_backend.workers.worker_pool as worker_pool_module

        configs = [
            self._make_worker_pool_config(size=2, max_claimed_jobs=10),
            self._make_worker_pool_config(size=2, max_claimed_jobs=new_limit),
        ]
        load_count = {"value": 0}

        def load_config() -> SimpleNamespace:
            idx = min(load_count["value"], len(configs) - 1)
            load_count["value"] += 1
            return configs[idx]

        monkeypatch.setattr(
            worker_pool_module.UltimaScraperCollectionConfig,
            "load_or_create_default_config",
            load_config,
        )

        pool = worker_pool_module.WorkerPool(
            num_workers=2,
            redis_url="redis://localhost:6379",
            backend_id="backend-test",
        )
        scale_calls: list[tuple[int, bool]] = []
        monkeypatch.setattr(
            pool,
            "scale_to",
            lambda target, graceful=True: scale_calls.append((target, graceful)),
        )

        pool.enqueue_runtime_control_event(
            {"type": "settings_updated", "settings_scope": "backend-test", "version": 1}
        )

        assert pool.process_runtime_control_events() == 1
        assert pool._get_desired_max_claimed_jobs() == new_limit
        assert scale_calls == []

    def test_worker_pool_runtime_events_ignore_other_scope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ultima_scraper_backend.workers.worker_pool as worker_pool_module

        config = self._make_worker_pool_config(size=2, max_claimed_jobs=10)
        monkeypatch.setattr(
            worker_pool_module.UltimaScraperCollectionConfig,
            "load_or_create_default_config",
            lambda: config,
        )

        pool = worker_pool_module.WorkerPool(
            num_workers=2,
            redis_url="redis://localhost:6379",
            backend_id="backend-test",
        )
        scale_calls: list[tuple[int, bool]] = []
        monkeypatch.setattr(
            pool,
            "scale_to",
            lambda target, graceful=True: scale_calls.append((target, graceful)),
        )

        pool.enqueue_runtime_control_event(
            {
                "type": "settings_updated",
                "settings_scope": "other-backend",
                "version": 1,
            }
        )
        pool.enqueue_runtime_control_event(
            {
                "type": "worker_pool_scale",
                "settings_scope": "other-backend",
                "target_size": 5,
            }
        )

        assert pool.process_runtime_control_events() == 0
        assert scale_calls == []
        assert pool._get_desired_max_claimed_jobs() == 10


    def test_worker_pool_scale_to_zero_restart_uses_latest_claimed_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ultima_scraper_backend.workers.worker_pool as worker_pool_module

        config = self._make_worker_pool_config(size=1, max_claimed_jobs=10)
        monkeypatch.setattr(
            worker_pool_module.UltimaScraperCollectionConfig,
            "load_or_create_default_config",
            lambda: config,
        )

        pool = worker_pool_module.WorkerPool(
            num_workers=1,
            redis_url="redis://localhost:6379",
            backend_id="backend-test",
        )
        current_count = {"value": 1}
        start_calls: list[int] = []
        stop_calls: list[float] = []
        spawned: list[int] = []

        monkeypatch.setattr(pool, "get_worker_count", lambda: current_count["value"])
        monkeypatch.setattr(
            pool,
            "_start_job_service",
            lambda startup_timeout=15.0: start_calls.append(
                pool._get_desired_max_claimed_jobs()
            ),
        )
        monkeypatch.setattr(
            pool,
            "_stop_job_service",
            lambda timeout=10.0: stop_calls.append(timeout),
        )
        monkeypatch.setattr(
            pool,
            "_spawn_worker",
            lambda index: spawned.append(index),
        )

        pool.update_max_claimed_jobs(0)
        pool.scale_to(0)
        current_count["value"] = 0
        pool.scale_to(1)

        assert stop_calls
        assert start_calls == [0]
        assert spawned == [0]

    def test_worker_run_signal_uses_graceful_shutdown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ultima_scraper_backend.workers.worker_pool as worker_pool_module

        handlers: dict[int, Any] = {}
        shutdown_events: list[str] = []
        run_calls: list[str] = []
        shutdown_calls: list[str] = []

        class FakeShutdownEvent:
            def set(self) -> None:
                shutdown_events.append("set")

        class FakeWorker:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.running = True
                self._shutdown_event = FakeShutdownEvent()

            async def initialize(self) -> bool:
                handlers[signal.SIGTERM](signal.SIGTERM, None)
                return True

            async def run(self) -> None:
                run_calls.append("run")

            async def shutdown(self) -> None:
                shutdown_calls.append("shutdown")

        monkeypatch.setattr(
            worker_pool_module.signal,
            "signal",
            lambda signum, handler: handlers.__setitem__(signum, handler),
        )
        monkeypatch.setattr(
            worker_pool_module, "_configure_worker_logging", lambda *_: None
        )
        monkeypatch.setattr(worker_pool_module, "Worker", FakeWorker)

        worker_pool_module.WorkerPool._run_worker(
            worker_id="worker-test",
            redis_url="redis://localhost:6379",
            supported_sites=["onlyfans"],
            config=self._make_worker_pool_config(size=1, max_claimed_jobs=10),
            backend_id="backend-test",
            worker_index=0,
            worker_count=1,
        )

        assert run_calls == []
        assert shutdown_events == ["set"]
        assert shutdown_calls == ["shutdown"]


    @pytest.mark.asyncio
    async def test_remote_config_update_publishes_settings_updated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ultima_scraper_backend.models.backend as backend_module
        from ultima_scraper_backend.config import WorkerPool
        from ultima_scraper_backend.config_settings_sync import PersistedConfigSnapshot

        class FakeRedis:
            def __init__(self) -> None:
                self.published: list[tuple[str, dict[str, Any]]] = []
                # Runtime refill controls are synced through the raw client.
                self.client = SimpleNamespace(hset=AsyncMock())

            async def publish(self, channel: str, payload: str) -> int:
                self.published.append((channel, json.loads(payload)))
                return 1

        class FakeConfig:
            def __init__(self) -> None:
                self.settings = SimpleNamespace(
                    hostname="backend-host",
                    worker_pool=WorkerPool(
                        enabled=True,
                        size=5,
                        max_claimed_jobs=10,
                        sites=["onlyfans"],
                    ),
                    get_backend_id=lambda: "backend-test",
                )
                self._settings_version = 3

            def config_write_backend(self) -> str:
                return "backend-test"

        snapshot = PersistedConfigSnapshot(
            settings_id=7,
            settings_scope="backend-test",
            version=4,
            updated_at=datetime.now(timezone.utc).isoformat(),
            previous_value=None,
        )

        fake_config = FakeConfig()

        def persist_snapshot(config, *, expected_version):
            assert config is fake_config
            assert expected_version == 3
            assert config.settings.worker_pool.size == 7
            return snapshot

        fake_redis = FakeRedis()
        backend = backend_module.BackendInstance(
            instance_id="backend-runtime-id",
            redis=fake_redis,
            distributed_mode=False,
        )

        monkeypatch.setattr(
            backend,
            "_publish_config_to_redis",
            AsyncMock(),
        )
        monkeypatch.setattr(
            "ultima_scraper_backend.config.UltimaScraperCollectionConfig.load_or_create_default_config",
            lambda: fake_config,
        )
        monkeypatch.setattr(
            "ultima_scraper_backend.config_settings_sync.persist_config_snapshot",
            persist_snapshot,
        )

        await backend._handle_config_update_request(
            {
                "request_id": "req-1",
                "updates": {
                    "worker_pool": {
                        "enabled": True,
                        "size": 7,
                        "max_claimed_jobs": 2,
                        "sites": ["onlyfans"],
                    }
                },
            }
        )

        fake_redis.client.hset.assert_awaited_once()
        published_types = [payload["type"] for _, payload in fake_redis.published]
        assert "worker_pool_scale" in published_types
        assert "max_claimed_jobs_update" in published_types
        assert "settings_updated" in published_types
        assert "config_update_response" in published_types

        settings_updated = next(
            payload
            for _, payload in fake_redis.published
            if payload["type"] == "settings_updated"
        )
        assert settings_updated["settings_scope"] == "backend-test"
        assert settings_updated["version"] == snapshot.version
        assert fake_redis.published[-1][1]["success"] is True

    @pytest.mark.asyncio
    async def test_ensure_auth_loaded_for_task_uses_database_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ultima_scraper_backend.workers.worker_pool as worker_pool_module
        from ultima_scraper_backend.job_system.models import Task, TaskType

        config = worker_pool_module.UltimaScraperCollectionConfig()
        worker = worker_pool_module.Worker(
            worker_id="worker-test",
            redis_url="redis://localhost:6379",
            supported_sites=["onlyfans"],
            config=config,
            backend_id="backend-test",
            worker_index=0,
            worker_count=1,
        )

        class FakeAPI:
            def __init__(self) -> None:
                self.loaded_auths: set[int] = set()

            def find_auth(self, auth_id: int) -> object | None:
                if auth_id in self.loaded_auths:
                    return object()
                return None

        fake_api = FakeAPI()
        worker.apis = {"onlyfans": fake_api}
        worker.db_managers = {"onlyfans": SimpleNamespace(engine="engine-sentinel")}

        captured: dict[str, Any] = {}

        class FakeInitializer:
            def __init__(self, engine: object) -> None:
                captured["engine"] = engine

            async def create_cookie_auth(
                self,
                *,
                site: str,
                account_id: int,
                api_instance: FakeAPI,
            ) -> object:
                captured["site"] = site
                captured["account_id"] = account_id
                api_instance.loaded_auths.add(account_id)
                return object()

        monkeypatch.setattr(
            "ultima_scraper_backend.usapi_initializer.USAPIInitializer",
            FakeInitializer,
        )
        monkeypatch.setattr(
            "ultima_scraper_backend.usapi_initializer.is_auth_in_shard",
            lambda auth_id, worker_index, worker_count: True,
        )

        task = Task(
            user_id=2556617,
            task_type=TaskType.SCRAPE,
            site_name="OnlyFans",
            auth_id=10001,
            payload={},
        )

        await worker._ensure_auth_loaded_for_task(task, "onlyfans")

        assert captured["engine"] == "engine-sentinel"
        assert captured["site"] == "onlyfans"
        assert captured["account_id"] == 10001


class TestTaskStateCleanup:
    """Regression tests for terminal-job task-state cleanup."""

    @pytest.mark.asyncio
    async def test_clear_task_state_can_preserve_terminal_counters(
        self, storage: Any, fake_redis: Any
    ) -> None:
        job_id = "job-terminal-stats"
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        ready_key = storage.TASKS_READY_KEY.format(job_id=job_id)
        completed_key = storage.TASKS_COMPLETED_KEY.format(job_id=job_id)

        await fake_redis.hset(
            state_key,
            mapping={
                "total_tasks": "5",
                "ready_tasks": "1",
                "blocked_tasks": "0",
                "inflight_tasks": "0",
                "deferred_tasks": "0",
                "completed_tasks": "4",
                "failed_tasks": "0",
            },
        )
        await fake_redis.sadd(ready_key, "task-ready")
        await fake_redis.sadd(completed_key, "task-done")

        await storage.clear_task_state(job_id, reset_stats=False)

        assert await fake_redis.exists(ready_key) == 0
        assert await fake_redis.exists(completed_key) == 0
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "completed_tasks"))
            == "4"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "ready_tasks")) == "1"
        )

    @pytest.mark.asyncio
    async def test_mark_job_cancelled_clears_live_sets_but_preserves_terminal_stats(
        self, storage: Any, fake_redis: Any
    ) -> None:
        from ultima_scraper_backend.job_system.models import Job

        job = Job.create(
            name="Large Cancel",
            created_by="webui",
            tasks=[],
        )
        await storage.persist_job(job, persist_tasks=False)

        state_key = storage.JOB_STATE_KEY.format(job_id=job.job_id)
        ready_key = storage.TASKS_READY_KEY.format(job_id=job.job_id)
        inflight_key = storage.TASKS_INFLIGHT_KEY.format(job_id=job.job_id)
        completed_key = storage.TASKS_COMPLETED_KEY.format(job_id=job.job_id)

        await fake_redis.hset(
            state_key,
            mapping={
                "total_tasks": "700000",
                "ready_tasks": "699990",
                "blocked_tasks": "0",
                "inflight_tasks": "8",
                "deferred_tasks": "1",
                "completed_tasks": "1",
                "failed_tasks": "1",
            },
        )
        await fake_redis.sadd(ready_key, "task-ready")
        await fake_redis.sadd(inflight_key, "task-running")
        await fake_redis.sadd(completed_key, "task-done")

        cancelled_job = await storage.mark_job_cancelled(
            job.job_id,
            reason="cancelled by user",
        )

        assert cancelled_job is not None
        assert cancelled_job.state.value == "cancelled"
        assert await fake_redis.exists(ready_key) == 0
        assert await fake_redis.exists(inflight_key) == 0
        assert await fake_redis.exists(completed_key) == 0
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "status"))
            == "cancelled"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "total_tasks"))
            == "700000"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "ready_tasks")) == "0"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "inflight_tasks"))
            == "0"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "deferred_tasks"))
            == "0"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "completed_tasks"))
            == "1"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "failed_tasks")) == "1"
        )

    @pytest.mark.asyncio
    async def test_mark_job_failed_preserves_failed_state_and_terminal_stats(
        self, storage: Any, fake_redis: Any
    ) -> None:
        from ultima_scraper_backend.job_system.models import Job

        job = Job.create(
            name="Failed Batch",
            created_by="webui",
            tasks=[],
        )
        await storage.persist_job(job, persist_tasks=False)

        state_key = storage.JOB_STATE_KEY.format(job_id=job.job_id)
        ready_key = storage.TASKS_READY_KEY.format(job_id=job.job_id)
        inflight_key = storage.TASKS_INFLIGHT_KEY.format(job_id=job.job_id)
        completed_key = storage.TASKS_COMPLETED_KEY.format(job_id=job.job_id)
        await fake_redis.hset(
            state_key,
            mapping={
                "total_tasks": "295",
                "ready_tasks": "279",
                "blocked_tasks": "0",
                "inflight_tasks": "10",
                "deferred_tasks": "0",
                "completed_tasks": "5",
                "failed_tasks": "1",
            },
        )
        await fake_redis.sadd(ready_key, "task-ready")
        await fake_redis.sadd(inflight_key, "task-running")
        await fake_redis.sadd(
            completed_key,
            "task-complete-1",
            "task-complete-2",
            "task-complete-3",
            "task-complete-4",
            "task-complete-5",
        )

        failed_job = await storage.mark_job_failed(
            job.job_id,
            reason="proxy failure budget reached",
        )

        assert failed_job is not None
        assert failed_job.state.value == "failed"
        assert failed_job.metadata["failure_reason"] == "proxy failure budget reached"
        assert await fake_redis.exists(ready_key) == 0
        assert await fake_redis.exists(inflight_key) == 0
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "status")) == "failed"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "total_tasks"))
            == "295"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "ready_tasks")) == "0"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "inflight_tasks"))
            == "0"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "completed_tasks"))
            == "5"
        )
        assert (
            _decode_redis_value(await fake_redis.hget(state_key, "failed_tasks")) == "1"
        )

        repeated_cleanup = await storage.mark_job_failed(
            job.job_id,
            reason="job already failed",
        )
        assert repeated_cleanup is not None
        assert (
            repeated_cleanup.metadata["failure_reason"]
            == "proxy failure budget reached"
        )

    @pytest.mark.asyncio
    async def test_release_dedup_for_job_id_only_deletes_owned_key(
        self, storage: Any, fake_redis: Any
    ) -> None:
        from ultima_scraper_backend.job_system.models import Task, TaskType

        job_id = "job-dedup-release"
        task = Task(
            task_id="task-owned-by-cancelled-job",
            task_type=TaskType.SCRAPE,
            user_id=123,
            payload=None,
            site_name="OnlyFans",
        )
        await storage.persist_task(job_id, task)
        dedup_key = storage.DEDUPE_KEY.format(dedup=task.dedup_key)

        await fake_redis.set(dedup_key, "task-owned-by-another-job")
        await storage.release_dedup_for_job_id(job_id)
        assert (
            _decode_redis_value(await fake_redis.get(dedup_key))
            == "task-owned-by-another-job"
        )

        await fake_redis.set(dedup_key, task.task_id)
        await storage.release_dedup_for_job_id(job_id)
        assert await fake_redis.exists(dedup_key) == 0


class TestBackendRoutingCleanup:
    """Regression tests for queue cleanup during large job cancellation."""

    @pytest.mark.asyncio
    async def test_enqueue_ready_tasks_preserves_priority_and_batch_order(
        self, fake_redis: Any
    ) -> None:
        from ultima_scraper_backend.job_system.routing import BackendRouter

        router = BackendRouter(FakeRedisManager(fake_redis))
        await router.enqueue_ready_tasks(
            backend_id="backend-batched",
            items=[
                ("job-a", "task-a", 0),
                ("job-a", "task-b", -1),
                ("job-a", "task-c", 0),
            ],
        )

        members = await fake_redis.zrange(router._queue_key("backend-batched"), 0, -1)
        assert [_decode_redis_value(member) for member in members] == [
            "job-a:task-b",
            "job-a:task-a",
            "job-a:task-c",
        ]
        assert (
            int(await fake_redis.get(router._ready_sequence_key("backend-batched")))
            == 3
        )

    @pytest.mark.asyncio
    async def test_remove_ready_tasks_for_job_uses_prefix_scan(
        self, fake_redis: Any
    ) -> None:
        from ultima_scraper_backend.job_system.routing import BackendRouter

        manager = FakeRedisManager(fake_redis)
        router = BackendRouter(manager)

        await router.enqueue_ready_task(
            backend_id="backend-test",
            job_id="job-cancelled",
            task_id="task-1",
        )
        await router.enqueue_ready_task(
            backend_id="backend-test",
            job_id="job-cancelled",
            task_id="task-2",
        )
        await router.enqueue_ready_task(
            backend_id="backend-test",
            job_id="job-keep",
            task_id="task-3",
        )

        removed = await router.remove_ready_tasks_for_job(
            "backend-test",
            "job-cancelled",
            batch_size=1,
        )

        queue_key = router._queue_key("backend-test")
        remaining = await fake_redis.zrange(queue_key, 0, -1)
        normalized_remaining = [
            item.decode() if isinstance(item, bytes) else str(item)
            for item in remaining
        ]

        assert removed == 2
        assert normalized_remaining == ["job-keep:task-3"]

    @pytest.mark.asyncio
    async def test_mark_job_complete_removes_claimed_routing_state(
        self, fake_redis: Any
    ) -> None:
        from ultima_scraper_backend.job_system.models import Job, JobState
        from ultima_scraper_backend.job_system.routing import BackendRouter

        manager = FakeRedisManager(fake_redis)
        router = BackendRouter(manager)
        backend_id = "backend-complete"
        job = Job(name="Completed", created_by="tests", tasks=[])
        job.state = JobState.COMPLETED

        await fake_redis.zadd(router.LOAD_KEY, {backend_id: 1.0})
        await fake_redis.rpush(router._claimed_jobs_key(backend_id), job.job_id)
        await fake_redis.sadd(router.backend_jobs_key(backend_id), job.job_id)
        await fake_redis.set(router._job_envelope_key(job.job_id), "payload")
        await router.enqueue_ready_task(
            backend_id=backend_id,
            job_id=job.job_id,
            task_id="task-stale",
        )

        await router.mark_job_complete(
            backend_id=backend_id,
            job=job,
            success=True,
        )

        assert await fake_redis.lrange(router._claimed_jobs_key(backend_id), 0, -1) == []
        assert not await fake_redis.sismember(
            router.backend_jobs_key(backend_id), job.job_id
        )
        assert not await fake_redis.exists(router._job_envelope_key(job.job_id))
        assert await fake_redis.zcard(router._queue_key(backend_id)) == 0


class TestJobManagerCancellation:
    """Regression tests for fast cancellation control flow."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("no_ledger_runs")
    async def test_cancel_job_by_id_can_skip_deep_cleanup(self) -> None:
        from ultima_scraper_backend.job_system.manager import JobManager
        from ultima_scraper_backend.job_system.models import Job

        job = Job.create(
            name="Fast Cancel",
            created_by="webui",
            tasks=[],
        )
        storage = SimpleNamespace(
            fetch_job=AsyncMock(return_value=job),
            mark_job_cancelled=AsyncMock(return_value=job),
        )
        router = SimpleNamespace(clear_job_routing=AsyncMock())

        manager = JobManager.__new__(JobManager)
        manager.redis_manager = SimpleNamespace(set=AsyncMock(return_value=True))
        storage.task_archive_limits = lambda: (500, 64 * 1024 * 1024)
        manager.storage = storage
        manager.router = router
        manager.finalize_job_cancellation = AsyncMock()
        manager._resolve_backend_assignment = AsyncMock(return_value="backend-1")

        result = await manager.cancel_job_by_id(
            job.job_id,
            reason="cancelled by user",
            wait_for_resource_cleanup=False,
        )

        assert result is job
        storage.mark_job_cancelled.assert_awaited_once_with(
            job.job_id,
            reason="cancelled by user",
        )
        router.clear_job_routing.assert_awaited_once_with(
            job_id=job.job_id,
            backend_id="backend-1",
        )
        manager.finalize_job_cancellation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_finalize_job_completion_purges_task_blobs(self, fake_redis: Any) -> None:
        from ultima_scraper_backend.database.write_queue import (
            DatabaseWriteOperation,
        )
        from ultima_scraper_backend.job_system.manager import JobManager
        from ultima_scraper_backend.job_system.models import JobState

        call_order: list[str] = []
        storage = SimpleNamespace(
            fetch_job=AsyncMock(
                return_value=SimpleNamespace(
                    completed_at="2026-09-04T12:00:00+00:00",
                    state=JobState.COMPLETED, metadata={},
                )
            ),
            release_dedup_for_job_id=AsyncMock(
                side_effect=lambda job_id: call_order.append(f"release:{job_id}")
            ),
            purge_job_task_blobs=AsyncMock(
                side_effect=lambda job_id: call_order.append(f"purge:{job_id}") or 321
            ),
        )

        manager = JobManager.__new__(JobManager)
        manager.redis_manager = SimpleNamespace(
            set=AsyncMock(return_value=True),
            delete=AsyncMock(),
        )
        manager.database_writes = SimpleNamespace(
            submit=AsyncMock(
                side_effect=lambda _operation, payload, **_kwargs: (
                    call_order.append(f"archive:{payload['job_id']}")
                    or {"archived_tasks": 12}
                )
            )
        )
        from ultima_scraper_backend.job_system.storage import JobStorage

        storage._client = lambda: fake_redis
        for name in ("JOB_STATE_KEY", "JOB_CONFIG_KEY", "JOB_INDEX_KEY"):
            setattr(storage, name, getattr(JobStorage, name))
        await fake_redis.hset(storage.JOB_STATE_KEY.format(job_id="job-completed-1"), mapping={
            "status": "completed", "completed_at": "2026-09-04T12:00:00+00:00",
        })
        await fake_redis.set(storage.JOB_CONFIG_KEY.format(job_id="job-completed-1"), "{}")
        await fake_redis.zadd(storage.JOB_INDEX_KEY, {"job-completed-1": 1})
        storage.task_archive_limits = lambda: (500, 64 * 1024 * 1024)
        manager.storage = storage
        manager.router = SimpleNamespace()

        await legacy.finalize_job_completion(manager, "job-completed-1")

        manager.redis_manager.set.assert_awaited_once()
        acquired = manager.redis_manager.set.await_args
        assert acquired.args[0] == "ultimascraper:job:job-completed-1:terminal_cleanup_lock"
        assert acquired.args[1].startswith("job-manager:completed:")
        assert acquired.kwargs == {"nx": True, "ex": JobManager.TERMINAL_CLEANUP_LOCK_TTL}
        manager.database_writes.submit.assert_awaited_once()
        assert manager.database_writes.submit.await_args.args[0] == (
            DatabaseWriteOperation.ARCHIVE_JOB_TASKS
        )
        assert manager.database_writes.submit.await_args.args[1] == {
            "job_id": "job-completed-1",
            "batch_size": 500,
            "max_bytes": 64 * 1024 * 1024,
            "generation": "2026-09-04T12:00:00+00:00",
            "task_definition_id": "job-completed-1",
            "archive_signature": ANY,
        }
        storage.release_dedup_for_job_id.assert_awaited_once_with("job-completed-1")
        storage.purge_job_task_blobs.assert_awaited_once_with("job-completed-1")
        assert call_order == [
            "archive:job-completed-1",
            "release:job-completed-1",
            "purge:job-completed-1",
        ]

    @pytest.mark.asyncio
    async def test_finalize_job_completion_skips_purge_when_archive_fails(self, fake_redis: Any) -> None:
        from ultima_scraper_backend.job_system.manager import JobManager
        from ultima_scraper_backend.job_system.models import JobState

        storage = SimpleNamespace(
            fetch_job=AsyncMock(
                return_value=SimpleNamespace(
                    completed_at="2026-09-04T12:00:00+00:00",
                    state=JobState.COMPLETED, metadata={},
                )
            ),
            release_dedup_for_job_id=AsyncMock(),
            purge_job_task_blobs=AsyncMock(),
        )

        manager = JobManager.__new__(JobManager)
        manager.redis_manager = SimpleNamespace(
            set=AsyncMock(return_value=True),
            delete=AsyncMock(),
        )
        manager.database_writes = SimpleNamespace(
            submit=AsyncMock(side_effect=RuntimeError("db down"))
        )
        from ultima_scraper_backend.job_system.storage import JobStorage

        storage._client = lambda: fake_redis
        for name in ("JOB_STATE_KEY", "JOB_CONFIG_KEY", "JOB_INDEX_KEY"):
            setattr(storage, name, getattr(JobStorage, name))
        await fake_redis.hset(storage.JOB_STATE_KEY.format(job_id="job-completed-2"), mapping={
            "status": "completed", "completed_at": "2026-09-04T12:00:00+00:00",
        })
        await fake_redis.set(storage.JOB_CONFIG_KEY.format(job_id="job-completed-2"), "{}")
        await fake_redis.zadd(storage.JOB_INDEX_KEY, {"job-completed-2": 1})
        storage.task_archive_limits = lambda: (500, 64 * 1024 * 1024)
        manager.storage = storage
        manager.router = SimpleNamespace()

        await legacy.finalize_job_completion(manager, "job-completed-2")

        manager.database_writes.submit.assert_awaited_once()
        storage.release_dedup_for_job_id.assert_awaited_once_with("job-completed-2")
        storage.purge_job_task_blobs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prepare_retry_job_rejects_archived_terminal_tasks(self) -> None:
        from ultima_scraper_backend.job_system.manager import JobManager
        from ultima_scraper_backend.job_system.models import Job, JobState

        archived_job = Job.create(
            name="Archived Completed Job",
            created_by="webui",
            tasks=[],
        )
        archived_job.state = JobState.COMPLETED

        manager = JobManager.__new__(JobManager)
        manager.storage = SimpleNamespace(
            fetch_job_with_tasks=AsyncMock(return_value=archived_job)
        )

        with pytest.raises(RuntimeError, match="archived from Redis"):
            await manager.prepare_retry_job("job-completed-archived")


class TestJobBuilderDependencyNormalization:
    """Regression tests for dependency normalization in build_job."""

    def test_build_job_prunes_dangling_dependency_ids(self) -> None:
        """Download dependencies should not keep references to removed task IDs."""
        from ultima_scraper_api import ContentType

        from ultima_scraper_backend.job_system.job_builder import (
            build_job,
            build_task,
        )
        from ultima_scraper_backend.job_system.models import TaskType

        scrape_task = build_task(
            TaskType.SCRAPE,
            site_name="OnlyFans",
            user_id=123,
            user_username="creator",
            content_type=ContentType.POSTS,
            auth_id=None,
            download_media=False,
        ).model_copy(update={"task_id": "old-scrape-id"})

        download_task = build_task(
            TaskType.DOWNLOAD,
            site_name="OnlyFans",
            user_id=123,
            user_username="creator",
            content_type=ContentType.POSTS,
            auth_id=None,
        ).model_copy(update={"depends_on": ["old-scrape-id"]})

        expanded_scrape = scrape_task.model_copy(
            update={"task_id": "new-scrape-id", "auth_id": 42}
        )

        class _DummyDbManager:
            def disconnect(self) -> None:
                return

        with (
            patch(
                "ultima_scraper_backend.job_system.job_builder.create_usr_database_manager",
                return_value=_DummyDbManager(),
            ),
            patch(
                "ultima_scraper_backend.job_system.job_builder.iter_scrape_tasks_by_db_subscriptions",
                return_value=iter([expanded_scrape]),
            ),
        ):
            result = build_job(
                tasks=[scrape_task, download_task],
                job_name="regression-stale-deps",
            )

        downloads = [t for t in result.job.tasks if t.task_type == TaskType.DOWNLOAD]
        assert len(downloads) == 1
        assert downloads[0].depends_on == ["new-scrape-id"]
        assert downloads[0].auth_id == 42


class TestStaleDedupRecovery:
    """Regression tests for stale dedup cleanup and deferred task requeue."""

    @pytest.mark.asyncio
    async def test_requeue_deferred_respects_requeue_lock(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """A held requeue lock should prevent duplicate re-enqueue passes."""
        dedup_name = "task:scrape:lock-test:ContentType.POSTS"
        requeue_lock_key = storage.DEFERRED_REQUEUE_LOCK_KEY.format(
            dedup_key=dedup_name
        )

        await fake_redis.set(requeue_lock_key, b"other-worker", ex=30)

        requeued = await storage.requeue_deferred_tasks_for_dedup(
            dedup_name, default_backend_id="backend-test"
        )

        assert requeued == 0


class TestDeferredTaskLifecycle:
    """Regression tests for deferred task state transitions and recovery."""

    @pytest.mark.asyncio
    async def test_mark_deferred_then_requeue_updates_task_state(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """Deferred tasks should move to deferred state, then back to pending when requeued."""
        from ultima_scraper_backend.redis_channels import BACKEND_QUEUE_PREFIX

        backend_id = "backend-deferred-1"
        job_id = "job-deferred-1"
        task_id = "task-deferred-1"
        dedup_name = "task:scrape:999:ContentType.POSTS"
        deferred_member = f"{job_id}:{task_id}"

        task_key = storage.TASK_KEY.format(job_id=job_id, task_id=task_id)
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        ready_key = storage.TASKS_READY_KEY.format(job_id=job_id)
        deferred_key = storage.DEFERRED_TASKS_KEY.format(dedup_key=dedup_name)
        queue_key = f"{BACKEND_QUEUE_PREFIX}{backend_id}"

        await fake_redis.set(
            task_key, json.dumps({"task_id": task_id, "state": "pending"})
        )
        await fake_redis.hset(
            state_key, mapping={"status": "pending", "backend_id": backend_id}
        )
        await fake_redis.sadd(ready_key, task_id)

        await legacy.mark_task_deferred(storage, job_id, task_id, dedup_name)

        raw_after_defer = await fake_redis.get(task_key)
        assert raw_after_defer is not None
        blob_after_defer = json.loads(raw_after_defer)
        assert blob_after_defer["state"] == "deferred"
        assert await fake_redis.sismember(deferred_key, deferred_member)
        assert not await fake_redis.sismember(ready_key, task_id)

        requeued = await storage.requeue_deferred_tasks_for_dedup(
            dedup_name, default_backend_id=backend_id
        )
        assert requeued == 1

        raw_after_requeue = await fake_redis.get(task_key)
        assert raw_after_requeue is not None
        blob_after_requeue = json.loads(raw_after_requeue)
        assert blob_after_requeue["state"] == "pending"
        assert not await fake_redis.sismember(deferred_key, deferred_member)
        assert await fake_redis.sismember(ready_key, task_id)
        assert await fake_redis.zscore(queue_key, deferred_member) is not None

    @pytest.mark.asyncio
    async def test_requeue_keeps_marker_when_task_redeferred_mid_pass(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """If a task re-defers during requeue, the fresh deferred marker must survive."""
        backend_id = "backend-deferred-race-1"
        job_id = "job-deferred-race-1"
        task_id = "task-deferred-race-1"
        dedup_name = "task:download:222:ContentType.STORIES"
        deferred_member = f"{job_id}:{task_id}"

        task_key = storage.TASK_KEY.format(job_id=job_id, task_id=task_id)
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        ready_key = storage.TASKS_READY_KEY.format(job_id=job_id)
        deferred_key = storage.DEFERRED_TASKS_KEY.format(dedup_key=dedup_name)

        await fake_redis.set(
            task_key,
            json.dumps(
                {
                    "task_id": task_id,
                    "state": "deferred",
                    "deferred_dedup_key": dedup_name,
                }
            ),
        )
        await fake_redis.hset(
            state_key, mapping={"status": "pending", "backend_id": backend_id}
        )
        await fake_redis.sadd(deferred_key, deferred_member)

        from ultima_scraper_backend.job_system import recovery_scripts

        original_eval = fake_redis.eval

        async def _transition_and_redefer(script, numkeys, *args):
            result = await original_eval(script, numkeys, *args)
            if script == recovery_scripts.REQUEUE_DEFERRED and result == 1:
                # Simulate a worker re-deferring immediately after the atomic
                # pending/queue transition, before its caller resumes.
                await legacy.mark_task_deferred(storage, job_id, task_id, dedup_name)
            return result

        with patch.object(fake_redis, "eval", new=_transition_and_redefer):
            requeued = await storage.requeue_deferred_tasks_for_dedup(
                dedup_name, default_backend_id=backend_id
            )

        assert requeued == 1
        assert await fake_redis.sismember(deferred_key, deferred_member)
        assert not await fake_redis.sismember(ready_key, task_id)

        raw_task = await fake_redis.get(task_key)
        assert raw_task is not None
        task_blob = json.loads(raw_task)
        assert task_blob["state"] == "deferred"
        assert task_blob.get("deferred_dedup_key") == dedup_name

    @pytest.mark.asyncio
    async def test_release_dedup_for_job_id_requeues_deferred_tasks(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """Releasing dedup for a job must immediately wake up and requeue deferred tasks from other jobs."""
        from ultima_scraper_backend.job_system.models import Task, TaskType
        from ultima_scraper_backend.redis_channels import BACKEND_QUEUE_PREFIX

        backend_id = "backend-release-test"
        job_a = "job-a"
        job_b = "job-b"
        task_b_id = "task-b"

        task_a = Task(
            task_id="task-a",
            task_type=TaskType.SCRAPE,
            user_id=777,
            site_name="OnlyFans",
            payload=None,
        )
        await storage.persist_task(job_a, task_a)
        dedup_name = task_a.dedup_key
        dedup_key = storage.DEDUPE_KEY.format(dedup=dedup_name)
        deferred_key = storage.DEFERRED_TASKS_KEY.format(dedup_key=dedup_name)
        deferred_member_b = f"{job_b}:{task_b_id}"
        ready_key_b = storage.TASKS_READY_KEY.format(job_id=job_b)
        queue_key = f"{BACKEND_QUEUE_PREFIX}{backend_id}"

        # Job A owns dedup lock
        await fake_redis.set(dedup_key, task_a.task_id)

        # Job B has task deferred waiting for dedup lock
        await fake_redis.hset(
            storage.JOB_STATE_KEY.format(job_id=job_b),
            mapping={"status": "running", "backend_id": backend_id},
        )
        await fake_redis.set(
            storage.TASK_KEY.format(job_id=job_b, task_id=task_b_id),
            json.dumps({"task_id": task_b_id, "state": "deferred", "deferred_dedup_key": dedup_name}),
        )
        await fake_redis.sadd(deferred_key, deferred_member_b)

        # Release dedup for Job A (e.g. Job A was cancelled or finished)
        await storage.release_dedup_for_job_id(job_a, default_backend_id=backend_id)

        # Dedup key should be removed
        assert not await fake_redis.exists(dedup_key)
        # Job B's task should be re-enqueued to ready and backend queue
        assert await fake_redis.sismember(ready_key_b, task_b_id)
        assert not await fake_redis.sismember(deferred_key, deferred_member_b)
        assert await fake_redis.zscore(queue_key, deferred_member_b) is not None

    @pytest.mark.asyncio
    async def test_terminal_mps_abort_releases_unpublished_dedup_after_lease_loss(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """Cancellation must not leave reservations made by a losing publisher."""
        from ultima_scraper_backend.job_system import mps_state

        job_id = "job-cancelled-publication"
        task = SimpleNamespace(
            task_id="task-unpublished",
            dedup_key="task:scrape:OnlyFans:123:Profile:any",
        )
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        dedup_key = storage.DEDUPE_KEY.format(dedup=task.dedup_key)
        lock_key = "ultimascraper:mps:materialization:job-cancelled-publication:lock"
        await fake_redis.hset(state_key, mapping={"status": "cancelled"})
        await fake_redis.set(dedup_key, task.task_id)

        await mps_state.release_unpublished(
            storage,
            job_id,
            [task],
            lock_key=lock_key,
            lock_owner="lost-materializer",
        )

        assert not await fake_redis.exists(dedup_key)

    @pytest.mark.asyncio
    async def test_live_mps_replacement_keeps_unpublished_dedup_after_lease_loss(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """A live successor keeps its matching reservation when ownership changed."""
        from ultima_scraper_backend.job_system import mps_state

        job_id = "job-live-publication"
        task = SimpleNamespace(
            task_id="task-unpublished",
            dedup_key="task:scrape:OnlyFans:456:Profile:any",
        )
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        dedup_key = storage.DEDUPE_KEY.format(dedup=task.dedup_key)
        lock_key = "ultimascraper:mps:materialization:job-live-publication:lock"
        await fake_redis.hset(state_key, mapping={"status": "running"})
        await fake_redis.set(lock_key, "replacement-materializer")
        await fake_redis.set(dedup_key, task.task_id)

        await mps_state.release_unpublished(
            storage,
            job_id,
            [task],
            lock_key=lock_key,
            lock_owner="lost-materializer",
        )

        assert await fake_redis.get(dedup_key) == task.task_id.encode()


class TestBoundedTaskReads:
    """Regression tests for large-job-safe task loading."""

    @pytest.mark.asyncio
    async def test_persist_job_writes_job_and_task_indexes(
        self, storage: Any, fake_redis: Any
    ) -> None:
        from ultima_scraper_backend.job_system.models import Job, Task, TaskType

        task = Task(
            task_id="task-indexed-1",
            task_type=TaskType.API_COMMAND,
            user_id=1,
            payload=None,
            site_name="OnlyFans",
        )
        job = Job(name="Indexed job", created_by="tests", tasks=[task])

        await storage.persist_job(job, persist_tasks=True)

        assert await fake_redis.get(storage.JOB_CONFIG_KEY.format(job_id=job.job_id))
        assert (
            await fake_redis.hget(
                storage.JOB_STATE_KEY.format(job_id=job.job_id),
                "status",
            )
        ) is not None
        assert await fake_redis.zscore(storage.JOB_INDEX_KEY, job.job_id) is not None

        raw_task_ids = await fake_redis.zrange(
            storage.TASK_INDEX_KEY.format(job_id=job.job_id),
            0,
            -1,
        )
        normalized_task_ids = [
            item.decode() if isinstance(item, bytes) else str(item)
            for item in raw_task_ids
        ]
        assert normalized_task_ids == [task.task_id]

    @pytest.mark.asyncio
    async def test_persist_task_serializes_and_restores_pydantic_payloads(
        self, storage: Any, fake_redis: Any
    ) -> None:
        from ultima_scraper_backend.job_system.models import Job, Task, TaskType
        from ultima_scraper_backend.job_system.payloads import ScrapeTaskPayload

        payload = ScrapeTaskPayload(
            user_username="alice",
            max_items=1,
            download_media=False,
            use_guest_auth=True,
            track_invalid_user=True,
        )
        task = Task(
            task_id="task-payload-1",
            task_type=TaskType.SCRAPE,
            user_id=544318955,
            payload=payload,
            site_name="OnlyFans",
            user_username="alice",
            content_type="Profile",
        )
        job = Job(name="Payload job", created_by="tests", tasks=[task])

        await storage.persist_job(job, persist_tasks=True)

        raw_task = await fake_redis.get(
            storage.TASK_KEY.format(job_id=job.job_id, task_id=task.task_id)
        )
        assert raw_task is not None
        task_blob = json.loads(
            raw_task.decode() if isinstance(raw_task, bytes) else raw_task
        )
        assert task_blob["payload"]["use_guest_auth"] is True
        assert task_blob["payload"]["track_invalid_user"] is True

        loaded = await storage.fetch_task(job.job_id, task.task_id)
        assert loaded is not None
        assert isinstance(loaded.payload, ScrapeTaskPayload)
        assert loaded.payload.use_guest_auth is True
        assert loaded.payload.track_invalid_user is True

    @pytest.mark.asyncio
    async def test_fetch_task_ignores_template_payload_metadata_when_restoring_payloads(
        self, storage: Any
    ) -> None:
        from ultima_scraper_backend.job_system.models import Job, Task, TaskType
        from ultima_scraper_backend.job_system.payloads import ScrapeTaskPayload

        task = Task(
            task_id="task-template-payload-1",
            task_type=TaskType.SCRAPE,
            user_id=544318955,
            payload={
                "user_username": "alice",
                "download_media": True,
                "save_to_db": True,
                "template_content_type": "Posts",
                "template_task": "scrape_1",
            },
            site_name="OnlyFans",
            user_username="alice",
            content_type="Posts",
        )
        job = Job(name="Template payload job", created_by="tests", tasks=[task])

        await storage.persist_job(job, persist_tasks=True)

        loaded = await storage.fetch_task(job.job_id, task.task_id)
        assert loaded is not None
        assert isinstance(loaded.payload, ScrapeTaskPayload)
        assert loaded.payload.download_media is True
        assert loaded.payload.max_items is None
        assert "template_content_type" not in loaded.payload.model_dump()
        assert "template_task" not in loaded.payload.model_dump()

    @pytest.mark.asyncio
    async def test_seeded_scrape_download_template_instantiates_typed_payloads_without_template_metadata(
        self, fake_redis: Any
    ) -> None:
        from ultima_scraper_api import ContentType

        from ultima_scraper_backend.job_system.models import TaskType
        from ultima_scraper_backend.job_system.payloads import (
            DownloadTaskPayload,
            ScrapeTaskPayload,
        )
        from ultima_scraper_backend.job_system.templates import (
            JobTemplateStore,
            seed_builtin_templates,
        )

        store = JobTemplateStore(FakeRedisManager(fake_redis))
        templates = await seed_builtin_templates(store)

        assert len(templates) == 1

        template = templates[0]
        instantiation = template.instantiate(
            {
                "site": "OnlyFans",
                "user_id": 544318955,
                "username": "alice",
            },
            created_by="tests",
        )

        assert instantiation.tasks
        archived_tasks = [
            task
            for task in instantiation.tasks
            if task.content_type == ContentType.ARCHIVED_POSTS
        ]
        for task in instantiation.tasks:
            if task.task_type == TaskType.SCRAPE:
                assert isinstance(task.payload, ScrapeTaskPayload)
                payload_dump = task.payload.model_dump()
                assert task.payload.max_items is None
            else:
                assert task.task_type == TaskType.DOWNLOAD
                assert isinstance(task.payload, DownloadTaskPayload)
                payload_dump = task.payload.model_dump()
                assert task.payload.max_items is None

            assert "template_content_type" not in payload_dump
            assert "template_task" not in payload_dump

        assert len(archived_tasks) == 2
        assert all(
            task.content_type != "Archived Posts" for task in instantiation.tasks
        )

    @pytest.mark.asyncio
    async def test_seeded_scrape_download_template_downloads_each_content_type_once(
        self, fake_redis: Any
    ) -> None:
        from collections import Counter

        from ultima_scraper_backend.job_system.auth_expansion import (
            iter_scrape_tasks_by_db_subscriptions,
        )
        from ultima_scraper_backend.job_system.models import TaskType
        from ultima_scraper_backend.job_system.templates import (
            JobTemplateStore,
            seed_builtin_templates,
        )

        store = JobTemplateStore(FakeRedisManager(fake_redis))
        (template,) = await seed_builtin_templates(store)
        instantiation = template.instantiate(
            {"site": "OnlyFans", "user_id": 544318955, "username": "alice"},
            created_by="tests",
        )

        # Expanding a signed-in scrape adds a download for download_media;
        # the template's own download task must stay the only one.
        expanded = []
        for task in instantiation.tasks:
            task.auth_id = 53348944
            if task.task_type == TaskType.SCRAPE:
                expanded.extend(
                    iter_scrape_tasks_by_db_subscriptions(task=task, db_manager=None)
                )
            else:
                expanded.append(task)

        downloads = Counter(
            task.content_type for task in expanded if task.task_type == TaskType.DOWNLOAD
        )
        assert len(downloads) == 6
        assert set(downloads.values()) == {1}

    @pytest.mark.asyncio
    async def test_fetch_job_with_tasks_skips_task_loading_when_disabled(
        self, storage: Any
    ) -> None:
        from ultima_scraper_backend.job_system.models import Job

        job = Job(name="No inline tasks", created_by="tests", tasks=[])
        await storage.persist_job(job, persist_tasks=False)

        with patch.object(
            storage, "fetch_task_page", AsyncMock(side_effect=AssertionError)
        ):
            loaded = await storage.fetch_job_with_tasks(job.job_id, include_tasks=False)

        assert loaded is not None
        assert loaded.job_id == job.job_id
        assert loaded.tasks == []

    @pytest.mark.asyncio
    async def test_completed_filter_reads_recent_edge_in_one_batch(
        self, storage: Any, fake_redis: Any
    ) -> None:
        from ultima_scraper_backend.job_system.models import (
            Job,
            Task,
            TaskState,
            TaskType,
        )

        tasks = [
            Task(
                task_id=f"task-filter-{index}",
                task_type=TaskType.SCRAPE,
                user_id=index,
                payload=None,
                site_name="OnlyFans",
            )
            for index in range(43)
        ]
        job = Job(name="Sparse completed filter", created_by="tests", tasks=tasks)
        await storage.persist_job(job, persist_tasks=True)

        completed = tasks[-3:]
        for task in completed:
            task.state = TaskState.COMPLETED
            await storage.persist_task(job.job_id, task)

        original_zrevrange = fake_redis.zrevrange
        original_mget = fake_redis.mget

        async def recording_zrevrange(*args: Any, **kwargs: Any) -> Any:
            return await original_zrevrange(*args, **kwargs)

        async def recording_mget(*args: Any, **kwargs: Any) -> Any:
            return await original_mget(*args, **kwargs)

        with (
            patch.object(
                fake_redis,
                "zrange",
                AsyncMock(side_effect=AssertionError("forward scan used")),
            ),
            patch.object(
                fake_redis,
                "zrevrange",
                AsyncMock(side_effect=recording_zrevrange),
            ) as reverse_range,
            patch.object(
                fake_redis,
                "mget",
                AsyncMock(side_effect=recording_mget),
            ) as batch_get,
            patch.object(
                storage,
                "fetch_task",
                AsyncMock(side_effect=AssertionError("per-task GET used")),
            ),
        ):
            page = await storage.fetch_task_page(
                job.job_id,
                limit=2,
                state=TaskState.COMPLETED.value,
            )

        assert [task.task_id for task in page.tasks] == [
            completed[-1].task_id,
            completed[-2].task_id,
        ]
        assert page.next_cursor == "2"
        reverse_range.assert_awaited_once_with(
            storage.TASK_INDEX_KEY.format(job_id=job.job_id),
            0,
            9,
        )
        batch_get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_active_task_stats_use_authoritative_state_sets(
        self, storage: Any, fake_redis: Any
    ) -> None:
        job_id = "job-stats-drift"
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        await fake_redis.hset(
            state_key,
            mapping={
                "status": "running",
                "total_tasks": "99",
                "ready_tasks": "38",
                "blocked_tasks": "7",
                "inflight_tasks": "13",
                "completed_tasks": "244",
            },
        )
        await fake_redis.zadd(
            storage.TASK_INDEX_KEY.format(job_id=job_id),
            {f"task-{index}": float(index) for index in range(5)},
        )
        await fake_redis.sadd(
            storage.TASKS_READY_KEY.format(job_id=job_id), "task-1", "task-2"
        )
        await fake_redis.sadd(storage.TASKS_BLOCKED_KEY.format(job_id=job_id), "task-3")
        await fake_redis.sadd(
            storage.TASKS_INFLIGHT_KEY.format(job_id=job_id), "task-4"
        )
        await fake_redis.sadd(
            storage.TASKS_COMPLETED_KEY.format(job_id=job_id), "task-0"
        )

        stats = await storage.get_job_task_stats(job_id)

        assert stats["total"] == 5
        assert stats["ready"] == 2
        assert stats["blocked"] == 1
        assert stats["inflight"] == 1
        assert stats["completed"] == 1

    @pytest.mark.asyncio
    async def test_terminal_cleanup_preserves_set_backed_completion_snapshot(
        self, storage: Any, fake_redis: Any
    ) -> None:
        job_id = "job-terminal-snapshot"
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        await fake_redis.hset(
            state_key,
            mapping={
                "status": "completed",
                "total_tasks": "5",
                "ready_tasks": "1",
                "inflight_tasks": "1",
                "completed_tasks": "2",
                "failed_tasks": "0",
            },
        )
        await fake_redis.zadd(
            storage.TASK_INDEX_KEY.format(job_id=job_id),
            {f"task-{index}": float(index) for index in range(5)},
        )
        await fake_redis.sadd(
            storage.TASKS_COMPLETED_KEY.format(job_id=job_id),
            "task-0",
            "task-1",
            "task-2",
            "task-3",
        )

        await storage.clear_task_state(job_id, reset_stats=False)
        stats = await storage.get_job_task_stats(job_id)

        assert stats["total"] == 5
        assert stats["completed"] == 4
        assert stats["ready"] == 0
        assert stats["inflight"] == 0

class TestRemovedSQLiteSupport:
    """Document removed SQLite pathways in the job system."""

    def test_sqlite_status_sync_entrypoint_is_removed(self) -> None:
        from ultima_scraper_backend.job_system.storage import JobStorage

        assert not hasattr(JobStorage, "_sync_job_status_sqlite")

    def test_sqlite_fallback_allow_false_is_noop(self) -> None:
        import ultima_scraper_db_archive.global_db as gdb

        gdb.set_sqlite_fallback_allowed(False)


class TestRetentionArchivesTasksToCentralDb:
    """Ensure Redis task state is archived before retention wipes it."""

    @staticmethod
    async def _seed_job(storage: Any, fake_redis: Any, *, job_id: str) -> None:
        """Populate fakeredis with a terminal job and two persisted tasks."""
        from ultima_scraper_backend.job_system.models import Task, TaskType

        config_key = storage.JOB_CONFIG_KEY.format(job_id=job_id)
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)

        await fake_redis.set(
            config_key,
            json.dumps({"job_id": job_id, "job_type": "scrape"}),
        )
        await fake_redis.hset(
            state_key,
            mapping={
                "status": "completed",
                "total_tasks": "0",
                "completed_at": "2026-09-04T12:00:00+00:00",
            },
        )
        # Score in the past so cleanup picks it up.
        await fake_redis.zadd(storage.JOB_INDEX_KEY, {job_id: 0.0})

        task_a = Task(
            task_id="task-a",
            task_type=TaskType.SCRAPE,
            user_id=101,
            user_username="alice",
            site_name="OnlyFans",
            auth_id=7,
            state=__import__(
                "ultima_scraper_backend.job_system.models",
                fromlist=["TaskState"],
            ).TaskState.COMPLETED,
        )
        task_b = Task(
            task_id="task-b",
            task_type=TaskType.DOWNLOAD,
            user_id=202,
            user_username="bob",
            site_name="Fansly",
            auth_id=9,
            state=__import__(
                "ultima_scraper_backend.job_system.models",
                fromlist=["TaskState"],
            ).TaskState.FAILED,
        )
        from unittest.mock import AsyncMock, patch

        with patch.object(
            storage, "fetch_job_with_tasks", AsyncMock(return_value=None)
        ):
            await legacy.add_task_to_job(storage, job_id, task_a)
            await legacy.add_task_to_job(storage, job_id, task_b)

    @pytest.mark.asyncio
    async def test_archive_job_tasks_to_db_persists_rows(
        self, storage: Any, fake_redis: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = "job-archive-1"
        await self._seed_job(storage, fake_redis, job_id=job_id)

        deleted_job_ids: list[str] = []
        inserted_rows: list[list[dict[str, Any]]] = []

        def fake_delete(job_id_arg: str) -> int:
            deleted_job_ids.append(job_id_arg)
            return 0

        def fake_insert(rows: list[dict[str, Any]]) -> int:
            inserted_rows.append([dict(row) for row in rows])
            return len(rows)

        monkeypatch.setattr(
            type(storage), "_delete_central_tasks_sync", staticmethod(fake_delete)
        )
        monkeypatch.setattr(
            type(storage), "_insert_central_tasks_sync", staticmethod(fake_insert)
        )
        monkeypatch.setattr(
            type(storage), "_count_central_tasks_sync", staticmethod(lambda _job: sum(map(len, inserted_rows)))
        )

        archived = await storage._archive_job_tasks_to_db(job_id)

        assert archived == 2
        assert deleted_job_ids == [job_id]
        flat_rows = [row for batch in inserted_rows for row in batch]
        assert {row["task_id"] for row in flat_rows} == {"task-a", "task-b"}
        by_id = {row["task_id"]: row for row in flat_rows}
        assert by_id["task-a"]["status"] == "completed"
        assert by_id["task-a"]["job_id"] == job_id
        assert by_id["task-a"]["task_type"] == "scrape"
        assert by_id["task-a"]["site"] == "OnlyFans"
        assert by_id["task-a"]["username"] == "alice"
        assert by_id["task-a"]["auth_id"] == 7
        assert by_id["task-b"]["status"] == "failed"
        assert by_id["task-b"]["site"] == "Fansly"

    @pytest.mark.asyncio
    async def test_cleanup_archives_before_deleting_redis(
        self, storage: Any, fake_redis: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = "job-archive-2"
        await self._seed_job(storage, fake_redis, job_id=job_id)

        call_order: list[str] = []
        inserted_rows: list[dict[str, Any]] = []

        def fake_delete(_: str) -> int:
            return 0

        def fake_insert(rows: list[dict[str, Any]]) -> int:
            inserted_rows.extend(rows)
            call_order.append("archive")
            return len(rows)

        async def stub_delete_job(arg_job_id: str) -> None:
            call_order.append(f"delete:{arg_job_id}")

        monkeypatch.setattr(
            type(storage), "_delete_central_tasks_sync", staticmethod(fake_delete)
        )
        monkeypatch.setattr(
            type(storage), "_insert_central_tasks_sync", staticmethod(fake_insert)
        )
        monkeypatch.setattr(
            type(storage), "_count_central_tasks_sync", staticmethod(lambda _job: len(inserted_rows))
        )
        monkeypatch.setattr(storage, "delete_job", stub_delete_job)

        async def archive_through_writer(
            _operation: object,
            payload: dict[str, Any],
            **_kwargs: object,
        ) -> dict[str, int]:
            archived = await storage._archive_job_tasks_to_db(payload["job_id"])
            return {"archived_tasks": archived}

        storage.database_writes = SimpleNamespace(
            max_command_bytes=64 * 1024 * 1024,
            submit=AsyncMock(side_effect=archive_through_writer)
        )

        removed = await storage.cleanup_completed_jobs(0)

        assert removed == 1
        assert call_order == ["archive", f"delete:{job_id}"]
        assert {row["task_id"] for row in inserted_rows} == {"task-a", "task-b"}

    @pytest.mark.asyncio
    async def test_cleanup_skips_delete_when_archive_fails(
        self, storage: Any, fake_redis: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        job_id = "job-archive-3"
        await self._seed_job(storage, fake_redis, job_id=job_id)

        delete_calls: list[str] = []

        def fake_delete(_: str) -> int:
            return 0

        def exploding_insert(_: list[dict[str, Any]]) -> int:
            raise RuntimeError("db down")

        async def stub_delete_job(arg_job_id: str) -> None:
            delete_calls.append(arg_job_id)

        monkeypatch.setattr(
            type(storage), "_delete_central_tasks_sync", staticmethod(fake_delete)
        )
        monkeypatch.setattr(
            type(storage),
            "_insert_central_tasks_sync",
            staticmethod(exploding_insert),
        )
        monkeypatch.setattr(storage, "delete_job", stub_delete_job)
        storage.database_writes = SimpleNamespace(
            max_command_bytes=64 * 1024 * 1024,
            submit=AsyncMock(side_effect=RuntimeError("db down"))
        )

        removed = await storage.cleanup_completed_jobs(0)

        # Archive failure must not delete Redis state.
        assert removed == 0
        assert delete_calls == []

    @pytest.mark.asyncio
    async def test_archive_preserves_download_results_and_message(
        self, storage: Any, fake_redis: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Per-media download failures must survive Redis retention via result_json."""
        from ultima_scraper_backend.job_system.models import (
            Task,
            TaskResult,
            TaskState,
            TaskType,
        )

        job_id = "job-archive-errors"
        config_key = storage.JOB_CONFIG_KEY.format(job_id=job_id)
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        await fake_redis.set(
            config_key,
            json.dumps({"job_id": job_id, "job_type": "scrape"}),
        )
        await fake_redis.hset(
            state_key,
            mapping={"status": "completed", "total_tasks": "0"},
        )
        await fake_redis.zadd(storage.JOB_INDEX_KEY, {job_id: 0.0})

        download_results = [
            {
                "status": "failed",
                "error_type": "size_mismatch",
                "media_id": 2451109556,
                "content_type": "Stories",
                "filepath": "/mnt/media/bad.mp4",
            },
            {
                "status": "failed",
                "error_type": "download_error",
                "media_id": 2451109557,
                "content_type": "Stories",
            },
        ]
        task = Task(
            task_id="task-dl-err",
            task_type=TaskType.DOWNLOAD,
            user_id=11574192,
            user_username="lunadiaz12",
            site_name="OnlyFans",
            auth_id=1,
            state=TaskState.COMPLETED,
            result=TaskResult(
                success=True,
                message="Scraped Stories: saved=1, failed=2",
                output={"download_results": download_results},
                errors=[],
            ),
        )

        from unittest.mock import AsyncMock, patch

        with patch.object(
            storage, "fetch_job_with_tasks", AsyncMock(return_value=None)
        ):
            await legacy.add_task_to_job(storage, job_id, task)

        inserted_rows: list[dict[str, Any]] = []

        def fake_delete(_: str) -> int:
            return 0

        def fake_insert(rows: list[dict[str, Any]]) -> int:
            inserted_rows.extend(rows)
            return len(rows)

        monkeypatch.setattr(
            type(storage), "_delete_central_tasks_sync", staticmethod(fake_delete)
        )
        monkeypatch.setattr(
            type(storage), "_insert_central_tasks_sync", staticmethod(fake_insert)
        )
        monkeypatch.setattr(
            type(storage), "_count_central_tasks_sync", staticmethod(lambda _job: len(inserted_rows))
        )

        archived = await storage._archive_job_tasks_to_db(job_id)
        assert archived == 1

        row = inserted_rows[0]
        assert row["message"] == "Scraped Stories: saved=1, failed=2"
        assert row["result_json"] is not None
        parsed = json.loads(row["result_json"])
        assert parsed["output"]["download_results"] == download_results


class TestCentralJobStatusSync:
    """Verify terminal job states are persisted back to the management DB."""

    class _FakeSession:
        def __init__(
            self, row: Any | None, *, update_rowcounts: list[int] | None = None
        ) -> None:
            self._row = row
            self.added: list[Any] = []
            self.committed = False
            self.rolled_back = False
            self.executed_updates: list[object] = []
            self._update_rowcounts = update_rowcounts or []

        def __enter__(self) -> TestCentralJobStatusSync._FakeSession:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, _model: Any, job_id: str) -> Any | None:
            if self._row is not None:
                assert job_id == self._row.job_id
            return self._row

        def add(self, row: Any) -> None:
            self.added.append(row)

        def execute(self, statement: object) -> Any:
            if getattr(statement, "is_select", False):
                return SimpleNamespace(first=lambda: (self._row, self._row.job_id) if self._row is not None else None)
            self.executed_updates.append(statement)
            rowcount = self._update_rowcounts.pop(0) if self._update_rowcounts else 0
            return SimpleNamespace(rowcount=rowcount)

        def commit(self) -> None:
            self.committed = True

        def rollback(self) -> None:
            self.rolled_back = True

    @pytest.mark.parametrize(
        ("status", "error", "completed_at", "expected_success", "expected_error"),
        [
            (
                "completed",
                None,
                "2026-03-15T11:22:33Z",
                True,
                None,
            ),
            (
                "failed",
                "download exploded",
                None,
                False,
                "download exploded",
            ),
            (
                "cancelled",
                None,
                None,
                False,
                None,
            ),
        ],
    )
    def test_update_job_status_database_syncs_terminal_status(
        self,
        monkeypatch: pytest.MonkeyPatch,
        status: str,
        error: str | None,
        completed_at: str | None,
        expected_success: bool,
        expected_error: str | None,
    ) -> None:
        import ultima_scraper_db_archive.global_db as gdb
        from ultima_scraper_backend.job_system.storage import JobStorage

        row = SimpleNamespace(
            job_id="job-sync-1",
            status="running",
            completed_at=None,
            result_success=None,
            result_error="old error",
            result_completed_at=None,
            last_event_at=None,
        )
        fake_session = self._FakeSession(row)
        monkeypatch.setattr(gdb, "global_session", lambda: fake_session)

        JobStorage._update_job_status_database_sync(
            row.job_id,
            status,
            error=error,
            completed_at=completed_at,
        )

        assert row.status == status
        assert row.result_success is expected_success
        assert row.result_error == expected_error
        assert row.completed_at is not None
        assert row.result_completed_at == row.completed_at
        assert row.last_event_at == row.completed_at
        assert fake_session.added == [row]
        assert len(fake_session.executed_updates) == 1
        assert fake_session.committed is True
        assert fake_session.rolled_back is False

    def test_update_job_status_database_upserts_missing_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import ultima_scraper_db_archive.global_db as gdb
        from ultima_scraper_backend.job_system.storage import JobStorage

        fake_session = self._FakeSession(None)
        monkeypatch.setattr(gdb, "global_session", lambda: fake_session)

        JobStorage._update_job_status_database_sync(
            "job-missing",
            "completed",
            completed_at="2026-03-15T11:22:33Z",
            job_snapshot={
                "name": "Scrape + Download",
                "created_by": "webui",
                "site": "OnlyFans",
                "created_at": "2026-03-15T10:00:00Z",
                "started_at": "2026-03-15T10:05:00Z",
                "total_tasks": 12,
                "metadata": {"source": "tasks"},
            },
        )

        assert len(fake_session.added) == 1
        row = fake_session.added[0]
        assert row.job_id == "job-missing"
        assert row.job_type == "Scrape + Download"
        assert row.site == "onlyfans"
        assert row.status == "completed"
        assert json.loads(row.args_json) == {
            "job_name": "Scrape + Download",
            "created_by": "webui",
            "task_count": 12,
            "source": "tasks",
        }
        assert row.created_at == datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
        assert row.started_at == datetime(2026, 3, 15, 10, 5, tzinfo=timezone.utc)
        assert row.result_success is True
        assert row.completed_at == datetime(
            2026, 3, 15, 11, 22, 33, tzinfo=timezone.utc
        )
        assert row.result_completed_at == row.completed_at
        assert row.last_event_at == row.completed_at
        assert len(fake_session.executed_updates) == 1
        assert fake_session.committed is True
        assert fake_session.rolled_back is False

    @pytest.mark.asyncio
    async def test_reconcile_database_jobs_repairs_terminal_job_tasks(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import ultima_scraper_db_archive.global_db as gdb
        from ultima_scraper_backend.job_system.storage import JobStorage

        class _FakeReconcileSession(self._FakeSession):
            def __init__(self) -> None:
                super().__init__(None)

            def execute(self, statement: object) -> Any:
                self.executed_updates.append(statement)
                return SimpleNamespace(one=lambda: (3, 3, "task-last"))

        fake_session = _FakeReconcileSession()
        monkeypatch.setattr(gdb, "global_session", lambda: fake_session)
        storage = JobStorage(SimpleNamespace(client=SimpleNamespace()))
        result = storage._reconcile_database_jobs_sync(batch_size=3)

        assert result == {"repaired_tasks": 3, "next_task_id": "task-last"}
        assert len(fake_session.executed_updates) == 1
        assert fake_session.committed is True
        assert fake_session.rolled_back is False


# ---------------------------------------------------------------------------
# 3) SQL pagination tests for list_jobs
# ---------------------------------------------------------------------------


class TestSqlPagination:
    """Test _fetch_paginated_db_jobs (SQL LIMIT/OFFSET pagination)."""

    def test_pagination_returns_correct_page(self, tmp_path: Path) -> None:
        """Should return only the requested page of results."""
        from uuid import uuid4

        import ultima_scraper_db_archive.global_db as gdb

        gdb._global_engine = None
        _require_configured_global_postgres(gdb, tmp_path)
        try:
            _require_reachable_global_postgres(gdb)
            prefix = f"page-job-{uuid4().hex[:8]}-"
            # Insert 15 jobs
            with gdb.global_session() as session:
                for i in range(15):
                    job = gdb.CentralJobModel(
                        job_id=f"{prefix}{i:03d}",
                        job_type="scrape",
                        site="onlyfans",
                        status="completed",
                    )
                    session.add(job)
                session.commit()

            # Fetch page 1, size 5
            from sqlalchemy import func as sa_func
            from sqlalchemy import select as sql_select

            with gdb.global_session() as session:
                total: int = session.exec(
                    sql_select(sa_func.count())
                    .select_from(gdb.CentralJobModel)
                    .where(gdb.CentralJobModel.job_id.like(f"{prefix}%"))
                ).scalar()
                assert total == 15

                query = (
                    sql_select(gdb.CentralJobModel)
                    .where(gdb.CentralJobModel.job_id.like(f"{prefix}%"))
                    .order_by(gdb.CentralJobModel.created_at.desc())
                    .offset(0)
                    .limit(5)
                )
                rows = list(session.exec(query).all())
                assert len(rows) == 5

            # Fetch page 3 (last page, partial)
            with gdb.global_session() as session:
                query = (
                    sql_select(gdb.CentralJobModel)
                    .where(gdb.CentralJobModel.job_id.like(f"{prefix}%"))
                    .order_by(gdb.CentralJobModel.created_at.desc())
                    .offset(10)
                    .limit(5)
                )
                rows = list(session.exec(query).all())
                assert len(rows) == 5
        finally:
            gdb._global_engine = None

    def test_pagination_with_status_filter(self, tmp_path: Path) -> None:
        """Should filter by status and return correct total."""
        from uuid import uuid4

        import ultima_scraper_db_archive.global_db as gdb

        gdb._global_engine = None
        _require_configured_global_postgres(gdb, tmp_path)
        try:
            _require_reachable_global_postgres(gdb)
            prefix = f"filter-job-{uuid4().hex[:8]}-"
            with gdb.global_session() as session:
                for i in range(10):
                    job = gdb.CentralJobModel(
                        job_id=f"{prefix}{i:03d}",
                        job_type="scrape",
                        site="onlyfans",
                        status="completed" if i < 7 else "pending",
                    )
                    session.add(job)
                session.commit()

            from sqlalchemy import func as sa_func
            from sqlalchemy import select as sql_select

            with gdb.global_session() as session:
                count_q = (
                    sql_select(sa_func.count())
                    .select_from(gdb.CentralJobModel)
                    .where(gdb.CentralJobModel.job_id.like(f"{prefix}%"))
                    .where(gdb.CentralJobModel.status == "completed")
                )
                total: int = session.exec(count_q).scalar()
                assert total == 7

                count_q_pending = (
                    sql_select(sa_func.count())
                    .select_from(gdb.CentralJobModel)
                    .where(gdb.CentralJobModel.job_id.like(f"{prefix}%"))
                    .where(gdb.CentralJobModel.status == "pending")
                )
                total_pending: int = session.exec(count_q_pending).scalar()
                assert total_pending == 3
        finally:
            gdb._global_engine = None

    def test_empty_page_returns_empty(self, tmp_path: Path) -> None:
        """Page beyond results should return empty list, not error."""
        from uuid import uuid4

        import ultima_scraper_db_archive.global_db as gdb

        gdb._global_engine = None
        _require_configured_global_postgres(gdb, tmp_path)
        try:
            _require_reachable_global_postgres(gdb)
            prefix = f"empty-page-job-{uuid4().hex[:8]}-"
            with gdb.global_session() as session:
                job = gdb.CentralJobModel(
                    job_id=f"{prefix}only-job",
                    job_type="scrape",
                    site="onlyfans",
                    status="completed",
                )
                session.add(job)
                session.commit()

            from sqlalchemy import select as sql_select

            with gdb.global_session() as session:
                query = (
                    sql_select(gdb.CentralJobModel)
                    .where(gdb.CentralJobModel.job_id.like(f"{prefix}%"))
                    .order_by(gdb.CentralJobModel.created_at.desc())
                    .offset(100)
                    .limit(10)
                )
                rows = list(session.exec(query).all())
                assert rows == []
        finally:
            gdb._global_engine = None


# ---------------------------------------------------------------------------
# 4) CONTENT_TYPE_MAP tests
# ---------------------------------------------------------------------------


class TestContentTypeMap:
    """Test the CONTENT_TYPE_MAP module-level constant."""

    def test_map_exists_and_has_expected_keys(self) -> None:
        from ultima_scraper_backend.api.routes.jobs import CONTENT_TYPE_MAP

        expected_keys = {
            "Posts",
            "ArchivedPosts",
            "Archived",
            "Messages",
            "Stories",
            "Highlights",
            "Profile",
            "Chats",
            "MassMessages",
        }
        assert set(CONTENT_TYPE_MAP.keys()) == expected_keys

    def test_map_values_are_enum_members(self) -> None:
        from enum import Enum

        from ultima_scraper_backend.api.routes.jobs import CONTENT_TYPE_MAP

        for key, value in CONTENT_TYPE_MAP.items():
            assert isinstance(
                value, Enum
            ), f"{key} maps to {type(value)}, expected Enum"

    def test_map_is_not_empty(self) -> None:
        from ultima_scraper_backend.api.routes.jobs import CONTENT_TYPE_MAP

        assert len(CONTENT_TYPE_MAP) > 0


# ---------------------------------------------------------------------------
# 5) deque for _processed_message_ids tests
# ---------------------------------------------------------------------------


class TestProcessedMessageIds:
    """Test the deque replacement for _processed_message_ids."""

    def test_type_is_deque(self) -> None:
        """_processed_message_ids should be a deque, not a set."""
        # We instantiate with a mock backend to avoid real initialization
        from ultima_scraper_backend.websocket_actions import (
            WebSocketActionHandler,
        )

        mock_backend = MagicMock()
        mock_backend.ultima_scraper_api = None
        handler = WebSocketActionHandler(mock_backend)
        assert isinstance(handler._processed_message_ids, deque)

    def test_maxlen_is_1000(self) -> None:
        """deque should have maxlen=1000."""
        from ultima_scraper_backend.websocket_actions import (
            WebSocketActionHandler,
        )

        mock_backend = MagicMock()
        mock_backend.ultima_scraper_api = None
        handler = WebSocketActionHandler(mock_backend)
        assert handler._processed_message_ids.maxlen == 1000

    def test_deque_auto_evicts(self) -> None:
        """deque should automatically evict oldest entries when full."""
        from ultima_scraper_backend.websocket_actions import (
            WebSocketActionHandler,
        )

        mock_backend = MagicMock()
        mock_backend.ultima_scraper_api = None
        handler = WebSocketActionHandler(mock_backend)

        # Fill to capacity
        for i in range(1000):
            handler._processed_message_ids.append(f"msg-{i}")
        assert len(handler._processed_message_ids) == 1000
        assert "msg-0" in handler._processed_message_ids

        # Add one more — oldest should be evicted
        handler._processed_message_ids.append("msg-1000")
        assert len(handler._processed_message_ids) == 1000
        assert "msg-0" not in handler._processed_message_ids
        assert "msg-1000" in handler._processed_message_ids

    def test_in_operator_works(self) -> None:
        """'in' operator should work for dedup checks."""
        from ultima_scraper_backend.websocket_actions import (
            WebSocketActionHandler,
        )

        mock_backend = MagicMock()
        mock_backend.ultima_scraper_api = None
        handler = WebSocketActionHandler(mock_backend)

        handler._processed_message_ids.append("test-msg")
        assert "test-msg" in handler._processed_message_ids
        assert "other-msg" not in handler._processed_message_ids

    def test_no_manual_pruning_constants(self) -> None:
        """MAX_PROCESSED_MESSAGE_IDS and REMOVE_PROCESSED_COUNT
        should no longer exist in websocket_actions module."""
        import ultima_scraper_backend.websocket_actions as wa

        assert not hasattr(wa, "MAX_PROCESSED_MESSAGE_IDS")
        assert not hasattr(wa, "REMOVE_PROCESSED_COUNT")


# ---------------------------------------------------------------------------
# 6) Redis scan_iter tests (verify keys are found via scan rather than KEYS)
# ---------------------------------------------------------------------------


class TestScanIter:
    """Test that scan_iter-based methods discover keys correctly."""

    @pytest.mark.asyncio
    async def test_scan_iter_finds_state_keys(self, fake_redis: Any) -> None:
        """scan_iter should find job state keys matching the pattern."""
        # Seed some keys
        await fake_redis.set("ultimascraper:job:job-1:state", "running")
        await fake_redis.set("ultimascraper:job:job-2:state", "completed")
        await fake_redis.set("ultimascraper:unrelated:key", "value")

        found: list[str] = []
        async for key in fake_redis.scan_iter(
            match="ultimascraper:job:*:state", count=100
        ):
            k = key.decode() if isinstance(key, bytes) else str(key)
            found.append(k)

        assert len(found) == 2
        assert "ultimascraper:job:job-1:state" in found
        assert "ultimascraper:job:job-2:state" in found

    @pytest.mark.asyncio
    async def test_scan_iter_empty_when_no_match(self, fake_redis: Any) -> None:
        """scan_iter should return nothing when no keys match."""
        await fake_redis.set("ultimascraper:other:key", "value")

        found: list[str] = []
        async for key in fake_redis.scan_iter(
            match="ultimascraper:job:*:state", count=100
        ):
            k = key.decode() if isinstance(key, bytes) else str(key)
            found.append(k)

        assert found == []


# ---------------------------------------------------------------------------
# 9) Watch pause feature tests
# ---------------------------------------------------------------------------


class TestWatchesPausedKey:
    """Test the WATCHES_PAUSED_KEY constant exists in redis keys."""

    def test_key_constant_exists(self) -> None:
        from ultima_scraper_backend.redis.keys import WATCHES_PAUSED_KEY

        assert "watches:paused" in WATCHES_PAUSED_KEY

    def test_key_uses_prefix(self) -> None:
        from ultima_scraper_backend.redis.keys import (
            KEY_PREFIX,
            WATCHES_PAUSED_KEY,
        )

        assert WATCHES_PAUSED_KEY.startswith(KEY_PREFIX)


class TestAreWatchesPaused:
    """Test _are_watches_paused on the WebSocketActionHandler."""

    @pytest.fixture
    def handler(self) -> Any:
        """Create a minimal WebSocketActionHandler for testing."""
        from ultima_scraper_backend.websocket_actions import (
            WebSocketActionHandler,
        )

        h = WebSocketActionHandler.__new__(WebSocketActionHandler)
        h.redis = None
        h.engine = None
        h._watched_user_ids = set()
        h._watched_cache_ts = 0.0
        h._WATCHED_CACHE_TTL = 30.0
        h._watched_db_manager = None
        return h

    @pytest.mark.asyncio
    async def test_not_paused_when_no_redis(self, handler: Any) -> None:
        """No Redis → always not paused."""
        handler.redis = None
        assert await handler._are_watches_paused() is False

    @pytest.mark.asyncio
    async def test_not_paused_when_key_absent(
        self, handler: Any, fake_redis: Any
    ) -> None:
        """Redis connected but key not set → not paused."""
        handler.redis = fake_redis
        assert await handler._are_watches_paused() is False

    @pytest.mark.asyncio
    async def test_paused_when_key_present(self, handler: Any, fake_redis: Any) -> None:
        """Redis key set → paused."""
        from ultima_scraper_backend.redis.keys import WATCHES_PAUSED_KEY

        await fake_redis.set(WATCHES_PAUSED_KEY, "1")
        handler.redis = fake_redis
        assert await handler._are_watches_paused() is True

    @pytest.mark.asyncio
    async def test_not_paused_after_key_deleted(
        self, handler: Any, fake_redis: Any
    ) -> None:
        """Key set then deleted → not paused."""
        from ultima_scraper_backend.redis.keys import WATCHES_PAUSED_KEY

        await fake_redis.set(WATCHES_PAUSED_KEY, "1")
        await fake_redis.delete(WATCHES_PAUSED_KEY)
        handler.redis = fake_redis
        assert await handler._are_watches_paused() is False


# ---------------------------------------------------------------------------
# 10) WorkerRegistry threaded heartbeat tests
# ---------------------------------------------------------------------------


class TestThreadedHeartbeat:
    """Test that WorkerRegistry uses a daemon thread for heartbeats."""

    def _make_registry(self) -> Any:
        """Create a WorkerRegistry with a mock RedisManager."""
        from unittest.mock import AsyncMock

        from ultima_scraper_backend.redis.worker_registry import (
            WorkerRegistry,
        )

        mock_redis = MagicMock()
        mock_redis.config = MagicMock()
        mock_redis.config.host = "localhost"
        mock_redis.config.port = 6379
        mock_redis.config.db = 0
        mock_redis.config.password = None
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.sadd = AsyncMock(return_value=1)

        registry = WorkerRegistry(
            redis_manager=mock_redis,
            backend_id="test-backend",
            worker_id="test-worker-001",
            worker_type="scraper",
            ttl=120,
            heartbeat_interval=1,  # 1s for fast test
        )
        return registry

    @pytest.mark.asyncio
    async def test_start_heartbeat_spawns_thread(self) -> None:
        """start_heartbeat() should create a daemon thread."""
        registry = self._make_registry()

        # Patch sync_redis.Redis to avoid real connection
        with patch("ultima_scraper_backend.redis.worker_registry.sync_redis.Redis"):
            await registry.start_heartbeat()

        assert registry._running is True
        assert registry._heartbeat_thread is not None
        assert registry._heartbeat_thread.is_alive()
        assert registry._heartbeat_thread.daemon is True
        assert "heartbeat-test-worker-001" == registry._heartbeat_thread.name

        await registry.stop_heartbeat()
        assert registry._running is False

    @pytest.mark.asyncio
    async def test_stop_heartbeat_joins_thread(self) -> None:
        """stop_heartbeat() should stop the thread within a reasonable time."""
        registry = self._make_registry()

        with patch("ultima_scraper_backend.redis.worker_registry.sync_redis.Redis"):
            await registry.start_heartbeat()
            assert registry._heartbeat_thread is not None
            assert registry._heartbeat_thread.is_alive()

            await registry.stop_heartbeat()
            assert registry._heartbeat_thread is None

    @pytest.mark.asyncio
    async def test_threaded_heartbeat_calls_redis(self) -> None:
        """The heartbeat thread should call SET and EXPIRE on the sync Redis."""
        import time

        mock_sync_redis = MagicMock()
        mock_sync_redis.set = MagicMock(return_value=True)
        mock_sync_redis.expire = MagicMock(return_value=True)
        mock_sync_redis.sadd = MagicMock(return_value=1)
        mock_sync_redis.close = MagicMock()

        registry = self._make_registry()

        with patch(
            "ultima_scraper_backend.redis.worker_registry.sync_redis.Redis",
            return_value=mock_sync_redis,
        ):
            await registry.start_heartbeat()
            # Wait for at least one heartbeat cycle
            time.sleep(1.5)
            await registry.stop_heartbeat()

        # The thread should have called set() for heartbeat key
        assert mock_sync_redis.set.call_count >= 1
        # And expire() for worker info key
        assert mock_sync_redis.expire.call_count >= 1
        # And sadd() for set memberships
        assert mock_sync_redis.sadd.call_count >= 1

    def test_ttl_increased_to_120(self) -> None:
        """DEFAULT_TTL should be 120s (not the old 45s)."""
        from ultima_scraper_backend.redis.worker_registry import (
            WorkerRegistry,
        )

        assert WorkerRegistry.DEFAULT_TTL == 120

    def test_heartbeat_interval_increased_to_30(self) -> None:
        """HEARTBEAT_INTERVAL should be 30s (not the old 15s)."""
        from ultima_scraper_backend.redis.worker_registry import (
            WorkerRegistry,
        )

        assert WorkerRegistry.HEARTBEAT_INTERVAL == 30


# ---------------------------------------------------------------------------
# 10) Redis memory optimisation tests
# ---------------------------------------------------------------------------


class TestRedisMemoryOptimisations:
    """Verify TTL reductions and cleanup_completed_jobs behaviour."""

    def test_task_state_ttl_is_24_hours(self) -> None:
        """DEFAULT_TASK_STATE_TTL should match the current 24h retention."""
        from ultima_scraper_backend.job_system.storage import JobStorage

        assert JobStorage.DEFAULT_TASK_STATE_TTL == 24 * 60 * 60

    def test_event_stream_ttl_is_24_hours(self) -> None:
        """STREAM_TTL should be 24h, not the old 7d."""
        from ultima_scraper_backend.job_system.event_log import EventLog

        assert EventLog.STREAM_TTL == 24 * 60 * 60

    @pytest.mark.asyncio
    async def test_cleanup_completed_jobs_removes_terminal(
        self,
        storage: Any,
        fake_redis: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """cleanup_completed_jobs should delete jobs in terminal states."""
        import time

        monkeypatch.setenv("ULTIMA_JOB_TASK_ARCHIVE_BATCH_SIZE", "500")

        # Seed a completed job whose index score is old enough
        job_id = "job-cleanup-1"
        old_ts = time.time() - 3 * 3600  # 3 hours ago
        await fake_redis.zadd(storage.JOB_INDEX_KEY, {job_id: old_ts})

        # Minimal state hash
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        completed_at = "2026-09-04T12:00:00+00:00"
        await fake_redis.hset(
            state_key,
            mapping={"status": "completed", "completed_at": completed_at},
        )

        # Seed config & task index so delete_job doesn't error
        config_key = storage.JOB_CONFIG_KEY.format(job_id=job_id)
        await fake_redis.set(config_key, json.dumps({"job_id": job_id}))
        task_index = storage.TASK_INDEX_KEY.format(job_id=job_id)
        await fake_redis.zadd(task_index, {"task-1": old_ts})
        task_key = storage.TASK_KEY.format(job_id=job_id, task_id="task-1")
        await fake_redis.set(task_key, json.dumps({"task_id": "task-1"}))

        archive_tasks = AsyncMock(return_value={"archived_tasks": 1})
        storage.database_writes = SimpleNamespace(
            max_command_bytes=64 * 1024 * 1024, submit=archive_tasks
        )

        deleted = await storage.cleanup_completed_jobs(max_age_seconds=7200)

        assert deleted == 1
        archive_tasks.assert_awaited_once()
        assert archive_tasks.await_args.args[1] == {
            "job_id": job_id,
            "batch_size": 500,
            "max_bytes": 64 * 1024 * 1024,
            "generation": completed_at,
            "task_definition_id": job_id,
            "archive_signature": ANY,
            "archive_header": True,
            "header_max_bytes": 64 * 1024 * 1024,
        }
        # Job should be gone from the index
        assert await fake_redis.zscore(storage.JOB_INDEX_KEY, job_id) is None
        # State hash should be gone
        assert await fake_redis.exists(state_key) == 0

    @pytest.mark.asyncio
    async def test_cleanup_skips_running_jobs(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """cleanup_completed_jobs should NOT delete running jobs."""
        import time

        job_id = "job-cleanup-running"
        old_ts = time.time() - 3 * 3600
        await fake_redis.zadd(storage.JOB_INDEX_KEY, {job_id: old_ts})
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        await fake_redis.hset(state_key, mapping={"status": "running"})

        deleted = await storage.cleanup_completed_jobs(max_age_seconds=7200)
        assert deleted == 0
        # Job should still be in the index
        assert await fake_redis.zscore(storage.JOB_INDEX_KEY, job_id) is not None

    @pytest.mark.asyncio
    async def test_cleanup_removes_dangling_index_entries(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """Entries in JOB_INDEX that have no state hash should be cleaned."""
        import time

        job_id = "job-cleanup-dangling"
        old_ts = time.time() - 3 * 3600
        await fake_redis.zadd(storage.JOB_INDEX_KEY, {job_id: old_ts})
        # No state hash — simulates expired state

        deleted = await storage.cleanup_completed_jobs(max_age_seconds=7200)
        assert deleted == 1
        assert await fake_redis.zscore(storage.JOB_INDEX_KEY, job_id) is None

    @pytest.mark.asyncio
    async def test_cleanup_respects_max_age(
        self, storage: Any, fake_redis: Any
    ) -> None:
        """Jobs newer than max_age_seconds should be kept."""
        import time

        job_id = "job-cleanup-recent"
        recent_ts = time.time() - 60  # 1 minute ago
        await fake_redis.zadd(storage.JOB_INDEX_KEY, {job_id: recent_ts})
        state_key = storage.JOB_STATE_KEY.format(job_id=job_id)
        await fake_redis.hset(state_key, mapping={"status": "completed"})

        deleted = await storage.cleanup_completed_jobs(max_age_seconds=7200)
        assert deleted == 0
        assert await fake_redis.zscore(storage.JOB_INDEX_KEY, job_id) is not None


async def test_runtime_telemetry_omits_unreached_drain_boundary(storage: Any):
    job_id = "running-boundaries"
    key = storage.JOB_RUNTIME_TELEMETRY_KEY.format(job_id=job_id)
    await storage._client().hset(key, mapping={
        "task_count": 5, "first_started_ms": 1000, "last_finished_ms": 6000,
        "steady_first_finished_ms": 2000,
    })
    telemetry = await storage.get_job_runtime_telemetry(job_id)
    assert telemetry["ramp_window_ms"] == 1000
    assert telemetry["drain_window_ms"] is None
    await storage._client().hset(key, "steady_last_finished_ms", 5000)
    telemetry = await storage.get_job_runtime_telemetry(job_id)
    assert telemetry["drain_window_ms"] == 1000


async def test_guest_auth_telemetry_aggregates_without_extra_redis_calls(storage: Any):
    await storage.record_task_runtime_telemetry("guest-auth-detail", started_ms=1000, finished_ms=2000,
        queue_wait_ms=0, setup_ms=0, handler_ms=1000, writer_ms=0, post_ms=0, release_ms=0,
        success=True, route_active_ms=0, route_attempts=0, guest_auth_stats_json='{"lock_wait":{"ms":30,"count":2},"cache_hit":{"ms":0,"count":1}}')
    metrics = await storage.get_job_runtime_telemetry("guest-auth-detail")
    assert metrics["guest_auth_stats"]["lock_wait"] == {"ms": 30, "count": 2}
    assert metrics["guest_auth_stats"]["cache_hit"]["count"] == 1


@pytest.mark.asyncio
async def test_route_selection_telemetry_aggregates(storage):
    stats = {"direct": {"route_attempts":1,"lookup_observations":1,"lookup_found_count":1,"primary_selected_count":1,"healthy_selected_count":1,"retry_selected_count":1}}
    import json
    for _ in range(2):
        await storage.record_task_runtime_telemetry("route-selection-fixture", started_ms=1000, finished_ms=2000, queue_wait_ms=0, setup_ms=0, handler_ms=1000, writer_ms=0, post_ms=0, release_ms=0, success=True, route_active_ms=1000, route_attempts=1, route_lookup_stats_json=json.dumps(stats))
    metrics = await storage.get_job_runtime_telemetry("route-selection-fixture")
    route = metrics["route_lookup_stats"]["direct"]
    assert route["primary_selected_count"] == 2
    assert route["healthy_selected_count"] == 2
    assert route["retry_selected_count"] == 2
    assert route["deferred_selected_count"] == 0


async def test_terminal_timing_aggregates(storage):
    await storage.record_task_runtime_telemetry("terminal-timing", started_ms=1000, finished_ms=2000,
        queue_wait_ms=0, setup_ms=0, handler_ms=500, writer_ms=0, post_ms=300, release_ms=0,
        success=True, route_active_ms=0, route_attempts=0,
        terminal_stats_json='{"before_counter":{"ms":100,"count":1},"counter_transition":{"ms":200,"count":1}}')
    metrics = await storage.get_job_runtime_telemetry("terminal-timing")
    assert metrics["terminal_stats"]["counter_transition"] == {"ms":200,"count":1}


async def test_ledger_timing_aggregates_without_additional_phase_time(storage):
    for _ in range(2):
        await storage.record_task_runtime_telemetry(
            "ledger-detail", started_ms=1000, finished_ms=2000,
            queue_wait_ms=0, setup_ms=0, handler_ms=500, writer_ms=100,
            post_ms=300, release_ms=0, success=True,
            route_active_ms=0, route_attempts=0,
            ledger_stats_json=json.dumps({
                "writer_prepare": {"ms": 60, "count": 1},
                "writer_prepare_execution": {"ms": 20, "count": 1},
                "writer_prepare_admission": {"ms": 40, "count": 1},
            }),
        )
    metrics = await storage.get_job_runtime_telemetry("ledger-detail")
    assert metrics["ledger_stats"]["writer_prepare"] == {"ms": 120, "count": 2}
    assert metrics["ledger_stats"]["writer_prepare_admission"] == {"ms": 80, "count": 2}
    assert metrics["mean_task_duration_ms"] == 1000
    assert metrics["mean_handler_exclusive_ms"] == 400
