#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlmodel import select

from ultima_scraper_backend.config import _encrypt_config_secrets
from ultima_scraper_backend.database.factory import MultiSiteDatabaseManager
from ultima_scraper_db_archive.crypto import (
    encrypt_secret_value,
    get_secret_crypto,
    is_encrypted_secret,
    validate_secret_crypto_configuration,
)
from ultima_scraper_db_archive.global_db import SettingsModel, get_global_session

logger = logging.getLogger("encrypt_secrets")

AUTH_SECRET_COLUMNS = [
    "cookie",
    "x_bc",
    "authorization",
    "user_agent",
    "email",
    "password",
]


@dataclass(slots=True)
class MigrationStats:
    settings_rows_updated: int = 0
    auth_rows_updated: int = 0
    auth_fields_updated: int = 0


def _encrypt_global_settings(stats: MigrationStats) -> None:
    with get_global_session() as session:
        rows = list(session.exec(select(SettingsModel)).all())
        for row in rows:
            updated = False

            if row.is_secret and row.value and not is_encrypted_secret(row.value):
                encrypted = encrypt_secret_value(row.value)
                if encrypted and encrypted != row.value:
                    row.value = encrypted
                    updated = True

            if row.key == "config" and row.value:
                try:
                    payload = json.loads(row.value)
                except json.JSONDecodeError:
                    logger.warning("Skipping invalid config JSON in settings row id=%s", row.id)
                    payload = None
                if isinstance(payload, dict):
                    before = json.dumps(payload, sort_keys=True)
                    _encrypt_config_secrets(payload)
                    after = json.dumps(payload, sort_keys=True)
                    if before != after:
                        row.value = json.dumps(payload)
                        updated = True

            if updated:
                session.add(row)
                stats.settings_rows_updated += 1
        session.commit()


def _encrypt_site_auths(site: str, stats: MigrationStats) -> None:
    db = MultiSiteDatabaseManager().get_or_create_manager(site)
    with db.get_session() as session:
        rows = session.exec(
            text(
                'SELECT id, cookie, x_bc, "authorization", user_agent, email, password '
                "FROM user_auths"
            )
        ).all()

        for row in rows:
            mapping = row._mapping
            row_id = mapping["id"]
            updates: dict[str, str] = {}

            for column in AUTH_SECRET_COLUMNS:
                raw_value = mapping.get(column)
                if not isinstance(raw_value, str) or not raw_value:
                    continue
                if is_encrypted_secret(raw_value):
                    continue
                encrypted = encrypt_secret_value(raw_value)
                if encrypted and encrypted != raw_value:
                    updates[column] = encrypted

            if not updates:
                continue

            assignments = ", ".join(f"{column} = :{column}" for column in updates)
            params = {"id": row_id, **updates}
            session.execute(
                text(f"UPDATE user_auths SET {assignments} WHERE id = :id"),
                params,
            )
            stats.auth_rows_updated += 1
            stats.auth_fields_updated += len(updates)

        session.commit()


def run(sites: list[str]) -> MigrationStats:
    validate_secret_crypto_configuration()
    if get_secret_crypto() is None:
        raise RuntimeError("USR_SECRET_KEY must be configured to run secret encryption migration")
    stats = MigrationStats()
    _encrypt_global_settings(stats)
    for site in sites:
        _encrypt_site_auths(site.lower(), stats)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Encrypt existing plaintext secret values in management settings and user_auths tables."
        )
    )
    parser.add_argument(
        "--sites",
        nargs="+",
        default=["onlyfans", "fansly"],
        help="Site databases to process (default: onlyfans fansly)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    stats = run(args.sites)
    logger.info(
        "Secret migration complete: settings_rows_updated=%s auth_rows_updated=%s auth_fields_updated=%s",
        stats.settings_rows_updated,
        stats.auth_rows_updated,
        stats.auth_fields_updated,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
