"""HTTP previews do not consume supervised task concurrency slots."""

import asyncio
from types import SimpleNamespace

import pytest

from ultima_scraper_backend.plugin_system import execution
from ultima_scraper_backend.plugin_system.services import PluginServices


def test_preview_burst_does_not_acquire_slots(monkeypatch):
    definition = SimpleNamespace(handler=SimpleNamespace(kind="http", timeout_seconds=30))
    record = SimpleNamespace(
        manifest=SimpleNamespace(operational_policy=SimpleNamespace(task_concurrency=1))
    )
    monkeypatch.setattr(execution, "validate_task", lambda *args: (record, definition))

    async def run():
        entered = 0
        all_entered = asyncio.Event()

        async def invoke(service, plugin_id, task_type, payload):
            nonlocal entered
            entered += 1
            if entered == 20:
                all_entered.set()
            await all_entered.wait()
            return payload

        monkeypatch.setattr(execution, "invoke_task", invoke)
        # No repository: preview invocations must not acquire database leases.
        results = await asyncio.wait_for(
            asyncio.gather(*[
                PluginServices().invoke_operation("ultima-ai", "predict", {"id": i})
                for i in range(20)
            ]),
            timeout=2,
        )
        assert results == [{"id": i} for i in range(20)]

    asyncio.run(run())


@pytest.mark.parametrize("kind,timeout", [("process", 30), ("http", 61)])
def test_preview_still_requires_short_http_operation(monkeypatch, kind, timeout):
    definition = SimpleNamespace(handler=SimpleNamespace(kind=kind, timeout_seconds=timeout))
    monkeypatch.setattr(execution, "validate_task", lambda *args: (None, definition))
    with pytest.raises(ValueError, match="ledger jobs"):
        asyncio.run(PluginServices().invoke_operation("ultima-ai", "predict", {}))
