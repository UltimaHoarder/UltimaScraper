"""Planner pages preserve bounded work and exact candidate route offsets."""

import time
from dataclasses import replace

import pytest
from sqlalchemy import func, select
from test_execution_ledger import (
    finish,
    ledger,
    ledger_engine,
    postgres_engine,
    submit,
    task,
)
from ultima_scraper_backend.job_system import mps_tasks
from ultima_scraper_backend.job_system.ledger import Limits, Work
from ultima_scraper_backend.job_system.models import Job, Task, TaskResult, TaskState

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


def test_runtime_planner_batch_keeps_explicit_claim_controls(monkeypatch):
    monkeypatch.setenv("ULTIMA_LEDGER_BATCH", "")
    monkeypatch.setenv("ULTIMA_LEDGER_PLANNER_BATCH", "")
    assert Limits.load().batch == 128
    assert Limits.load().planner_batch == 512
    monkeypatch.setenv("ULTIMA_LEDGER_BATCH", "32")
    assert Limits.load().batch == Limits.load().planner_batch == 32
    monkeypatch.setenv("ULTIMA_LEDGER_PLANNER_BATCH", "256")
    assert Limits.load().batch == 32
    assert Limits.load().planner_batch == 256
    monkeypatch.setenv("ULTIMA_LEDGER_PLANNER_BATCH", "0")
    with pytest.raises(ValueError, match="must be positive"):
        Limits.load()
    assert Limits(batch=4).planner_batch is None


def create_range(ledger, identity):
    job = Job.create(name="Planner pages", created_by="test", tasks=[])
    job.job_id = identity
    return ledger.manifests.create(
        job_id=identity,
        site="onlyfans",
        job_config=job.to_dict(),
        selection={"start_id": 1, "end_id": 24, "max_profiles": None},
        proxy_pool=[],
        site_session_factory=ledger.session_factory,
    )


def test_larger_planner_pages_keep_global_window_and_claim_caps(ledger):
    ledger.limits = replace(
        ledger.limits, tasks=6, global_tasks=8, batch=2, planner_batch=10
    )
    create_range(ledger, "job-a")
    create_range(ledger, "job-b")
    observations = []
    assert ledger.tick(diagnostics=observations) == "job-a"
    assert observations[-1]["admitted_tasks"] == 6
    assert observations[-1]["controls"]["archive_batch_tasks"] == 10
    assert ledger.tick(diagnostics=observations) == "job-b"
    assert observations[-1]["admitted_tasks"] == 2
    with ledger.session_factory() as session:
        assert len(session.execute(select(Work)).scalars().all()) == 8
    claims = ledger.claim_many(
        owner="worker-a", backend_id="backend-a", capabilities=["onlyfans"], count=100
    )
    assert len(claims) == 2
    for claim in claims:
        finish(ledger, claim)
    for _ in range(2):
        ledger.tick(diagnostics=observations)
    with ledger.session_factory() as session:
        rows = session.execute(select(Work)).scalars().all()
        assert len(rows) <= 8
        assert sum(row.run_id == "job-a" for row in rows) <= 6
        assert sum(row.run_id == "job-b" for row in rows) <= 6
    assert sum(row["archived_tasks"] for row in observations) == 2


def test_larger_archive_page_still_obeys_the_result_byte_budget(ledger):
    ledger.limits = replace(
        ledger.limits, tasks=10, global_tasks=10, batch=2, planner_batch=10
    )
    submit(ledger, [task(f"task-{index}", user_id=index + 1) for index in range(10)])
    ledger.tick()
    claims = []
    while len(claims) < 10:
        claims.extend(
            ledger.claim_many(
                owner="worker-a",
                backend_id="backend-a",
                capabilities=["onlyfans"],
                count=100,
            )
        )
    for claim in claims:
        item = Task.from_dict(claim.task)
        item.state = TaskState.COMPLETED
        item.result = TaskResult(success=True, output={"blob": "x" * 3000})
        item.completed_at = item.result.completed_at
        ledger.finish(claim, item)
    with ledger.session_factory() as session:
        sizes = (
            session.execute(select(func.octet_length(Work.payload_json)))
            .scalars()
            .all()
        )
    ledger.limits = replace(ledger.limits, result_bytes=sum(sorted(sizes)[-2:]))
    observations = []
    ledger.tick(diagnostics=observations)
    assert observations[-1]["archived_tasks"] == 2
    assert observations[-1]["controls"]["archive_batch_tasks"] == 10
    with ledger.session_factory() as session:
        assert len(session.execute(select(Work)).scalars().all()) == 8
    for claim in claims:
        assert ledger.task("job-test", claim.task_id)["result"]["output"] == {
            "blob": "x" * 3000
        }


def test_contiguous_builder_pages_preserve_routes_through_candidate_holes(
    ledger, monkeypatch
):
    proxies = [f"http://route-{index}.invalid:8080" for index in range(80)]
    geo = {
        proxy: ("US", "GB", "DE", "JP")[index % 4]
        for index, proxy in enumerate(proxies)
    }
    monkeypatch.setattr(mps_tasks, "get_cached_proxy_geo_map", lambda **kwargs: geo)
    monkeypatch.setattr(
        ledger.manifests,
        "candidate_ids",
        lambda job_id, positions, **kwargs: {
            position: position + 100 for position in positions
        },
    )
    plan = {
        "job_id": "job-pages",
        "site": "onlyfans",
        "cursor": 0,
        "total": 12,
        "proxy_pool": proxies,
        "selection": {
            "candidate_total": 12,
            "candidate_checkpoint": {"next": 8, "pending": [[0, 6]]},
            "include_direct_connection": True,
            "max_route_hops": 3,
            "conclusive_miss_threshold": 2,
        },
    }
    positions = [1, 3, 4, 9, 10, 11]
    expected = [
        mps_tasks._build_mps_task_batch(
            job_id="job-pages",
            site_display="OnlyFans",
            target_user_ids=[position + 100],
            proxy_pool=proxies,
            proxy_geo_map=geo,
            candidate_offset=position,
            include_direct=True,
            max_route_hops=3,
            conclusive_miss_threshold=2,
        )[0]
        for position in positions
    ]
    groups = []
    original = mps_tasks._group_mps_proxy_countries

    def group_once(pool, mapping):
        groups.append(time.monotonic())
        return original(pool, mapping)

    monkeypatch.setattr(mps_tasks, "_group_mps_proxy_countries", group_once)
    tasks, ordinals = ledger._source_page(
        None,
        plan,
        [0, 2, 5, 8],
        6,
        65536,
    )
    assert len(groups) == 3
    assert ordinals == {
        task.task_id: position for task, position in zip(tasks, positions, strict=True)
    }
    for actual, before in zip(tasks, expected, strict=True):
        assert actual.task_id == before.task_id
        assert actual.user_id == before.user_id
        assert actual.payload == before.payload
        assert actual.capabilities == before.capabilities
