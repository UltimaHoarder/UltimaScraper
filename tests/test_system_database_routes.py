"""Tests for database overview and maintenance routes on the system page."""

from __future__ import annotations

from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, text

from ultima_scraper_backend.api.routes import system as system_module
from ultima_scraper_backend.api.routes.system import (
    DatabaseAnalyzeRequest,
    DatabaseReindexRequest,
    DatabaseVacuumRequest,
)


@pytest.fixture
def memory_db_engine(tmp_path):
    db_file = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)"))
        conn.execute(text("INSERT INTO users VALUES (1, 'alice'), (2, 'bob')"))
        conn.commit()
    return engine


@pytest.mark.asyncio
async def test_get_database_overview_returns_databases(memory_db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = SimpleNamespace(instance_id="backend-a")
    config = SimpleNamespace(
        settings=SimpleNamespace(worker_pool=SimpleNamespace(sites=["fansly"]))
    )

    class DummyManager:
        def __init__(self):
            self.engine = memory_db_engine
            self.connection_string = "sqlite:///:memory:"

    class DummyMultiDB:
        def get_all_sites(self):
            return ["fansly"]
        def get_or_create_manager(self, site):
            return DummyManager()
        def get_manager(self, site):
            return DummyManager()

    monkeypatch.setattr(system_module, "MultiSiteDatabaseManager", DummyMultiDB)
    monkeypatch.setattr(system_module, "_get_maintenance_engine", lambda site=None: memory_db_engine)

    response = await system_module.get_database_overview(backend, config)

    assert response.success is True
    assert response.backend_id == "backend-a"
    assert response.total_databases >= 2
    assert any(d.site == "management" for d in response.databases)
    db = next(d for d in response.databases if d.site == "fansly")
    assert db.site == "fansly"
    assert db.status == "healthy"
    assert len(db.tables) == 1
    assert db.tables[0].table_name == "users"
    assert db.tables[0].live_tuples == 2
    # SQLite counts are exact COUNT(*) results, not planner estimates.
    assert db.row_counts_estimated is False


@pytest.mark.asyncio
async def test_vacuum_database_table(memory_db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    config = SimpleNamespace(
        settings=SimpleNamespace(worker_pool=SimpleNamespace(sites=["fansly"]))
    )
    monkeypatch.setattr(system_module, "_get_maintenance_engine", lambda site=None: memory_db_engine)

    request = DatabaseVacuumRequest(
        site="fansly",
        table_name="users",
        full=False,
        analyze=True,
    )

    response = await system_module.vacuum_database(request, config)

    assert response.success is True
    assert response.site == "fansly"
    assert response.table_name == "users"
    assert "VACUUM" in response.mode
    assert response.duration_seconds >= 0


@pytest.mark.asyncio
async def test_analyze_database_table(memory_db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    config = SimpleNamespace(
        settings=SimpleNamespace(worker_pool=SimpleNamespace(sites=["fansly"]))
    )
    monkeypatch.setattr(system_module, "_get_maintenance_engine", lambda site=None: memory_db_engine)

    request = DatabaseAnalyzeRequest(
        site="fansly",
        table_name="users",
    )

    response = await system_module.analyze_database(request, config)

    assert response.success is True
    assert response.site == "fansly"
    assert response.table_name == "users"
    assert response.duration_seconds >= 0


@pytest.mark.asyncio
async def test_reindex_database_table(memory_db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    config = SimpleNamespace(
        settings=SimpleNamespace(worker_pool=SimpleNamespace(sites=["fansly"]))
    )
    monkeypatch.setattr(system_module, "_get_maintenance_engine", lambda site=None: memory_db_engine)

    request = DatabaseReindexRequest(
        site="fansly",
        table_name="users",
        concurrently=False,
    )

    response = await system_module.reindex_database(request, config)

    assert response.success is True
    assert response.site == "fansly"
    assert response.duration_seconds >= 0


@pytest.mark.asyncio
async def test_vacuum_no_engine_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    config = SimpleNamespace(
        settings=SimpleNamespace(worker_pool=SimpleNamespace(sites=["nonexistent"]))
    )
    monkeypatch.setattr(system_module, "_get_maintenance_engine", lambda site=None: None)

    class EmptyMultiDB:
        def get_all_sites(self):
            return []
        def get_or_create_manager(self, site):
            raise ValueError("No connection")

    monkeypatch.setattr(system_module, "MultiSiteDatabaseManager", EmptyMultiDB)

    request = DatabaseVacuumRequest(site="nonexistent")
    response = await system_module.vacuum_database(request, config)

    assert response.success is False
    assert "Vacuum failed" in response.message or "No connected database engine" in response.message


@pytest.mark.asyncio
async def test_get_database_overview_includes_active_operations(memory_db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = SimpleNamespace(instance_id="backend-a")
    config = SimpleNamespace(
        settings=SimpleNamespace(worker_pool=SimpleNamespace(sites=["fansly"]))
    )

    class DummyManager:
        def __init__(self):
            self.engine = memory_db_engine
            self.connection_string = "sqlite:///:memory:"

    class DummyMultiDB:
        def get_all_sites(self):
            return ["fansly"]
        def get_or_create_manager(self, site):
            return DummyManager()
        def get_manager(self, site):
            return DummyManager()

    monkeypatch.setattr(system_module, "MultiSiteDatabaseManager", DummyMultiDB)
    monkeypatch.setattr(system_module, "_get_maintenance_engine", lambda site=None: memory_db_engine)

    # Register an active database operation to simulate a running maintenance task
    op_id = system_module._register_database_op("vacuum", "fansly", "users", tables_total=1)
    system_module._update_database_op(op_id, current_table="users", tables_completed=0, phase="scanning heap", progress_percent=45.0)

    try:
        response = await system_module.get_database_overview(backend, config)
        assert len(response.active_operations) >= 1
        active_op = next(o for o in response.active_operations if o.id == op_id)
        assert active_op.operation_type == "vacuum"
        assert active_op.site == "fansly"
        assert active_op.current_table == "users"
        assert active_op.progress_percent == 45.0
        assert active_op.status == "running"
    finally:
        system_module._finish_database_op(op_id, success=True, message="done")


@pytest.mark.asyncio
async def test_cancel_database_operation() -> None:
    op_id = system_module._register_database_op("vacuum", "management", None, tables_total=10)
    assert not system_module._is_database_op_cancelled(op_id)

    cancel_req = system_module.DatabaseCancelRequest(site="management")
    cancel_res = await system_module.cancel_database_operation(cancel_req)

    assert cancel_res.success is True
    assert cancel_res.cancelled_count >= 1
    assert system_module._is_database_op_cancelled(op_id)

    system_module._finish_database_op(op_id, success=False, message="cancelled")
