"""Completion must plan only the requested job's attempt history partitions."""

import pytest
from sqlalchemy import text
from test_execution_ledger import claim, ledger, ledger_engine, postgres_engine, submit, task
from test_history_partition_admission import partitioned_engine
from ultima_scraper_backend.database.job_partitions import partition_name
from ultima_scraper_backend.job_system.ledger import _FINISH_ATTEMPT_SQL
from ultima_scraper_backend.job_system.ledger_batches import (
    _FINISH,
    _encoded_requests,
    completion_request,
    finish_batch,
)
from ultima_scraper_backend.job_system.models import Task, TaskResult, TaskState

__all__ = ["ledger", "ledger_engine", "postgres_engine", "partitioned_engine"]


@pytest.mark.parametrize("batched", [False, True])
def test_completion_prunes_attempt_locks_and_preserves_replay(
    ledger, partitioned_engine, batched
):
    for index in range(4):
        submit(ledger, [task(user_id=index + 1)], identity=f"job-pruning-{index}")
    ledger.tick()
    owned = claim(ledger)
    assert owned is not None
    item = Task.from_dict(owned.task)
    item.state = TaskState.COMPLETED
    item.result = TaskResult(success=True, output={"value": 7})
    item.completed_at = item.result.completed_at
    request = completion_request(ledger, owned, item)
    if batched:
        _, encoded = _encoded_requests(ledger, [request])
        statement = _FINISH
        params = {"requests": encoded, "history_run_ids": [owned.run_id]}
    else:
        statement = _FINISH_ATTEMPT_SQL
        params = request

    with partitioned_engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("EXPLAIN (FORMAT JSON) " + str(statement)), params)
        locked_leaves = set(connection.execute(text("""
            SELECT c.relname FROM pg_locks l
            JOIN pg_class c ON c.oid=l.relation
            JOIN pg_inherits i ON i.inhrelid=c.oid
            WHERE l.pid=pg_backend_pid()
              AND i.inhparent='management.execution_attempts'::regclass
        """)).scalars())
        assert locked_leaves == {partition_name(owned.run_id, "execution_attempts")}

    if batched:
        assert finish_batch(ledger, [request]) == [None]
        assert finish_batch(ledger, [request]) == [None]
    else:
        ledger.finish(owned, item)
        ledger.finish(owned, item)
    with partitioned_engine.connect() as connection:
        assert connection.scalar(text("""
            SELECT state FROM management.execution_attempts
            WHERE run_id=:run_id AND task_id=:task_id AND number=:number
        """), request) == "completed"
