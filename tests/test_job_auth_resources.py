"""Account-backed producers must stop at bounded SQL pages, including large inputs."""

from contextlib import closing
from itertools import islice
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlmodel import Session
from ultima_scraper_api import ContentType
from ultima_scraper_backend.api.routes import jobs
from ultima_scraper_backend.job_system import TaskType, auth_expansion, job_builder


class VirtualAccounts:
    def __init__(self, total):
        self.total = total
        self.returned = self.open = self.disconnected = 0
        self.queries = []
        self.site = "onlyfans"

    def ensure_connected(self):
        pass

    def disconnect(self):
        self.disconnected += 1

    def get_session(self):
        parent = self

        class PageSession:
            def __enter__(self):
                parent.open += 1
                return self

            def __exit__(self, *args):
                self.close()

            def close(self):
                parent.open = 0

            def exec(self, query):
                assert query._limit_clause is not None, (
                    "Account discovery requested all rows"
                )
                limit = query._limit_clause.value
                assert 0 < limit <= 7
                sql = str(query)
                assert "OFFSET" not in sql
                parent.queries.append(sql)
                count = min(limit, parent.total - parent.returned)
                start = parent.returned + 1
                parent.returned += count
                # A fixture exposes only the scalar IDs or compact projected
                # account metadata requested by the producer, never credentials.
                if len(query.selected_columns) == 1:
                    rows = list(range(start, start + count))
                else:
                    assert len(query.selected_columns) <= 4
                    rows = [
                        SimpleNamespace(
                            id=i, user_id=i, username=f"auth-{i}", username_bytes=10
                        )
                        for i in range(start, start + count)
                    ]
                return type("Rows", (list,), {"all": lambda self: list(self)})(rows)

        return PageSession()


def scrape(*, auth_id=None, download=True):
    return job_builder.build_task(
        TaskType.SCRAPE,
        site_name="OnlyFans",
        user_id=999,
        user_username="creator",
        content_type=ContentType.POSTS,
        auth_id=auth_id,
        download_media=download,
    )


@pytest.mark.parametrize("download", [False, True])
def test_guest_scrape_preserves_requested_download_without_account_lookup(
    monkeypatch, download
):
    manager = VirtualAccounts(0)
    monkeypatch.setattr(
        job_builder, "create_usr_database_manager", lambda **kwargs: manager
    )
    task = scrape(download=download)
    task.payload.use_guest_auth = True
    tasks = list(job_builder.iter_expanded_tasks([task]))
    assert tasks[0] is task and tasks[0].payload.use_guest_auth
    assert manager.queries == [] and manager.disconnected == 1
    assert len(tasks) == (2 if download else 1)
    if download:
        assert tasks[1].task_type == TaskType.DOWNLOAD
        assert tasks[1].depends_on == [task.task_id]
        assert tasks[1].auth_id is None


@pytest.mark.parametrize("total", [100, 1_000_000])
def test_one_scrape_expands_only_consumed_account_pages(monkeypatch, total):
    manager = VirtualAccounts(total)
    monkeypatch.setenv("ULTIMA_JOB_AUTH_PAGE_SIZE", "7")
    monkeypatch.setattr(
        job_builder, "create_usr_database_manager", lambda **kwargs: manager
    )
    with closing(job_builder.iter_expanded_tasks([scrape()])) as source:
        tasks = list(islice(source, 8))
        assert manager.returned == 7
        assert manager.open == 0, "A yielded task retained a database session"
        for first, second in zip(tasks[::2], tasks[1::2]):
            assert first.task_type == TaskType.SCRAPE
            assert second.task_type == TaskType.DOWNLOAD
            assert second.depends_on == [first.task_id]
            assert second.auth_id == first.auth_id
    assert manager.disconnected == 1


@pytest.mark.parametrize("total", [100, 1_000_000])
async def test_subscription_refresh_yields_without_loading_all_auths(
    monkeypatch, total
):
    manager = VirtualAccounts(total)
    monkeypatch.setenv("ULTIMA_JOB_AUTH_PAGE_SIZE", "7")
    backend = SimpleNamespace(
        multi_site_db_manager=SimpleNamespace(
            get_or_create_manager=lambda site: manager
        )
    )
    source = await jobs._build_task_from_payload(
        jobs.TaskPayload(
            task_type="refresh_subscriptions", params={"site": "OnlyFans"}
        ),
        backend,
    )
    assert hasattr(source, "__aiter__"), (
        "Refresh construction returned a complete task collection"
    )
    try:
        first = await anext(source)
        assert first.auth_id == first.user_id == 1
        assert first.content_type == ContentType.SUBSCRIPTIONS
        assert manager.returned == 7 and manager.open == 0
        assert all(
            "cookie" not in sql and "authorization" not in sql
            for sql in manager.queries
        )
    finally:
        await source.aclose()


@pytest.fixture
def accounts():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def functions(connection, record):
        connection.create_function(
            "octet_length", 1, lambda value: len((value or "").encode())
        )

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE user_auths (id integer PRIMARY KEY, user_id bigint, site text, active boolean, username text)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE subscriptions (user_id bigint, subscriber_id bigint, active boolean)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO user_auths VALUES (:id,:user_id,:site,:active,:username)"
            ),
            [
                {
                    "id": i,
                    "user_id": user,
                    "site": site,
                    "active": active,
                    "username": name,
                }
                for i, user, site, active, name in [
                    (1, 10, "onlyfans", True, "first"),
                    (2, 10, "onlyfans", True, "duplicate"),
                    (3, 30, "onlyfans", False, "inactive"),
                    (4, 40, "fansly", True, "other-site"),
                    (5, 50, "onlyfans", True, "expired-sub"),
                    (6, 60, "onlyfans", True, "last"),
                    (10, 100, "onlyfans", True, "exact-record"),
                    (11, 110, "onlyfans", True, "é" * 100),
                ]
            ],
        )
        connection.execute(
            text("INSERT INTO subscriptions VALUES (999,:subscriber,:active)"),
            [{"subscriber": i, "active": i != 50} for i in (10, 30, 40, 50, 60)],
        )
    manager = SimpleNamespace(
        site="onlyfans",
        ensure_connected=lambda: None,
        get_session=lambda: Session(engine),
    )
    try:
        yield manager
    finally:
        engine.dispose()


@pytest.mark.parametrize("inactive,expected", [(False, [10, 60]), (True, [10, 50, 60])])
def test_paged_subscription_selection_keeps_access_semantics(
    accounts, monkeypatch, inactive, expected
):
    monkeypatch.setenv("ULTIMA_JOB_AUTH_PAGE_SIZE", "1")
    assert (
        auth_expansion.get_eligible_auth_ids_for_user(
            db_manager=accounts,
            performer_user_id=999,
            include_inactive_subscriptions=inactive,
        )
        == expected
    )


def test_explicit_auth_needs_no_account_query():
    with closing(
        auth_expansion.iter_scrape_tasks_by_db_subscriptions(
            task=scrape(auth_id=77), db_manager=None
        )
    ) as source:
        values = list(source)
    assert [task.auth_id for task in values] == [77, 77]
    assert values[1].depends_on == [values[0].task_id]


@pytest.mark.parametrize("requested,expected", [(10, [100]), (60, [60]), (909, [])])
async def test_refresh_prefers_record_id_then_user_id(
    accounts, monkeypatch, requested, expected
):
    async def inline(call, *args, **kwargs):
        return call(*args, **kwargs)

    monkeypatch.setattr(jobs.asyncio, "to_thread", inline)
    monkeypatch.setenv("ULTIMA_JOB_AUTH_PAGE_SIZE", "1")
    backend = SimpleNamespace(
        multi_site_db_manager=SimpleNamespace(
            get_or_create_manager=lambda site: accounts
        )
    )
    source = await jobs._build_task_from_payload(
        jobs.TaskPayload(
            task_type="refresh_subscriptions", params={"auth_id": requested}
        ),
        backend,
    )
    assert [task.auth_id async for task in source] == expected


async def test_refresh_rejects_large_username_before_transferring_it(
    accounts, monkeypatch
):
    from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded

    async def inline(call, *args, **kwargs):
        return call(*args, **kwargs)

    monkeypatch.setattr(jobs.asyncio, "to_thread", inline)
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_MAX_BYTES", "100")
    backend = SimpleNamespace(
        multi_site_db_manager=SimpleNamespace(
            get_or_create_manager=lambda site: accounts
        )
    )
    source = await jobs._build_task_from_payload(
        jobs.TaskPayload(task_type="refresh_subscriptions", params={"auth_id": 11}),
        backend,
    )
    with pytest.raises(TaskPayloadBudgetExceeded):
        await anext(source)
    await source.aclose()


async def test_refresh_byte_pages_do_not_skip_accounts(accounts, monkeypatch):
    async def inline(call, *args, **kwargs):
        return call(*args, **kwargs)

    monkeypatch.setattr(jobs.asyncio, "to_thread", inline)
    monkeypatch.setenv("ULTIMA_JOB_AUTH_PAGE_SIZE", "7")
    monkeypatch.setenv("ULTIMA_JOB_AUTH_PAGE_MAX_BYTES", "240")
    source = auth_expansion.iter_subscription_refresh_tasks(
        multi_site_db_manager=SimpleNamespace(
            get_or_create_manager=lambda site: accounts
        ),
        site_name="OnlyFans",
        requested_auth_id=None,
    )
    rows = [task async for task in source]
    assert [task.auth_id for task in rows] == [10, 10, 50, 60, 100, 110]
    assert rows[-1].user_username == "é" * 100


async def test_refresh_source_closes_when_staging_rejects_a_task(monkeypatch):
    from ultima_scraper_backend.job_system.storage import TaskPayloadBudgetExceeded

    closed = []

    async def incoming():
        try:
            yield scrape(auth_id=77, download=False)
            pytest.fail("A rejected input pulled the remaining account source")
        finally:
            closed.append(True)

    async def build(*args, **kwargs):
        return incoming()

    monkeypatch.setattr(jobs, "_build_task_from_payload", build)
    monkeypatch.setenv("ULTIMA_JOB_TASK_INPUT_MAX_BYTES", "1")
    request = jobs.CreateJobRequest(
        job_name="Rejected refresh",
        created_by="fixture",
        tasks=[jobs.TaskPayload(task_type="refresh_subscriptions", params={})],
    )
    with pytest.raises(TaskPayloadBudgetExceeded):
        async with jobs._prepare_created_job(
            request, SimpleNamespace(redis=True), SimpleNamespace()
        ):
            pytest.fail("An oversized input published prepared work")
    assert closed == [True]
