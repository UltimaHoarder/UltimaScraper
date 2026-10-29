"""Public producer compatibility and pool-local auth reload routing."""

import asyncio
import json
import threading
import time
from collections import Counter
from types import SimpleNamespace

import pytest
from test_database_write_queue import redis_manager
from ultima_scraper_backend.workers import worker_pool

from ultima_scraper_backend import usapi_initializer

__all__ = ["redis_manager"]


def make_pool(monkeypatch, redis_url="redis://unused", backend_id="shared"):
    config = SimpleNamespace(settings=SimpleNamespace(
        redis=SimpleNamespace(enabled=True, host="fixture"),
        worker_pool=SimpleNamespace(sites=["onlyfans"], max_claimed_jobs=5),
        get_backend_id=lambda: backend_id,
    ))
    monkeypatch.setattr(worker_pool.UltimaScraperCollectionConfig,
                        "load_or_create_default_config", lambda: config)
    return worker_pool.WorkerPool(3, redis_url, backend_id)


def wait_until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "Listener failed to make progress"
        time.sleep(0.005)


def test_new_worker_channel_follows_relay_readiness_and_pool_identity(monkeypatch):
    first, second = make_pool(monkeypatch), make_pool(monkeypatch)
    assert first._auth_reload_channel != second._auth_reload_channel
    assert first._worker_reload_events_channel() == worker_pool.HOOKS_CHANNEL
    first._runtime_listener_ready_event.set()
    assert first._worker_reload_events_channel() == first._auth_reload_channel
    spawned = []

    class Process:
        pid = 123

        def __init__(self, **kwargs):
            spawned.append(kwargs)

        def start(self):
            pass

    first._process_context = SimpleNamespace(Process=Process)
    first._spawn_worker(1)
    assert spawned[-1]["args"][-1] == first._auth_reload_channel
    first._runtime_listener_ready_event.clear()
    first._spawn_worker(2)
    assert spawned[-1]["args"][-1] == worker_pool.HOOKS_CHANNEL


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [None, "private-fixture"])
async def test_worker_listener_keeps_standalone_default_and_escaped_reload(channel):
    subscribed, found = [], []

    class PubSub:
        async def subscribe(self, name):
            subscribed.append(name)

        async def listen(self):
            for payload in [
                '[]', 'malformed', '{"event":"task_completed"}',
                '{"event":"reload_user_data","site":"unsupported","account_id":42}',
                '{"ev\\u0065nt":"reload_user_d\\u0061ta","site":"OnlyFans","account_id":"42"}',
            ]:
                yield {"type": "message", "data": payload}

    worker = worker_pool.Worker.__new__(worker_pool.Worker)
    worker.worker_id = "standalone"
    worker.redis = SimpleNamespace(client=SimpleNamespace(pubsub=PubSub))
    worker.supported_sites = ["onlyfans"]
    worker.apis = {"onlyfans": SimpleNamespace(find_auth=lambda account: found.append(account))}
    if channel is not None:
        worker.reload_events_channel = channel
    await worker._listen_for_reload_events()
    assert subscribed == [channel or worker_pool.HOOKS_CHANNEL]
    assert found == [42]


@pytest.mark.parametrize("reconnect", [False, True])
def test_relay_filters_hooks_preserves_raw_reload_and_keeps_config_routing(monkeypatch, reconnect):
    pool = make_pool(monkeypatch)
    escaped = '{"ev\\u0065nt":"reload_user_d\\u0061ta","site":"OnlyFans","account_id":42}'
    messages = [
        {"channel": worker_pool.HOOKS_CHANNEL, "data": '{"event":"task_completed"}'},
        {"channel": worker_pool.HOOKS_CHANNEL, "data": '[]'},
        {"channel": worker_pool.HOOKS_CHANNEL, "data": 'malformed'},
        {"channel": worker_pool.HOOKS_CHANNEL.encode(), "data": escaped.encode()},
        {"channel": worker_pool.HOOKS_CHANNEL, "data": '{"type":"worker_pool_scale","backend_id":"shared","target_size":100}'},
        {"channel": worker_pool.CONFIG_EVENTS_CHANNEL, "data": '{"type":"worker_pool_scale","backend_id":"shared","target_size":4}'},
    ]
    clients, forwarded = [], []
    consumed = threading.Event()

    class PubSub:
        closed = False

        def __init__(self, fail):
            self.fail = fail
            self.messages = list(messages)

        def subscribe(self, *channels):
            assert channels == (worker_pool.CONFIG_EVENTS_CHANNEL, worker_pool.HOOKS_CHANNEL)

        def get_message(self, timeout):
            if self.fail:
                self.fail = False
                raise ConnectionError("owned reconnect fixture")
            if self.messages:
                return self.messages.pop(0)
            consumed.set()
            pool._runtime_listener_stop_event.wait(0.005)
            return None

        def close(self):
            self.closed = True

    class Client:
        closed = False

        def __init__(self):
            self.sub = PubSub(reconnect and not clients)
            clients.append(self)

        def pubsub(self, **kwargs):
            return self.sub

        def publish(self, channel, payload):
            forwarded.append((channel, payload))

        def close(self):
            self.closed = True

    monkeypatch.setattr(worker_pool.sync_redis.Redis, "from_url", lambda *args, **kwargs: Client())
    try:
        pool._start_runtime_control_listener()
        assert consumed.wait(5)
        assert pool._worker_reload_events_channel() == pool._auth_reload_channel
        assert forwarded == [
            (pool._auth_reload_channel, json.dumps({"event": "ledger_wakeup"})),
            (pool._auth_reload_channel, escaped.encode()),
        ]
        assert pool._drain_runtime_control_events() == [
            {"type": "worker_pool_scale", "backend_id": "shared", "target_size": 4}
        ]
    finally:
        pool._stop_runtime_control_listener()
    assert len(clients) == 1 + int(reconnect)
    assert all(client.closed and client.sub.closed for client in clients)
    assert pool._worker_reload_events_channel() == worker_pool.HOOKS_CHANNEL


@pytest.mark.asyncio
async def test_public_reload_reaches_each_worker_once_across_two_native_pools(redis_manager, monkeypatch):
    client = redis_manager.client
    if type(client).__module__.startswith("fakeredis"):
        pytest.skip("owned native Redis required for threaded pubsub relay")
    path = client.connection_pool.connection_kwargs["path"]
    assert path.startswith("/tmp/usr-writer-test-")
    pools = [make_pool(monkeypatch, f"unix://{path}") for _ in range(2)]
    tasks, subscriptions = [], []
    reloads, decoded = Counter(), Counter()
    original = worker_pool._decode_pubsub_payload

    def decode(raw):
        if threading.current_thread() is threading.main_thread():
            decoded[asyncio.current_task().get_name()] += 1
        return original(raw)

    monkeypatch.setattr(worker_pool, "_decode_pubsub_payload", decode)

    class Initializer:
        def __init__(self, engine):
            pass

        async def initialize_auth(self, **kwargs):
            assert kwargs["account_id"] == 42 and kwargs["skip_api_refresh"] is True
            reloads[kwargs["api_instance"].worker_id] += 1
            return SimpleNamespace(subscriptions=[])

    monkeypatch.setattr(usapi_initializer, "USAPIInitializer", Initializer)

    def pubsub():
        sub = client.pubsub()
        subscriptions.append(sub)
        return sub

    try:
        for index, pool in enumerate(pools):
            pool._start_runtime_control_listener()
            assert pool._runtime_listener_ready_event.is_set()
            for worker_index in range(3):
                identity = f"relay-test-{index}-{worker_index}"
                worker = worker_pool.Worker.__new__(worker_pool.Worker)
                worker.worker_id = identity
                worker.redis = SimpleNamespace(client=SimpleNamespace(pubsub=pubsub))
                worker.reload_events_channel = pool._worker_reload_events_channel()
                worker.supported_sites = ["onlyfans"]
                worker.apis = {"onlyfans": SimpleNamespace(worker_id=identity, find_auth=lambda _: SimpleNamespace())}
                worker.db_managers = {"onlyfans": SimpleNamespace(engine=object(), get_user_auth=lambda _: None)}
                tasks.append(asyncio.create_task(worker._listen_for_reload_events(), name=identity))
        async with asyncio.timeout(5):
            for pool in pools:
                while int((await client.pubsub_numsub(pool._auth_reload_channel))[0][1]) != 3:
                    await asyncio.sleep(0.005)
        async with client.pipeline(transaction=False) as pipeline:
            for _ in range(1000):
                pipeline.publish(worker_pool.HOOKS_CHANNEL, '{"event":"task_completed"}')
            pipeline.publish(worker_pool.HOOKS_CHANNEL, json.dumps({
                "event": "reload_user_data", "site": "OnlyFans", "account_id": 42,
            }))
            await pipeline.execute()
        async with asyncio.timeout(5):
            while sum(reloads.values()) < 6:
                await asyncio.sleep(0.005)
        await asyncio.sleep(0.05)
        assert reloads == Counter({task.get_name(): 1 for task in tasks})
        assert decoded == Counter({task.get_name(): 1 for task in tasks})
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for sub in subscriptions:
            await sub.aclose()
        for pool in pools:
            pool._stop_runtime_control_listener()
