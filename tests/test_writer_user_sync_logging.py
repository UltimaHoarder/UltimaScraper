"""The writer logs one INFO summary per profile batch, not one line per profile."""

import logging
from contextlib import contextmanager
from types import SimpleNamespace

from ultima_scraper_backend.database import write_receipts
from ultima_scraper_backend.database.helpers import user_sync
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteCommand,
    DatabaseWriteOperation,
)


class _Session:
    def __init__(self):
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def connection(self):
        return None

    def flush(self):
        return None

    def commit(self):
        self.committed = True

    def rollback(self):
        return None


def _command(index):
    return DatabaseWriteCommand(
        command_id=f"cmd-{index}", operation=DatabaseWriteOperation.UPSERT_USER,
        site="onlyfans", payload={"user": {"id": 100 + index, "username": f"u{index}"}},
        producer_id="test", created_at="2026-10-20T00:00:00+00:00",
    )


async def test_profile_batch_logs_one_info_summary(monkeypatch, caplog):
    session = _Session()

    @contextmanager
    def receipts(_session, commands, _results, timing=None):
        yield list(commands)

    async def sync(manager, user, **kwargs):
        # The real sync fills these per-profile timings; the writer adds to them.
        kwargs["timing"].update(dict.fromkeys(
            ("payload_ms", "user_row_ms", "alias_ms", "authority_ms",
             "profile_ms", "social_ms", "flush_ms"), 0.0))
        user_sync.logger.debug("Synced user %s for site %s", user.id, kwargs.get("site"))
        return True

    monkeypatch.setattr(write_receipts, "receipt_batch", receipts)
    monkeypatch.setattr(user_sync, "sync_user_from_api", sync)
    monkeypatch.setattr(user_sync, "_prefetch_user_sync_profile_cache", lambda _s, _u: {})
    executor = PostgreSQLWriteExecutor.__new__(PostgreSQLWriteExecutor)
    executor._site_manager = lambda site: SimpleNamespace(get_session=lambda: session)

    caplog.set_level(logging.INFO)
    results = await executor._upsert_users([_command(i) for i in range(3)], "onlyfans")

    assert session.committed and len(results) == 3
    synced = [record for record in caplog.records if "Synced" in record.getMessage()]
    assert [(record.levelno, record.getMessage()) for record in synced] == [
        (logging.INFO, "Synced 3 user(s) for site onlyfans")
    ]
