"""Spawned services persist complete, credential-safe error diagnostics."""

import logging
import multiprocessing
import os
import re
import sys
import threading

import pytest
from sqlalchemy.exc import OperationalError
from ultima_scraper_backend.logging_utils import (
    DailyErrorFileHandler,
    RuntimeLogFormatter,
    configure_runtime_logging,
)


@pytest.fixture
def runtime_logs(monkeypatch, tmp_path):
    root = logging.getLogger()
    previous_handlers = root.handlers[:]
    previous_level = root.level
    previous_hooks = (sys.excepthook, threading.excepthook)
    monkeypatch.setenv("USR_LOG_DIR", str(tmp_path))
    yield tmp_path
    for handler in root.handlers[:]:
        if handler not in previous_handlers:
            root.removeHandler(handler)
            handler.close()
    root.handlers[:] = previous_handlers
    root.setLevel(previous_level)
    sys.excepthook, threading.excepthook = previous_hooks


def test_persistent_logs_include_error_stack_and_exclude_credentials(runtime_logs):
    configure_runtime_logging("database-writer", console=False)
    configure_runtime_logging("database-writer", console=False)
    logger = logging.getLogger("test.writer")
    logger.info("informational startup")
    try:
        raise OperationalError(
            "SELECT :credential", {"credential": "private-bind-value"},
            RuntimeError("database failure postgresql://user:private-db-password@db/archive"),
        )
    except OperationalError:
        logger.exception("Writer failed jobs=['job-test']")
    errors = list(runtime_logs.glob("errors-*.log"))
    assert len(errors) == 1
    content = errors[0].read_text()
    assert content.count("Writer failed jobs=['job-test']") == 1
    assert "Traceback" in content and "OperationalError" in content
    assert "service=database-writer" in content and f"pid={os.getpid()}" in content
    assert "private-bind-value" not in content and "private-db-password" not in content
    assert "informational startup" not in content
    assert "informational startup" in next(runtime_logs.glob("database-writer-*.log")).read_text()


def _concurrent_log_child(directory, marker, ready, release):
    os.environ["USR_LOG_DIR"] = directory
    configure_runtime_logging(marker, console=False)
    ready.set()
    assert release.wait(10)
    logging.getLogger("test.concurrent").error(
        "BEGIN:%s\n%s\nEND:%s", marker, marker * 65536, marker,
    )


def test_spawned_errors_share_one_file_without_interleaving(runtime_logs):
    context = multiprocessing.get_context("spawn")
    release = context.Event()
    ready = [context.Event(), context.Event()]
    children = [context.Process(
        target=_concurrent_log_child,
        args=(str(runtime_logs), marker, signal, release),
    ) for marker, signal in zip(("alpha", "bravo"), ready, strict=True)]
    try:
        for child in children:
            child.start()
        for signal in ready:
            assert signal.wait(15)
        release.set()
        for child in children:
            child.join(15)
            assert child.exitcode == 0
        files = list(runtime_logs.glob("errors-*.log"))
        assert len(files) == 1
        records = re.findall(r"BEGIN:(\w+)\n(.*?)\nEND:\1", files[0].read_text(), re.DOTALL)
        assert len(records) == 2
        assert all(body == marker * 65536 for marker, body in records)
    finally:
        release.set()
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(5)


def test_unhandled_exceptions_are_persisted_and_keep_previous_hook(runtime_logs, monkeypatch):
    called = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: called.append(args))
    configure_runtime_logging("launcher", console=False)
    try:
        raise ValueError("unexpected service failure")
    except ValueError:
        arguments = sys.exc_info()
        sys.excepthook(*arguments)
    assert called == [arguments]
    assert "unexpected service failure" in next(runtime_logs.glob("errors-*.log")).read_text()


def test_exception_group_sql_parameters_are_redacted(runtime_logs):
    configure_runtime_logging("api", console=False)
    error = OperationalError("SELECT :secret", {"secret": "private-group-bind"}, RuntimeError("query failed"))
    try:
        raise ExceptionGroup("API failure", [error])
    except ExceptionGroup:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    content = next(runtime_logs.glob("errors-*.log")).read_text()
    assert "ExceptionGroup" in content and "OperationalError" in content
    assert "private-group-bind" not in content


def test_header_and_structured_credentials_are_redacted(runtime_logs):
    configure_runtime_logging("api", console=False)
    logging.getLogger("test.redaction").error(
        'Authorization: Basic private-basic-value\n'
        'Cookie: sess=private-session; auth_id=private-auth\n'
        '{"password": "private-json-password", "cookie": "private-json-cookie", '
        '"apiKey": "private-api-key", "refresh_token": "private-refresh-token"}'
    )
    assert "private-" not in next(runtime_logs.glob("errors-*.log")).read_text()


@pytest.mark.asyncio
async def test_api_http_failures_have_request_context(runtime_logs, monkeypatch):
    from starlette.requests import Request
    from starlette.responses import Response
    from ultima_scraper_backend.api import app as api_app

    configure_runtime_logging("api", console=False)
    monkeypatch.setattr(api_app, "_enforce_security_rate_limits", lambda _request: None)
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/admin/health",
                       "query_string": b"", "headers": [], "server": ("localhost", 21121), "scheme": "http"})

    async def fail(_request):
        raise ValueError("route failure")

    with pytest.raises(ValueError) as caught:
        await api_app.security_http_middleware(request, fail)
    assert any("path=/api/v1/admin/health" in note and "request_id=" in note for note in caught.value.__notes__)

    async def failed_response(_request):
        return Response(status_code=500)

    await api_app.security_http_middleware(request, failed_response)
    content = next(runtime_logs.glob("errors-*.log")).read_text()
    assert "status=500" in content and "path=/api/v1/admin/health" in content and "request_id=" in content


def test_error_file_changes_at_day_boundary(runtime_logs, monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from ultima_scraper_backend import logging_utils

    day = [datetime(2026, 10, 14, tzinfo=UTC)]
    monkeypatch.setattr(logging_utils, "datetime", SimpleNamespace(now=lambda: day[0]))
    handler = DailyErrorFileHandler(runtime_logs)
    handler.setFormatter(RuntimeLogFormatter("%(message)s"))
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "daily error", (), None)
    handler.handle(record)
    day[0] = datetime(2026, 10, 15, tzinfo=UTC)
    handler.handle(record)
    assert (runtime_logs / "errors-2026-10-14.log").read_text() == "daily error\n"
    assert (runtime_logs / "errors-2026-10-15.log").read_text() == "daily error\n"
