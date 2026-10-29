"""Run controls must not starve behind a busy run's overlapping shared fences."""
from __future__ import annotations

import threading
import time

import pytest
from test_execution_ledger import ledger, ledger_engine, submit, task  # noqa: F401
from test_mps_manifest import postgres_engine  # noqa: F401

from ultima_scraper_backend.job_system import run_turnstile


def _share_lock_storm(ledger, stop: threading.Event, holders: int = 4, hold: float = 0.08):
    """Keep the run row share-locked by overlapping transactions, as busy writers do."""

    def hold_forever(offset: float):
        time.sleep(offset)
        while not stop.is_set():
            with ledger.session_factory() as session:
                ledger._locked_run(session, "job-test", shared=True)
                time.sleep(hold)
                session.commit()

    threads = [
        threading.Thread(target=hold_forever, args=(hold * index / holders,), daemon=True)
        for index in range(holders)
    ]
    for thread in threads:
        thread.start()
    time.sleep(hold * 2)  # every holder is cycling before the control starts
    return threads


def _pause_in_background(ledger):
    finished = threading.Event()
    errors: list[BaseException] = []

    def pause():
        try:
            ledger.control("job-test", "pause")
        except BaseException as exc:  # noqa: BLE001 - surfaced by the test
            errors.append(exc)
        finally:
            finished.set()

    threading.Thread(target=pause, daemon=True).start()
    return finished, errors


@pytest.mark.parametrize("turnstile", [False, True])
def test_pause_gets_through_a_storm_of_shared_run_locks(ledger, monkeypatch, turnstile):
    if turnstile:
        monkeypatch.setenv(run_turnstile.TURNSTILE_ENV, "1")
    else:
        monkeypatch.delenv(run_turnstile.TURNSTILE_ENV, raising=False)
    submit(ledger, [task("task-a")])
    ledger.tick()
    stop = threading.Event()
    threads = _share_lock_storm(ledger, stop)
    try:
        finished, errors = _pause_in_background(ledger)
        if turnstile:
            # The control queues ahead of new shared lockers and gets in once
            # the current holders finish.
            assert finished.wait(3), "pause starved behind shared run locks"
        else:
            # Without the turnstile, joining share lockers keep it waiting.
            assert not finished.wait(1.5)
    finally:
        stop.set()
        for thread in threads:
            thread.join(5)
    assert finished.wait(5)
    assert not errors
    assert ledger.job("job-test")["state"] == "paused"


def test_skip_locked_sites_yield_while_a_control_waits(ledger, monkeypatch):
    monkeypatch.setenv(run_turnstile.TURNSTILE_ENV, "1")
    submit(ledger, [task("task-a")])
    with ledger.session_factory() as holder, ledger.session_factory() as control:
        # A shared holder keeps the control waiting on the exclusive turnstile.
        run_turnstile.lock_shared(holder, ["job-test"])
        waiting = threading.Thread(
            target=lambda: (run_turnstile.lock_exclusive(control, "job-test"), control.commit()),
            daemon=True,
        )
        waiting.start()
        time.sleep(0.3)
        assert waiting.is_alive()
        with ledger.session_factory() as planner:
            from sqlalchemy import select

            allowed = planner.execute(select(run_turnstile.try_shared("job-test"))).scalar_one()
            planner.rollback()
        # A SKIP LOCKED site passes over the run instead of joining the holders.
        assert allowed is False
        holder.commit()
        waiting.join(5)
        assert not waiting.is_alive()


def test_turnstile_is_off_by_default(monkeypatch):
    monkeypatch.delenv(run_turnstile.TURNSTILE_ENV, raising=False)
    assert not run_turnstile.enabled()
    calls = []
    session = type("S", (), {"execute": lambda self, *a, **k: calls.append(a)})()
    run_turnstile.lock_shared(session, ["job-a"])
    run_turnstile.lock_exclusive(session, "job-a")
    assert calls == []
