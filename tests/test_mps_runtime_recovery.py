"""MPS commit/restart boundaries over real Redis and a separate SQL writer.

Requires USR_TEST_WITH_POSTGRES=1. All processes, schemas, Redis state and
configuration belong to disposable fixtures; no deployment endpoint is accepted.
"""

from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import pytest
import redis as sync_redis
from sqlalchemy import text

from test_content_write_resources import content_engine, postgres_engine

__all__ = ["content_engine", "postgres_engine"]


def test_million_profile_manifest_recovers_across_process_and_redis_loss(
    content_engine,
    tmp_path,
):
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig
    from ultima_scraper_backend.database.mps_manifest import mps_task_id
    from ultima_scraper_backend.database.write_queue import (
        DatabaseWriteClient,
        DatabaseWriterService,
    )
    from ultima_scraper_backend.job_system import JobStorage, mps_state
    from ultima_scraper_db_archive.global_db import SettingsModel

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    scope = "mps-runtime-" + uuid4().hex
    env = {
        "PATH": os.environ["PATH"],
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "ULTIMA_ARCHIVE_DATABASE_URL": content_engine.url.render_as_string(
            hide_password=False
        ),
        "ULTIMA_USE_PGBOUNCER": "0",
        "ULTIMA_ENABLE_RUNTIME_SCHEMA_SYNC": "0",
        "BACKEND_ID": scope,
        "IS_SETUP": "true",
        "REDIS_URL": f"redis://127.0.0.1:{port}/0",
        "REDIS_ENABLED": "true",
        "ULTIMA_JOB_WINDOW_MAX_TASKS": "8",
        "ULTIMA_JOB_WINDOW_MAX_BYTES": "65536",
        "ULTIMA_JOB_GLOBAL_WINDOW_MAX_TASKS": "8",
        "ULTIMA_JOB_GLOBAL_WINDOW_MAX_BYTES": "65536",
    }
    for key, directory in {
        "XDG_CONFIG_HOME": "config",
        "XDG_CACHE_HOME": "cache",
        "XDG_DATA_HOME": "data",
        "XDG_STATE_HOME": "state",
        "TMPDIR": "tmp",
        "LOG_ROOT": "logs",
        "USR_LOG_DIR": "runtime-logs",
        "USR_PLUGINS_DIR": "plugins",
    }.items():
        path = tmp_path / directory
        path.mkdir()
        env[key] = str(path)
    config = UltimaScraperCollectionConfig()
    with content_engine.begin() as connection:
        connection.execute(
            SettingsModel.__table__.insert().values(
                backend=scope,
                key="config",
                value=json.dumps(config.persistence_payload()),
            )
        )

    command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        "-c",
        "import sys,runpy; sys.path[:]=%r; runpy.run_path(%r,run_name='__main__')"
        % (
            sys.path,
            str(Path(__file__).with_name("mps_runtime_process.py")),
        ),
    ]
    processes = []

    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    with ExitStack() as cleanup:
        client = sync_redis.Redis(host="127.0.0.1", port=port, decode_responses=True)
        cleanup.callback(client.close)

        def start_redis():
            log = cleanup.enter_context(
                (tmp_path / f"redis-{len(processes)}.log").open("w")
            )
            process = subprocess.Popen(
                [
                    "redis-server",
                    "--bind",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--dir",
                    str(tmp_path),
                    "--save",
                    "",
                    "--appendonly",
                    "no",
                    "--maxmemory",
                    "64mb",
                    "--maxmemory-policy",
                    "noeviction",
                ],
                env=env,
                stdout=log,
                stderr=log,
            )
            processes.append(process)
            cleanup.callback(stop, process)
            wait_for(lambda: client.ping(), timeout=10)
            return process

        def start(action, *, output=None, **extra):
            log = cleanup.enter_context(
                (tmp_path / f"{action}-{len(processes)}.log").open("w")
            )
            process = subprocess.Popen(
                command,
                env={
                    **env,
                    "MPS_FIXTURE_ACTION": action,
                    "MPS_FIXTURE_OUTPUT": str(output or tmp_path / "unused.json"),
                    **extra,
                },
                cwd=tmp_path,
                stdout=log,
                stderr=log,
            )
            processes.append(process)
            cleanup.callback(stop, process)
            return process

        def run(action, *, output, **extra):
            process = start(action, output=output, **extra)
            assert process.wait(timeout=45) == 0, f"See {tmp_path}/{action}-*.log"
            return json.loads(output.read_text())

        def window():
            return client.zrange(JobStorage.TASK_INDEX_KEY.format(job_id=job_id), 0, -1)

        def snapshot():
            with content_engine.connect() as connection:
                return connection.execute(
                    text(
                        "SELECT cursor,completed,failed,total FROM management.mps_plans WHERE job_id=:id"
                    ),
                    {"id": job_id},
                ).one()

        def check_window(start):
            expected = [
                mps_task_id(job_id, ordinal, 1000 + ordinal)
                for ordinal in range(start, start + 8)
            ]
            return window() == expected

        redis_process = start_redis()
        writer = start("writer")
        plan = run("submit", output=tmp_path / "plan.json")
        job_id = plan["job_id"]
        env["MPS_FIXTURE_JOB_ID"] = job_id
        assert plan["total"] == 1_000_000 and plan["cursor"] == 0
        with content_engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM management.mps_candidate_ranges WHERE job_id=:id"
                    ),
                    {"id": job_id},
                ).scalar_one()
                == 1
            )
        committed = tmp_path / "committed.json"
        materializer = start(
            "materializer", output=committed, MPS_FIXTURE_PAUSE_AFTER_COMMIT="1"
        )
        wait_for(lambda: check_window(0), timeout=25)
        assert int(client.hget(mps_state.BUDGET_KEY, "tasks")) == 8
        assert client.dbsize() < 100
        # A restored/recreated Redis stream can also lose its consumer group
        # while the connection remains open. The writer must recreate it.
        assert client.xgroup_destroy(
            DatabaseWriteClient.STREAM_KEY, DatabaseWriterService.CONSUMER_GROUP
        )
        wait_for(
            lambda: bool(client.xinfo_groups(DatabaseWriteClient.STREAM_KEY)),
            timeout=15,
        )
        assert writer.poll() is None
        assert (
            run("complete", output=tmp_path / "complete-first.json")["completed"] == 8
        )
        wait_for(committed.exists, timeout=25)
        committed_count = snapshot()[0]
        assert 0 < committed_count <= 8
        assert snapshot() == (committed_count, committed_count, 0, 1_000_000)
        assert check_window(0)  # Commit occurred before Redis purge.
        materializer.kill()
        materializer.wait(timeout=5)
        materializer = start("materializer")
        # The unmodified production materializer lease expires after 90 seconds.
        # Wait for normal lock recovery rather than deleting a live lease.
        wait_for(lambda: check_window(8), timeout=120)
        assert snapshot() == (8, 8, 0, 1_000_000)
        assert writer.poll() is None

        # Replace only this test's nonpersistent Redis process with an empty one.
        # Keep SQL evidence and both application processes running.
        stop(redis_process)
        redis_process = start_redis()
        wait_for(lambda: check_window(8), timeout=35)
        assert snapshot() == (8, 8, 0, 1_000_000)
        assert materializer.poll() is None and writer.poll() is None
        assert (
            run("complete", output=tmp_path / "complete-second.json")["completed"] == 8
        )
        wait_for(lambda: snapshot()[0] == 16, timeout=35)
        wait_for(lambda: check_window(16), timeout=25)
        assert snapshot() == (16, 16, 0, 1_000_000)
        assert int(client.hget(mps_state.BUDGET_KEY, "tasks")) == 8
        assert client.dbsize() < 100
        with content_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*),count(DISTINCT user_id),min(user_id),max(user_id) "
                    "FROM management.job_tasks WHERE job_id=:id"
                ),
                {"id": job_id},
            ).one() == (16, 16, 1000, 1015)


def wait_for(predicate, *, timeout):
    deadline = time.monotonic() + timeout
    while True:
        try:
            if predicate():
                return
        except (sync_redis.exceptions.ConnectionError, OSError):
            pass
        if time.monotonic() >= deadline:
            pytest.fail(f"Timed out after {timeout}s waiting for fixture state")
        time.sleep(0.1)
