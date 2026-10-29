"""Existing migration directory preserves global ownership and legacy fallback."""

import importlib.util
import json
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, select, text
from test_execution_ledger import ledger as ledger_fixture
from test_execution_ledger import ledger_engine as ledger_engine_fixture
from test_execution_ledger import postgres_engine as postgres_engine_fixture
from test_mps_archive_set_inserts import completed_range
from ultima_scraper_backend.database.job_partitions import partition_name
from ultima_scraper_db_archive.execution_models import JobTaskIdentityModel
from ultima_scraper_db_archive.global_db import CentralTaskModel

ledger = ledger_fixture
__all__ = ['ledger', 'ledger_engine', 'postgres_engine']


@pytest.fixture
def postgres_engine():
    # Each migration/disabled-trigger fixture needs a fresh schema. TRUNCATE
    # does not remove inherited guards or clear their identity directories.
    yield from postgres_engine_fixture.__wrapped__()


@pytest.fixture
def ledger_engine(postgres_engine):
    return ledger_engine_fixture.__wrapped__(postgres_engine)


def repartition(ledger_engine):
    path = (Path(__file__).resolve().parents[2]
            / 'UltimaDatabases/UltimaScraperDBArchive/ultima_scraper_db_archive'
            / 'migrations/alembic/versions/c92ea6407b31_partition_all_job_history.py')
    spec = importlib.util.spec_from_file_location('archive_directory_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with ledger_engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


def test_unpartitioned_archive_uses_original_global_history(ledger):
    from ultima_scraper_backend.database.job_partitions import task_identity_model

    completed_range(ledger, 3)
    with ledger.session_factory() as session:
        assert task_identity_model(session) is CentralTaskModel
    assert ledger.archive_tick() == 'archive-pages'


def test_directory_backfill_and_archive_preserve_exact_global_identities(ledger, ledger_engine):
    from ultima_scraper_backend.database.job_partitions import task_identity_model

    completed_range(ledger, 3)
    assert ledger.archive_tick() == 'archive-pages'
    repartition(ledger_engine)
    statements = []
    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)
    event.listen(ledger_engine, 'before_cursor_execute', capture)
    try:
        with ledger.session_factory() as session:
            model = task_identity_model(session)
            assert model is JobTaskIdentityModel
            assert task_identity_model(session) is model
            directory = session.execute(select(model.task_id, model.job_id)).all()
            history = session.execute(select(CentralTaskModel.task_id, CentralTaskModel.job_id)).all()
            assert sorted(directory) == sorted(history) and len(directory) == 3
    finally:
        event.remove(ledger_engine, 'before_cursor_execute', capture)
    assert sum('WITH RECURSIVE history_relations' in statement for statement in statements) == 1
    assert not any('pg_partition_tree' in statement for statement in statements)


def test_partitioned_archive_rejects_other_directory_owner_and_rolls_back(ledger, ledger_engine):
    from ultima_scraper_backend.job_system.models import Job, Task
    from ultima_scraper_backend.job_system.storage import _task_to_central_row

    job = completed_range(ledger, 1)
    other = Job.create(name='Other owner', created_by='test', tasks=[])
    ledger.manifests.create(job_id=other.job_id, site='onlyfans', job_config=other.to_dict(),
                            selection={'start_id': 2, 'end_id': 2, 'max_profiles': None},
                            proxy_pool=[], site_session_factory=ledger.session_factory)
    with ledger.session_factory() as session:
        item = Task.from_dict(json.loads(session.scalar(text(
            'SELECT payload_json FROM management.execution_work_payloads WHERE run_id=:job'
        ), {'job': job})))
        session.execute(CentralTaskModel.__table__.insert(), _task_to_central_row(item, other.job_id))
        session.commit()
    repartition(ledger_engine)
    with pytest.raises(ValueError, match='Archived task belongs to another job'):
        ledger.archive_tick()
    with ledger.session_factory() as session:
        assert session.scalar(text('SELECT cursor FROM management.mps_plans WHERE job_id=:job'), {'job': job}) == 0
        assert session.scalar(text('SELECT count(*) FROM management.execution_work WHERE run_id=:job'), {'job': job}) == 1
        assert session.scalar(text('SELECT count(*) FROM management.job_tasks WHERE job_id=:job'), {'job': job}) == 0
        assert session.scalar(text('SELECT job_id FROM management.job_task_identities WHERE task_id=:task'), {'task': item.task_id}) == other.job_id


@pytest.mark.parametrize('leaf_only', [False, True])
def test_disabled_identity_guard_falls_back_to_global_history(ledger, ledger_engine, leaf_only):
    from ultima_scraper_backend.database.job_partitions import task_identity_model

    job = completed_range(ledger, 3)
    assert ledger.archive_tick() == job
    repartition(ledger_engine)
    table = partition_name(job, 'job_tasks') if leaf_only else 'job_tasks'
    with ledger.session_factory() as session:
        session.execute(text(f'ALTER TABLE management.{table} DISABLE TRIGGER history_identity_guard'))
        assert task_identity_model(session) is CentralTaskModel
        assert session.scalar(select(CentralTaskModel.task_id).limit(1)) is not None


def test_missing_directory_uses_original_global_history(ledger, ledger_engine):
    from ultima_scraper_backend.database.job_partitions import task_identity_model

    job = completed_range(ledger, 3)
    assert ledger.archive_tick() == job
    repartition(ledger_engine)
    with ledger.session_factory() as session:
        # Disposable fault fixture only; production helper is read-only.
        session.execute(text('ALTER TABLE management.job_task_identities RENAME TO fault_missing_directory'))
        assert task_identity_model(session) is CentralTaskModel
        assert session.scalar(select(CentralTaskModel.task_id).limit(1)) is not None


def optimized_guard_migration():
    path = (Path(__file__).resolve().parents[2]
            / 'UltimaDatabases/UltimaScraperDBArchive/ultima_scraper_db_archive'
            / 'migrations/alembic/versions/a43f7c9d2e61_avoid_redundant_history_identity_reads.py')
    spec = importlib.util.spec_from_file_location('optimized_identity_guard', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_guarded_archive_does_not_pre_read_new_task_identities(ledger, ledger_engine):
    job = completed_range(ledger, 1001)
    repartition(ledger_engine)
    with ledger_engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        optimized_guard_migration().upgrade()
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(ledger_engine, 'before_cursor_execute', capture)
    try:
        assert ledger.archive_tick() == job
    finally:
        event.remove(ledger_engine, 'before_cursor_execute', capture)
    assert not any(statement.startswith('SELECT') and 'FROM management.job_task_identities' in statement for statement in statements)
    with ledger.session_factory() as session:
        assert session.scalar(text('SELECT count(*) FROM management.job_task_identities')) == 1001
        assert session.scalar(text('SELECT count(*) FROM management.job_tasks')) == 1001
        assert session.scalar(text('SELECT count(*) FROM management.execution_work_payloads')) == 0


@pytest.mark.parametrize('optimized', [False, True])
def test_concurrent_archive_owner_claim_is_rejected_atomically(ledger, ledger_engine, optimized):
    from ultima_scraper_backend.job_system.models import Job, Task
    from ultima_scraper_backend.job_system.storage import _task_to_central_row

    job = completed_range(ledger, 1)
    other = Job.create(name='Racing owner', created_by='test', tasks=[])
    ledger.manifests.create(job_id=other.job_id, site='onlyfans', job_config=other.to_dict(),
                            selection={'start_id': 2, 'end_id': 2, 'max_profiles': None},
                            proxy_pool=[], site_session_factory=ledger.session_factory)
    with ledger.session_factory() as session:
        item = Task.from_dict(json.loads(session.scalar(text(
            'SELECT payload_json FROM management.execution_work_payloads WHERE run_id=:job'
        ), {'job': job})))
    repartition(ledger_engine)
    if optimized:
        with ledger_engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            optimized_guard_migration().upgrade()
    raced = False

    def race(conn, cursor, statement, parameters, context, many):
        nonlocal raced
        if not raced and statement.startswith('INSERT INTO management.job_tasks'):
            raced = True
            with ledger_engine.begin() as contender:
                contender.execute(CentralTaskModel.__table__.insert(), _task_to_central_row(item, other.job_id))

    event.listen(ledger_engine, 'before_cursor_execute', race)
    try:
        with pytest.raises(ValueError, match='Archived task belongs to another job'):
            ledger.archive_tick()
    finally:
        event.remove(ledger_engine, 'before_cursor_execute', race)
    assert raced
    with ledger.session_factory() as session:
        assert session.scalar(text('SELECT cursor FROM management.mps_plans WHERE job_id=:job'), {'job': job}) == 0
        assert session.scalar(text('SELECT count(*) FROM management.execution_work WHERE run_id=:job'), {'job': job}) == 1
        assert session.scalar(text('SELECT job_id FROM management.job_task_identities WHERE task_id=:task'), {'task': item.task_id}) == other.job_id


def test_optimized_attempt_guard_retains_ownership_and_downgrade(ledger, ledger_engine):
    from datetime import UTC, datetime

    from sqlalchemy.exc import IntegrityError
    from ultima_scraper_db_archive.execution_models import ExecutionAttemptModel

    job = completed_range(ledger, 2)
    repartition(ledger_engine)
    migration = optimized_guard_migration()
    with ledger_engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    row = {'run_id': job, 'task_id': 'extra-task', 'number': 2, 'token': 'new-attempt-token',
           'owner': 'worker', 'state': 'running', 'started_at': datetime.now(UTC), 'timings_json': '{}'}
    with ledger_engine.begin() as connection:
        connection.execute(ExecutionAttemptModel.__table__.insert(), row)
        connection.execute(text("UPDATE management.execution_attempts SET state='completed' WHERE run_id=:job AND token=:token"), {'job': job, 'token': row['token']})
    with pytest.raises(IntegrityError, match='Attempt token already belongs to another attempt'), ledger_engine.begin() as connection:
        connection.execute(ExecutionAttemptModel.__table__.insert(), {**row, 'task_id': 'different-task'})
    with ledger_engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()
    with pytest.raises(IntegrityError, match='Attempt token already belongs to another attempt'), ledger_engine.begin() as connection:
        connection.execute(ExecutionAttemptModel.__table__.insert(), {**row, 'task_id': 'another-task'})
