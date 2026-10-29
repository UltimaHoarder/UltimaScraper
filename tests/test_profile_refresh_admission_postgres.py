"""Concurrent API processes must join one committed profile-refresh job."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4
import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from ultima_scraper_db_archive import global_db
from ultima_scraper_backend.database.task_admission import prepare_task_plan
from ultima_scraper_backend.job_system.models import Job, Task, TaskType
from ultima_scraper_backend.job_system.payloads import APICommandTaskPayload
from test_execution_ledger import ledger_engine
from test_mps_manifest import postgres_engine


@pytest.mark.parametrize('identity_suffix', ['', ':lease-recovery-v1'])
def test_concurrent_profile_admission_joins_existing_job_and_preserves_state(ledger_engine, monkeypatch, identity_suffix):
    @contextmanager
    def sessions():
        with Session(ledger_engine) as session:
            yield session
    monkeypatch.setattr(global_db, 'global_session', sessions)
    from hashlib import sha256
    key = f'profile:onlyfans:7:{uuid4().hex}{identity_suffix}'
    job_id = 'api-' + sha256(key.encode()).hexdigest()[:32]
    task = Task(user_id='api-profile', task_type=TaskType.API_COMMAND, site_name='onlyfans',
                job_id=job_id, task_id='task-'+job_id,
                payload=APICommandTaskPayload(command='refresh_profile', args={'user_id': 7}),
                max_attempts=3)
    job = Job(job_id=job_id, name='API command: refresh_profile', created_by='api', tasks=[task],
              metadata={'admission_idempotent': True, 'source': 'api'})
    config = job.to_config(include_task_ids=False).to_dict()
    def submit():
        return prepare_task_plan(job_id=job_id, job_type=job.name, site='onlyfans',
                                 job_config=config, args_payload={}, tasks=[task])
    with ThreadPoolExecutor(max_workers=8) as workers:
        responses = list(workers.map(lambda _: submit(), range(24)))
    assert all(response == responses[0] for response in responses)
    with ledger_engine.begin() as conn:
        assert conn.scalar(text('SELECT count(*) FROM management.jobs WHERE job_id=:job'), {'job':job_id}) == 1
        assert conn.scalar(text('SELECT count(*) FROM management.execution_runs WHERE run_id=:job'), {'job':job_id}) == 1
        assert conn.scalar(text("SELECT count(*) FROM management.mps_task_definitions WHERE task_json::jsonb->>'job_id'=:job"), {'job':job_id}) == 1
        saved = json.loads(conn.scalar(text('SELECT job_config_json FROM management.mps_plans WHERE job_id=:job'), {'job':job_id}))
        saved['metadata']['fixture_committed_result'] = True
        conn.execute(text('UPDATE management.mps_plans SET job_config_json=:config WHERE job_id=:job'), {'job':job_id, 'config':json.dumps(saved)})
    assert submit()['metadata']['fixture_committed_result'] is True
    config['metadata']['admission_idempotent'] = False
    with pytest.raises(ValueError, match='already exists'):
        submit()
