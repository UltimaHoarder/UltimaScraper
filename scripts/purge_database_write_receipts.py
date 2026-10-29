"""Inspect or apply bounded receipt retention; never bypass Redis inventory."""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path

from ultima_scraper_backend.config import UltimaScraperCollectionConfig
from ultima_scraper_backend.database.receipt_retention import (
    DEFAULT_RETENTION_MINUTES,
    MINIMUM_RETENTION_MINUTES,
    RECEIPT_BATCH_SIZE,
    pending_command_ids,
    purge_receipts,
    retention_mode,
)
from ultima_scraper_backend.database.threads import run_database_call
from ultima_scraper_backend.redis.client import RedisManager


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--mode",
        choices=["idle", "paused", "always"],
        default=retention_mode(),
        help="Idle yields to jobs and queued writes; always permits concurrent cleanup",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=4,
        help="0 continues until the full sweep completes",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Checkpoint cursor, cutoff and committed count for resumption",
    )
    parser.add_argument("--batch-size", type=int, default=RECEIPT_BATCH_SIZE)
    parser.add_argument(
        "--cursor", default="(0,0)", help="Resume a reported physical sweep cursor"
    )
    args = parser.parse_args()
    if args.max_batches < 0:
        parser.error("--max-batches must be nonnegative")
    total = 0
    cursor = args.cursor
    cutoff = None
    if args.state_file and args.state_file.exists():
        checkpoint = json.loads(args.state_file.read_text())
        if checkpoint.get("finished"):
            print(json.dumps(checkpoint), flush=True)
            return
        cursor = checkpoint["cursor"]
        total = checkpoint["total_deleted"]
        cutoff = datetime.fromisoformat(checkpoint["cutoff"])
    config = UltimaScraperCollectionConfig.load_or_create_default_config()
    if cutoff is None:
        # One fixed cutoff for the whole sweep, so a resumed run deletes the same set.
        minutes = getattr(
            getattr(config.settings, "job_execution", None),
            "receipt_retention_minutes",
            DEFAULT_RETENTION_MINUTES,
        )
        cutoff = datetime.now(UTC) - timedelta(
            minutes=max(MINIMUM_RETENTION_MINUTES, minutes)
        )
    redis = RedisManager(config=config.settings.redis)
    if not await redis.connect():
        raise RuntimeError("Redis unavailable; receipt cleanup aborted")
    try:
        for batch in count():
            if args.max_batches and batch >= args.max_batches:
                break
            protected = await pending_command_ids(redis)
            result = await run_database_call(
                purge_receipts,
                protected_ids=protected,
                batch_size=args.batch_size,
                dry_run=not args.apply,
                cursor=cursor if args.apply else None,
                cutoff=cutoff,
                mode=args.mode,
            )
            total += result.deleted
            print(
                json.dumps(
                    {
                        "batch": batch + 1,
                        "selected": result.selected,
                        "deleted": result.deleted,
                        "total_deleted": total,
                        "busy": result.busy,
                        "queued_commands": len(protected),
                        "dry_run": not args.apply,
                        "next_cursor": result.next_cursor or cursor,
                        "finished": result.finished,
                        "paused_reason": result.paused_reason,
                        "mode": args.mode,
                    }
                ),
                flush=True,
            )
            if (
                (result.busy or result.paused_reason)
                and args.apply
                and not args.max_batches
            ):
                await asyncio.sleep(5 if result.paused_reason else 1)
                continue
            if not args.apply or result.busy or result.paused_reason:
                break
            cursor = result.next_cursor
            if args.state_file:
                temporary = args.state_file.with_suffix(args.state_file.suffix + ".tmp")
                temporary.write_text(
                    json.dumps(
                        {
                            "cursor": cursor,
                            "cutoff": cutoff.isoformat(),
                            "total_deleted": total,
                            "finished": result.finished,
                        }
                    )
                )
                temporary.replace(args.state_file)
            if result.finished:
                break
    finally:
        await redis.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
