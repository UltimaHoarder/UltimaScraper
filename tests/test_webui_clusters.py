from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from ultima_webui_server import Settings, create_app

TOKEN = "cluster-token"
ORIGIN = {"origin": "http://testserver"}


def _backend(identity: dict | None, live: list[dict] | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/system/identity")
    def get_identity(request: Request):
        if request.headers.get("x-usr-admin-token") != TOKEN:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        if identity is None:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return identity

    @app.get("/api/v1/system/backends")
    def get_backends():
        return {"success": True, "backends": live or []}

    @app.api_route("/api/v1/{path:path}", methods=["GET", "POST"])
    def anything(path: str, request: Request):
        # Says which backend answered.
        return {"served_by": identity["backend_id"] if identity else None, "path": path, "method": request.method}

    return app


class _Server:
    def __init__(self, app: FastAPI) -> None:
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


def _identity(backend_id: str, cluster_id: str | None, instance: str = "start-1") -> dict:
    return {
        "backend_id": backend_id,
        "instance": instance,
        "cluster_id": cluster_id,
        "api_url": None,
        "version": "1.0",
        "api_version": 1,
        "capabilities": ["clusters"],
    }


LIVE = [
    {"backend_id": "nas-1", "hostname": "nas", "status": "online", "last_seen": "now", "cluster_id": "c1"},
    {"backend_id": "nas-2", "hostname": "nas2", "status": "online", "last_seen": "now", "cluster_id": "c1",
     "api_url": "http://nas2.example.test:21121"},
    {"backend_id": "other", "hostname": "x", "status": "online", "last_seen": "now", "cluster_id": "c2"},
    {"backend_id": "legacy", "hostname": "y", "status": "online", "last_seen": "now"},
]


@pytest.fixture
def fleet() -> Iterator[dict[str, _Server]]:
    servers = {
        "nas": _Server(_backend(_identity("nas-1", "c1"), LIVE)),
        # A second deployment that reused nas-1's id on the same database.
        "copy": _Server(_backend(_identity("nas-1", "c1", instance="start-2"), LIVE)),
        "lone": _Server(_backend(_identity("lone", "c9"))),
        "old": _Server(_backend(None)),
    }
    yield servers
    for server in servers.values():
        server.stop()


def _client(tmp_path: Path) -> TestClient:
    client = TestClient(
        create_app(Settings(data_dir=tmp_path / "data", static_dir=tmp_path)), client=("127.0.0.1", 50000)
    )
    assert client.post("/webui/api/v1/session/claim", json={"password": "a-long-password"}, headers=ORIGIN).status_code == 204
    return client


def _add(client: TestClient, name: str, url: str) -> str:
    response = client.post("/webui/api/v1/connections", json={"name": name, "base_url": url, "token": TOKEN}, headers=ORIGIN)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_connections_group_into_clusters_with_suggestions_and_conflicts(
    tmp_path: Path, fleet: dict[str, _Server]
) -> None:
    client = _client(tmp_path)
    assert TestClient(client.app).get("/webui/api/v1/clusters").status_code == 401
    for name, server in fleet.items():
        _add(client, name, server.url)
    _add(client, "gone", "http://127.0.0.1:9")

    result = client.get("/webui/api/v1/clusters").json()

    clusters = {cluster["cluster_id"]: cluster for cluster in result["clusters"]}
    assert set(clusters) == {"c1", "c9"}
    assert clusters["c1"]["connection_ids"] == ["nas", "copy"]
    # Only members of this cluster that the WebUI does not know yet.
    assert [(s["backend_id"], s["api_url"]) for s in clusters["c1"]["suggestions"]] == [
        ("nas-2", "http://nas2.example.test:21121")
    ]
    assert clusters["c1"]["conflicting_backend_ids"] == ["nas-1"]
    assert clusters["c9"] == {"cluster_id": "c9", "name": "Cluster c9", "connection_ids": ["lone"], "suggestions": [], "conflicting_backend_ids": []}
    members = {member["connection_id"]: member for member in result["members"]}
    assert members["old"]["reachable"] is True and members["old"]["identity"] is None
    assert members["gone"]["reachable"] is False and members["gone"]["identity"] is None


def test_an_unreachable_member_keeps_its_cluster(tmp_path: Path, fleet: dict[str, _Server]) -> None:
    client = _client(tmp_path)
    _add(client, "nas", fleet["nas"].url)
    client.get("/webui/api/v1/clusters")

    fleet["nas"].stop()
    result = client.get("/webui/api/v1/clusters").json()

    [member] = result["members"]
    assert member["reachable"] is False and member["identity"]["cluster_id"] == "c1"
    # Suggestions and conflicts need a live answer, so there are none now.
    assert result["clusters"] == [
        {"cluster_id": "c1", "name": "Cluster c1", "connection_ids": ["nas"], "suggestions": [], "conflicting_backend_ids": []}
    ]

    # Removing the connection forgets what it reported.
    client.delete("/webui/api/v1/connections/nas", headers=ORIGIN)
    assert client.get("/webui/api/v1/clusters").json() == {"members": [], "clusters": [], "main_cluster_id": None}


def test_reads_of_shared_data_fail_over_to_a_cluster_member(tmp_path: Path, fleet: dict[str, _Server]) -> None:
    client = _client(tmp_path)
    _add(client, "nas", fleet["nas"].url)
    _add(client, "copy", fleet["copy"].url)
    _add(client, "lone", fleet["lone"].url)
    client.get("/webui/api/v1/clusters")  # learns who is in which cluster
    assert client.get("/b/nas/api/v1/jobs").headers.get("x-usr-served-by") is None

    fleet["nas"].stop()

    jobs = client.get("/b/nas/api/v1/jobs?page=2")
    assert jobs.status_code == 200 and jobs.headers["x-usr-served-by"] == "copy"
    assert jobs.json() == {"served_by": "nas-1", "path": "jobs", "method": "GET"}  # the other member answered
    # Per-node data and writes go only to the backend asked for.
    assert client.get("/b/nas/api/v1/system/backend").status_code == 502
    assert client.get("/b/nas/api/v1/settings").status_code == 502
    assert client.post("/b/nas/api/v1/jobs", json={}, headers=ORIGIN).status_code == 502
    # A backend outside any cluster has nobody to fall back on.
    fleet["lone"].stop()
    assert client.get("/b/lone/api/v1/jobs").status_code == 502
