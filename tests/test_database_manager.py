"""Tests for the supported database manager factory surface."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from ultima_scraper_backend.database import (
    DatabaseManagerFactory,
    MultiSiteDatabaseManager,
)
from ultima_scraper_backend.database.managers.postgres_manager import (
    PostgreSQLDatabaseManager,
)


@pytest.fixture(autouse=True)
def reset_multi_site_singleton():
    """Keep singleton state from leaking across tests."""
    MultiSiteDatabaseManager._instance = None
    yield
    MultiSiteDatabaseManager._instance = None


def test_factory_rejects_unsupported_backend_name():
    """Factory should reject backend labels outside PostgreSQL."""
    with pytest.raises(
        ValueError,
        match="Unsupported database backend: sqlite. PostgreSQL is required.",
    ):
        DatabaseManagerFactory.create_manager_by_backend(
            "onlyfans",
            backend="sqlite",
        )


def test_multi_site_manager_initializes_empty_registry(tmp_path: Path):
    """The multi-site coordinator should start empty before any site is created."""
    manager = MultiSiteDatabaseManager(base_directory=tmp_path)

    assert manager.base_directory == tmp_path
    assert manager.get_all_sites() == []
    assert manager.get_manager("onlyfans") is None
    assert not manager.has_manager("onlyfans")


def test_postgres_manager_uses_concurrent_api_pool_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.database.managers import postgres_manager

    monkeypatch.setattr(postgres_manager, "runtime_env_value", lambda _key: None)

    manager = PostgreSQLDatabaseManager(
        site="onlyfans",
        connection_string="postgresql://user:pass@localhost/archive",
        auto_create=False,
    )

    assert manager.pool_size == 8
    assert manager.max_overflow == 8
    assert manager.pool_timeout == 5


def test_multi_site_manager_creates_one_pool_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    coordinator = MultiSiteDatabaseManager(base_directory=tmp_path)
    created: list[object] = []

    def create_manager(**_kwargs: object) -> object:
        manager = SimpleNamespace(is_connected=True)
        created.append(manager)
        return manager

    monkeypatch.setattr(
        DatabaseManagerFactory,
        "create_postgres_manager",
        create_manager,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        managers = list(
            executor.map(
                lambda _index: coordinator.get_or_create_manager("onlyfans"),
                range(32),
            )
        )

    assert len(created) == 1
    assert all(manager is created[0] for manager in managers)


def test_multi_site_manager_reconnects_existing_disconnected_manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    coordinator = MultiSiteDatabaseManager(base_directory=tmp_path)
    manager = PostgreSQLDatabaseManager(
        site="fansly",
        connection_string="postgresql://user:pass@localhost/archive",
        auto_create=False,
    )
    reconnects: list[str] = []

    def reconnect() -> None:
        reconnects.append(manager.site)
        manager.engine = SimpleNamespace()
        manager._is_connected = True

    monkeypatch.setattr(manager, "connect", reconnect)
    coordinator.add_manager("fansly", manager)

    returned = coordinator.get_or_create_manager("fansly")

    assert returned is manager
    assert reconnects == ["fansly"]
    assert manager.is_connected is True


def test_pgbouncer_application_releases_clients_after_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.pool import NullPool
    from ultima_scraper_backend.database.managers import postgres_manager

    captured_kwargs: dict[str, object] = {}
    event_listeners: dict[str, object] = {}
    fake_engine = SimpleNamespace()

    def create_engine(_url: str, **kwargs: object) -> object:
        captured_kwargs.update(kwargs)
        return fake_engine

    monkeypatch.setattr(
        postgres_manager,
        "runtime_env_value",
        lambda key: {
            "ULTIMA_USE_PGBOUNCER": "true",
            "ULTIMA_PGBOUNCER_CLIENT_POOL_SIZE": "12",
            "ULTIMA_PGBOUNCER_CLIENT_MAX_OVERFLOW": "0",
        }.get(key),
    )
    monkeypatch.setattr(postgres_manager, "create_engine", create_engine)
    monkeypatch.setattr(
        postgres_manager.event,
        "listen",
        lambda _engine, event_name, callback: event_listeners.update(
            {event_name: callback}
        ),
    )

    manager = PostgreSQLDatabaseManager(
        site="onlyfans",
        connection_string="postgresql://user:pass@localhost/archive",
        auto_create=False,
    )
    manager.connect()

    assert manager.engine is fake_engine
    assert captured_kwargs["poolclass"] is NullPool
    assert "pool_size" not in captured_kwargs
    assert "max_overflow" not in captured_kwargs
    assert captured_kwargs["connect_args"] == {"prepare_threshold": None}
    assert "connect" not in event_listeners
    assert "begin" in event_listeners

    statements: list[str] = []
    fake_connection = SimpleNamespace(
        exec_driver_sql=lambda sql: statements.append(sql)
        or SimpleNamespace(close=lambda: None)
    )
    event_listeners["begin"](fake_connection)  # type: ignore[operator]

    assert statements == [
        (
            "SET LOCAL search_path TO onlyfans, public; "
            "SET LOCAL statement_timeout TO 90000; "
            "SET LOCAL lock_timeout TO 10000; "
            "SET LOCAL idle_in_transaction_session_timeout TO 120000"
        ),
    ]


def test_worker_reader_uses_read_only_null_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.pool import NullPool
    from ultima_scraper_backend.database.managers import postgres_manager

    captured_kwargs: dict[str, object] = {}
    event_listeners: dict[str, object] = {}
    fake_engine = SimpleNamespace()

    monkeypatch.setattr(postgres_manager, "runtime_env_value", lambda _key: None)
    monkeypatch.setattr(
        postgres_manager,
        "create_engine",
        lambda _url, **kwargs: captured_kwargs.update(kwargs) or fake_engine,
    )
    monkeypatch.setattr(
        postgres_manager.event,
        "listen",
        lambda _engine, event_name, callback: event_listeners.update(
            {event_name: callback}
        ),
    )

    manager = PostgreSQLDatabaseManager(
        site="onlyfans",
        connection_string="postgresql://user:pass@localhost/archive",
        read_only=True,
        pool_role="worker_reader",
        pool_size=100,
        max_overflow=100,
    )
    manager.connect()

    assert captured_kwargs["poolclass"] is NullPool
    assert "pool_size" not in captured_kwargs
    assert "max_overflow" not in captured_kwargs
    assert "connect" in event_listeners
    assert "begin" in event_listeners

    statements: list[str] = []
    event_listeners["begin"](  # type: ignore[operator]
        SimpleNamespace(exec_driver_sql=statements.append)
    )
    assert statements == ["SET TRANSACTION READ ONLY"]


@pytest.mark.parametrize("port", [5432, 6432])
def test_writer_pool_is_fixed_and_has_no_overflow(
    monkeypatch: pytest.MonkeyPatch,
    port: int,
) -> None:
    from sqlalchemy.pool import QueuePool
    from ultima_scraper_backend.database.managers import postgres_manager

    captured_kwargs: dict[str, object] = {}
    fake_engine = SimpleNamespace()

    monkeypatch.setattr(
        postgres_manager,
        "runtime_env_value",
        lambda key: ("4" if key == "ULTIMA_DATABASE_WRITER_CONCURRENCY" else None),
    )
    monkeypatch.setattr(
        postgres_manager,
        "create_engine",
        lambda _url, **kwargs: captured_kwargs.update(kwargs) or fake_engine,
    )
    monkeypatch.setattr(postgres_manager.event, "listen", lambda *_args: None)

    manager = PostgreSQLDatabaseManager(
        site="onlyfans",
        connection_string=f"postgresql://user:pass@localhost:{port}/archive",
        pool_role="writer",
        pool_size=100,
        max_overflow=100,
    )
    manager.connect()

    assert manager.pool_size == 4
    assert manager.max_overflow == 0
    assert captured_kwargs["poolclass"] is QueuePool
    assert captured_kwargs["pool_size"] == 4
    assert captured_kwargs["max_overflow"] == 0


@pytest.mark.parametrize("role", ["application", "writer"])
def test_async_pgbouncer_retains_only_writer_clients(monkeypatch, role):
    from sqlalchemy.pool import NullPool
    from ultima_scraper_backend.database.managers import postgres_manager

    captured = {}
    monkeypatch.setattr(postgres_manager, "runtime_env_value", lambda _key: None)
    monkeypatch.setattr(
        postgres_manager, "create_async_engine",
        lambda _url, **kwargs: captured.update(kwargs) or __import__("sqlalchemy").create_engine("sqlite://"),
    )
    manager = PostgreSQLDatabaseManager(
        site="onlyfans",
        connection_string="postgresql://user:pass@localhost:6432/archive",
        pool_role=role,
    )
    manager.create_async_engine()
    if role == "application":
        assert captured["poolclass"] is NullPool
        assert "pool_size" not in captured
    else:
        assert "poolclass" not in captured
        assert captured["pool_size"] == 4
        assert captured["max_overflow"] == 0


def test_idle_api_clients_do_not_accumulate_across_site_managers(monkeypatch):
    from sqlalchemy import create_engine, event, text
    from ultima_scraper_backend.database.managers import postgres_manager

    engines = []
    opened = []
    closed = []
    listen = event.listen

    def local_engine(_url, **kwargs):
        kwargs.pop("connect_args", None)
        kwargs.pop("isolation_level", None)
        engine = create_engine("sqlite://", **kwargs)
        listen(engine, "connect", lambda connection, _record: opened.append(connection))
        listen(engine, "close", lambda connection, _record: closed.append(connection))
        engines.append(engine)
        return engine

    monkeypatch.setattr(postgres_manager, "runtime_env_value", lambda _key: None)
    monkeypatch.setattr(postgres_manager, "create_engine", local_engine)
    # PostgreSQL SET LOCAL statements are tested above; use SQLite only to
    # observe actual SQLAlchemy pool ownership and DBAPI connection closure.
    monkeypatch.setattr(postgres_manager, "event", SimpleNamespace(listen=lambda *_args: None))
    try:
        for site in ("onlyfans", "fansly", "loyalfans"):
            manager = PostgreSQLDatabaseManager(
                site=site,
                connection_string="postgresql://user:pass@localhost:6432/archive",
            )
            manager.connect()
            for _ in range(2):
                with manager.engine.connect() as connection:
                    assert connection.scalar(text("SELECT 1")) == 1
                assert len(closed) == len(opened)
        assert len(opened) == len(closed) == 6
    finally:
        for engine in engines:
            engine.dispose()


def test_worker_reader_role_requires_read_only() -> None:
    with pytest.raises(ValueError, match="must be read-only"):
        PostgreSQLDatabaseManager(
            site="onlyfans",
            connection_string="postgresql://user:pass@localhost/archive",
            read_only=False,
            pool_role="worker_reader",
        )


def test_central_writer_pool_uses_same_fixed_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_db_archive.global_db as global_db
    from sqlalchemy.pool import QueuePool

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        global_db,
        "runtime_env_value",
        lambda key: "writer" if key == "ULTIMA_DATABASE_PROCESS_ROLE" else None,
    )
    monkeypatch.setattr(
        global_db,
        "_global_pool_int",
        lambda key, default: (
            4 if key == "ULTIMA_DATABASE_WRITER_CONCURRENCY" else 100
        ),
    )
    monkeypatch.setattr(
        global_db,
        "create_engine",
        lambda _url, **kwargs: captured.update(kwargs) or __import__("sqlalchemy").create_engine("sqlite://"),
    )
    monkeypatch.setattr(global_db, "set_postgres_engine", lambda _engine: None)

    global_db.set_postgres_url(
        "postgresql://user:password@postgres.test:5432/ultima_archive"
    )

    assert captured["poolclass"] is QueuePool
    assert captured["pool_size"] == 4
    assert captured["max_overflow"] == 0


def test_worker_factory_enforces_reader_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ultima_scraper_backend.database import usr_factory

    captured: dict[str, object] = {}
    sentinel = object()
    monkeypatch.setattr(
        usr_factory,
        "create_usr_database_manager",
        lambda **kwargs: captured.update(kwargs) or sentinel,
    )

    manager = usr_factory.create_worker_database_manager("onlyfans")

    assert manager is sentinel
    assert captured["read_only"] is True
    assert captured["auto_create"] is False
    assert captured["pool_role"] == "worker_reader"


def test_global_database_rejects_unknown_process_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_db_archive.global_db as global_db

    monkeypatch.setattr(
        global_db,
        "runtime_env_value",
        lambda key: ("unexpected" if key == "ULTIMA_DATABASE_PROCESS_ROLE" else None),
    )

    with pytest.raises(ValueError, match="Unsupported database process role"):
        global_db.set_postgres_url(
            "postgresql://user:password@postgres.test:5432/ultima_archive"
        )


def test_database_manager_defaults_to_no_schema_bootstrap() -> None:
    manager = PostgreSQLDatabaseManager(
        site="onlyfans",
        connection_string="postgresql://user:pass@localhost/archive",
    )

    assert manager.auto_create is False
