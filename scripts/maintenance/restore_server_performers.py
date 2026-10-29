"""CLI for the shared server archive restoration engine."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ultima_scraper_backend.services.server_restore_files import (
    apply_plan,
    make_plan,
    scan,
    write_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scanner = commands.add_parser("scan")
    scanner.add_argument(
        "--server",
        type=Path,
        required=True,
        help="Path to the destination server archive directory.",
    )
    scanner.add_argument("--output", type=Path, required=True)
    planner = commands.add_parser("plan")
    planner.add_argument("--inventory", type=Path, required=True)
    selection = planner.add_mutually_exclusive_group(required=True)
    selection.add_argument("--performer", action="append")
    selection.add_argument("--all-performers", action="store_true")
    planner.add_argument("--hash-new-files", action="store_true")
    planner.add_argument("--hash-collisions", action="store_true")
    planner.add_argument("--remove-duplicates", action="store_true")
    planner.add_argument("--repair-zero-bytes", action="store_true")
    planner.add_argument("--cleanup-empty", action="store_true")
    planner.add_argument("--ignore-db-json", action=argparse.BooleanOptionalAction, default=True)
    planner.add_argument("--output", type=Path, required=True)
    executor = commands.add_parser("apply")
    executor.add_argument("--plan", type=Path, required=True)
    executor.add_argument("--journal", type=Path, required=True)
    executor.add_argument("--approved-plan-sha256", required=True)
    args = parser.parse_args()
    if args.command == "scan":
        from ultima_scraper_backend.config import UltimaScraperCollectionConfig

        setup = UltimaScraperCollectionConfig.load_or_create_default_config().settings.download_setup
        roots = [p for drive in setup.drives for p in drive.directories]
        write_report(
            args.output,
            scan(
                args.server,
                roots,
                ["OnlyFans", *setup.get_site_directory_aliases("onlyfans")],
            ),
        )
    elif args.command == "plan":
        inventory = json.loads(args.inventory.read_text())
        performers = (
            sorted({m["performer"] for m in inventory["matches"]})
            if args.all_performers
            else args.performer
        )
        write_report(
            args.output,
            make_plan(
                inventory,
                performers,
                hash_new_files=args.hash_new_files,
                hash_collisions=args.hash_collisions,
                remove_duplicates=args.remove_duplicates,
                repair_zero_bytes=args.repair_zero_bytes,
                cleanup_empty=args.cleanup_empty,
                ignore_db_json=args.ignore_db_json,
            ),
        )
    else:
        raw = args.plan.read_bytes()
        if hashlib.sha256(raw).hexdigest() != args.approved_plan_sha256:
            parser.error("Approved plan SHA256 does not match")
        apply_plan(json.loads(raw), args.journal)


if __name__ == "__main__":
    main()
