"""SQL worker services replace Redis dispatch and scheduling in every runtime."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ultima_scraper_backend.config import ExecutionMode
from ultima_scraper_backend.job_system import ledger as ledger_module
from ultima_scraper_backend.job_system import ledger_runtime
from ultima_scraper_backend.job_system.models import Job
from ultima_scraper_backend.job_system.manager import JobManager
from ultima_scraper_backend.workers import worker_pool


@pytest.fixture
def pool_config(monkeypatch):
    config = SimpleNamespace(
        settings=SimpleNamespace(
            worker_pool=SimpleNamespace(max_claimed_jobs=10, sites=["onlyfans"]),
            backend=SimpleNamespace(execution_mode=ExecutionMode.LOCAL),
            redis=SimpleNamespace(enabled=True, host="owned-fixture"),
            get_backend_id=lambda: "fixture",
        )
    )
    monkeypatch.setattr(
        worker_pool.UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        lambda: config,
    )
    return config


@pytest.mark.parametrize("mode", ["worker", "webui", "api"])
@pytest.mark.parametrize("distributed", [False, True])
def test_standalone_worker_owns_sql_service_and_closes_it(
    monkeypatch,
    pool_config,
    mode,
    distributed,
):
    pool_config.settings.backend.execution_mode = (
        ExecutionMode.DISTRIBUTED if distributed else ExecutionMode.LOCAL
    )
    monkeypatch.setenv("RUN_MODE", mode)
    monkeypatch.delenv("ULTIMA_JOB_ENGINE", raising=False)
    events = []
    started = threading.Event()

    class Redis:
        def __init__(self, **kwargs):
            pass

        async def connect(self):
            events.append("connect")

        async def disconnect(self):
            events.append("disconnect")

    async def service(backend):
        events.append("ledger:start")
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            events.append("ledger:stop")

    monkeypatch.setattr(worker_pool, "RedisManager", Redis)
    monkeypatch.setattr(ledger_runtime, "service", service)
    pool = worker_pool.WorkerPool(num_workers=1, backend_id="fixture")
    try:
        pool._start_job_service(startup_timeout=2)
        if mode == "worker":
            assert started.wait(2)
            pool._start_job_service(startup_timeout=2)
            assert events.count("ledger:start") == 1
        else:
            assert not events
    finally:
        pool._stop_job_service(timeout=2)
    assert events == (
        ["connect", "ledger:start", "ledger:stop", "disconnect"]
        if mode == "worker"
        else []
    )


def test_sql_service_startup_connection_error_prevents_worker_start(
    monkeypatch,
    pool_config,
):
    monkeypatch.setenv("RUN_MODE", "worker")
    disconnect = Mock()

    class Redis:
        def __init__(self, **kwargs):
            pass

        async def connect(self):
            raise ConnectionError("owned-fixture unavailable")

        async def disconnect(self):
            disconnect()

    monkeypatch.setattr(worker_pool, "RedisManager", Redis)
    pool = worker_pool.WorkerPool(num_workers=1, backend_id="fixture")
    try:
        with pytest.raises(RuntimeError, match="Failed to start execution ledger"):
            pool._start_job_service(startup_timeout=2)
    finally:
        pool._stop_job_service(timeout=2)
    disconnect.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "index,count,lanes",
    [(0, 1, [None]), (0, 2, ["interactive", None]), (1, 2, [None])],
)
async def test_empty_sql_claims_never_fall_back_to_redis(
    monkeypatch, index, count, lanes
):
    ledger = SimpleNamespace(claim_many=Mock(return_value=[]))
    monkeypatch.setattr(ledger_runtime, "ExecutionLedger", lambda: ledger)
    worker = SimpleNamespace(
        supported_sites=["onlyfans"],
        worker_count=count,
        worker_index=index,
        worker_id="owned-worker",
    )
    router = ledger_runtime.LedgerRouterAdapter(worker)
    assert await router.claim_ready_tasks("owned-backend", count=4) == []
    assert [call.kwargs["lane"] for call in ledger.claim_many.call_args_list] == lanes
    assert worker._ledger_claims == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("interactive", [0, 1, 4])
async def test_worker_zero_tops_up_interactive_claims_with_batch_work(
    monkeypatch, interactive
):
    def claim_many(*, lane, count, **_):
        made = interactive if lane == "interactive" else count
        return [
            SimpleNamespace(run_id=f"run-{lane}", task_id=f"{lane}-{n}")
            for n in range(min(made, count))
        ]

    ledger = SimpleNamespace(claim_many=Mock(side_effect=claim_many))
    monkeypatch.setattr(ledger_runtime, "ExecutionLedger", lambda: ledger)
    worker = SimpleNamespace(
        supported_sites=["onlyfans"], worker_count=8, worker_index=0,
        worker_id="worker-zero",
    )
    router = ledger_runtime.LedgerRouterAdapter(worker)
    claimed = await router.claim_ready_tasks("owned-backend", count=4)
    # Interactive commands first, then batch work up to the requested count.
    assert claimed == [
        *[("run-interactive", f"interactive-{n}") for n in range(interactive)],
        *[("run-None", f"None-{n}") for n in range(4 - interactive)],
    ]
    calls = [(c.kwargs["lane"], c.kwargs["count"]) for c in ledger.claim_many.call_args_list]
    assert calls == [("interactive", 4)] + ([(None, 4 - interactive)] if interactive < 4 else [])


@pytest.mark.asyncio
async def test_worker_refuses_task_without_sql_attempt():
    worker = worker_pool.Worker.__new__(worker_pool.Worker)
    worker.worker_id = "owned-worker"
    worker._claim_runtime_context = {}
    worker._ledger_claims = {}
    worker.task_job_storage = SimpleNamespace(
        fetch_job=AsyncMock(), fetch_task=AsyncMock()
    )
    assert await worker._execute_ready_task("job-old", "task-old") == (
        False,
        False,
        None,
    )
    worker.task_job_storage.fetch_job.assert_not_awaited()
    worker.task_job_storage.fetch_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_loop_executes_sql_claims_without_redis_dispatch(monkeypatch):
    worker = worker_pool.Worker.__new__(worker_pool.Worker)
    worker.worker_id, worker.backend_id = "owned-worker", "owned-backend"
    worker.supported_sites = ["onlyfans"]
    worker.worker_count, worker.worker_index = 1, 0
    worker.apis, worker.task_job_storage = {"onlyfans": object()}, object()
    worker._shutdown_event = asyncio.Event()
    worker._claim_runtime_context = {}
    worker._update_worker_status = AsyncMock()
    worker.compute_dynamic_concurrency = lambda: 8
    worker.compute_claim_batch_size = lambda available: available
    claim = SimpleNamespace(run_id="job-sql", task_id="task-sql")

    def claim_many(**kwargs):
        assert kwargs["count"] == 8
        worker.running = False
        return [claim]

    ledger = SimpleNamespace(claim_many=claim_many, limits=ledger_module.Limits(batch=8))
    execute = AsyncMock(return_value=(True, True, True))
    monkeypatch.setattr(ledger_runtime, "ExecutionLedger", lambda: ledger)
    monkeypatch.setattr(ledger_runtime, "execute", execute)
    await worker.run()
    execute.assert_awaited_once()
    assert execute.await_args.args == (worker, ledger, claim)
    # Eight fetch slots plus min(8, batch) persistence slots share one attempt set.
    assert execute.await_args.kwargs["effective_worker_concurrency"] == 16
    assert worker._ledger_claims == {}
    assert not worker.running


@pytest.mark.asyncio
async def test_activation_requires_sql_admission():
    manager = JobManager(SimpleNamespace())
    with pytest.raises(ValueError, match="admitted to the execution ledger"):
        await manager.activate_job(
            Job.create(name="Unadmitted", created_by="test", tasks=[]),
            distributed_mode=True,
        )
    job = Job.create(
        name="Admitted",
        created_by="test",
        tasks=[],
        metadata={"execution_engine": "ledger"},
    )
    assert await manager.activate_job(job, distributed_mode=True) == (None, [])


@pytest.mark.asyncio
async def test_control_service_start_is_idempotent_and_stop_cancels(monkeypatch):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def service(backend):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(ledger_runtime, "service", service)
    await ledger_runtime.start_service(SimpleNamespace())
    await asyncio.wait_for(started.wait(), 2)
    task = ledger_runtime._service_task
    try:
        await ledger_runtime.start_service(SimpleNamespace())
        assert ledger_runtime._service_task is task
    finally:
        await ledger_runtime.stop_service()
    assert stopped.is_set() and ledger_runtime._service_task is None
