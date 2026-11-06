from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import socket
import sys
import time
import traceback
from collections.abc import Callable
from http.client import HTTPConnection
from multiprocessing.connection import Connection
from multiprocessing.context import BaseContext
from multiprocessing.process import BaseProcess
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING, Any, Final, cast
from urllib.parse import quote

from ultima_scraper_core import load_env, runtime_env_value

load_env()

if TYPE_CHECKING:
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    from ultima_webui_server.launcher import ViteDevServer, WebUIServer

logger = logging.getLogger(__name__)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent
os.environ.setdefault("USR_REPOSITORY_ROOT", str(PROJECT_ROOT))
VALID_RUN_MODES: Final[set[str]] = {"webui", "api", "worker"}
CONTROL_HEALTH_PATH: Final[str] = "/api/v1/admin/health"
DEFAULT_CONTROL_STARTUP_TIMEOUT: Final[float] = 120.0
CONTROL_HEALTH_POLL_INTERVAL: Final[float] = 0.25
SUPERVISOR_POLL_INTERVAL: Final[float] = 0.5
WORKER_POOL_SERVICE_INTERVAL: Final[float] = 0.25
# Long-running services get time to finish their own graceful shutdown (the
# worker pool alone may spend ~25s stopping workers and its job service).
GRACEFUL_STOP_TIMEOUT: Final[float] = 30.0
# Raised by the plugin supervisor when its database schema is not migrated.
PLUGIN_SCHEMA_EXIT_CODE: Final[int] = 78
# How often a worker runtime on a new installation rechecks for completed setup.
SETUP_WAIT_POLL_INTERVAL: Final[float] = 5.0
# Children inherit this so the control plane can signal the launcher itself.
SUPERVISOR_PID_ENV: Final[str] = "ULTIMA_SUPERVISOR_PID"
# SIGUSR1 asks the launcher to stop every service, then start again in place.
RESTART_SIGNAL: Final[signal.Signals | None] = getattr(signal, "SIGUSR1", None)
PLUGIN_FAILURE_CHANNELS: Final[tuple[str, str]] = (
    "_plugin_failure_receiver",
    "_plugin_failure_sender",
)

_config: UltimaScraperCollectionConfig | None = None


def run_control() -> None:
    """Import the ASGI control plane only inside its dedicated process."""

    os.environ["ULTIMA_DATABASE_PROCESS_ROLE"] = "application"
    from ultima_scraper_backend.api.app import run_control as run_control_process

    run_control_process()


def database_writer_main() -> None:
    """Import the database writer only inside its dedicated process."""

    os.environ["ULTIMA_DATABASE_PROCESS_ROLE"] = "writer"
    from ultima_scraper_backend.database.writer_runtime import (
        database_writer_main as run_database_writer,
    )

    run_database_writer()


def ledger_archiver_main() -> None:
    """Archive passes in their own process (ULTIMA_ARCHIVE_PROCESS=1)."""

    os.environ["ULTIMA_DATABASE_PROCESS_ROLE"] = "application"
    from ultima_scraper_backend.job_system.archiver_process import (
        ledger_archiver_main as run_ledger_archiver,
    )

    run_ledger_archiver()


def start_ledger_archiver(context: BaseContext) -> list[tuple[str, BaseProcess]]:
    """Start the archiver process when enabled; the control plane then skips its loops."""
    from ultima_scraper_backend.job_system.ledger_runtime import archive_process_enabled

    if not archive_process_enabled():
        return []
    return [("ledger archiver", start_process(context, ledger_archiver_main, "ledger-archiver", "ledger archiver"))]


def database_writer_process_count() -> int:
    """ULTIMA_DATABASE_WRITER_PROCESSES; each writer owns a share of the queue."""
    raw = runtime_env_value("ULTIMA_DATABASE_WRITER_PROCESSES")
    if raw is None or not str(raw).strip():
        return 1
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise ValueError("ULTIMA_DATABASE_WRITER_PROCESSES must be a positive integer")
    return value


def start_database_writers(
    context: BaseContext,
) -> list[tuple[str, BaseProcess]]:
    count = database_writer_process_count()
    writers: list[tuple[str, BaseProcess]] = []
    try:
        for index in range(count):
            suffix = "" if count == 1 else f"-{index + 1}"
            name = f"database writer{suffix.replace('-', ' ')}"
            writers.append(
                (
                    name,
                    start_process(
                        context, database_writer_main, f"database-writer{suffix}", name
                    ),
                )
            )
    except BaseException:
        stop_database_writers(writers)
        raise
    return writers


def stop_database_writers(writers: list[tuple[str, BaseProcess]]) -> None:
    for name, process in writers:
        terminate_process(process, name, timeout=GRACEFUL_STOP_TIMEOUT)


def plugin_supervisor_main() -> None:
    from ultima_scraper_backend.plugin_system.supervisor import main as run_plugins

    run_plugins()


def _run_plugin_process(target: Callable[[], None], failure_sender: Connection) -> None:
    """Keep spawned service failures visible to the launcher and its log."""
    try:
        configure_runtime_logging("plugin supervisor")
        target()
    except BaseException as exc:
        if not isinstance(exc, SystemExit) or exc.code not in (None, 0):
            from ultima_scraper_backend.plugin_system.recovery import error_summary

            cause = exc.__cause__ if isinstance(exc, SystemExit) else exc
            cause = cause or exc
            summary = error_summary(cause)
            try:
                failure_sender.send(summary)
            except BrokenPipeError, EOFError, OSError:
                pass
            stack = "\n".join(
                f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}'
                for frame in traceback.extract_tb(cause.__traceback__)
            )
            logger.error("Plugin supervisor failed: %s\n%s", summary, stack)
        if isinstance(exc, SystemExit):
            raise
        raise SystemExit(1) from None
    finally:
        failure_sender.close()


def _read_runtime_power_command(pid: int | None = None) -> dict[str, Any] | None:
    import json
    import tempfile

    pid = pid or os.getpid()
    command_path = Path(tempfile.gettempdir()) / f"ultimascraper_power_command_{pid}.json"
    if not command_path.is_file():
        return None
    try:
        data = json.loads(command_path.read_text())
        return data if isinstance(data, dict) else None
    except Exception:
        return None
    finally:
        try:
            command_path.unlink(missing_ok=True)
        except OSError:
            pass


class ShutdownRequest:
    """Records SIGTERM/SIGINT/SIGUSR1 so supervisor loops can exit and clean up."""

    def __init__(self) -> None:
        self.requested = False
        self.restart = False
        self.selective_restart_requested = False
        self.targets: list[str] | None = None

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        if RESTART_SIGNAL is not None and signum == RESTART_SIGNAL:
            cmd = _read_runtime_power_command(os.getpid())
            targets = (
                [str(t) for t in cmd["targets"]]
                if cmd and isinstance(cmd.get("targets"), list)
                else None
            )
            if targets and "api" not in targets and "all" not in targets:
                self.selective_restart_requested = True
                self.targets = targets
                return
            self.requested = True
            self.restart = True
            self.targets = targets
            return

        self.requested = True
        self.restart = False
        self.selective_restart_requested = False
        self.targets = None

    @classmethod
    def install(cls) -> ShutdownRequest:
        shutdown = cls()
        signal.signal(signal.SIGTERM, shutdown._handle_signal)
        signal.signal(signal.SIGINT, shutdown._handle_signal)
        if RESTART_SIGNAL is not None:
            signal.signal(RESTART_SIGNAL, shutdown._handle_signal)
        return shutdown


def get_config() -> UltimaScraperCollectionConfig:
    global _config
    if _config is None:
        from ultima_scraper_backend.config import UltimaScraperCollectionConfig

        _config = UltimaScraperCollectionConfig.load_or_create_default_config()
    return _config


def configure_runtime_logging(run_mode: str) -> None:
    from ultima_scraper_backend.logging_utils import (
        configure_runtime_logging as configure,
    )

    configure(run_mode)


def _run_service_process(target: Callable[[], None], name: str) -> None:
    configure_runtime_logging(name)
    try:
        target()
    except BaseException as exc:
        if not isinstance(exc, KeyboardInterrupt) and (
            not isinstance(exc, SystemExit) or exc.code not in (None, 0)
        ):
            logger.critical("Service %s failed", name, exc_info=True)
        raise


def normalize_run_mode(value: str | None) -> str:
    run_mode = (value or "webui").strip().lower()
    if run_mode not in VALID_RUN_MODES:
        choices = ", ".join(sorted(VALID_RUN_MODES))
        raise ValueError(f"Invalid RUN_MODE={run_mode!r}; expected one of: {choices}")
    return run_mode


def apply_runtime_environment(run_mode: str) -> None:
    control_host = runtime_env_value("CONTROL_HOST") or "127.0.0.1"
    configured_control_port = int(runtime_env_value("CONTROL_PORT") or "21121")
    control_port = (
        resolve_available_port(control_host, configured_control_port)
        if run_mode == "webui"
        else configured_control_port
    )

    os.environ["RUN_MODE"] = run_mode
    os.environ["CONTROL_HOST"] = control_host
    os.environ["CONTROL_PORT"] = str(control_port)


def build_redis_url(config: UltimaScraperCollectionConfig) -> str:
    redis_config = config.settings.redis
    if redis_config.password:
        return (
            f"redis://:{quote(redis_config.password, safe='')}@"
            f"{redis_config.host}:{redis_config.port}/{redis_config.db}"
        )
    return f"redis://{redis_config.host}:{redis_config.port}/{redis_config.db}"


def resolve_available_port(host: str, preferred_port: int) -> int:
    candidate_hosts = [host]
    if host in {"0.0.0.0", "::"}:
        candidate_hosts.insert(0, "127.0.0.1")

    try:
        for candidate_host in candidate_hosts:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind((candidate_host, preferred_port))
                except OSError:
                    continue
                return preferred_port

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            bind_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
            sock.bind((bind_host, 0))
            return int(sock.getsockname()[1])
    except PermissionError:
        logger.debug(
            "Skipping port availability probe for %s:%s due to socket permissions",
            host,
            preferred_port,
        )
        return preferred_port


def get_positive_float_environment(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = None
    # ``not value > 0`` also rejects NaN, which would disable the deadline.
    if value is None or not value > 0:
        logger.warning("Invalid %s=%r; using %.1f", name, raw, default)
        return default
    return value


def get_control_probe_host(host: str) -> str:
    if host == "0.0.0.0":
        return "127.0.0.1"
    if host == "::":
        return "::1"
    return host


def control_plane_is_healthy(host: str, port: int, timeout: float = 1.0) -> bool:
    connection = HTTPConnection(get_control_probe_host(host), port, timeout=timeout)
    try:
        connection.request("GET", CONTROL_HEALTH_PATH)
        response = connection.getresponse()
        response.read()
        return response.status == 200
    except OSError, TimeoutError:
        return False
    finally:
        connection.close()


def describe_process_exit(name: str, process: BaseProcess) -> str:
    exitcode = process.exitcode
    if name == "plugin supervisor" and exitcode == PLUGIN_SCHEMA_EXIT_CODE:
        return "plugin supervisor cannot start: plugin database schema is missing or incompatible. Apply plugin migration d2a70c16f493 through the database migration workflow, then restart (exit code 78)"
    if exitcode is None:
        return f"{name} is not running (exit code unavailable)"
    if exitcode < 0:
        try:
            signal_name = signal.Signals(-exitcode).name
        except ValueError:
            signal_name = f"signal {-exitcode}"
        return f"{name} exited unexpectedly via {signal_name} (exit code {exitcode})"
    description = f"{name} exited unexpectedly (exit code {exitcode})"
    failure_receiver = getattr(process, "_plugin_failure_receiver", None)
    if failure_receiver is not None:
        try:
            if failure_receiver.poll():
                cast(Any, process)._plugin_failure_detail = failure_receiver.recv()
        except EOFError, OSError:
            pass
        detail = getattr(process, "_plugin_failure_detail", None)
        if detail:
            description += f": {detail}"
    return description


def wait_for_control_plane(
    process: BaseProcess,
    host: str,
    port: int,
    *,
    timeout: float,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    probe_host = get_control_probe_host(host)
    deadline = time.monotonic() + timeout
    logger.info(
        "Waiting up to %.1fs for backend control plane at http://%s:%s%s",
        timeout,
        probe_host,
        port,
        CONTROL_HEALTH_PATH,
    )

    while True:
        if should_stop is not None and should_stop():
            return False
        if not process.is_alive():
            raise RuntimeError(describe_process_exit("backend control plane", process))

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Backend control plane did not become healthy within {timeout:.1f}s"
            )

        if control_plane_is_healthy(host, port, timeout=min(1.0, remaining)):
            logger.info("Backend control plane is healthy")
            return True

        time.sleep(min(CONTROL_HEALTH_POLL_INTERVAL, remaining))


def ensure_critical_processes_alive(
    processes: list[tuple[str, BaseProcess | None]],
) -> None:
    for name, process in processes:
        if process is not None and not process.is_alive():
            raise RuntimeError(describe_process_exit(name, process))


def supervise_processes(
    processes: list[tuple[str, BaseProcess | None]],
    shutdown: ShutdownRequest,
    on_selective_restart: Callable[[list[str]], None] | None = None,
) -> None:
    """Block until shutdown is requested; fail fast when a child exits."""
    while not shutdown.requested:
        if shutdown.selective_restart_requested:
            targets = shutdown.targets or []
            shutdown.selective_restart_requested = False
            shutdown.targets = None
            if on_selective_restart is not None:
                on_selective_restart(targets)
        ensure_critical_processes_alive(processes)
        time.sleep(SUPERVISOR_POLL_INTERVAL)


def worker_pool_main() -> None:
    os.environ["ULTIMA_DATABASE_PROCESS_ROLE"] = "worker_reader"
    from ultima_scraper_backend.workers.worker_pool import WorkerPool

    config = get_config()
    pool = WorkerPool(
        num_workers=config.settings.worker_pool.size,
        redis_url=build_redis_url(config),
        backend_id=config.settings.get_backend_id(),
    )

    shutdown = ShutdownRequest.install()
    try:
        pool.start()
        while not shutdown.requested:
            pool.service_runtime()
            time.sleep(WORKER_POOL_SERVICE_INTERVAL)
    finally:
        pool.stop()


def get_process_context() -> BaseContext:
    # SQLAlchemy engines, Redis pools, event loops, and HTTP clients are not
    # fork-safe.  Spawn gives every service a clean ownership boundary on all
    # platforms instead of copying live connection pools into every worker.
    return multiprocessing.get_context("spawn")


def create_process(
    context: BaseContext, target: Callable[[], None], name: str
) -> BaseProcess:
    """Create a child process with a typed boundary around multiprocessing context."""
    context_runtime = cast(Any, context)
    if name == "plugin-supervisor":
        receiver, sender = context_runtime.Pipe(duplex=False)
        process = context_runtime.Process(
            target=_run_plugin_process, args=(target, sender), name=name
        )
        process._plugin_failure_receiver = receiver
        process._plugin_failure_sender = sender
        return cast(BaseProcess, process)
    return cast(BaseProcess, context_runtime.Process(
        target=_run_service_process, args=(target, name), name=name,
    ))


def start_process(
    context: BaseContext, target: Callable[[], None], name: str, description: str
) -> BaseProcess:
    process = create_process(context, target, name)
    try:
        process.start()
    except BaseException:
        _close_plugin_failure_channel(process)
        raise
    logger.info("Started %s (PID %s)", description, process.pid)
    return process


def terminate_process(
    process: BaseProcess | None, name: str, timeout: float = 5
) -> None:
    if process is None:
        return
    popen = getattr(process, "_popen", None)
    if popen is None:
        logger.debug("Skipping %s shutdown because the process never started", name)
        _close_plugin_failure_channel(process)
        return
    if not process.is_alive():
        process.join(timeout=0.1)
        _close_plugin_failure_channel(process)
        return

    logger.info("Stopping %s (PID %s)", name, process.pid)
    # Listed before the stop: once the parent is gone its children are
    # reparented and can no longer be found from it.
    children = _child_processes(process.pid)
    process.terminate()
    process.join(timeout=timeout)
    if process.is_alive():
        logger.warning("%s did not exit cleanly; killing PID %s", name, process.pid)
        process.kill()
        process.join(timeout=timeout)
    _stop_leftover_children(name, children, timeout)
    _close_plugin_failure_channel(process)


def _child_processes(pid: int | None) -> list[Any]:
    """Every process started under pid, e.g. the control plane's API workers."""
    import psutil

    try:
        return psutil.Process(pid).children(recursive=True) if pid else []
    except psutil.Error:
        return []


def _stop_leftover_children(name: str, children: list[Any], timeout: float) -> None:
    """Stop children that outlived their parent.

    A killed parent leaves them running unsupervised, and a restart cannot
    exec until they exit, because they still hold the resource tracker's pipe.
    """
    import psutil

    alive = [child for child in children if child.is_running()]
    if not alive:
        return
    logger.warning(
        "%s left %d process(es) running; stopping %s",
        name,
        len(alive),
        ", ".join(str(child.pid) for child in alive),
    )
    for child in alive:
        try:
            child.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(alive, timeout=timeout)
    for child in alive:
        try:
            child.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=timeout)


def _close_plugin_failure_channel(process: BaseProcess) -> None:
    for name in PLUGIN_FAILURE_CHANNELS:
        channel = getattr(process, name, None)
        if channel is not None:
            channel.close()


def restart_in_place() -> None:
    """Replace this launcher with a fresh copy once every child has stopped.

    exec keeps the PID, environment and log redirection, so service managers
    and shells that started the launcher keep supervising the new runtime.
    """
    from multiprocessing import resource_tracker

    logger.info("Restarting UltimaScraper runtime")
    # exec closes the tracker's pipe, so it would exit as a zombie the new
    # image never reaps. Stop and reap it while this image still owns it.
    stop_tracker = getattr(getattr(resource_tracker, "_resource_tracker", None), "_stop", None)
    if stop_tracker is not None:
        stop_tracker()
    logging.shutdown()
    os.execv(sys.executable, [sys.executable, *sys.orig_argv[1:]])


def wait_for_first_time_setup(shutdown: ShutdownRequest) -> bool:
    """Hold the worker runtime until setup has created the schema and config.

    The WebUI setup wizard migrates a new database, so before that the
    writers and plugin supervisor cannot start. Meanwhile the Docker probe
    sees a live worker that expects no scrape workers. Returns False when
    shutdown was requested while waiting.
    """
    from ultima_scraper_backend.workers.readiness import WorkerReadiness
    from ultima_scraper_db_archive.global_db import get_global_engine, is_setup_complete

    if is_setup_complete():
        return True
    logger.info(
        "Waiting for first-time setup in the WebUI (or for the database) before starting workers"
    )
    readiness = WorkerReadiness(os.environ.get("USR_WORKER_READINESS_FILE"))
    backend_id = runtime_env_value("BACKEND_ID") or socket.gethostname()
    while not shutdown.requested:
        readiness.publish(backend_id, 0, [])
        time.sleep(SETUP_WAIT_POLL_INTERVAL)
        if is_setup_complete():
            # The launcher only supervises from here; release its connection.
            get_global_engine().dispose()
            logger.info("First-time setup is complete; starting workers")
            return True
    readiness.close()
    return False


def verify_cluster_secret_key() -> None:
    """Refuse to start with a USR_SECRET_KEY the rest of the cluster doesn't use.

    Backends and workers sharing one database read each other's encrypted
    secrets. Before setup has created the schema there is nothing to check;
    setup checks the key once it has migrated the database.
    """
    from ultima_scraper_db_archive.global_db import get_global_engine, is_setup_complete
    from ultima_scraper_db_archive.secret_key_check import (
        SecretKeyMismatch,
        verify_secret_key_for_engine,
    )

    if not is_setup_complete():
        return
    engine = get_global_engine()
    try:
        verify_secret_key_for_engine(engine)
    except SecretKeyMismatch as exc:
        logger.error("%s", exc)
        raise SystemExit(str(exc)) from None
    finally:
        # The launcher only supervises from here; release its connection.
        engine.dispose()


def run_worker_runtime() -> ShutdownRequest:
    """Supervise the writer, worker pool and plugins without a control plane."""
    logger.info("Starting explicit worker-only runtime")
    shutdown = ShutdownRequest.install()
    if not wait_for_first_time_setup(shutdown):
        return shutdown
    verify_cluster_secret_key()
    process_context = get_process_context()
    writers: list[tuple[str, BaseProcess]] = []
    worker_process: BaseProcess | None = None
    plugin_process: BaseProcess | None = None
    try:
        writers = start_database_writers(process_context)
        worker_process = start_process(
            process_context, worker_pool_main, "worker-pool", "worker pool"
        )
        plugin_process = start_process(
            process_context,
            plugin_supervisor_main,
            "plugin-supervisor",
            "plugin supervisor",
        )
        worker_processes: list[tuple[str, BaseProcess | None]] = [
            *writers,
            ("worker pool", worker_process),
            ("plugin supervisor", plugin_process),
        ]

        def handle_worker_selective_restart(targets: list[str]) -> None:
            nonlocal worker_process, plugin_process, writers
            logger.info("Performing worker targeted restart for services: %s", ", ".join(targets))
            if "worker_pool" in targets and worker_process is not None:
                terminate_process(worker_process, "worker pool", timeout=GRACEFUL_STOP_TIMEOUT)
                worker_process = start_process(process_context, worker_pool_main, "worker-pool", "worker pool")
            if "plugins" in targets and plugin_process is not None:
                terminate_process(plugin_process, "plugin supervisor", timeout=GRACEFUL_STOP_TIMEOUT)
                plugin_process = start_process(process_context, plugin_supervisor_main, "plugin-supervisor", "plugin supervisor")
            if "database_writer" in targets:
                stop_database_writers(writers)
                writers = start_database_writers(process_context)
            worker_processes[:] = [
                *writers,
                ("worker pool", worker_process),
                ("plugin supervisor", plugin_process),
            ]

        supervise_processes(
            worker_processes,
            shutdown,
            on_selective_restart=handle_worker_selective_restart,
        )
    except KeyboardInterrupt:
        logger.info("Worker runtime shutdown requested from keyboard interrupt")
    finally:
        for process, name in (
            (plugin_process, "plugin supervisor"),
            (worker_process, "worker pool"),
        ):
            terminate_process(process, name, timeout=GRACEFUL_STOP_TIMEOUT)
        stop_database_writers(writers)
    return shutdown


_FALSE = {"0", "false", "no", "off"}


class NativeWebUI:
    """The WebUI server in front of the backend, and the Vite dev server."""

    def __init__(self, server: WebUIServer | None, dev: ViteDevServer | None) -> None:
        self.server = server
        self.dev = dev

    def stop(self) -> None:
        if self.dev is not None:
            self.dev.stop()
        if self.server is not None:
            self.server.stop()


def start_webui() -> NativeWebUI:
    """Start the WebUI on its public port (USR_WEBUI_PORT, 21120 by default).

    In a source checkout with npm (unless USR_WEBUI_DEV=false) the Vite dev
    server takes that port and goes through the WebUI server; otherwise the
    WebUI server serves the built app there itself. Without the WebUI server
    there is no WebUI: the page never talks to the backend directly.
    """
    try:
        from ultima_webui_server.launcher import ViteDevServer, WebUIServer
    except ImportError as exc:
        raise RuntimeError(
            "The WebUI server package is not installed. In a source checkout run "
            "`uv sync`; otherwise use the Docker release, or start with RUN_MODE=api."
        ) from exc
    runtime = NativeWebUI(None, None)
    try:
        with_dev_server = (
            (runtime_env_value("USR_WEBUI_DEV") or "").strip().lower() not in _FALSE
            and ViteDevServer.available(PROJECT_ROOT)
        )
        server = WebUIServer(PROJECT_ROOT, behind_dev_server=with_dev_server)
        if not server.start():
            logger.error("The WebUI is unavailable; backend services are still running")
            return runtime
        runtime.server = server
        if not with_dev_server:
            return runtime
        dev = ViteDevServer(PROJECT_ROOT, server_url=server.url)
        if not dev.start():
            logger.error(
                "The WebUI dev server did not start (is port %s free?); "
                "backend services are still running",
                runtime_env_value("USR_WEBUI_PORT") or 21120,
            )
            # Nothing reaches the server's private port without the dev server.
            runtime.stop()
            runtime.server = None
            return runtime
        runtime.dev = dev
        if webui_url := dev.wait_for_url(timeout=15):
            logger.info("WebUI available at %s", webui_url)
        else:
            logger.warning("WebUI started but no URL was detected from Vite output")
    except BaseException:
        # The caller never receives this instance, so it cannot stop it.
        runtime.stop()
        raise
    return runtime


def main() -> ShutdownRequest:
    """Run until a signal arrives; the result says whether to restart."""
    run_mode = normalize_run_mode(runtime_env_value("RUN_MODE"))
    configure_runtime_logging(run_mode)

    # API and worker supervisors only manage child processes. Their children
    # load canonical settings after selecting their own database process role.
    config = get_config() if run_mode == "webui" else None
    apply_runtime_environment(run_mode)

    if run_mode == "worker":
        return run_worker_runtime()

    verify_cluster_secret_key()

    shutdown = ShutdownRequest.install()
    os.environ[SUPERVISOR_PID_ENV] = str(os.getpid())
    control_process: BaseProcess | None = None
    database_writers: list[tuple[str, BaseProcess]] = []
    archiver_processes: list[tuple[str, BaseProcess]] = []
    worker_pool_process: BaseProcess | None = None
    plugin_supervisor_process: BaseProcess | None = None
    webui: NativeWebUI | None = None
    process_context = get_process_context()

    try:
        database_writers = start_database_writers(process_context)
        archiver_processes = start_ledger_archiver(process_context)
        control_process = start_process(
            process_context, run_control, "ultima-control", "backend control plane"
        )

        control_startup_timeout = get_positive_float_environment(
            "CONTROL_STARTUP_TIMEOUT",
            DEFAULT_CONTROL_STARTUP_TIMEOUT,
        )
        control_ready = wait_for_control_plane(
            control_process,
            os.environ["CONTROL_HOST"],
            int(os.environ["CONTROL_PORT"]),
            timeout=control_startup_timeout,
            should_stop=lambda: shutdown.requested,
        )
        if not control_ready:
            logger.info("Shutdown requested while waiting for backend control plane")
            return shutdown

        if run_mode == "webui":
            plugin_supervisor_process = start_process(
                process_context,
                plugin_supervisor_main,
                "plugin-supervisor",
                "plugin supervisor",
            )

        ensure_critical_processes_alive(
            [
                ("backend control plane", control_process),
                *database_writers,
            ]
        )

        if config is not None and config.settings.worker_pool.enabled:
            worker_pool_process = start_process(
                process_context, worker_pool_main, "worker-pool", "worker pool"
            )
        elif run_mode != "api":
            logger.info("Worker pool disabled in config")

        if run_mode == "webui":
            webui = start_webui()

        processes_to_watch: list[tuple[str, BaseProcess | None]] = [
            ("backend control plane", control_process),
            ("worker pool", worker_pool_process),
            *database_writers,
            *archiver_processes,
            ("plugin supervisor", plugin_supervisor_process),
        ]

        def handle_selective_restart(targets: list[str]) -> None:
            nonlocal worker_pool_process, plugin_supervisor_process, database_writers, webui
            logger.info("Performing targeted restart for services: %s", ", ".join(targets))
            if "worker_pool" in targets and worker_pool_process is not None:
                terminate_process(worker_pool_process, "worker pool", timeout=GRACEFUL_STOP_TIMEOUT)
                worker_pool_process = start_process(
                    process_context, worker_pool_main, "worker-pool", "worker pool"
                )
            if "plugins" in targets and plugin_supervisor_process is not None:
                terminate_process(plugin_supervisor_process, "plugin supervisor", timeout=GRACEFUL_STOP_TIMEOUT)
                plugin_supervisor_process = start_process(
                    process_context, plugin_supervisor_main, "plugin-supervisor", "plugin supervisor"
                )
            if "database_writer" in targets:
                stop_database_writers(database_writers)
                database_writers = start_database_writers(process_context)
            if "webui" in targets and webui is not None:
                webui.stop()
                webui = start_webui()
            processes_to_watch[:] = [
                ("backend control plane", control_process),
                ("worker pool", worker_pool_process),
                *database_writers,
                *archiver_processes,
                ("plugin supervisor", plugin_supervisor_process),
            ]

        logger.info("Runtime started in %s mode", run_mode)
        supervise_processes(
            processes_to_watch,
            shutdown,
            on_selective_restart=handle_selective_restart,
        )
    except KeyboardInterrupt:
        logger.info("Shutdown requested from keyboard interrupt")
    finally:
        if webui is not None:
            webui.stop()
        terminate_process(
            plugin_supervisor_process,
            "plugin supervisor",
            timeout=GRACEFUL_STOP_TIMEOUT,
        )
        terminate_process(
            worker_pool_process, "worker pool", timeout=GRACEFUL_STOP_TIMEOUT
        )
        terminate_process(control_process, "backend control plane")
        for name, process in archiver_processes:
            terminate_process(process, name, timeout=GRACEFUL_STOP_TIMEOUT)
        stop_database_writers(database_writers)
    return shutdown


def run_launcher() -> None:
    if main().restart:
        restart_in_place()


def run_ticket_command(args: list[str]) -> int:
    """Print a shareable connection ticket for this backend."""
    from ultima_webui_server.tickets import create_ticket

    name = (runtime_env_value("BACKEND_ID") or "").strip() or socket.gethostname()

    public_url = (runtime_env_value("USR_PUBLIC_API_URL") or "").strip()
    if not public_url:
        host = (runtime_env_value("CONTROL_HOST") or "").strip() or "0.0.0.0"
        if host in ("0.0.0.0", "::"):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                host = s.getsockname()[0]
                s.close()
            except Exception:
                host = socket.gethostname()
        port = (runtime_env_value("CONTROL_PORT") or "").strip() or "21121"
        public_url = f"http://{host}:{port}"

    token = (runtime_env_value("USR_ADMIN_TOKEN") or "").strip()
    if not token:
        token_file = (runtime_env_value("USR_ADMIN_TOKEN_FILE") or "").strip()
        if token_file and Path(token_file).is_file():
            token = Path(token_file).read_text(encoding="utf-8").strip()
        else:
            candidates = [
                Path(runtime_env_value("USR_CONFIG_DIR") or "/home/ultimascraper/.config/ultima_scraper_verse") / "secrets" / "USR_ADMIN_TOKEN",
                Path.home() / ".config" / "ultima_scraper_verse" / "secrets" / "USR_ADMIN_TOKEN",
            ]
            for candidate in candidates:
                if candidate.is_file():
                    token = candidate.read_text(encoding="utf-8").strip()
                    if token:
                        break

    ticket = create_ticket(
        name=name,
        base_url=public_url,
        token=token or None,
        tls_verify=True,
    )

    print("=" * 72)
    print("UltimaScraper Connection Ticket:")
    print()
    print(ticket)
    print()
    print(f"Backend Name: {name}")
    print(f"Address:      {public_url}")
    print(f"Token:        {'[Included]' if token else '[None/Unauthenticated]'}")
    print()
    print("Paste this ticket into the WebUI's 'Add a backend' screen.")
    print("=" * 72)
    return 0


def cli_main() -> None:
    """Start the installed distribution in API mode by default."""
    if len(sys.argv) > 1 and sys.argv[1] in ("ticket", "ticket-gen"):
        sys.exit(run_ticket_command(sys.argv[2:]))
    os.environ.setdefault("RUN_MODE", "api")
    run_launcher()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("ticket", "ticket-gen"):
        sys.exit(run_ticket_command(sys.argv[2:]))
    run_launcher()
