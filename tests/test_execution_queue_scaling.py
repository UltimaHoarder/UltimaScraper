"""Queue storage and bounded history reads, only in the owned PostgreSQL fixture."""

import importlib.util
import json
import os
import statistics
import time
from pathlib import Path

import pytest
from alembic import op
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, insert, text
from test_execution_ledger import (
    claim,
    finish,
    ledger,
    ledger_engine,
    postgres_engine,
    submit,
    task,
)
from ultima_scraper_backend.job_system.ledger import _dump
from ultima_scraper_backend.job_system.models import TaskResult, TaskState
from ultima_scraper_backend.job_system.storage import _task_to_central_row
from ultima_scraper_db_archive.global_db import CentralTaskModel

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def _migration(connection, action="upgrade"):
    path = (
        Path(__file__).resolve().parents[2]
        / "UltimaDatabases/UltimaScraperDBArchive/ultima_scraper_db_archive/migrations/alembic/versions/9e7c3a1d6b20_narrow_execution_queue.py"
    )
    spec = importlib.util.spec_from_file_location("queue_storage_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = MigrationContext.configure(connection)
    with context.begin_transaction(), Operations.context(context):
        getattr(module, action)()


def _nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from _nodes(child)


def test_task_pages_merge_overlap_and_preserve_offsets_and_byte_cursors(ledger):
    ids = [f"task-{i:03}" for i in range(13)]
    submit(ledger, [task(identity, user_id=i + 1) for i, identity in enumerate(ids)])
    ledger.tick()
    finish(ledger, claim(ledger))
    ledger.archive_tick()
    # The same ID can exist in input definitions, the resident window, and
    # history during transitions. Bounded per-source reads must still dedup.
    with ledger.session_factory() as session:
        session.execute(
            insert(CentralTaskModel), [_task_to_central_row(task(ids[2]), "job-test")]
        )
        session.commit()
    for offset in (0, 2, 7):
        cursor, seen = "", []
        for page_number in range(8):
            page = ledger.task_page(
                "job-test",
                after=cursor,
                offset=offset if page_number == 0 else 0,
                limit=3,
            )
            seen.extend(row["task_id"] for row in page["tasks"])
            if not page["has_more"]:
                break
            cursor = page["next_cursor"].removeprefix("ledger:")
        assert seen == ids[offset:]
    first_size = len(_dump(ledger.task("job-test", ids[0])))
    first = ledger.task_page("job-test", limit=3, max_bytes=first_size + 1)
    assert [row["task_id"] for row in first["tasks"]] == ids[:1]
    second = ledger.task_page(
        "job-test", after=first["next_cursor"].removeprefix("ledger:"), limit=3
    )
    assert [row["task_id"] for row in second["tasks"]] == ids[1:4]


def test_task_page_reads_bounded_history_candidates(ledger, ledger_engine):
    submit(ledger, [task()])
    with ledger_engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO management.job_tasks (task_id,job_id,task_type,status)
            SELECT 'history-'||lpad(n::text,8,'0'),'job-test','scrape','completed'
            FROM generate_series(1,100000) n
        """)
        )
        connection.execute(text("ANALYZE management.job_tasks"))
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        if "UNION" in statement and "task_id" in statement:
            statements.append((statement, parameters))

    event.listen(ledger_engine, "before_cursor_execute", capture)
    try:
        page = ledger.task_page("job-test", after="history-00050000", limit=100)
    finally:
        event.remove(ledger_engine, "before_cursor_execute", capture)
    assert [row["task_id"] for row in page["tasks"]] == [
        f"history-{i:08}" for i in range(50001, 50101)
    ]
    assert page["has_more"]
    assert len(statements) == 1
    statement, parameters = statements[0]
    with ledger_engine.connect() as connection:
        result = connection.exec_driver_sql(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + statement, parameters
        ).scalar_one()[0]
    nodes = list(_nodes(result["Plan"]))
    # Every history/definition scan returns at most one source page. The old
    # UNION plan scanned and hashed the whole history before LIMIT.
    history_scans = [
        n for n in nodes if n.get("Relation Name", "").startswith("job_tasks")
    ]
    assert history_scans
    assert all(n["Actual Rows"] <= 101 for n in history_scans)
    assert all(
        n["Actual Rows"] <= 303
        for n in nodes
        if n["Node Type"] in {"Sort", "Aggregate"}
    )
    with ledger_engine.connect() as connection:
        old = connection.execute(
            text("""
            EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON)
            SELECT task_id FROM (
              SELECT task_id FROM management.execution_work WHERE run_id='job-test'
              UNION SELECT task_id FROM management.job_tasks WHERE job_id='job-test'
              UNION SELECT task_id FROM management.mps_task_definitions WHERE manifest_id IS NULL
            ) ids WHERE task_id>'history-00050000' ORDER BY task_id LIMIT 101
        """)
        ).scalar_one()[0]
    report = {
        "history_rows": 100000,
        "before_ms": old["Execution Time"],
        "after_ms": result["Execution Time"],
        "before_history_candidates": sum(
            n["Actual Rows"]
            for n in _nodes(old["Plan"])
            if n.get("Relation Name", "").startswith("job_tasks")
        ),
        "after_history_candidates": sum(n["Actual Rows"] for n in history_scans),
    }
    print(json.dumps({"pagination": report}))
    _save_measurement("pagination", report)


def test_queue_storage_migration_and_generic_terminal_plan(ledger, ledger_engine):
    submit(ledger, [task()])
    ledger.tick()
    with ledger_engine.connect() as connection:
        expected = connection.execute(
            text(
                "SELECT run_id,task_id,payload_json FROM management.execution_work_payloads"
            )
        ).all()
        connection.rollback()
        _migration(connection, "downgrade")
        assert (
            connection.execute(
                text(
                    "SELECT run_id,task_id,payload_json FROM management.execution_work"
                )
            ).all()
            == expected
        )
        connection.rollback()
        _migration(connection)
        assert (
            connection.execute(
                text(
                    "SELECT run_id,task_id,payload_json FROM management.execution_work_payloads"
                )
            ).all()
            == expected
        )
        assert connection.scalar(
            text(
                "SELECT bool_and(w.payload_size=octet_length(p.payload_json)) FROM management.execution_work w JOIN management.execution_work_payloads p USING(run_id,task_id)"
            )
        )
        connection.rollback()
        connection.execute(text("SET plan_cache_mode=force_generic_plan"))
        connection.execute(text("SET enable_seqscan=off"))
        connection.execute(
            text(
                "PREPARE queue_terminal(text) AS SELECT task_id,payload_size FROM management.execution_work WHERE run_id=$1 AND state IN ('completed','failed') ORDER BY task_id LIMIT 32"
            )
        )
        plan = connection.execute(
            text("EXPLAIN (FORMAT JSON) EXECUTE queue_terminal('job-test')")
        ).scalar_one()[0]
        assert any(
            n.get("Index Name") == "idx_execution_work_terminal"
            for n in _nodes(plan["Plan"])
        )
        connection.execute(text("DEALLOCATE queue_terminal"))
        connection.rollback()


def test_queue_migration_failure_preserves_legacy_payloads(
    ledger, ledger_engine, monkeypatch
):
    submit(ledger, [task()])
    ledger.tick()
    with ledger_engine.connect() as connection:
        _migration(connection, "downgrade")
        expected = connection.execute(
            text("SELECT run_id,task_id,payload_json FROM management.execution_work")
        ).all()
        connection.rollback()
        original = op.drop_column

        def fail_before_column_removal(*args, **kwargs):
            if args[:2] == ("execution_work", "payload_json"):
                raise RuntimeError("simulated migration interruption")
            return original(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(op, "drop_column", fail_before_column_removal)
            with pytest.raises(RuntimeError, match="simulated migration interruption"):
                _migration(connection)
        assert (
            connection.scalar(
                text("SELECT to_regclass('management.execution_work_payloads')")
            )
            is None
        )
        assert (
            connection.execute(
                text(
                    "SELECT run_id,task_id,payload_json FROM management.execution_work"
                )
            ).all()
            == expected
        )
        connection.rollback()
        _migration(connection)


def test_renew_preserves_payload_version_and_archive_cascades_payload(ledger):
    submit(ledger, [task()])
    ledger.tick()
    owned = claim(ledger)
    with ledger.session_factory() as session:
        before = session.execute(
            text(
                "SELECT ctid::text,payload_json FROM management.execution_work_payloads"
            )
        ).one()
    ledger.renew(owned)
    with ledger.session_factory() as session:
        assert (
            session.execute(
                text(
                    "SELECT ctid::text,payload_json FROM management.execution_work_payloads"
                )
            ).one()
            == before
        )
    # Exact storage bytes remain independent of the original input budget.
    payload = json.dumps(
        {**owned.task, "user_username": "caf\u00e9"}, ensure_ascii=False
    )
    ledger._checkpoint(owned, payload=payload)
    with ledger.session_factory() as session:
        assert session.scalar(
            text("SELECT payload_size FROM management.execution_work")
        ) == len(payload.encode("utf-8"))
    finish(ledger, owned)
    ledger.archive_tick()
    with ledger.session_factory() as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM management.execution_work_payloads")
            )
            == 0
        )


@pytest.mark.skipif(
    os.environ.get("USR_BENCH_QUEUE_STORAGE") != "1",
    reason="opt-in isolated storage benchmark",
)
@pytest.mark.parametrize("order", [("before", "after"), ("after", "before")])
def test_queue_churn_comparison(ledger_engine, order):
    """4k tasks, 48k state updates, 32k payload updates, a pinned reader.

    Both arms retain their old versions. Report total storage as well as the
    metadata heap: moving payloads must not hide its physical cost.
    """
    samples = {}
    with ledger_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        for label in order:
            name = f"management.queue_churn_{label}"
            data = name + "_payloads"
            connection.execute(text(f"DROP TABLE IF EXISTS {name},{data}"))
            payload_column = ",payload_json text NOT NULL" if label == "before" else ""
            connection.execute(
                text(
                    f"CREATE TABLE {name} (run_id text, task_id text, state text,attempt int DEFAULT 0,payload_bytes bigint,payload_size bigint{payload_column}, PRIMARY KEY(run_id,task_id))"
                )
            )
            connection.execute(
                text(f"CREATE INDEX ON {name}(task_id) WHERE state='queued'")
            )
            if label == "after":
                connection.execute(text(f"ALTER TABLE {name} SET (fillfactor=70)"))
                connection.execute(
                    text(
                        f"CREATE TABLE {data} (run_id text,task_id text,payload_json text NOT NULL,PRIMARY KEY(run_id,task_id))"
                    )
                )
            payloads = []
            for i in range(4000):
                item = task(f"task-{i:08}", user_id=i + 1)
                item.state = TaskState.COMPLETED
                item.result = TaskResult(
                    success=True,
                    metrics={"items_saved": 1},
                    message="Profile persisted",
                )
                item.payload = {
                    "proxy_hops": [
                        f"http://route-{i % 107}-{j}.invalid:8080" for j in range(3)
                    ]
                }
                payloads.append(
                    {"task_id": item.task_id, "payload": _dump(item.to_dict())}
                )
            columns = ",payload_json" if label == "before" else ""
            values = ",CAST(:payload AS text)" if label == "before" else ""
            connection.execute(
                text(
                    f"INSERT INTO {name} (run_id,task_id,state,payload_bytes,payload_size{columns}) VALUES ('job-churn',:task_id,'queued',octet_length(CAST(:payload AS text)),octet_length(CAST(:payload AS text)){values})"
                ),
                payloads,
            )
            if label == "after":
                connection.execute(
                    text(f"INSERT INTO {data} VALUES ('job-churn',:task_id,:payload)"),
                    payloads,
                )
            with ledger_engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as reader:
                reader.execute(text(f"SELECT task_id FROM {name} LIMIT 1")).first()
                start = time.perf_counter()
                for cycle in range(12):
                    state = ("running", "persisting", "completed")[cycle % 3]
                    if label == "before":
                        payload_update = (
                            ",payload_json=jsonb_set(payload_json::jsonb,'{attempts}',to_jsonb(attempt+1))::text"
                            if cycle % 3
                            else ""
                        )
                        connection.execute(
                            text(
                                f"UPDATE {name} SET state=:state,attempt=attempt+1{payload_update}"
                            ),
                            {"state": state},
                        )
                    elif cycle % 3:
                        connection.execute(
                            text(
                                f"WITH changed AS (UPDATE {data} SET payload_json=jsonb_set(payload_json::jsonb,'{{attempts}}',to_jsonb(:attempt))::text RETURNING run_id,task_id,octet_length(payload_json) as bytes) UPDATE {name} w SET state=:state,attempt=attempt+1,payload_size=p.bytes FROM changed p WHERE w.run_id=p.run_id AND w.task_id=p.task_id"
                            ),
                            {"state": state, "attempt": cycle + 1},
                        )
                    else:
                        connection.execute(
                            text(f"UPDATE {name} SET state=:state,attempt=attempt+1"),
                            {"state": state},
                        )
                update_s = time.perf_counter() - start
                connection.execute(text(f"ANALYZE {name}"))
                size_expression = (
                    "octet_length(payload_json)"
                    if label == "before"
                    else "payload_size"
                )
                plans = [
                    connection.execute(
                        text(
                            f"EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT count(*),sum(payload_bytes),sum({size_expression}),array_agg(task_id) FROM {name}"
                        )
                    ).scalar_one()[0]
                    for _ in range(5)
                ]
                heap = connection.scalar(text(f"SELECT pg_relation_size('{name}')"))
                total = connection.scalar(
                    text(f"SELECT pg_total_relation_size('{name}')")
                )
                if label == "after":
                    total += connection.scalar(
                        text(f"SELECT pg_total_relation_size('{data}')")
                    )
                    assert connection.scalar(
                        text(
                            f"SELECT bool_and(w.payload_size=octet_length(p.payload_json)) FROM {name} w JOIN {data} p USING(run_id,task_id)"
                        )
                    )
                assert connection.scalar(text(f"SELECT count(*) FROM {name}")) == 4000
                samples[label] = {
                    "heap_bytes": heap,
                    "total_bytes": total,
                    "update_s": update_s,
                    "median_accounting_ms": statistics.median(
                        p["Execution Time"] for p in plans
                    ),
                    "buffer_pages": plans[-1]["Plan"]["Shared Hit Blocks"]
                    + plans[-1]["Plan"]["Shared Read Blocks"],
                }
            connection.execute(text(f"DROP TABLE {name}"))
            if label == "after":
                connection.execute(text(f"DROP TABLE {data}"))
    print(json.dumps({"order": order, "results": samples}))
    _save_measurement("churn-" + "-".join(order), {"order": order, "results": samples})
    assert samples["after"]["heap_bytes"] < samples["before"]["heap_bytes"] / 2
    assert samples["after"]["buffer_pages"] < samples["before"]["buffer_pages"] / 2


def _save_measurement(name, result):
    directory = os.environ.get("USR_QUEUE_SCALING_RESULTS")
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{name}.json").write_text(json.dumps(result, indent=2))
