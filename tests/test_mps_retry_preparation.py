"""Retry preparation bounds transferred definitions and generated SQL batches."""

import json
import tracemalloc
from contextlib import contextmanager

import pytest
from sqlalchemy import event, text

import test_mps_graph_retry as fixtures
from ultima_scraper_backend.job_system import Job, Task, TaskType

postgres_engine = fixtures.postgres_engine
store = fixtures.store


def source_plan(store, count=3):
    return fixtures.explicit_plan(
        store,
        [
            Task(task_type=TaskType.DOWNLOAD, site_name="OnlyFans", user_id=i + 1)
            for i in range(count)
        ],
    )


def widen(store, source, *, ordinal=None, size=250000, field="payload"):
    if field == "payload":
        expression = "jsonb_set(task_json::jsonb, '{payload,media_ids}', ids.value)"
    elif field == "result":
        expression = "jsonb_set(task_json::jsonb, '{result}', jsonb_build_object('success',true,'output',jsonb_build_object('ids',ids.value)))"
    else:
        assert field == "children"
        expression = "jsonb_set(task_json::jsonb, '{_mps_retry_children}', jsonb_build_array(jsonb_build_object('task_id','unselected-child','task_type','download','site_name','OnlyFans','user_id',2,'payload',jsonb_build_object('paid_content_feed',true,'media_ids',ids.value))))"
    with store.session_factory() as session:
        session.execute(
            text(f"""
            UPDATE management.mps_task_definitions SET task_json=({expression})::text
            FROM (SELECT jsonb_agg(i) value FROM generate_series(1,CAST(:size AS integer)) i) ids
            WHERE manifest_id=:manifest AND (CAST(:ordinal AS bigint) IS NULL OR ordinal=CAST(:ordinal AS bigint))
        """),
            {
                "size": size,
                "manifest": source["selection"]["task_manifest_id"],
                "ordinal": ordinal,
            },
        )
        session.commit()


@contextmanager
def written_batches(store):
    with store.session_factory() as session:
        engine = session.get_bind()
    sizes = []

    def capture(connection, clause, multiparams, params, execution_options):
        if (
            getattr(getattr(clause, "table", None), "name", None)
            == "mps_task_definitions"
            and multiparams
        ):
            sizes.append(
                (
                    len(multiparams),
                    sum(
                        len(row["task_json"].encode())
                        + len(json.dumps(row["dependency_ids"]).encode())
                        for row in multiparams
                    ),
                )
            )

    event.listen(engine, "before_execute", capture)
    try:
        yield sizes
    finally:
        event.remove(engine, "before_execute", capture)


@pytest.mark.parametrize("ordinal", [0, 2])
def test_retry_rejects_wide_definition_before_transfer_and_rolls_back(
    store, monkeypatch, ordinal, record_property
):
    source = source_plan(store)
    widen(store, source, ordinal=ordinal)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "3")
    monkeypatch.setenv("ULTIMA_MPS_RETRY_BATCH_MAX_BYTES", "32768")
    config = Job.create(name="Retry", tasks=[], created_by="test").to_dict()
    error = None
    tracemalloc.start()
    try:
        try:
            fixtures.clone(store, source, config=config)
        except ValueError as exc:
            error = exc
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    record_property("retry_input_peak_bytes", peak)
    assert peak < 2 * 1024 * 1024, f"32-KiB read admission allocated {peak:,} bytes"
    assert error is not None and "budget" in str(error)
    assert store.get(config["job_id"]) is None
    assert store.get(source["job_id"])["status"] == "ready"
    # Increasing the independent budget admits the unchanged durable payload.
    monkeypatch.setenv("ULTIMA_MPS_RETRY_BATCH_MAX_BYTES", str(32 * 1024 * 1024))
    retried = fixtures.clone(store, source, config=config)
    assert retried["total"] == 3
    page = store.definitions.page(retried["job_id"], offset=ordinal, limit=1)
    assert len(page[0]["task"]["payload"]["media_ids"]) == 250000


def test_retry_bounds_generated_insert_bytes_independently_of_row_count(
    store, monkeypatch
):
    source = source_plan(store, 8)
    widen(store, source, size=2000)
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "8")
    monkeypatch.setenv("ULTIMA_MPS_RETRY_BATCH_MAX_BYTES", "32768")
    with written_batches(store) as batches:
        retried = fixtures.clone(store, source)
    assert retried["total"] == 8
    assert sum(count for count, size in batches) == 8
    assert all(size <= 32768 for count, size in batches)
    assert max(count for count, size in batches) < 8
    tasks = store.definitions.page(retried["job_id"], offset=0, limit=8)
    assert all(len(row["task"]["payload"]["media_ids"]) == 2000 for row in tasks)


@pytest.mark.parametrize("field", ["result", "children"])
def test_retry_excludes_discarded_history_and_child_payloads_before_transfer(
    store, monkeypatch, field, record_property
):
    source = source_plan(store, 1)
    widen(store, source, field=field)
    monkeypatch.setenv("ULTIMA_MPS_RETRY_BATCH_MAX_BYTES", "32768")
    tracemalloc.start()
    try:
        retried = fixtures.clone(store, source)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    record_property("discarded_history_peak_bytes", peak)
    assert peak < 2 * 1024 * 1024, f"Discarded history allocated {peak:,} bytes"
    row = store.definitions.page(retried["job_id"], offset=0, limit=1)[0]
    assert row["task"]["result"] is None
    if field == "children":
        assert row["task"]["_mps_retry_children"] == [
            {
                "task_id": None,
                "task_type": "download",
                "site_name": "OnlyFans",
                "user_id": 2,
                "content_type": None,
                "paid_content_feed": True,
            }
        ]


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_invalid_retry_byte_budget_leaves_source_unchanged(store, monkeypatch, value):
    source = source_plan(store)
    monkeypatch.setenv("ULTIMA_MPS_RETRY_BATCH_MAX_BYTES", value)
    with pytest.raises(ValueError, match="ULTIMA_MPS_RETRY_BATCH_MAX_BYTES"):
        fixtures.clone(store, source)
    assert store.get(source["job_id"])["status"] == "ready"


@pytest.mark.parametrize("explicit", [False, True])
def test_retry_byte_setting_derives_command_budget_without_clamping_override(
    store, monkeypatch, explicit
):
    source = source_plan(store, 1)
    widen(store, source, size=2000)
    monkeypatch.setenv("ULTIMA_DATABASE_WRITE_MAX_COMMAND_BYTES", "4096")
    if explicit:
        monkeypatch.setenv("ULTIMA_MPS_RETRY_BATCH_MAX_BYTES", "65536")
        assert fixtures.clone(store, source)["total"] == 1
    else:
        monkeypatch.delenv("ULTIMA_MPS_RETRY_BATCH_MAX_BYTES", raising=False)
        with pytest.raises(ValueError, match="budget"):
            fixtures.clone(store, source)


def test_retry_remapped_dependency_expansion_obeys_output_budget(store, monkeypatch):
    parents = [
        Task(
            task_id=f"n{i}",
            task_type=TaskType.DOWNLOAD,
            site_name="OnlyFans",
            user_id=i + 1,
        )
        for i in range(100)
    ]
    child = Task(
        task_id="dependent",
        task_type=TaskType.DOWNLOAD,
        site_name="OnlyFans",
        user_id=101,
        depends_on=[task.task_id for task in parents],
    )
    source = fixtures.explicit_plan(store, parents + [child])
    config = Job.create(name="Retry", tasks=[], created_by="test").to_dict()
    monkeypatch.setenv("ULTIMA_MPS_RETRY_BATCH_MAX_BYTES", "8192")
    with pytest.raises(ValueError, match="budget") as error:
        fixtures.clone(store, source, config=config)
    # The stored source value fitted; deterministic ID remapping expanded the
    # generated definition past the output allowance.
    assert error.value.task_id == fixtures.retry_task_id(
        config["job_id"], child.task_id
    )
    assert store.get(source["job_id"])["status"] == "ready"
    assert store.get(config["job_id"]) is None
    monkeypatch.setenv("ULTIMA_MPS_RETRY_BATCH_MAX_BYTES", "16384")
    with written_batches(store) as sizes:
        retry = fixtures.clone(store, source, config=config)
    assert all(size <= 16384 for count, size in sizes)
    copied = store.definitions.page(retry["job_id"], offset=100, limit=1)[0]
    assert copied["task"]["depends_on"] == [
        fixtures.retry_task_id(retry["job_id"], task.task_id) for task in parents
    ]
