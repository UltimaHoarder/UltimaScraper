"""Resource eligibility must retain exact lease boundaries and keyed identity."""

from datetime import timedelta

import pytest
from sqlalchemy import event, text
from test_execution_ledger import (
    ledger,
    ledger_engine,
    postgres_engine,
    submit,
    task,
)
from ultima_scraper_backend.job_system import ledger as ledger_module

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


@pytest.mark.parametrize("offset", [None, -1, 0, 1])
def test_resource_lease_boundary_preserves_claim_eligibility(ledger, monkeypatch, offset):
    submit(ledger, [task()])
    ledger.tick()
    with ledger.session_factory() as session:
        now = session.scalar(text("SELECT clock_timestamp()"))
        key = session.scalar(text("SELECT dedup_key FROM management.execution_work"))
        if offset is not None:
            session.execute(text("""
                INSERT INTO management.execution_resources
                    (resource_key,token,run_id,task_id,lease_until)
                VALUES (:key,'other-token','job-test','other-task',:until)
            """), {"key": key, "until": now + timedelta(seconds=offset)})
            session.commit()
    monkeypatch.setattr(ledger_module, "_now", lambda session: now)
    claims = ledger.claim_many(owner="new-worker", backend_id="backend-a",
                               capabilities=["onlyfans"], count=1)
    assert bool(claims) is (offset is None or offset <= 0)
    if claims:
        with ledger.session_factory() as session:
            assert session.scalar(text("SELECT token FROM management.execution_resources WHERE resource_key=:key"),
                                  {"key": key}) == claims[0].token


def test_unrelated_active_resource_does_not_block_ready_identity(ledger):
    submit(ledger, [task()])
    ledger.tick()
    with ledger.session_factory() as session:
        session.execute(text("""
            INSERT INTO management.execution_resources
                (resource_key,token,run_id,task_id,lease_until)
            SELECT 'unrelated-'||n,'other-token','job-test','other-task',
                   clock_timestamp()+interval '1 hour'
            FROM generate_series(1,5000) n
        """))
        session.execute(text("ANALYZE management.execution_resources"))
        session.execute(text("ANALYZE management.execution_work"))
        session.commit()
    claims = ledger.claim_many(owner="new-worker", backend_id="backend-a",
                               capabilities=["onlyfans"], count=1)
    assert [claim.task_id for claim in claims] == ["task-a"]


def test_empty_resource_key_keeps_original_eligibility(ledger):
    submit(ledger, [task()])
    ledger.tick()
    with ledger.session_factory() as session:
        session.execute(text("UPDATE management.execution_work SET dedup_key=''"))
        session.commit()
    claims = ledger.claim_many(owner="new-worker", backend_id="backend-a",
                               capabilities=["onlyfans"], count=1)
    assert [claim.task_id for claim in claims] == ["task-a"]
    with ledger.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.execution_resources")) == 0


def test_claim_jit_is_off_only_inside_owned_transaction(ledger, ledger_engine):
    submit(ledger, [task()])
    ledger.tick()
    with ledger.session_factory() as session:
        before = session.scalar(text("SHOW jit"))
    observed = []

    def inspect_setting(conn, cursor, statement, parameters, context, many):
        if statement == "SET LOCAL jit=off":
            with cursor.connection.cursor() as probe:
                probe.execute("SHOW jit")
                observed.append(probe.fetchone()[0])

    event.listen(ledger_engine, "after_cursor_execute", inspect_setting)
    try:
        claims = ledger.claim_many(owner="new-worker", backend_id="backend-a",
                                   capabilities=["onlyfans"], count=1)
    finally:
        event.remove(ledger_engine, "after_cursor_execute", inspect_setting)
    assert len(claims) == 1
    assert observed == ["off"]
    with ledger.session_factory() as session:
        assert session.scalar(text("SHOW jit")) == before


def test_claim_jit_resets_after_transaction_failure(ledger, ledger_engine):
    submit(ledger, [task()])
    ledger.tick()
    with ledger.session_factory() as session:
        before = session.scalar(text("SHOW jit"))

    def fail_after_setting(conn, cursor, statement, parameters, context, many):
        if statement == "SET LOCAL jit=off":
            raise RuntimeError("owned claim fault")

    event.listen(ledger_engine, "after_cursor_execute", fail_after_setting)
    try:
        with pytest.raises(RuntimeError, match="owned claim fault"):
            ledger.claim_many(owner="new-worker", backend_id="backend-a",
                              capabilities=["onlyfans"], count=1)
    finally:
        event.remove(ledger_engine, "after_cursor_execute", fail_after_setting)
    with ledger.session_factory() as session:
        assert session.scalar(text("SHOW jit")) == before
    assert ledger.stats("job-test")["inflight"] == 0
