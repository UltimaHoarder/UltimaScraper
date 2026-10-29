"""Analyze Redis memory usage for the USR key schema.

Read-only diagnostic: scans all keys and uses `MEMORY USAGE` to estimate
bytes per key, then aggregates by the USR key categories defined in
`../UltimaBackends/UltimaScraperBackend/ultima_scraper_backend/job_system/storage.py` and `routing.py`.

Usage:
    uv run python scripts/maintenance/analyze_redis_memory.py                 # use config.json
    uv run python scripts/maintenance/analyze_redis_memory.py --url redis://host:port/0
    uv run python scripts/maintenance/analyze_redis_memory.py --top 30 --sample 0   # full scan
    uv run python scripts/maintenance/analyze_redis_memory.py --per-job          # per-job breakdown
    uv run python scripts/maintenance/analyze_redis_memory.py --show-big-keys 20 # list biggest keys

Notes:
- `MEMORY USAGE key` is O(1) but runs on the server; `--sample N` caps the
  number of keys inspected per category for very large keyspaces.
- Safe to run while the system is live (no writes, SCAN cursor is gentle).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

import redis


# ---- Key classification -----------------------------------------------------
# Keep in sync with storage.py / routing.py prefixes under KEY_PREFIX.
KEY_PREFIX = "ultimascraper"

# Order matters: more specific patterns must come before generic ones.
CATEGORIES: list[tuple[str, re.Pattern[str]]] = [
    ("task_blob",          re.compile(rf"^{KEY_PREFIX}:jobs:[^:]+:task:[^:]+$")),
    ("task_dependents",    re.compile(rf"^{KEY_PREFIX}:jobs:[^:]+:task:[^:]+:dependents$")),
    ("task_exec_lock",     re.compile(rf"^{KEY_PREFIX}:task:[^:]+:exec_lock$")),
    ("task_index",         re.compile(rf"^{KEY_PREFIX}:jobs:[^:]+:tasks$")),
    ("tasks_ready",        re.compile(rf"^{KEY_PREFIX}:jobs:[^:]+:tasks:ready$")),
    ("tasks_blocked",      re.compile(rf"^{KEY_PREFIX}:jobs:[^:]+:tasks:blocked$")),
    ("tasks_completed",    re.compile(rf"^{KEY_PREFIX}:jobs:[^:]+:tasks:completed$")),
    ("tasks_inflight",     re.compile(rf"^{KEY_PREFIX}:jobs:[^:]+:tasks:inflight$")),
    ("task_outputs",       re.compile(rf"^{KEY_PREFIX}:jobs:[^:]+:task_outputs$")),
    ("job_config",         re.compile(rf"^{KEY_PREFIX}:jobs:[^:]+:config$")),
    ("job_state",          re.compile(rf"^{KEY_PREFIX}:job:[^:]+:state$")),
    ("job_state_lock",     re.compile(rf"^{KEY_PREFIX}:job:[^:]+:state_lock$")),
    ("job_routing_lock",   re.compile(rf"^{KEY_PREFIX}:job:[^:]+:routing_lock$")),
    ("job_envelope",       re.compile(rf"^{KEY_PREFIX}:jobs:envelopes:[^:]+$")),
    ("job_index",          re.compile(rf"^{KEY_PREFIX}:jobs:index$")),
    ("jobs_unclaimed",     re.compile(rf"^{KEY_PREFIX}:jobs:unclaimed$")),
    ("jobs_scheduled",     re.compile(rf"^{KEY_PREFIX}:jobs:scheduled$")),
    ("dedupe",             re.compile(rf"^{KEY_PREFIX}:tasks:dedupe:.+$")),
    ("deferred_bucket",    re.compile(rf"^{KEY_PREFIX}:deferred:(?!.*:requeue_lock$).+$")),
    ("deferred_requeue_lock", re.compile(rf"^{KEY_PREFIX}:deferred:.+:requeue_lock$")),
    ("recovery_lock",      re.compile(rf"^{KEY_PREFIX}:recovery:backend:[^:]+$")),
    ("backend_active_jobs", re.compile(rf"^{KEY_PREFIX}:backend:[^:]+:active_jobs$")),
    ("backend_claimed",    re.compile(rf"^{KEY_PREFIX}:backend:[^:]+:claimed.*$")),
    ("backend_workers",    re.compile(rf"^{KEY_PREFIX}:backend:[^:]+:workers$")),
    ("backend_info",       re.compile(rf"^{KEY_PREFIX}:backend:[^:]+$")),
    ("worker_heartbeat",   re.compile(rf"^{KEY_PREFIX}:workers:heartbeat:.+$")),
    ("worker_info",        re.compile(rf"^{KEY_PREFIX}:workers:[^:]+$")),
    ("statistics_cache",   re.compile(rf"^{KEY_PREFIX}:statistics.*$")),
    ("queue_priority",     re.compile(rf"^{KEY_PREFIX}:queue:.+$")),
]

JOB_ID_RE = re.compile(rf"^{KEY_PREFIX}:(?:jobs|job|jobs:envelopes):([^:]+)")


def classify(key: str) -> str:
    for name, pat in CATEGORIES:
        if pat.match(key):
            return name
    if key.startswith(f"{KEY_PREFIX}:"):
        return "other_ultimascraper"
    return "non_ultimascraper"


def extract_job_id(key: str) -> str | None:
    m = JOB_ID_RE.match(key)
    if not m:
        return None
    candidate = m.group(1)
    # Skip non-job-id tokens like "index", "unclaimed", "scheduled", "envelopes".
    if candidate in {"index", "unclaimed", "scheduled", "envelopes"}:
        return None
    return candidate


# ---- Aggregation ------------------------------------------------------------
@dataclass
class CategoryStats:
    keys: int = 0
    sampled: int = 0
    total_bytes: int = 0
    max_bytes: int = 0
    max_key: str = ""

    @property
    def avg_sampled(self) -> float:
        return self.total_bytes / self.sampled if self.sampled else 0.0

    @property
    def estimated_total(self) -> int:
        # Extrapolate from the sampled average to the full key count.
        return int(self.avg_sampled * self.keys)


@dataclass
class JobStats:
    bytes: int = 0
    keys: int = 0
    categories: dict[str, int] = field(default_factory=dict)


def human(nbytes: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while nbytes >= 1024 and i < len(units) - 1:
        nbytes /= 1024
        i += 1
    return f"{nbytes:,.2f} {units[i]}"


# ---- Redis URL discovery ----------------------------------------------------
def resolve_redis_url(cli_url: str | None) -> str:
    if cli_url:
        return cli_url
    # Try the app's config file so this mirrors the running backend.
    try:
        from ultima_scraper_backend.config import (  # type: ignore
            UltimaScraperCollectionConfig,
        )
        cfg = UltimaScraperCollectionConfig.load_or_create_default_config()
        r = cfg.settings.redis
        auth = f":{r.password}@" if r.password else ""
        return f"redis://{auth}{r.host}:{r.port}/{r.db}"
    except Exception as exc:
        print(f"[warn] could not load app config ({exc}); falling back to localhost",
              file=sys.stderr)
        return "redis://localhost:6379/0"


# ---- Main analysis ----------------------------------------------------------
def iter_keys(
    client: redis.Redis,
    match: str,
    count: int,
) -> Iterable[str]:
    for raw in client.scan_iter(match=match, count=count):
        if isinstance(raw, bytes):
            yield raw.decode("utf-8", errors="replace")
        else:
            yield str(raw)


def analyze(
    client: redis.Redis,
    *,
    match: str,
    sample_per_category: int,
    top_n: int,
    per_job: bool,
    show_big_keys: int,
) -> None:
    info = client.info("memory")
    used_memory = int(info.get("used_memory", 0))
    used_memory_rss = int(info.get("used_memory_rss", 0))
    dataset = int(info.get("used_memory_dataset", 0) or 0)
    total_keys = client.dbsize()

    print("=" * 78)
    print("Redis memory overview")
    print("=" * 78)
    print(f"  used_memory       : {human(used_memory)}")
    print(f"  used_memory_rss   : {human(used_memory_rss)}")
    if dataset:
        print(f"  used_memory_dataset: {human(dataset)}  (actual data, excl. overhead)")
    print(f"  dbsize (keys)     : {total_keys:,}")
    print()

    stats: dict[str, CategoryStats] = defaultdict(CategoryStats)
    job_stats: dict[str, JobStats] = defaultdict(JobStats)
    big_keys: list[tuple[int, str, str]] = []  # (bytes, key, category)

    # Pass 1: count keys per category (cheap, no MEMORY USAGE).
    print(f"[1/2] Scanning keys (match={match!r}) ...")
    all_keys_by_cat: dict[str, list[str]] = defaultdict(list)
    for i, key in enumerate(iter_keys(client, match=match, count=1000), start=1):
        cat = classify(key)
        stats[cat].keys += 1
        all_keys_by_cat[cat].append(key)
        if i % 50000 == 0:
            print(f"      scanned {i:,} keys ...", flush=True)
    print(f"      done: {sum(s.keys for s in stats.values()):,} keys across "
          f"{len(stats)} categories")
    print()

    # Pass 2: sample MEMORY USAGE per category.
    print(f"[2/2] Sampling MEMORY USAGE "
          f"(up to {sample_per_category or 'ALL'} keys/category) ...")
    for cat, keys in all_keys_by_cat.items():
        sample = keys if sample_per_category == 0 else keys[:sample_per_category]
        s = stats[cat]
        for key in sample:
            try:
                nbytes = client.memory_usage(key)
            except redis.ResponseError:
                continue
            if nbytes is None:
                continue
            nbytes = int(nbytes)
            s.sampled += 1
            s.total_bytes += nbytes
            if nbytes > s.max_bytes:
                s.max_bytes = nbytes
                s.max_key = key
            if show_big_keys:
                big_keys.append((nbytes, key, cat))
            if per_job:
                jid = extract_job_id(key)
                if jid:
                    js = job_stats[jid]
                    js.bytes += nbytes
                    js.keys += 1
                    js.categories[cat] = js.categories.get(cat, 0) + nbytes
    print("      done")
    print()

    # ---- Category report ---------------------------------------------------
    total_est = sum(s.estimated_total for s in stats.values())
    rows = sorted(stats.items(), key=lambda kv: kv[1].estimated_total, reverse=True)
    print("=" * 78)
    print("By category (extrapolated from samples)")
    print("=" * 78)
    print(f"{'category':<24} {'keys':>10} {'sampled':>9} "
          f"{'avg':>10} {'max':>12} {'est. total':>14} {'%':>6}")
    print("-" * 78)
    for cat, s in rows[:top_n]:
        pct = (s.estimated_total / total_est * 100) if total_est else 0.0
        print(f"{cat:<24} {s.keys:>10,} {s.sampled:>9,} "
              f"{human(s.avg_sampled):>10} {human(s.max_bytes):>12} "
              f"{human(s.estimated_total):>14} {pct:>5.1f}%")
    print("-" * 78)
    print(f"{'TOTAL (est. dataset)':<24} "
          f"{sum(s.keys for s in stats.values()):>10,} "
          f"{'':>9} {'':>10} {'':>12} {human(total_est):>14}")
    print()
    if used_memory and total_est:
        coverage = total_est / used_memory * 100
        print(f"Estimated dataset size covers {coverage:.1f}% of used_memory "
              f"(remainder = Redis overhead + unsampled + extrapolation error).")
        print()

    # ---- Biggest single keys ----------------------------------------------
    if show_big_keys:
        big_keys.sort(reverse=True)
        print("=" * 78)
        print(f"Top {show_big_keys} biggest sampled keys")
        print("=" * 78)
        for nbytes, key, cat in big_keys[:show_big_keys]:
            print(f"  {human(nbytes):>10}  [{cat}]  {key}")
        print()

    # ---- Per-job breakdown -------------------------------------------------
    if per_job and job_stats:
        print("=" * 78)
        print(f"Top {top_n} jobs by sampled bytes")
        print("=" * 78)
        print(f"{'job_id':<40} {'sampled_keys':>13} {'sampled_bytes':>15}")
        print("-" * 78)
        top_jobs = sorted(job_stats.items(), key=lambda kv: kv[1].bytes,
                          reverse=True)[:top_n]
        for jid, js in top_jobs:
            print(f"{jid:<40} {js.keys:>13,} {human(js.bytes):>15}")
        print()
        print("Tip: use --sample 0 for accurate per-job totals; default samples")
        print("     only N keys per category so a job with 80k task blobs will")
        print("     be undercounted here.")
        print()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=None, help="Redis URL (default: read config.json)")
    p.add_argument("--match", default="*", help="SCAN MATCH pattern (default: *)")
    p.add_argument("--sample", type=int, default=2000,
                   help="Max keys sampled per category for MEMORY USAGE "
                        "(0 = all, accurate but slower). Default: 2000")
    p.add_argument("--top", type=int, default=25,
                   help="How many rows in category/job tables. Default: 25")
    p.add_argument("--per-job", action="store_true",
                   help="Also aggregate bytes per job_id.")
    p.add_argument("--show-big-keys", type=int, default=20,
                   help="List the N largest sampled keys. 0 = disable. Default: 20")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    url = resolve_redis_url(args.url)
    print(f"Connecting to {url}\n")
    client = redis.Redis.from_url(url, decode_responses=False, socket_timeout=30)
    try:
        client.ping()
    except redis.RedisError as exc:
        print(f"ERROR: cannot reach Redis at {url}: {exc}", file=sys.stderr)
        return 1

    analyze(
        client,
        match=args.match,
        sample_per_category=args.sample,
        top_n=args.top,
        per_job=args.per_job,
        show_big_keys=args.show_big_keys,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
