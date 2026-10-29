"""Owned benchmark worker; all database and Redis endpoints come from fixtures."""

import asyncio
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from redis.asyncio import Redis
from sqlalchemy import create_engine, event
from sqlmodel import Session
from ultima_scraper_backend.database.threads import run_owned_thread_call
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteClient,
    DatabaseWriteOperation,
)
from ultima_scraper_backend.job_system.ledger import Claim, ExecutionLedger, Limits
from ultima_scraper_backend.job_system.ledger_runtime import (
    FencedWriter,
    LedgerTaskStorage,
)
from ultima_scraper_backend.job_system.models import Task, TaskResult, TaskState
from ultima_scraper_backend.workers.worker_pool import _TimedDatabaseWrites
from ultima_scraper_db_archive import global_db


async def main(config_path):
    config = json.loads(Path(config_path).read_text())
    engine = create_engine(
        config["sql_url"],
        pool_size=3,
        max_overflow=0,
        connect_args={
            "options": "-c search_path=onlyfans,management,public -c statement_timeout=15000"
        },
    )

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    global_db.global_session = sessions
    redis = SimpleNamespace(client=Redis(unix_socket_path=config["redis_socket"]))
    client = DatabaseWriteClient(
        redis,
        max_queue_commands=800,
        max_queue_bytes=512 * 1024 * 1024,
        timeout_seconds=120,
    )
    ledger = ExecutionLedger(
        sessions,
        limits=Limits(tasks=10000, global_tasks=10000, batch=128, lease_seconds=600),
    )
    slots = asyncio.Semaphore(207)
    durations, queue = [], []
    calls = 0

    def executed(*args):
        nonlocal calls
        calls += 1

    event.listen(engine, "after_cursor_execute", executed)

    async def execute(data):
        async with slots:
            owned = Claim(**data)
            item = Task.from_dict(owned.task)
            started = time.monotonic()
            storage = LedgerTaskStorage(ledger, owned, item, redis)
            fenced = FencedWriter(client, ledger, owned, storage)
            timed = _TimedDatabaseWrites(fenced)
            await asyncio.sleep(0.7 + (item.user_id % 100) / 200)
            if item.user_id % 100 < 17:
                operation = DatabaseWriteOperation.UPSERT_INVALID_USER
                payload = {"user_id": item.user_id, "reason": "not_found"}
            else:
                operation = DatabaseWriteOperation.UPSERT_USER
                payload = {
                    "user": {
                        "id": item.user_id,
                        "username": f"fixture-{item.user_id}",
                        "name": "Fixture profile",
                        "about": "Fixture biography",
                        "avatar": f"https://fixture.invalid/{item.user_id}.jpg",
                        "website": "https://fixture.invalid/",
                        "postsCount": 10,
                        "is_performer": True,
                    }
                }
            await timed.submit(operation, payload, site="onlyfans")
            queue.append(timed.queue_ms)
            item.state = TaskState.COMPLETED
            item.result = TaskResult(success=True)
            item.completed_at = item.result.completed_at
            await run_owned_thread_call(ledger.finish, owned, item)
            durations.append(time.monotonic() - started)

    try:
        Path(config["ready"]).touch()
        while not Path(config["go"]).is_file():
            await asyncio.sleep(0.01)
        async with asyncio.timeout(120):
            async with asyncio.TaskGroup() as group:
                for data in config["claims"]:
                    group.create_task(execute(data))
        Path(config["result"]).write_text(
            json.dumps({"durations": durations, "queue": queue, "driver_calls": calls})
        )
    finally:
        await redis.client.aclose()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
