"""/ws/events sends each connection only its subscribed topics; per-task activity is coalesced."""

import json

import pytest
from ultima_scraper_backend.api.routes import websocket as ws_route
from ultima_scraper_backend.api.routes import websocket_topics as topics


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"type": "log", "message": "x"}, ("logs",)),
        ({"event_type": "finished", "function": "get_user", "arguments": {}}, ("api_hooks",)),
        ({"event": "messages_synced", "chat_user_id": 4}, ("chats",)),
        ({"event": "chats_synced", "auth_id": 1}, ("chats",)),
        ({"event": "chat_message_like"}, ("chats",)),
        ({"type": "job_event", "event": "job_completed", "job_id": "job-1"}, ("jobs", "job:job-1")),
        ({"type": "job_event", "event": "task_completed", "job_id": "job-1"}, ("job:job-1",)),
        ({"event": "scrape_progress", "job_id": "job-1", "status": "completed"}, ("job:job-1",)),
        ({"type": "worker_status", "event": "worker_heartbeat", "id": "worker-1"}, ("system",)),
        ({"type": "queue_depth"}, ("system",)),
    ],
)
def test_event_topics(event, expected):
    assert topics.event_topics(event) == expected


def test_only_known_topics_are_accepted():
    assert topics.valid_topics(["jobs", "job:abc", "bogus", 5, "job:"]) == {"jobs", "job:abc"}
    assert topics.valid_topics("jobs") == frozenset()
    assert len(topics.valid_topics([f"job:{i}" for i in range(100)])) == topics.MAX_TOPICS


def test_per_task_activity_is_coalesced_per_job():
    coalescer = topics.JobChangeCoalescer()
    for _ in range(500):
        coalescer.add({"type": "job_event", "event": "task_completed", "job_id": "job-1"})
    coalescer.add({"event": "scrape_progress", "job_id": "job-1", "status": "completed", "items_scraped": 3})
    coalescer.add({"type": "job_event", "event": "task_started", "job_id": "job-2"})
    changes = {change["job_id"]: change for change in coalescer.drain()}
    assert changes["job-1"]["event"] == "job_changed"
    assert changes["job-1"]["activity"] == {"task_completed": 500, "scrape_progress": 1}
    assert changes["job-1"]["latest"] == {"status": "completed", "items_scraped": 3}
    assert changes["job-2"]["activity"] == {"task_started": 1}
    assert coalescer.drain() == []


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_text(self, message):
        self.sent.append(json.loads(message))


@pytest.mark.asyncio
async def test_broadcast_routes_by_subscription(monkeypatch):
    legacy, jobs, one_job, logs = FakeSocket(), FakeSocket(), FakeSocket(), FakeSocket()
    monkeypatch.setattr(ws_route, "active_connections", {legacy, jobs, one_job, logs})
    monkeypatch.setattr(ws_route, "connection_topics", {
        jobs: frozenset({"jobs"}), one_job: frozenset({"job:job-1"}), logs: frozenset({"logs"}),
    })
    await ws_route.broadcast_event({"type": "job_event", "event": "task_completed", "job_id": "job-1"})
    await ws_route.broadcast_event({"type": "job_event", "event": "job_completed", "job_id": "job-2"})
    await ws_route.broadcast_event({"type": "log", "message": "hello"})

    assert [e["event"] if "event" in e else e["type"] for e in legacy.sent] == ["task_completed", "job_completed", "log"]
    assert [e["event"] for e in jobs.sent] == ["job_completed"]
    assert [e["event"] for e in one_job.sent] == ["task_completed"]
    assert [e["type"] for e in logs.sent] == ["log"]
