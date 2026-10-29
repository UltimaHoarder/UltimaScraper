"""Receipt retention: a short live window, and fences instead of an age guard."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select, text
from test_execution_ledger import ledger, ledger_engine, postgres_engine
from test_ledger_writer_batch_fences import command, owned_batch
from test_writer_receipt_lookup import receipt_row
from ultima_scraper_backend.database import receipt_retention
from ultima_scraper_backend.database.receipt_retention import purge_receipts
from ultima_scraper_backend.database.write_receipts import receipt_batch
from ultima_scraper_backend.job_system.ledger import StaleAttempt
from ultima_scraper_db_archive.global_db import DatabaseWriteReceiptModel

__all__ = ["ledger", "ledger_engine", "postgres_engine"]


@pytest.mark.parametrize(("stored", "expected"), [(None, 60), (90, 90), (5, 15)])
def test_retention_minutes_reads_the_setting_with_a_floor(monkeypatch, stored, expected):
    from ultima_scraper_backend.job_system import resources

    monkeypatch.setattr(
        resources,
        "_persisted_job_execution_setting",
        lambda name, db_session=None: stored if name == receipt_retention.RETENTION_SETTING else None,
    )
    session = SimpleNamespace(begin_nested=nullcontext)
    assert receipt_retention.retention_minutes(session) == expected


def test_setting_defaults_to_an_hour_and_rejects_less_than_the_result_wait():
    from pydantic import ValidationError
    from ultima_scraper_backend.config import JobExecutionSettings

    assert JobExecutionSettings().receipt_retention_minutes == 60
    with pytest.raises(ValidationError):
        JobExecutionSettings(receipt_retention_minutes=10)


def test_old_unreceipted_upsert_is_admitted(ledger):
    # Upserts are idempotent: an old envelope without a receipt simply runs.
    original = command(owned_batch(ledger, 1)[0])
    old = replace(
        original,
        command_id="old-upsert",
        execution_attempt=None,
        execution_key=None,
        created_at=(datetime.now(UTC) - timedelta(days=30)).isoformat(),
    )
    results = {}
    with ledger.session_factory() as session, receipt_batch(session, [old], results) as pending:
        assert pending == [old]
        results[old.command_id] = {"saved": True}


def test_old_envelope_of_a_finished_run_fails_its_attempt_fence(ledger):
    item = replace(
        command(owned_batch(ledger, 1)[0]),
        created_at=(datetime.now(UTC) - timedelta(days=30)).isoformat(),
    )
    ledger.control("job-test", "cancel")
    with (
        ledger.session_factory() as session,
        pytest.raises(StaleAttempt),
        receipt_batch(session, [item], {}),
    ):
        pytest.fail("a finished run's command reached mutation")


def test_finished_runs_release_receipts_after_the_window_and_live_runs_keep_them(ledger):
    owned_batch(ledger, 1)
    old = datetime.now(UTC) - timedelta(hours=2)
    rows = []
    for key in ("finished", "live"):
        row = receipt_row(key)
        row.update(committed_at=old, run_id="job-test", failed_command_json=None,
                   post_commit_json=None)
        rows.append(row)
    with ledger.session_factory() as session:
        session.execute(insert(DatabaseWriteReceiptModel), rows)
        session.commit()

    # While the run is live, its receipts stay.
    assert purge_receipts(protected_ids=set(), session_factory=ledger.session_factory).deleted == 0

    with ledger.session_factory() as session:
        session.execute(text(
            "UPDATE management.execution_runs SET state='completed', "
            "completed_at=clock_timestamp() - interval '90 minutes' WHERE run_id='job-test'"
        ))
        session.commit()
    result = purge_receipts(protected_ids={"live"}, session_factory=ledger.session_factory)
    assert result.deleted == 1
    with ledger.session_factory() as session:
        assert list(session.scalars(select(DatabaseWriteReceiptModel.command_id))) == ["live"]


def test_recently_finished_runs_keep_receipts_until_the_window_passes(ledger):
    owned_batch(ledger, 1)
    row = receipt_row("fresh")
    row.update(committed_at=datetime.now(UTC) - timedelta(hours=2), run_id="job-test",
               failed_command_json=None, post_commit_json=None)
    with ledger.session_factory() as session:
        session.execute(insert(DatabaseWriteReceiptModel), [row])
        session.execute(text(
            "UPDATE management.execution_runs SET state='completed', "
            "completed_at=clock_timestamp() - interval '5 minutes' WHERE run_id='job-test'"
        ))
        session.commit()
    assert purge_receipts(protected_ids=set(), session_factory=ledger.session_factory).deleted == 0
