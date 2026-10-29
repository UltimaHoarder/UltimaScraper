#!/usr/bin/env python3
"""Validate the explicit USR scrape-worker runtime and its Redis heartbeats."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import psutil
from redis import Redis


def _redis_password() -> str | None:
    direct = os.environ.get("REDIS_PASSWORD", "")
    secret_file = os.environ.get("REDIS_PASSWORD_FILE", "")
    if direct and secret_file:
        raise RuntimeError("Set only REDIS_PASSWORD or REDIS_PASSWORD_FILE")
    if not secret_file:
        return direct or None

    value = Path(secret_file).read_text(encoding="utf-8").strip()
    if not value:
        return None
    return value


def _read_readiness() -> dict:
    path = Path(
        os.environ.get(
            "USR_WORKER_READINESS_FILE", "/dev/shm/usr-worker-readiness.json"
        )
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    age = time.monotonic() - float(payload["updated_monotonic"])
    if payload["version"] != 1 or not 0 <= age <= 45:
        raise ValueError("Worker readiness is stale or incompatible")
    process = psutil.Process(int(payload["pid"]))
    if (
        not process.is_running()
        or process.status() == psutil.STATUS_ZOMBIE
        or abs(process.create_time() - float(payload["process_started"])) > 0.01
    ):
        raise ValueError("Worker parent identity changed")
    expected = payload["expected_workers"]
    ids = payload["worker_ids"]
    if (
        type(expected) is not int
        or expected < 0
        or not isinstance(ids, list)
        or any(not isinstance(v, str) or not v for v in ids)
        or len(ids) != len(set(ids))
    ):
        raise ValueError("Invalid worker readiness")
    return payload


def _active_worker_count(readiness: dict) -> int:
    redis = Redis(
        host=os.environ["REDIS_HOST"],
        port=int(os.environ.get("REDIS_PORT", "6379")),
        db=int(os.environ.get("REDIS_DB", "0")),
        password=_redis_password(),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        worker_ids = readiness["worker_ids"]
        pipeline = redis.pipeline(transaction=False)
        pipeline.ping()
        pipeline.smembers(f"ultimascraper:backend:{readiness['backend_id']}:workers")
        for worker_id in worker_ids:
            pipeline.exists(f"ultimascraper:workers:{worker_id}")
            pipeline.exists(f"ultimascraper:workers:heartbeat:{worker_id}")
        results = pipeline.execute()
        if not results[0]:
            raise ConnectionError("Redis ping failed")
        members = results[1]
        return sum(
            worker_id in members
            and bool(results[2 + i * 2])
            and bool(results[3 + i * 2])
            for i, worker_id in enumerate(worker_ids)
        )
    finally:
        redis.close()


def main() -> None:
    if (
        os.environ.get("USR_CONTAINER_ROLE") != "worker"
        or os.environ.get("RUN_MODE") != "worker"
    ):
        raise SystemExit("USR worker image role is invalid")
    try:
        readiness = _read_readiness()
        expected_workers = readiness["expected_workers"]
        active_workers = _active_worker_count(readiness)
    except Exception as exc:
        raise SystemExit("USR worker Redis heartbeat check failed") from exc
    if active_workers < expected_workers:
        raise SystemExit("USR worker Redis heartbeats are incomplete")


if __name__ == "__main__":
    main()
