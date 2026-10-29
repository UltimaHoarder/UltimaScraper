import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from ultima_scraper_backend.plugin_system import installation
from ultima_scraper_backend.plugin_system.http_transport import HTTPResponse
from ultima_scraper_backend.plugin_system.platform import PluginPlatform

ROOT = Path(__file__).resolve().parents[1]


def git(path, *args):
    return subprocess.check_output(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(path),
            *args,
        ],
        text=True,
    ).strip()


def source(root, name="sample-plugin", manifest=None):
    directory = root / name
    directory.mkdir(parents=True)
    declaration = manifest or {
        "plugin_id": name,
        "plugin_version": "1.0.0",
        "display_name": "Sample Plugin",
        "usr_compatibility": ">=0.1.0",
        "capabilities": ["events.read"],
    }
    (directory / "manifest.yaml").write_text(yaml.safe_dump(declaration))
    (directory / "data.txt").write_text("reviewed bytes\n")
    git(directory, "init", "-b", "main")
    git(directory, "config", "user.name", "Plugin tests")
    git(directory, "config", "user.email", "plugins@example.invalid")
    git(directory, "add", ".")
    git(directory, "commit", "-m", "Baseline")
    return directory


@pytest.fixture
def platform(tmp_path, monkeypatch):
    monkeypatch.setenv("USR_PLUGIN_SOURCES_DIR", str(tmp_path / "sources"))
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    result = PluginPlatform(runtime, http_request=lambda *_args, **_kwargs: None)
    result.load_all()

    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "ultima_scraper_backend.plugin_system.extensions.run_database_call", inline
    )
    return result


def prepare(platform, directory):
    return platform.prepare_plugin_install(
        {"kind": "local", "source_id": directory.name}
    )


def confirm(platform, preview):
    return platform.confirm_plugin_install(
        preview["plugin_id"], preview["preview_token"]
    )


def test_review_is_exact_and_install_does_not_execute_or_copy_git(platform):
    directory = source(platform.sources_directory())
    original_manifest = (directory / "manifest.yaml").read_bytes()
    preview = prepare(platform, directory)
    assert platform.list_plugins() == []
    (directory / "data.txt").write_text("changed after review")
    installed = confirm(platform, preview)
    assert installed["status"] == "disabled"
    assert installed["pending_capabilities"] == ["events.read"]
    assert (
        platform._plugins_dir / "sample-plugin/data.txt"
    ).read_text() == "reviewed bytes\n"
    assert not (platform._plugins_dir / "sample-plugin/.git").exists()
    assert (
        platform._plugins_dir / "sample-plugin/manifest.yaml"
    ).read_bytes() == original_manifest
    assert (directory / ".git").exists()
    with pytest.raises(ValueError, match="setup"):
        platform.enable_plugin("sample-plugin")
    with pytest.raises(installation.InstallationConflict, match="already installed"):
        prepare(platform, directory)


@pytest.mark.asyncio
async def test_permission_and_setup_required_before_enable(platform):
    preview = prepare(platform, source(platform.sources_directory()))
    confirm(platform, preview)
    with pytest.raises(PermissionError, match="Approve"):
        await platform.save_plugin_setup("sample-plugin", {}, {}, enable=True)
    platform.approve_capabilities("sample-plugin")
    assert (await platform.save_plugin_setup("sample-plugin", {}, {}, enable=True))[
        "status"
    ] == "enabled"


@pytest.mark.asyncio
async def test_uninstall_restart_and_reinstall_retain_state_and_revoke_tokens(platform):
    directory = source(platform.sources_directory())
    confirm(platform, prepare(platform, directory))
    platform.approve_capabilities("sample-plugin")
    await platform.save_plugin_setup("sample-plugin", {}, {}, enable=True)
    platform.repository.set_document(
        "plugin_configuration", "sample-plugin", {"retained": "value"}
    )
    platform.repository.update_host_document(
        "sample-plugin", "schedule:sample", lambda _: {"job_id": "historical"}
    )
    platform.secrets.set_secret("sample-plugin", "setup", "saved", "retained-key")
    token = platform.repository.issue_api_token("sample-plugin")
    result = platform.uninstall_plugin("sample-plugin")
    assert result["data_retained"]
    assert not platform.repository.authenticate_api_token(token)
    assert platform.list_plugins() == []
    assert platform.list_plugin_sources()[0]["data_retained"]
    assert not platform.list_plugin_sources()[0]["installed"]
    restarted = PluginPlatform(platform._plugins_dir)
    restarted.load_all()
    assert restarted.list_plugins() == []
    # Even a stale filesystem event must not reintroduce an intentionally removed installation.
    restarted.handle_filesystem_changes(["sample-plugin"], [], ["sample-plugin"])
    assert restarted.list_plugins() == []
    confirm(restarted, prepare(restarted, directory))
    assert (
        restarted.secrets.get_raw_secret("sample-plugin", "setup", "saved")
        == "retained-key"
    )
    assert restarted.repository.get_document(
        "plugin_configuration", "sample-plugin"
    ) == {"retained": "value"}
    assert (
        restarted.repository.get_host_document("sample-plugin", "schedule:sample")[
            "job_id"
        ]
        == "historical"
    )
    assert restarted.list_plugins()[0]["status"] == "disabled"


def test_optional_deletion_requires_exact_id_and_preserves_source_and_packages(
    platform,
):
    directory = source(platform.sources_directory())
    preview = prepare(platform, directory)
    confirm(platform, preview)
    platform.secrets.set_secret("sample-plugin", "setup", "saved", "retained-key")
    with pytest.raises(ValueError, match="exact plugin ID"):
        platform.uninstall_plugin(
            "sample-plugin", delete_data=True, confirmation="wrong"
        )
    assert platform.list_plugins()
    result = platform.uninstall_plugin(
        "sample-plugin", delete_data=True, confirmation="sample-plugin"
    )
    assert not result["data_retained"]
    assert result["deleted_records"] > 0
    assert not platform.secrets.get_raw_secret("sample-plugin", "setup", "saved")
    assert directory.exists()
    assert platform.package_directory(
        "sample-plugin", preview["package_digest"]
    ).exists()
    assert not platform.list_plugin_sources()[0]["data_retained"]


def test_concurrent_operations_and_preview_replay_are_rejected(platform):
    directory = source(platform.sources_directory())
    preview = prepare(platform, directory)
    other = PluginPlatform(platform._plugins_dir)
    with (
        platform.installation_lock("sample-plugin"),
        pytest.raises(installation.InstallationConflict, match="in progress"),
    ):
        confirm(other, preview)
    confirm(platform, preview)
    with pytest.raises(installation.InstallationConflict, match="used"):
        confirm(other, preview)


@pytest.mark.parametrize(
    "invalid",
    ["symlink", "missing_asset", "incompatible", "reserved", "too_many", "too_large"],
)
def test_invalid_package_leaves_no_installation(platform, invalid):
    directory = source(platform.sources_directory())
    if invalid == "symlink":
        (directory / "linked").symlink_to(directory / "data.txt")
    elif invalid == "reserved":
        (directory / "manifest.json").write_text("{}")
    elif invalid == "too_many":
        for index in range(1025):
            (directory / f"file-{index}").touch()
    elif invalid == "too_large":
        with (directory / "data.txt").open("wb") as stream:
            stream.truncate(32 * 1024 * 1024 + 1)
    else:
        declaration = yaml.safe_load((directory / "manifest.yaml").read_text())
        if invalid == "incompatible":
            declaration["usr_compatibility"] = ">=999"
        else:
            declaration["capabilities"].append("webui.extend")
            declaration["webui"] = {"entry": "missing.js"}
        (directory / "manifest.yaml").write_text(yaml.safe_dump(declaration))
    with pytest.raises(ValueError):
        prepare(platform, directory)
    assert platform.list_plugins() == []
    assert not (platform._plugins_dir / "sample-plugin").exists()


def test_source_path_escape_and_non_repository_are_rejected(platform):
    with pytest.raises(ValueError):
        platform.prepare_plugin_install({"kind": "local", "source_id": "../outside"})
    directory = source(platform.sources_directory())
    shutil.rmtree(directory / ".git")
    with pytest.raises(ValueError, match="Git operation"):
        prepare(platform, directory)


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/repo",
        "https://secret@host/repo",
        "https://user:secret@host/repo",
        "-u",
        "ext::command",
    ],
)
def test_git_url_rejects_credentials_and_other_transports(platform, url):
    with pytest.raises(ValueError, match="HTTPS or SSH"):
        platform.prepare_plugin_install({"kind": "git", "url": url})
    assert not list(platform.sources_directory().glob(".install-*"))


def test_git_acquisition_pins_revision_and_preserves_checkout(
    platform, monkeypatch, tmp_path
):
    repository = source(tmp_path / "remote")
    original = installation._git

    def local_transport(directory, *args, **kwargs):
        if args[0] == "clone":
            subprocess.run(
                ["git", "clone", "--no-checkout", str(repository), args[-1]],
                check=True,
                capture_output=True,
            )
            return ""
        return original(directory, *args, **kwargs)

    monkeypatch.setattr(installation, "_git", local_transport)
    revision = git(repository, "rev-parse", "HEAD")
    preview = platform.prepare_plugin_install(
        {
            "kind": "git",
            "url": "https://plugins.example/sample.git",
            "revision": revision,
        }
    )
    assert preview["source"]["revision"] == revision
    assert not preview["source"]["dirty"]
    confirm(platform, preview)
    checkout = platform.sources_directory() / "sample-plugin"
    assert git(checkout, "rev-parse", "HEAD") == revision
    assert not git(checkout, "status", "--porcelain")


def test_clone_failure_cleans_hidden_checkout(platform, monkeypatch):
    def fail(*_args, **_kwargs):
        raise ValueError("Git operation failed")

    monkeypatch.setattr(installation, "_git", fail)
    with pytest.raises(ValueError):
        platform.prepare_plugin_install(
            {"kind": "git", "url": "https://plugins.example/sample.git"}
        )
    assert not list(platform.sources_directory().glob(".install-*"))


def test_expired_and_modified_previews_cannot_be_installed(platform):
    directory = source(platform.sources_directory())
    preview = prepare(platform, directory)
    platform.repository.update_host_document(
        "sample-plugin",
        "install-preview:" + preview["preview_token"],
        lambda old: {**old, "expires_at": "2000-01-01T00:00:00+00:00"},
    )
    with pytest.raises(installation.InstallationConflict, match="expired"):
        confirm(platform, preview)
    preview = prepare(platform, directory)
    asset = (
        platform.package_directory("sample-plugin", preview["package_digest"])
        / "data.txt"
    )
    asset.chmod(0o644)
    asset.write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        confirm(platform, preview)
    assert not platform.list_plugins()


def test_git_filters_are_not_executed_during_local_review(platform):
    directory = source(platform.sources_directory())
    marker = directory / "filter-executed"
    (directory / ".gitattributes").write_text("data.txt filter=unsafe\n")
    git(directory, "config", "filter.unsafe.clean", f"touch {marker}")
    preview = prepare(platform, directory)
    assert preview["source"]["dirty"]
    assert not marker.exists()


def test_installation_omits_git_ignored_runtime_files(platform):
    directory = source(platform.sources_directory())
    (directory / ".gitignore").write_text("*.sqlite3\n")
    with (directory / "runtime.sqlite3").open("wb") as stream:
        stream.truncate(32 * 1024 * 1024 + 1)
    (directory / "new-module.py").write_text("# Unsaved local development file\n")
    confirm(platform, prepare(platform, directory))
    installed = platform._plugins_dir / "sample-plugin"
    assert not (installed / "runtime.sqlite3").exists()
    assert (installed / "new-module.py").is_file()


def test_git_confirmation_never_moves_an_existing_source_repository(
    platform, monkeypatch, tmp_path
):
    existing = source(platform.sources_directory())
    original_bytes = (existing / "manifest.yaml").read_bytes()
    remote = source(tmp_path / "remote")
    original = installation._git

    def local_transport(directory, *args, **kwargs):
        if args[0] == "clone":
            subprocess.run(
                ["git", "clone", "--no-checkout", str(remote), args[-1]],
                check=True,
                capture_output=True,
            )
            return ""
        return original(directory, *args, **kwargs)

    monkeypatch.setattr(installation, "_git", local_transport)
    preview = platform.prepare_plugin_install(
        {"kind": "git", "url": "https://plugins.example/sample.git"}
    )
    with pytest.raises(
        installation.InstallationConflict, match="source repository already exists"
    ):
        confirm(platform, preview)
    assert (
        existing.exists()
        and (existing / "manifest.yaml").read_bytes() == original_bytes
    )
    platform.cancel_plugin_install(preview["plugin_id"], preview["preview_token"])
    assert not list(platform.sources_directory().glob(".install-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("folder", ["USWeb", "USWebAdmin", "UltimaAI", "WebshareProxy"])
async def test_all_source_repositories_support_setup(platform, folder):
    directory = platform.sources_directory() / folder
    shutil.copytree(ROOT.parent / "USRPlugins" / folder, directory)
    preview = prepare(platform, directory)
    confirm(platform, preview)
    plugin_id = preview["plugin_id"]
    fields = platform.setup_description(plugin_id)["credentials"]
    if fields:
        with pytest.raises(ValueError, match="Required credential missing"):
            await platform.save_plugin_setup(plugin_id, {}, {}, enable=True)
    platform.approve_capabilities(plugin_id)

    async def request(*_args, **_kwargs):
        return HTTPResponse(200, b"{}")

    platform._http_request = request
    result = await platform.save_plugin_setup(
        plugin_id, {}, {field["name"]: "test-key" for field in fields}, enable=True
    )
    assert result["status"] == "enabled"
    assert result["setup_ready"]
    await platform.save_plugin_setup(
        plugin_id, {}, {field["name"]: "" for field in fields}
    )
    assert platform.setup_description(plugin_id)["ready"]


@pytest.mark.asyncio
async def test_installation_api_contract_and_admin_auth(platform, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from ultima_scraper_backend.api import app as production
    from ultima_scraper_backend.plugin_system.api_routes import _get_platform, router

    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "ultima_scraper_backend.plugin_system.api_routes.run_database_call", inline
    )
    monkeypatch.setattr(production._runtime_security, "admin_token_required", True)
    monkeypatch.setattr(
        production,
        "ensure_http_admin_auth",
        lambda request, **_kwargs: (
            None
            if request.headers.get("x-usr-admin-token") == "fixture-admin"
            else (_ for _ in ()).throw(
                production.HTTPException(401, "Admin token required")
            )
        ),
    )
    monkeypatch.setattr(
        production, "_enforce_security_rate_limits", lambda _request: None
    )
    app = FastAPI()
    app.state.plugin_platform = platform

    async def fixture_platform():
        return platform

    # This runtime's test compatibility hook also needs to avoid AnyIO's
    # helper-thread wakeup for synchronous FastAPI dependencies.
    app.dependency_overrides[_get_platform] = fixture_platform
    app.middleware("http")(production.security_http_middleware)
    app.include_router(router, prefix="/api/v1")
    directory = source(platform.sources_directory())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/plugins/sources")).status_code == 401
        client.headers["x-usr-admin-token"] = "fixture-admin"
        response = await client.get("/api/v1/plugins/sources")
        assert response.status_code == 200
        assert response.json()[0]["source_id"] == directory.name
        response = await client.post(
            "/api/v1/plugins/install/prepare",
            json={"kind": "local", "source_id": directory.name},
        )
        assert response.status_code == 200
        preview = response.json()
        assert "checkout" not in preview
        receipt = {
            "plugin_id": preview["plugin_id"],
            "preview_token": preview["preview_token"],
        }
        response = await client.post("/api/v1/plugins/install/confirm", json=receipt)
        assert response.status_code == 201
        assert response.json()["status"] == "disabled"
        response = await client.post(
            "/api/v1/plugins/install/prepare",
            json={"kind": "local", "source_id": directory.name},
        )
        assert response.status_code == 409
        # Broker credentials must not bypass administration authentication.
        client.headers.pop("x-usr-admin-token")
        client.headers["Authorization"] = (
            "Bearer " + platform.repository.issue_api_token("sample-plugin")
        )
        assert (
            await client.post("/api/v1/plugins/sample-plugin/uninstall", json={})
        ).status_code == 401
        client.headers["x-usr-admin-token"] = "fixture-admin"
        response = await client.post("/api/v1/plugins/sample-plugin/uninstall", json={})
        assert response.status_code == 200
        assert response.json()["data_retained"]
        assert (await client.get("/api/v1/plugins")).json() == []
