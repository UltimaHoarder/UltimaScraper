"""Concurrent MPS uploads share bounded admission through owned cleanup."""

from __future__ import annotations

import asyncio
import threading

import httpx
import pytest
from starlette.requests import ClientDisconnect

import test_mps_http_inputs as fixtures
from ultima_scraper_backend.api import job_update_body

manager = fixtures.manager


@pytest.mark.parametrize(
    ("settings", "capacity"),
    [
        ({}, 1),
        ({"CONCURRENCY": "1", "MAX_INFLIGHT_BYTES": "98304"}, 1),
        ({"CONCURRENCY": "5", "MAX_INFLIGHT_BYTES": "32768"}, 1),
        ({"CONCURRENCY": "3", "MAX_INFLIGHT_BYTES": "65536"}, 2),
        ({"MAX_INFLIGHT_BYTES": "98304"}, 3),
    ],
)
async def test_busy_upload_does_not_read_body_or_open_file(
    monkeypatch, manager, settings, capacity
):
    for name, value in settings.items():
        monkeypatch.setenv(f"ULTIMA_MPS_UPLOAD_{name}", value)
    opened = []
    real_file = job_update_body.tempfile.TemporaryFile

    def temporary(**kwargs):
        source = real_file(**kwargs)
        opened.append(source)
        return source

    monkeypatch.setattr(job_update_body.tempfile, "TemporaryFile", temporary)
    entered = [asyncio.Event() for _ in range(capacity)]
    release = asyncio.Event()
    read_rejected = False

    async def held_body(index):
        entered[index].set()
        yield b'{"job_name":'
        await release.wait()
        yield b'"Completed"}'

    async def rejected_body():
        nonlocal read_rejected
        read_rejected = True
        yield b'{"job_name":"Must not be read"}'

    app = fixtures.upload_app(monkeypatch, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        path = f"/jobs/{manager.job.job_id}"
        pending = [
            asyncio.create_task(client.patch(path, content=held_body(index)))
            for index in range(capacity)
        ]
        try:
            for event in entered:
                await asyncio.wait_for(event.wait(), 5)
            rejected = await client.patch(path, content=rejected_body())
            assert rejected.status_code == 503, rejected.text
            assert not read_rejected
            assert len(opened) == capacity
            assert all(not source.closed for source in opened)
        finally:
            release.set()
            completed = await asyncio.gather(*pending)
        assert all(response.status_code == 200 for response in completed)
        assert all(source.closed for source in opened)
        retry = await client.patch(path, json={"job_name": "Retry"})
        assert retry.status_code == 200, retry.text


async def test_smaller_aggregate_budget_bounds_a_value_and_can_be_increased(
    monkeypatch, manager
):
    monkeypatch.setenv("ULTIMA_MPS_UPLOAD_MAX_INFLIGHT_BYTES", "64")
    app = fixtures.upload_app(monkeypatch, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        path = f"/jobs/{manager.job.job_id}"
        response = await client.patch(path, json={"job_name": "x" * 100})
        assert response.status_code == 413, response.text
        assert manager.job.name == "Upload fixture"
        monkeypatch.setenv("ULTIMA_MPS_UPLOAD_MAX_INFLIGHT_BYTES", "128")
        response = await client.patch(path, json={"job_name": "x" * 100})
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("name", ["CONCURRENCY", "MAX_INFLIGHT_BYTES"])
@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
async def test_invalid_upload_setting_fails_before_opening_file(
    monkeypatch, manager, name, value
):
    variable = f"ULTIMA_MPS_UPLOAD_{name}"
    monkeypatch.setenv(variable, value)

    def temporary(**kwargs):
        pytest.fail("Invalid admission settings opened a temporary file")

    monkeypatch.setattr(job_update_body.tempfile, "TemporaryFile", temporary)
    app = fixtures.upload_app(monkeypatch, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        with pytest.raises(ValueError, match=variable):
            await client.patch(f"/jobs/{manager.job.job_id}", json={})


@pytest.mark.parametrize("failure", ["disconnect", "parse", "staging"])
async def test_failed_upload_releases_capacity(monkeypatch, manager, failure):
    app = fixtures.upload_app(monkeypatch, manager)
    update = manager.update_job_by_id

    async def fail_update(*args, **kwargs):
        raise RuntimeError("Staging failed")

    async def disconnected_body():
        yield b'{"job_name":'
        raise ClientDisconnect()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        path = f"/jobs/{manager.job.job_id}"
        if failure == "disconnect":
            with pytest.raises(ClientDisconnect):
                await client.patch(path, content=disconnected_body())
        elif failure == "parse":
            assert (await client.patch(path, content=b'{"tasks":[')).status_code == 422
        else:
            manager.update_job_by_id = fail_update
            response = await client.patch(path, json={"job_name": "Failure"})
            assert response.status_code == 400
            assert "Staging failed" in response.text
            manager.update_job_by_id = update
        response = await client.patch(path, json={"job_name": "Recovered"})
        assert response.status_code == 200, response.text


async def test_capacity_is_retained_through_staging(monkeypatch, manager):
    entered = asyncio.Event()
    release = asyncio.Event()
    update = manager.update_job_by_id

    async def held_update(*args, **kwargs):
        if not entered.is_set():
            entered.set()
            await release.wait()
        return await update(*args, **kwargs)

    manager.update_job_by_id = held_update
    app = fixtures.upload_app(monkeypatch, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        path = f"/jobs/{manager.job.job_id}"
        pending = asyncio.create_task(client.patch(path, json={"job_name": "Held"}))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            response = await client.patch(path, json={"job_name": "Too early"})
            assert response.status_code == 503, response.text
        finally:
            release.set()
            assert (await pending).status_code == 200
        response = await client.patch(path, json={"job_name": "After staging"})
        assert response.status_code == 200, response.text


async def test_tempfile_open_failure_releases_capacity(monkeypatch, manager):
    real_file = job_update_body.tempfile.TemporaryFile
    first = True

    def temporary(**kwargs):
        nonlocal first
        if first:
            first = False
            raise OSError("Fixture storage unavailable")
        return real_file(**kwargs)

    monkeypatch.setattr(job_update_body.tempfile, "TemporaryFile", temporary)
    app = fixtures.upload_app(monkeypatch, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        path = f"/jobs/{manager.job.job_id}"
        with pytest.raises(OSError, match="Fixture storage unavailable"):
            await client.patch(path, json={})
        response = await client.patch(path, json={"job_name": "Storage recovered"})
        assert response.status_code == 200, response.text


async def test_cancelled_write_keeps_capacity_until_file_is_closed(monkeypatch, manager):
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    real_file = job_update_body.tempfile.TemporaryFile
    first = True

    class HeldFile:
        def __init__(self, source):
            self.source = source

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.source.close()
            closed.set()

        def write(self, body):
            entered.set()
            assert release.wait(5)
            assert not self.source.closed
            return self.source.write(body)

    def temporary(**kwargs):
        nonlocal first
        source = real_file(**kwargs)
        if first:
            first = False
            return HeldFile(source)
        return source

    monkeypatch.setattr(job_update_body.tempfile, "TemporaryFile", temporary)
    app = fixtures.upload_app(monkeypatch, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        path = f"/jobs/{manager.job.job_id}"
        pending = asyncio.create_task(client.patch(path, json={}))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            pending.cancel()
            await asyncio.sleep(0)
            assert not closed.is_set()
            response = await client.patch(path, json={"job_name": "Too early"})
            assert response.status_code == 503, response.text
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await pending
        assert closed.is_set()
        response = await client.patch(path, json={"job_name": "After cleanup"})
        assert response.status_code == 200, response.text
