"""Generated archive and competing requests for an owned runtime benchmark."""

import json
import shutil
import threading
import time
import urllib.request

from sqlalchemy import text


def seed_catalog(engine, args, root, output, platform_port, group_sample, group):
    started = time.monotonic()
    assert args.catalog_media % args.catalog_users == 0
    per_user = args.catalog_media // args.catalog_users
    assert per_user % 10 == 0 and args.seed_batch % per_user == 0
    with (output / "seed.jsonl").open("w") as log:
        for first in range(1, args.catalog_media + 1, args.seed_batch):
            last = min(first + args.seed_batch - 1, args.catalog_media)
            assert shutil.disk_usage(root).free >= args.minimum_free_bytes
            with engine.begin() as connection:
                connection.execute(
                    text("SET LOCAL search_path=onlyfans,management,public")
                )
                connection.execute(
                    text("""
                    INSERT INTO users(id,username,performer)
                    SELECT 2000000+i, 'archive-performer-' || i, true
                    FROM generate_series(CAST(:first AS bigint),CAST(:last AS bigint)) AS source(i)
                """),
                    {"first": (first - 1) // per_user, "last": (last - 1) // per_user},
                )
                connection.execute(
                    text("""
                    INSERT INTO x_posts(id,user_id,text,media_count,created_at)
                    SELECT 20000000000000+i,2000000+i/:posts_per_user,
                        'Archived post ' || i || ': ' || repeat(md5(i::text),12),
                        10,'2026-08-01T00:00:00Z'::timestamptz
                    FROM generate_series(CAST(:first AS bigint),CAST(:last AS bigint)) AS source(i)
                """),
                    {
                        "first": (first - 1) // 10,
                        "last": (last - 1) // 10,
                        "posts_per_user": per_user // 10,
                    },
                )
                connection.execute(
                    text("""
                    INSERT INTO media(id,user_id,url,size,category,created_at)
                    SELECT 30000000000000+i,2000000+(i-1)/:per_user,
                        :origin || '/archive/' || i || '.jpg?signature=' || repeat(md5(i::text),22),
                        1048576+(i%100)*4096,
                        CASE WHEN i%5=0 THEN 'video' ELSE 'image' END,
                        '2026-08-01T00:00:00Z'::timestamptz
                    FROM generate_series(CAST(:first AS bigint),CAST(:last AS bigint)) AS source(i)
                """),
                    {
                        "first": first,
                        "last": last,
                        "per_user": per_user,
                        "origin": f"http://127.0.0.1:{platform_port}",
                    },
                )
                connection.execute(
                    text("""
                    INSERT INTO content_media_asso(post_id,media_id)
                    SELECT 20000000000000+(i-1)/10,30000000000000+i
                    FROM generate_series(CAST(:first AS bigint),CAST(:last AS bigint)) AS source(i)
                """),
                    {"first": first, "last": last},
                )
                connection.execute(
                    text("""
                    INSERT INTO filepaths(media_id,filepath)
                    SELECT 30000000000000+i,
                        '/fixture-archive/' || (2000000+(i-1)/:per_user) || '/Posts/' || i || '.jpg'
                    FROM generate_series(CAST(:first AS bigint),CAST(:last AS bigint)) AS source(i)
                """),
                    {"first": first, "last": last, "per_user": per_user},
                )
            sample = {
                "seeded_media": last,
                "elapsed": time.monotonic() - started,
                "cgroup": group_sample(group),
                "filesystem_free_bytes": shutil.disk_usage(root).free,
            }
            log.write(json.dumps(sample) + "\n")
            log.flush()
            print(
                json.dumps(
                    {"event": "seed", "media": last, "seconds": sample["elapsed"]}
                ),
                flush=True,
            )
        with engine.begin() as connection:
            for table in (
                "users",
                "x_posts",
                "media",
                "content_media_asso",
                "filepaths",
            ):
                connection.execute(text(f"ANALYZE onlyfans.{table}"))
        with engine.connect() as connection:
            relations = [
                dict(row._mapping)
                for row in connection.execute(
                    text("""
                SELECT relname,pg_total_relation_size(relid) AS bytes,n_live_tup
                FROM pg_stat_user_tables WHERE schemaname='onlyfans'
                  AND relname IN ('users','x_posts','media','content_media_asso','filepaths')
                ORDER BY relname
            """)
                )
            ]
            counts = dict(
                connection.execute(
                    text("""
                SELECT 'users',count(*) FROM onlyfans.users
                    WHERE id>=2000000 AND id<2000000+:users
                UNION ALL SELECT 'posts',count(*) FROM onlyfans.x_posts
                UNION ALL SELECT 'media',count(*) FROM onlyfans.media
                UNION ALL SELECT 'links',count(*) FROM onlyfans.content_media_asso
                UNION ALL SELECT 'filepaths',count(*) FROM onlyfans.filepaths
            """),
                    {"users": args.catalog_users},
                ).all()
            )
            database_bytes = connection.scalar(
                text("SELECT pg_database_size(current_database())")
            )
        assert counts == {
            "users": args.catalog_users,
            "posts": args.catalog_media // 10,
            "media": args.catalog_media,
            "links": args.catalog_media,
            "filepaths": args.catalog_media,
        }, counts
        result = {
            "counts": counts,
            "database_bytes": database_bytes,
            "relations": relations,
            "seconds": time.monotonic() - started,
            "scope": "Generated rows with existing indexes, false downloaded flags and no physical catalog media files; all belong to this disposable database.",
        }
        (output / "catalog.json").write_text(json.dumps(result, indent=2) + "\n")
        return result


class MixedWork:
    def __init__(
        self,
        engine,
        redis,
        port,
        output,
        *,
        statistics_interval,
        maintenance_interval,
        checkpoint_timeout_seconds,
    ):
        self.engine, self.redis, self.port = engine, redis, port
        self.output = output
        self.statistics_interval = statistics_interval
        self.maintenance_interval = maintenance_interval
        self.checkpoint_timeout_seconds = checkpoint_timeout_seconds
        self.stop_event = threading.Event()
        self.started_event = threading.Event()
        self.errors = []
        self.snapshot = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def statistics(self, *, refresh):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/v1/statistics/onlyfans?refresh={'true' if refresh else 'false'}",
            headers={"X-USR-Admin-Token": "fixture-local-only"},
        )
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        if result.get("build_error"):
            raise RuntimeError(f"Statistics failed: {result['build_error']}")
        return {
            "seconds": time.monotonic() - started,
            "refresh": refresh,
            "response": result,
        }

    def read_page(self, path):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            headers={"X-USR-Admin-Token": "fixture-local-only"},
        )
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            result = json.loads(body)
        return {
            "path": path,
            "seconds": time.monotonic() - started,
            "response_bytes": len(body),
            "items": len(
                result.get("jobs", result.get("tasks", result.get("backends", [])))
            ),
            "total": result.get("total"),
        }

    def run(self):
        if not self.started_event.wait(900):
            return
        started = time.monotonic()
        next_statistics = 0
        next_maintenance = self.maintenance_interval
        with (self.output / "mixed.jsonl").open("w") as log:
            while not self.stop_event.is_set():
                now = time.monotonic() - started
                operation = "statistics"
                operation_started = time.monotonic()
                try:
                    refresh = now >= next_statistics
                    record = self.statistics(refresh=refresh)
                    self.snapshot = record["response"].get("snapshot")
                    log.write(
                        json.dumps({"event": "statistics", "elapsed": now, **record})
                        + "\n"
                    )
                    log.flush()
                    if refresh:
                        next_statistics = now + self.statistics_interval
                    for path in (
                        "/api/v1/jobs?page=1&page_size=50",
                        "/api/v1/jobs?page=2&page_size=50",
                    ):
                        operation = path
                        operation_started = time.monotonic()
                        log.write(
                            json.dumps(
                                {
                                    "event": "read",
                                    "elapsed": now,
                                    **self.read_page(path),
                                }
                            )
                            + "\n"
                        )
                        log.flush()
                    if now >= next_maintenance:
                        operation = "checkpoint/aof maintenance"
                        operation_started = time.monotonic()
                        maintenance_at = time.monotonic()
                        with self.engine.connect().execution_options(
                            isolation_level="AUTOCOMMIT"
                        ) as connection:
                            connection.execute(
                                text(
                                    "SELECT set_config('statement_timeout', :timeout, false)"
                                ),
                                {
                                    "timeout": str(
                                        self.checkpoint_timeout_seconds * 1000
                                    )
                                },
                            )
                            try:
                                connection.execute(text("CHECKPOINT"))
                            finally:
                                connection.execute(text("RESET statement_timeout"))
                        persistence = self.redis.info("persistence")
                        rewrite_started = False
                        if not persistence.get("aof_rewrite_in_progress"):
                            try:
                                self.redis.bgrewriteaof()
                                rewrite_started = True
                            except Exception:
                                if not self.redis.info("persistence").get(
                                    "aof_rewrite_in_progress"
                                ):
                                    raise
                        log.write(
                            json.dumps(
                                {
                                    "event": "maintenance",
                                    "elapsed": now,
                                    "checkpoint_seconds": time.monotonic()
                                    - maintenance_at,
                                    "aof_rewrite_started": rewrite_started,
                                }
                            )
                            + "\n"
                        )
                        log.flush()
                        next_maintenance = now + self.maintenance_interval
                except Exception as exc:  # noqa: BLE001 - propagate thread failure to controller
                    failure = {
                        "operation": operation,
                        "seconds": time.monotonic() - operation_started,
                        "error": repr(exc),
                    }
                    self.errors.append(failure)
                    log.write(
                        json.dumps({"event": "error", "elapsed": now, **failure}) + "\n"
                    )
                    log.flush()
                    return
                self.stop_event.wait(5)

    def stop(self):
        self.stop_event.set()
        self.started_event.set()
        self.thread.join(timeout=self.checkpoint_timeout_seconds + 30)
        assert not self.thread.is_alive(), "Owned mixed-work thread did not stop"

    def final_statistics(self):
        pending_deadline = time.monotonic() + 300
        while True:
            state = self.statistics(refresh=False)["response"]
            if not state["is_building"]:
                break
            if time.monotonic() > pending_deadline:
                raise RuntimeError("In-flight statistics refresh did not finish")
            time.sleep(1)
        previous = state.get("snapshot")
        previous_time = previous.get("calculated_at") if previous else None
        self.statistics(refresh=True)
        deadline = time.monotonic() + 300
        while True:
            response = self.statistics(refresh=False)["response"]
            snapshot = response.get("snapshot")
            if (
                snapshot
                and not response["is_building"]
                and snapshot["calculated_at"] != previous_time
            ):
                with self.engine.connect() as connection:
                    total, known = connection.execute(
                        text("SELECT count(*),sum(size) FROM onlyfans.media")
                    ).one()
                assert snapshot["total_media_count"] == total, (snapshot, total)
                assert snapshot["total_known_bytes"] == known, (snapshot, known)
                (self.output / "final-statistics.json").write_text(
                    json.dumps(response, indent=2) + "\n"
                )
                return response
            if time.monotonic() > deadline:
                raise RuntimeError("Final statistics refresh did not finish")
            time.sleep(1)


def redis_retained_state(client):
    """Count owned key memory/expiry without reading or retaining payloads."""
    groups = {}
    for key in client.scan_iter(match="ultimascraper:*", count=100):
        if key.endswith(":config") and ":jobs:" in key:
            group = "job_config"
        elif key.endswith(":state") and ":job:" in key:
            group = "job_state"
        elif ":jobs:" in key and ":task:" in key:
            group = "task_detail_or_dependency"
        elif key.endswith(":task_outputs"):
            group = "task_outputs"
        elif key.endswith(":task_archive"):
            group = "archive_marker"
        elif ":database:" in key:
            group = "database_queue_or_delivery"
        elif ":jobs:" in key:
            group = "job_indexes_or_windows"
        elif ":events" in key:
            group = "events"
        else:
            group = "other"
        amount = client.memory_usage(key)
        if amount is None:
            continue
        row = groups.setdefault(
            group, {"keys": 0, "memory_bytes": 0, "without_expiry": 0}
        )
        row["keys"] += 1
        row["memory_bytes"] += amount
        row["without_expiry"] += int(client.ttl(key) == -1)
    return groups
