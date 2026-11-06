from __future__ import annotations

import json
import socket
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ultima_webui_server import Settings, create_app

BACKEND_TOKEN = "backend-secret-token"
ORIGIN = {"origin": "http://testserver"}


def _fake_backend() -> FastAPI:
    backend = FastAPI()

    def _authorised(token: str | None) -> bool:
        return token == BACKEND_TOKEN

    @backend.get("/api/v1/admin/health")
    def health() -> dict:
        return {"status": "ok"}

    @backend.get("/api/v1/system/backend")
    def identity(request: Request) -> Response:
        if not _authorised(request.headers.get("x-usr-admin-token")):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return JSONResponse({"backend_id": "fake"})

    @backend.api_route("/api/v1/echo", methods=["GET", "POST"])
    async def echo(request: Request) -> dict:
        return {
            "method": request.method,
            "headers": dict(request.headers),
            "query": dict(request.query_params),
            "body": (await request.body()).decode(),
        }

    @backend.get("/api/v1/media")
    def media(request: Request) -> Response:
        data = b"0123456789"
        if request.headers.get("range") == "bytes=2-5":
            return Response(data[2:6], status_code=206, headers={"content-range": "bytes 2-5/10"})
        return Response(data, headers={"set-cookie": "backend=1"})

    @backend.websocket("/ws/events")
    async def events(websocket: WebSocket) -> None:
        token = websocket.headers.get("x-usr-admin-token") or websocket.query_params.get("admin_token")
        if not _authorised(token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        await websocket.send_text("hello")
        try:
            while True:
                await websocket.send_text(f"echo:{await websocket.receive_text()}")
        except WebSocketDisconnect:
            return

    return backend


@pytest.fixture(scope="module")
def backend_url() -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(_fake_backend(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def _app(tmp_path: Path, backend_url: str | None = None, *, with_static: bool = True):
    static = tmp_path / "static"
    if with_static:
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_text("<html><head><title>USR</title></head><body></body></html>")
        (static / "assets" / "app-abc123.js").write_text("console.log(1)")
        (static / "favicon.svg").write_text("<svg/>")
    return create_app(
        Settings(
            data_dir=tmp_path / "data",
            static_dir=static,
            default_backend_url=backend_url,
            default_backend_token=BACKEND_TOKEN if backend_url else None,
        )
    )


def _client(app, host: str = "127.0.0.1") -> TestClient:
    return TestClient(app, client=(host, 50000))


def _signed_in(app) -> TestClient:
    client = _client(app)
    response = client.post(
        "/webui/api/v1/session/claim", json={"password": "a-long-password"}, headers=ORIGIN
    )
    assert response.status_code == 204, response.text
    return client


# ---- Sign-in ----------------------------------------------------------


def test_first_visitor_on_the_network_sets_the_password_once(tmp_path: Path) -> None:
    app = _app(tmp_path)
    client = _client(app)

    status = client.get("/webui/api/v1/session").json()
    assert status == {
        "authenticated": False,
        "password_set": False,
        "can_claim": True,
        "default_connection": None,
        "main_connections": [],
    }
    claimed = client.post("/webui/api/v1/session/claim", json={"password": "a-long-password"}, headers=ORIGIN)
    assert claimed.status_code == 204
    cookie = claimed.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/webui/api/v1/session").json()["authenticated"] is True

    again = _client(app).post(
        "/webui/api/v1/session/claim", json={"password": "another-password"}, headers=ORIGIN
    )
    assert again.status_code == 409


def test_remote_first_visitor_needs_the_setup_code(tmp_path: Path) -> None:
    app = _app(tmp_path)
    remote = _client(app, host="8.8.8.8")

    assert remote.get("/webui/api/v1/session").json()["can_claim"] is False
    refused = remote.post("/webui/api/v1/session/claim", json={"password": "a-long-password"}, headers=ORIGIN)
    assert refused.status_code == 403
    accepted = remote.post(
        "/webui/api/v1/session/claim",
        json={"password": "a-long-password", "code": app.state.auth.setup_code},
        headers=ORIGIN,
    )
    assert accepted.status_code == 204


def test_a_visitor_behind_an_untrusted_proxy_needs_the_setup_code(tmp_path: Path) -> None:
    app = _app(tmp_path)
    # A reverse proxy on the same machine: every browser arrives from loopback.
    proxied = _client(app)
    forwarded = {**ORIGIN, "x-forwarded-for": "203.0.113.7"}

    assert proxied.get("/webui/api/v1/session", headers=forwarded).json()["can_claim"] is False
    refused = proxied.post("/webui/api/v1/session/claim", json={"password": "a-long-password"}, headers=forwarded)
    assert refused.status_code == 403
    accepted = proxied.post(
        "/webui/api/v1/session/claim",
        json={"password": "a-long-password", "code": app.state.auth.setup_code},
        headers=forwarded,
    )
    assert accepted.status_code == 204


def test_a_trusted_proxy_reports_the_browser_address(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", static_dir=tmp_path / "static", trusted_proxies="127.0.0.1"))
    local = _client(app, host="10.0.0.9")

    assert local.get("/webui/api/v1/session", headers={"x-forwarded-for": "10.0.0.9"}).json()["can_claim"] is True


def test_login_rejects_wrong_passwords_and_rate_limits(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _signed_in(app)
    client = _client(app, host="10.0.0.9")

    for _ in range(5):
        assert client.post("/webui/api/v1/session/login", json={"password": "wrong"}, headers=ORIGIN).status_code == 401
    assert client.post("/webui/api/v1/session/login", json={"password": "a-long-password"}, headers=ORIGIN).status_code == 429


def test_short_passwords_and_cross_site_claims_are_refused(tmp_path: Path) -> None:
    client = _client(_app(tmp_path))

    assert client.post("/webui/api/v1/session/claim", json={"password": ""}, headers=ORIGIN).status_code == 400
    assert client.post("/webui/api/v1/session/claim", json={"password": "seven77"}, headers=ORIGIN).status_code == 400
    assert client.post("/webui/api/v1/session/claim", json={"password": "twelve-chars"}, headers=ORIGIN).status_code == 204
    cross_site = client.post(
        "/webui/api/v1/session/claim",
        json={"password": "a-long-password"},
        headers={"origin": "https://evil.example"},
    )
    assert cross_site.status_code == 403


def test_change_password_and_revoke_sessions(tmp_path: Path) -> None:
    app = _app(tmp_path)
    client = _signed_in(app)

    # Requires signed-in session
    unsigned_client = _client(app)
    assert unsigned_client.post(
        "/webui/api/v1/session/password",
        json={"current_password": "a-long-password", "new_password": "new-secret-password"},
        headers=ORIGIN,
    ).status_code == 401

    # Wrong current password
    assert client.post(
        "/webui/api/v1/session/password",
        json={"current_password": "wrong-password", "new_password": "new-secret-password"},
        headers=ORIGIN,
    ).status_code == 401

    # Empty new password
    assert client.post(
        "/webui/api/v1/session/password",
        json={"current_password": "a-long-password", "new_password": ""},
        headers=ORIGIN,
    ).status_code == 422  # validation error on min_length

    # A new password shorter than 8 characters
    assert client.post(
        "/webui/api/v1/session/password",
        json={"current_password": "a-long-password", "new_password": "short-p"},
        headers=ORIGIN,
    ).status_code == 400

    elsewhere = _client(app, host="10.0.0.9")
    assert elsewhere.post("/webui/api/v1/session/login", json={"password": "a-long-password"}, headers=ORIGIN).status_code == 204

    # Successful password change
    changed = client.post(
        "/webui/api/v1/session/password",
        json={"current_password": "a-long-password", "new_password": "new-secret-password"},
        headers=ORIGIN,
    )
    assert changed.status_code == 204
    # Every other session is signed out; the caller keeps a fresh one.
    assert elsewhere.get("/webui/api/v1/session").json()["authenticated"] is False
    assert client.get("/webui/api/v1/session").json()["authenticated"] is True

    # Sign in with old password fails
    another_client = _client(app)
    assert another_client.post(
        "/webui/api/v1/session/login",
        json={"password": "a-long-password"},
        headers=ORIGIN,
    ).status_code == 401

    # Sign in with new password succeeds
    login_resp = another_client.post(
        "/webui/api/v1/session/login",
        json={"password": "new-secret-password"},
        headers=ORIGIN,
    )
    assert login_resp.status_code == 204

    # Revoke all sessions keeps current client authenticated with fresh token
    revoked = client.post("/webui/api/v1/session/revoke-all", headers=ORIGIN)
    assert revoked.status_code == 204
    assert client.get("/webui/api/v1/session").json()["authenticated"] is True
    # The other client session was revoked
    assert another_client.get("/webui/api/v1/session").json()["authenticated"] is False


def test_list_and_revoke_clients(tmp_path: Path) -> None:
    app = _app(tmp_path)
    client_a = _signed_in(app)
    unsigned = _client(app)
    assert unsigned.get("/webui/api/v1/clients").status_code == 401

    # Client A checks clients list
    clients_resp = client_a.get("/webui/api/v1/clients")
    assert clients_resp.status_code == 200
    clients = clients_resp.json()
    assert len(clients) == 1
    assert clients[0]["is_current"] is True
    assert clients[0]["device_info"] == "Test Client"
    assert clients[0]["is_local"] is True

    # Client B logs in from another host with custom user agent
    client_b = _client(app, host="192.168.1.100")
    login_b = client_b.post(
        "/webui/api/v1/session/login",
        json={"password": "a-long-password"},
        headers={**ORIGIN, "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"},
    )
    assert login_b.status_code == 204

    # Client A now sees both clients
    clients = client_a.get("/webui/api/v1/clients").json()
    assert len(clients) == 2
    b_entry = next(c for c in clients if not c["is_current"])
    assert b_entry["device_info"] == "Chrome on Linux"
    assert b_entry["ip_address"] == "192.168.1.100"

    # Cross-site delete is refused
    cross_site = client_a.delete(
        f"/webui/api/v1/clients/{b_entry['id']}",
        headers={"origin": "https://evil.example"},
    )
    assert cross_site.status_code == 403

    # Client A revokes Client B
    revoke_resp = client_a.delete(f"/webui/api/v1/clients/{b_entry['id']}", headers=ORIGIN)
    assert revoke_resp.status_code == 204

    # Client B is now signed out
    assert client_b.get("/webui/api/v1/connections").status_code == 401

    # Client A is still signed in
    assert client_a.get("/webui/api/v1/connections").status_code == 200
    assert len(client_a.get("/webui/api/v1/clients").json()) == 1


# ---- Connections ------------------------------------------------------


def test_connections_need_a_session_and_never_return_tokens(tmp_path: Path, backend_url: str) -> None:
    app = _app(tmp_path, backend_url)
    assert _client(app).get("/webui/api/v1/connections").status_code == 401
    client = _signed_in(app)

    created = client.post(
        "/webui/api/v1/connections",
        json={"name": "NAS Backend", "base_url": f"{backend_url}/", "token": BACKEND_TOKEN},
        headers=ORIGIN,
    )
    assert created.status_code == 201, created.text
    listed = client.get("/webui/api/v1/connections").json()

    assert [connection["id"] for connection in listed] == ["default", "nas-backend"]
    assert listed[1]["base_url"] == backend_url and listed[1]["has_token"] is True
    assert BACKEND_TOKEN not in client.get("/webui/api/v1/connections").text
    stored = sqlite3.connect(tmp_path / "data" / "webui.db").execute("SELECT token FROM connections").fetchone()[0]
    assert stored.startswith("v1:") and BACKEND_TOKEN not in stored
    # The deployment's default connection cannot be changed here.
    assert client.delete("/webui/api/v1/connections/default", headers=ORIGIN).status_code == 409
    assert client.delete("/webui/api/v1/connections/nas-backend", headers=ORIGIN).status_code == 204


def test_connection_test_checks_reachability_and_the_token(tmp_path: Path, backend_url: str) -> None:
    client = _signed_in(_app(tmp_path))
    good = client.post(
        "/webui/api/v1/connections", json={"name": "good", "base_url": backend_url, "token": BACKEND_TOKEN}, headers=ORIGIN
    ).json()["id"]
    bad = client.post(
        "/webui/api/v1/connections", json={"name": "bad", "base_url": backend_url, "token": "wrong"}, headers=ORIGIN
    ).json()["id"]
    gone = client.post(
        "/webui/api/v1/connections", json={"name": "gone", "base_url": "http://127.0.0.1:9"}, headers=ORIGIN
    ).json()["id"]

    assert client.post(f"/webui/api/v1/connections/{good}/test", headers=ORIGIN).json()["authenticated"] is True
    refused = client.post(f"/webui/api/v1/connections/{bad}/test", headers=ORIGIN).json()
    assert refused["reachable"] is True and refused["authenticated"] is False
    assert client.post(f"/webui/api/v1/connections/{gone}/test", headers=ORIGIN).json()["reachable"] is False


def test_only_the_deployments_own_backend_starts_with_trusted_plugins(tmp_path: Path, backend_url: str) -> None:
    client = _signed_in(_app(tmp_path, backend_url))
    client.post("/webui/api/v1/connections", json={"name": "nas", "base_url": backend_url}, headers=ORIGIN)

    trust = {c["id"]: c["trust_plugins"] for c in client.get("/webui/api/v1/connections").json()}
    assert trust == {"default": True, "nas": False}

    url = "/webui/api/v1/connections/{}/plugin-trust"
    assert client.put(url.format("nas"), json={"trusted": True}, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.put(url.format("nas"), json={"trusted": True}, headers=ORIGIN).json()["trust_plugins"] is True
    # The deployment's connection cannot be edited, but its trust can be withdrawn.
    assert client.put(url.format("default"), json={"trusted": False}, headers=ORIGIN).json()["trust_plugins"] is False
    assert client.put(url.format("missing"), json={"trusted": True}, headers=ORIGIN).status_code == 404

    # A new connection that reuses a removed one's id starts untrusted again.
    client.delete("/webui/api/v1/connections/nas", headers=ORIGIN)
    client.post("/webui/api/v1/connections", json={"name": "nas", "base_url": backend_url}, headers=ORIGIN)
    assert {c["id"]: c["trust_plugins"] for c in client.get("/webui/api/v1/connections").json()}["nas"] is False


# ---- Proxy ------------------------------------------------------------


def test_backend_proxy_injects_the_token_and_strips_browser_credentials(tmp_path: Path, backend_url: str) -> None:
    client = _signed_in(_app(tmp_path, backend_url))

    echoed = client.post(
        "/b/default/api/v1/echo?admin_token=browser-token&page=2",
        content="payload",
        headers={**ORIGIN, "x-usr-admin-token": "browser-token", "x-forwarded-for": "6.6.6.6"},
    ).json()

    assert echoed["method"] == "POST" and echoed["body"] == "payload"
    assert echoed["headers"]["x-usr-admin-token"] == BACKEND_TOKEN
    assert "cookie" not in echoed["headers"]
    assert echoed["query"] == {"page": "2"}
    # The backend trusts only the last hop: the address this server saw.
    assert echoed["headers"]["x-forwarded-for"] == "6.6.6.6, 127.0.0.1"


def test_backend_proxy_needs_a_session(tmp_path: Path, backend_url: str) -> None:
    client = _client(_app(tmp_path, backend_url))

    assert client.get("/b/default/api/v1/echo").status_code == 401


def test_cross_site_writes_with_the_session_are_refused(tmp_path: Path, backend_url: str) -> None:
    client = _signed_in(_app(tmp_path, backend_url))

    response = client.post("/b/default/api/v1/echo", content="x", headers={"origin": "https://evil.example"})

    assert response.status_code == 403


def test_legacy_routes_keep_working_without_a_webui_session(tmp_path: Path, backend_url: str) -> None:
    app = _app(tmp_path, backend_url)
    anonymous = _client(app)

    # The browser's own admin token passes through, as it did behind nginx.
    passed = anonymous.get("/api/v1/echo", headers={"x-usr-admin-token": "browser-token"}).json()
    assert passed["headers"]["x-usr-admin-token"] == "browser-token"
    # A signed-in browser gets the default backend's token instead.
    injected = _signed_in(app).get("/api/v1/echo", headers={"x-usr-admin-token": "stale"}).json()
    assert injected["headers"]["x-usr-admin-token"] == BACKEND_TOKEN


def test_range_requests_stream_through_and_backend_cookies_are_dropped(tmp_path: Path, backend_url: str) -> None:
    client = _signed_in(_app(tmp_path, backend_url))

    partial = client.get("/b/default/api/v1/media", headers={"range": "bytes=2-5"})
    full = client.get("/b/default/api/v1/media")

    assert partial.status_code == 206 and partial.content == b"2345"
    assert partial.headers["content-range"] == "bytes 2-5/10"
    assert "set-cookie" not in full.headers
    # Opened as a page, a backend response cannot act as the WebUI origin.
    assert full.headers["content-security-policy"].startswith("sandbox")
    assert "allow-same-origin" not in full.headers["content-security-policy"]
    assert full.headers["x-content-type-options"] == "nosniff"


def test_unreachable_backends_return_502(tmp_path: Path) -> None:
    client = _signed_in(_app(tmp_path, "http://127.0.0.1:9"))

    response = client.get("/b/default/api/v1/echo")

    assert response.status_code == 502


def test_websocket_bridge_injects_the_token(tmp_path: Path, backend_url: str) -> None:
    client = _signed_in(_app(tmp_path, backend_url))

    with client.websocket_connect("/b/default/ws/events", headers=ORIGIN) as websocket:
        assert websocket.receive_text() == "hello"
        websocket.send_text("ping")
        assert websocket.receive_text() == "echo:ping"


def test_websocket_bridge_refuses_unsigned_and_cross_site_upgrades(tmp_path: Path, backend_url: str) -> None:
    app = _app(tmp_path, backend_url)

    for client, headers in ((_client(app), ORIGIN), (_signed_in(app), {"origin": "https://evil.example"})):
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/b/default/ws/events", headers=headers) as websocket:
                websocket.receive_text()
        assert closed.value.code == 4401


def test_revoking_a_client_matches_its_id_exactly(tmp_path: Path) -> None:
    app = _app(tmp_path)
    signed_in = _signed_in(app)
    other = _client(app, host="10.0.0.9")
    assert other.post("/webui/api/v1/session/login", json={"password": "a-long-password"}, headers=ORIGIN).status_code == 204

    # A LIKE wildcard as the id once matched, and deleted, every session.
    assert signed_in.delete("/webui/api/v1/clients/%25", headers=ORIGIN).status_code == 204
    assert other.get("/webui/api/v1/session").json()["authenticated"] is True
    assert signed_in.get("/webui/api/v1/session").json()["authenticated"] is True


# ---- Host names and response headers ------------------------------------


@pytest.mark.parametrize("host", ["localhost:21120", "127.0.0.1", "[::1]:21120", "192.168.1.5", "nas", "nas.local", "usr.home.arpa"])
def test_local_host_names_are_served(tmp_path: Path, host: str) -> None:
    assert _client(_app(tmp_path)).get("/health", headers={"host": host}).status_code == 200


def test_a_public_host_name_is_refused_unless_allowed(tmp_path: Path) -> None:
    # A DNS rebinding page reaches this server under the attacker's own name.
    client = _client(_app(tmp_path))
    assert client.get("/webui/api/v1/session", headers={"host": "rebind.attacker.example"}).status_code == 400
    assert client.get("/health", headers={"x-forwarded-host": "rebind.attacker.example"}).status_code == 400
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/events", headers={"host": "rebind.attacker.example"}) as websocket:
            websocket.receive_text()
    assert closed.value.code == 1008

    allowed = create_app(
        Settings(data_dir=tmp_path / "allowed", static_dir=tmp_path / "static", allowed_hosts=("usr.example.com", ".example.org"))
    )
    for host in ("usr.example.com", "example.org", "usr.example.org:443"):
        assert _client(allowed).get("/health", headers={"host": host}).status_code == 200
    assert _client(allowed).get("/health", headers={"host": "usr.example.net"}).status_code == 400


def test_responses_forbid_framing_and_sniffing(tmp_path: Path) -> None:
    response = _client(_app(tmp_path)).get("/")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"


# ---- The WebUI itself -------------------------------------------------


def test_spa_routes_serve_the_index(tmp_path: Path) -> None:
    client = _client(_app(tmp_path))

    page = client.get("/setup")
    asset = client.get("/assets/app-abc123.js")

    assert page.status_code == 200 and "<title>USR</title>" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert "immutable" in asset.headers["cache-control"]
    assert client.get("/favicon.svg").text == "<svg/>"
    assert client.get("/webui/unknown").status_code == 404
    # App pages for a backend are the SPA too.
    assert "<title>USR</title>" in client.get("/b/default/users/1").text
    assert "<title>USR</title>" in client.get("/connections").text
    assert client.get("/../../etc/passwd").status_code in (200, 404)
    assert "root:" not in client.get("/..%2F..%2Fetc%2Fpasswd").text


def test_missing_build_reports_clearly(tmp_path: Path) -> None:
    client = _client(_app(tmp_path, with_static=False))

    assert client.get("/").status_code == 503
    assert client.get("/health").text == "healthy\n"


def test_connection_ticket_export_and_parse(tmp_path: Path, backend_url: str) -> None:
    client = _signed_in(_app(tmp_path, backend_url))
    client.post(
        "/webui/api/v1/connections",
        json={"name": "cluster-node", "base_url": backend_url, "token": BACKEND_TOKEN},
        headers=ORIGIN,
    )

    ticket_res = client.get("/webui/api/v1/connections/cluster-node/ticket")
    assert ticket_res.status_code == 200
    ticket = ticket_res.json()["ticket"]
    assert ticket.startswith("usr://ticket/")

    # Parse ticket via API
    parsed = client.post("/webui/api/v1/connections/parse-ticket", json={"ticket": ticket}, headers=ORIGIN)
    assert parsed.status_code == 200
    data = parsed.json()
    assert data["name"] == "cluster-node"
    assert data["base_url"] == backend_url
    assert data["token"] == BACKEND_TOKEN
    assert data["tls_verify"] is True

    # Parse usr:// URI format as well
    uri_ticket = f"usr://{BACKEND_TOKEN}@192.168.50.60:21121?name=custom-node"
    parsed_uri = client.post("/webui/api/v1/connections/parse-ticket", json={"ticket": uri_ticket}, headers=ORIGIN)
    assert parsed_uri.status_code == 200
    uri_data = parsed_uri.json()
    assert uri_data["name"] == "custom-node"
    assert uri_data["base_url"] == "http://192.168.50.60:21121"
    assert uri_data["token"] == BACKEND_TOKEN


def test_the_default_connections_ticket_names_the_backend_not_this_server(tmp_path: Path, backend_url: str) -> None:
    client = _signed_in(_app(tmp_path, backend_url))
    # What the backend last reported about itself (this fake has no identity route).
    client.app.state.store.save_identity("default", '{"backend_id": "fake", "cluster_id": "c-1"}')

    exported = client.get("/webui/api/v1/connections/default/ticket").json()
    parsed = client.post("/webui/api/v1/connections/parse-ticket", json={"ticket": exported["ticket"]}, headers=ORIGIN).json()

    # The backend's own id, which means something on another WebUI.
    assert exported["name"] == parsed["name"] == "fake"
    assert parsed["cluster_id"] == "c-1"
    # A loopback address is kept, with a warning that it only works from here.
    assert parsed["base_url"] == backend_url
    assert "only works from this WebUI's host" in exported["warning"]


def test_tickets_share_an_address_other_webuis_can_use() -> None:
    from ultima_webui_server.tickets import local_only, shareable_fields

    assert all(local_only(url) for url in ("http://127.0.0.1:21121", "http://localhost:21121", "http://backend:21121"))
    assert not any(local_only(url) for url in ("http://192.168.50.120:21121", "https://alpha.lan:21121"))

    # A Docker-internal address gives way to the one the backend advertises.
    assert shareable_fields(
        name="This server",
        base_url="http://backend:21121",
        default_connection=True,
        backend_id="alpha-18427e",
        api_url="http://192.168.50.120:21121",
    ) == ("alpha-18427e", "http://192.168.50.120:21121", None)
    # A name chosen here is kept, and a reachable address is not touched.
    assert shareable_fields(
        name="NAS",
        base_url="http://192.168.1.10:21121",
        default_connection=False,
        backend_id="nas-1",
        api_url=None,
    ) == ("NAS", "http://192.168.1.10:21121", None)
    # No backend id known yet: the default connection keeps its label rather than nothing.
    name, _, warning = shareable_fields(
        name="This server", base_url="http://127.0.0.1:21121", default_connection=True, backend_id=None, api_url=None
    )
    assert name == "This server" and warning is not None


# ---- Cluster page, invites and joining ----------------------------------------


def _add(client: TestClient, name: str, base_url: str, backend_id: str, cluster_id: str = "c-1") -> str:
    created = client.post(
        "/webui/api/v1/connections",
        json={"name": name, "base_url": base_url, "token": f"{name}-token"},
        headers=ORIGIN,
    ).json()
    client.app.state.store.save_identity(
        created["id"], json.dumps({"backend_id": backend_id, "cluster_id": cluster_id})
    )
    return created["id"]


def test_the_overview_lists_api_servers_as_backends_and_every_worker_host() -> None:
    from ultima_webui_server.clusters import Identity, build_overview
    from ultima_webui_server.connections import Connection

    devbox = Connection(id="devbox", name="devbox", base_url="http://192.168.1.20:21121", tls_verify=True, managed=False, _token="t")
    members = [(devbox, Identity(backend_id="devbox-1", cluster_id="c-1"))]
    live = [
        # The full backend this WebUI connects to: API and workers.
        {"backend_id": "devbox-1", "hostname": "devbox", "cluster_id": "c-1", "version": "0.1.0", "status": "online",
         "max_workers": 12, "active_workers": 10, "pending_jobs": 3, "workers": [{"worker_id": "w1", "status": "busy"}]},
        # Workers only (alpha): no connection, no advertised address.
        {"backend_id": "alpha-1", "hostname": "alpha", "cluster_id": "c-1", "status": "online", "max_workers": 4, "active_workers": 4},
        # Another API server that advertises its address.
        {"backend_id": "nas-1", "hostname": "nas", "cluster_id": "c-1", "api_url": "https://192.168.1.10:21121", "status": "online"},
        # An older member that does not say which cluster: still this Redis, so this cluster.
        {"backend_id": "old-1", "hostname": "old", "max_workers": 2},
        # Another cluster on the same list is ignored.
        {"backend_id": "else-1", "hostname": "else", "cluster_id": "c-2", "api_url": "http://else:21121", "max_workers": 1},
    ]

    overview = build_overview("c-1", "Home", members, live, "devbox")

    assert [(b.name, b.connection_id, b.address) for b in overview.backends] == [
        ("devbox", "devbox", "http://192.168.1.20:21121"),
        ("nas", None, "https://192.168.1.10:21121"),
    ]
    assert [(h.name, h.active_workers, h.max_workers) for h in overview.worker_hosts] == [
        ("alpha", 4, 4),
        ("devbox", 10, 12),
        ("old", 0, 2),
    ]
    assert overview.worker_hosts[1].workers[0].worker_id == "w1" and overview.error is None


def test_a_connected_backend_missing_from_the_list_shows_as_unreachable() -> None:
    from ultima_webui_server.clusters import Identity, build_overview
    from ultima_webui_server.connections import Connection

    nas = Connection(id="nas", name="NAS", base_url="http://nas:21121", tls_verify=True, managed=False, _token="t")
    members = [(nas, Identity(backend_id="nas-1", cluster_id="c-1"))]

    listed = build_overview("c-1", "Home", members, [], "nas")
    nobody = build_overview("c-1", "Home", members, None, None)

    assert [(b.name, b.status) for b in listed.backends] == [("NAS", "unreachable")]
    assert [(b.name, b.status) for b in nobody.backends] == [("NAS", "unknown")]
    assert nobody.error == "No member of this cluster answered."


async def test_overviews_ask_the_next_member_and_are_kept_briefly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from ultima_webui_server import clusters as clusters_mod

    client = _signed_in(_app(tmp_path))
    _add(client, "down", "http://10.0.0.1:21121", "down-1")
    _add(client, "up", "http://10.0.0.2:21121", "up-1")
    asked: list[str] = []

    async def live_members(reached):
        asked.append(reached.id)
        return None if reached.id == "down" else [{"backend_id": "up-1", "hostname": "up", "cluster_id": "c-1"}]

    async def resolve(connection_id):
        return client.app.state.connections.get(connection_id)

    monkeypatch.setattr(clusters_mod, "_live_members", live_members)
    overviews = clusters_mod.ClusterOverviews(client.app.state.connections, client.app.state.store, resolve)

    first = await overviews.get("c-1")
    again = await overviews.get("c-1")

    assert first.answered_by == "up" and asked == ["down", "up"]
    assert again == first and asked == ["down", "up"]
    with pytest.raises(HTTPException) as unknown:
        await overviews.get("not-a-cluster")
    assert unknown.value.status_code == 404


def test_a_cluster_invite_shares_reachable_members_and_says_what_it_left_out(tmp_path: Path) -> None:
    from ultima_webui_server.tickets import parse_cluster_invite

    client = _signed_in(_app(tmp_path))
    _add(client, "devbox", "http://192.168.1.20:21121", "devbox-1")
    _add(client, "local", "http://127.0.0.1:9", "local-1")
    assert client.put("/webui/api/v1/clusters/c-1/name", json={"name": "Home"}, headers=ORIGIN).json() == {"name": "Home"}

    out = client.get("/webui/api/v1/clusters/c-1/invite").json()
    parsed = parse_cluster_invite(out["invite"])

    assert out["invite"].startswith("usr://cluster/")
    assert parsed["cluster_id"] == "c-1" and parsed["name"] == out["name"] == "Home"
    assert [(m["name"], m["base_url"], m["token"]) for m in parsed["members"]] == [
        ("devbox", "http://192.168.1.20:21121", "devbox-token")
    ]
    assert [item["name"] for item in out["excluded"]] == ["local"]
    assert "only works from this WebUI's host" in out["excluded"][0]["reason"]
    assert client.get("/webui/api/v1/clusters/unknown/invite").status_code == 404


def test_an_invite_with_nothing_to_share_is_refused(tmp_path: Path) -> None:
    client = _signed_in(_app(tmp_path))
    _add(client, "local", "http://127.0.0.1:9", "local-1")

    refused = client.get("/webui/api/v1/clusters/c-1/invite")

    assert refused.status_code == 400 and "local:" in refused.json()["detail"]
    # And how to make one reachable.
    assert "Serve HTTPS for other machines" in refused.json()["detail"]


def test_joining_previews_then_adds_new_members_and_names_the_cluster(tmp_path: Path) -> None:
    from ultima_webui_server.tickets import create_cluster_invite

    client = _signed_in(_app(tmp_path))
    _add(client, "already", "http://192.168.1.20:21121", "devbox-1")
    invite = create_cluster_invite(
        cluster_id="c-1",
        name="Home",
        members=[
            {"name": "devbox", "backend_id": "devbox-1", "base_url": "http://192.168.1.20:21121", "token": "a"},
            {"name": "nas", "backend_id": "nas-1", "base_url": "http://192.168.1.10:21121", "token": "b"},
        ],
    )

    preview = client.post("/webui/api/v1/clusters/preview-invite", json={"ticket": invite}, headers=ORIGIN).json()
    joined = client.post("/webui/api/v1/clusters/join", json={"ticket": invite}, headers=ORIGIN).json()
    again = client.post("/webui/api/v1/clusters/join", json={"ticket": invite}, headers=ORIGIN).json()

    assert "token" not in json.dumps(preview)
    assert [(m["name"], m["already_connected"]) for m in preview["members"]] == [("devbox", True), ("nas", False)]
    assert (joined["name"], joined["created"], joined["skipped"]) == ("Home", ["nas"], ["devbox"])
    assert again["created"] == [] and again["skipped"] == ["devbox", "nas"]
    # The new member belongs to the cluster before it is first asked, and carries its token.
    assert json.loads(client.app.state.store.identities()["nas"][0])["cluster_id"] == "c-1"
    assert client.app.state.connections.get("nas").token() == "b"
    names = {c["cluster_id"]: c["name"] for c in client.get("/webui/api/v1/clusters").json()["clusters"]}
    assert names.get("c-1") == "Home"


def test_invites_and_tickets_do_not_mix(tmp_path: Path) -> None:
    client = _signed_in(_app(tmp_path))

    as_ticket = client.post("/webui/api/v1/connections/parse-ticket", json={"ticket": "usr://cluster/abc"}, headers=ORIGIN)
    as_invite = client.post("/webui/api/v1/clusters/preview-invite", json={"ticket": "usr://ticket/abc"}, headers=ORIGIN)

    assert as_ticket.status_code == 400 and "cluster invite" in as_ticket.json()["detail"]
    assert as_invite.status_code == 400 and "Not a cluster invite" in as_invite.json()["detail"]


# ---- Upgrading a cluster ------------------------------------------------


def _deployment(store, deployment_id: str, name: str, *, connection_id=None, join=None, backend=True) -> None:
    from ultima_webui_server.store import DeploymentRecord

    store.save_deployment(
        DeploymentRecord(
            id=deployment_id,
            name=name,
            target="local",
            details={
                "kind": "local",
                "install_dir": f"/srv/{name}",
                "project": f"usr-{name}",
                "version": "0.1.0",
                "image_source": "copy",
                "components": {"backend": backend, "worker": True},
                "join_connection_id": join,
            },
            connection_id=connection_id,
            state="active",
            created_at=1.0,
            updated_at=1.0,
        )
    )


def test_a_cluster_upgrades_its_nodes_one_after_another_and_stops_at_a_failure(tmp_path: Path) -> None:
    import time as _time

    app = _app(tmp_path)
    with _client(app) as client:
        assert client.post(
            "/webui/api/v1/session/claim", json={"password": "a-long-password"}, headers=ORIGIN
        ).status_code == 204
        devbox = _add(client, "devbox", "http://192.168.1.20:21121", "devbox-1")
        other = _add(client, "elsewhere", "http://10.0.0.9:21121", "x-1", cluster_id="c-2")
        store = app.state.store
        _deployment(store, "d-alpha", "alpha", join=devbox, backend=False)
        _deployment(store, "d-devbox", "devbox", connection_id=devbox)
        _deployment(store, "d-nas", "nas", join=devbox, backend=False)
        _deployment(store, "d-other", "other", connection_id=other)

        listed = client.get("/webui/api/v1/clusters/c-1/deployments").json()
        # API servers first: they bring the shared database up to date.
        assert [item["name"] for item in listed] == ["devbox", "alpha", "nas"]

        upgraded: list[tuple[str, str]] = []

        async def fake_upgrade(deployment, target, request, emit):
            upgraded.append((deployment.name, request.version))
            if deployment.name == "alpha":
                raise RuntimeError("alpha could not pull the images")
            await emit("output", f"{deployment.name} is on {request.version}")

        app.state.installer._upgrade = fake_upgrade
        started = client.post("/webui/api/v1/clusters/c-1/upgrade", json={"version": "0.2.0"}, headers=ORIGIN)
        assert started.status_code == 202, started.text

        run_id = started.json()["id"]
        for _ in range(100):
            status = client.get(f"/webui/api/v1/installs/{run_id}").json()
            if status["state"] != "running":
                break
            _time.sleep(0.05)
        assert status["state"] == "failed"
        assert upgraded == [("devbox", "0.2.0"), ("alpha", "0.2.0")]
        messages = [event["message"] for event in status["events"]]
        assert "Upgrading devbox (1 of 3)" in messages and "Upgrading alpha (2 of 3)" in messages
        assert "Not upgraded, still on their version: nas" in messages
        assert any("alpha could not pull the images" in message for message in messages)

        # A choice of nodes, and a bad version, are honoured.
        assert client.post(
            "/webui/api/v1/clusters/c-1/upgrade",
            json={"version": "0.2.0", "deployment_ids": []},
            headers=ORIGIN,
        ).json()["detail"] == "There is nothing to upgrade."
        assert client.post(
            "/webui/api/v1/clusters/c-1/upgrade", json={"version": "bad version!"}, headers=ORIGIN
        ).status_code == 400


def test_the_main_cluster_is_where_the_app_opens(tmp_path: Path) -> None:
    client = _signed_in(_app(tmp_path))
    home = _add(client, "devbox", "http://192.168.1.20:21121", "devbox-1", cluster_id="c-1")
    lab = _add(client, "lab", "http://10.0.0.9:21121", "lab-1", cluster_id="c-2")

    # The first cluster this WebUI was in is the main one until another is chosen.
    assert client.get("/webui/api/v1/session").json()["main_connections"] == [home]
    assert client.get("/webui/api/v1/clusters").json()["main_cluster_id"] == "c-1"
    assert client.put("/webui/api/v1/clusters/main", json={"cluster_id": "c-2"}, headers=ORIGIN).status_code == 200

    session = client.get("/webui/api/v1/session").json()
    assert session["default_connection"] == lab and session["main_connections"] == [lab]
    assert client.put("/webui/api/v1/clusters/main", json={"cluster_id": "nope"}, headers=ORIGIN).status_code == 404
    assert client.put("/webui/api/v1/clusters/main", json={"cluster_id": "c-1"}, headers=ORIGIN).status_code == 200
    assert client.get("/webui/api/v1/session").json()["main_connections"] == [home]
    # A main cluster this WebUI has left is replaced by the first one it is still in.
    client.delete(f"/webui/api/v1/connections/{home}", headers=ORIGIN)
    assert client.get("/webui/api/v1/session").json()["main_connections"] == [lab]

    renamed = client.put("/webui/api/v1/hosts/name", json={"key": "192.168.50.40", "name": "nas01"}, headers=ORIGIN)
    assert renamed.json() == {"key": "192.168.50.40", "name": "nas01"}
