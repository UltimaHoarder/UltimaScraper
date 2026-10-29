"""Concurrent durable plan publication regression tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import WatchError

from ultima_scraper_backend.job_system import durable as durable_module


@pytest.mark.asyncio
@pytest.mark.parametrize("lose_owner", [False, True])
async def test_ensure_plan_rechecks_window_and_owner_after_watch_conflict(lose_owner):
    from ultima_scraper_backend.job_system.materializer import _MPSMaterializationLockLost

    storage = MagicMock()
    client = storage._client.return_value
    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)
    pipe.watch = AsyncMock()
    pipe.get = AsyncMock(side_effect=["owner", "replacement" if lose_owner else "owner"])
    # A worker opens a legacy window between WATCH and EXEC.
    pipe.hmget = AsyncMock(side_effect=[(b"0", b"0", b"0", None), (b"0", b"5", b"5", None)])
    pipe.execute = AsyncMock(side_effect=[WatchError("Watched variable changed."), []])
    client.pipeline.return_value = pipe
    plan = {
        "job_id": "recovery-test", "status": "preparing",
        "job_config": {"metadata": {}}, "selection": {"task_manifest_id": "manifest"},
        "cursor": 0, "total": 10, "site": "OnlyFans",
    }
    policy = MagicMock(scope="ordinary", budget_key="budget", waiting_key="waiting", waiting_set_key="waiting-set")
    with patch.object(durable_module, "ensure_job", new_callable=AsyncMock), patch.object(durable_module, "window_policy", return_value=policy):
        if lose_owner:
            with pytest.raises(_MPSMaterializationLockLost):
                await durable_module.ensure_plan(storage, plan, lock_key="lock", lock_owner="owner")
            assert pipe.execute.await_count == 1
            assert pipe.hmget.await_count == 1
        else:
            assert await durable_module.ensure_plan(storage, plan, lock_key="lock", lock_owner="owner")
            assert pipe.execute.await_count == 2
            assert pipe.hmget.await_count == 2
            assert pipe.hset.call_count == 1  # Retry preserves the newly active window.
            budget_writes = [call.args[2] for call in pipe.hsetnx.call_args_list if call.args[1] == "window_budget_key"]
            assert budget_writes == ["budget", durable_module.mps_state.LEGACY_MPS_BUDGET_KEY]
        assert pipe.watch.await_count == 2
        assert pipe.get.await_count == 2
