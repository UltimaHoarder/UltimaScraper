from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from ultima_webui_server import Settings, create_app
from ultima_webui_server.installer.probe import probe
from ultima_webui_server.installer.render import (
    COMPOSE_DIR,
    Components,
    DeploySpec,
    InvalidSpec,
    image_reference,
    render,
)
from ultima_webui_server.installer.runner import Redactor
from ultima_webui_server.installer.targets import CommandResult
from ultima_webui_server.store import Store

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = {"origin": "http://testserver"}


def _spec(**changes) -> DeploySpec:
    values = dict(
        project="usr-nas",
        install_dir="/home/deploy/ultimascraper",
        components=Components(),
        image_prefix="",
        version="0.1.0",
        backend_id="nas-abc123",
        backend_port=21121,
        web_port=21120,
    )
    values.update(changes)
    return DeploySpec(**values)


def _env(rendered) -> dict[str, str]:
    lines = rendered.files[".env"][0].decode().splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def test_installer_ships_the_repository_compose_file() -> None:
    assert (COMPOSE_DIR / "docker-compose.yml").read_text() == (ROOT / "docker-compose.yml").read_text()


def test_render_writes_private_secrets_and_selected_profiles() -> None:
    rendered = render(_spec(components=Components(webui=True, worker=False)))
    env = _env(rendered)

    assert rendered.files[".env"][1] == 0o600
    assert rendered.files["docker-compose.yml"][1] == 0o644
    assert env["COMPOSE_PROFILES"] == "webui,backend,postgres,redis"
    assert env["USR_ADMIN_TOKEN"] == rendered.admin_token and len(rendered.admin_token) >= 32
    assert env["BACKEND_ID"] == "nas-abc123"
    # One image runs every role.
    assert env["USR_IMAGE"] == "ultimascraper" and env["USR_VERSION"] == "0.1.0"
    assert not {"USR_BACKEND_IMAGE", "USR_WORKER_IMAGE", "USR_WEBUI_IMAGE"} & env.keys()
    assert env["REDIS_HOST"] == "redis" and env["ULTIMA_ARCHIVE_DATABASE_URL"] == ""
    assert env["USR_WEBUI_DEFAULT_BACKEND_URL"] == "http://backend:21121"
    # Every install gets fresh secrets.
    assert render(_spec()).admin_token != rendered.admin_token


def test_an_installed_webui_serves_https_for_the_host() -> None:
    with_webui = _env(render(_spec(components=Components(webui=True), webui_hostnames=("nas.lan",))))
    without = _env(render(_spec()))

    assert (with_webui["USR_WEBUI_TLS"], with_webui["USR_WEBUI_TLS_HOSTNAMES"]) == ("self-signed", "nas.lan")
    assert "USR_WEBUI_TLS" not in without


def test_a_shared_backend_serves_https_on_every_interface_at_its_advertised_address() -> None:
    from ultima_webui_server.installer.render import BACKEND_TLS_FILE
    from ultima_webui_server.installer.runner import compose_command

    shared = render(_spec(share_backend=True, advertise_host="192.168.1.20", backend_tls_port=8444))
    plain = render(_spec())

    assert BACKEND_TLS_FILE in shared.files and BACKEND_TLS_FILE not in plain.files
    assert _env(shared)["USR_ADVERTISE_HOST"] == "192.168.1.20" and _env(shared)["USR_BACKEND_TLS_PORT"] == "8444"
    assert "USR_ADVERTISE_HOST" not in _env(plain) and "USR_BACKEND_TLS_PORT" not in _env(plain)
    # Every install says which address its host has, for the cluster to show.
    assert _env(render(_spec(advertise_host="192.168.50.120")))["USR_ADVERTISE_HOST"] == "192.168.50.120"
    override = shared.files[BACKEND_TLS_FILE][0].decode()
    assert "USR_BACKEND_TLS: self-signed" in override and '"${USR_BACKEND_TLS_PORT:-8443}:8443"' in override
    assert shared.compose_command(_spec()).endswith(f"-f {BACKEND_TLS_FILE}")
    assert compose_command("/d", "usr-nas", Components(), shared=True).endswith(f"-f {BACKEND_TLS_FILE}")
    with pytest.raises(InvalidSpec, match="which address"):
        render(_spec(share_backend=True))
    with pytest.raises(InvalidSpec, match="Only a backend"):
        render(_spec(share_backend=True, advertise_host="h", components=Components(backend=False, worker=False)))


def test_render_uses_registry_images_and_external_services() -> None:
    spec = _spec(
        image_prefix="forgejo.example/org/ultimascraper",
        components=Components(postgres=False, redis=False),
        database_url="postgresql+psycopg://usr:pw#1@db.example/ultima_archive",
        redis_host="redis.example",
        redis_port=6380,
        redis_password="secret",
    )
    env = _env(render(spec))

    assert image_reference(spec) == "forgejo.example/org/ultimascraper/ultimascraper:0.1.0"
    assert env["USR_IMAGE"] == "forgejo.example/org/ultimascraper/ultimascraper"
    assert env["COMPOSE_PROFILES"] == "backend,worker"
    assert env["ULTIMA_ARCHIVE_DATABASE_URL"] == "'postgresql+psycopg://usr:pw#1@db.example/ultima_archive'"
    assert (env["REDIS_HOST"], env["REDIS_PORT"], env["REDIS_PASSWORD"]) == ("redis.example", "6380", "secret")


def test_image_reference_normalizes_protocol_and_uppercase() -> None:
    from ultima_webui_server.installer.runner import InstallIn

    spec = _spec(
        image_prefix="https://forgejo.example/org/UltimaScraper/",
        version="edge",
    )
    assert image_reference(spec) == "forgejo.example/org/ultimascraper/ultimascraper:edge"

    install_in = InstallIn(
        name="test",
        image_source="registry",
        image_prefix="https://forgejo.example/org/UltimaScraper/",
        version="edge",
    )
    assert install_in.image_prefix == "forgejo.example/org/ultimascraper"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"components": Components(False, False, False, False, False)}, "at least one"),
        ({"components": Components(postgres=False)}, "database URL"),
        ({"components": Components(redis=False)}, "Redis host"),
        ({"project": "Bad Name"}, "lowercase"),
        ({"components": Components(postgres=False), "database_url": "postgresql://u:it's@db/x"}, "single quotes"),
    ],
)
def test_render_refuses_incomplete_or_unsafe_specs(changes: dict, message: str) -> None:
    with pytest.raises(InvalidSpec, match=message):
        render(_spec(**changes))


def test_redactor_hides_every_secret() -> None:
    redact = Redactor()
    redact.add("hunter22", None, "abc", "admin-token-value")

    assert redact("sudo hunter22 and admin-token-value, abc") == "sudo [REDACTED] and [REDACTED], abc"


class _FakeTarget:
    description = "fake"

    def __init__(self, answers: dict[str, CommandResult]) -> None:
        self.answers = answers
        self.commands: list[tuple[str, bool]] = []

    async def run(self, command, *, sudo=False, stdin=None, check=True, on_output=None):
        self.commands.append((command, sudo))
        for prefix, result in self.answers.items():
            if command.startswith(prefix) and (sudo or not prefix.startswith("sudo:")):
                return result
        return CommandResult(0, "", "")

    async def close(self) -> None:
        return None


async def test_probe_maps_the_architecture_and_finds_docker_through_sudo() -> None:
    target = _FakeTarget(
        {
            "uname -m": CommandResult(0, "aarch64", ""),
            ". /etc/os-release": CommandResult(0, "Ubuntu 26.04 LTS", ""),
            "id -un": CommandResult(0, "deploy", ""),
            'printf "%s" "$HOME"': CommandResult(0, "/home/deploy", ""),
            "docker version": CommandResult(1, "", "permission denied while trying to connect"),
            "(ss -ltnH": CommandResult(0, "0.0.0.0:22\n127.0.0.1:21121\n[::]:21122", ""),
        }
    )

    async def sudo_docker(command, *, sudo=False, stdin=None, check=True, on_output=None):
        target.commands.append((command, sudo))
        if sudo and command.startswith("docker version"):
            return CommandResult(0, "28.1.0", "")
        if sudo and command.startswith("docker compose"):
            return CommandResult(0, "2.40.0", "")
        return await _FakeTarget.run(target, command, sudo=sudo, stdin=stdin, check=check)

    target.run = sudo_docker  # type: ignore[method-assign]
    facts = await probe(target, sudo_available=True)

    assert (facts.architecture, facts.user, facts.home) == ("arm64", "deploy", "/home/deploy")
    assert facts.docker_version == "28.1.0" and facts.docker_needs_sudo is True
    assert facts.compose_version == "2.40.0"
    assert facts.free_port(21121) == 21123


async def test_probe_refuses_unsupported_architectures() -> None:
    from ultima_webui_server.installer.probe import UnsupportedHost

    with pytest.raises(UnsupportedHost, match="riscv64"):
        await probe(_FakeTarget({"uname -m": CommandResult(0, "riscv64", "")}), sudo_available=False)


def test_store_upgrades_an_existing_connections_table(tmp_path: Path) -> None:
    path = tmp_path / "webui.db"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE connections (id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL, "
        "token TEXT, tls_verify INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL);"
        "INSERT INTO connections VALUES ('nas', 'NAS', 'http://nas:21121', NULL, 1, 0);"
    )
    old.close()

    store = Store(path)

    [connection] = store.list_connections()
    assert connection.id == "nas" and connection.tunnel is None


def _signed_in(tmp_path: Path) -> TestClient:
    app = create_app(Settings(data_dir=tmp_path / "data", static_dir=tmp_path))
    client = TestClient(app, client=("127.0.0.1", 50000))
    assert client.post("/webui/api/v1/session/claim", json={"password": "a-long-password"}, headers=ORIGIN).status_code == 204
    return client


def test_install_api_needs_a_session_and_complete_ssh_details(tmp_path: Path) -> None:
    client = _signed_in(tmp_path)
    assert TestClient(client.app).get("/webui/api/v1/installs/environment").status_code == 401

    environment = client.get("/webui/api/v1/installs/environment").json()
    assert set(environment) == {"version", "local_available", "in_container", "copy_available", "releases"}
    assert environment["version"] == "0.1.0"  # the installed package's

    incomplete = client.post(
        "/webui/api/v1/installs",
        json={"name": "nas", "version": "0.1.0", "target": {"kind": "ssh", "host": "nas", "username": "deploy"}},
        headers=ORIGIN,
    )
    assert incomplete.status_code == 400
    assert "host key" in incomplete.json()["detail"]
    registry_without_source = client.post(
        "/webui/api/v1/installs",
        json={
            "name": "nas",
            "version": "0.1.0",
            "image_source": "registry",
            "target": {"kind": "ssh", "host": "nas", "username": "d", "password": "p", "host_key": "ssh-ed25519 AAAA"},
        },
        headers=ORIGIN,
    )
    assert registry_without_source.status_code == 400


def test_host_key_lookup_reports_unreachable_hosts(tmp_path: Path) -> None:
    client = _signed_in(tmp_path)

    response = client.post("/webui/api/v1/installs/host-key", json={"host": "127.0.0.1", "port": 9}, headers=ORIGIN)

    assert response.status_code == 502


@pytest.mark.parametrize(
    ("os_release", "family"),
    [
        ("ubuntu debian", "ubuntu"),
        ("debian ", "debian"),
        ("linuxmint ubuntu debian", "ubuntu"),
        ("rocky rhel centos fedora", "fedora"),
        ("alpine ", "alpine"),
        ("endeavouros arch", "arch"),
        ("opensuse-leap suse opensuse", None),
    ],
)
async def test_docker_setup_recognises_distribution_families(os_release: str, family: str | None) -> None:
    from ultima_webui_server.installer.docker_setup import distribution

    target = _FakeTarget({". /etc/os-release": CommandResult(0, os_release, "")})

    assert await distribution(target) == family


async def test_docker_setup_refuses_unknown_distributions_with_instructions() -> None:
    from ultima_webui_server.installer.docker_setup import DockerSetupFailed, install_docker

    async def ignore(_line: str) -> None:
        return None

    with pytest.raises(DockerSetupFailed, match="docs.docker.com"):
        await install_docker(_FakeTarget({". /etc/os-release": CommandResult(0, "gentoo", "")}), ignore)


def _deployment(client: TestClient, **details) -> str:
    from ultima_webui_server.store import DeploymentRecord

    record = DeploymentRecord(
        id="dep1",
        name="NAS",
        target="deploy@nas",
        details={
            "kind": "ssh",
            "host": "nas",
            "port": 22,
            "username": "deploy",
            "host_key": "ssh-ed25519 AAAA",
            "install_dir": "/home/deploy/ultimascraper",
            "project": "usr-nas",
            "version": "0.1.0",
            "image_source": "copy",
            "image_prefix": "",
            "components": {"backend": True, "worker": True, "postgres": True, "redis": True, "webui": False},
            "architecture": "amd64",
            "backend_port": 21121,
            "web_port": 21120,
            **details,
        },
        connection_id=None,
        state="active",
        created_at=0,
        updated_at=0,
    )
    client.app.state.store.save_deployment(record)
    return record.id


def test_deployments_are_listed_without_credentials(tmp_path: Path) -> None:
    client = _signed_in(tmp_path)
    _deployment(client)

    [listed] = client.get("/webui/api/v1/deployments").json()

    assert listed["name"] == "NAS" and listed["details"]["version"] == "0.1.0"
    assert "password" not in str(listed) and "private_key" not in str(listed)


def test_cluster_stores_returns_fallback_and_rewrites_for_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ULTIMA_ARCHIVE_DATABASE_URL", "postgresql://user:pass@127.0.0.1:5432/mydb")
    monkeypatch.setenv("REDIS_HOST", "127.0.0.1")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_PASSWORD", "secret")
    client = _signed_in(tmp_path)
    res_local = client.get("/webui/api/v1/installs/cluster-stores?target_is_remote=false").json()
    assert res_local["available"] is True
    assert res_local["database"]["host"] == "127.0.0.1"
    assert res_local["database"]["port"] == 5432
    assert res_local["database"]["name"] == "mydb"
    assert res_local["database"]["username"] == "user"
    assert res_local["database"]["password"] == "pass"
    assert res_local["redis"]["host"] == "127.0.0.1"
    assert res_local["redis"]["port"] == 6379
    assert res_local["redis"]["password"] == "secret"

    res_remote = client.get("/webui/api/v1/installs/cluster-stores?target_is_remote=true").json()
    assert res_remote["available"] is True
    assert res_remote["database"]["host"] != "127.0.0.1"
    assert res_remote["redis"]["host"] != "127.0.0.1"


@pytest.mark.parametrize(
    ("deployment_id", "body", "status", "message"),
    [
        ("missing", {"action": "repair", "credentials": {"password": "x"}}, 404, "No such deployment"),
        ("dep1", {"action": "repair"}, 400, "password or a private key"),
        ("dep1", {"action": "upgrade", "credentials": {"password": "x"}}, 400, "version"),
        (
            "dep1",
            {"action": "upgrade", "credentials": {"password": "x"}, "version": "0.2.0", "image_source": "registry"},
            400,
            "registry",
        ),
        (
            "dep1",
            {"action": "upgrade", "credentials": {"password": "x"}, "version": "0.2.0", "image_prefix": "evil|reg"},
            422,
            "",
        ),
    ],
)
def test_operations_refuse_incomplete_requests(
    tmp_path: Path, deployment_id: str, body: dict, status: int, message: str
) -> None:
    client = _signed_in(tmp_path)
    _deployment(client)

    response = client.post(f"/webui/api/v1/deployments/{deployment_id}/operations", json=body, headers=ORIGIN)

    assert response.status_code == status, response.text
    assert message in response.text


def test_shared_component_rules_fixture_matches_render_validation() -> None:
    from ultima_webui_server.installer.render import COMPONENT_RULES, DatabaseSpec

    rows = COMPONENT_RULES["combinations"]
    assert len(rows) == 72
    error_messages = COMPONENT_RULES["error_messages"]

    for row in rows:
        spec = _spec(
            components=Components(
                backend=row["backend"] == "install",
                worker=row["worker"] == "install",
                postgres=row["postgres"] == "install",
                redis=row["redis"] == "install",
                webui=row["webui"] == "install",
            ),
            database=DatabaseSpec(host="db.internal") if row["postgres"] == "existing" else None,
            redis_host="redis.internal" if row["redis"] == "existing" else None,
        )
        if row["valid"]:
            rendered = render(spec)
            assert ".env" in rendered.files
        else:
            expected_msg = error_messages[row["error_code"]]
            with pytest.raises(InvalidSpec) as exc_info:
                render(spec)
            assert str(exc_info.value) == expected_msg


def test_store_only_deployment_publishes_ports_via_override_compose_file() -> None:
    from ultima_webui_server.installer.render import STORE_PORTS_FILE

    spec = _spec(
        components=Components(backend=False, worker=False, postgres=True, redis=True, webui=False),
        postgres_port=5433,
        redis_port=6380,
    )
    rendered = render(spec)

    assert STORE_PORTS_FILE in rendered.files
    assert f"-f {STORE_PORTS_FILE}" in rendered.compose_command(spec)
    env = _env(rendered)
    assert env["COMPOSE_PROFILES"] == "postgres,redis"
    assert env["POSTGRES_PORT"] == "5433"
    assert env["REDIS_PORT"] == "6380"


def test_structured_database_builds_url_and_rewrites_localhost_to_host_docker_internal() -> None:
    from ultima_webui_server.installer.render import DatabaseSpec

    spec = _spec(
        components=Components(backend=True, worker=True, postgres=False, redis=False),
        database=DatabaseSpec(
            host="localhost",
            port=5432,
            name="ultima_archive",
            user="ultima_user",
            password="s3cr#t@password",
        ),
        redis_host="127.0.0.1",
        redis_port=6379,
        redis_password="redis-secret",
    )
    rendered = render(spec)
    env = _env(rendered)

    assert env["ULTIMA_ARCHIVE_DATABASE_URL"] == (
        "postgresql+asyncpg://ultima_user:s3cr%23t%40password@host.docker.internal:5432/ultima_archive"
    )
    assert env["REDIS_HOST"] == "host.docker.internal"
    assert env["REDIS_PORT"] == "6379"

    # Also verify direct database_url with 127.0.0.1 is rewritten.
    direct = render(
        _spec(
            components=Components(backend=True, worker=False, postgres=False, redis=True),
            database_url="postgresql+asyncpg://u:p@127.0.0.1:5432/archive",
        )
    )
    assert _env(direct)["ULTIMA_ARCHIVE_DATABASE_URL"] == (
        "postgresql+asyncpg://u:p@host.docker.internal:5432/archive"
    )


def test_detect_and_check_service_with_faked_local_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ultima_webui_server.installer import probe as probe_mod
    from ultima_webui_server.installer.images import LocalRelease

    async def fake_releases() -> list[LocalRelease]:
        return [LocalRelease(version="0.1.0", architecture="amd64", names=("ultimascraper",))]

    monkeypatch.setattr(probe_mod, "local_releases", fake_releases)

    fake_target = _FakeTarget(
        {
            "uname -m": CommandResult(0, "x86_64", ""),
            ". /etc/os-release": CommandResult(0, "Ubuntu 24.04 LTS", ""),
            "id -un": CommandResult(0, "alice", ""),
            'printf "%s" "$HOME"': CommandResult(0, "/home/alice", ""),
            "hostname": CommandResult(0, "devbox", ""),
            "docker version": CommandResult(0, "27.5.1", ""),
            "docker compose version": CommandResult(0, "2.32.4", ""),
            "docker compose ls": CommandResult(
                0,
                '[{"Name":"usr-existing","Status":"running(2)"},{"Name":"other-stack","Status":"running(1)"}]',
                "",
            ),
            "docker ps": CommandResult(0, "postgres:16-alpine\tpg-local\n", ""),
            "awk '/^MemTotal:/": CommandResult(0, "1024", ""),
            'df -Pm "$HOME"': CommandResult(0, "3000", ""),
            "(ss -ltnH": CommandResult(0, "127.0.0.1:5432\n127.0.0.1:6379\n", ""),
            "cat /home/alice/ultimascraper/.usr-install.json": CommandResult(
                0,
                '{"project":"usr-existing","version":"0.1.0","components":["backend","postgres","redis"]}',
                "",
            ),
            "if command -v bash": CommandResult(0, "", ""),
        }
    )

    client = _signed_in(tmp_path)
    installer = client.app.state.installer
    installer.local_allowed = True

    async def fake_open_target(_target_in):
        return fake_target

    monkeypatch.setattr(installer, "open_target", fake_open_target)

    detect_resp = client.post(
        "/webui/api/v1/installs/detect",
        json={"target": {"kind": "local"}, "install_dir": "~/ultimascraper"},
        headers=ORIGIN,
    )
    assert detect_resp.status_code == 200, detect_resp.text
    data = detect_resp.json()
    facts = data["facts"]
    assert facts["architecture"] == "amd64"
    assert facts["hostname"] == "devbox"
    assert facts["sudo_mode"] == "none"
    assert data["needs_sudo_for"] == []
    assert facts["existing_projects"] == ["usr-existing"]
    assert facts["existing_install"]["project"] == "usr-existing"
    assert facts["services"]["postgres"]["detected"] is True
    assert facts["services"]["redis"]["detected"] is True
    assert data["recommended_components"] == {
        "backend": "install",
        "worker": "install",
        "postgres": "existing",
        "redis": "existing",
        "webui": "reuse",
    }
    assert data["recommended_image_source"] == "target"
    assert len(facts["warnings"]) == 2

    check_resp = client.post(
        "/webui/api/v1/installs/check-service",
        json={"target": {"kind": "local"}, "kind": "postgres", "host": "localhost", "port": 5432},
        headers=ORIGIN,
    )
    assert check_resp.status_code == 200, check_resp.text
    assert check_resp.json()["reachable"] is True


async def test_local_install_without_ssh_fields_and_worker_cluster_match_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ultima_webui_server.clusters import ClusterOut, ClustersOut, Identity, MemberOut
    from ultima_webui_server.installer import probe as probe_mod
    from ultima_webui_server.installer import runner as runner_mod

    async def fake_releases():
        return []

    monkeypatch.setattr(probe_mod, "local_releases", fake_releases)

    exec_prefix = (
        "cd /home/alice/ultimascraper && docker compose --project-name usr-worker-node "
        "-f docker-compose.yml -f docker-compose.backend-port.yml exec -T worker"
    )
    fake_target = _FakeTarget(
        {
            "uname -m": CommandResult(0, "x86_64", ""),
            ". /etc/os-release": CommandResult(0, "Ubuntu 24.04 LTS", ""),
            "id -un": CommandResult(0, "alice", ""),
            'printf "%s" "$HOME"': CommandResult(0, "/home/alice", ""),
            "hostname": CommandResult(0, "my-workstation", ""),
            "docker version": CommandResult(0, "27.5.1", ""),
            "docker compose version": CommandResult(0, "2.32.4", ""),
            "test -e": CommandResult(1, "", ""),
            "docker image inspect": CommandResult(0, "amd64\n", ""),
            exec_prefix: CommandResult(0, "cluster-abc\n", ""),
        }
    )

    client = _signed_in(tmp_path)
    installer = client.app.state.installer
    installer.local_allowed = True

    async def fake_open_target(_target_in):
        return fake_target

    monkeypatch.setattr(installer, "open_target", fake_open_target)

    # 1. Local install with WebUI and without SSH fields sets webui_hostnames from machine hostname
    spec = installer._spec(
        runner_mod.InstallIn(
            name="Local Box",
            target=runner_mod.TargetIn(kind="local"),
            components=runner_mod.ComponentsIn(backend=False, worker=False, postgres=False, redis=False, webui=True),
        ),
        backend_port=21121,
        web_port=21120,
        home="/home/alice",
        hostname="my-workstation",
    )
    assert spec.webui_hostnames == ("my-workstation",)

    # 2. Worker-only install verifies cluster identity via describe_clusters
    async def matching_clusters(_connections, _store, _resolve):
        return ClustersOut(
            members=[
                MemberOut(
                    connection_id="primary",
                    name="Primary Backend",
                    reachable=True,
                    identity=Identity(backend_id="primary-1", cluster_id="cluster-abc"),
                )
            ],
            clusters=[
                ClusterOut(
                    cluster_id="cluster-abc",
                    connection_ids=["primary"],
                    suggestions=[],
                )
            ],
        )

    monkeypatch.setattr(runner_mod, "describe_clusters", matching_clusters)

    events: list[tuple[str, str]] = []

    async def record_emit(kind: str, message: str) -> None:
        events.append((kind, message))

    worker_req = runner_mod.InstallIn(
        name="Worker Node",
        target=runner_mod.TargetIn(kind="local"),
        components=runner_mod.ComponentsIn(backend=False, worker=True, postgres=False, redis=False, webui=False),
        database=runner_mod.DatabaseIn(host="10.0.0.10", port=5432, name="ultima_archive", user="postgres", password="pw"),
        redis_host="10.0.0.10",
        join_connection_id="primary",
    )
    await installer._install(worker_req, runner_mod.Redactor(), record_emit)
    assert any("Worker joined cluster cluster-abc" in msg for _, msg in events)

    # 3. Mismatched worker cluster identity raises InstallError
    fake_target.answers[exec_prefix] = CommandResult(0, "cluster-wrong\n", "")
    with pytest.raises(runner_mod.InstallError, match="Cluster identity mismatch"):
        await installer._install(worker_req, runner_mod.Redactor(), record_emit)

    # 4. ComponentsIn accepts wizard mode strings ("install", "existing", "none", "reuse")
    parsed_components = runner_mod.ComponentsIn.model_validate(
        {
            "backend": "install",
            "worker": "none",
            "postgres": "existing",
            "redis": "install",
            "webui": "reuse",
        }
    )
    assert parsed_components.model_dump() == {
        "backend": True,
        "worker": False,
        "postgres": False,
        "redis": True,
        "webui": False,
    }




def _local_host(hostname: str = "devbox", **extra: CommandResult) -> _FakeTarget:
    return _FakeTarget(
        {
            "uname -m": CommandResult(0, "x86_64", ""),
            ". /etc/os-release": CommandResult(0, "Ubuntu 24.04 LTS", ""),
            "id -un": CommandResult(0, "alice", ""),
            'printf "%s" "$HOME"': CommandResult(0, "/home/alice", ""),
            "hostname": CommandResult(0, hostname, ""),
            "docker version": CommandResult(0, "27.5.1", ""),
            "docker compose version": CommandResult(0, "2.32.4", ""),
            "test -e": CommandResult(1, "", ""),
            **extra,
        }
    )


def _local_installer(client: TestClient, target: _FakeTarget, monkeypatch: pytest.MonkeyPatch):
    from ultima_webui_server.installer import probe as probe_mod

    async def no_releases():
        return []

    async def fake_open_target(_target_in):
        return target

    monkeypatch.setattr(probe_mod, "local_releases", no_releases)
    installer = client.app.state.installer
    installer.local_allowed = True
    monkeypatch.setattr(installer, "open_target", fake_open_target)
    return installer


async def _ignore(_kind: str, _message: str) -> None:
    return None


async def test_operations_keep_store_ports_published_on_store_only_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ultima_webui_server.installer import runner as runner_mod
    from ultima_webui_server.installer.render import STORE_PORTS_FILE

    target = _local_host(
        **{
            "cat /home/deploy/ultimascraper/.usr-install.json": CommandResult(
                0, '{"project": "usr-nas", "version": "0.1.0"}', ""
            ),
            "test -f": CommandResult(0, "", ""),
        }
    )
    client = _signed_in(tmp_path)
    installer = _local_installer(client, target, monkeypatch)
    _deployment(
        client,
        kind="local",
        components={"backend": False, "worker": False, "postgres": True, "redis": True, "webui": False},
    )
    record = installer.store.get_deployment("dep1")
    local = runner_mod.TargetIn(kind="local")

    await installer._repair(record, local, runner_mod.OperationIn(action="repair"), _ignore)
    await installer._upgrade(
        record, local, runner_mod.OperationIn(action="upgrade", version="0.2.0", image_source="target"), _ignore
    )
    await installer._uninstall(record, local, runner_mod.OperationIn(action="uninstall"), _ignore)

    compose_runs = [command for command, _ in target.commands if " up --detach" in command or " down " in command]
    assert len(compose_runs) == 3
    assert all(f"-f {STORE_PORTS_FILE}" in command for command in compose_runs)
    # A host that runs a backend keeps its stores private.
    assert STORE_PORTS_FILE not in runner_mod.compose_command("/srv/usr", "usr-nas", Components())


async def test_check_service_passes_the_host_as_an_argument_with_a_timeout() -> None:
    from ultima_webui_server.installer.probe import check_service

    target = _FakeTarget({})
    ok, _ = await check_service(target, host="db.lan", port=5432)
    [(command, _)] = target.commands
    assert ok and "timeout 3 bash" in command and command.endswith("probe db.lan 5432; else nc -z -w 3 db.lan 5432; fi")

    for hostile in ("$(touch /tmp/x)", "db;id", "a b", "`id`"):
        target = _FakeTarget({})
        ok, message = await check_service(target, host=hostile, port=5432)
        assert not ok and "valid host" in message and target.commands == []

    timed_out = _FakeTarget({"if command -v bash": CommandResult(124, "", "")})
    ok, message = await check_service(timed_out, host="10.0.0.5", port=6379)
    assert not ok and "within 3s" in message


def test_only_published_or_listening_stores_are_detected() -> None:
    from ultima_webui_server.installer.probe import _detect_services

    # Another stack's bundled database keeps its port on its own network.
    hidden = _detect_services(frozenset(), ["postgres:16-alpine\tusr-other-postgres-1\t5432/tcp"])
    assert hidden["postgres"]["detected"] is False
    assert hidden["postgres"]["unreachable_containers"] == ["usr-other-postgres-1"]
    assert "redis" not in hidden

    published = _detect_services(
        frozenset(),
        [
            "postgres:16-alpine\tpg\t0.0.0.0:5433->5432/tcp, [::]:5433->5432/tcp",
            "valkey/valkey:8\tcache\t127.0.0.1:6380->6379/tcp",
        ],
    )
    assert (published["postgres"]["detected"], published["postgres"]["port"]) == (True, 5433)
    assert (published["redis"]["detected"], published["redis"]["port"]) == (True, 6380)

    native = _detect_services(frozenset({5432}), [])
    assert native["postgres"] == {
        "detected": True,
        "host": "localhost",
        "port": 5432,
        "listening": True,
        "container": None,
    }


async def test_probe_recommends_installing_stores_it_cannot_reach(monkeypatch: pytest.MonkeyPatch) -> None:
    from ultima_webui_server.installer import probe as probe_mod

    async def no_releases():
        return []

    monkeypatch.setattr(probe_mod, "local_releases", no_releases)
    target = _local_host(
        **{"docker ps": CommandResult(0, "postgres:16-alpine\tusr-a-postgres-1\t5432/tcp\nredis:7\tr\t6379/tcp\n", "")}
    )
    facts = await probe(target, sudo_available=False)

    assert probe_mod.recommend_components(facts)["postgres"] == "install"
    assert probe_mod.recommend_components(facts)["redis"] == "install"


async def test_store_only_install_reports_how_other_hosts_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ultima_webui_server.installer import runner as runner_mod

    target = _local_host(hostname="storage-box")
    client = _signed_in(tmp_path)
    installer = _local_installer(client, target, monkeypatch)
    request = runner_mod.InstallIn(
        name="Stores",
        components=runner_mod.ComponentsIn(backend=False, worker=False, postgres=True, redis=True, webui=False),
        postgres_port=5433,
        redis_port=6380,
        image_source="target",
    )
    outputs: dict = {}
    await installer._install(request, runner_mod.Redactor(), _ignore, outputs)

    connection = outputs["store_connection"]
    assert connection["host"] == "storage-box"
    assert connection["postgres"]["port"] == 5433 and connection["postgres"]["user"] == "ultimascraper"
    assert connection["redis"]["port"] == 6380
    assert len(connection["postgres"]["password"]) >= 24 and len(connection["redis"]["password"]) >= 24

    # The run's status carries it, only once the run has succeeded.
    installer._store_connections["run1"] = outputs
    assert installer.store_connection("run1") == connection
    assert installer.store_connection("unknown") is None


async def test_a_failed_worker_cluster_check_keeps_the_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ultima_webui_server.clusters import ClusterOut, ClustersOut, Identity, MemberOut
    from ultima_webui_server.installer import runner as runner_mod

    exec_prefix = (
        "cd /home/alice/ultimascraper && docker compose --project-name usr-worker-node "
        "-f docker-compose.yml -f docker-compose.backend-port.yml exec -T worker"
    )
    target = _local_host(
        **{
            "docker image inspect": CommandResult(0, "amd64\n", ""),
            exec_prefix: CommandResult(0, "cluster-wrong\n", ""),
        }
    )
    client = _signed_in(tmp_path)
    installer = _local_installer(client, target, monkeypatch)

    async def clusters(_connections, _store, _resolve):
        return ClustersOut(
            members=[
                MemberOut(
                    connection_id="primary",
                    name="Primary",
                    reachable=True,
                    identity=Identity(backend_id="primary-1", cluster_id="cluster-abc"),
                )
            ],
            clusters=[ClusterOut(cluster_id="cluster-abc", connection_ids=["primary"], suggestions=[])],
        )

    monkeypatch.setattr(runner_mod, "describe_clusters", clusters)
    request = runner_mod.InstallIn(
        name="Worker Node",
        components=runner_mod.ComponentsIn(backend=False, worker=True, postgres=False, redis=False, webui=False),
        database=runner_mod.DatabaseIn(host="10.0.0.10", password="pw"),
        redis_host="10.0.0.10",
        join_connection_id="primary",
        image_source="target",
    )

    with pytest.raises(runner_mod.InstallError, match="install was kept"):
        await installer._install(request, runner_mod.Redactor(), _ignore)

    [kept] = [d for d in installer.store.list_deployments() if d.details["project"] == "usr-worker-node"]
    assert kept.state == "active" and kept.details["join_connection_id"] == "primary"


def test_a_worker_without_a_backend_must_name_the_backend_it_joins(tmp_path: Path) -> None:
    client = _signed_in(tmp_path)
    client.app.state.installer.local_allowed = True
    body = {
        "name": "Worker Node",
        "target": {"kind": "local"},
        "components": {"backend": "none", "worker": "install", "postgres": "existing", "redis": "existing"},
        "database": {"host": "10.0.0.10", "password": "pw"},
        "redis_host": "10.0.0.10",
        "image_source": "target",
    }

    missing = client.post("/webui/api/v1/installs", json=body, headers=ORIGIN)
    unknown = client.post("/webui/api/v1/installs", json=body | {"join_connection_id": "nope"}, headers=ORIGIN)

    assert missing.status_code == 400 and "backend this worker joins" in missing.json()["detail"]
    assert unknown.status_code == 404


def test_structured_database_defaults_to_the_bundled_user() -> None:
    from ultima_webui_server.installer.render import DatabaseSpec
    from ultima_webui_server.installer.runner import DatabaseIn

    assert DatabaseIn().user == DatabaseSpec().user == "ultimascraper"


class _CheckingTarget(_FakeTarget):
    """Raises on a failing command run with check=True, like the real targets."""

    async def run(self, command, *, sudo=False, stdin=None, check=True, on_output=None):
        from ultima_webui_server.installer.targets import CommandFailed

        result = await super().run(command, sudo=sudo, stdin=stdin, check=check, on_output=on_output)
        if check and result.exit_status != 0:
            raise CommandFailed(command, result)
        return result


def _failing_pull_host(**extra: CommandResult) -> _CheckingTarget:
    return _CheckingTarget(
        {
            "uname -m": CommandResult(0, "aarch64", ""),
            ". /etc/os-release": CommandResult(0, "Debian GNU/Linux 13 (trixie)", ""),
            "id -un": CommandResult(0, "ultima", ""),
            'printf "%s" "$HOME"': CommandResult(0, "/home/ultima", ""),
            "hostname": CommandResult(0, "alpha", ""),
            "docker version": CommandResult(0, "26.1.5", ""),
            "docker compose version": CommandResult(0, "2.26.1", ""),
            "test -e": CommandResult(1, "", ""),
            "test -d": CommandResult(1, "", ""),
            "cd /home/ultima/ultimascraper && docker compose": CommandResult(
                18, "", "Error response from daemon: manifest unknown"
            ),
            **extra,
        }
    )


@pytest.mark.parametrize(("folder_existed", "removes_folder"), [(False, True), (True, False)])
async def test_a_failed_image_pull_removes_the_files_it_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, folder_existed: bool, removes_folder: bool
) -> None:
    from ultima_webui_server.installer import runner as runner_mod
    from ultima_webui_server.installer.targets import CommandFailed

    target = _failing_pull_host(**({"test -d": CommandResult(0, "", "")} if folder_existed else {}))
    client = _signed_in(tmp_path)
    installer = _local_installer(client, target, monkeypatch)
    request = runner_mod.InstallIn(
        name="alpha",
        image_source="registry",
        image_prefix="forgejo.example/org/ultimascraper",
        version="acceptance-arm64",
    )

    with pytest.raises(CommandFailed, match="manifest unknown"):
        await installer._install(request, runner_mod.Redactor(), _ignore)

    [cleanup] = [command for command, _ in target.commands if command.startswith("rm -f -- ")]
    for name in (".env", "docker-compose.yml", "docker-compose.backend-port.yml"):
        assert f"/home/ultima/ultimascraper/{name}" in cleanup
    assert ("rmdir -- /home/ultima/ultimascraper" in cleanup) is removes_folder
    # Nothing ran, so nothing is left to manage.
    assert installer.store.list_deployments() == []
    assert not any(" up --detach" in command for command, _ in target.commands)


async def test_an_existing_install_is_never_cleaned_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ultima_webui_server.installer import runner as runner_mod

    target = _failing_pull_host(**{"test -e": CommandResult(0, "", "")})
    client = _signed_in(tmp_path)
    installer = _local_installer(client, target, monkeypatch)

    with pytest.raises(runner_mod.InstallError, match="already holds an install"):
        await installer._install(runner_mod.InstallIn(name="alpha", image_source="target"), runner_mod.Redactor(), _ignore)

    assert not any(command.startswith("rm ") for command, _ in target.commands)


def test_uninstall_needs_the_webui_password_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _signed_in(tmp_path)
    _deployment(client)
    installer = client.app.state.installer
    started: list[str] = []
    # Never let the test reach a real host.
    monkeypatch.setattr(installer, "start_operation", lambda deployment_id, body: started.append(body.action) or "run1")
    url = "/webui/api/v1/deployments/dep1/operations"
    uninstall = {"action": "uninstall", "credentials": {"password": "x"}}

    missing = client.post(url, json=uninstall, headers=ORIGIN)
    wrong = client.post(url, json=uninstall | {"webui_password": "not-it"}, headers=ORIGIN)
    right = client.post(url, json=uninstall | {"webui_password": "a-long-password"}, headers=ORIGIN)
    repair = client.post(url, json={"action": "repair", "credentials": {"password": "x"}}, headers=ORIGIN)

    assert (missing.status_code, wrong.status_code) == (403, 403)
    assert wrong.json()["detail"] == "Wrong WebUI password."
    assert right.status_code == 202 and repair.status_code == 202
    assert started == ["uninstall", "repair"]
    # A refused password does not end the session.
    assert client.get("/webui/api/v1/deployments").status_code == 200


def test_uninstall_password_attempts_are_limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _signed_in(tmp_path)
    _deployment(client)
    monkeypatch.setattr(client.app.state.installer, "start_operation", lambda *_: "run1")
    body = {"action": "uninstall", "credentials": {"password": "x"}, "webui_password": "guess"}

    codes = [
        client.post("/webui/api/v1/deployments/dep1/operations", json=body, headers=ORIGIN).status_code
        for _ in range(7)
    ]

    assert codes[:5] == [403] * 5 and codes[-1] == 429


_NAS_COMPOSE = (
    "cd /home/deploy/ultimascraper && docker compose --project-name usr-nas "
    "-f docker-compose.yml -f docker-compose.backend-port.yml"
)


def _upgrade_host(**extra: CommandResult) -> _CheckingTarget:
    return _CheckingTarget(
        {
            "uname -m": CommandResult(0, "x86_64", ""),
            ". /etc/os-release": CommandResult(0, "Ubuntu 24.04 LTS", ""),
            "id -un": CommandResult(0, "deploy", ""),
            'printf "%s" "$HOME"': CommandResult(0, "/home/deploy", ""),
            "hostname": CommandResult(0, "nas", ""),
            "docker version": CommandResult(0, "27.5.1", ""),
            "docker compose version": CommandResult(0, "2.32.4", ""),
            "cat /home/deploy/ultimascraper/.usr-install.json": CommandResult(
                0, '{"project": "usr-nas", "version": "0.1.0"}', ""
            ),
            "docker image inspect": CommandResult(0, "amd64\n", ""),
            **extra,
        }
    )


async def _upgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: _CheckingTarget):
    from ultima_webui_server.installer import runner as runner_mod

    client = _signed_in(tmp_path)
    installer = _local_installer(client, target, monkeypatch)
    _deployment(client, kind="local")
    record = installer.store.get_deployment("dep1")
    events: list[tuple[str, str]] = []

    async def emit(kind: str, message: str) -> None:
        events.append((kind, message))

    request = runner_mod.OperationIn(action="upgrade", version="0.2.0", image_source="target")
    return installer, installer._upgrade(record, runner_mod.TargetIn(kind="local"), request, emit), events


async def test_a_failed_upgrade_restores_the_previous_env_and_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ultima_webui_server.installer import runner as runner_mod

    target = _upgrade_host(
        **{f"{_NAS_COMPOSE} up --detach --wait --wait-timeout 600": CommandResult(1, "", "backend is unhealthy")}
    )
    installer, upgrade, events = await _upgrade(tmp_path, monkeypatch, target)

    with pytest.raises(runner_mod.InstallError, match="undone: NAS is back on version 0.1.0"):
        await upgrade

    commands = [command for command, _ in target.commands]
    env, backup = "/home/deploy/ultimascraper/.env", "/home/deploy/ultimascraper/.env.usr-before-upgrade"
    compose = "/home/deploy/ultimascraper/docker-compose.yml"
    backed_up = commands.index(f"cp -p {env} {backup}")
    compose_backed_up = commands.index(f"cp -p {compose} {compose}.usr-before-upgrade")
    edited = next(i for i, command in enumerate(commands) if "USR_IMAGE=" in command)
    rewritten = next(i for i, command in enumerate(commands) if f"cat > {compose} " in command)
    restored = commands.index(f"mv -f -- {backup} {env}")
    compose_restored = commands.index(f"mv -f -- {compose}.usr-before-upgrade {compose}")
    restarted = commands.index(f"{_NAS_COMPOSE} up --detach --wait --wait-timeout 300")
    assert backed_up < compose_backed_up < edited < rewritten < restored < compose_restored < restarted
    # Nothing records the version that never ran.
    assert installer.store.get_deployment("dep1").details["version"] == "0.1.0"
    assert not any(".usr-install.json" in command and "cat >" in command for command in commands)
    assert ("step", "Going back to version 0.1.0") in events


async def test_a_failed_rollback_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ultima_webui_server.installer import runner as runner_mod

    target = _upgrade_host(
        **{
            f"{_NAS_COMPOSE} up --detach --wait --wait-timeout 600": CommandResult(1, "", "unhealthy"),
            f"{_NAS_COMPOSE} up --detach --wait --wait-timeout 300": CommandResult(1, "", "still unhealthy"),
        }
    )
    installer, upgrade, _ = await _upgrade(tmp_path, monkeypatch, target)

    with pytest.raises(runner_mod.InstallError, match="Going back to version 0.1.0 failed too; run Repair"):
        await upgrade
    assert installer.store.get_deployment("dep1").details["version"] == "0.1.0"


async def test_a_successful_upgrade_records_the_version_and_drops_the_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _upgrade_host()
    installer, upgrade, _ = await _upgrade(tmp_path, monkeypatch, target)

    await upgrade

    commands = [command for command, _ in target.commands]
    assert "rm -f -- /home/deploy/ultimascraper/.env.usr-before-upgrade" in commands
    assert "rm -f -- /home/deploy/ultimascraper/docker-compose.yml.usr-before-upgrade" in commands
    assert not any(command.startswith("mv -f") for command in commands)
    # An install from before the single image gets this WebUI's Compose files and USR_IMAGE.
    assert any("cat > /home/deploy/ultimascraper/docker-compose.yml " in command for command in commands)
    assert any("USR_IMAGE=" in command for command in commands)
    assert any(".usr-install.json" in command and "cat >" in command for command in commands)
    assert installer.store.get_deployment("dep1").details["version"] == "0.2.0"


async def test_upgrade_and_repair_record_the_build_behind_the_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ultima_webui_server.installer import runner as runner_mod

    target = _upgrade_host(
        **{f"{_NAS_COMPOSE} ps -q backend": CommandResult(0, "0.2.0-edge.0123abcd4567\n", "")}
    )
    installer, upgrade, _ = await _upgrade(tmp_path, monkeypatch, target)

    await upgrade
    details = installer.store.get_deployment("dep1").details
    assert (details["version"], details["image_version"]) == ("0.2.0", "0.2.0-edge.0123abcd4567")
    [probe_command] = [c for c, _ in target.commands if " ps -q backend" in c]
    assert "xargs -r docker inspect --format" in probe_command and "org.opencontainers.image.version" in probe_command

    # A repair refreshes it after the tag moved.
    target.answers[f"{_NAS_COMPOSE} ps -q backend"] = CommandResult(0, "0.2.0-edge.89abcdef0123\n", "")
    record = installer.store.get_deployment("dep1")
    await installer._repair(record, runner_mod.TargetIn(kind="local"), runner_mod.OperationIn(action="repair"), _ignore)
    assert installer.store.get_deployment("dep1").details["image_version"] == "0.2.0-edge.89abcdef0123"


async def test_running_image_version_is_empty_without_a_label() -> None:
    from ultima_webui_server.installer.probe import HostFacts
    from ultima_webui_server.installer.runner import _running_image_version

    facts = HostFacts("amd64", "Ubuntu", "u", "/home/u", "27", "2.32", False, None, None)
    no_label = _FakeTarget({"compose ps -q backend": CommandResult(0, "<no value>\n", "")})
    stores_only = _FakeTarget({})

    assert await _running_image_version(no_label, facts, "compose", Components()) == ""
    assert await _running_image_version(stores_only, facts, "compose", Components(backend=False, worker=False)) == ""
    assert stores_only.commands == []


def test_join_cluster_inherits_secret_key_and_configures_remote_webui() -> None:
    from ultima_webui_server.installer.render import Components, DeploySpec, render

    spec = DeploySpec(
        project="usr-pi",
        install_dir="/home/pi/ultimascraper",
        components=Components(backend=False, worker=True, webui=True, postgres=False, redis=False),
        image_prefix="",
        version="edge",
        backend_id="pi-node-1",
        backend_port=21121,
        web_port=21120,
        database_url="postgresql://usr:pw@192.168.50.40:6432/ultima_archive",
        redis_host="192.168.50.40",
        redis_port=30059,
        secret_key="cluster-shared-secret-key",
        default_backend_url="http://192.168.50.60:21121",
        default_backend_token="cluster-admin-token-xyz",
    )
    env = _env(render(spec))

    assert env["USR_SECRET_KEY"] == "cluster-shared-secret-key"
    assert env["USR_ADMIN_TOKEN"] == "cluster-admin-token-xyz"
    assert env["USR_WEBUI_DEFAULT_BACKEND_URL"] == "http://192.168.50.60:21121"
    assert env["COMPOSE_PROFILES"] == "webui,worker"
    assert env["BACKEND_ID"] == "pi-node-1"



async def _change_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: _CheckingTarget, services: dict, **details
):
    from ultima_webui_server.installer import runner as runner_mod

    client = _signed_in(tmp_path)
    installer = _local_installer(client, target, monkeypatch)
    _deployment(client, kind="local", **details)
    record = installer.store.get_deployment("dep1")
    events: list[tuple[str, str]] = []

    async def emit(kind: str, message: str) -> None:
        events.append((kind, message))

    request = runner_mod.OperationIn(action="services", services=services)
    return installer, installer._change_services(record, runner_mod.TargetIn(kind="local"), request, emit), events


_NAS_ENV = "COMPOSE_PROFILES=backend,worker,postgres,redis\nREDIS_HOST=redis\nUSR_ADMIN_TOKEN=t\n"


async def test_a_host_gets_a_webui_added_to_its_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _upgrade_host(**{"cat /home/deploy/ultimascraper/.env": CommandResult(0, _NAS_ENV, "")})
    installer, change, events = await _change_services(
        tmp_path, monkeypatch, target, {"backend": True, "worker": True, "webui": True}
    )

    await change

    commands = [command for command, _ in target.commands]
    env = "/home/deploy/ultimascraper/.env"
    assert any("COMPOSE_PROFILES=webui,backend,worker,postgres,redis" in command and env in command for command in commands)
    assert any("USR_WEBUI_TLS=self-signed" in command for command in commands)
    assert f"{_NAS_COMPOSE} up --detach --wait --wait-timeout 600" in commands
    assert not any(" rm --stop " in command for command in commands)
    assert installer.store.get_deployment("dep1").details["components"]["webui"] is True
    assert ("step", "Changing services: +webui") in events


async def test_a_host_stops_services_taken_out_of_its_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = _upgrade_host(**{"cat /home/deploy/ultimascraper/.env": CommandResult(0, _NAS_ENV, "")})
    installer, change, _ = await _change_services(
        tmp_path, monkeypatch, target, {"backend": False, "worker": False, "webui": False}
    )

    await change

    commands = [command for command, _ in target.commands]
    assert f"{_NAS_COMPOSE} --profile backend --profile worker rm --stop --force backend worker" in commands
    # Left with PostgreSQL and Redis for other hosts.
    assert any("COMPOSE_PROFILES=postgres,redis" in command for command in commands)
    assert installer.store.get_deployment("dep1").details["components"]["backend"] is False


async def test_a_change_the_rules_refuse_runs_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ultima_webui_server.installer import runner as runner_mod

    # A worker-only host on another backend's stores: with nothing left, they are unused.
    worker_env = "COMPOSE_PROFILES=worker\nULTIMA_ARCHIVE_DATABASE_URL=postgresql://u@db/x\nREDIS_HOST=10.0.0.5\n"
    target = _upgrade_host(**{"cat /home/deploy/ultimascraper/.env": CommandResult(0, worker_env, "")})
    _, change, _ = await _change_services(
        tmp_path,
        monkeypatch,
        target,
        {"backend": False, "worker": False, "webui": False},
        components={"backend": False, "worker": True, "postgres": False, "redis": False, "webui": False},
    )

    with pytest.raises(runner_mod.InstallError, match="Existing PostgreSQL or Redis can only be used"):
        await change
    assert not any(command.startswith("cp -p") for command, _ in target.commands)


async def test_a_failed_change_goes_back_to_the_services_it_ran(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ultima_webui_server.installer import runner as runner_mod

    target = _upgrade_host(
        **{
            "cat /home/deploy/ultimascraper/.env": CommandResult(0, _NAS_ENV, ""),
            f"{_NAS_COMPOSE} up --detach --wait --wait-timeout 600": CommandResult(1, "", "webui is unhealthy"),
        }
    )
    installer, change, _ = await _change_services(
        tmp_path, monkeypatch, target, {"backend": True, "worker": True, "webui": True}
    )

    with pytest.raises(runner_mod.InstallError, match="It runs the services it ran before"):
        await change
    commands = [command for command, _ in target.commands]
    env, backup = "/home/deploy/ultimascraper/.env", "/home/deploy/ultimascraper/.env.usr-before-upgrade"
    assert commands.index(f"mv -f -- {backup} {env}") < commands.index(f"{_NAS_COMPOSE} up --detach --wait --wait-timeout 300")
    assert installer.store.get_deployment("dep1").details["components"]["webui"] is False
