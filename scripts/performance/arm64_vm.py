"""Create and run an isolated 4 GiB ARM64 USR benchmark from current source.

This is a complete guest, not a memory recorder on the development host. Only
allowlisted source files are copied; deployment data and credentials stay out.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IMAGE_URL = "https://cloud-images.ubuntu.com/releases/resolute/release/ubuntu-26.04-server-cloudimg-arm64.img"
IMAGE_SHA256 = "63a93bd5a8d76e33b15ceb5daa3657bd79be804748051ab178e643b0f5da22e7"
GIB = 1024**3


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def event(name, **values):
    print(json.dumps({"event": name, **values}), flush=True)


def invoke(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_environment(environment):
    assert environment["architecture"] == "aarch64", "Benchmark requires an ARM64 guest"
    assert 3.5 * GIB < environment["memory_total_bytes"] <= 4 * GIB, (
        "Benchmark requires a 4 GiB guest"
    )
    assert environment["swap_total_bytes"] == 0, (
        "Disable guest swap before benchmarking"
    )


def source_files(repo):
    """Keep editable sibling layout, without copying any local configuration."""
    roots = [
        repo.parent / "UltimaScraperCore",
        repo.parent / "UltimaBackends/UltimaScraperBackend",
        repo.parent / "UltimaScraperAPI",
        repo.parent / "UltimaDatabases/UltimaScraperDB",
        repo.parent / "UltimaDatabases/UltimaScraperDBArchive",
    ]
    files = {
        repo / "main.py",
        repo / "pyproject.toml",
        repo / "uv.lock",
        repo / "README.md",
    }
    for root in roots:
        if not (root / "pyproject.toml").is_file():
            raise RuntimeError(f"Missing editable package: {root}")
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if any(
                part
                in {
                    ".git",
                    ".venv",
                    "__pycache__",
                    "tests",
                    "node_modules",
                    "build",
                    "dist",
                }
                for part in relative.parts
            ):
                continue
            if path.is_file() and (
                path.suffix == ".py"
                or (
                    "migrations" in relative.parts
                    and path.name in {"alembic.ini", "script.py.mako", "README"}
                )
                or path.name
                in {"pyproject.toml", "README.md", "LICENSE", "setup.cfg", "setup.py"}
            ):
                files.add(path)
    files.update((repo / "scripts/performance/arm64").glob("*.py"))
    return sorted(files)


def snapshot(state):
    manifest = {}
    with tarfile.open(state / "source.tar.gz", "w:gz") as archive:
        for path in source_files(REPO):
            relative = str(path.relative_to(REPO.parent))
            manifest[relative] = digest(path)
            archive.add(path, arcname=relative, recursive=False)
    for relative, expected in manifest.items():
        if digest(REPO.parent / relative) != expected:
            raise RuntimeError(
                "Source changed during snapshot; retry with a stable checkout"
            )
    identity = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    save(state / "source-manifest.json", {"identity": identity, "files": manifest})
    return identity


class VM:
    def __init__(self, state):
        self.state = state.resolve()
        if "," in str(self.state):
            raise ValueError(
                "Use a state directory without commas for QEMU drive arguments"
            )
        self.state.mkdir(parents=True, exist_ok=True)
        self.config_path = self.state / "vm.json"
        self.config = (
            json.loads(self.config_path.read_text())
            if self.config_path.exists()
            else {}
        )
        socket_directory = (
            Path("/tmp")
            / f"usr-arm64-{os.getuid()}-{hashlib.sha256(str(self.state).encode()).hexdigest()[:16]}"
        )
        socket_directory.mkdir(mode=0o700, exist_ok=True)
        self.socket_path = socket_directory / "qmp.sock"

    def ssh(self, command, *, capture=False, check=True):
        return subprocess.run(
            [
                "ssh",
                "-i",
                str(self.state / "ssh-key"),
                "-p",
                str(self.config["ssh_port"]),
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                f"UserKnownHostsFile={self.state / 'known-hosts'}",
                "bench@127.0.0.1",
                command,
            ],
            check=check,
            capture_output=capture,
            text=True,
        )

    def scp(self, source, destination, *, download=False):
        remote = f"bench@127.0.0.1:{destination}"
        invoke(
            [
                "scp",
                "-r",
                "-q",
                "-i",
                str(self.state / "ssh-key"),
                "-P",
                str(self.config["ssh_port"]),
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                f"UserKnownHostsFile={self.state / 'known-hosts'}",
                *([remote, str(source)] if download else [str(source), remote]),
            ]
        )

    def qmp(self, command, arguments=None):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(5)
            connection.connect(str(self.socket_path))
            with connection.makefile("rwb") as stream:
                stream.readline()
                for request in (
                    {"execute": "qmp_capabilities"},
                    {"execute": command, "arguments": arguments or {}},
                ):
                    stream.write(json.dumps(request).encode() + b"\n")
                    stream.flush()
                    while True:
                        response = json.loads(stream.readline())
                        if "return" in response:
                            break
                        if "error" in response:
                            raise RuntimeError(response["error"])
        return response["return"]

    def alive(self):
        try:
            return self.qmp("query-status")["status"] == "running"
        except OSError, ValueError:
            return False

    def create(self, base_image):
        for executable in (
            "qemu-system-aarch64",
            "qemu-img",
            "genisoimage",
            "ssh",
            "scp",
            "ssh-keygen",
        ):
            if not shutil.which(executable):
                raise RuntimeError(f"Install host prerequisite: {executable}")
        if shutil.disk_usage(self.state).free < 48 * GIB:
            raise RuntimeError(
                "Keep at least 48 GiB host disk free for the disposable VM and evidence"
            )
        firmware = next(
            (
                p
                for p in (
                    Path("/usr/share/edk2/aarch64/QEMU_EFI.fd"),
                    Path("/usr/share/AAVMF/AAVMF_CODE.fd"),
                )
                if p.exists()
            ),
            None,
        )
        if firmware is None:
            raise RuntimeError("Install AArch64 QEMU UEFI firmware")
        base = self.state / "base.img"
        if not base.exists():
            if base_image:
                shutil.copyfile(base_image, base)
            else:
                event("download_image", url=IMAGE_URL)
                partial = base.with_suffix(".partial")
                urllib.request.urlretrieve(IMAGE_URL, partial)
                partial.replace(base)
        if digest(base) != IMAGE_SHA256:
            raise RuntimeError(
                "ARM64 image checksum differs from the pinned Canonical release; refusing to boot"
            )
        if not (self.state / "ssh-key").exists():
            invoke(
                [
                    "ssh-keygen",
                    "-q",
                    "-t",
                    "ed25519",
                    "-N",
                    "",
                    "-f",
                    str(self.state / "ssh-key"),
                ]
            )
        if not (self.state / "os.qcow2").exists():
            invoke(
                [
                    "qemu-img",
                    "create",
                    "-f",
                    "qcow2",
                    "-F",
                    "qcow2",
                    "-b",
                    str(base),
                    str(self.state / "os.qcow2"),
                ]
            )
            invoke(["qemu-img", "resize", str(self.state / "os.qcow2"), "16G"])
            invoke(
                [
                    "qemu-img",
                    "create",
                    "-f",
                    "qcow2",
                    str(self.state / "application.qcow2"),
                    "32G",
                ]
            )
            public_key = (self.state / "ssh-key.pub").read_text().strip()
            user_data = f"""#cloud-config
hostname: usr-arm64-benchmark
users:
  - name: bench
    groups: [sudo]
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    ssh_authorized_keys:
      - {public_key}
ssh_pwauth: false
disk_setup:
  /dev/vdb:
    table_type: gpt
    layout: true
    overwrite: false
fs_setup:
  - label: usr-bench-data
    filesystem: ext4
    device: /dev/vdb1
mounts:
  - [LABEL=usr-bench-data, /srv/usr, ext4, defaults, '0', '2']
runcmd:
  - [mkdir, -p, /srv/usr/tmp, /srv/usr/project, /srv/usr/runs, /srv/usr/cache]
  - [chown, -R, 'bench:bench', /srv/usr]
  - [chmod, '1777', /srv/usr/tmp]
  - [swapoff, -a]
  - [loginctl, enable-linger, bench]
"""
            (self.state / "user-data").write_text(user_data)
            (self.state / "meta-data").write_text(
                "instance-id: usr-arm64-benchmark\nlocal-hostname: usr-arm64-benchmark\n"
            )
            invoke(
                [
                    "genisoimage",
                    "-quiet",
                    "-output",
                    str(self.state / "seed.iso"),
                    "-volid",
                    "cidata",
                    "-joliet",
                    "-rock",
                    str(self.state / "user-data"),
                    str(self.state / "meta-data"),
                ]
            )
        if not self.config:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            self.config = {
                "ssh_port": port,
                "firmware": str(firmware),
                "guest_memory_MiB": 4096,
                "cpus": 4,
                "image_sha256": IMAGE_SHA256,
                "image_url": IMAGE_URL,
            }
            save(self.config_path, self.config)

    def boot(self):
        if self.alive():
            return
        # Only this runner's stopped QMP socket is removed.
        self.socket_path.unlink(missing_ok=True)
        command = [
            "qemu-system-aarch64",
            "-machine",
            "virt,gic-version=3",
            "-cpu",
            "cortex-a72",
            "-smp",
            "4",
            "-m",
            "4096",
            "-accel",
            "tcg,thread=multi",
            "-bios",
            self.config["firmware"],
            "-display",
            "none",
            "-monitor",
            "none",
            "-serial",
            f"file:{self.state / 'serial.log'}",
            "-qmp",
            f"unix:{self.socket_path},server=on,wait=off",
            "-drive",
            f"if=none,id=osdisk,file={self.state / 'os.qcow2'},format=qcow2,cache=none",
            "-device",
            "virtio-blk-pci,drive=osdisk",
            "-drive",
            f"if=none,id=appdisk,file={self.state / 'application.qcow2'},format=qcow2,cache=none,bps=41943040,iops=150",
            "-device",
            "virtio-blk-pci,drive=appdisk",
            "-drive",
            f"if=none,id=seed,file={self.state / 'seed.iso'},format=raw,readonly=on",
            "-device",
            "virtio-blk-pci,drive=seed",
            "-netdev",
            f"user,id=net0,hostfwd=tcp:127.0.0.1:{self.config['ssh_port']}-:22",
            "-device",
            "virtio-net-pci,netdev=net0",
            "-device",
            "virtio-rng-pci",
        ]
        save(self.state / "qemu-command.json", command)
        with (self.state / "qemu.log").open("a") as log:
            process = subprocess.Popen(
                command, stdout=log, stderr=log, start_new_session=True
            )
        save(self.state / "process.json", {"pid": process.pid})
        event("vm_boot", pid=process.pid, memory_MiB=4096)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"QEMU exited; see {self.state / 'qemu.log'}")
            if self.ssh("true", capture=True, check=False).returncode == 0:
                self.ssh(
                    "sudo cloud-init status --wait >/dev/null && mountpoint -q /srv/usr"
                )
                return
            time.sleep(5)
        raise RuntimeError(f"Guest boot deadline; see {self.state / 'serial.log'}")

    def prepare(self, base_image):
        self.create(base_image)
        self.boot()
        self.ssh("rm -f /srv/usr/active-run.json")
        assert self.qmp("query-memory-size-summary")["base-memory"] == 4 * GIB
        assert len(self.qmp("query-cpus-fast")) == 4
        blocks = self.qmp("query-block")
        data_disk = next(block for block in blocks if block["device"] == "appdisk")
        assert data_disk["inserted"]["bps"] == 41943040
        assert data_disk["inserted"]["iops"] == 150
        save(
            self.state / "qmp-verification.json",
            {
                "memory": self.qmp("query-memory-size-summary"),
                "cpus": len(self.qmp("query-cpus-fast")),
                "version": self.qmp("query-version"),
                "application_disk": data_disk,
            },
        )
        identity = snapshot(self.state)
        self.scp(self.state / "source.tar.gz", "/srv/usr/source.tar.gz")
        self.scp(self.state / "source-manifest.json", "/srv/usr/source-manifest.json")
        provision = REPO / "scripts/performance/arm64/provision.sh"
        self.scp(provision, "/srv/usr/provision.sh")
        event("provision", source_identity=identity)
        provisioned = self.ssh(
            "bash /srv/usr/provision.sh > /srv/usr/provision.log 2>&1", check=False
        )
        if provisioned.returncode:
            self.scp(
                self.state / "provision.log", "/srv/usr/provision.log", download=True
            )
            raise RuntimeError(
                f"Guest provisioning failed; see {self.state / 'provision.log'}"
            )
        self.scp(
            self.state / "environment.json", "/srv/usr/environment.json", download=True
        )
        environment = json.loads((self.state / "environment.json").read_text())
        check_environment(environment)
        event("guest_verified", **environment)
        return identity

    def run(
        self,
        mode,
        duration,
        base_image,
        workload="guest-onlyfans",
        max_posts=4,
        diagnostics=False,
        downloads=None,
    ):
        identity = self.prepare(base_image)
        name = f"{mode}-{time.time_ns()}"
        command = shlex.join(
            [
                "/srv/usr/project/UltimaScraper/.venv/bin/python",
                "-B",
                "/srv/usr/project/UltimaScraper/scripts/performance/arm64/run.py",
                "--mode",
                mode,
                "--duration",
                str(duration),
                "--name",
                name,
                "--workload",
                workload,
                "--max-posts",
                str(max_posts),
            ]
            + (["--downloads", str(downloads)] if downloads is not None else [])
            + (["--diagnostics"] if diagnostics else [])
        )
        event(
            "benchmark_start",
            mode=mode,
            duration_per_case=duration if mode != "smoke" else None,
            source_identity=identity,
            workload=workload,
            downloads=downloads,
        )
        target = self.state / "results"
        target.mkdir(exist_ok=True)
        evidence_collected = False
        try:
            outcome = self.ssh(command, check=False)
        finally:
            try:
                self.scp(target, f"/srv/usr/runs/{name}", download=True)
                evidence_collected = True
            except subprocess.CalledProcessError:
                event("evidence_collection_failed", guest_path=f"/srv/usr/runs/{name}")
        if not evidence_collected:
            raise RuntimeError(
                "Benchmark evidence could not be collected; refusing to report a pass"
            )
        if outcome.returncode:
            raise RuntimeError(
                f"Benchmark failed ({outcome.returncode}); retained evidence: {target / name}"
            )
        event(
            "diagnostic_completed" if mode == "diagnostic" else "benchmark_passed",
            results=str(target / name),
        )

    def stop(self):
        if not self.alive():
            return
        self.ssh("sudo shutdown -h now", check=False)
        # Ubuntu services may use a 90-second stop deadline before poweroff.
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if not self.alive():
                event("vm_stopped")
                return
            time.sleep(1)
        raise RuntimeError(
            "Guest shutdown has not completed; inspect before removing any disks"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["prepare", "smoke", "run", "diagnose", "status", "stop"]
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Retain process stacks, ASGI timings, event-loop lag and SQL waits",
    )
    parser.add_argument(
        "--state-dir", type=Path, default=REPO / ".performance-simulation-arm64-current"
    )
    parser.add_argument("--base-image", type=Path)
    parser.add_argument(
        "--downloads",
        type=int,
        help="Concurrent file downloads; select one count instead of the default 2/4 comparison",
    )
    parser.add_argument(
        "--max-posts",
        type=int,
        default=None,
        help="Guest-visible Posts per onlyfans cycle (default: max of 4 and selected downloads)",
    )
    parser.add_argument(
        "--workload",
        choices=["guest-onlyfans", "offline-fixture"],
        default="guest-onlyfans",
        help="Real guest-auth onlyfans workload (default), or an offline infrastructure check",
    )
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help="Leave the owned guest booted for diagnosis after a case",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Seconds of admitted work per sustained case",
    )
    arguments = parser.parse_args()
    if arguments.duration is None:
        arguments.duration = 1200 if arguments.action == "diagnose" else 7200
    if not 60 <= arguments.duration <= 86400:
        parser.error("Duration must be between 60 and 86400 seconds")
    if arguments.downloads is not None and not 1 <= arguments.downloads <= 100:
        parser.error("Downloads must be between 1 and 100")
    required_downloads = arguments.downloads or (
        2 if arguments.action == "smoke" else 4
    )
    if arguments.max_posts is None:
        arguments.max_posts = max(4, required_downloads)
    if not 4 <= arguments.max_posts <= 100:
        parser.error("Max posts must be between 4 and 100")
    if (
        arguments.workload == "guest-onlyfans"
        and required_downloads > arguments.max_posts
    ):
        parser.error("Max posts must be at least the selected downloads")
    if arguments.workload == "offline-fixture" and required_downloads > 20:
        parser.error("The offline fixture supports at most 20 concurrent downloads")
    vm = VM(arguments.state_dir)
    lock = (vm.state / "runner.lock").open("a")
    if arguments.action != "status":
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error(
                "Another runner owns this VM; use status or wait for it to finish"
            )
    if arguments.action == "prepare":
        vm.prepare(arguments.base_image)
    elif arguments.action in {"smoke", "run", "diagnose"}:
        try:
            vm.run(
                {"smoke": "smoke", "run": "sustained", "diagnose": "diagnostic"}[
                    arguments.action
                ],
                arguments.duration,
                arguments.base_image,
                arguments.workload,
                arguments.max_posts,
                arguments.diagnostics or arguments.action == "diagnose",
                arguments.downloads,
            )
        finally:
            if not arguments.keep_running:
                failure = sys.exception()
                try:
                    vm.stop()
                except Exception as shutdown_error:
                    if failure is None:
                        raise
                    failure.add_note(f"Guest shutdown also failed: {shutdown_error}")
                    event("vm_shutdown_failed", error=str(shutdown_error))
    elif arguments.action == "stop":
        vm.stop()
    else:
        running = vm.alive()
        details = {}
        if running:
            active = vm.ssh("cat /srv/usr/active-run.json", capture=True, check=False)
            if active.returncode == 0:
                details = json.loads(active.stdout)
                status_path = Path(details["status_path"])
                if status_path.is_relative_to("/srv/usr/runs"):
                    progress = vm.ssh(
                        shlex.join(["cat", str(status_path)]), capture=True, check=False
                    )
                    if progress.returncode == 0:
                        details["progress"] = json.loads(progress.stdout)
        event("status", running=running, state=str(vm.state), benchmark=details)


if __name__ == "__main__":
    main()
