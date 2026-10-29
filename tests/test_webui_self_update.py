from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from ultima_webui_server import Settings, create_app
from ultima_webui_server import self_update as su
from ultima_webui_server import version as version_mod

ORIGIN = {"origin": "http://testserver"}
INDEX = "https://forge.example/api/packages/owner/pypi/simple"


def _updater(kind: su.InstallKind = "uv-tool", index: str = INDEX, uv: str | None = "/usr/bin/uv", channel=None):
    return su.SelfUpdater(su.Environment(index=index, channel=channel, uv=uv, kind=kind))


def test_versions_sort_as_pep_440_and_channels_filter_them() -> None:
    ordered = ["0.1.0.dev20261024000000", "0.1.0.dev20261025004224", "0.1.0a1", "0.1.0rc2", "0.1.0", "0.1.1.dev1"]
    assert sorted(reversed(ordered), key=su.version_key) == ordered
    assert su.version_key("0.1.0-edge.0123abcd") is None
    assert su.newest(ordered, "release") == "0.1.0"
    assert su.newest(ordered, "edge") == "0.1.1.dev1"
    assert su.is_prerelease("0.1.0.dev5") and not su.is_prerelease("0.1.0")


def test_versions_are_read_from_json_and_html_project_pages() -> None:
    page_json = (
        '{"files": [{"filename": "ultima_scraper_webui_server-0.1.0-py3-none-any.whl"},'
        ' {"filename": "ultima_scraper_webui_server-0.1.1.dev7-py3-none-any.whl"},'
        ' {"filename": "ultima_scraper_core-0.1.1.dev7-py3-none-any.whl"}]}'
    )
    page_html = (
        '<a href="/f/a#sha256=1">ultima_scraper_webui_server-0.1.0-py3-none-any.whl</a>\n'
        '<a href="/f/b#sha256=2">ultima_scraper_webui_server-0.1.1.dev7-py3-none-any.whl</a>'
    )

    assert su.versions_in_index(page_json, "application/vnd.pypi.simple.v1+json") == ["0.1.0", "0.1.1.dev7"]
    assert su.versions_in_index(page_html, "text/html") == ["0.1.0", "0.1.1.dev7"]


async def test_an_edge_install_is_offered_the_newest_build(monkeypatch: pytest.MonkeyPatch) -> None:
    updater = _updater()
    monkeypatch.setattr(su, "package_version", lambda: "0.1.0.dev20261024000000")

    async def latest(channel):
        return {"edge": "0.1.0.dev20261025004224", "release": None}[channel]

    monkeypatch.setattr(updater, "latest", latest)
    status = await updater.status()

    assert (status.channel, status.latest, status.update_available, status.can_update) == (
        "edge",
        "0.1.0.dev20261025004224",
        True,
        True,
    )
    assert status.reason is None


@pytest.mark.parametrize(
    ("updater", "reason"),
    [
        (_updater(kind="container"), "runs in a container"),
        (_updater(kind="other"), "uv tool install"),
        (_updater(index=""), "USR_WEBUI_UPDATE_INDEX"),
        (_updater(uv=None), "USR_WEBUI_UV"),
    ],
)
async def test_updates_are_only_offered_where_they_can_run(
    monkeypatch: pytest.MonkeyPatch, updater: su.SelfUpdater, reason: str
) -> None:
    monkeypatch.setattr(su, "package_version", lambda: "0.1.0")

    async def latest(channel):
        return "0.1.1"

    monkeypatch.setattr(updater, "latest", latest)
    status = await updater.status()

    assert status.can_update is False and reason in (status.reason or "")


async def test_a_release_install_ignores_dev_builds_and_an_up_to_date_one_has_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    updater = _updater()
    monkeypatch.setattr(su, "package_version", lambda: "0.1.0")
    seen: list[str] = []

    async def latest(channel):
        seen.append(channel)
        return "0.1.0"

    monkeypatch.setattr(updater, "latest", latest)
    status = await updater.status()

    assert seen == ["release"]
    assert (status.update_available, status.can_update, status.reason) == (False, False, None)


class _Process:
    def __init__(self, returncode: int, output: bytes) -> None:
        self.returncode = returncode
        self._output = output

    async def communicate(self):
        return self._output, None

    def kill(self) -> None:
        pass


async def test_update_installs_exactly_the_offered_version_then_restarts(monkeypatch: pytest.MonkeyPatch) -> None:
    updater = _updater(index="https://bot:s3cret@forge.example/api/packages/owner/pypi/simple")
    monkeypatch.setattr(su, "package_version", lambda: "0.1.0.dev1")

    async def latest(channel):
        return "0.1.0.dev2"

    monkeypatch.setattr(updater, "latest", latest)
    calls: list[tuple] = []
    envs: list[dict] = []
    restarts: list[bool] = []
    monkeypatch.setenv("SSL_CERT_FILE", "/etc/usr/ca-bundle.pem")

    async def fake_exec(*command, **kwargs):
        calls.append(command)
        envs.append(kwargs.get("env") or {})
        return _Process(0, b"Resolved from https://bot:s3cret@forge.example/api/packages/owner/pypi/simple\n")

    monkeypatch.setattr(su.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(su, "schedule_restart", lambda: restarts.append(True))

    result = await updater.update()

    [command] = calls
    assert command[:4] == ("/usr/bin/uv", "tool", "install", "--force")
    assert command[command.index("--index") + 1] == updater.environment.index
    assert command[-1] == "ultima-scraper-webui-server==0.1.0.dev2"
    assert (result.version, result.restarting, restarts) == ("0.1.0.dev2", True, [True])
    assert "s3cret" not in result.log
    # uv uses the system store and the configured bundle, as a private index needs.
    assert envs[0]["UV_SYSTEM_CERTS"] == "1" and envs[0]["SSL_CERT_FILE"] == "/etc/usr/ca-bundle.pem"


async def test_a_failed_install_does_not_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    updater = _updater()
    monkeypatch.setattr(su, "package_version", lambda: "0.1.0.dev1")

    async def latest(channel):
        return "0.1.0.dev2"

    async def fake_exec(*command, **kwargs):
        return _Process(1, b"No solution found")

    restarts: list[bool] = []
    monkeypatch.setattr(updater, "latest", latest)
    monkeypatch.setattr(su.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(su, "schedule_restart", lambda: restarts.append(True))

    with pytest.raises(HTTPException) as failure:
        await updater.update()
    assert failure.value.status_code == 502 and "No solution found" in failure.value.detail
    assert restarts == []

    monkeypatch.setattr(su, "package_version", lambda: "0.1.0.dev2")
    with pytest.raises(HTTPException) as nothing:
        await updater.update()
    assert nothing.value.status_code == 400


def test_the_routes_need_a_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", static_dir=tmp_path))
    client = TestClient(app, client=("127.0.0.1", 50000))
    assert client.get("/webui/api/v1/self").status_code == 401
    assert client.post("/webui/api/v1/self/update", headers=ORIGIN).status_code == 401

    assert client.post("/webui/api/v1/session/claim", json={"password": "a-long-password"}, headers=ORIGIN).status_code == 204
    updater = app.state.self_updater
    updater.environment = su.Environment(index="", channel=None, uv=None, kind="other")
    monkeypatch.setattr(su, "package_version", lambda: "0.1.0")
    status = client.get("/webui/api/v1/self").json()
    assert status["version"] == "0.1.0" and status["can_update"] is False
    assert client.post("/webui/api/v1/self/update", headers=ORIGIN).status_code == 400


def test_a_published_package_reports_the_image_built_with_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("USR_WEBUI_VERSION", raising=False)
    build = types.ModuleType("ultima_webui_server._build")
    build.IMAGE_VERSION = "0.1.0-edge.0123abcd4567"
    monkeypatch.setitem(sys.modules, "ultima_webui_server._build", build)
    assert version_mod.own_version() == "0.1.0-edge.0123abcd4567"

    monkeypatch.setenv("USR_WEBUI_VERSION", "0.1.0")
    assert version_mod.own_version() == "0.1.0"


def test_index_credentials_never_show() -> None:
    assert su.redact_url("https://bot:tok@forge.example:3000/simple") == "https://***@forge.example:3000/simple"
    assert su.redact_url(INDEX) == INDEX
