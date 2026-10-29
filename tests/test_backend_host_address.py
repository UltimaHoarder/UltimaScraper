"""Which address a backend reports for the machine it runs on."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from ultima_scraper_backend import cluster


def _redis(addr: str | None) -> SimpleNamespace:
    async def client_info():
        if addr is None:
            raise ConnectionError("no CLIENT INFO")
        return {"addr": addr, "laddr": "192.168.1.20:6379"}

    return SimpleNamespace(client=SimpleNamespace(client_info=client_info))


@pytest.fixture
def machine(monkeypatch: pytest.MonkeyPatch):
    def set_up(*, advertised: str = "", container: bool, own: str | None):
        from ultima_scraper_backend import backend_tls

        monkeypatch.setattr(backend_tls, "advertise_host", lambda: advertised or None)
        monkeypatch.setattr(cluster, "_in_container", lambda: container)
        monkeypatch.setattr(cluster, "_lan_address", lambda: own)

    return set_up


def test_the_deployments_address_wins(machine) -> None:
    machine(advertised="alpha.lan", container=True, own="172.18.0.4")

    assert asyncio.run(cluster.host_address(_redis("192.168.50.120:51234"))) == "alpha.lan"


def test_a_native_backend_knows_its_own_lan_address(machine) -> None:
    machine(container=False, own="192.168.1.20")

    # Even when Redis sees it through Docker's port proxy.
    assert asyncio.run(cluster.host_address(_redis("172.17.0.1:40000"))) == "192.168.1.20"


def test_a_container_reports_the_host_address_redis_on_another_machine_sees(machine) -> None:
    machine(container=True, own="172.18.0.4")

    assert asyncio.run(cluster.host_address(_redis("192.168.50.120:51234"))) == "192.168.50.120"
    assert asyncio.run(cluster.host_address(_redis("[fd00::218]:51234"))) == "fd00::218"


def test_a_container_next_to_its_redis_reports_nothing(machine) -> None:
    machine(container=True, own="172.18.0.4")

    assert asyncio.run(cluster.host_address(_redis("172.18.0.4:51234"))) is None
    assert asyncio.run(cluster.host_address(_redis("127.0.0.1:51234"))) is None
    assert asyncio.run(cluster.host_address(_redis(None))) is None


def test_presence_carries_the_address(machine, monkeypatch: pytest.MonkeyPatch) -> None:
    machine(container=True, own="172.18.0.4")
    monkeypatch.setattr(cluster, "get_cluster_id", lambda: "c-1")
    monkeypatch.setattr(cluster, "public_api_url", lambda: None)
    written: dict = {}

    async def set_(key, value, ex):
        written[key] = value

    redis = _redis("192.168.50.120:51234")
    redis.set = set_
    asyncio.run(cluster.publish_presence(redis, "alpha-9d4b85", 30))

    import json

    entry = json.loads(written[f"{cluster.PRESENCE_KEY_PREFIX}alpha-9d4b85"])
    assert entry["address"] == "192.168.50.120"


def test_the_backends_list_keeps_the_address() -> None:
    from ultima_scraper_backend.api.routes.system import (
        RemoteBackendInfo,
        _merge_presence,
    )

    listed = [
        RemoteBackendInfo(backend_id="alpha-9d4b85", hostname="alpha-9d4b85", status="online", last_seen="", max_workers=4, version="")
    ]
    _merge_presence(listed, [{"backend_id": "alpha-9d4b85", "address": "192.168.50.120"}])

    assert listed[0].address == "192.168.50.120"


def test_a_backend_reports_the_release_its_image_is(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes.system import RemoteBackendInfo, _merge_presence

    monkeypatch.setenv("USR_IMAGE_VERSION", "0.1.0-edge.0123abcd4567")
    assert cluster.runtime_version() == "0.1.0-edge.0123abcd4567"
    # A local build has no image version: the package's.
    monkeypatch.setenv("USR_IMAGE_VERSION", "dev")
    assert cluster.runtime_version() not in ("", "dev")

    # The routing registry's version gives way to the one presence reports.
    listed = [
        RemoteBackendInfo(backend_id="alpha-8be427", hostname="h", status="online", last_seen="", max_workers=4, version="1.0.0")
    ]
    _merge_presence(listed, [{"backend_id": "alpha-8be427", "version": "0.1.0-edge.0123abcd4567"}])
    assert listed[0].version == "0.1.0-edge.0123abcd4567"
