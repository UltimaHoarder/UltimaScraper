"""Disposable benchmark schema must satisfy the real plugin startup checks.

Opt in with USR_TEST_WITH_POSTGRES=1; all databases belong to the test cluster.
"""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from test_mps_manifest import postgres_engine
from ultima_scraper_backend.plugin_system.postgres_repository import (
    PluginSchemaNotReady,
    PostgresPluginRepository,
)
from ultima_scraper_backend.plugin_system.repository import SCHEMA_VERSION

__all__ = ["postgres_engine"]


def test_fresh_benchmark_database_starts_plugin_repository(
    postgres_engine, monkeypatch
):
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("USR_BENCH_REPO", str(repo))
    monkeypatch.syspath_prepend(str(repo / "scripts/performance/arm64"))
    spec = importlib.util.spec_from_file_location(
        "arm64_benchmark_schema", repo / "scripts/performance/arm64/benchmark.py"
    )
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)

    database = "benchmark_" + uuid4().hex
    with postgres_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(text(f"CREATE DATABASE {database}"))
    engine = create_engine(postgres_engine.url.set(database=database))
    sessions = sessionmaker(engine)
    try:
        # Reproduce the supervisor's failure before invoking the benchmark setup.
        with pytest.raises(PluginSchemaNotReady, match="schema is missing"):
            PostgresPluginRepository(sessions)
        with engine.begin() as connection:
            benchmark.initialize_fixture_schema(connection)

        from ultima_scraper_db_archive.plugin_models import PLUGIN_TABLES

        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names(schema="management"))
            assert {table.name for table in PLUGIN_TABLES} <= tables
            assert {"jobs", "job_tasks", "database_write_receipts"} <= tables
            for site_name in ("onlyfans", "fansly"):
                assert "users" in inspect(connection).get_table_names(schema=site_name)
            version = connection.scalar(
                text(
                    "SELECT value FROM management.plugin_repository_meta "
                    "WHERE key='schema_version'"
                )
            )
            assert version == str(SCHEMA_VERSION)

        repository = PostgresPluginRepository(sessions)
        assert repository.list_enabled_plugins() == set()
        repository.set_plugin_enabled("benchmark-fixture", True)
        # Separate runtime instances must see the prepared shared authority.
        assert PostgresPluginRepository(sessions).list_enabled_plugins() == {
            "benchmark-fixture"
        }
    finally:
        engine.dispose()
        with postgres_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.execute(text(f"DROP DATABASE {database}"))
