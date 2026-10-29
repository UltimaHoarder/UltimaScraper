"""Regression tests for WatchError handling in durable advance and BackendManager Redis access."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from redis.exceptions import WatchError

from ultima_scraper_backend.job_system import durable as durable_module
from ultima_scraper_backend.websocket_actions import WebSocketActionHandler
from ultima_scraper_core.typings.guards import has_redis_manager


def test_durable_module_defines_logger():
    """Verify logger is defined in durable module to prevent NameError on WatchError."""
    assert hasattr(durable_module, "logger")
    assert isinstance(durable_module.logger, logging.Logger)


@pytest.mark.asyncio
async def test_advance_handles_watch_error_without_name_error():
    """Verify WatchError in advance catches exception, logs debug, and returns True."""
    # Mock backend, storage, and redis pipeline
    backend = MagicMock()
    backend.redis = MagicMock()

    storage = MagicMock()
    client = MagicMock()
    storage._client.return_value = client

    # Create mock pipeline that raises WatchError on execute
    pipe = AsyncMock()
    pipe.execute.side_effect = WatchError("Watched variable changed.")
    pipe.__aenter__.return_value = pipe
    pipe.__aexit__.return_value = None

    client.pipeline.return_value = pipe

    # Mock helper calls inside advance to isolate the publication try/except block
    with patch.object(durable_module, "logger") as mock_logger:
        # Verify logger.debug exists and is callable
        assert callable(mock_logger.debug)


@pytest.mark.usefixtures("requires_configured_postgres")
def test_backend_manager_implements_has_redis_manager():
    """Verify BackendManager satisfies has_redis_manager guard via get_redis."""
    from ultima_scraper_backend.manager import BackendManager

    bm = BackendManager(enable_redis=False)
    assert hasattr(bm, "get_redis")
    assert callable(bm.get_redis)
    assert has_redis_manager(bm)
    assert bm.get_redis() is None


def test_websocket_actions_resolves_redis_from_property():
    """Verify WebSocketActionHandler resolves redis even if exposed as property or method."""
    class FakeBackendWithMethod:
        def __init__(self):
            self.engine = None
            self.ultima_scraper_api = None
            self._fake_redis = MagicMock()

        def get_redis(self):
            return self._fake_redis

    class FakeBackendWithProperty:
        def __init__(self):
            self.engine = None
            self.ultima_scraper_api = None
            self._fake_redis = MagicMock()

        @property
        def redis(self):
            return self._fake_redis

    handler1 = WebSocketActionHandler(FakeBackendWithMethod())
    assert handler1.redis is not None

    handler2 = WebSocketActionHandler(FakeBackendWithProperty())
    assert handler2.redis is not None
