"""Runs the WebUI next to a native backend, for main.py.

The WebUI is reached on one port, 21120 by default (USR_WEBUI_PORT):

- In a source checkout with npm, ViteDevServer listens there and sends
  sign-in, /b/{connection} and backend traffic to the WebUI server, which
  then listens on a private loopback port.
- Otherwise WebUIServer listens there itself and serves the built app
  (src/UltimaScraperWeb/webui/dist).

Either way the WebUI server adds the backend's admin token; the page never
holds one. Both run as child processes that end with the runtime.

This module imports only the standard library and ultima_scraper_core, so the
launcher stays light; the server itself runs in its own process.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path

from ultima_scraper_core import runtime_env_value

logger = logging.getLogger(__name__)

DEFAULT_PORT = 21120
_LOOPBACK = "127.0.0.1"
_STARTUP_TIMEOUT = 20.0
_TRUE = {"1", "true", "yes", "on"}
WEBUI_REL_DIR = Path("src", "UltimaScraperWeb", "webui")


_TLS_SETTINGS = ("USR_WEBUI_TLS", "USR_WEBUI_TLS_CERT_FILE", "USR_WEBUI_TLS_KEY_FILE", "USR_WEBUI_TLS_HOSTNAMES")


def tls_settings() -> dict[str, str]:
    """The HTTPS settings from the runtime environment (USR_WEBUI_TLS*)."""
    return {name: value for name in _TLS_SETTINGS if (value := (runtime_env_value(name) or "").strip())}


def resolve_tls() -> tuple[Path, Path] | None:
    """The certificate and key the public port serves; creates a self-signed one if asked."""
    from .config import default_data_dir
    from .tls import fingerprint, tls_files

    settings = tls_settings()
    if not settings:
        return None
    data_dir = Path(runtime_env_value("USR_WEBUI_DATA_DIR") or default_data_dir())
    files = tls_files(data_dir, settings)
    if files is None:
        return None
    if files.self_signed:
        logger.warning(
            "The WebUI uses a self-signed certificate (%s). Browsers ask you to trust it once; "
            "check its SHA-256 fingerprint first: %s",
            files.cert_file,
            fingerprint(files.cert_file),
        )
    return files.cert_file, files.key_file


def remote_bind_enabled() -> bool:
    return (runtime_env_value("USR_ALLOW_REMOTE_BIND") or "").strip().lower() in _TRUE


def public_port() -> int:
    """The port the WebUI is opened on."""
    return int(runtime_env_value("USR_WEBUI_PORT") or DEFAULT_PORT)


def public_host() -> str:
    return runtime_env_value("USR_WEBUI_HOST") or ("0.0.0.0" if remote_bind_enabled() else _LOOPBACK)


# Run before the real command: on Linux, ask for SIGTERM when the runtime that
# started us dies (a debugger's hard stop, say), then exec the command. Without
# it a killed runtime leaves the WebUI holding its port. Set in the child, so
# no preexec_fn runs in the multi-threaded runtime.
_EXIT_WITH_PARENT = (
    "import ctypes, os, signal, sys\n"
    "parent = int(sys.argv[1])\n"
    "ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)\n"
    "if os.getppid() != parent:\n"
    "    sys.exit(0)\n"
    "os.execvp(sys.argv[2], sys.argv[2:])\n"
)


def exits_with_this_process(command: list[str]) -> list[str]:
    """command, wrapped so it ends when this process ends (Linux only)."""
    if not sys.platform.startswith("linux"):
        return command
    env_bin = shutil.which("env") or "/usr/bin/env"
    return [env_bin, sys.executable, "-S", "-c", _EXIT_WITH_PARENT, str(os.getpid()), *command]


def _reachable_host(host: str) -> str:
    """Where this machine reaches a server bound to host."""
    if host in {"", "0.0.0.0"}:
        return _LOOPBACK
    if host == "::":
        return "::1"
    return host


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _free_loopback_port() -> int:
    with socket.socket() as probe:
        probe.bind((_LOOPBACK, 0))
        return probe.getsockname()[1]


class WebUIServer:
    """A child process; start() returns False, and logs why, when it cannot run.

    behind_dev_server: the Vite dev server owns the public port and forwards
    to this server on a private loopback port, trusting its X-Forwarded-For.
    """

    def __init__(self, project_root: Path, *, behind_dev_server: bool) -> None:
        self._project_root = project_root
        self._process: subprocess.Popen[bytes] | None = None
        self.behind_dev_server = behind_dev_server
        if behind_dev_server:
            self.host, self.port = _LOOPBACK, _free_loopback_port()
        else:
            self.host, self.port = public_host(), public_port()
        # Behind the dev server, it terminates HTTPS; this hop stays on loopback.
        self.tls = {} if behind_dev_server else tls_settings()

    @property
    def url(self) -> str:
        """The address this machine reaches the server at."""
        scheme = "https" if self.tls else "http"
        return f"{scheme}://{_url_host(_reachable_host(self.host))}:{self.port}"

    @property
    def static_dir(self) -> Path:
        return self._project_root / WEBUI_REL_DIR / "dist"

    def child_environment(self) -> dict[str, str]:
        control_host = _reachable_host(os.environ.get("CONTROL_HOST") or _LOOPBACK)
        control_port = os.environ.get("CONTROL_PORT") or "21121"
        environment = os.environ.copy()
        environment.update(
            {
                "USR_WEBUI_HOST": self.host,
                "USR_WEBUI_PORT": str(self.port),
                "USR_WEBUI_STATIC_DIR": str(self.static_dir),
                "USR_WEBUI_DEFAULT_BACKEND_URL": f"http://{_url_host(control_host)}:{control_port}",
                "USR_WEBUI_DEFAULT_BACKEND_TOKEN": runtime_env_value("USR_ADMIN_TOKEN") or "",
            }
        )
        for name in _TLS_SETTINGS:
            environment.pop(name, None)
        environment.update(self.tls)
        if self.behind_dev_server:
            # Only the dev server can reach this loopback port; its
            # X-Forwarded-For names the browser, which decides who is local.
            environment["USR_WEBUI_TRUSTED_PROXIES"] = _LOOPBACK
        else:
            environment.pop("USR_WEBUI_TRUSTED_PROXIES", None)
        return environment

    def _healthy(self) -> bool:
        if self.tls:
            # Its own certificate may be self-signed; only the answer matters here.
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            connection: HTTPConnection = HTTPSConnection(
                _reachable_host(self.host), self.port, timeout=2, context=context
            )
        else:
            connection = HTTPConnection(_reachable_host(self.host), self.port, timeout=2)
        try:
            connection.request("GET", "/health")
            return connection.getresponse().status == 200
        except OSError:
            return False
        finally:
            connection.close()

    def _port_hint(self) -> str:
        if self.behind_dev_server:
            return ""
        return f" Is port {self.port} free? Set USR_WEBUI_PORT to use another."

    def start(self) -> bool:
        if self._process is not None:
            return True
        if self._healthy():
            logger.error(
                "Port %s already has a WebUI on it (another UltimaScraper runtime?), "
                "so this one did not start.%s",
                self.port,
                self._port_hint(),
            )
            return False
        try:
            process = subprocess.Popen(
                exits_with_this_process([sys.executable, "-m", "ultima_webui_server"]),
                cwd=self._project_root,
                env=self.child_environment(),
                start_new_session=os.name == "posix",
            )
        except OSError:
            logger.exception("Could not start the WebUI server")
            return False
        deadline = time.monotonic() + _STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if process.poll() is not None:
                logger.error(
                    "The WebUI server exited during startup (code %s).%s",
                    process.returncode,
                    self._port_hint(),
                )
                return False
            if self._healthy():
                self._process = process
                if not self.behind_dev_server:
                    if not (self.static_dir / "index.html").is_file():
                        logger.warning(
                            "The WebUI is not built, so %s shows only a notice. Build it with: "
                            "npm --prefix src/UltimaScraperWeb/webui ci && "
                            "npm --prefix src/UltimaScraperWeb/webui run build:production",
                            self.url,
                        )
                    logger.info("WebUI available at %s", self.url)
                return True
            time.sleep(0.25)
        logger.error("The WebUI server did not answer within %.0f seconds", _STARTUP_TIMEOUT)
        self._process = process
        self.stop()
        return False

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


_VITE_URL_RE = re.compile(r"Local:\s+(https?://\S+)")
_VITE_NETWORK_URL_RE = re.compile(r"Network:\s+(https?://\S+)")
_DEFAULT_VITE_HOST = "127.0.0.1"


class ViteDevServer:
    """The Vite dev server, on the WebUI's public port (21120 by default).

    Everything but the app's own files goes through the WebUI server at
    server_url: sign-in, /b/{connection} routes and backend traffic.
    """

    def __init__(self, project_root: Path, server_url: str) -> None:
        self._project_root = project_root
        self._server_url = server_url
        self._process: subprocess.Popen[str] | None = None
        self._url: str | None = None
        self._host = _DEFAULT_VITE_HOST
        self._port = public_port()
        self._url_event = threading.Event()

    @property
    def url(self) -> str | None:
        """The local URL the WebUI dev server is listening on."""
        return self._url

    def wait_for_url(self, timeout: float = 15.0) -> str | None:
        """Block until the dev server prints its URL or *timeout* expires."""
        self._url_event.wait(timeout=timeout)
        if self._url is None and self._process is not None and self._process.poll() is None:
            host = "localhost" if self._host == "0.0.0.0" else self._host
            self._url = f"http://{host}:{self._port}"
            self._url_event.set()
        return self._url

    def _read_stdout(self, process: subprocess.Popen[str]) -> None:
        """Background thread: read Vite stdout and capture the local URL."""
        assert process.stdout is not None  # noqa: S101
        for line in process.stdout:
            logger.debug("WebUI: %s", line.rstrip())
            if match := _VITE_URL_RE.search(line):
                self._url = match.group(1)
            elif self._url is None and (match := _VITE_NETWORK_URL_RE.search(line)):
                # Use the Network URL only when no Local URL has been printed.
                self._url = match.group(1)
            else:
                continue
            self._url_event.set()

    @staticmethod
    def _candidate_hosts(remote_bind: bool) -> list[str]:
        if not remote_bind:
            return [_DEFAULT_VITE_HOST]
        return ["0.0.0.0", _LOOPBACK]

    @staticmethod
    def available(project_root: Path) -> bool:
        """A source checkout with its node modules installed, and npm."""
        return (project_root / WEBUI_REL_DIR / "node_modules").is_dir() and shutil.which("npm") is not None

    def start(self) -> bool:
        """Start the WebUI dev server if available."""
        if self._process is not None:
            return True

        webui_dir = self._project_root / WEBUI_REL_DIR
        if not webui_dir.is_dir():
            logger.warning("WebUI directory not found: %s", webui_dir)
            return False

        remote_bind = remote_bind_enabled()

        child_env = os.environ.copy()
        if remote_bind:
            child_env["USR_ALLOW_REMOTE_BIND"] = "true"
        child_env["USR_WEBUI_SERVER_URL"] = self._server_url
        for name in _TLS_SETTINGS:
            child_env.pop(name, None)
        # The dev server owns the public port, so it serves HTTPS when asked.
        if tls := resolve_tls():
            child_env["USR_WEBUI_TLS_CERT_FILE"], child_env["USR_WEBUI_TLS_KEY_FILE"] = map(str, tls)

        npm = shutil.which("npm")
        if npm is None:
            logger.warning("npm was not found; WebUI will not start")
            return False

        for host in self._candidate_hosts(remote_bind):
            # strictPort: a second runtime fails here instead of drifting to
            # 5174 and leaving two WebUIs to choose from.
            cmd = [npm, "run", "dev", "--", "--host", host, "--port", str(self._port), "--strictPort"]
            try:
                process = subprocess.Popen(
                    exits_with_this_process(cmd),
                    cwd=webui_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    env=child_env,
                    # npm, Vite and esbuild share a group that stop() ends
                    # together; an orphaned Vite would keep the port.
                    start_new_session=os.name == "posix",
                )
            except OSError:
                logger.exception("Failed to start WebUI with npm")
                continue

            time.sleep(0.8)
            if process.poll() is not None:
                startup_output = ""
                if process.stdout is not None:
                    startup_output = process.stdout.read().strip()
                logger.warning(
                    "WebUI command exited early%s%s",
                    "\n" if startup_output else "",
                    startup_output,
                )
                continue

            self._host = host
            self._process = process
            threading.Thread(
                target=self._read_stdout,
                args=(process,),
                name="webui-stdout",
                daemon=True,
            ).start()
            logger.info(
                "Started WebUI dev server on %s:%s (PID: %s)",
                self._host,
                self._port,
                process.pid,
            )
            return True

        logger.warning("The WebUI startup command failed")
        return False

    def stop(self) -> None:
        """Stop the WebUI dev server if it is running."""
        if self._process is None:
            return

        try:
            self._signal_group(signal.SIGTERM)
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._signal_group(getattr(signal, "SIGKILL", signal.SIGTERM))
                self._process.wait(timeout=5)
        finally:
            self._process = None

    def _signal_group(self, signum: int) -> None:
        assert self._process is not None
        if os.name != "posix":
            # Windows has no process groups here; terminate() is a hard kill.
            self._process.terminate()
            return
        try:
            os.killpg(self._process.pid, signum)
        except ProcessLookupError:
            pass
