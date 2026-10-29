from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import main as runtime_main


def test_importing_launcher_does_not_load_scraper_or_database_stack() -> None:
    code = """
import importlib.abc
import sys
import time

sys.path[:] = PATHS

class RuntimeImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.', 1)[0] in {
            'ultima_scraper_backend', 'ultima_scraper_api',
            'ultima_scraper_db_archive', 'sqlalchemy', 'sqlmodel',
        }:
            raise AssertionError(f'Launcher imported runtime dependency {fullname}')

sys.meta_path.insert(0, RuntimeImportGuard())
import main
assert main.normalize_run_mode('worker') == 'worker'
""".replace("PATHS", repr(sys.path))
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", code],
        cwd=Path(runtime_main.__file__).parent,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@dataclass
class FakeProcess:
    alive: bool = True
    exitcode: int | None = None

    def is_alive(self) -> bool:
        return self.alive


def test_control_probe_uses_loopback_for_wildcard_bind() -> None:
    assert runtime_main.get_control_probe_host("0.0.0.0") == "127.0.0.1"
    assert runtime_main.get_control_probe_host("::") == "::1"
    assert runtime_main.get_control_probe_host("192.0.2.10") == "192.0.2.10"


def test_wait_for_control_plane_waits_until_health_check_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = iter([False, False, True])
    monkeypatch.setattr(
        runtime_main,
        "control_plane_is_healthy",
        lambda *_args, **_kwargs: next(checks),
    )
    monkeypatch.setattr(runtime_main.time, "sleep", lambda _seconds: None)

    assert runtime_main.wait_for_control_plane(
        FakeProcess(),  # type: ignore[arg-type]
        "127.0.0.1",
        21121,
        timeout=10.0,
    )


def test_wait_for_control_plane_reports_child_signal() -> None:
    process = FakeProcess(alive=False, exitcode=-9)

    with pytest.raises(RuntimeError, match=r"SIGKILL.*exit code -9"):
        runtime_main.wait_for_control_plane(
            process,  # type: ignore[arg-type]
            "127.0.0.1",
            21121,
            timeout=10.0,
        )


def test_wait_for_control_plane_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_main,
        "control_plane_is_healthy",
        lambda *_args, **_kwargs: False,
    )

    with pytest.raises(TimeoutError, match="did not become healthy"):
        runtime_main.wait_for_control_plane(
            FakeProcess(),  # type: ignore[arg-type]
            "127.0.0.1",
            21121,
            timeout=0.0,
        )


def test_critical_process_monitor_reports_clean_exit() -> None:
    process = FakeProcess(alive=False, exitcode=0)

    with pytest.raises(RuntimeError, match=r"worker pool.*exit code 0"):
        runtime_main.ensure_critical_processes_alive(
            [("worker pool", process)],  # type: ignore[list-item]
        )


def test_plugin_schema_failure_reports_the_required_migration() -> None:
    with pytest.raises(
        RuntimeError, match=r"schema is missing.*d2a70c16f493.*exit code 78"
    ):
        runtime_main.ensure_critical_processes_alive(
            [("plugin supervisor", FakeProcess(alive=False, exitcode=78))],
        )


def _fail_plugin_child() -> None:
    from sqlalchemy.exc import OperationalError

    raise OperationalError(
        "SELECT :secret",
        {"secret": "private-credential"},
        RuntimeError("database connection was closed"),
    )


def test_spawned_plugin_failure_reaches_launcher_and_runtime_log(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("USR_LOG_DIR", str(tmp_path))
    process = runtime_main.create_process(
        runtime_main.get_process_context(), _fail_plugin_child, "plugin-supervisor"
    )
    try:
        process.start()
        process.join(timeout=20)
        assert not process.is_alive()
        assert process.exitcode == 1
        with pytest.raises(
            RuntimeError, match="OperationalError: database connection was closed"
        ):
            runtime_main.ensure_critical_processes_alive(
                [("plugin supervisor", process)]
            )
        # Repeated inspection retains the consumed IPC error.
        assert "database connection was closed" in runtime_main.describe_process_exit(
            "plugin supervisor", process
        )
        log = "".join(path.read_text() for path in tmp_path.glob("errors-*.log"))
        assert "_fail_plugin_child" in log
        assert "database connection was closed" in log
        assert "private-credential" not in log
    finally:
        runtime_main.terminate_process(process, "plugin supervisor")
        process._plugin_failure_receiver.close()
        process._plugin_failure_sender.close()


@pytest.mark.parametrize("service", ["database-writer", "worker-pool", "ultima-control"])
def test_every_launcher_service_persists_fatal_failures(monkeypatch, tmp_path, service):
    monkeypatch.setenv("USR_LOG_DIR", str(tmp_path))
    process = runtime_main.create_process(
        runtime_main.get_process_context(), _fail_plugin_child, service,
    )
    try:
        process.start()
        process.join(timeout=15)
        assert not process.is_alive() and process.exitcode == 1
        files = list(tmp_path.glob("errors-*.log"))
        assert len(files) == 1
        content = files[0].read_text()
        assert f"service={service}" in content
        assert "database connection was closed" in content and "_fail_plugin_child" in content
        assert "private-credential" not in content
    finally:
        runtime_main.terminate_process(process, service)


@pytest.mark.parametrize(
    ("run_mode", "expected_events"),
    [
        (
            "api",
            [
                "start:database-writer",
                "start:ultima-control",
                "healthy:ultima-control",
            ],
        ),
        (
            "webui",
            [
                "start:database-writer",
                "start:ultima-control",
                "healthy:ultima-control",
                "start:plugin-supervisor",
                "start:worker-pool",
            ],
        ),
        (
            "worker",
            ["start:database-writer", "start:worker-pool", "start:plugin-supervisor"],
        ),
    ],
)
def test_main_obeys_runtime_process_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    run_mode: str,
    expected_events: list[str],
) -> None:
    events: list[str] = []

    class LaunchProcess(FakeProcess):
        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name
            self.pid = len(events) + 100

        def start(self) -> None:
            events.append(f"start:{self.name}")

    config = SimpleNamespace(
        settings=SimpleNamespace(
            worker_pool=SimpleNamespace(enabled=True),
        )
    )

    def launcher_config():
        assert run_mode == "webui", (
            "Only the WebUI launcher consumes application config"
        )
        return config

    def apply_environment(run_mode: str) -> None:
        monkeypatch.setenv("RUN_MODE", run_mode)
        monkeypatch.setenv("CONTROL_HOST", "127.0.0.1")
        monkeypatch.setenv("CONTROL_PORT", "21121")

    def create_process(_context, _target, name: str) -> LaunchProcess:
        return LaunchProcess(name)

    def wait_for_control(*_args, **_kwargs) -> bool:
        events.append("healthy:ultima-control")
        return True

    def controlled_sleep(seconds: float) -> None:
        if seconds == 0.5:
            raise KeyboardInterrupt

    class FakeWebUI:
        @staticmethod
        def available(_project_root) -> bool:
            return True

        def __init__(self, _project_root, server_url: str) -> None:
            pass

        def start(self) -> bool:
            return False

        def stop(self) -> None:
            pass

    class AbsentServer(_FakeServer):
        starts = False

    _install_ui_module(monkeypatch, FakeWebUI, AbsentServer)

    monkeypatch.setenv("RUN_MODE", run_mode)
    monkeypatch.setattr(runtime_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_main, "configure_runtime_logging", lambda _mode: None)
    monkeypatch.setattr(runtime_main, "get_config", launcher_config)
    monkeypatch.setattr(runtime_main, "apply_runtime_environment", apply_environment)
    monkeypatch.setattr(runtime_main, "get_process_context", object)
    monkeypatch.setattr(runtime_main, "create_process", create_process)
    monkeypatch.setattr(runtime_main, "wait_for_control_plane", wait_for_control)
    monkeypatch.setattr(
        runtime_main,
        "worker_pool_main",
        lambda: events.append("worker-pool:foreground"),
    )
    monkeypatch.setattr(
        runtime_main,
        "terminate_process",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(runtime_main.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(runtime_main.time, "sleep", controlled_sleep)
    monkeypatch.setattr(runtime_main, "wait_for_first_time_setup", lambda _shutdown: True)
    runtime_main.main()

    assert events == expected_events


def test_invalid_run_mode_fails_closed() -> None:
    with pytest.raises(ValueError, match="Invalid RUN_MODE"):
        runtime_main.normalize_run_mode("surprise-worker-mode")


def test_legacy_backend_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid RUN_MODE"):
        runtime_main.normalize_run_mode("backend")


def test_api_runtime_keeps_configured_control_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTROL_PORT", "21121")
    monkeypatch.setattr(
        runtime_main,
        "resolve_available_port",
        lambda *_args: pytest.fail("API mode must not select a different port"),
    )

    runtime_main.apply_runtime_environment("api")

    assert runtime_main.os.environ["CONTROL_PORT"] == "21121"


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "nan"])
def test_invalid_positive_float_environment_uses_default(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("CONTROL_STARTUP_TIMEOUT", raw)

    assert (
        runtime_main.get_positive_float_environment("CONTROL_STARTUP_TIMEOUT", 7.0)
        == 7.0
    )


def test_positive_float_environment_accepts_valid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTROL_STARTUP_TIMEOUT", "2.5")

    assert (
        runtime_main.get_positive_float_environment("CONTROL_STARTUP_TIMEOUT", 7.0)
        == 2.5
    )


def test_shutdown_request_records_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    handlers = {}
    monkeypatch.setattr(
        runtime_main.signal,
        "signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )

    shutdown = runtime_main.ShutdownRequest.install()

    assert not shutdown.requested
    handlers[runtime_main.signal.SIGTERM](runtime_main.signal.SIGTERM, None)
    assert shutdown.requested
    assert not shutdown.restart
    assert set(handlers) == {
        runtime_main.signal.SIGTERM,
        runtime_main.signal.SIGINT,
        runtime_main.signal.SIGUSR1,
    }


def test_restart_signal_requests_restart_until_a_stop_signal_follows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers = {}
    monkeypatch.setattr(
        runtime_main.signal,
        "signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )
    shutdown = runtime_main.ShutdownRequest.install()

    handlers[runtime_main.signal.SIGUSR1](runtime_main.signal.SIGUSR1, None)
    assert shutdown.requested and shutdown.restart
    handlers[runtime_main.signal.SIGTERM](runtime_main.signal.SIGTERM, None)
    assert shutdown.requested and not shutdown.restart


def test_selective_restart_request_flags_targets_without_stopping_supervisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers = {}
    monkeypatch.setattr(
        runtime_main.signal,
        "signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )
    monkeypatch.setattr(
        runtime_main,
        "_read_runtime_power_command",
        lambda pid=None: {"action": "restart", "targets": ["worker_pool", "plugins"]},
    )
    shutdown = runtime_main.ShutdownRequest.install()

    handlers[runtime_main.signal.SIGUSR1](runtime_main.signal.SIGUSR1, None)
    assert not shutdown.requested
    assert shutdown.selective_restart_requested
    assert shutdown.targets == ["worker_pool", "plugins"]


def test_supervise_processes_invokes_selective_restart_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown = runtime_main.ShutdownRequest()
    shutdown.selective_restart_requested = True
    shutdown.targets = ["worker_pool"]

    restarted: list[list[str]] = []
    def on_restart(targets: list[str]) -> None:
        restarted.append(targets)
        shutdown.requested = True

    runtime_main.supervise_processes([], shutdown, on_selective_restart=on_restart)
    assert restarted == [["worker_pool"]]
    assert not shutdown.selective_restart_requested


@pytest.mark.parametrize("restart", [True, False])
def test_launcher_execs_itself_only_after_a_restart_request(
    monkeypatch: pytest.MonkeyPatch, restart: bool
) -> None:
    shutdown = runtime_main.ShutdownRequest()
    shutdown.requested, shutdown.restart = True, restart
    execs = []
    monkeypatch.setattr(runtime_main, "main", lambda: shutdown)
    monkeypatch.setattr(runtime_main.sys, "orig_argv", ["python", "-u", "main.py"])
    monkeypatch.setattr(runtime_main.os, "execv", lambda path, argv: execs.append((path, argv)))

    runtime_main.run_launcher()

    expected = [(runtime_main.sys.executable, [runtime_main.sys.executable, "-u", "main.py"])]
    assert execs == (expected if restart else [])


def test_failed_start_closes_plugin_failure_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []

    class Channel:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            closed.append(self.name)

    class UnstartableProcess:
        _plugin_failure_receiver = Channel("receiver")
        _plugin_failure_sender = Channel("sender")

        def start(self) -> None:
            raise OSError("spawn failed")

    monkeypatch.setattr(
        runtime_main, "create_process", lambda *_args: UnstartableProcess()
    )

    with pytest.raises(OSError, match="spawn failed"):
        runtime_main.start_process(
            object(),  # type: ignore[arg-type]
            lambda: None,
            "plugin-supervisor",
            "plugin supervisor",
        )
    assert closed == ["receiver", "sender"]


def test_worker_runtime_stops_started_children_when_one_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminated: list[str] = []

    class ExitedProcess(FakeProcess):
        pid = 1

        def start(self) -> None:
            pass

    processes = {
        "database-writer": ExitedProcess(),
        "worker-pool": ExitedProcess(alive=False, exitcode=3),
        "plugin-supervisor": ExitedProcess(),
    }
    monkeypatch.setattr(runtime_main.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(runtime_main, "get_process_context", object)
    monkeypatch.setattr(runtime_main, "wait_for_first_time_setup", lambda _shutdown: True)
    monkeypatch.setattr(
        runtime_main, "create_process", lambda _context, _target, name: processes[name]
    )
    monkeypatch.setattr(
        runtime_main,
        "terminate_process",
        lambda _process, name, **_kwargs: terminated.append(name),
    )

    with pytest.raises(RuntimeError, match=r"worker pool exited.*exit code 3"):
        runtime_main.run_worker_runtime()
    assert terminated == ["plugin supervisor", "worker pool", "database writer"]


def test_webui_prefers_local_vite_url_over_later_network_url(tmp_path) -> None:
    from ultima_webui_server.launcher import ViteDevServer

    webui = ViteDevServer(tmp_path, server_url="http://127.0.0.1:41234")
    process = SimpleNamespace(
        stdout=iter(
            [
                "  VITE ready\n",
                "  ➜  Local:   http://localhost:21120/\n",
                "  ➜  Network: http://192.0.2.10:21120/\n",
            ]
        )
    )

    webui._read_stdout(process)  # type: ignore[arg-type]

    assert webui.url == "http://localhost:21120/"


def test_webui_falls_back_to_network_vite_url(tmp_path) -> None:
    from ultima_webui_server.launcher import ViteDevServer

    webui = ViteDevServer(tmp_path, server_url="http://127.0.0.1:41234")
    process = SimpleNamespace(stdout=iter(["  ➜  Network: http://192.0.2.10:21120/\n"]))

    webui._read_stdout(process)  # type: ignore[arg-type]

    assert webui.url == "http://192.0.2.10:21120/"
    assert webui.wait_for_url(timeout=0) == "http://192.0.2.10:21120/"


class _FakeServer:
    """A WebUI server that starts unless told otherwise."""

    starts = True
    url = "http://127.0.0.1:41234"
    created: list[bool] = []

    def __init__(self, _project_root, *, behind_dev_server: bool) -> None:
        self.behind_dev_server = behind_dev_server
        self.stopped = False
        type(self).created.append(behind_dev_server)

    def start(self) -> bool:
        return self.starts

    def stop(self) -> None:
        self.stopped = True


def _install_ui_module(monkeypatch: pytest.MonkeyPatch, webui_class, server_class) -> None:
    launcher = ModuleType("ultima_webui_server.launcher")
    launcher.ViteDevServer = webui_class  # type: ignore[attr-defined]
    launcher.WebUIServer = server_class  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ultima_webui_server.launcher", launcher)


@pytest.mark.parametrize(
    ("dev_available", "dev_setting", "server_starts", "expected_server", "expected_dev"),
    [
        # Source checkout: Vite owns the public port, the server sits behind it.
        (True, None, True, [True], ["http://127.0.0.1:41234"]),
        # No dev server: the WebUI server serves the built app on the public port.
        (False, None, True, [False], []),
        (True, "false", True, [False], []),
        # No WebUI server, no WebUI: never a page that talks to the backend itself.
        (True, None, False, [True], []),
    ],
)
def test_start_webui_always_goes_through_the_webui_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    dev_available: bool,
    dev_setting: str | None,
    server_starts: bool,
    expected_server: list[bool],
    expected_dev: list[str],
) -> None:
    dev_targets: list[str] = []

    class DevServer:
        @staticmethod
        def available(_project_root) -> bool:
            return dev_available

        def __init__(self, _project_root, server_url: str) -> None:
            dev_targets.append(server_url)

        def start(self) -> bool:
            return True

        def wait_for_url(self, timeout: float) -> str | None:
            return "http://localhost:21120/"

        def stop(self) -> None:
            pass

    class Server(_FakeServer):
        starts = server_starts
        created: list[bool] = []

    _install_ui_module(monkeypatch, DevServer, Server)
    monkeypatch.setattr(runtime_main, "PROJECT_ROOT", tmp_path)
    if dev_setting is None:
        monkeypatch.delenv("USR_WEBUI_DEV", raising=False)
    else:
        monkeypatch.setenv("USR_WEBUI_DEV", dev_setting)

    runtime = runtime_main.start_webui()

    assert Server.created == expected_server
    assert dev_targets == expected_dev
    assert (runtime.server is not None) is server_starts
    runtime.stop()


def test_webui_server_sits_on_loopback_behind_the_dev_server(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from ultima_webui_server.launcher import WebUIServer

    monkeypatch.setenv("USR_ADMIN_TOKEN", "native-admin-token")
    monkeypatch.setenv("CONTROL_HOST", "0.0.0.0")
    monkeypatch.setenv("CONTROL_PORT", "8111")
    monkeypatch.setenv("USR_ALLOW_REMOTE_BIND", "true")
    monkeypatch.delenv("USR_WEBUI_HOST", raising=False)
    monkeypatch.delenv("USR_WEBUI_PORT", raising=False)

    behind = WebUIServer(tmp_path, behind_dev_server=True)
    environment = behind.child_environment()

    # Only the dev server reaches it, and its X-Forwarded-For is believed.
    assert behind.host == "127.0.0.1" and behind.port != 21120
    assert environment["USR_WEBUI_TRUSTED_PROXIES"] == "127.0.0.1"
    assert environment["USR_WEBUI_DEFAULT_BACKEND_URL"] == "http://127.0.0.1:8111"
    assert environment["USR_WEBUI_DEFAULT_BACKEND_TOKEN"] == "native-admin-token"
    assert environment["USR_WEBUI_STATIC_DIR"] == str(
        tmp_path / "src" / "UltimaScraperWeb" / "webui" / "dist"
    )

    # Without a dev server it takes the public port itself and trusts no proxy.
    monkeypatch.setenv("USR_WEBUI_TRUSTED_PROXIES", "10.0.0.1")
    alone = WebUIServer(tmp_path, behind_dev_server=False)
    assert (alone.host, alone.port, alone.url) == ("0.0.0.0", 21120, "http://127.0.0.1:21120")
    assert "USR_WEBUI_TRUSTED_PROXIES" not in alone.child_environment()
    monkeypatch.setenv("USR_WEBUI_PORT", "8090")
    assert WebUIServer(tmp_path, behind_dev_server=False).port == 8090


def test_webui_server_leaves_a_busy_port_alone(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from ultima_webui_server import launcher as server_module

    monkeypatch.setattr(server_module.WebUIServer, "_healthy", lambda self: True)
    monkeypatch.setattr(
        server_module.subprocess, "Popen", lambda *a, **k: pytest.fail("must not start a second server")
    )

    assert server_module.WebUIServer(tmp_path, behind_dev_server=False).start() is False


def test_dev_server_holds_no_token_and_keeps_its_port(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from ultima_webui_server import launcher as webui_module

    (tmp_path / "src" / "UltimaScraperWeb" / "webui").mkdir(parents=True)
    captured: dict = {}

    class Process:
        pid = 1
        stdout = iter(())

        def __init__(self, command, *args, env, **kwargs) -> None:
            captured.update(command=command, env=env)

        def poll(self):
            return None

    monkeypatch.setattr(webui_module.shutil, "which", lambda _name: "/usr/bin/npm")
    monkeypatch.setattr(webui_module.subprocess, "Popen", Process)
    monkeypatch.setattr(webui_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("USR_ADMIN_TOKEN", "native-admin-token")
    monkeypatch.delenv("USR_WEBUI_PORT", raising=False)

    assert webui_module.ViteDevServer(tmp_path, server_url="http://127.0.0.1:41234").start()

    assert captured["env"]["USR_WEBUI_SERVER_URL"] == "http://127.0.0.1:41234"
    assert "native-admin-token" not in captured["env"].get("VITE_USR_ADMIN_TOKEN", "")
    # A taken 21120 is an error, not a second WebUI on 5174.
    assert captured["command"][-3:] == ["--port", "21120", "--strictPort"]
    # Wrapped so a hard-killed runtime takes Vite with it.
    assert "npm" in captured["command"][captured["command"].index("run") - 1]


def test_start_webui_stops_dev_server_when_interrupted(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    stopped: list[bool] = []

    class InterruptedWebUI:
        @staticmethod
        def available(_project_root) -> bool:
            return True

        def __init__(self, _project_root, server_url: str) -> None:
            pass

        def start(self) -> bool:
            return True

        def wait_for_url(self, timeout: float) -> str | None:
            raise KeyboardInterrupt

        def stop(self) -> None:
            stopped.append(True)

    _install_ui_module(monkeypatch, InterruptedWebUI, _FakeServer)
    monkeypatch.setattr(runtime_main, "PROJECT_ROOT", tmp_path)

    with pytest.raises(KeyboardInterrupt):
        runtime_main.start_webui()
    assert stopped == [True]


def test_webui_runtime_gives_services_the_graceful_stop_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The worker pool needs the same shutdown window in every launch mode."""
    timeouts: dict[str, float | None] = {}

    class LaunchProcess(FakeProcess):
        pid = 100

        def start(self) -> None:
            pass

    config = SimpleNamespace(
        settings=SimpleNamespace(worker_pool=SimpleNamespace(enabled=True))
    )

    def apply_environment(run_mode: str) -> None:
        monkeypatch.setenv("CONTROL_HOST", "127.0.0.1")
        monkeypatch.setenv("CONTROL_PORT", "21121")

    def stop_runtime(seconds: float) -> None:
        if seconds == runtime_main.SUPERVISOR_POLL_INTERVAL:
            raise KeyboardInterrupt

    class FakeWebUI:
        @staticmethod
        def available(_project_root) -> bool:
            return True

        def __init__(self, _project_root, server_url: str) -> None:
            pass

        def start(self) -> bool:
            return False

        def stop(self) -> None:
            pass

    _install_ui_module(monkeypatch, FakeWebUI, _FakeServer)
    monkeypatch.setenv("RUN_MODE", "webui")
    monkeypatch.setattr(runtime_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_main, "configure_runtime_logging", lambda _mode: None)
    monkeypatch.setattr(runtime_main, "get_config", lambda: config)
    monkeypatch.setattr(runtime_main, "apply_runtime_environment", apply_environment)
    monkeypatch.setattr(runtime_main, "get_process_context", object)
    monkeypatch.setattr(
        runtime_main, "create_process", lambda _context, _target, _name: LaunchProcess()
    )
    monkeypatch.setattr(runtime_main, "wait_for_control_plane", lambda *_a, **_k: True)
    monkeypatch.setattr(
        runtime_main,
        "terminate_process",
        lambda _process, name, timeout=None: timeouts.__setitem__(name, timeout),
    )
    monkeypatch.setattr(runtime_main.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(runtime_main.time, "sleep", stop_runtime)

    runtime_main.main()

    graceful = runtime_main.GRACEFUL_STOP_TIMEOUT
    assert timeouts == {
        "plugin supervisor": graceful,
        "worker pool": graceful,
        "backend control plane": None,
        "database writer": graceful,
    }


def _worker_healthcheck_module() -> ModuleType:
    import importlib.util

    path = Path(runtime_main.__file__).parent / "docker" / "worker-healthcheck.py"
    spec = importlib.util.spec_from_file_location("usr_worker_healthcheck", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch_setup_state(monkeypatch: pytest.MonkeyPatch, states: list[bool]) -> list[str]:
    from ultima_scraper_db_archive import global_db

    disposed: list[str] = []
    monkeypatch.setattr(global_db, "is_setup_complete", lambda: states.pop(0))
    monkeypatch.setattr(
        global_db,
        "get_global_engine",
        lambda: SimpleNamespace(dispose=lambda: disposed.append("engine")),
    )
    return disposed


def test_worker_starts_at_once_when_setup_is_complete(monkeypatch, tmp_path) -> None:
    readiness_file = tmp_path / "readiness.json"
    monkeypatch.setenv("USR_WORKER_READINESS_FILE", str(readiness_file))
    _patch_setup_state(monkeypatch, [True])

    assert runtime_main.wait_for_first_time_setup(runtime_main.ShutdownRequest())
    assert not readiness_file.exists()


def test_worker_waits_for_setup_while_reporting_healthy(monkeypatch, tmp_path) -> None:
    readiness_file = tmp_path / "readiness.json"
    monkeypatch.setenv("USR_WORKER_READINESS_FILE", str(readiness_file))
    monkeypatch.setenv("BACKEND_ID", "usr-docker")
    disposed = _patch_setup_state(monkeypatch, [False, False, True])
    healthcheck = _worker_healthcheck_module()
    probes: list[dict] = []

    def sleep(_seconds: float) -> None:
        readiness = healthcheck._read_readiness()
        probes.append(readiness)
        assert healthcheck._active_worker_count.__name__  # probe is importable
        assert readiness["expected_workers"] == 0 and readiness["worker_ids"] == []

    monkeypatch.setattr(runtime_main.time, "sleep", sleep)

    assert runtime_main.wait_for_first_time_setup(runtime_main.ShutdownRequest())
    assert len(probes) == 2
    assert probes[0]["backend_id"] == "usr-docker"
    assert disposed == ["engine"]


def test_worker_stops_while_waiting_for_setup(monkeypatch, tmp_path) -> None:
    readiness_file = tmp_path / "readiness.json"
    monkeypatch.setenv("USR_WORKER_READINESS_FILE", str(readiness_file))
    _patch_setup_state(monkeypatch, [False, False])
    shutdown = runtime_main.ShutdownRequest()

    def sleep(_seconds: float) -> None:
        shutdown.requested = True

    monkeypatch.setattr(runtime_main.time, "sleep", sleep)
    monkeypatch.setattr(runtime_main.ShutdownRequest, "install", classmethod(lambda cls: shutdown))
    monkeypatch.setattr(
        runtime_main,
        "start_database_writers",
        lambda _context: pytest.fail("writers started before setup"),
    )

    assert runtime_main.run_worker_runtime() is shutdown
    assert not readiness_file.exists()


def _stubborn_parent(child_pid_file: str) -> None:
    """Starts a child, then ignores SIGTERM like a parent stuck waiting for it."""
    import signal as signals

    child = subprocess.Popen(["sleep", "60"])
    Path(child_pid_file).write_text(str(child.pid))
    signals.signal(signals.SIGTERM, signals.SIG_IGN)
    child.wait()


def test_stopping_a_stuck_process_also_stops_its_children(tmp_path) -> None:
    """A killed control plane must not leave its API workers running: a
    restart cannot exec while they hold the resource tracker's pipe."""
    import multiprocessing as mp

    import psutil

    pid_file = tmp_path / "child.pid"
    process = mp.get_context("fork").Process(target=_stubborn_parent, args=(str(pid_file),))
    process.start()
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            break
        time.sleep(0.05)
    child_pid = int(pid_file.read_text())

    runtime_main.terminate_process(process, "stubborn parent", timeout=0.5)

    assert not process.is_alive()
    assert not psutil.pid_exists(child_pid) or psutil.Process(child_pid).status() == psutil.STATUS_ZOMBIE


def test_webui_children_end_with_the_runtime_that_started_them(tmp_path) -> None:
    """A debugger's hard stop kills main.py without its cleanup; Vite and the
    WebUI server must not keep the port afterwards."""
    import psutil

    from ultima_webui_server.launcher import exits_with_this_process

    if not sys.platform.startswith("linux"):
        pytest.skip("parent-death signals are Linux-only")
    pid_file = tmp_path / "child.pid"
    # A stand-in runtime that starts a long-running child the way the launcher
    # does, then is killed without any cleanup.
    runtime = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess, sys, time\n"
            "from ultima_webui_server.launcher import exits_with_this_process\n"
            "child = subprocess.Popen(exits_with_this_process(['sleep', '60']))\n"
            f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
            "time.sleep(60)\n",
        ],
        cwd=Path(runtime_main.__file__).parent,
    )
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text():
            break
        time.sleep(0.05)
    child = psutil.Process(int(pid_file.read_text()))
    for _ in range(100):
        if child.cmdline()[:1] == ["sleep"]:
            break
        time.sleep(0.02)
    assert child.cmdline()[0] == "sleep"  # the wrapper exec'd into the command

    runtime.kill()
    runtime.wait()

    gone, _ = psutil.wait_procs([child], timeout=5)
    assert gone, "the child outlived the runtime that started it"
    wrapped = exits_with_this_process(["vite"])
    assert wrapped[-1] == "vite"
    assert "python" not in Path(wrapped[0]).name.lower()
