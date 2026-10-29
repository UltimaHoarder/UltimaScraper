"""Owned native-service startup measurement. No deployment inputs accepted."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import site
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(os.environ.get("USR_BENCH_REPO", "/srv/usr/project/UltimaScraper"))
site.addsitedir(str(REPO / ".venv/lib/python3.14/site-packages"))
sys.path.insert(0, str(REPO))

import psutil
import redis
from mixed import MixedWork, redis_retained_state, seed_catalog
from sqlalchemy import create_engine, text
from workload import (
    PlatformHandler,
    network_metrics,
    progress,
    reset_live_media,
    submit,
    verify,
    verify_live_cycle,
)


class RulesHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(
            {
                "static_param": "fixture",
                "format": "{}:{}",
                "checksum_indexes": [0],
                "checksum_constants": [0],
                "checksum_constant": 0,
                "app_token": "fixture",
                "remove_headers": [],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def initialize_fixture_schema(connection):
    """Prepare the current runtime schema in this case's fresh, owned database."""
    from ultima_scraper_backend.plugin_system.repository import SCHEMA_VERSION
    from ultima_scraper_db_archive import execution_models, plugin_models  # noqa: F401
    from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates import (
        postgres_site,
    )

    for schema in ("onlyfans", "management", "fansly"):
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    connection.execute(text("CREATE EXTENSION pg_trgm WITH SCHEMA public"))
    for site_name in ("onlyfans", "fansly"):
        connection.execute(text(f"SET LOCAL search_path={site_name},management,public"))
        postgres_site.Base.metadata.create_all(connection)
    # create_all registers tables, but migration-owned data must also be seeded.
    connection.execute(
        plugin_models.plugin_repository_meta.insert().values(
            key="schema_version", value=str(SCHEMA_VERSION)
        )
    )


def stop(process, *, signum=signal.SIGTERM, timeout=40):
    if process.poll() is None:
        process.send_signal(signum)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Only descendants of the exact Popen instance belong to this run.
            children = psutil.Process(process.pid).children(recursive=True)
            for child in reversed(children):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            process.kill()
            process.wait(timeout=5)


def memory(roots):
    rows = []
    seen = set()
    for role, root in roots:
        if root.poll() is not None:
            continue
        try:
            parent = psutil.Process(root.pid)
            processes = [parent, *parent.children(recursive=True)]
        except psutil.NoSuchProcess:
            continue
        for process in processes:
            if process.pid in seen:
                continue
            seen.add(process.pid)
            try:
                info = process.memory_full_info()
                cpu = process.cpu_times()
                rows.append(
                    {
                        "role": role,
                        "pid": process.pid,
                        "ppid": process.ppid(),
                        "name": process.name(),
                        "rss": info.rss,
                        "pss": info.pss,
                        "uss": info.uss,
                        "cpu_seconds": cpu.user + cpu.system,
                        "threads": process.num_threads(),
                    }
                )
            except psutil.NoSuchProcess:
                pass
    return rows


def memory_group():
    relative = next(
        line.split(":", 2)[2]
        for line in Path("/proc/self/cgroup").read_text().splitlines()
        if line.startswith("0::")
    )
    return Path("/sys/fs/cgroup") / relative.lstrip("/")


def group_sample(group):
    value = {"path": str(group)}
    for name in (
        "memory.current",
        "memory.peak",
        "memory.max",
        "memory.swap.current",
        "memory.swap.max",
        "memory.oom.group",
    ):
        raw = (group / name).read_text().strip()
        value[name] = int(raw) if raw.isdigit() else raw
    for name in ("memory.events", "memory.stat", "cpu.stat"):
        value[name] = {
            key: int(number)
            for key, number in (
                line.split() for line in (group / name).read_text().splitlines()
            )
        }
    for pressure in ("memory", "cpu", "io"):
        value[f"{pressure}.pressure"] = (
            (group / f"{pressure}.pressure").read_text().strip()
        )
    value["guest_meminfo"] = {
        line.split(":", 1)[0]: int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.endswith("kB")
    }
    value["guest_vmstat"] = {
        key: int(amount)
        for key, amount in (
            line.split() for line in Path("/proc/vmstat").read_text().splitlines()
        )
        if key in {"pswpin", "pswpout", "pgmajfault", "oom_kill"}
    }
    disk = Path("/sys/block/vdb/stat")
    value["guest_data_disk_stat"] = disk.read_text().strip() if disk.exists() else None
    io_path = group / "io.stat"
    value["io.stat"] = io_path.read_text().strip() if io_path.exists() else None
    return value


def observer_failures(output):
    """Read bounded log tails; failure reporting must preserve the exception."""
    failures = {}
    for name in ("mixed", "dashboard", "websocket"):
        path = output / f"{name}.jsonl"
        if not path.exists():
            continue
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 128 * 1024))
            lines = stream.read().splitlines()
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except ValueError, UnicodeDecodeError:
                continue
            if isinstance(row, dict) and "error" in row:
                failures[name] = row
                break
    return failures


def run(args):
    live = args.workload == "guest-onlyfans"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    memory_cgroup = memory_group()
    initial_group = group_sample(memory_cgroup)
    if args.require_memory_max_bytes is not None:
        assert initial_group["memory.max"] == args.require_memory_max_bytes, (
            initial_group
        )
        assert initial_group["memory.swap.max"] == 0, initial_group
        assert initial_group["memory.oom.group"] == 1, initial_group
    (output / "initial-cgroup.json").write_text(
        json.dumps(initial_group, indent=2) + "\n"
    )
    with ExitStack() as stack:
        root = Path(
            stack.enter_context(
                tempfile.TemporaryDirectory(prefix=".usr-bench-", dir=args.data_parent)
            )
        )
        (output / "owned-root.txt").write_text(str(root) + "\n")

        def archive_logs():
            for name in ("logs", "runtime-logs", "metrics"):
                if (root / name).exists():
                    shutil.copytree(root / name, output / name)

        stack.callback(archive_logs)
        redis_port, control_port = free_port(), free_port()
        PlatformHandler.files = args.files
        PlatformHandler.body = (bytes(range(256)) * ((args.media_bytes + 255) // 256))[
            : args.media_bytes
        ]
        PlatformHandler.delay = args.response_delay
        rules = ThreadingHTTPServer(("127.0.0.1", 0), PlatformHandler)
        stack.callback(rules.server_close)
        thread = threading.Thread(target=rules.serve_forever, daemon=True)
        thread.start()
        stack.callback(rules.shutdown)

        # Environment-first isolation, including configuration discovery and
        # all relative application output. No inherited URLs, tokens or proxies.
        env = {
            "PATH": os.environ["PATH"],
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
        for var, dirname in {
            "XDG_CONFIG_HOME": "config",
            "XDG_CACHE_HOME": "cache",
            "XDG_DATA_HOME": "data",
            "XDG_STATE_HOME": "state",
            "TMPDIR": "tmp",
            "LOG_ROOT": "logs",
            "USR_LOG_DIR": "runtime-logs",
            "USR_PLUGINS_DIR": "plugins",
            "FIXTURE_READY_DIR": "ready",
            "FIXTURE_METRICS_DIR": "metrics",
        }.items():
            path = root / dirname
            path.mkdir()
            env[var] = str(path)
        url = f"postgresql+psycopg://usr_test@/postgres?host={root}"
        env.update(
            ULTIMA_ARCHIVE_DATABASE_URL=url,
            ULTIMA_USE_PGBOUNCER="0",
            ULTIMA_ENABLE_RUNTIME_SCHEMA_SYNC="0",
            USR_EXPECTED_DATABASE="postgres",
            REDIS_URL=f"redis://127.0.0.1:{redis_port}/0",
            REDIS_ENABLED="true",
            BACKEND_ID="runtime-fixture",
            IS_SETUP="true",
            CONTROL_HOST="127.0.0.1",
            CONTROL_PORT=str(control_port),
            CONTROL_WORKERS=str(args.control_workers),
            CONTROL_STARTUP_TIMEOUT=str(args.startup_timeout_seconds),
            USR_ADMIN_TOKEN_REQUIRED="true",
            USR_ADMIN_TOKEN="fixture-local-only",
            USR_ENCRYPT_SECRETS="false",
            FIXTURE_PLATFORM_URL=f"http://127.0.0.1:{rules.server_port}",
            USR_BENCH_REPO=str(REPO),
            USR_BENCH_WORKLOAD=args.workload,
            USR_BENCH_DIAGNOSTICS="1" if args.diagnostics else "0",
            ULTIMA_CONTENT_BATCH_SIZE=str(args.batch_size),
            ULTIMA_DOWNLOAD_BATCH_SIZE=str(args.batch_size),
            ULTIMA_TASK_RESULT_PREVIEW_MAX_ENTRIES="2",
            ULTIMA_TASK_RESULT_PREVIEW_MAX_BYTES="4096",
            FIXTURE_ALLOWED_PORTS=",".join(
                map(str, [redis_port, control_port, rules.server_port])
            ),
        )
        for field, variable in (
            ("retention_seconds", "USR_COMPLETED_JOB_RETENTION_SECONDS"),
            ("retention_batch_size", "USR_COMPLETED_JOB_RETENTION_BATCH_SIZE"),
            (
                "reconcile_interval_seconds",
                "USR_TERMINAL_JOB_RECONCILE_INTERVAL_SECONDS",
            ),
        ):
            value = getattr(args, field)
            if value is not None:
                env[variable] = str(value)
        os.environ.clear()
        os.environ.update(env)
        os.chdir(root)
        subprocess.run(
            [
                "initdb",
                "-D",
                str(root / "pgdata"),
                "-U",
                "usr_test",
                "--auth-local=trust",
                "--auth-host=reject",
                "--no-locale",
                "-E",
                "UTF8",
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        pglog = stack.enter_context((output / "postgres.log").open("w"))
        pg = subprocess.Popen(
            [
                "postgres",
                "-D",
                str(root / "pgdata"),
                "-k",
                str(root),
                "-h",
                "",
                "-c",
                f"shared_buffers={args.shared_buffers_mb}MB",
            ],
            env=env,
            stdout=pglog,
            stderr=pglog,
        )
        stack.callback(
            stop, pg, signum=signal.SIGINT, timeout=args.checkpoint_timeout_seconds
        )
        engine = create_engine(url)
        stack.callback(engine.dispose)
        deadline = time.monotonic() + 120
        while True:
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                break
            except Exception:
                if pg.poll() is not None or time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

        from ultima_scraper_backend.config import Drive, UltimaScraperCollectionConfig
        from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates import (
            postgres_site,
        )

        config = UltimaScraperCollectionConfig()
        config.settings.hostname = "runtime-fixture"
        config.settings.backend.backend_id = "runtime-fixture"
        config.settings.worker_pool.size = args.workers
        config.settings.worker_pool.sites = ["onlyfans"]
        config.settings.network.downloads.max_file_concurrency = args.file_concurrency
        config.settings.network.downloads.max_concurrency = args.part_concurrency
        config.settings.network.downloads.per_domain_concurrency = max(
            config.settings.network.downloads.per_domain_concurrency,
            args.file_concurrency,
        )
        if not live:
            config.site_apis.onlyfans.dynamic_rules_url = (
                f"http://127.0.0.1:{rules.server_port}/rules"
            )
        for setup in (config.settings.download_setup, config.settings.metadata_setup):
            setup.drives = [Drive(directories=[root / "media"])]
        (output / "settings.json").write_text(
            json.dumps(config.persistence_payload(), indent=2) + "\n"
        )
        (root / "media").mkdir()
        with engine.begin() as connection:
            initialize_fixture_schema(connection)
            connection.execute(
                postgres_site.SettingsModel.__table__.insert().values(
                    backend="runtime-fixture",
                    key="config",
                    value=json.dumps(config.persistence_payload()),
                )
            )
            connection.execute(text("SET LOCAL search_path=onlyfans,management,public"))
            if not live:
                connection.execute(
                    postgres_site.UserModel.__table__.insert().values(
                        id=99, username="fixture-buyer"
                    )
                )
                connection.execute(
                    postgres_site.UserAuthModel.__table__.insert().values(
                        site="onlyfans",
                        user_id=99,
                        username="fixture-buyer",
                        cookie="auth_id=99; sess=fixture;",
                        x_bc="fixture",
                        user_agent="Owned-runtime-fixture",
                        active=True,
                        status="valid",
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO users(id,username,performer) SELECT id, 'performer' || id, true FROM generate_series(1000,:last) id"
                    ),
                    {"last": 999 + args.profiles},
                )
            else:
                # The live guest lookup confirmed this platform identity. Posts
                # writes need a performer FK, as in an already-added USR profile.
                # The worker independently resolves/validates the name again.
                connection.execute(
                    postgres_site.UserModel.__table__.insert().values(
                        id=15585607, username="onlyfans", performer=True
                    )
                )
        catalog = seed_catalog(
            engine, args, root, output, rules.server_port, group_sample, memory_cgroup
        )
        assert catalog["database_bytes"] >= args.minimum_catalog_bytes, catalog
        redislog = stack.enter_context((output / "redis.log").open("w"))
        rp = subprocess.Popen(
            [
                "redis-server",
                "--bind",
                "127.0.0.1",
                "--port",
                str(redis_port),
                "--save",
                "",
                "--appendonly",
                args.redis_aof,
                "--dir",
                str(root),
                "--maxmemory-policy",
                "noeviction",
            ],
            env=env,
            stdout=redislog,
            stderr=redislog,
        )
        stack.callback(stop, rp, timeout=10)
        client = redis.Redis(host="127.0.0.1", port=redis_port, decode_responses=True)
        stack.callback(client.close)
        deadline = time.monotonic() + 120
        while True:
            try:
                client.ping()
                break
            except redis.exceptions.ConnectionError:
                if rp.poll() is not None or time.monotonic() > deadline:
                    raise
                time.sleep(0.05)

        roots = [("postgres", pg), ("redis", rp)]
        started = time.monotonic()
        for role in ("api", "worker"):
            log = stack.enter_context((output / f"{role}.log").open("w"))
            process = subprocess.Popen(
                [sys.executable, "-S", "-B", str(Path(__file__).with_name("entry.py"))],
                env={**env, "RUN_MODE": role},
                cwd=root,
                stdout=log,
                stderr=log,
            )
            roots.append((role, process))
            stack.callback(stop, process)

        (output / "services.json").write_text(
            json.dumps(
                {
                    "root": str(root),
                    "cgroup": str(memory_cgroup),
                    "redis_port": redis_port,
                    "control_port": control_port,
                    "platform_port": rules.server_port,
                    "pids": {role: process.pid for role, process in roots},
                },
                indent=2,
            )
            + "\n"
        )
        mixed = MixedWork(
            engine,
            client,
            control_port,
            output,
            statistics_interval=args.statistics_interval,
            maintenance_interval=args.maintenance_interval,
            checkpoint_timeout_seconds=args.checkpoint_timeout_seconds,
        )
        stack.callback(mixed.stop)
        from dashboard import DashboardObserver

        dashboard = DashboardObserver(control_port, output, mixed.started_event)
        stack.callback(dashboard.stop)
        from events import EventObserver

        events = EventObserver(control_port, output, mixed.started_event)
        stack.callback(events.stop)
        ready_at = None
        workload_at = None
        finished_at = None
        job_ids = []
        active_jobs = set()
        complete_jobs = set()
        live_files_verified = 0
        live_bytes_verified = 0
        retention_checkpoint = 0
        admission_stop = None
        low_headroom_since = None
        last_task_progress = time.monotonic()
        peak = {}
        last_rows = []
        health_body = None
        with (output / "samples.jsonl").open("w") as samples:
            while True:
                now = time.monotonic()
                for role, process in roots:
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"{role} exited with {process.returncode}; see {output}/{role}.log"
                        )
                if events.errors:
                    raise RuntimeError(f"Dashboard socket failed: {events.errors}")
                if mixed.errors:
                    raise RuntimeError(f"Mixed-work fixture failed: {mixed.errors}")
                disk_free = shutil.disk_usage(root).free
                if disk_free < args.minimum_free_bytes and admission_stop is None:
                    admission_stop = {
                        "reason": "disk_reserve",
                        "elapsed": now - started,
                        "free_bytes": disk_free,
                        "reserve_bytes": args.minimum_free_bytes,
                        "active_jobs": sorted(active_jobs),
                        "active_http": PlatformHandler.active,
                    }
                    (output / "admission-stop.json").write_text(
                        json.dumps(admission_stop, indent=2) + "\n"
                    )
                    print(
                        json.dumps(dict(event="admission_stopped", **admission_stop)),
                        flush=True,
                    )
                available = psutil.virtual_memory().available
                if (
                    workload_at is not None
                    and now - workload_at >= args.warmup_seconds
                    and available < args.minimum_available_bytes
                ):
                    if low_headroom_since is None:
                        low_headroom_since = now
                    if (
                        now - low_headroom_since >= args.low_headroom_seconds
                        and admission_stop is None
                    ):
                        admission_stop = {
                            "reason": "os_headroom",
                            "elapsed": now - started,
                            "available_bytes": available,
                            "minimum_bytes": args.minimum_available_bytes,
                            "low_seconds": now - low_headroom_since,
                            "active_jobs": sorted(active_jobs),
                        }
                        (output / "admission-stop.json").write_text(
                            json.dumps(admission_stop, indent=2) + "\n"
                        )
                        print(
                            json.dumps(
                                dict(event="admission_stopped", **admission_stop)
                            ),
                            flush=True,
                        )
                else:
                    low_headroom_since = None
                rows = memory(roots)
                last_rows = rows
                totals = {}
                for role in ("api", "worker", "postgres", "redis"):
                    group = [row for row in rows if row["role"] == role]
                    totals[role] = {
                        key: sum(row[key] for row in group)
                        for key in ("rss", "pss", "uss", "cpu_seconds", "threads")
                    }
                    totals[role]["processes"] = len(group)
                    peak[role] = max(peak.get(role, 0), totals[role]["pss"])
                with engine.connect() as connection:
                    sessions = connection.execute(
                        text(
                            "SELECT state,count(*) FROM pg_stat_activity WHERE backend_type='client backend' GROUP BY state"
                        )
                    ).all()
                    database_stats = dict(
                        connection.execute(
                            text(
                                "SELECT xact_commit,xact_rollback,blks_read,blks_hit,tup_returned,tup_fetched,tup_inserted,tup_updated,tup_deleted,temp_files,temp_bytes,deadlocks FROM pg_stat_database WHERE datname=current_database()"
                            )
                        )
                        .one()
                        ._mapping
                    )
                    if args.diagnostics:
                        activity = [
                            dict(row._mapping)
                            for row in connection.execute(
                                text(
                                    "SELECT pid,state,wait_event_type,wait_event,"
                                    "EXTRACT(EPOCH FROM now()-query_start) AS query_seconds,"
                                    "EXTRACT(EPOCH FROM now()-xact_start) AS transaction_seconds,"
                                    "left(query,2000) AS query FROM pg_stat_activity "
                                    "WHERE backend_type='client backend' AND pid<>pg_backend_pid()"
                                )
                            )
                        ]
                        with (output / "postgres-activity.jsonl").open(
                            "a"
                        ) as activity_log:
                            activity_log.write(
                                json.dumps(
                                    {
                                        "monotonic": time.monotonic(),
                                        "activity": activity,
                                    },
                                    default=str,
                                )
                                + "\n"
                            )
                first_queued = client.xrange("ultimascraper:database:writes", count=1)
                oldest_queue_age_ms = (
                    max(
                        0,
                        int(time.time() * 1000) - int(first_queued[0][0].split("-")[0]),
                    )
                    if first_queued
                    else 0
                )
                current_traffic = network_metrics(root / "metrics") if live else None
                item = {
                    "elapsed": now - started,
                    "phase": "drain"
                    if finished_at
                    else "workload"
                    if workload_at
                    else "idle"
                    if ready_at
                    else "startup",
                    "processes": rows,
                    "totals": totals,
                    "redis": client.info("memory"),
                    "cgroup": group_sample(memory_cgroup),
                    "postgres_sessions": {str(k): v for k, v in sessions},
                    "postgres_database": database_stats,
                    "jobs_submitted": len(job_ids),
                    "jobs_completed": len(complete_jobs),
                    "http_requests": PlatformHandler.requests,
                    "active_http": current_traffic["active_downloads"]
                    if live
                    else PlatformHandler.active,
                    "completed_downloads": current_traffic["real_downloads"]
                    if live
                    else PlatformHandler.requests,
                    "downloaded_bytes": current_traffic["downloaded_bytes"]
                    if live
                    else PlatformHandler.requests * len(PlatformHandler.body),
                    "queue_depth": client.xlen("ultimascraper:database:writes"),
                    "queue_bytes": int(
                        client.get("ultimascraper:database:writes:bytes") or 0
                    ),
                    "oldest_queue_age_ms": oldest_queue_age_ms,
                    "filesystem_free_bytes": disk_free,
                    "redis_persistence": client.info("persistence"),
                    "host_memory_available_bytes": available,
                }
                samples.write(json.dumps(item) + "\n")
                samples.flush()
                status = {
                    "phase": item["phase"],
                    "elapsed": item["elapsed"],
                    "jobs_completed": len(complete_jobs),
                    "jobs_submitted": len(job_ids),
                    "cgroup_memory": item["cgroup"]["memory.current"],
                    "cgroup_events": item["cgroup"]["memory.events"],
                    "redis_bytes": item["redis"]["used_memory"],
                    "queue_depth": item["queue_depth"],
                    "active_downloads": item["active_http"],
                    "completed_downloads": item["completed_downloads"],
                    "downloaded_bytes": item["downloaded_bytes"],
                    "guest_available_bytes": available,
                    "disk_free_bytes": disk_free,
                }
                temporary_status = output / "status.tmp"
                temporary_status.write_text(json.dumps(status) + "\n")
                temporary_status.replace(output / "status.json")
                if ready_at is None:
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{control_port}/api/v1/admin/health",
                            timeout=5,
                        ) as response:
                            health_body = json.load(response)
                        ready_files = list((root / "ready").iterdir())
                        if len(ready_files) == args.workers:
                            ready_at = now
                            print(
                                json.dumps(
                                    {
                                        "event": "ready",
                                        "seconds": now - started,
                                        "workers": args.workers,
                                    }
                                ),
                                flush=True,
                            )
                    except OSError, ValueError:
                        pass
                    if now - started > args.startup_timeout_seconds:
                        raise RuntimeError(
                            "Bootstrap deadline exceeded; see isolated process logs"
                        )
                elif workload_at is None and now - ready_at >= args.idle_seconds:
                    workload_at = now
                    mixed.started_event.set()
                elif workload_at is not None:
                    states = progress(engine, list(active_jobs))
                    for job_id, row in states.items():
                        if row["status"] in ("failed", "cancelled"):
                            raise RuntimeError(f"Owned job failed: {row}")
                        if row["status"] == "completed":
                            if live:
                                verified = verify_live_cycle(
                                    engine, root / "media", job_id, output=output
                                )
                                # Hashing can cross the admission deadline.
                                now = time.monotonic()
                                traffic = network_metrics(root / "metrics")
                                live_files_verified += verified["files_verified"]
                                live_bytes_verified += verified["bytes_verified"]
                                assert (
                                    traffic["real_downloads"] == live_files_verified
                                ), (
                                    "Already-downloaded skips cannot count as a sustained transfer",
                                    traffic,
                                )
                                with (output / "verified-cycles.jsonl").open(
                                    "a"
                                ) as cycles:
                                    cycles.write(json.dumps(verified) + "\n")
                                if (
                                    args.minimum_workload_seconds
                                    and now - workload_at
                                    < args.minimum_workload_seconds
                                ):
                                    reset_live_media(
                                        engine, root / "media", verified["user_id"]
                                    )
                            active_jobs.remove(job_id)
                            complete_jobs.add(job_id)
                            last_task_progress = now
                            print(
                                json.dumps(
                                    {
                                        "event": "job_completed",
                                        "jobs": len(complete_jobs),
                                        "seconds": now - workload_at,
                                    }
                                ),
                                flush=True,
                            )
                    if len(complete_jobs) >= retention_checkpoint:
                        with (output / "retained-redis.jsonl").open("a") as retained:
                            retained.write(
                                json.dumps(
                                    {
                                        "completed_jobs": len(complete_jobs),
                                        "elapsed": now - workload_at,
                                        "groups": redis_retained_state(client),
                                    }
                                )
                                + "\n"
                            )
                        retention_checkpoint = len(complete_jobs) + 10
                    while (
                        admission_stop is None
                        and len(active_jobs) < args.active_profiles
                        and len(job_ids) < args.profiles
                        and (
                            args.minimum_workload_seconds == 0
                            or now - workload_at < args.minimum_workload_seconds
                        )
                    ):
                        job_id = submit(
                            control_port, 1000 + len(job_ids), args.files, live=live
                        )
                        job_ids.append(job_id)
                        active_jobs.add(job_id)
                    if len(complete_jobs) == len(job_ids) and (
                        admission_stop is not None
                        or len(job_ids) == args.profiles
                        or (
                            args.minimum_workload_seconds > 0
                            and now - workload_at >= args.minimum_workload_seconds
                        )
                    ):
                        if finished_at is None:
                            finished_at = now
                        elif now - finished_at >= args.drain_seconds:
                            break
                    if now - workload_at > args.timeout_seconds:
                        raise RuntimeError(
                            f"Workload deadline exceeded; {len(complete_jobs)}/{args.profiles} complete"
                        )
                    if now - last_task_progress > args.stall_seconds:
                        print(
                            json.dumps(
                                {
                                    "event": "still_running",
                                    "active": states,
                                    "missing_platform_paths": sorted(
                                        PlatformHandler.missing
                                    ),
                                }
                            ),
                            flush=True,
                        )
                        last_task_progress = now
                if int(now - started) % 30 == 0:
                    print(
                        json.dumps(
                            {
                                "event": "sample",
                                "seconds": now - started,
                                "completed": len(complete_jobs),
                                "active_downloads": item["active_http"],
                                "completed_downloads": item["completed_downloads"],
                                "pss": sum(v["pss"] for v in totals.values()),
                                "missing_platform_paths": sorted(
                                    PlatformHandler.missing
                                ),
                            }
                        ),
                        flush=True,
                    )
                time.sleep(1)
        dashboard.stop()
        mixed.stop()
        assert not mixed.errors, mixed.errors
        events.stop()
        events_result = events.verify()
        dashboard_result = dashboard.verify()
        final_statistics = mixed.final_statistics()
        traffic = network_metrics(root / "metrics") if live else None
        if live:
            assert traffic["auths"] and all(
                row["guest"] for row in traffic["auths"].values()
            ), traffic
            assert len(traffic["performers"]) == 1 and all(
                row["username"].casefold() == "onlyfans"
                for row in traffic["performers"].values()
            ), traffic
            with engine.connect() as connection:
                attempts = dict(
                    connection.execute(
                        text(
                            "SELECT state,count(*) FROM management.execution_attempts GROUP BY state"
                        )
                    ).all()
                )
            assert attempts == {"completed": len(complete_jobs) * 2}, attempts
            verification = {
                "files_verified": live_files_verified,
                "bytes_verified": live_bytes_verified,
                "ledger_attempts": attempts,
                "stored_auths": 0,
                "network": traffic,
            }
        else:
            verification = verify(
                engine,
                root / "media",
                profiles=len(complete_jobs),
                files=args.files,
                body=PlatformHandler.body,
            )
        (output / "file-verification.json").write_text(
            json.dumps(verification, indent=2) + "\n"
        )
        from workload import verify_history

        verification["history"] = verify_history(control_port, job_ids)
        (output / "retained-redis-final.json").write_text(
            json.dumps(redis_retained_state(client), indent=2) + "\n"
        )
        assert not PlatformHandler.missing, PlatformHandler.missing
        target_met = (
            finished_at - workload_at >= args.minimum_workload_seconds
            if args.minimum_workload_seconds > 0
            else len(complete_jobs) == args.profiles
        )
        result = {
            "runtime_environment": {
                "architecture": os.uname().machine,
                "memory_total_bytes": psutil.virtual_memory().total,
            },
            "settings": {
                key: str(value) if isinstance(value, Path) else value
                for key, value in vars(args).items()
            },
            "outcome": "complete" if target_met else "shortened_verified",
            "target_met": target_met,
            "admission_stop": admission_stop,
            "workers": args.workers,
            "control_workers": args.control_workers,
            "shared_buffers_mb": args.shared_buffers_mb,
            "startup_seconds": ready_at - started,
            "workload_seconds": finished_at - workload_at,
            "completed_profiles": 1 if live else len(complete_jobs),
            "completed_iterations": len(complete_jobs),
            "peak_pss": peak,
            "final_processes": last_rows,
            "verification": verification,
            "cgroup": group_sample(memory_cgroup),
            "initial_cgroup": initial_group,
            "catalog": catalog,
            "statistics": final_statistics,
            "dashboard": dashboard_result,
            "websocket": events_result,
            "platform_requests": traffic["real_downloads"]
            if live
            else PlatformHandler.requests,
            "platform_peak_active": traffic["peak_downloads"]
            if live
            else PlatformHandler.peak,
            "health": health_body,
            "limitations": [
                *(
                    [
                        f"real guest auth, onlyfans performer, guest-visible Posts capped at {args.files} per cycle",
                        "verified disposable media removed and download flags reset between cycles",
                        "local SHA256 and persisted size checks; upstream provides no reference hash",
                    ]
                    if live
                    else [
                        "guest authentication replaced by no-op fixture",
                        "fake stored auth with real authenticated login/model/session lifecycle against loopback responses",
                        "external platform WebSocket start disabled; connection objects/callbacks retained",
                    ]
                ),
                "real SQL ledger workers, writer, Redis/PostgreSQL, HTTP streaming and file writes",
                "QEMU ARM64 guest environment must be verified by the outer VM controller"
                if os.uname().machine == "aarch64"
                else "Native host diagnostic; not 4 GiB ARM64 acceptance",
                "emulated timings do not establish physical Pi throughput, thermals or USB-controller behavior",
                "no PgBouncer or container acceptance",
                "filesystem page cache excluded from process PSS",
            ],
        }
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {
                    key: value
                    for key, value in result.items()
                    if key != "final_processes"
                }
            ),
            flush=True,
        )
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostics", action="store_true")
    parser.add_argument(
        "--workload", choices=["guest-onlyfans", "offline-fixture"], required=True
    )
    parser.add_argument("--retention-seconds", type=int)
    parser.add_argument("--retention-batch-size", type=int)
    parser.add_argument("--reconcile-interval-seconds", type=int)
    parser.add_argument("--warmup-seconds", type=int, required=True)
    parser.add_argument("--minimum-available-bytes", type=int, required=True)
    parser.add_argument("--low-headroom-seconds", type=int, required=True)
    parser.add_argument("--startup-timeout-seconds", type=int, required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--control-workers", type=int, required=True)
    parser.add_argument("--shared-buffers-mb", type=int, required=True)
    parser.add_argument("--idle-seconds", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-parent", type=Path, required=True)
    parser.add_argument("--profiles", type=int, required=True)
    parser.add_argument("--active-profiles", type=int, required=True)
    parser.add_argument("--files", type=int, required=True)
    parser.add_argument("--file-concurrency", type=int, required=True)
    parser.add_argument("--part-concurrency", type=int, required=True)
    parser.add_argument("--batch-size", type=int, required=True)
    parser.add_argument("--media-bytes", type=int, required=True)
    parser.add_argument("--response-delay", type=float, required=True)
    parser.add_argument("--drain-seconds", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    parser.add_argument("--stall-seconds", type=int, required=True)
    parser.add_argument("--redis-aof", choices=("yes", "no"), required=True)
    parser.add_argument("--require-memory-max-bytes", type=int)
    parser.add_argument("--minimum-workload-seconds", type=int, required=True)
    parser.add_argument("--catalog-media", type=int, required=True)
    parser.add_argument("--catalog-users", type=int, required=True)
    parser.add_argument("--seed-batch", type=int, required=True)
    parser.add_argument("--statistics-interval", type=int, required=True)
    parser.add_argument("--checkpoint-timeout-seconds", type=int, required=True)
    parser.add_argument("--maintenance-interval", type=int, required=True)
    parser.add_argument("--minimum-free-bytes", type=int, required=True)
    parser.add_argument("--minimum-catalog-bytes", type=int, required=True)
    arguments = parser.parse_args()
    assert arguments.data_parent.is_absolute() and arguments.data_parent.is_dir()
    assert arguments.workload == "guest-onlyfans" or (
        shutil.disk_usage(arguments.data_parent).free
        > arguments.profiles * arguments.files * arguments.media_bytes + 1024**3
    )
    assert all(
        getattr(arguments, name) > 0
        for name in (
            "catalog_media",
            "catalog_users",
            "seed_batch",
            "statistics_interval",
            "maintenance_interval",
            "minimum_free_bytes",
        )
    )
    assert all(
        getattr(arguments, name) > 0
        for name in (
            "profiles",
            "active_profiles",
            "files",
            "file_concurrency",
            "part_concurrency",
            "batch_size",
            "media_bytes",
            "drain_seconds",
            "timeout_seconds",
            "stall_seconds",
        )
    )

    if (
        min(
            arguments.workers,
            arguments.control_workers,
            arguments.shared_buffers_mb,
            arguments.idle_seconds,
        )
        <= 0
    ):
        parser.error("All numerical experiment inputs must be positive")
    try:
        result = run(arguments)
    except Exception as error:
        if arguments.output.is_dir():
            failure = {
                "type": type(error).__name__,
                "message": str(error),
                "observers": observer_failures(arguments.output),
            }
            (arguments.output / "failure.json").write_text(
                json.dumps(failure, indent=2) + "\n"
            )
        raise
    finally:
        if arguments.output.is_dir():
            (arguments.output / "shutdown-cgroup.json").write_text(
                json.dumps(group_sample(memory_group()), indent=2) + "\n"
            )
    raise SystemExit(0 if result["target_met"] else 2)
