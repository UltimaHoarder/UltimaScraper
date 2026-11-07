"""Joining a cluster with a one-time invite, over HTTPS pinned to the invite's fingerprint."""

from __future__ import annotations

import asyncio
import socket
import ssl
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient
from ultima_scraper_core.tls import ensure_self_signed, fingerprint
from ultima_webui_server import Settings, create_app
from ultima_webui_server.installer.runner import register_worker_inventory
from ultima_webui_server.pinning import PinMismatch, pinned_certificate, pinned_context
from ultima_webui_server.tickets import (
    create_cluster_join_invite,
    is_cluster_join_invite,
    parse_cluster_invite,
    parse_cluster_join_invite,
)
from ultima_webui_server.tunnels import TunnelManager

ORIGIN = {"origin": "http://testserver"}
CODE = "usri_once"
CLIENT_TOKEN = "usrc_client"
ADMIN_TOKEN = "admin-token"


class _Cluster:
    """A backend serving the cluster routes over HTTPS, recording what it was asked."""

    def __init__(self, tls_dir: Path) -> None:
        files = ensure_self_signed(tls_dir, common_name="UltimaScraper backend")
        self.fingerprint = fingerprint(files.cert_file)
        self.redeemed: list[dict] = []
        self.heartbeats: list[dict] = []
        self.revoked: list[str] = []
        self.inventory: list[dict] = []
        self.codes = {CODE}
        self.name = "Home"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.server = uvicorn.Server(
            uvicorn.Config(
                self._app(),
                host="127.0.0.1",
                port=self.port,
                log_level="warning",
                ssl_certfile=str(files.cert_file),
                ssl_keyfile=str(files.key_file),
            )
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)

    @property
    def url(self) -> str:
        return f"https://127.0.0.1:{self.port}"

    def info(self) -> dict:
        return {
            "cluster_id": "c-1",
            "name": self.name,
            "members": [
                {"backend_id": "devbox-1", "name": "devbox", "api_url": self.url, "tls_fingerprint": self.fingerprint},
                # A worker host without an API for other machines.
                {"backend_id": "alpha-1", "name": "alpha", "api_url": None, "tls_fingerprint": None},
            ],
        }

    def _app(self) -> FastAPI:
        app = FastAPI()

        def allowed(request: Request) -> bool:
            return request.headers.get("x-usr-admin-token") in (CLIENT_TOKEN, ADMIN_TOKEN)

        @app.post("/api/v1/cluster/join")
        async def join(request: Request):
            body = await request.json()
            if body.get("code") not in self.codes:
                return JSONResponse({"detail": "The invite is unknown, already used, or expired."}, status_code=403)
            self.codes.discard(body["code"])
            self.redeemed.append(body)
            return {**self.info(), "client_id": "client-1", "token": CLIENT_TOKEN}

        @app.get("/api/v1/cluster")
        def cluster(request: Request):
            if not allowed(request):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return self.info()

        @app.post("/api/v1/cluster/invites", status_code=201)
        def invite(request: Request):
            if not allowed(request):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            self.codes.add("usri_fresh")
            return {"code": "usri_fresh", "expires_at": "2026-10-27T10:00:00Z"}

        @app.post("/api/v1/cluster/clients/heartbeat", status_code=204)
        async def heartbeat(request: Request):
            if not allowed(request):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            self.heartbeats.append(await request.json())

        @app.get("/api/v1/cluster/clients")
        def clients(request: Request):
            if not allowed(request):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return [
                {
                    "id": "client-1",
                    "name": "WebUI on devbox",
                    "kind": "webui",
                    "created_at": "2026-10-26T10:00:00Z",
                    "is_self": True,
                    "revoked_at": "2026-10-26T11:00:00Z" if "client-1" in self.revoked else None,
                }
            ]

        @app.delete("/api/v1/cluster/clients/{client_id}", status_code=204)
        def revoke(client_id: str, request: Request):
            if not allowed(request):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            self.revoked.append(client_id)

        @app.get("/api/v1/system/identity")
        def identity(request: Request):
            if not allowed(request):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return {"backend_id": "devbox-1", "instance": "i", "cluster_id": "c-1", "api_url": self.url}

        @app.get("/api/v1/jobs")
        def jobs(request: Request):
            return {"authorised": allowed(request)}

        @app.get("/api/v1/system/cluster-stores")
        def cluster_stores(request: Request):
            if not allowed(request):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return {
                "available": True,
                "cluster_id": "c-1",
                "database": {"host": "192.0.2.98", "port": 5432, "name": "ultima_archive"},
                "redis": {"host": "192.0.2.98", "port": 6379},
                "settings_id": 1,
            }

        @app.put("/api/v1/settings/db/backends")
        async def inventory(request: Request):
            if not allowed(request):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            self.inventory.append(await request.json())
            return {}

        return app

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture
def cluster(tmp_path: Path) -> Iterator[_Cluster]:
    running = _Cluster(tmp_path / "backend-tls")
    yield running
    running.stop()


def _webui(tmp_path: Path) -> TestClient:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    client = TestClient(
        create_app(Settings(data_dir=tmp_path / "data", static_dir=static)), client=("127.0.0.1", 50000)
    )
    claimed = client.post("/webui/api/v1/session/claim", json={"password": "a-long-password"}, headers=ORIGIN)
    assert claimed.status_code == 204, claimed.text
    return client


def _invite(cluster: _Cluster, fingerprint_: str | None = None) -> str:
    return create_cluster_join_invite(
        code=CODE, entry_url=cluster.url, fingerprint=fingerprint_ or cluster.fingerprint
    )


# ---- The invite ------------------------------------------------------------


def test_a_one_time_invite_names_the_code_the_member_and_its_fingerprint() -> None:
    invite = create_cluster_join_invite(code="usri_abc", entry_url="https://[fd00::5]:8443", fingerprint="AB:CD")

    assert invite == "usr://cluster/usri_abc@[fd00::5]:8443#AB:CD"
    assert is_cluster_join_invite(invite)
    assert parse_cluster_join_invite(invite) == {
        "code": "usri_abc",
        "entry_url": "https://[fd00::5]:8443",
        "fingerprint": "AB:CD",
    }
    with pytest.raises(ValueError, match="version 2"):
        parse_cluster_invite(invite)
    with pytest.raises(ValueError, match="https"):
        create_cluster_join_invite(code="usri_abc", entry_url="http://10.0.0.5:21121", fingerprint="AB")
    with pytest.raises(ValueError, match="code, an address and a fingerprint"):
        parse_cluster_join_invite("usr://cluster/usri_abc@10.0.0.5:8443")


# ---- Pinning ---------------------------------------------------------------


def test_the_pinned_certificate_is_the_only_one_accepted(cluster: _Cluster, tmp_path: Path) -> None:
    pem = asyncio.run(pinned_certificate(cluster.url, cluster.fingerprint.replace(":", "").lower()))
    with pytest.raises(PinMismatch):
        asyncio.run(pinned_certificate(cluster.url, "00" * 32))

    assert httpx.get(f"{cluster.url}/api/v1/jobs", verify=pinned_context(pem)).json() == {"authorised": False}
    other = ensure_self_signed(tmp_path / "other").cert_file.read_text()
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
        httpx.get(f"{cluster.url}/api/v1/jobs", verify=pinned_context(other))
    with pytest.raises(httpx.ConnectError):
        httpx.get(f"{cluster.url}/api/v1/jobs", verify=ssl.create_default_context())


# ---- Joining ---------------------------------------------------------------


def test_the_preview_checks_the_certificate_without_using_the_code(cluster: _Cluster, tmp_path: Path) -> None:
    client = _webui(tmp_path)

    good = client.post("/webui/api/v1/clusters/preview-invite", json={"ticket": _invite(cluster)}, headers=ORIGIN)
    bad = client.post(
        "/webui/api/v1/clusters/preview-invite", json={"ticket": _invite(cluster, "00" * 32)}, headers=ORIGIN
    )

    assert good.json()["version"] == 2 and good.json()["verified"] is True
    assert good.json()["entry_url"] == cluster.url
    assert bad.json()["verified"] is False and "not the expected" in bad.json()["error"]
    assert cluster.redeemed == []


def test_joining_pins_each_member_and_reaches_it_with_the_client_token(cluster: _Cluster, tmp_path: Path) -> None:
    client = _webui(tmp_path)

    joined = client.post("/webui/api/v1/clusters/join", json={"ticket": _invite(cluster)}, headers=ORIGIN)

    assert joined.status_code == 200, joined.text
    body = joined.json()
    assert body["cluster_id"] == "c-1" and body["name"] == "Home"
    assert body["created"] == ["devbox"] and body["skipped"] == ["alpha"]
    assert cluster.redeemed[0]["kind"] == "webui" and cluster.redeemed[0]["name"].startswith("WebUI on ")
    store = client.app.state.store
    credential = store.get_cluster_credential("c-1")
    assert credential is not None and credential.client_id == "client-1" and credential.entry_url == cluster.url
    assert CLIENT_TOKEN not in credential.token  # encrypted
    connection = client.app.state.connections.get("devbox")
    assert connection.tls_certificate and connection.token() == CLIENT_TOKEN
    # Through the proxy: pinned TLS, with the client token.
    assert client.get("/b/devbox/api/v1/jobs").json() == {"authorised": True}
    # The code worked once.
    again = client.post("/webui/api/v1/clusters/join", json={"ticket": _invite(cluster)}, headers=ORIGIN)
    assert again.status_code == 400 and "already used" in again.json()["detail"]


def test_local_services_reach_a_joined_member_through_its_pinned_certificate(
    cluster: _Cluster, tmp_path: Path
) -> None:
    client = _webui(tmp_path)
    joined = client.post("/webui/api/v1/clusters/join", json={"ticket": _invite(cluster)}, headers=ORIGIN)
    assert joined.status_code == 200, joined.text
    state = client.app.state

    stores = asyncio.run(state.installer.get_cluster_stores(connection_id="devbox"))
    listed = asyncio.run(
        register_worker_inventory(
            state.connections,
            TunnelManager(),
            connection_id="devbox",
            node_name="nas",
            backend_id="192-0-2-84-1",
            address="192.0.2.84",
            settings_id=1,
        )
    )

    assert stores["available"] is True, stores
    assert stores["database"]["host"] == "192.0.2.98"
    assert listed and cluster.inventory[0]["local_ip"] == "192.0.2.84"


def test_a_member_presenting_another_certificate_is_not_joined(cluster: _Cluster, tmp_path: Path) -> None:
    client = _webui(tmp_path)

    refused = client.post(
        "/webui/api/v1/clusters/join", json={"ticket": _invite(cluster, "00" * 32)}, headers=ORIGIN
    )

    assert refused.status_code == 400 and "not the expected" in refused.json()["detail"]
    assert cluster.redeemed == [] and client.app.state.store.cluster_credentials() == []


def test_a_joined_webui_invites_others_checks_in_and_takes_the_clusters_name(
    cluster: _Cluster, tmp_path: Path
) -> None:
    from ultima_webui_server.cluster_membership import ClusterMembership

    client = _webui(tmp_path)
    client.post("/webui/api/v1/clusters/join", json={"ticket": _invite(cluster)}, headers=ORIGIN)

    invite = client.get("/webui/api/v1/clusters/c-1/invite").json()
    assert invite["version"] == 2 and invite["warning"] is None
    assert parse_cluster_join_invite(invite["invite"]) == {
        "code": "usri_fresh",
        "entry_url": cluster.url,
        "fingerprint": cluster.fingerprint,
    }
    assert [item["name"] for item in invite["excluded"]] == ["alpha"]

    cluster.name = "Lab"
    membership: ClusterMembership = client.app.state.membership
    asyncio.run(membership.sync("c-1"))
    assert cluster.heartbeats and cluster.heartbeats[-1]["name"].startswith("WebUI on ")
    assert client.get("/webui/api/v1/clusters").json()["clusters"][0]["name"] == "Lab"

    clients = client.get("/webui/api/v1/clusters/c-1/clients").json()
    assert clients[0]["is_self"] is True
    assert client.delete("/webui/api/v1/clusters/c-1/clients/client-1", headers=ORIGIN).status_code == 204
    assert cluster.revoked == ["client-1"] and client.app.state.store.get_cluster_credential("c-1") is None


def test_a_webui_with_an_admin_token_lists_itself_in_the_cluster(cluster: _Cluster, tmp_path: Path) -> None:
    client = _webui(tmp_path)
    connections = client.app.state.connections
    pem = asyncio.run(pinned_certificate(cluster.url, cluster.fingerprint))
    connection = connections.create_pinned(name="devbox", base_url=cluster.url, token=ADMIN_TOKEN, certificate=pem)
    client.app.state.store.save_identity(connection.id, '{"backend_id": "devbox-1", "cluster_id": "c-1"}')

    asyncio.run(client.app.state.membership.sync("c-1"))
    asyncio.run(client.app.state.membership.sync("c-1"))

    credential = client.app.state.store.get_cluster_credential("c-1")
    assert credential is not None and credential.client_id == "client-1"
    # Enrolled once, and checked in with its own token.
    assert len(cluster.redeemed) == 1 and cluster.redeemed[0]["name"].startswith("WebUI on ")
    assert len(cluster.heartbeats) == 2
    # Its admin connection is left as it was.
    assert connections.get(connection.id).token() == ADMIN_TOKEN


class _PlainFront:
    """The same cluster, reached over plain HTTP with the admin token (as alpha reaches it)."""

    def __init__(self, cluster: _Cluster) -> None:
        app = FastAPI()

        def admin(request: Request) -> bool:
            return request.headers.get("x-usr-admin-token") == ADMIN_TOKEN

        @app.get("/api/v1/cluster")
        def info(request: Request):
            return cluster.info() if admin(request) else JSONResponse({"detail": "Unauthorized"}, status_code=401)

        @app.post("/api/v1/cluster/invites", status_code=201)
        def invite(request: Request):
            if not admin(request):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            cluster.codes.add("usri_plain")
            return {"code": "usri_plain", "expires_at": "2026-10-28T10:00:00Z"}

        @app.post("/api/v1/cluster/join")
        def join():
            return JSONResponse({"detail": "Join over HTTPS: the reply carries a credential."}, status_code=400)

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def test_a_webui_on_plain_http_lists_itself_through_the_clusters_https_member(
    cluster: _Cluster, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ultima_webui_server import cluster_membership
    from ultima_webui_server.connections import ConnectionIn

    # As across a LAN: the plain link is not safe for a token, only HTTPS is.
    monkeypatch.setattr(cluster_membership, "_token_safe", lambda url: url.startswith("https://"))
    monkeypatch.setattr(cluster_membership, "_trusted_channel", lambda connection: connection.base_url.startswith("https://"))
    front = _PlainFront(cluster)
    try:
        client = _webui(tmp_path)
        connection = client.app.state.connections.create(
            ConnectionIn(name="devbox", base_url=front.url, token=ADMIN_TOKEN, tls_verify=True)
        )
        client.app.state.store.save_identity(connection.id, '{"backend_id": "devbox-1", "cluster_id": "c-1"}')
        membership = client.app.state.membership

        asyncio.run(membership.sync("c-1"))

        credential = client.app.state.store.get_cluster_credential("c-1")
        assert credential is not None and credential.entry_url == cluster.url
        assert credential.entry_certificate and "BEGIN CERTIFICATE" in credential.entry_certificate
        # Redeemed at the HTTPS member, which is where it checks in, pinned.
        assert cluster.redeemed and cluster.redeemed[0]["code"] == "usri_plain"
        assert cluster.heartbeats and cluster.heartbeats[-1]["name"].startswith("WebUI on ")
        # Its own connection stays as it was.
        assert client.app.state.connections.get(connection.id).token() == ADMIN_TOKEN
        # Its clients list asks the cluster with its own token: it is listed as itself.
        assert client.get("/webui/api/v1/clusters/c-1/clients").json()[0]["is_self"] is True
    finally:
        front.stop()


def test_a_webui_that_could_not_enrol_tries_again_later(cluster: _Cluster, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ultima_webui_server import cluster_membership

    client = _webui(tmp_path)
    membership = client.app.state.membership
    attempts: list[str] = []

    async def no_https(cluster_id: str):
        attempts.append(cluster_id)
        return None

    monkeypatch.setattr(membership, "_enrol_over_https", no_https)
    asyncio.run(membership._enrol("c-9"))
    asyncio.run(membership._enrol("c-9"))
    assert attempts == ["c-9"]
    monkeypatch.setattr(cluster_membership, "_ENROL_RETRY_SECONDS", 0.0)
    asyncio.run(membership._enrol("c-9"))
    assert attempts == ["c-9", "c-9"]
