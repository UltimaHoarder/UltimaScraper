from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from ultima_scraper_backend import job_system as job_system_module
from ultima_scraper_backend.api.routes import auths as auths_module
from ultima_scraper_backend.api.routes import jobs as jobs_module
from ultima_scraper_backend.api.routes import system as system_module
from ultima_scraper_backend.api.routes import users as users_module
from ultima_scraper_backend.job_system import models as job_models_module


@pytest.fixture(autouse=True)
def _legacy_route_job_plans(monkeypatch):
    """These SQL doubles describe jobs without durable plans.

    Actual PostgreSQL plan/header reads are covered by test_durable_job_history.
    """
    monkeypatch.setattr(jobs_module, "_read_task_plan_sync", lambda _job_id: None)
    monkeypatch.setattr(jobs_module, "_fetch_durable_headers_sync", lambda _job_ids: {})


async def _inline_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Run stubbed sync work inline so contract tests do not own an executor."""
    return func(*args, **kwargs)


class _FakeExecResult:
    def __init__(
        self,
        *,
        one_value: int | None = None,
        all_rows: list[object] | None = None,
        first_value: object | None = None,
    ) -> None:
        self._one_value = one_value
        self._all_rows = all_rows or []
        self._first_value = first_value

    def one(self) -> int:
        if self._one_value is None:
            raise AssertionError("one() was not expected for this result")
        return self._one_value

    def first(self) -> object | None:
        if self._first_value is not None:
            return self._first_value
        return self._all_rows[0] if self._all_rows else None

    def all(self) -> list[object]:
        return list(self._all_rows)


class _FakeSession:
    def __init__(self, results: list[_FakeExecResult]) -> None:
        self._results = results

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def exec(self, _query: object) -> _FakeExecResult:
        if not self._results:
            raise AssertionError("Unexpected query execution")
        return self._results.pop(0)


class _FakeSiteDB:
    def __init__(self, results: list[_FakeExecResult]) -> None:
        self._results = results

    def get_session(self) -> _FakeSession:
        return _FakeSession(self._results)


class _FakeDBManager:
    def __init__(self) -> None:
        self._onlyfans_results = [
            _FakeExecResult(one_value=1),
            _FakeExecResult(
                all_rows=[
                    (
                        SimpleNamespace(
                            id=1,
                            site="onlyfans",
                            username="auth-main",
                            user_id=1001,
                            status="ok",
                            active=True,
                            last_tested_at=None,
                            created_at=None,
                            cookie="cookie-value",
                            authorization="",
                            user_agent="Mozilla/5.0 Smoke Test",
                            proxy_id=None,
                            is_age_verified=True,
                            age_verification_required=False,
                        ),
                        SimpleNamespace(spend=True, spender_type="primary"),
                    )
                ]
            ),
        ]

    def get_or_create_manager(self, site_name: str):
        if site_name == "onlyfans":
            return _FakeSiteDB(self._onlyfans_results)
        return None


class _OrdinaryJobStorage:
    JOB_STATE_KEY = job_system_module.JobStorage.JOB_STATE_KEY

    def _client(self) -> object:
        return SimpleNamespace(hget=AsyncMock(return_value=None))


class _FakeStorage(_OrdinaryJobStorage):
    def __init__(self, _redis: object) -> None:
        return None

    async def fetch_tasks_stream(
        self,
        _job_id: str,
        _batch_size: int,
        *,
        cursor: str | None = None,
        state: str | None = None,
        task_type: str | None = None,
        error_only: bool = False,
    ) -> AsyncIterator[object]:
        del cursor, state, task_type, error_only
        yield SimpleNamespace(task_id="task-1")

    async def fetch_task_page(
        self,
        _job_id: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
        state: str | None = None,
        task_type: str | None = None,
        error_only: bool = False,
    ) -> object:
        del limit, state, task_type, error_only
        return SimpleNamespace(
            tasks=[], next_cursor=cursor, has_more=False, scanned_count=0
        )


@pytest.mark.asyncio
async def test_system_bootstrap_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = SimpleNamespace(
        instance_id="backend-contract",
        distributed_mode=False,
        redis=None,
    )
    config = SimpleNamespace(
        settings=SimpleNamespace(
            worker_pool=SimpleNamespace(sites=["OnlyFans", "Fansly"]),
        )
    )

    class _DummySettingsService:
        def get_setup_status(self) -> dict[str, object]:
            return {
                "is_configured": True,
                "has_config": True,
                "has_database": True,
                "data_directory": "/tmp/usr",
                "startup_id": "startup-contract",
            }

    monkeypatch.setattr(system_module, "SettingsService", _DummySettingsService)
    monkeypatch.setattr(system_module, "_get_runtime_version", lambda: "9.9.9")
    monkeypatch.setattr(system_module.socket, "gethostname", lambda: "contract-host")

    response = system_module.get_system_bootstrap(backend, config)

    assert response.backend_id == "backend-contract"
    assert response.hostname == "contract-host"
    assert response.supported_sites == ["onlyfans", "fansly"]
    assert response.support_matrix.ui_mode == "webui"
    assert response.support_matrix.runtime_database == "postgresql"


@pytest.mark.asyncio
async def test_jobs_active_tasks_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.job_system import ledger as ledger_module

    task = job_system_module.Task(
        task_id="task-1",
        task_type=job_system_module.TaskType.SCRAPE,
        user_id=1,
        site_name="onlyfans",
        user_username="alice",
        state=job_system_module.TaskState.RUNNING,
        started_at="2026-03-08T00:00:00Z",
    )
    limits = []

    def active(_ledger, *, limit):
        limits.append(limit)
        return [
            {
                "job_id": "job-123",
                "job_name": "Contract Job",
                "job_status": "running",
                "job_total_tasks": 1,
                "task": task.to_dict(),
            }
        ]

    monkeypatch.setattr(ledger_module.ExecutionLedger, "__init__", lambda _self: None)
    monkeypatch.setattr(ledger_module.ExecutionLedger, "active", active)
    monkeypatch.setattr(jobs_module, "_task_progress", lambda _task: (0.5, 6, 12))

    response = await jobs_module.list_active_tasks(
        limit_jobs=120,
        limit_tasks=1000,
        backend=SimpleNamespace(),
    )

    assert limits == [250]
    assert response.total == 1
    detail = response.tasks[0]
    assert detail.job_id == "job-123"
    assert detail.job_name == "Contract Job"
    assert detail.job_status == "running"
    assert detail.job_total_tasks == 1
    assert detail.task_id == "task-1"
    assert detail.username == "alice"
    assert detail.status == "running"
    assert (detail.progress, detail.items_processed, detail.items_total) == (0.5, 6, 12)


def test_task_detail_exposes_canonical_worker_owner() -> None:
    from ultima_scraper_backend.job_system.models import Task, TaskType

    task = Task(
        task_id="task-owned-contract",
        task_type=TaskType.SCRAPE,
        user_id=123,
        payload=None,
        site_name="OnlyFans",
        worker_id="worker-owner-contract",
    )

    detail = jobs_module._task_to_detail(task)

    assert detail.worker_id == "worker-owner-contract"


@pytest.mark.asyncio
async def test_job_task_stream_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = SimpleNamespace(
        instance_id="backend-contract",
        distributed_mode=False,
        redis=SimpleNamespace(client=object()),
    )

    monkeypatch.setattr(jobs_module, "JobStorage", _FakeStorage)
    monkeypatch.setattr(
        jobs_module,
        "_task_to_detail",
        lambda _task: jobs_module.TaskDetail(
            task_id="task-1",
            task_type="scrape_user",
            status="running",
            site="onlyfans",
            username="alice",
            content_type=None,
            payload=None,
            started_at="2026-03-08T00:00:00Z",
            completed_at=None,
            progress=0.5,
            items_processed=6,
            items_total=12,
            error=None,
            result=None,
        ),
    )

    response = await jobs_module.stream_job_tasks("job-123", backend=backend)
    chunks = [chunk async for chunk in response.body_iterator]
    text = b"".join(
        chunk.encode("utf-8") if isinstance(chunk, str) else chunk for chunk in chunks
    ).decode("utf-8")

    assert response.media_type == "text/event-stream"
    assert 'data: {"task_id":"task-1"' in text
    assert "data: [DONE]" in text


@pytest.mark.asyncio
async def test_job_task_stream_falls_back_to_central_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EmptyStreamStorage(_OrdinaryJobStorage):
        def __init__(self, _redis: object) -> None:
            return None

        async def fetch_tasks_stream(
            self,
            _job_id: str,
            _batch_size: int,
            *,
            cursor: str | None = None,
            state: str | None = None,
            task_type: str | None = None,
            error_only: bool = False,
        ) -> AsyncIterator[object]:
            del cursor, state, task_type, error_only
            if False:
                yield None

    backend = SimpleNamespace(
        instance_id="backend-contract",
        distributed_mode=False,
        redis=SimpleNamespace(client=object()),
    )

    monkeypatch.setattr(jobs_module, "JobStorage", _EmptyStreamStorage)
    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _inline_to_thread)
    monkeypatch.setattr(
        jobs_module,
        "_fetch_central_task_page_sync",
        lambda job_id, *, offset=0, limit=100, state=None, task_type=None, error_only=False: jobs_module.TaskPageResponse(
            tasks=(
                [
                    jobs_module.TaskDetail(
                        task_id=f"{job_id}-task-{offset}",
                        task_type="scrape_user",
                        status="pending",
                        site="onlyfans",
                        username="alice",
                        content_type=None,
                        payload=None,
                        started_at=None,
                        completed_at=None,
                        progress=0.0,
                        items_processed=0,
                        items_total=12,
                        error=None,
                        result=None,
                    )
                ]
                if offset == 0
                else []
            ),
            next_cursor=None,
            has_more=False,
            scanned_count=offset + 1 if offset == 0 else offset,
            offset=offset,
            limit=limit,
        ),
    )

    response = await jobs_module.stream_job_tasks("job-456", backend=backend)
    chunks = [chunk async for chunk in response.body_iterator]
    text = b"".join(
        chunk.encode("utf-8") if isinstance(chunk, str) else chunk for chunk in chunks
    ).decode("utf-8")

    assert response.media_type == "text/event-stream"
    assert 'data: {"task_id":"job-456-task-0"' in text
    assert "data: [DONE]" in text


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_ledger_runs")
async def test_get_job_tasks_falls_back_to_central_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = SimpleNamespace(
        instance_id="backend-contract",
        distributed_mode=False,
        redis=None,
    )

    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _inline_to_thread)
    monkeypatch.setattr(
        jobs_module,
        "_fetch_central_task_page_sync",
        lambda job_id, *, offset=0, limit=100, state=None, task_type=None, error_only=False: jobs_module.TaskPageResponse(
            tasks=[
                jobs_module.TaskDetail(
                    task_id=f"{job_id}-task-{offset}",
                    task_type="download_media",
                    status="pending",
                    site="onlyfans",
                    username="alice",
                    content_type="posts",
                    payload=None,
                    started_at=None,
                    completed_at=None,
                    progress=0.0,
                    items_processed=0,
                    items_total=25,
                    error=None,
                    result=None,
                )
            ],
            next_cursor=None,
            has_more=False,
            scanned_count=offset + 1,
            offset=offset,
            limit=limit,
        ),
    )

    response = await jobs_module.get_job_tasks(
        "job-789", offset=0, limit=100, backend=backend
    )

    assert len(response.tasks) == 1
    assert response.tasks[0].task_id == "job-789-task-0"
    assert response.tasks[0].task_type == "download_media"


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_ledger_runs")
async def test_get_job_tasks_falls_back_to_event_log_when_central_rows_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = SimpleNamespace(
        instance_id="backend-contract",
        distributed_mode=False,
        redis=SimpleNamespace(name="redis-event-log"),
    )
    empty_page = jobs_module.TaskPageResponse(
        tasks=[],
        next_cursor=None,
        has_more=False,
        scanned_count=0,
        offset=0,
        limit=100,
    )

    class _FakeJobStorage(_OrdinaryJobStorage):
        def __init__(self, _redis: object) -> None:
            return None

        async def fetch_task_page(self, *args, **kwargs):
            del args, kwargs
            return empty_page

    class _FakeEventLog:
        def __init__(self, _redis: object) -> None:
            return None

        async def read_events(self, job_id: str):
            assert job_id == "job-archived"
            return [
                SimpleNamespace(
                    event_type=jobs_module.EventType.TASK_CLAIMED,
                    task_id="task-download-1",
                    worker_id="worker-1",
                    timestamp="2026-04-19T00:00:00+00:00",
                    data={"task_type": "download"},
                ),
                SimpleNamespace(
                    event_type=jobs_module.EventType.TASK_STARTED,
                    task_id="task-download-1",
                    worker_id="worker-1",
                    timestamp="2026-04-19T00:00:01+00:00",
                    data={"task_type": "download", "content_type": "posts"},
                ),
                SimpleNamespace(
                    event_type=jobs_module.EventType.TASK_COMPLETED,
                    task_id="task-download-1",
                    worker_id="worker-1",
                    timestamp="2026-04-19T00:00:02+00:00",
                    data={"job_completed": True},
                ),
                SimpleNamespace(
                    event_type=jobs_module.EventType.TASK_CLAIMED,
                    task_id="task-scrape-2",
                    worker_id="worker-2",
                    timestamp="2026-04-19T00:01:00+00:00",
                    data={"task_type": "scrape"},
                ),
                SimpleNamespace(
                    event_type=jobs_module.EventType.TASK_FAILED,
                    task_id="task-scrape-2",
                    worker_id="worker-2",
                    timestamp="2026-04-19T00:01:05+00:00",
                    data={"error": "boom"},
                ),
            ]

    monkeypatch.setattr(jobs_module, "JobStorage", _FakeJobStorage)
    monkeypatch.setattr(jobs_module, "EventLog", _FakeEventLog)
    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _inline_to_thread)
    monkeypatch.setattr(
        jobs_module,
        "_fetch_central_task_page_sync",
        lambda job_id, *, offset=0, limit=100, state=None, task_type=None, error_only=False: empty_page,
    )

    response = await jobs_module.get_job_tasks(
        "job-archived",
        state="completed",
        task_type="download_media",
        backend=backend,
    )

    assert len(response.tasks) == 1
    assert response.tasks[0].task_id == "task-download-1"
    assert response.tasks[0].task_type == "download_media"
    assert response.tasks[0].status == jobs_module.TaskState.COMPLETED.value
    assert response.tasks[0].content_type == "posts"
    assert response.tasks[0].worker_id == "worker-1"
    assert response.tasks[0].started_at == "2026-04-19T00:00:01+00:00"
    assert response.tasks[0].completed_at == "2026-04-19T00:00:02+00:00"
    assert response.next_cursor is None


@pytest.mark.asyncio
async def test_update_job_uses_job_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    task = job_system_module.Task(
        task_id="task-update-1",
        task_type=job_system_module.TaskType.API_COMMAND,
        user_id=1,
        site_name="onlyfans",
        user_username="alice",
    )
    updated_job = job_models_module.Job.create(
        name="Updated Name",
        created_by="webui",
        tasks=[task],
    )

    captured: dict[str, object] = {}

    class _FakeJobManager:
        def __init__(self, _redis: object) -> None:
            return None

        async def update_job_by_id(self, job_id: str, **kwargs: object) -> object:
            captured["job_id"] = job_id
            captured["kwargs"] = kwargs
            return updated_job

    async def _fake_database_call(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        del func, args, kwargs
        return None

    monkeypatch.setattr(jobs_module, "JobManager", _FakeJobManager)
    monkeypatch.setattr(jobs_module, "run_database_call", _fake_database_call)

    backend = SimpleNamespace(
        redis=SimpleNamespace(is_connected=True),
        distributed_mode=True,
        active_queue=None,
    )

    response = await jobs_module.update_job(
        "job-update-1",
        jobs_module.UpdateJobRequest(job_name=" Updated Name "),
        backend=backend,
        backend_manager=SimpleNamespace(),
    )

    assert response.job_id == updated_job.job_id
    assert captured["job_id"] == "job-update-1"
    assert captured["kwargs"] == {
        "name": "Updated Name",
        "schedule": None,
        "tasks": None,
        "route_immediate_job": True,
        "args_patch": {"job_name": " Updated Name "},
    }


@pytest.mark.asyncio
async def test_retry_job_uses_job_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    original_task = job_system_module.Task(
        task_id="task-original-1",
        task_type=job_system_module.TaskType.API_COMMAND,
        user_id=1,
        site_name="onlyfans",
        user_username="alice",
        state=job_system_module.TaskState.FAILED,
    )
    original_job = job_models_module.Job.create(
        name="Original Job",
        created_by="webui",
        tasks=[original_task],
    )

    retry_task = job_system_module.Task(
        task_id="task-retry-1",
        task_type=job_system_module.TaskType.API_COMMAND,
        user_id=1,
        site_name="onlyfans",
        user_username="alice",
    )
    retry_job = job_models_module.Job.create(
        name="Retry: Original Job",
        created_by="webui",
        tasks=[retry_task],
    )

    manager_calls: dict[str, object] = {}

    class _FakeJobManager:
        def __init__(self, _redis: object) -> None:
            return None

        async def prepare_retry_job(
            self,
            job_id: str,
            *,
            auth_id: int | None = None,
            max_include_tasks: int | None = None,
        ) -> tuple[object, object]:
            manager_calls["prepare"] = {
                "job_id": job_id,
                "auth_id": auth_id,
                "max_include_tasks": max_include_tasks,
            }
            return original_job, retry_job

        async def activate_retry_job(
            self,
            *,
            original_job: object,
            retry_job: object,
            cancel_reason: str,
            distributed_mode: bool,
            priority: int = 0,
            preferred_backend_id: str | None = None,
        ) -> tuple[str | None, list[object]]:
            manager_calls["activate"] = {
                "original_job_id": getattr(original_job, "job_id", None),
                "retry_job_id": getattr(retry_job, "job_id", None),
                "cancel_reason": cancel_reason,
                "distributed_mode": distributed_mode,
                "priority": priority,
                "preferred_backend_id": preferred_backend_id,
            }
            return preferred_backend_id, [retry_task]

    class _FakeStorage:
        def __init__(self, _redis: object) -> None:
            return None

        async def fetch_job(self, _job_id: str, *, include_tasks: bool) -> object:
            assert include_tasks is False
            return original_job

        async def get_job_task_stats(self, _job_id: str) -> dict[str, object]:
            return {
                "total": 1,
                "ready": 0,
                "blocked": 0,
                "inflight": 0,
                "deferred": 1,
                "completed": 0,
                "failed": 0,
                "task_type_counts": {
                    retry_task.task_type.value: 1,
                },
            }

    async def _fake_to_thread(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        del func, args, kwargs
        return None

    monkeypatch.setattr(jobs_module, "JobManager", _FakeJobManager)
    monkeypatch.setattr(jobs_module, "JobStorage", _FakeStorage)
    monkeypatch.setattr(jobs_module, "run_database_call", _fake_to_thread)
    monkeypatch.setattr(jobs_module, "publish_ws_event", AsyncMock())

    backend = SimpleNamespace(
        redis=SimpleNamespace(is_connected=True),
        distributed_mode=True,
        instance_id="backend-contract",
        active_queue=None,
    )

    response = await jobs_module.retry_job(
        "job-retry-1",
        jobs_module.RetryJobRequest(auth_id=77),
        backend=backend,
    )

    assert response.job_id == retry_job.job_id
    assert response.task_stats is not None
    assert response.task_stats.deferred == 1
    assert manager_calls["prepare"] == {
        "job_id": "job-retry-1",
        "auth_id": 77,
        "max_include_tasks": jobs_module.MAX_INLINE_TASK_LOAD,
    }
    assert manager_calls["activate"] == {
        "original_job_id": original_job.job_id,
        "retry_job_id": retry_job.job_id,
        "cancel_reason": f"superseded by retry job {retry_job.job_id}",
        "distributed_mode": True,
        "priority": 0,
        "preferred_backend_id": None,
    }


@pytest.mark.asyncio
async def test_build_refresh_subscriptions_targets_single_auth_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeExecResult:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def all(self) -> list[object]:
            return list(self._rows)

        def first(self) -> object | None:
            return self._rows[0] if self._rows else None

    class _FakeSession:
        def __init__(self, rows_per_query: list[list[object]]) -> None:
            self._rows_per_query = rows_per_query

        def exec(self, _query: object) -> _FakeExecResult:
            if not self._rows_per_query:
                raise AssertionError("Unexpected query execution")
            return _FakeExecResult(self._rows_per_query.pop(0))

        def close(self) -> None:
            return None

    class _FakeSiteDB:
        def __init__(self, rows_per_query: list[list[object]]) -> None:
            self._rows_per_query = rows_per_query

        def get_session(self) -> _FakeSession:
            return _FakeSession(self._rows_per_query)

    class _FakeMultiSiteDBManager:
        def __init__(self, rows_per_query: list[list[object]]) -> None:
            self._rows_per_query = rows_per_query

        def get_or_create_manager(self, site_name: str) -> _FakeSiteDB | None:
            if site_name != "onlyfans":
                return None
            return _FakeSiteDB(self._rows_per_query)

    async def _run_sync(func, *args, **kwargs):
        return func(*args, **kwargs)

    selected_auth = SimpleNamespace(id=77, user_id=10001, username="AUTH-10001", username_bytes=10)
    backend_manager = SimpleNamespace(
        multi_site_db_manager=_FakeMultiSiteDBManager([[selected_auth]])
    )

    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _run_sync)

    result = await jobs_module._build_task_from_payload(
        jobs_module.TaskPayload(
            task_type="refresh_subscriptions",
            params={"site": "OnlyFans", "auth_id": 77},
        ),
        backend_manager,
    )

    result = [task async for task in result]
    assert len(result) == 1
    assert result[0].user_id == 10001
    assert result[0].auth_id == 10001
    assert result[0].user_username == "AUTH-10001"


@pytest.mark.asyncio
async def test_normalize_auth_id_prefers_exact_auth_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeExecResult:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def all(self) -> list[object]:
            return list(self._rows)

        def first(self) -> object | None:
            return self._rows[0] if self._rows else None

    class _FakeSession:
        def __init__(self, rows_per_query: list[list[object]]) -> None:
            self._rows_per_query = rows_per_query

        def exec(self, _query: object) -> _FakeExecResult:
            if not self._rows_per_query:
                raise AssertionError("Unexpected query execution")
            return _FakeExecResult(self._rows_per_query.pop(0))

        def close(self) -> None:
            return None

    class _FakeSiteDB:
        def __init__(self, rows_per_query: list[list[object]]) -> None:
            self._rows_per_query = rows_per_query

        def get_session(self) -> _FakeSession:
            return _FakeSession(self._rows_per_query)

    class _FakeMultiSiteDBManager:
        def __init__(self, rows_per_query: list[list[object]]) -> None:
            self._rows_per_query = rows_per_query

        def get_or_create_manager(self, site_name: str) -> _FakeSiteDB | None:
            if site_name != "onlyfans":
                return None
            return _FakeSiteDB(self._rows_per_query)

    async def _run_sync(func, *args, **kwargs):
        return func(*args, **kwargs)

    selected_auth = SimpleNamespace(id=77, user_id=10001, username="test-user")
    backend_manager = SimpleNamespace(
        multi_site_db_manager=_FakeMultiSiteDBManager([[selected_auth]])
    )

    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _run_sync)

    normalized_auth_id = await jobs_module._normalize_auth_id_for_site(
        "OnlyFans",
        77,
        backend_manager,
    )

    assert normalized_auth_id == 10001


@pytest.mark.asyncio
async def test_resolve_auth_from_message_history_prefers_recent_chat_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeMultiSiteDBManager:
        def __init__(self, results: list[_FakeExecResult]) -> None:
            self._results = results

        def get_or_create_manager(self, site_name: str) -> _FakeSiteDB | None:
            if site_name != "onlyfans":
                return None
            return _FakeSiteDB(self._results)

    async def _run_sync(func, *args, **kwargs):
        return func(*args, **kwargs)

    backend_manager = SimpleNamespace(
        multi_site_db_manager=_FakeMultiSiteDBManager(
            [
                _FakeExecResult(all_rows=[10001, 41900816]),
                _FakeExecResult(all_rows=[41900816, 10001]),
            ]
        )
    )

    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _run_sync)

    resolved_auth_id = await jobs_module._resolve_auth_from_message_history(
        "OnlyFans",
        268927747,
        backend_manager,
    )

    assert resolved_auth_id == 41900816


@pytest.mark.asyncio
async def test_build_scrape_user_task_uses_message_history_auth_when_unsubscribed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_manager = SimpleNamespace()
    monkeypatch.setattr(
        jobs_module,
        "_resolve_auth_from_subscription",
        AsyncMock(return_value=None),
    )
    message_history_resolver = AsyncMock(return_value=41900816)
    monkeypatch.setattr(
        jobs_module,
        "_resolve_auth_from_message_history",
        message_history_resolver,
    )

    result = await jobs_module._build_task_from_payload(
        jobs_module.TaskPayload(
            task_type="scrape_user",
            params={
                "site": "OnlyFans",
                "user_id": 268927747,
                "username": "chat_target",
                "content_types": ["Messages"],
                "download_media": False,
            },
        ),
        backend_manager,
    )

    assert isinstance(result, jobs_module.Task)
    assert result.auth_id == 41900816
    message_history_resolver.assert_awaited_once_with(
        "OnlyFans",
        268927747,
        backend_manager,
    )


@pytest.mark.asyncio
async def test_build_scrape_and_download_uses_message_history_auth_when_unsubscribed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_manager = SimpleNamespace()
    monkeypatch.setattr(
        jobs_module,
        "_resolve_auth_from_subscription",
        AsyncMock(return_value=None),
    )
    message_history_resolver = AsyncMock(return_value=41900816)
    monkeypatch.setattr(
        jobs_module,
        "_resolve_auth_from_message_history",
        message_history_resolver,
    )

    result = await jobs_module._build_task_from_payload(
        jobs_module.TaskPayload(
            task_type="scrape_and_download",
            params={
                "site": "OnlyFans",
                "user_id": 268927747,
                "username": "chat_target",
                "content_types": ["Messages"],
                "max_items": 25,
            },
        ),
        backend_manager,
    )

    assert isinstance(result, list)
    assert len(result) == 2
    assert all(task.auth_id == 41900816 for task in result)
    message_history_resolver.assert_awaited_once_with(
        "OnlyFans",
        268927747,
        backend_manager,
    )


@pytest.mark.asyncio
async def test_prioritize_job_uses_job_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    prioritized_job = job_models_module.Job.create(
        name="Priority Job",
        created_by="webui",
        tasks=[],
    )

    class _FakeJobManager:
        def __init__(self, _redis: object) -> None:
            return None

        async def prioritize_job_by_id(
            self,
            job_id: str,
            *,
            priority: int = -1,
        ) -> tuple[object, int]:
            assert job_id == "job-priority-1"
            assert priority == -1
            return prioritized_job, 42

    monkeypatch.setattr(jobs_module, "JobManager", _FakeJobManager)
    monkeypatch.setattr(jobs_module, "publish_ws_event", AsyncMock())

    response = await jobs_module.prioritize_job(
        "job-priority-1",
        backend=SimpleNamespace(redis=SimpleNamespace(is_connected=True)),
    )

    assert response == {"job_id": "job-priority-1", "rescored": 42, "priority": -1}


@pytest.mark.asyncio
async def test_cancel_job_uses_job_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    cancelled_job = job_models_module.Job.create(
        name="Cancel Job",
        created_by="webui",
        tasks=[],
    )
    submit_write = AsyncMock(return_value={"synced": True})

    class _FakeJobManager:
        def __init__(self, _redis: object) -> None:
            self.database_writes = SimpleNamespace(submit=submit_write)

        async def cancel_job_by_id(
            self,
            job_id: str,
            *,
            reason: str = "",
            wait_for_resource_cleanup: bool = True,
        ) -> object:
            assert job_id == "job-cancel-1"
            assert reason == "cancelled by user"
            assert wait_for_resource_cleanup is False
            return cancelled_job

    monkeypatch.setattr(jobs_module, "JobManager", _FakeJobManager)
    monkeypatch.setattr(jobs_module, "publish_ws_event", AsyncMock())
    schedule_cleanup = MagicMock()
    monkeypatch.setattr(jobs_module, "_schedule_cancel_cleanup", schedule_cleanup)

    response = await jobs_module.cancel_job(
        "job-cancel-1",
        backend=SimpleNamespace(redis=SimpleNamespace(is_connected=True)),
    )

    schedule_cleanup.assert_called_once()
    submit_write.assert_awaited_once()
    assert submit_write.await_args.args[0] == jobs_module.DatabaseWriteOperation.SYNC_JOB_STATUS
    assert submit_write.await_args.args[1]["job_id"] == "job-cancel-1"
    assert submit_write.await_args.args[1]["status"] == (
        jobs_module.JobStatus.CANCELLED.value
    )
    assert isinstance(submit_write.await_args.args[1]["completed_at"], str)
    assert response == {"job_id": "job-cancel-1", "status": "cancelled"}


@pytest.mark.asyncio
async def test_cancel_job_skips_cleanup_when_central_sync_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancelled_job = job_models_module.Job.create(
        name="Cancel Job",
        created_by="webui",
        tasks=[],
    )

    class _FakeJobManager:
        def __init__(self, _redis: object) -> None:
            self.database_writes = SimpleNamespace(
                submit=AsyncMock(side_effect=RuntimeError("db down"))
            )

        async def cancel_job_by_id(
            self,
            job_id: str,
            *,
            reason: str = "",
            wait_for_resource_cleanup: bool = True,
        ) -> object:
            assert job_id == "job-cancel-2"
            assert reason == "cancelled by user"
            assert wait_for_resource_cleanup is False
            return cancelled_job

    monkeypatch.setattr(jobs_module, "JobManager", _FakeJobManager)
    monkeypatch.setattr(jobs_module, "publish_ws_event", AsyncMock())
    schedule_cleanup = MagicMock()
    monkeypatch.setattr(jobs_module, "_schedule_cancel_cleanup", schedule_cleanup)

    response = await jobs_module.cancel_job(
        "job-cancel-2",
        backend=SimpleNamespace(redis=SimpleNamespace(is_connected=True)),
    )

    schedule_cleanup.assert_not_called()
    assert response == {"job_id": "job-cancel-2", "status": "cancelled"}


@pytest.mark.asyncio
async def test_bulk_delete_supports_selected_ids_and_reports_partial_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete = AsyncMock(side_effect=[None, HTTPException(status_code=409, detail="job is changing")])
    monkeypatch.setattr(jobs_module, "delete_job", delete)

    response = await jobs_module.bulk_delete_jobs(
        jobs_module.DeleteJobsRequest(job_ids=["job-a", "job-a", " job-b "]),
        backend=SimpleNamespace(redis=None),
    )

    assert response.requested == 2
    assert response.deleted == 1
    assert response.failed == 1
    assert response.failures[0].job_id == "job-b"
    assert [call.args[0] for call in delete.await_args_list] == ["job-a", "job-b"]


@pytest.mark.asyncio
async def test_bulk_delete_resolves_age_cutoff_on_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    find = AsyncMock(return_value=["old-job-1", "old-job-2"])
    delete = AsyncMock()
    monkeypatch.setattr(jobs_module, "run_database_call", find)
    monkeypatch.setattr(jobs_module, "delete_job", delete)

    response = await jobs_module.bulk_delete_jobs(
        jobs_module.DeleteJobsRequest(older_than_hours=24),
        backend=SimpleNamespace(redis=None),
    )

    assert response == jobs_module.DeleteJobsResponse(
        requested=2,
        deleted=2,
        failed=0,
        failures=[],
    )
    find.assert_awaited_once()
    assert [call.args[0] for call in delete.await_args_list] == ["old-job-1", "old-job-2"]


@pytest.mark.asyncio
async def test_list_jobs_reclassifies_incomplete_active_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_db_archive.global_db as gdb

    created_at = datetime.now(timezone.utc) - timedelta(seconds=45)
    db_job = SimpleNamespace(
        job_id="job-ghost-list",
        job_type="MPS Profile Scrape",
        site="onlyfans",
        status="pending",
        priority=4,
        worker_id="worker-contract",
        created_at=created_at,
        started_at=None,
        completed_at=None,
        last_event_at=None,
        args_json=json.dumps({"job_name": "Ghost List Job", "created_by": "webui_mps"}),
    )

    def _fake_global_session() -> _FakeSession:
        return _FakeSession(
            [
                _FakeExecResult(one_value=1),
                _FakeExecResult(all_rows=[db_job]),
            ]
        )

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def _fake_pipeline_execute(_redis, **_kwargs):
        return [
            {
                "status": "pending",
                "created_at": created_at.isoformat(),
                "total_tasks": "100",
                "completed_tasks": "0",
                "failed_tasks": "0",
            },
            json.dumps(
                {
                    "job_id": "job-ghost-list",
                    "name": "Ghost List Job",
                    "created_by": "webui_mps",
                    "metadata": {"priority": -1},
                    "schedule": None,
                    "task_ids": [],
                }
            ),
            [],
        ]

    mark_failed = AsyncMock()
    monkeypatch.setattr(gdb, "global_session", _fake_global_session)
    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(jobs_module, "_redis_pipeline_execute", _fake_pipeline_execute)
    monkeypatch.setattr(jobs_module, "_redis_zrevrange", AsyncMock(return_value=[]))
    monkeypatch.setattr(jobs_module, "_mark_central_jobs_failed", mark_failed)

    response = await jobs_module.list_jobs(
        status=None,
        search="",
        page=1,
        page_size=50,
        backend=SimpleNamespace(redis=SimpleNamespace()),
    )

    assert response.total == 1
    assert len(response.jobs) == 1
    assert response.jobs[0].status == jobs_module.JobStatus.FAILED
    assert response.jobs[0].job_type == "MPS Profile Scrape"
    assert response.jobs[0].site == "onlyfans"
    assert response.jobs[0].priority == -1
    assert response.jobs[0].worker_id == "worker-contract"
    mark_failed.assert_awaited_once_with(["job-ghost-list"])


def test_restore_central_ghost_jobs_clears_stale_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_db_archive.global_db as gdb

    failure_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    row = SimpleNamespace(
        job_id="job-recovered-central",
        status="failed",
        result_success=False,
        result_error=jobs_module.GHOST_JOB_ERROR,
        completed_at=failure_time,
        result_completed_at=failure_time,
        last_event_at=failure_time,
    )

    class _RepairSession:
        def __init__(self) -> None:
            self.commit = MagicMock()

        def __enter__(self) -> _RepairSession:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def exec(self, _query: object) -> _FakeExecResult:
            return _FakeExecResult(all_rows=[row])

    session = _RepairSession()
    monkeypatch.setattr(gdb, "global_session", lambda: session)

    jobs_module._restore_central_ghost_jobs_sync(
        {"job-recovered-central": "running"}
    )

    assert row.status == "running"
    assert row.result_success is None
    assert row.result_error is None
    assert row.completed_at is None
    assert row.result_completed_at is None
    assert row.last_event_at > failure_time
    session.commit.assert_called_once_with()


@pytest.mark.asyncio
async def test_list_jobs_restores_deferred_materialization_without_task_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_db_archive.global_db as gdb

    created_at = datetime.now(timezone.utc) - timedelta(seconds=45)
    db_job = SimpleNamespace(
        job_id="job-materializing-list",
        job_type="MPS Profile Scrape",
        site="onlyfans",
        status="failed",
        priority=0,
        worker_id=None,
        created_at=created_at,
        started_at=None,
        completed_at=None,
        last_event_at=None,
        result_success=False,
        result_error=jobs_module.GHOST_JOB_ERROR,
        args_json=json.dumps(
            {
                "job_name": "Materializing MPS Job",
                "created_by": "webui_mps",
                "task_count": 915_132,
            }
        ),
    )

    def _fake_global_session() -> _FakeSession:
        return _FakeSession(
            [
                _FakeExecResult(one_value=1),
                _FakeExecResult(all_rows=[db_job]),
            ]
        )

    async def _fake_pipeline_execute(_redis, **_kwargs):
        return [
            {
                "status": "pending",
                "created_at": created_at.isoformat(),
                "total_tasks": "915132",
            },
            json.dumps(
                {
                    "job_id": "job-materializing-list",
                    "name": "Materializing MPS Job",
                    "created_by": "webui_mps",
                    "metadata": {"materialization_status": "materializing"},
                    "schedule": None,
                    "task_ids": [],
                }
            ),
            [],
        ]

    mark_failed = AsyncMock()
    restore_ghost = AsyncMock()
    monkeypatch.setattr(gdb, "global_session", _fake_global_session)
    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _inline_to_thread)
    monkeypatch.setattr(jobs_module, "_redis_pipeline_execute", _fake_pipeline_execute)
    monkeypatch.setattr(jobs_module, "_redis_zrevrange", AsyncMock(return_value=[]))
    monkeypatch.setattr(jobs_module, "_mark_central_jobs_failed", mark_failed)
    monkeypatch.setattr(
        jobs_module,
        "_restore_central_ghost_jobs",
        restore_ghost,
    )

    response = await jobs_module.list_jobs(
        status=None,
        search="",
        page=1,
        page_size=50,
        backend=SimpleNamespace(redis=SimpleNamespace()),
    )

    assert response.total == 1
    assert response.jobs[0].status == jobs_module.JobStatus.PENDING
    assert response.jobs[0].materialization_status == "materializing"
    mark_failed.assert_not_awaited()
    restore_ghost.assert_awaited_once_with({"job-materializing-list": "pending"})


@pytest.mark.asyncio
async def test_list_jobs_reclassifies_fully_missing_active_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_db_archive.global_db as gdb

    created_at = datetime.now(timezone.utc) - timedelta(seconds=45)
    db_job = SimpleNamespace(
        job_id="job-ghost-missing",
        job_type="MPS Profile Scrape",
        status="pending",
        created_at=created_at,
        started_at=None,
        completed_at=None,
        last_event_at=None,
        args_json=json.dumps(
            {
                "job_name": "Ghost Missing Job",
                "created_by": "webui_mps",
                "task_count": 803000,
            }
        ),
    )

    def _fake_global_session() -> _FakeSession:
        return _FakeSession(
            [
                _FakeExecResult(one_value=1),
                _FakeExecResult(all_rows=[db_job]),
            ]
        )

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def _fake_pipeline_execute(_redis, **_kwargs):
        return [None, None, []]

    mark_failed = AsyncMock()
    monkeypatch.setattr(gdb, "global_session", _fake_global_session)
    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(jobs_module, "_redis_pipeline_execute", _fake_pipeline_execute)
    monkeypatch.setattr(jobs_module, "_mark_central_jobs_failed", mark_failed)

    response = await jobs_module.list_jobs(
        status=None,
        search="",
        page=1,
        page_size=50,
        backend=SimpleNamespace(redis=SimpleNamespace()),
    )

    assert response.total == 1
    assert len(response.jobs) == 1
    assert response.jobs[0].job_id == "job-ghost-missing"
    assert response.jobs[0].status == jobs_module.JobStatus.FAILED
    assert response.jobs[0].task_count == 803000
    assert response.jobs[0].task_stats.total == 803000
    mark_failed.assert_awaited_once_with(["job-ghost-missing"])


@pytest.mark.asyncio
async def test_list_jobs_redis_fallback_ignores_taskless_partial_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_db_archive.global_db as gdb

    created_at = datetime.now(timezone.utc) - timedelta(seconds=45)

    def _fake_global_session() -> _FakeSession:
        return _FakeSession(
            [
                _FakeExecResult(one_value=0),
                _FakeExecResult(all_rows=[]),
            ]
        )

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def _fake_pipeline_execute(_redis, **_kwargs):
        return [
            {
                "status": "pending",
                "created_at": created_at.isoformat(),
                "total_tasks": "100",
            },
            json.dumps(
                {
                    "job_id": "job-ghost-fallback",
                    "name": "Ghost Fallback Job",
                    "created_by": "webui_mps",
                    "metadata": {},
                    "schedule": None,
                    "task_ids": [],
                }
            ),
            [],
        ]

    monkeypatch.setattr(gdb, "global_session", _fake_global_session)
    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(jobs_module, "_redis_pipeline_execute", _fake_pipeline_execute)
    monkeypatch.setattr(
        jobs_module,
        "_redis_zrevrange",
        AsyncMock(return_value=["job-ghost-fallback"]),
    )

    response = await jobs_module.list_jobs(
        status=None,
        search="",
        page=1,
        page_size=50,
        backend=SimpleNamespace(redis=SimpleNamespace()),
    )

    assert response.total == 0
    assert response.jobs == []


@pytest.mark.asyncio
async def test_get_job_reclassifies_incomplete_active_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_db_archive.global_db as gdb

    created_at = datetime.now(timezone.utc) - timedelta(seconds=45)
    db_job = SimpleNamespace(
        job_id="job-ghost-detail",
        job_type="MPS Profile Scrape",
        status="pending",
        site="onlyfans",
        priority=0,
        worker_id=None,
        retries=0,
        max_retries=3,
        created_at=created_at,
        started_at=None,
        completed_at=None,
        last_event_at=None,
        result_success=None,
        result_message=None,
        result_error=None,
        args_json=json.dumps({"job_name": "Ghost Detail Job", "task_count": 100}),
    )

    def _fake_global_session() -> _FakeSession:
        return _FakeSession([_FakeExecResult(first_value=db_job)])

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def _fake_pipeline_execute(_redis, **_kwargs):
        return [
            {
                "status": "pending",
                "created_at": created_at.isoformat(),
                "total_tasks": "100",
            },
            json.dumps(
                {
                    "job_id": "job-ghost-detail",
                    "name": "Ghost Detail Job",
                    "created_by": "webui_mps",
                    "metadata": {},
                    "schedule": None,
                    "task_ids": [],
                }
            ),
            [],
        ]

    original_storage = jobs_module.JobStorage

    class _GhostStorage:
        JOB_STATE_KEY = original_storage.JOB_STATE_KEY
        JOB_CONFIG_KEY = original_storage.JOB_CONFIG_KEY
        TASK_INDEX_KEY = original_storage.TASK_INDEX_KEY

        def __init__(self, _redis: object) -> None:
            return None

        async def fetch_job_with_tasks(
            self,
            _job_id: str,
            *,
            include_tasks: bool = True,
            max_include_tasks: int | None = None,
        ) -> object:
            del include_tasks, max_include_tasks
            return SimpleNamespace(
                updated_at=None,
                completed_at=None,
                started_at=None,
                created_at=created_at.isoformat(),
                metadata={},
                total_tasks=100,
                completed_tasks=0,
                failed_tasks=0,
                tasks=[],
            )

        async def get_job_task_stats(self, _job_id: str) -> dict[str, object]:
            return {
                "total": 100,
                "ready": 0,
                "blocked": 0,
                "inflight": 0,
                "deferred": 0,
                "completed": 0,
                "failed": 0,
                "task_type_counts": {},
            }

    mark_failed = AsyncMock()
    monkeypatch.setattr(gdb, "global_session", _fake_global_session)
    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(jobs_module, "_redis_pipeline_execute", _fake_pipeline_execute)
    monkeypatch.setattr(jobs_module, "JobStorage", _GhostStorage)
    monkeypatch.setattr(
        jobs_module,
        "_fetch_central_error_stats_sync",
        lambda _job_id: jobs_module.JobErrorStats(total=0, groups={}),
    )
    monkeypatch.setattr(jobs_module, "_mark_central_jobs_failed", mark_failed)

    response = await jobs_module.get_job(
        "job-ghost-detail",
        include_tasks=False,
        backend=SimpleNamespace(redis=SimpleNamespace()),
    )

    assert response.status == jobs_module.JobStatus.FAILED.value
    assert response.result_success is False
    assert response.result_error == jobs_module.GHOST_JOB_ERROR
    assert response.task_stats.total == 100
    mark_failed.assert_awaited_once_with(
        ["job-ghost-detail"],
        error_message=jobs_module.GHOST_JOB_ERROR,
    )


@pytest.mark.asyncio
async def test_get_job_clears_stale_ghost_error_for_live_redis_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_db_archive.global_db as gdb

    created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    started_at = created_at + timedelta(seconds=30)
    db_job = SimpleNamespace(
        job_id="job-recovered-detail",
        job_type="MPS Profile Scrape",
        status="failed",
        site="onlyfans",
        priority=0,
        worker_id=None,
        retries=0,
        max_retries=3,
        created_at=created_at,
        started_at=None,
        completed_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        last_event_at=None,
        result_success=False,
        result_message=None,
        result_error=jobs_module.GHOST_JOB_ERROR,
        args_json=json.dumps(
            {
                "job_name": "Recovered MPS Job",
                "created_by": "webui_mps",
                "task_count": 915_132,
            }
        ),
    )

    def _fake_global_session() -> _FakeSession:
        return _FakeSession([_FakeExecResult(first_value=db_job)])

    async def _fake_pipeline_execute(_redis, **_kwargs):
        return [
            {
                "status": "running",
                "created_at": created_at.isoformat(),
                "started_at": started_at.isoformat(),
                "materialization_status": "complete",
                "materialized_tasks": "915132",
                "materialization_total": "915132",
                "total_tasks": "915132",
                "ready_tasks": "909000",
                "inflight_tasks": "10",
                "completed_tasks": "6122",
                "failed_tasks": "0",
            },
            json.dumps(
                {
                    "job_id": "job-recovered-detail",
                    "name": "Recovered MPS Job",
                    "created_by": "webui_mps",
                    "metadata": {"materialization_status": "complete"},
                    "schedule": None,
                    "task_ids": [],
                }
            ),
            ["task-1"],
        ]

    original_storage = jobs_module.JobStorage

    class _LiveStorage:
        JOB_STATE_KEY = original_storage.JOB_STATE_KEY
        JOB_CONFIG_KEY = original_storage.JOB_CONFIG_KEY
        TASK_INDEX_KEY = original_storage.TASK_INDEX_KEY

        def __init__(self, _redis: object) -> None:
            return None

        async def get_job_runtime_telemetry(self, _job_id: str) -> None:
            return None

        async def fetch_job_with_tasks(
            self,
            _job_id: str,
            *,
            include_tasks: bool = True,
            max_include_tasks: int | None = None,
        ) -> object:
            del include_tasks, max_include_tasks
            return SimpleNamespace(
                updated_at=datetime.now(timezone.utc).isoformat(),
                completed_at=None,
                started_at=None,
                created_at=created_at.isoformat(),
                metadata={"materialization_status": "complete"},
                total_tasks=915_132,
                completed_tasks=6_122,
                failed_tasks=0,
                tasks=[],
            )

        async def get_job_task_stats(self, _job_id: str) -> dict[str, object]:
            return {
                "total": 915_132,
                "ready": 909_000,
                "blocked": 0,
                "inflight": 10,
                "deferred": 0,
                "completed": 6_122,
                "failed": 0,
                "task_type_counts": {"scrape": 915_132},
            }

    restore_ghost = AsyncMock()
    monkeypatch.setattr(gdb, "global_session", _fake_global_session)
    monkeypatch.setattr(jobs_module, "run_database_call", _inline_to_thread)
    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _inline_to_thread)
    monkeypatch.setattr(jobs_module, "_redis_pipeline_execute", _fake_pipeline_execute)
    monkeypatch.setattr(jobs_module, "JobStorage", _LiveStorage)
    monkeypatch.setattr(
        jobs_module,
        "_fetch_central_error_stats_sync",
        lambda _job_id: jobs_module.JobErrorStats(total=0, groups={}),
    )
    monkeypatch.setattr(
        jobs_module,
        "_restore_central_ghost_jobs",
        restore_ghost,
    )

    response = await jobs_module.get_job(
        "job-recovered-detail",
        include_tasks=False,
        backend=SimpleNamespace(redis=SimpleNamespace()),
    )

    assert response.status == jobs_module.JobStatus.RUNNING.value
    assert response.started_at == started_at.isoformat()
    assert response.result_success is None
    assert response.result_error is None
    assert response.completed_at is None
    restore_ghost.assert_awaited_once_with({"job-recovered-detail": "running"})


@pytest.mark.asyncio
async def test_get_job_reclassifies_fully_missing_active_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_db_archive.global_db as gdb

    created_at = datetime.now(timezone.utc) - timedelta(seconds=45)
    db_job = SimpleNamespace(
        job_id="job-ghost-detail-missing",
        job_type="MPS Profile Scrape",
        status="pending",
        site="onlyfans",
        priority=0,
        worker_id=None,
        retries=0,
        max_retries=3,
        created_at=created_at,
        started_at=None,
        completed_at=None,
        last_event_at=None,
        result_success=None,
        result_message=None,
        result_error=None,
        args_json=json.dumps(
            {"job_name": "Ghost Missing Detail Job", "task_count": 803000}
        ),
    )

    def _fake_global_session() -> _FakeSession:
        return _FakeSession([_FakeExecResult(first_value=db_job)])

    async def _fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def _fake_pipeline_execute(_redis, **_kwargs):
        return [None, None, []]

    original_storage = jobs_module.JobStorage

    class _MissingStorage:
        JOB_STATE_KEY = original_storage.JOB_STATE_KEY
        JOB_CONFIG_KEY = original_storage.JOB_CONFIG_KEY
        TASK_INDEX_KEY = original_storage.TASK_INDEX_KEY

        def __init__(self, _redis: object) -> None:
            return None

        async def fetch_job_with_tasks(
            self,
            _job_id: str,
            *,
            include_tasks: bool = True,
            max_include_tasks: int | None = None,
        ) -> object:
            del include_tasks, max_include_tasks
            return None

        async def get_job_task_stats(self, _job_id: str) -> dict[str, object]:
            return {
                "total": 0,
                "ready": 0,
                "blocked": 0,
                "inflight": 0,
                "deferred": 0,
                "completed": 0,
                "failed": 0,
                "task_type_counts": {},
            }

    mark_failed = AsyncMock()
    monkeypatch.setattr(gdb, "global_session", _fake_global_session)
    monkeypatch.setattr(jobs_module.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(jobs_module, "_redis_pipeline_execute", _fake_pipeline_execute)
    monkeypatch.setattr(jobs_module, "JobStorage", _MissingStorage)
    monkeypatch.setattr(
        jobs_module,
        "_fetch_central_error_stats_sync",
        lambda _job_id: jobs_module.JobErrorStats(total=0, groups={}),
    )
    monkeypatch.setattr(jobs_module, "_mark_central_jobs_failed", mark_failed)

    response = await jobs_module.get_job(
        "job-ghost-detail-missing",
        include_tasks=False,
        backend=SimpleNamespace(redis=SimpleNamespace()),
    )

    assert response.status == jobs_module.JobStatus.FAILED.value
    assert response.result_success is False
    assert response.result_error == jobs_module.GHOST_JOB_ERROR
    assert response.task_stats.total == 803000
    mark_failed.assert_awaited_once_with(
        ["job-ghost-detail-missing"],
        error_message=jobs_module.GHOST_JOB_ERROR,
    )


@pytest.mark.asyncio
async def test_users_search_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeAuthedApi:
        async def get_user(self, username: str) -> object:
            assert username == "alice"
            return SimpleNamespace(
                id=123,
                username="alice",
                name="Alice Example",
                avatar="https://example.com/avatar.jpg",
                header="https://example.com/header.jpg",
                about="Creator profile",
                isVerified=True,
                isSubscribed=True,
                subscribePrice=9.99,
                postsCount=12,
                photosCount=34,
                videosCount=5,
                subscribedByData={"active": True},
            )

    scheduled_syncs: list[tuple[str, str]] = []

    async def _fake_get_guest_api(
        site: str, *, proxy_url: str | None = None
    ) -> object:
        assert site == "OnlyFans"
        assert proxy_url is None
        return _FakeAuthedApi()

    async def _fake_schedule_user_sync(
        user: object,
        site: str,
        *,
        observed_aliases=(),
        wait: bool = False,
    ) -> None:
        scheduled_syncs.append((getattr(user, "username", ""), site))

    monkeypatch.setattr(
        users_module, "_get_guest_api", _fake_get_guest_api
    )
    monkeypatch.setattr(users_module, "_schedule_user_sync", _fake_schedule_user_sync)
    # Exercise the guest lookup; no worker pool (or real backend) is available.
    monkeypatch.setattr(users_module, "get_backend_manager", lambda: None)

    response = await users_module.search_user(username="alice", site="onlyfans")

    assert response.success is True
    assert response.user is not None
    assert response.user.username == "alice"
    assert response.user.site == "OnlyFans"
    assert scheduled_syncs == [("alice", "onlyfans")]


@pytest.mark.asyncio
async def test_auths_list_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auths_module, "MultiSiteDatabaseManager", _FakeDBManager)
    monkeypatch.setattr(
        auths_module, "_apply_auth_filters", lambda query, **_kwargs: query
    )
    monkeypatch.setattr(auths_module, "_get_worker_shard", lambda _auth_id: 0)

    response = auths_module.list_auths(
        site="onlyfans",
        active_only=True,
        status_filter=None,
        username=None,
        user_id=None,
        limit=None,
        offset=0,
    )

    assert response.success is True
    assert response.total == 1
    assert response.auths[0].username == "auth-main"
    assert response.auths[0].worker_shard == 0


@pytest.mark.asyncio
async def test_bulk_delete_stream_reports_cleanup_and_partial_failure(monkeypatch):
    import json

    async def delete(job_id, backend, progress=None):
        if job_id == "bad":
            raise HTTPException(status_code=409, detail="busy")
        progress("execution_outbox", 25000)

    monkeypatch.setattr(jobs_module, "_delete_job_impl", delete)
    response = await jobs_module.bulk_delete_jobs_stream(
        jobs_module.DeleteJobsRequest(job_ids=["good", "bad"]),
        backend=SimpleNamespace(redis=None),
    )
    events = [json.loads(chunk) async for chunk in response.body_iterator]
    assert events[0] == {"type": "progress", "completed": 0, "total": 2}
    assert any(e["type"] == "cleanup" and e["rows"] == 25000 for e in events)
    assert events[-1]["type"] == "result"
    assert events[-1]["deleted"] == 1
    assert events[-1]["failed"] == 1
    assert [e["completed"] for e in events if e["type"] == "progress"] == [0, 1, 2]


@pytest.mark.asyncio
async def test_list_jobs_uses_committed_ledger_status_over_stale_redis(monkeypatch):
    import ultima_scraper_db_archive.global_db as gdb

    jid = 'job-deleting-list'
    created = datetime.now(timezone.utc)
    config = {'job_id': jid, 'name': 'Deleting job', 'created_by': 'test',
              'metadata': {'execution_engine': 'ledger'}, 'schedule': None, 'task_ids': []}
    row = SimpleNamespace(job_id=jid, job_type='mass_profile_scrape', site='onlyfans',
        status='running', priority=0, worker_id=None, created_at=created, started_at=created,
        completed_at=None, last_event_at=created, args_json=json.dumps({'job_name': 'Deleting job', 'task_count': 10}))
    monkeypatch.setattr(gdb, 'global_session', lambda: _FakeSession([
        _FakeExecResult(one_value=1), _FakeExecResult(all_rows=[row])]))
    monkeypatch.setattr(jobs_module, '_redis_pipeline_execute', AsyncMock(return_value=[
        {'status': 'running', 'total_tasks': '10'}, json.dumps(config), []]))
    monkeypatch.setattr(jobs_module, '_fetch_durable_headers_sync', lambda ids: {
        jid: {'config': config, 'status': 'cancelled', 'total': 10, 'completed': 0, 'failed': 0,
              'execution_stats': {'total': 10, 'completed': 0, 'failed': 0}}})
    monkeypatch.setattr(jobs_module, '_redis_zrevrange', AsyncMock(return_value=[]))
    monkeypatch.setattr(jobs_module, 'run_database_call', _inline_to_thread)
    response = await jobs_module.list_jobs(status=None, search='', include_tasks=False,
        include_api_commands=False, page=1, page_size=50,
        backend=SimpleNamespace(redis=SimpleNamespace()))
    assert response.jobs[0].status == jobs_module.JobStatus.CANCELLED


@pytest.mark.asyncio
async def test_list_jobs_filters_by_type_and_returns_available_types(monkeypatch):
    import ultima_scraper_db_archive.global_db as gdb

    jid = 'job-mps-1'
    created = datetime.now(timezone.utc)
    config = {'job_id': jid, 'name': 'MPS job', 'created_by': 'admin',
              'metadata': {'execution_engine': 'ledger'}, 'schedule': None, 'task_ids': []}
    row = SimpleNamespace(job_id=jid, job_type='mass_profile_scrape', site='onlyfans',
        status='running', priority=0, worker_id=None, created_at=created, started_at=created,
        completed_at=None, last_event_at=created, args_json=json.dumps({'job_name': 'MPS job', 'task_count': 5}))
    monkeypatch.setattr(gdb, 'global_session', lambda: _FakeSession([
        _FakeExecResult(one_value=1), _FakeExecResult(all_rows=[row])]))
    monkeypatch.setattr(jobs_module, '_redis_pipeline_execute', AsyncMock(return_value=[
        {'status': 'running', 'total_tasks': '5'}, json.dumps(config), []]))
    monkeypatch.setattr(jobs_module, '_fetch_durable_headers_sync', lambda ids: {
        jid: {'config': config, 'status': 'running', 'total': 5, 'completed': 0, 'failed': 0,
              'execution_stats': {'total': 5, 'completed': 0, 'failed': 0}}})
    monkeypatch.setattr(jobs_module, '_redis_zrevrange', AsyncMock(return_value=[]))
    monkeypatch.setattr(jobs_module, 'run_database_call', _inline_to_thread)
    response = await jobs_module.list_jobs(status=None, search='', include_tasks=False,
        include_api_commands=False, page=1, page_size=50, job_type='mass profile scrape',
        backend=SimpleNamespace(redis=SimpleNamespace()))
    assert response.total == 1
    assert len(response.jobs) == 1
    assert response.jobs[0].job_type == 'mass_profile_scrape'
    assert 'mass_profile_scrape' in response.available_types
