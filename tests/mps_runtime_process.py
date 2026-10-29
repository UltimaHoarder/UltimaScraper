"""Child entry point for the owned-service MPS recovery integration test."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import signal
from types import SimpleNamespace
import legacy_redis_runtime as legacy


async def run(action: str) -> None:
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig
    from ultima_scraper_backend.database.write_queue import (
        DatabaseWriteClient,
        DatabaseWriteOperation,
    )
    from ultima_scraper_backend.job_system import Job, JobStorage, TaskResult, TaskState
    from ultima_scraper_backend.redis.client import RedisManager

    config = UltimaScraperCollectionConfig.load_or_create_default_config()
    redis = RedisManager(config=config.settings.redis)
    assert await redis.connect()
    output = Path(os.environ["MPS_FIXTURE_OUTPUT"])
    job_id = os.environ.get("MPS_FIXTURE_JOB_ID")
    try:
        if action == "submit":
            job = Job.create(
                name="Owned MPS recovery fixture",
                created_by="tests",
                tasks=[],
                metadata={"site": "onlyfans", "mps_manifest": True},
            )
            result = await DatabaseWriteClient(redis).submit(
                DatabaseWriteOperation.PREPARE_MPS_JOB,
                {
                    "job_id": job.job_id,
                    "job_config": job.to_dict(),
                    "selection": {"start_id": 1000, "end_id": 1_000_999},
                    "proxy_pool": [],
                },
                site="onlyfans",
            )
            output.write_text(json.dumps(result))
        elif action == "complete":
            assert job_id
            storage = JobStorage(redis)
            count = 0
            # Capture this bounded cohort before completion starts rolling refill.
            tasks = [task async for task in storage.fetch_tasks_stream(job_id, batch_size=4)]
            for task in tasks:
                assert await legacy.mark_task_started(storage, job_id, task.task_id)
                task.state = TaskState.COMPLETED
                task.result = TaskResult(success=True, output={"items_processed": 1})
                await legacy.persist_task_result(storage, job_id, task)
                await legacy.mark_task_completed(storage, job_id, task.task_id)
                count += 1
            output.write_text(json.dumps({"completed": count}))
        elif action == "materializer":
            from ultima_scraper_backend.job_system import materializer as mps
            from ultima_scraper_backend.job_system import durable as mps_durable

            if os.environ.get("MPS_FIXTURE_PAUSE_AFTER_COMMIT") == "1":

                async def pause_after_commit(*args, **kwargs):
                    output.write_text(json.dumps({"pid": os.getpid()}))
                    await asyncio.Event().wait()

                # Fault boundary only: actual SQL writer/receipt has returned,
                # but the Redis window has not yet been purged.
                mps_durable._purge_archived_window = pause_after_commit

            stopped = asyncio.Event()
            loop = asyncio.get_running_loop()
            for signum in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(signum, stopped.set)
            backend = SimpleNamespace(
                redis=redis,
                instance_id=config.settings.get_backend_id(),
                distributed_mode=True,
            )
            await mps.start_mps_materializer(backend)
            try:
                await stopped.wait()
            finally:
                await mps.stop_mps_materializer()
        else:
            raise ValueError(action)
    finally:
        await redis.disconnect()


if __name__ == "__main__":
    action = os.environ["MPS_FIXTURE_ACTION"]
    os.environ["ULTIMA_DATABASE_PROCESS_ROLE"] = (
        "writer" if action == "writer" else "application"
    )
    if action == "writer":
        from ultima_scraper_backend.database.writer_runtime import database_writer_main

        database_writer_main()
    else:
        asyncio.run(run(action))
