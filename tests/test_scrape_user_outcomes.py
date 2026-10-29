"""Regressions from a guest-auth scrape_user run against an empty archive.

The performer row was never written, every post save failed on
``x_posts_user_id_fkey``, the download task failed, and the job still ended
``completed``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable
from sqlmodel import Session, create_engine
from ultima_scraper_api import ContentType

import ultima_scraper_backend.job_system.handlers.scrape.handler as scrape_handler_module
from ultima_scraper_backend.database.write_queue import DatabaseWriteOperation
from ultima_scraper_backend.job_system.durable import job_from_plan
from ultima_scraper_backend.job_system.ledger import ExecutionLedger
from ultima_scraper_backend.job_system.models import (
    Job,
    JobState,
    Task,
    TaskRunContext,
    TaskType,
)
from ultima_scraper_backend.job_system.payloads import ScrapeTaskPayload
from ultima_scraper_backend.manager import BackendManager
from ultima_scraper_db_archive import PostModel, StoryModel, UserModel

PERFORMER_ID = 15585607


def _fk_enforcing_engine():
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    # Tables only: the archive's NULLS LAST indexes are PostgreSQL syntax.
    with engine.begin() as connection:
        for model in (UserModel, PostModel, StoryModel):
            connection.execute(CreateTable(model.__table__))
    return engine


class _Author:
    def get_authed(self):
        return None


class _Content:
    def __init__(self, content_id: int) -> None:
        self.id = content_id
        self.text = "post"
        self.price = 0.0
        self.media = []
        self.created_at = datetime.now(timezone.utc)
        self.isArchived = False
        self.linkedUsers = []
        self.linkedPosts = []

    def get_author(self):
        return _Author()


class _Post(_Content):
    pass


class _Story(_Content):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("content_class", [_Post, _Story])
async def test_content_save_creates_missing_owner_row(content_class) -> None:
    engine = _fk_enforcing_engine()
    manager = object.__new__(BackendManager)

    with Session(engine) as session:
        result = await manager.save_content(
            content_class(9001),
            PERFORMER_ID,
            site="onlyfans",
            db_session=session,
        )
        assert result.success, result.message
        session.commit()
        assert session.get(UserModel, PERFORMER_ID) is not None


def _guest_posts_task() -> Task:
    return Task(
        site_name="onlyfans",
        user_id=PERFORMER_ID,
        user_username="onlyfans",
        content_type=ContentType.POSTS,
        task_type=TaskType.SCRAPE,
        auth_id=9001,
        payload=ScrapeTaskPayload(
            user_username="onlyfans",
            max_items=4,
            download_media=True,
            rescrape_existing=False,
        ),
    )


def _context(authed: object, task: Task, submit: AsyncMock) -> TaskRunContext:
    site_api = SimpleNamespace(
        find_auth=lambda auth_id: authed if auth_id == getattr(authed, "id", None) else None
    )
    return TaskRunContext(
        job=Job(name="scrape onlyfans", created_by="pytest", tasks=[task]),
        storage=SimpleNamespace(persist_task=AsyncMock()),
        previous_output=None,
        context={
            "site_api": site_api,
            "db_managers": {
                "onlyfans": SimpleNamespace(
                    get_user_auth=lambda auth_id: SimpleNamespace(user_id=auth_id)
                )
            },
            "site": "onlyfans",
            "worker_id": "worker-posts",
            "database_writes": SimpleNamespace(submit=submit),
        },
    )


def _performer() -> SimpleNamespace:
    return SimpleNamespace(
        id=PERFORMER_ID,
        username="onlyfans",
        posts_count=4,
        is_performer=True,
    )


@pytest.mark.asyncio
async def test_content_scrape_persists_performer_before_saving_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    performer = _performer()
    authed = SimpleNamespace(
        id=9001,
        username="guest",
        find_user=lambda _identifier: performer,
        get_user=AsyncMock(),
    )
    submit = AsyncMock(return_value={"synced": True})
    order: list[str] = []
    submit.side_effect = lambda operation, *args, **kwargs: (
        order.append(operation) or {"synced": True}
    )

    async def fake_scrape_content_type(*args, **kwargs):
        order.append("scrape")
        return 4, 4, [], []

    monkeypatch.setattr(
        scrape_handler_module, "scrape_content_type", fake_scrape_content_type
    )
    monkeypatch.setattr(scrape_handler_module, "publish_hook_event", AsyncMock())

    task = _guest_posts_task()
    result = await scrape_handler_module.scrape_task_handler(
        task, _context(authed, task, submit)
    )

    assert result.success is True, result.message
    assert order == [DatabaseWriteOperation.UPSERT_USER, "scrape"]
    payload = submit.call_args_list[0].args[1]
    assert payload["user"]["id"] == PERFORMER_ID
    assert payload["user"]["username"] == "onlyfans"
    assert payload["user"]["is_performer"] is True
    assert submit.call_args_list[0].kwargs["site"] == "onlyfans"


@pytest.mark.asyncio
async def test_content_scrape_fails_when_no_scraped_item_was_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    performer = _performer()
    authed = SimpleNamespace(
        id=9001,
        username="guest",
        find_user=lambda _identifier: performer,
        get_user=AsyncMock(),
    )
    fk_error = (
        "Failed to save 1: IntegrityError: insert or update on table x_posts "
        "violates foreign key constraint x_posts_user_id_fkey"
    )
    monkeypatch.setattr(
        scrape_handler_module,
        "scrape_content_type",
        AsyncMock(return_value=(4, 0, [fk_error], [])),
    )
    monkeypatch.setattr(scrape_handler_module, "publish_hook_event", AsyncMock())

    task = _guest_posts_task()
    result = await scrape_handler_module.scrape_task_handler(
        task, _context(authed, task, AsyncMock(return_value={"synced": True}))
    )

    assert result.success is False
    assert "x_posts_user_id_fkey" in result.message


@pytest.mark.parametrize(
    ("kind", "completed", "failed", "expected"),
    [
        ("ordinary", 1, 1, "failed"),
        ("ordinary", 2, 0, "completed"),
        ("ordinary", 0, 0, "completed"),
        ("mps", 1, 1, "completed"),
        ("mps", 0, 3, "failed"),
        (None, 1, 1, "completed"),
    ],
)
def test_terminal_job_state_by_job_kind(kind, completed, failed, expected) -> None:
    from ultima_scraper_backend.job_system.resources import terminal_job_state

    metadata = {"durable_job_kind": kind} if kind else {}
    assert terminal_job_state({"metadata": metadata}, completed, failed) == expected


def test_ordinary_job_with_failed_download_finishes_failed() -> None:
    """The scrape task completed and its download failed: management.jobs says failed."""
    central = SimpleNamespace(status="running", completed_at=None)
    added: list[object] = []
    session = SimpleNamespace(get=lambda _model, _key: central, add=added.append)
    run = SimpleNamespace(run_id="api-job", state="running", completed_at=None)
    source = SimpleNamespace(job_config_json="{}")
    plan = {
        "job_config": {"metadata": {"durable_job_kind": "ordinary"}},
        "completed": 1,
        "failed": 1,
        "total": 2,
    }
    now = datetime.now(timezone.utc)

    ExecutionLedger._complete_run(
        object.__new__(ExecutionLedger), session, run, source, plan, now
    )

    assert run.state == "failed"
    assert central.status == "failed"
    assert json.loads(added[0].payload_json)["status"] == "failed"


def test_ordinary_plan_view_reports_failed_job() -> None:
    task = _guest_posts_task()
    job = Job(name="scrape onlyfans", created_by="pytest", tasks=[task])
    config = job.to_dict()
    config["metadata"] = {"durable_job_kind": "ordinary", "mps_manifest": True}
    plan = {
        "job_config": config,
        "status": "complete",
        "completed": 1,
        "failed": 1,
        "total": 2,
        "cursor": 2,
        "summary": {},
        "selection": {},
    }
    assert job_from_plan(plan).state == JobState.FAILED
