"""Set-based claims write and return exactly what the ORM claim path does."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import event, text
from test_execution_ledger import ledger, ledger_engine, postgres_engine, submit, task
from ultima_scraper_backend.job_system.ledger import ExecutionLedger, Limits

__all__ = ["ledger", "ledger_engine", "postgres_engine"]

RUN = "job-claims"
# Users 2 and 5 repeat (in-batch dedup); user 3's resource is already leased.
USERS = [1, 2, 2, 3, 4, 5, 5, 6, 7, 8, 9, 10]
TRUNCATE = (
    "TRUNCATE management.execution_outbox, management.execution_resources, "
    "management.execution_attempts, management.execution_work, management.execution_runs, "
    "management.execution_definitions, management.mps_retry_tasks, management.mps_task_definitions, "
    "management.mps_candidate_ranges, management.mps_plans, management.job_tasks, management.jobs, "
    "management.database_write_receipts CASCADE"
)


def _planner(ledger):
    return ExecutionLedger(
        ledger.session_factory, limits=Limits(tasks=32, global_tasks=64, batch=16, planner_batch=32)
    )


def _claim_round(ledger, monkeypatch, set_claims):
    monkeypatch.setenv("ULTIMA_LEDGER_SET_CLAIMS", "1" if set_claims else "0")
    with ledger.session_factory() as session:
        session.execute(text(TRUNCATE))
        session.execute(text("UPDATE management.execution_feed SET next_sequence=1"))
        session.commit()
    planner = _planner(ledger)
    submit(planner, [task(f"t-{index:02d}", user_id=user) for index, user in enumerate(USERS)], identity=RUN)
    planner.tick(refill_only=True)
    leased_key = task("t-03", user_id=3).dedup_key
    with ledger.session_factory() as session:
        session.execute(text("""
            INSERT INTO management.execution_resources (resource_key, token, run_id, task_id, lease_until)
            VALUES (:key, 'held-elsewhere', :run, 'other-task', now() + interval '1 hour')
        """), {"key": leased_key, "run": RUN})
        session.commit()
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)

    with ledger.session_factory() as session:
        engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        claims = planner.claim_many(
            owner="worker-a", backend_id="backend-a", capabilities=["onlyfans", "api_commands"], count=16,
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    return claims, _snapshot(ledger), statements


def _snapshot(ledger):
    with ledger.session_factory() as session:
        rows = session.execute(text("""
            SELECT w.task_id, w.state, w.owner, w.attempt, w.payload_size,
                   w.lease_until - a.started_at AS lease, w.token = a.token AS attempt_token,
                   a.number, a.state AS attempt_state, a.owner AS attempt_owner, a.timings_json,
                   a.completed_at, a.error, a.started_at, p.payload_json,
                   r.token = w.token AS resource_token, r.lease_until - a.started_at AS resource_lease
            FROM management.execution_work w
            JOIN management.execution_work_payloads p USING (run_id, task_id)
            LEFT JOIN management.execution_attempts a USING (run_id, task_id)
            LEFT JOIN management.execution_resources r ON r.resource_key = w.dedup_key AND r.task_id = w.task_id
            WHERE w.run_id = :run ORDER BY w.task_id
        """), {"run": RUN}).mappings().all()
        run = session.execute(text(
            "SELECT r.state, r.started_at IS NOT NULL, j.status, j.started_at IS NOT NULL "
            "FROM management.execution_runs r JOIN management.jobs j ON j.job_id = r.run_id WHERE r.run_id = :run"
        ), {"run": RUN}).one()
    snapshot = []
    for row in rows:
        row = dict(row)
        payload = json.loads(row.pop("payload_json"))
        started = row.pop("started_at")
        if started is not None:
            # The claim stamps the payload with the attempt's own start time.
            assert payload["started_at"] == payload["updated_at"] == started.isoformat()
            payload["started_at"] = payload["updated_at"] = "<attempt start>"
        # Each submission gets its own manifest ID, and an unclaimed task keeps
        # its admission time: both differ between the two rounds by design.
        for key in ("created_at", "job_id", "mps_task_manifest"):
            payload.pop(key, None)
        if started is None:
            payload.pop("updated_at", None)
        snapshot.append({**row, "payload": payload})
    return {"rows": snapshot, "run": tuple(run)}


def _claims(claims, snapshot):
    tokens = {row["task_id"]: row["attempt_token"] for row in snapshot["rows"]}
    normalized = []
    for claim in claims:
        task_view = {key: value for key, value in claim.task.items()
                     if key not in ("created_at", "updated_at", "job_id", "mps_task_manifest")}
        assert claim.job["metadata"]["total_tasks_count_override"] == len(USERS)
        normalized.append((claim.run_id, claim.task_id, claim.owner, claim.number,
                           tokens[claim.task_id], task_view, sorted(claim.job)))
    return normalized


def test_set_claims_match_the_orm_claim_path(ledger, monkeypatch):
    orm_claims, orm_rows, orm_sql = _claim_round(ledger, monkeypatch, set_claims=False)
    set_claims, set_rows, set_sql = _claim_round(ledger, monkeypatch, set_claims=True)

    assert len(orm_claims) == len(set_claims) == len(USERS) - 3  # two duplicates, one leased
    assert set_rows == orm_rows
    assert _claims(set_claims, set_rows) == _claims(orm_claims, orm_rows)
    claimed = [row for row in set_rows["rows"] if row["state"] == "running"]
    assert all(row["lease"] == timedelta(seconds=ledger.limits.lease_seconds) or row["lease"] > timedelta(0) for row in claimed)
    assert set_rows["run"] == (("running", True, "running", True))
    # The same number of round trips: the saving is the ORM objects and flush
    # bookkeeping, replaced by three fixed-text array statements.
    assert len(set_sql) == len(orm_sql)
    for marker in ("UPDATE management.execution_work w SET", "UPDATE management.execution_work_payloads",
                   "INSERT INTO management.execution_attempts"):
        assert sum(marker in statement for statement in set_sql) == 1


def test_set_claims_are_off_by_default(monkeypatch):
    from ultima_scraper_backend.job_system.ledger import set_claims_enabled

    monkeypatch.delenv("ULTIMA_LEDGER_SET_CLAIMS", raising=False)
    assert set_claims_enabled() is False
    for value, expected in (("1", True), ("on", True), ("0", False), ("off", False), ("", False)):
        monkeypatch.setenv("ULTIMA_LEDGER_SET_CLAIMS", value)
        assert set_claims_enabled() is expected
