"""Normal scrape/download boundaries with owned PostgreSQL, Redis and HTTP.

Opt in with USR_TEST_WITH_POSTGRES=1. No deployment URL or archive is accepted.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import subprocess
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from aiohttp import web
import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text
from sqlalchemy.orm import configure_mappers

from test_content_write_resources import content_engine, postgres_engine
from test_download_pipeline import _build_config
from test_streaming_scrape import onlyfans_user, _post
from ultima_scraper_api import ContentType
from ultima_scraper_backend.config import Drive
from ultima_scraper_backend.database.managers.postgres_manager import (
    PostgreSQLDatabaseManager,
)
from ultima_scraper_backend.database.write_executor import PostgreSQLWriteExecutor
from ultima_scraper_backend.database.write_queue import (
    DatabaseWriteClient,
    DatabaseWriterService,
)
from ultima_scraper_backend.job_system.handlers.download.streaming import (
    download_selected_media,
)
from ultima_scraper_backend.job_system.handlers.scrape.content import (
    scrape_content_type,
)
from ultima_scraper_backend.job_system.models import Job, Task, TaskRunContext, TaskType
from ultima_scraper_backend.job_system.payloads import DownloadTaskPayload
from ultima_scraper_backend.job_system.storage import JobStorage
from ultima_scraper_backend.manager import BackendManager
from ultima_scraper_db_archive import global_db
import legacy_redis_runtime as legacy

__all__ = ["content_engine", "postgres_engine", "onlyfans_user"]


@asynccontextmanager
async def owned_redis(directory):
    socket = str(directory / "redis.sock")
    with (directory / "redis.log").open("w+") as log:
        process = subprocess.Popen(
            [
                "redis-server",
                "--port",
                "0",
                "--unixsocket",
                socket,
                "--unixsocketperm",
                "700",
                "--dir",
                str(directory),
                "--save",
                "",
                "--appendonly",
                "no",
            ],
            stdout=log,
            stderr=log,
        )
        client = Redis(unix_socket_path=socket)
        try:
            async with asyncio.timeout(5):
                while True:
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    try:
                        await client.ping()
                        break
                    except (RedisConnectionError, OSError):
                        await asyncio.sleep(0.02)
            yield SimpleNamespace(
                client=client,
                set=client.set,
                get=client.get,
                delete=client.delete,
                exists=client.exists,
            )
        finally:
            await client.aclose()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


@asynccontextmanager
async def media_server(*, size=65536, delay=0.01):
    body = (bytes(range(256)) * ((size + 255) // 256))[:size]
    state = SimpleNamespace(body=body, active=0, peak=0, requests=0)

    async def serve(request):
        start, end = 0, len(body) - 1
        status = 200
        headers = {"Accept-Ranges": "bytes", "Content-Type": "image/jpeg"}
        if value := request.headers.get("Range"):
            first, last = value.removeprefix("bytes=").split("-")
            start, end = int(first), int(last) if last else end
            status = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
        headers["Content-Length"] = str(end - start + 1)
        if request.method == "HEAD":
            return web.Response(headers=headers)
        state.active += 1
        state.peak = max(state.peak, state.active)
        state.requests += 1
        try:
            response = web.StreamResponse(status=status, headers=headers)
            await response.prepare(request)
            await asyncio.sleep(delay)
            await response.write(body[start : end + 1])
            await response.write_eof()
            return response
        finally:
            state.active -= 1

    application = web.Application()
    application.router.add_get("/{id}.jpg", serve)
    runner = web.AppRunner(application)
    await runner.setup()
    listener = web.TCPSite(runner, "127.0.0.1", 0)
    await listener.start()
    state.url = f"http://127.0.0.1:{runner.addresses[0][1]}"
    try:
        yield state
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("file_concurrency", [2, 4])
async def test_scrape_selection_download_and_receipts_across_real_services(
    content_engine, onlyfans_user, monkeypatch, tmp_path, file_concurrency
):
    configure_mappers()
    with content_engine.begin() as connection:
        global_db.DatabaseWriteReceiptModel.metadata.create_all(connection)
    manager = PostgreSQLDatabaseManager(
        "onlyfans",
        content_engine.url.render_as_string(hide_password=False),
        engine=content_engine,
        pool_role="writer",
    )
    # The fixture has already connected this owned engine and created its schema.
    manager._is_connected = True
    monkeypatch.setattr(global_db, "global_session", manager.get_session)
    monkeypatch.setattr(global_db, "get_postgres_engine", lambda: content_engine)
    monkeypatch.setenv("ULTIMA_CONTENT_BATCH_SIZE", "7")
    monkeypatch.setenv("ULTIMA_DOWNLOAD_BATCH_SIZE", "7")
    monkeypatch.setenv("ULTIMA_TASK_RESULT_PREVIEW_MAX_ENTRIES", "2")
    monkeypatch.setenv("ULTIMA_TASK_RESULT_PREVIEW_MAX_BYTES", "4096")
    config = _build_config()
    config.settings.download_setup.drives = [Drive(directories=[tmp_path])]
    config.settings.network.downloads.max_file_concurrency = file_concurrency
    config.settings.network.downloads.max_concurrency = 4
    user = onlyfans_user
    user.posts_count = 23
    authed = user.get_authed()
    authed.drm = None
    authed.username = "buyer"
    authed.api.config = config
    authed.api.site_name = "OnlyFans"
    authed.api.get_site_settings = lambda: config.site_apis.onlyfans
    base = file_concurrency * 1000

    async with owned_redis(tmp_path) as redis, media_server() as http:

        async def scrape(url):
            offset = int(parse_qs(urlparse(url).query).get("offset", ["0"])[0])
            return [
                _post(
                    base + i,
                    media=[
                        dict(
                            id=base + i,
                            type="photo",
                            canView=True,
                            files={
                                "full": dict(
                                    url=f"{http.url}/{base + i}.jpg",
                                    size=len(http.body),
                                )
                            },
                        )
                    ],
                )
                for i in range(offset, min(offset + 50, user.posts_count))
            ]

        monkeypatch.setattr(user.scrape_manager, "scrape", scrape)
        writer = DatabaseWriteClient(redis, timeout_seconds=10)
        executor = PostgreSQLWriteExecutor.__new__(PostgreSQLWriteExecutor)
        executor.backend = BackendManager.__new__(BackendManager)
        executor._site_manager = lambda _: manager
        service = DatabaseWriterService(redis, executor, block_ms=10, max_attempts=1)
        running = asyncio.create_task(service.run())
        try:
            storage = JobStorage(redis)
            task = Task(
                task_type=TaskType.DOWNLOAD,
                site_name="OnlyFans",
                user_id=7,
                auth_id=99,
                content_type=ContentType.POSTS,
                depends_on=["scrape"],
                payload=DownloadTaskPayload(),
            )
            job = Job(
                name="Owned pipeline integration", created_by="pytest", tasks=[task]
            )
            plan = dict(
                selection_id=uuid4().hex,
                job_id=job.job_id,
                task_id="scrape",
                site="onlyfans",
                auth_id=99,
            )
            result = await scrape_content_type(
                user,
                ContentType.POSTS,
                None,
                database_writes=writer,
                site="onlyfans",
                auth_user_id=99,
                media_selection=plan,
            )
            assert result == (23, 23, [], [])
            await legacy.store_task_output(storage, 
                job.job_id, "scrape", {"media_selection": plan}
            )
            context = TaskRunContext(
                job=job,
                storage=storage,
                previous_output=None,
                context={"database_writes": writer, "worker_id": "fixture"},
            )
            result = await download_selected_media(
                task=task,
                context=context,
                user=user,
                db_user=SimpleNamespace(username="seven"),
                db_manager=manager,
                authed=authed,
                config=config,
                content_type="Posts",
                resolved_auth_id=99,
            )
            assert result.success
            assert result.metrics["downloads_completed"] == 23
            assert result.metrics["failed"] == 0
            assert result.metrics["bytes_written"] == 23 * len(http.body)
            assert (
                len(result.output["files"])
                == len(result.output["download_results"])
                == 2
            )
            assert (
                result.output["files_total"]
                == result.output["download_results_total"]
                == 23
            )
            assert 1 < http.peak <= file_concurrency
            assert http.requests == 23
            files = list(tmp_path.rglob("*.jpg"))
            assert len(files) == 23
            assert all(file.read_bytes() == http.body for file in files)
            assert not user.scrape_manager.scraped.Posts
            blob = json.loads(
                await redis.get(
                    storage.TASK_KEY.format(job_id=job.job_id, task_id=task.task_id)
                )
            )
            assert len(blob["result"]["output"]["download_results"]) == 2
            with manager.get_session() as session:
                assert dict(
                    session.execute(
                        text(
                            "SELECT kind, count(*) FROM management.task_media_evidence "
                            "WHERE selection_id = :selection GROUP BY kind"
                        ),
                        {"selection": result.output["media_evidence"]["selection_id"]},
                    ).all()
                ) == {
                    "files": 23,
                    "download_results": 23,
                }
                assert (
                    session.execute(
                        text(
                            "SELECT count(*) FROM media WHERE id >= :start AND id < :end AND downloaded"
                        ),
                        {"start": base, "end": base + 23},
                    ).scalar_one()
                    == 23
                )
                assert (
                    session.execute(
                        text(
                            "SELECT count(*) FROM management.database_write_receipts "
                            "WHERE result_json::jsonb->>'success' <> 'true'"
                        )
                    ).scalar_one()
                    == 0
                )
            assert await redis.client.xlen(writer.STREAM_KEY) == 0
        finally:
            service.stop()
            await asyncio.wait_for(running, timeout=10)
