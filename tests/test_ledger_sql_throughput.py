"""Exercise hot-path SQL plans and attempt fences on an owned PostgreSQL cluster."""

# ruff: noqa: F811 - pytest discovers imported fixtures by their original names

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import event, text
from test_execution_ledger import (  # noqa: F401
    claim,
    finish,
    ledger,
    ledger_engine,
    submit,
    task,
)
from test_mps_manifest import postgres_engine  # noqa: F401


def plan_nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from plan_nodes(child)


def plans_for(engine, statements):
    with engine.connect() as connection:
        for statement, parameters in statements:
            plan = connection.exec_driver_sql(
                "EXPLAIN (FORMAT JSON) " + statement, parameters
            ).scalar_one()[0]["Plan"]
            yield list(plan_nodes(plan))


@pytest.mark.parametrize("operation", ["renew", "progress", "finish", "recover"])
@pytest.mark.parametrize("replacement", [False, True])
def test_resource_mutations_use_primary_key_and_preserve_replacement(
    ledger, ledger_engine, operation, replacement
):
    submit(ledger, [task()])
    ledger.tick()
    owned = claim(ledger)
    with ledger_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO management.execution_resources "
                "(resource_key,token,run_id,task_id,lease_until) "
                "SELECT 'unrelated-'||n, 'other-'||n, 'job-test', 'other-'||n, "
                "clock_timestamp()+interval '1 hour' FROM generate_series(1,10000) n"
            )
        )
        if replacement:
            connection.execute(
                text(
                    "UPDATE management.execution_resources SET token='replacement' "
                    "WHERE token=:token"
                ),
                {"token": owned.token},
            )
        if operation == "recover":
            connection.execute(
                text(
                    "UPDATE management.execution_work "
                    "SET lease_until=clock_timestamp()-interval '1 second'"
                )
            )
        connection.execute(text("ANALYZE management.execution_resources"))
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if any(
            mutation in statement
            for mutation in (
                "UPDATE management.execution_resources",
                "DELETE FROM management.execution_resources",
            )
        ):
            statements.append((statement, parameters))

    event.listen(ledger_engine, "after_cursor_execute", capture)
    try:
        if operation == "renew":
            assert ledger.renew(owned)
        elif operation == "progress":
            ledger.progress(owned, owned.task, persisting=True, renew=True)
        elif operation == "finish":
            finish(ledger, owned)
        else:
            assert ledger.recover_expired() == 1
    finally:
        event.remove(ledger_engine, "after_cursor_execute", capture)
    assert len(statements) == 1
    (nodes,) = list(plans_for(ledger_engine, statements))
    assert any(node.get("Index Name") == "execution_resources_pkey" for node in nodes)
    assert not any(node["Node Type"] == "Seq Scan" for node in nodes)
    with ledger_engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM management.execution_resources WHERE resource_key LIKE 'unrelated-%'"
                )
            )
            == 10000
        )
        replacements = connection.scalar(
            text(
                "SELECT count(*) FROM management.execution_resources WHERE token='replacement'"
            )
        )
        assert replacements == int(replacement)


def test_relay_uses_pending_index_with_large_delivered_history(ledger, ledger_engine):
    submit(ledger, [task()])
    with ledger_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO management.execution_outbox (run_id,payload_json,delivered) "
                "SELECT 'job-test','{}',true FROM generate_series(1,25000)"
            )
        )
        connection.execute(text("ANALYZE management.execution_outbox"))
    statements, received = [], []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT management.execution_outbox."):
            statements.append((statement, parameters))

    event.listen(ledger_engine, "after_cursor_execute", capture)
    try:
        assert ledger.relay(received.append) > 0
        assert ledger.relay(received.append) == 0
    finally:
        event.remove(ledger_engine, "after_cursor_execute", capture)
    assert received
    for nodes in plans_for(ledger_engine, statements):
        assert any(
            node.get("Index Name") == "idx_execution_outbox_pending" for node in nodes
        )
        assert not any(node["Node Type"] == "Seq Scan" for node in nodes)


def test_claim_uses_ordered_index_without_sorting_the_full_window(
    ledger, ledger_engine
):
    ledger.limits = replace(ledger.limits, tasks=10000, global_tasks=10000, batch=100)
    submit(ledger, [task()])
    ledger.tick()
    with ledger_engine.begin() as connection:
        template = connection.scalar(
            text("SELECT payload_json FROM management.execution_work_payloads LIMIT 1")
        )
        connection.execute(
            text(
                "INSERT INTO management.execution_work "
                "(run_id,task_id,state,lane,site,capabilities,dedup_key,payload_json,payload_bytes) "
                "SELECT 'job-test','filler-'||lpad(n::text,5,'0'),'queued','scrape','onlyfans',"
                "ARRAY['onlyfans']::text[],'dedup-'||n,:payload,length(:payload) "
                "FROM generate_series(1,9999) n"
            ),
            {"payload": template},
        )
        connection.execute(text("ANALYZE management.execution_work"))
        connection.execute(
            text(
                "INSERT INTO management.execution_resources "
                "(resource_key,token,run_id,task_id,lease_until) "
                "SELECT 'busy-'||n, 'other-'||n, 'job-test', 'other-'||n, "
                "clock_timestamp()+interval '1 hour' FROM generate_series(1,10000) n"
            )
        )
        connection.execute(text("ANALYZE management.execution_resources"))
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if (
            statement.startswith("SELECT management.execution_work.")
            and "SKIP LOCKED" in statement
        ):
            statements.append((statement, parameters))

    event.listen(ledger_engine, "after_cursor_execute", capture)
    try:
        claims = ledger.claim_many(
            owner="worker-a",
            backend_id="backend-a",
            capabilities=["onlyfans"],
            count=100,
        )
    finally:
        event.remove(ledger_engine, "after_cursor_execute", capture)
    assert len(claims) == len({owned.task_id for owned in claims}) == 100
    assert len(statements) == 1
    for nodes in plans_for(ledger_engine, statements):
        assert any(
            node.get("Index Name") == "idx_execution_work_claim_order" for node in nodes
        )
        assert not any(node["Node Type"] == "Sort" for node in nodes)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_job_search_sql_has_local_deadline_and_reports_timeout(
    ledger_engine, monkeypatch, timeout
):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from fastapi import HTTPException
    from sqlmodel import Session
    from ultima_scraper_backend.api.routes import jobs
    from ultima_scraper_db_archive import global_db

    observed = []

    class SearchSession(Session):
        def exec(self, statement, *args, **kwargs):
            if str(statement).startswith("SELECT count("):
                observed.append(
                    self.execute(text("SHOW statement_timeout")).scalar_one()
                )
                if timeout:
                    # Exercise PostgreSQL's actual cancellation and the route's
                    # SQLAlchemy error handling without waiting fifteen seconds.
                    self.execute(text("SET LOCAL statement_timeout='20ms'"))
                    self.execute(text("SELECT pg_sleep(0.1)"))
            return super().exec(statement, *args, **kwargs)

    @contextmanager
    def sessions():
        with SearchSession(ledger_engine) as session:
            yield session

    monkeypatch.setattr(global_db, "global_session", sessions)
    options = {
        "search": "missing-search-needle",
        "status": None,
        "include_tasks": False,
        "include_api_commands": False,
        "page": 1,
        "page_size": 50,
        "backend": SimpleNamespace(redis=None),
    }
    if timeout:
        with pytest.raises(HTTPException) as caught:
            await jobs.list_jobs(**options)
        assert caught.value.status_code == 504
    else:
        response = await jobs.list_jobs(**options)
        assert response.jobs == [] and response.total == 0
    assert observed == ["15s"]
    with Session(ledger_engine) as session:
        assert session.execute(text("SHOW statement_timeout")).scalar_one() == "0"
