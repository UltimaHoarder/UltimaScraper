"""Redis connection-pool backpressure contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ultima_scraper_api.managers.redis.connection import RedisManager


@pytest.mark.asyncio
async def test_redis_manager_uses_blocking_pool_at_connection_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_api.managers.redis.connection as connection_module

    captured: dict[str, Any] = {}

    class FakePool:
        async def aclose(self) -> None:
            return None

    class FakeClient:
        async def ping(self) -> bool:
            return True

        async def aclose(self) -> None:
            return None

    def create_blocking_pool(**kwargs: Any) -> FakePool:
        captured.update(kwargs)
        return FakePool()

    monkeypatch.setattr(
        connection_module,
        "BlockingConnectionPool",
        create_blocking_pool,
    )
    monkeypatch.setattr(
        connection_module.redis,
        "Redis",
        lambda *, connection_pool: (
            captured.update(connection_pool=connection_pool) or FakeClient()
        ),
    )

    manager = RedisManager(
        SimpleNamespace(
            enabled=True,
            host="redis.test",
            port=6379,
            db=0,
            password="secret",
        ),
        max_connections=37,
        pool_wait_timeout=12.5,
    )

    assert await manager.connect() is True
    assert captured["max_connections"] == 37
    assert captured["timeout"] == 12.5
    assert isinstance(captured["connection_pool"], FakePool)


def test_usr_redis_pool_budget_is_fixed_per_process_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.redis.client import RedisManager as USRRedisManager

    config = SimpleNamespace(
        enabled=True,
        host="redis.test",
        port=6379,
        db=0,
        password=None,
    )
    monkeypatch.setenv("ULTIMA_DATABASE_PROCESS_ROLE", "application")
    application = USRRedisManager(config=config)
    monkeypatch.setenv("ULTIMA_DATABASE_PROCESS_ROLE", "worker_reader")
    worker = USRRedisManager(config=config)
    monkeypatch.setenv("ULTIMA_DATABASE_PROCESS_ROLE", "writer")
    writer = USRRedisManager(config=config)

    assert application.pool_config["max_connections"] == 256
    assert worker.pool_config["max_connections"] == 32
    assert writer.pool_config["max_connections"] == 8


def test_usapi_can_share_the_usr_process_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    import ultima_scraper_api.managers.redis.connection as connection_module

    shared = RedisManager.__new__(RedisManager)
    shared._connected = True
    monkeypatch.setattr(connection_module, "_redis_manager", None)

    assert connection_module.attach_redis(shared) is shared
    assert connection_module.get_redis() is shared
    connection_module.detach_redis(shared)
    assert connection_module.get_redis() is None


def test_usr_redis_pool_rejects_unknown_process_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.redis.client import RedisManager as USRRedisManager

    monkeypatch.setenv("ULTIMA_DATABASE_PROCESS_ROLE", "unexpected")
    with pytest.raises(ValueError, match="Unsupported process connection role"):
        USRRedisManager(
            config=SimpleNamespace(
                enabled=True,
                host="redis.test",
                port=6379,
                db=0,
                password=None,
            )
        )


def test_explicit_invalid_usr_redis_pool_setting_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.redis.client import RedisManager as USRRedisManager

    monkeypatch.setenv("ULTIMA_DATABASE_PROCESS_ROLE", "worker_reader")
    monkeypatch.setenv("ULTIMA_REDIS_WORKER_MAX_CONNECTIONS", "not-an-integer")

    with pytest.raises(ValueError, match="positive integer"):
        USRRedisManager(
            config=SimpleNamespace(
                enabled=True,
                host="redis.test",
                port=6379,
                db=0,
                password=None,
            )
        )
