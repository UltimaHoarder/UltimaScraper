"""Configuration imports stay small while HTTP policy keeps its exact behavior."""

from test_worker_memory_imports import isolated


def test_worker_configuration_does_not_load_the_api_framework(tmp_path):
    isolated(
        "from ultima_scraper_backend.workers.worker_pool import Worker\n"
        "from ultima_scraper_backend.config import UltimaScraperCollectionConfig\n"
        "config = UltimaScraperCollectionConfig()\n"
        "assert 'fastapi' not in sys.modules\n"
        "assert 'ultima_scraper_backend.api.app' not in sys.modules\n",
        tmp_path,
    )


def test_deferred_http_validation_preserves_exception_and_request_types(tmp_path):
    isolated(
        "from ultima_scraper_backend import security\n"
        "assert 'fastapi' not in sys.modules\n"
        "try:\n"
        "    security.validate_outbound_url('file:///fixture')\n"
        "except Exception as exc:\n"
        "    from fastapi import HTTPException, Request\n"
        "    assert type(exc) is HTTPException\n"
        "    assert exc.status_code == 400\n"
        "    assert security.Request is Request\n"
        "else:\n"
        "    raise AssertionError('Unsafe URL was accepted')\n"
        "from typing import get_type_hints\n"
        "assert get_type_hints(security.ensure_http_admin_auth)['request'] is Request\n"
        "try:\n"
        "    security.ensure_ws_admin_auth(origin='https://untrusted.invalid', token=None, allowed_origins=['https://allowed.invalid'])\n"
        "except HTTPException as exc:\n"
        "    assert exc.status_code == 403\n"
        "else:\n"
        "    raise AssertionError('Untrusted WebSocket origin was accepted')\n",
        tmp_path,
    )
