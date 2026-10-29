"""Busy deletion passes continue; unchanged or blocked checkpoints back off."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ultima_scraper_backend.database.receipt_retention import ReceiptQueueSnapshot
from ultima_scraper_backend.services import job_deletion


@pytest.mark.parametrize("before,after,advanced", [
    ({"rows": 512}, {"rows": 1024}, True),
    ({"rows": 0, "identity_sweep_cursor": "(128,0)"},
     {"rows": 0, "identity_sweep_cursor": "(256,0)"}, True),
    ({"receipt_cursor": "a"}, {"receipt_cursor": "b"}, True),
    ({"completed_stages": 8}, {"completed_stages": 9}, True),
    ({"partitions_dropped": 1}, {"partitions_dropped": 2}, True),
    ({"rows": 512}, {"rows": 512, "error": "Waiting for writer lock",
                     "updated_at": "later"}, False),
    (None, {"error": "Waiting for writer inventory"}, False),
    ({"rows": 512, "receipt_cursor": None},
     {"rows": 512, "receipt_cursor": None}, False),
])
def test_pass_recognizes_durable_progress_without_spinning_on_errors(
    monkeypatch, before, after, advanced,
):
    lease = SimpleNamespace(scalar=Mock(side_effect=[True, before, after]),
                            scalars=Mock(return_value=["job-pending"]))

    @contextmanager
    def factory():
        yield lease

    ledger = SimpleNamespace(delete=Mock(return_value=None))
    monkeypatch.setattr(job_deletion, "ExecutionLedger", lambda _: ledger)
    result = job_deletion._cleanup_pass(factory, receipt_queue=ReceiptQueueSnapshot())
    assert result.finished == ()
    assert result.advanced is advanced


def test_losing_the_cluster_lease_is_an_idle_pass():
    lease = SimpleNamespace(scalar=Mock(return_value=False))

    @contextmanager
    def factory():
        yield lease

    assert job_deletion._cleanup_pass(factory) == job_deletion._DeletionPass()
    assert lease.scalar.call_count == 1


@pytest.mark.asyncio
async def test_worker_refreshes_inventory_without_idle_delay_until_progress_stops(monkeypatch):
    inventory = AsyncMock(side_effect=[ReceiptQueueSnapshot(), ReceiptQueueSnapshot()])
    runner = AsyncMock(side_effect=[
        job_deletion._DeletionPass(("job-finished",), True),
        job_deletion._DeletionPass(),
    ])
    delete_projection = AsyncMock()
    monkeypatch.setattr(job_deletion, "pending_write_inventory", inventory)
    monkeypatch.setattr(job_deletion, "run_database_call", runner)
    monkeypatch.setattr(job_deletion, "JobStorage", lambda _: SimpleNamespace(delete_job=delete_projection))
    delays = []

    async def sleep(delay):
        delays.append(delay)
        if delay == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(job_deletion.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await job_deletion.run_deletion_worker(SimpleNamespace())
    assert delays == [0, 2]
    assert inventory.await_count == 2
    assert runner.await_count == 2
    assert all(call.args == (job_deletion._cleanup_pass,) for call in runner.await_args_list)
    delete_projection.assert_awaited_once_with("job-finished")
