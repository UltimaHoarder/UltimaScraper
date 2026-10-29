"""Pool submission uses SQL ownership and bounded, lazy account expansion."""

import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
from itertools import islice
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, text

import test_mps_manifest as fixtures
from test_job_auth_resources import VirtualAccounts, scrape
from test_normal_durable_inputs import task
from ultima_scraper_backend import database
from ultima_scraper_backend.database.mps_definitions import MPSTaskDefinitions
from ultima_scraper_backend.job_system import Job, JobManager, JobSchedule, JobStorage, durable
from ultima_scraper_backend.job_system.auth_expansion import iter_worker_submission_tasks
from ultima_scraper_backend.job_system.routing import BackendRegistry, BackendRouter
from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded
from ultima_scraper_backend.workers import worker_pool

postgres_engine = fixtures.postgres_engine
store = fixtures.store
redis_manager = fixtures.redis_manager
window_runtime = fixtures.window_runtime


@pytest.fixture
def pool(window_runtime, monkeypatch):
    redis = window_runtime.redis
    redis.connect, redis.disconnect = AsyncMock(), AsyncMock()

    async def get(key):
        value = await redis.client.get(key)
        return value.decode() if isinstance(value, bytes) else value

    redis.get = get  # Match the production RedisManager string interface.
    monkeypatch.setattr(worker_pool, "RedisManager", lambda **kwargs: redis)
    pool = worker_pool.WorkerPool.__new__(worker_pool.WorkerPool)
    pool.config = SimpleNamespace(settings=SimpleNamespace(redis=SimpleNamespace()))
    backends = {
        name: SimpleNamespace(status="online", capabilities=["onlyfans", "extra"], load=load)
        for name, load in (("busy", 5), ("available", 0))
    }
    monkeypatch.setattr(BackendRegistry, "get_all_backends", AsyncMock(return_value=backends))
    monkeypatch.setenv("ULTIMA_JOB_TASK_INSERT_BATCH_SIZE", "2")
    return pool


@pytest.mark.parametrize("total", [100, 1_000_000])
def test_pool_expansion_reads_only_sampled_account_pages(monkeypatch, total):
    accounts = VirtualAccounts(total)
    monkeypatch.setenv("ULTIMA_JOB_AUTH_PAGE_SIZE", "7")
    monkeypatch.setattr(database, "create_usr_database_manager", lambda **kwargs: accounts)
    closed = []

    def inputs():
        try:
            yield scrape()
            pytest.fail("The consumer did not request the second input")
        finally:
            closed.append(True)

    with closing(iter_worker_submission_tasks(inputs())) as source:
        sampled = list(islice(source, 8))
        assert accounts.returned == 7 and accounts.open == 0
        assert [item.auth_id for item in sampled] == [1, 1, 2, 2, 3, 3, 4, 4]
        assert all(child.depends_on == [parent.task_id] for parent, child in zip(sampled[::2], sampled[1::2]))
    assert accounts.disconnected == 1 and closed == [True]


@pytest.mark.parametrize("skip", ["explicit", "guest", "zero", "dependent", "subtasks", "other"])
def test_pool_expansion_preserves_existing_eligibility_rules(monkeypatch, skip):
    source = scrape()
    if skip == "explicit":
        source.auth_id = 19
    elif skip == "guest":
        source.payload.use_guest_auth = True
    elif skip == "zero":
        source.user_id = 0
    elif skip == "dependent":
        source.depends_on = ["parent"]
    elif skip == "subtasks":
        source.subtasks = [SimpleNamespace()]
    else:
        source = task()
    monkeypatch.setattr(database, "create_usr_database_manager", lambda **kwargs: pytest.fail("Ineligible input queried accounts"))
    assert list(iter_worker_submission_tasks([source])) == [source]


@pytest.mark.parametrize("accounts_count", [0, 1])
def test_pool_preserves_empty_auth_fallback_and_single_auth_assignment(monkeypatch, accounts_count):
    accounts = VirtualAccounts(accounts_count)
    monkeypatch.setenv("ULTIMA_JOB_AUTH_PAGE_SIZE", "7")
    monkeypatch.setattr(database, "create_usr_database_manager", lambda **kwargs: accounts)
    original = scrape(download=False)
    result = list(iter_worker_submission_tasks([original]))
    assert len(result) == 1
    assert result[0].auth_id == (1 if accounts_count else None)
    assert original.auth_id is None and accounts.disconnected == 1


async def test_lazy_pool_submission_commits_routing_before_publication(store, pool, window_runtime, monkeypatch):
    produced, closed, batches = [], [], []
    original_append = MPSTaskDefinitions.append

    def append(self, *args, **kwargs):
        batches.append(len(kwargs["tasks"]))
        assert len(produced) <= sum(batches) + 1
        return original_append(self, *args, **kwargs)

    monkeypatch.setattr(MPSTaskDefinitions, "append", append)
    job = Job(name="Pool input", created_by="test", tasks=[], metadata={"required_capabilities": ["extra"]})
    loop = asyncio.get_running_loop()
    get_backends = BackendRegistry.get_all_backends

    async def lookup(redis):
        assert asyncio.get_running_loop() is loop
        assert store.get(job.job_id) is None, "Recovery saw uncommitted definitions"
        return await get_backends(redis)

    monkeypatch.setattr(BackendRegistry, "get_all_backends", lookup)
    # The existing IP lock takes precedence over the lower backend load.
    router = BackendRouter(window_runtime.redis)
    await window_runtime.redis.client.set(router._ip_lock_key("fixture-route"), "busy")

    def inputs():
        try:
            for index in range(9):
                produced.append(index)
                yield task(index, width=10)
        finally:
            closed.append(True)

    assert await pool.run_job(job, tasks=inputs()) == "busy"
    plan = store.get(job.job_id)
    assert plan["site"] == "onlyfans" and plan["total"] == 9
    assert plan["job_config"]["metadata"]["dispatch_backend_id"] == "busy"
    assert plan["job_config"]["metadata"]["required_capabilities"] == ["extra", "onlyfans"]
    assert plan["job_config"]["metadata"]["dispatch_priority"] == 10
    assert job.tasks == [] and closed == [True] and max(batches) == 2
    storage = JobStorage(window_runtime.redis)
    cached = await storage.fetch_job(job.job_id, include_tasks=False)
    assert cached.total_tasks == 9 and cached.tasks == []
    assert await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=job.job_id)) == 0
    window_runtime.redis.disconnect.assert_awaited_once()


async def test_no_eligible_backend_rolls_back_complete_preparation(store, pool, window_runtime, monkeypatch):
    monkeypatch.setattr(BackendRegistry, "get_all_backends", AsyncMock(return_value={}))
    job = Job(name="No backend", created_by="test", tasks=[task(i, width=10) for i in range(5)])
    with pytest.raises(RuntimeError, match="No backends"):
        await pool.run_job(job)
    assert store.get(job.job_id) is None
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.mps_task_definitions")) == 0
    assert not await JobStorage(window_runtime.redis).fetch_job(job.job_id, include_tasks=False)
    window_runtime.redis.disconnect.assert_awaited_once()


async def test_late_auth_failure_rolls_back_and_closes_owned_inputs(store, pool, window_runtime, monkeypatch):
    accounts = VirtualAccounts(100)
    get_session = accounts.get_session

    def session():
        if accounts.returned:
            raise RuntimeError("later account page failed")
        return get_session()

    accounts.get_session = session
    monkeypatch.setenv("ULTIMA_JOB_AUTH_PAGE_SIZE", "7")
    monkeypatch.setattr(database, "create_usr_database_manager", lambda **kwargs: accounts)
    job = Job(name="Auth failure", created_by="test", tasks=[scrape(download=False)])
    with pytest.raises(RuntimeError, match="later account page"):
        await pool.run_job(job)
    assert accounts.returned == 7 and accounts.disconnected == 1
    assert store.get(job.job_id) is None
    with store.session_factory() as session:
        assert session.scalar(text("SELECT count(*) FROM management.mps_task_definitions")) == 0
    assert not await JobStorage(window_runtime.redis).fetch_job(job.job_id, include_tasks=False)


async def test_interrupted_publication_recovers_committed_pool_assignment(store, pool, window_runtime, monkeypatch):
    original = JobManager.activate_job
    monkeypatch.setattr(JobManager, "activate_job", AsyncMock(side_effect=RuntimeError("publication interrupted")))
    job = Job(name="Interrupted pool", created_by="test", tasks=[task(0, width=10)])
    with pytest.raises(RuntimeError, match="publication interrupted"):
        await pool.run_job(job)
    assert store.get(job.job_id)["job_config"]["metadata"]["dispatch_backend_id"] == "available"
    monkeypatch.setattr(JobManager, "activate_job", original)
    await durable.recover(window_runtime)
    recovered = await JobStorage(window_runtime.redis).fetch_job(job.job_id, include_tasks=False)
    assert recovered.total_tasks == 1 and recovered.metadata["dispatch_backend_id"] == "available"


async def test_pool_returns_assignment_when_headers_are_full_or_job_is_future(store, pool, window_runtime, monkeypatch):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_MAX_HEADERS", "1")
    storage = JobStorage(window_runtime.redis)
    for index in range(3):
        job = Job(name=f"Pool {index}", created_by="test", tasks=[task(index, width=10)])
        if index == 2:
            job.schedule = JobSchedule(scheduled_for=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        assert await pool.run_job(job) == "available"
        assert store.get(job.job_id)["total"] == 1
        assert bool(await storage.fetch_job(job.job_id, include_tasks=False)) is (index == 0)
    assert await storage._client().zcard(storage.JOB_INDEX_KEY) == 1


@pytest.mark.parametrize("adapter", ["chats", "orders"])
@pytest.mark.parametrize("distributed", [False, True])
async def test_purchase_adapters_prepare_sql_before_bounded_activation(store, window_runtime, monkeypatch, adapter, distributed):
    from ultima_scraper_backend.api.routes import chats, orders
    from ultima_scraper_backend.job_system.templates import JobTemplateStore

    window_runtime.distributed_mode = distributed
    monkeypatch.setattr(chats, "get_backend_instance", AsyncMock(return_value=window_runtime))
    monkeypatch.setenv("ULTIMA_JOB_WINDOW_MAX_TASKS", "1")
    if adapter == "chats":
        await chats._create_ppv_scrape_job("onlyfans", 19, 99, "fixture", window_runtime)
        expected = 2
    else:
        one, two = task(0, width=10), task(1, width=10)
        two.depends_on = [one.task_id]
        template = SimpleNamespace(instantiate=lambda *args, **kwargs: SimpleNamespace(
            tasks=[one, two], job_name="Purchase fixture", metadata={},
        ))
        monkeypatch.setattr(JobTemplateStore, "get_template_by_name", AsyncMock(return_value=template))
        await orders._create_scrape_download_job("onlyfans", 19, 99, "fixture", window_runtime, backend=window_runtime)
        expected = 2
    plans = store.active_page(limit=10)
    assert len(plans) == 1
    plan = store.get(plans[0])
    assert plan["total"] == expected and plan["job_config"]["metadata"]["durable_job_kind"] == "ordinary"
    assert plan["job_config"]["metadata"].get("dispatch_backend_id") == (None if distributed else window_runtime.instance_id)
    storage = JobStorage(window_runtime.redis)
    assert await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=plan["job_id"])) == 0
    await durable.advance(window_runtime, plan["job_id"])
    assert await storage._client().zcard(storage.TASK_INDEX_KEY.format(job_id=plan["job_id"])) == 1


async def test_prepared_adapter_preserves_explicit_routing_and_header_capabilities(store, window_runtime):
    manager = JobManager(window_runtime.redis)
    original = Job(name="Adapter", created_by="test", tasks=[task(0, width=10)], metadata={"required_capabilities": ["extra"]})
    prepared = await manager.prepare_job(original, backend_id="target")
    assert prepared.tasks == [] and prepared.total_tasks == 1
    assert prepared.metadata["dispatch_backend_id"] == "target"
    assert prepared.metadata["required_capabilities"] == ["extra", "onlyfans"]
    assert original.tasks[0].auth_id == 19


@pytest.mark.parametrize("oversize", ["capabilities", "ip-lock"])
async def test_routing_rejects_oversized_aggregates_before_fetching_them(store, pool, window_runtime, monkeypatch, oversize):
    monkeypatch.setenv("ULTIMA_JOB_RUNTIME_HEADER_MAX_BYTES", "1024")
    tasks = [task(i, width=10) for i in range(7)]
    for index, item in enumerate(tasks):
        if oversize == "capabilities":
            item.capabilities = [str(index) + "x" * 300]
        else:
            item.ip_lock_key = "x" * 2000
    job = Job(name="Routing budget", created_by="test", tasks=tasks)
    statements = []
    # Use the actual SQL connection event, not a Python replacement for the store.
    with store.session_factory() as session:
        engine = session.get_bind()

    def query(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", query)
    try:
        with pytest.raises(TaskPayloadBudgetExceeded, match="routing"):
            await pool.run_job(job)
    finally:
        event.remove(engine, "before_cursor_execute", query)
    if oversize == "capabilities":
        assert not any("ORDER BY capability" in sql for sql in statements)
    assert store.get(job.job_id) is None
