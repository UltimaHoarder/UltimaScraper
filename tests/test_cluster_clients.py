"""Cluster clients: invites, joining, client tokens, HTTPS and the advertised address."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ultima_scraper_backend.config import BackendSettings
from ultima_scraper_backend import backend_tls, cluster, cluster_clients, security
from ultima_scraper_backend.api.routes import cluster as cluster_routes


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for name in (
        "USR_BACKEND_TLS",
        "USR_BACKEND_TLS_CERT_FILE",
        "USR_BACKEND_TLS_KEY_FILE",
        "USR_ADVERTISE_HOST",
        "USR_ADVERTISE_PORT",
        "CONTROL_TLS_PORT",
        "USR_ALLOW_REMOTE_BIND",
        "USR_ADMIN_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    # Nothing is read from this machine's real .env.
    monkeypatch.setenv("ULTIMA_ENV_PATH", str(tmp_path / "config" / ".env"))
    monkeypatch.setenv("USR_REPOSITORY_ROOT", str(tmp_path))
    backend_tls.tls_files.cache_clear()
    backend_tls.tls_fingerprint.cache_clear()
    # This backend's settings: none shared, unless a test says so.
    monkeypatch.setattr(backend_tls, "_settings", lambda: BackendSettings())
    monkeypatch.setattr(cluster_clients, "_active_hashes", frozenset())
    yield
    backend_tls.tls_files.cache_clear()
    backend_tls.tls_fingerprint.cache_clear()


# ---- Tokens ---------------------------------------------------------------------


def test_a_client_token_is_accepted_next_to_the_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USR_ADMIN_TOKEN", "admin-secret")
    token = f"{cluster_clients.CLIENT_TOKEN_PREFIX}abc"
    monkeypatch.setattr(cluster_clients, "_active_hashes", frozenset({cluster_clients.hash_secret(token)}))

    assert security.is_admin_token_valid("admin-secret")
    assert security.is_admin_token_valid(token)
    assert not security.is_admin_token_valid(f"{cluster_clients.CLIENT_TOKEN_PREFIX}other")
    # Only tokens that look like a client's are looked up.
    assert not cluster_clients.is_client_token("abc")
    assert not security.is_admin_token_valid(None)


async def test_an_unknown_client_token_reloads_once_before_it_is_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    reloads: list[bool] = []

    async def refresh(*, force: bool = False) -> None:
        reloads.append(force)

    monkeypatch.setattr(cluster_clients, "refresh", refresh)
    known = f"{cluster_clients.CLIENT_TOKEN_PREFIX}known"
    monkeypatch.setattr(cluster_clients, "_active_hashes", frozenset({cluster_clients.hash_secret(known)}))

    await cluster_clients.refresh_for(f"{cluster_clients.CLIENT_TOKEN_PREFIX}new")
    await cluster_clients.refresh_for(known)
    await cluster_clients.refresh_for("an-admin-token")
    await cluster_clients.refresh_for(None)

    assert reloads == [False]


# ---- HTTPS and the advertised address -------------------------------------------


def test_the_address_is_derived_only_for_a_backend_serving_https_on_the_lan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cluster, "_lan_address", lambda: "192.168.1.20")
    assert cluster.public_api_url() is None

    monkeypatch.setenv("USR_BACKEND_TLS", "self-signed")
    assert cluster.public_api_url() is None  # still loopback only

    monkeypatch.setenv("USR_ALLOW_REMOTE_BIND", "true")
    assert cluster.public_api_url() == "https://192.168.1.20:8443"

    # In a container, the deployment passes the host's address and published port.
    monkeypatch.setenv("USR_ADVERTISE_HOST", "192.168.50.120")
    monkeypatch.setenv("USR_ADVERTISE_PORT", "18443")
    assert cluster.public_api_url() == "https://192.168.50.120:18443"
    monkeypatch.setenv("USR_ADVERTISE_HOST", "fd00::5")
    assert cluster.public_api_url() == "https://[fd00::5]:18443"


def test_the_backends_settings_share_it_unless_the_environment_says_otherwise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cluster, "_lan_address", lambda: "192.168.1.20")
    monkeypatch.setenv("USR_ALLOW_REMOTE_BIND", "true")
    monkeypatch.setattr(
        backend_tls,
        "_settings",
        lambda: BackendSettings(share_https=True, https_port=9443, advertise_host="devbox.lan"),
    )

    assert backend_tls.tls_enabled() and backend_tls.tls_port() == 9443
    assert cluster.public_api_url() == "https://devbox.lan:9443"
    files = backend_tls.tls_files()
    assert files is not None and files.cert_file.parent == tmp_path / "config" / "tls"

    # A deployment that fixes it in the environment wins.
    monkeypatch.setenv("USR_BACKEND_TLS", "off")
    backend_tls.tls_files.cache_clear()
    assert not backend_tls.tls_enabled() and backend_tls.tls_files() is None
    monkeypatch.delenv("USR_BACKEND_TLS")
    monkeypatch.setenv("CONTROL_TLS_PORT", "18443")
    monkeypatch.setenv("USR_ADVERTISE_HOST", "192.168.50.120")
    assert cluster.public_api_url() == "https://192.168.50.120:18443"


def test_a_self_signed_certificate_is_kept_next_to_the_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USR_BACKEND_TLS", "self-signed")
    monkeypatch.setenv("USR_ADVERTISE_HOST", "alpha.lan")

    files = backend_tls.tls_files()

    assert files is not None and files.cert_file.parent == tmp_path / "config" / "tls"
    assert backend_tls.tls_fingerprint() and len(backend_tls.tls_fingerprint().split(":")) == 32


def test_https_settings_are_checked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert backend_tls.tls_files() is None and not backend_tls.tls_enabled()

    # Settings are read once per process; each case below starts afresh.
    backend_tls.tls_files.cache_clear()
    monkeypatch.setenv("USR_BACKEND_TLS_CERT_FILE", str(tmp_path / "missing.pem"))
    with pytest.raises(backend_tls.TLSConfigurationError, match="Set both"):
        backend_tls.tls_files()
    assert backend_tls.tls_fingerprint() is None

    backend_tls.tls_files.cache_clear()
    monkeypatch.delenv("USR_BACKEND_TLS_CERT_FILE")
    monkeypatch.setenv("USR_BACKEND_TLS", "on")
    with pytest.raises(backend_tls.TLSConfigurationError, match="self-signed"):
        backend_tls.tls_files()
    monkeypatch.setenv("CONTROL_TLS_PORT", "nope")
    assert backend_tls.tls_port() == backend_tls.DEFAULT_TLS_PORT


# ---- Routes -----------------------------------------------------------------------


def _client(monkeypatch: pytest.MonkeyPatch, *, base_url: str) -> TestClient:
    async def members(_backend):
        return "c-1", [cluster_routes.ClusterMember(backend_id="devbox-1", name="devbox", api_url="https://192.168.1.20:8443", tls_fingerprint="AA:BB")]

    async def run(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def backend():
        return object()

    monkeypatch.setattr(cluster_routes, "_members", members)
    monkeypatch.setattr(cluster_routes, "run_database_call", run)
    monkeypatch.setattr(cluster_clients, "cluster_name", lambda: "Home")
    app = FastAPI()
    app.include_router(cluster_routes.router, prefix="/api/v1")
    app.dependency_overrides[cluster_routes.get_backend_instance] = backend
    return TestClient(app, base_url=base_url)


def test_joining_needs_https_because_the_reply_carries_a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    redeemed: list[dict] = []

    def redeem(code, **fields):
        redeemed.append({"code": code, **fields})
        return cluster_clients.Joined(client_id="client-1", token=f"{cluster_clients.CLIENT_TOKEN_PREFIX}t")

    monkeypatch.setattr(cluster_clients, "redeem_invite", redeem)
    body = {"code": "usri_abcdefgh", "name": "alpha", "version": "0.1.0"}

    plain = _client(monkeypatch, base_url="http://testserver").post("/api/v1/cluster/join", json=body)
    assert plain.status_code == 400 and redeemed == []
    secure = _client(monkeypatch, base_url="https://testserver").post("/api/v1/cluster/join", json=body)

    joined = secure.json()
    assert secure.status_code == 200
    assert (joined["client_id"], joined["token"], joined["cluster_id"], joined["name"]) == (
        "client-1",
        f"{cluster_clients.CLIENT_TOKEN_PREFIX}t",
        "c-1",
        "Home",
    )
    assert joined["members"][0]["tls_fingerprint"] == "AA:BB"
    assert redeemed[0]["name"] == "alpha" and redeemed[0]["kind"] == "webui"


def test_a_used_or_unknown_invite_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def redeem(code, **fields):
        raise cluster_clients.InviteRejected("The invite is unknown, already used, or expired.")

    monkeypatch.setattr(cluster_clients, "redeem_invite", redeem)
    refused = _client(monkeypatch, base_url="https://testserver").post(
        "/api/v1/cluster/join", json={"code": "usri_abcdefgh", "name": "alpha"}
    )

    assert refused.status_code == 403 and "already used" in refused.json()["detail"]


def test_only_a_client_token_checks_in(monkeypatch: pytest.MonkeyPatch) -> None:
    token = f"{cluster_clients.CLIENT_TOKEN_PREFIX}t"
    monkeypatch.setattr(cluster_clients, "_active_hashes", frozenset({cluster_clients.hash_secret(token)}))
    beats: list[dict] = []
    monkeypatch.setattr(cluster_clients, "record_heartbeat", lambda t, **fields: beats.append(fields) or True)
    client = _client(monkeypatch, base_url="https://testserver")

    admin = client.post("/api/v1/cluster/clients/heartbeat", json={}, headers={"x-usr-admin-token": "admin"})
    ok = client.post("/api/v1/cluster/clients/heartbeat", json={"version": "1"}, headers={"x-usr-admin-token": token})

    assert admin.status_code == 400 and ok.status_code == 204
    assert beats == [{"name": None, "version": "1", "address": "testclient"}]


# ---- Against PostgreSQL ------------------------------------------------------------


@pytest.fixture
def cluster_database(monkeypatch: pytest.MonkeyPatch):
    target = os.getenv("USV_CLUSTER_TEST_DATABASE_URL")
    if not target:
        pytest.skip("Disposable cluster test database not configured")
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates import postgres_site as models

    url = make_url(target).set(drivername="postgresql+psycopg")
    assert url.database and url.database.startswith("degen_test_")
    parent = create_engine(url, isolation_level="AUTOCOMMIT")
    name = f"degen_test_cluster_{uuid4().hex}"
    with parent.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
    engine = create_engine(url.set(database=name))
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA management"))
        tables = [models.Base.metadata.tables[f"management.{table}"] for table in ("cluster", "cluster_clients", "cluster_invites")]
        models.Base.metadata.create_all(engine, tables=tables)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO management.cluster (id) VALUES (1)"))
        monkeypatch.setattr(cluster_clients, "_session", lambda: Session(engine))
        yield engine
    finally:
        engine.dispose()
        with parent.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        parent.dispose()


def test_an_invite_admits_one_client_until_it_is_revoked(cluster_database) -> None:
    from sqlalchemy import text

    code, expires_at = cluster_clients.create_invite("admin", hours=1)
    joined = cluster_clients.redeem_invite(code, name="alpha", kind="webui", version="0.1.0", address="192.168.50.120")

    assert code.startswith(cluster_clients.INVITE_CODE_PREFIX)
    assert expires_at - datetime.now(timezone.utc) <= timedelta(hours=1)
    assert cluster_clients.is_client_token(joined.token)
    with pytest.raises(cluster_clients.InviteRejected):
        cluster_clients.redeem_invite(code, name="again", kind="webui", version=None, address=None)
    # Nothing secret is stored in the clear.
    with cluster_database.connect() as connection:
        stored = connection.execute(text("SELECT token_hash FROM management.cluster_clients")).scalar()
        codes = connection.execute(text("SELECT code_hash, used_by FROM management.cluster_invites")).one()
    assert stored == cluster_clients.hash_secret(joined.token) and joined.token not in stored
    assert codes.code_hash == cluster_clients.hash_secret(code) and str(codes.used_by) == joined.client_id

    assert cluster_clients.record_heartbeat(joined.token, name=None, version="0.2.0", address="192.168.50.120")
    assert cluster_clients.client_for_token(joined.token) == joined.client_id
    [listed] = cluster_clients.list_clients()
    assert (listed["name"], listed["version"], listed["revoked_at"]) == ("alpha", "0.2.0", None)

    assert cluster_clients.revoke_client(joined.client_id)
    assert not cluster_clients.is_client_token(joined.token)
    assert not cluster_clients.record_heartbeat(joined.token, name=None, version=None, address=None)
    assert not cluster_clients.revoke_client(joined.client_id)
    assert not cluster_clients.revoke_client("not-a-uuid")


def test_an_expired_invite_is_refused_and_the_cluster_can_be_named(cluster_database) -> None:
    from sqlalchemy import text

    code, _ = cluster_clients.create_invite("admin")
    with cluster_database.begin() as connection:
        connection.execute(text("UPDATE management.cluster_invites SET expires_at = now() - interval '1 minute'"))

    with pytest.raises(cluster_clients.InviteRejected):
        cluster_clients.redeem_invite(code, name="late", kind="webui", version=None, address=None)
    assert cluster_clients.cluster_name() is None
    assert cluster_clients.rename_cluster("  Home  ") == "Home" and cluster_clients.cluster_name() == "Home"


async def test_the_token_set_reloads_from_the_database(cluster_database, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run(function, *args, **kwargs):
        return function(*args, **kwargs)

    import ultima_scraper_backend.database.threads as threads

    monkeypatch.setattr(threads, "run_database_call", run)
    code, _ = cluster_clients.create_invite("admin")
    joined = cluster_clients.redeem_invite(code, name="alpha", kind="webui", version=None, address=None)
    monkeypatch.setattr(cluster_clients, "_active_hashes", frozenset())  # as on another backend

    await cluster_clients.refresh(force=True)

    assert cluster_clients.is_client_token(joined.token)
