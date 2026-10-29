"""Lifecycle payload boundaries and replay contracts, independent of encoding count."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from test_execution_ledger import (  # noqa: F401
    claim,
    ledger,
    ledger_engine,
    submit,
    task,
)
from test_mps_manifest import postgres_engine  # noqa: F401
from ultima_scraper_backend.job_system.ledger import Claim, Limits, _dump
from ultima_scraper_backend.job_system.ledger_batches import (
    _requests,
    completion_request,
)
from ultima_scraper_backend.job_system.models import Task, TaskResult, TaskState
from ultima_scraper_backend.job_system.profile_completion import PROFILE_COMPLETION_KEY


def owned(item, *, intent=None):
    payload = item.to_dict()
    if intent is not None:
        payload[PROFILE_COMPLETION_KEY] = intent
    return Claim("run", item.task_id, "token", "worker", 1, {}, payload)


@pytest.mark.parametrize("state", list(TaskState))
@pytest.mark.parametrize("result_success", [None, False, True])
def test_completion_preserves_canonical_state_and_retry_intent(state, result_success):
    item = task()
    item.state = state
    if result_success is not None:
        item.result = TaskResult(success=result_success, message="fresh", output={"text": 'é\\\"\n'})
        item.completed_at = item.result.completed_at
    intent = {"command_id": "write-a", "nested": {"user_id": 1}}
    request = completion_request(SimpleNamespace(limits=Limits()), owned(item, intent=intent), item, retry=True)
    successful = state == TaskState.COMPLETED and result_success is True
    assert request["success"] == successful
    assert json.loads(request["payload"])["state"] == ("completed" if successful else "failed")
    if successful:
        assert request["retry_payload"] is None
    else:
        pending = json.loads(request["retry_payload"])
        assert pending["state"] == "pending"
        assert pending["result"] is pending["completed_at"] is pending["worker_id"] is None
        assert pending[PROFILE_COMPLETION_KEY] == intent
    assert PROFILE_COMPLETION_KEY not in json.loads(request["payload"])
    item.payload = {"fresh": "second invocation"}
    second = completion_request(SimpleNamespace(limits=Limits()), owned(item), item)
    assert json.loads(second["payload"])["payload"] == item.payload


@pytest.mark.parametrize("overflow", [False, True])
def test_completion_result_boundary_retains_failure_replacement(overflow):
    item = task()
    item.state = TaskState.COMPLETED
    item.result = TaskResult(success=True, output={"escaped": '\"\\é\n' * 1024})
    item.completed_at = item.result.completed_at
    size = len(_dump(item.to_dict()))
    limits = Limits(result_bytes=size - int(overflow))
    request = completion_request(SimpleNamespace(limits=limits), owned(item), item, retry=True)
    payload = json.loads(request["payload"])
    assert request["success"] is (not overflow)
    assert len(request["payload"]) <= limits.result_bytes
    if overflow:
        assert payload["result"]["message"] == "Task result exceeds the execution result byte budget"
        assert payload["subtasks"] == []
        assert request["retry"] is False
        assert request["retry_payload"] is None
    else:
        assert request["payload"] == _dump(item.to_dict())


def test_completion_oversized_input_still_fails_after_result_replacement():
    item = task()
    item.payload = {"input": "x" * 4096}
    with pytest.raises(ValueError, match="Task input exceeds the result page byte budget"):
        completion_request(SimpleNamespace(limits=Limits(result_bytes=2048)), owned(item), item)


def test_lifecycle_budget_counts_escaping_and_retry_payload():
    requests = [
        {"run_id": "run", "task_id": str(i), "payload": _dump({"text": '\"\\é\n' * 32}), "retry_payload": _dump({"retry": "x" * 256})}
        for i in range(2)
    ]
    rows = [{**request, "ordinal": i} for i, request in enumerate(requests)]
    exact = len(_dump(rows))
    assert _requests(SimpleNamespace(limits=Limits(result_bytes=exact)), requests) == rows
    with pytest.raises(ValueError, match="Lifecycle batch exceeds its byte budget"):
        _requests(SimpleNamespace(limits=Limits(result_bytes=exact - 1)), requests)
    assert "ordinal" not in requests[0]


def test_native_mixed_completion_replay_retains_committed_payload(ledger, live_task_events):  # noqa: F811
    submit(ledger, [task(f"task-{i}", user_id=i + 1) for i in range(3)])
    ledger.tick()
    claims = [claim(ledger) for _ in range(3)]
    requests = []
    for i, attempt in enumerate(claims):
        item = Task.from_dict(attempt.task)
        item.state = TaskState.COMPLETED
        item.result = TaskResult(success=True, output={"identity": i, "escaped": '\"\\é\n'})
        item.completed_at = item.result.completed_at
        requests.append(completion_request(ledger, attempt, item))
        if i == 0:
            ledger.finish(attempt, item)
    assert ledger.finish_batch(requests) == [None] * 3
    for request in requests:
        request["payload"] = _dump({"state": "failed", "result": {"output": "must not overwrite"}})
    assert ledger.finish_batch(requests) == [None] * 3
    for i, attempt in enumerate(claims):
        assert ledger.task(attempt.run_id, attempt.task_id)["result"]["output"]["identity"] == i
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.execution_attempts WHERE state='completed'")) == 3
        assert session.scalar(text("SELECT count(*) FROM management.execution_outbox WHERE CAST(payload_json AS json)->>'event'='task_completed'")) == 0
        # Replays publish nothing new: each completion is announced once, live.
        assert [e["event"] for e in live_task_events].count("task_completed") == 3
        assert session.scalar(text("SELECT count(*) FROM management.execution_resources")) == 0


@pytest.mark.parametrize("batched", [False, True])
@pytest.mark.parametrize("state,result_success", [(TaskState.COMPLETED, True), (TaskState.COMPLETED, False), (TaskState.RUNNING, True)])
def test_native_finish_stores_canonical_result_at_exact_budget(ledger, batched, state, result_success):  # noqa: F811
    submit(ledger, [task()])
    ledger.tick()
    attempt = claim(ledger)
    item = Task.from_dict(attempt.task)
    item.state = state
    item.result = TaskResult(success=result_success, output={"escaped": '\"\\é\n' * 32})
    item.completed_at = item.result.completed_at
    ledger.limits = replace(ledger.limits, result_bytes=len(_dump(item.to_dict())))
    if batched:
        assert ledger.finish_batch([completion_request(ledger, attempt, item)]) == [None]
    else:
        ledger.finish(attempt, item)
    expected = "completed" if state == TaskState.COMPLETED and result_success else "failed"
    stored = ledger.task(attempt.run_id, attempt.task_id)
    assert stored["state"] == expected
    assert stored["result"]["output"] == item.result.output

