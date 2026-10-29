"""Workers publish at most one progress event per job per second, ending on the newest state."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from ultima_scraper_backend.job_system.handlers.scrape import events


@pytest.fixture
def published(monkeypatch):
    sent = []

    async def publish(channel, payload):
        sent.append(json.loads(payload))

    monkeypatch.setattr(events, "PROGRESS_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(events, "_last_progress", {})
    monkeypatch.setattr(events, "_pending_progress", {})
    storage = SimpleNamespace(redis=SimpleNamespace(client=SimpleNamespace(publish=publish)))
    return storage, sent


@pytest.mark.asyncio
async def test_progress_is_throttled_per_job_and_flushes_the_latest(published):
    storage, sent = published
    for index in range(100):
        await events.publish_hook_event(storage, {"event": "scrape_progress", "job_id": "job-1", "index": index})
    await events.publish_hook_event(storage, {"event": "scrape_progress", "job_id": "job-2", "index": 0})
    assert [(e["job_id"], e["index"]) for e in sent] == [("job-1", 0), ("job-2", 0)]
    await asyncio.sleep(0.12)
    assert [(e["job_id"], e["index"]) for e in sent] == [("job-1", 0), ("job-2", 0), ("job-1", 99)]


@pytest.mark.asyncio
async def test_other_events_are_never_throttled(published):
    storage, sent = published
    for _ in range(3):
        await events.publish_hook_event(storage, {"event": "job_completed", "job_id": "job-1"})
        await events.publish_hook_event(storage, {"event": "scrape_progress"})  # no job: not throttled
    assert len(sent) == 6
