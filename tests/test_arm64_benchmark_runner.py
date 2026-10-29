"""Guards preventing host recordings or unsafe snapshots from passing as Pi runs."""

import importlib.util
import json
from pathlib import Path

import pytest


def load_script(name, relative):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / relative
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load_script("arm64_vm_runner", "scripts/performance/arm64_vm.py")
guest = load_script("arm64_guest_runner", "scripts/performance/arm64/run.py")
workload = load_script("arm64_workload", "scripts/performance/arm64/workload.py")


def test_host_forwards_download_selection_to_guest(tmp_path, monkeypatch):
    import shlex
    from types import SimpleNamespace

    vm = runner.VM(tmp_path)
    commands = []
    monkeypatch.setattr(vm, "prepare", lambda image: "frozen-source")

    def ssh(command, **kwargs):
        commands.append(shlex.split(command))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(vm, "ssh", ssh)
    monkeypatch.setattr(vm, "scp", lambda *args, **kwargs: None)
    vm.run("sustained", 7200, None, diagnostics=True, downloads=4)
    command = commands[0]
    assert command[command.index("--downloads") + 1] == "4"
    assert command[command.index("--duration") + 1] == "7200"
    assert command[command.index("--workload") + 1] == "guest-onlyfans"
    assert "--diagnostics" in command


@pytest.mark.parametrize(
    ("downloads", "max_posts", "resolved_posts"),
    [(4, None, 4), (8, None, 8), (8, 20, 20)],
)
def test_host_resolves_workload_for_selected_downloads(
    tmp_path, monkeypatch, downloads, max_posts, resolved_posts
):
    import sys

    calls = []

    class VM:
        state = tmp_path

        def run(self, *args):
            calls.append(args)

        def stop(self):
            pass

    argv = [
        "arm64_vm.py",
        "run",
        "--state-dir",
        str(tmp_path),
        "--downloads",
        str(downloads),
    ]
    if max_posts is not None:
        argv += ["--max-posts", str(max_posts)]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(runner, "VM", lambda state: VM())
    runner.main()
    assert calls == [
        ("sustained", 7200, None, "guest-onlyfans", resolved_posts, False, downloads)
    ]


@pytest.mark.parametrize(
    "options",
    [
        ["--downloads", "0"],
        ["--downloads", "-1"],
        ["--downloads", "101"],
        ["--downloads", "8", "--max-posts", "4"],
        ["--downloads", "21", "--workload", "offline-fixture"],
    ],
)
def test_invalid_download_selection_does_not_touch_vm(monkeypatch, options):
    import sys

    def unexpected_vm(state):
        pytest.fail("Invalid download selection must fail before VM preparation")

    monkeypatch.setattr(runner, "VM", unexpected_vm)
    monkeypatch.setattr(sys, "argv", ["arm64_vm.py", "run", *options])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2


@pytest.mark.parametrize(
    ("mode", "downloads", "max_posts", "expected"),
    [
        ("sustained", 4, 4, [("smoke-4", 4, 0), ("sustained-4", 4, 7200)]),
        ("sustained", 1, 4, [("smoke-1", 1, 0), ("sustained-1", 1, 7200)]),
        ("sustained", 8, 8, [("smoke-8", 8, 0), ("sustained-8", 8, 7200)]),
        (
            "sustained",
            None,
            4,
            [("smoke-2", 2, 0), ("sustained-2", 2, 7200), ("sustained-4", 4, 7200)],
        ),
        ("diagnostic", 2, 4, [("diagnostic-2", 2, 1200)]),
        ("smoke", 8, 8, [("smoke-8", 8, 0)]),
    ],
)
def test_guest_runs_only_selected_cases_with_full_acceptance_checks(
    tmp_path, monkeypatch, mode, downloads, max_posts, expected
):
    import sys
    from types import SimpleNamespace

    (tmp_path / "runs").mkdir()
    (tmp_path / "environment.json").write_text(
        json.dumps({"memory_total_bytes": 4 * guest.GIB, "swap_total_bytes": 0})
    )
    cases = []
    checks = []

    def run_case(command, **kwargs):
        case = Path(command[command.index("--output") + 1])
        case.mkdir()
        concurrency = int(command[command.index("--file-concurrency") + 1])
        duration = int(command[command.index("--minimum-workload-seconds") + 1])
        cases.append((case.name, concurrency, duration))
        assert "--property=MemoryMax=3G" in command
        assert "--property=MemorySwapMax=0" in command
        assert command[command.index("--workers") + 1] == "1"
        assert command[command.index("--files") + 1] == str(max_posts)
        assert command[command.index("--workload") + 1] == "guest-onlyfans"
        return SimpleNamespace(returncode=0)

    def assess_case(case, *, sustained):
        checks.append(sustained)
        return {
            "passed": True,
            "scope": "sustained" if sustained else "smoke",
            "verified_files": max_posts,
            "minimum_available_bytes": 2 * guest.GIB,
        }

    monkeypatch.setattr(guest, "ROOT", tmp_path)
    monkeypatch.setattr(guest.os, "uname", lambda: SimpleNamespace(machine="aarch64"))
    monkeypatch.setattr(guest, "source_identity", lambda: "frozen-source")
    monkeypatch.setattr(
        guest.shutil, "disk_usage", lambda path: SimpleNamespace(free=64 * guest.GIB)
    )
    monkeypatch.setattr(guest.subprocess, "run", run_case)
    monkeypatch.setattr(guest, "assess", assess_case)
    argv = [
        "run.py",
        "--mode",
        mode,
        "--duration",
        "1200" if mode == "diagnostic" else "7200",
        "--name",
        "selection-test",
        "--max-posts",
        str(max_posts),
        "--workload",
        "guest-onlyfans",
    ]
    if downloads is not None:
        argv += ["--downloads", str(downloads)]
    monkeypatch.setattr(sys, "argv", argv)
    guest.main()
    assert cases == expected
    assert checks == [
        bool(duration) and mode != "diagnostic" for _, _, duration in expected
    ]
    report = json.loads((tmp_path / "runs/selection-test/report.json").read_text())
    assert report["passed"] is True
    assert report["acceptance"] == (mode != "diagnostic")
    assert [case["name"] for case in report["cases"]] == [
        name for name, _, _ in expected
    ]
    assert report["download_concurrencies"] == sorted(
        {count for _, count, _ in expected}
    )


@pytest.mark.parametrize("downloads", [0, 8])
def test_guest_rejects_invalid_download_selection_before_preparation(
    monkeypatch, downloads
):
    import sys

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--mode",
            "sustained",
            "--duration",
            "7200",
            "--name",
            "invalid",
            "--max-posts",
            "4",
            "--downloads",
            str(downloads),
            "--workload",
            "guest-onlyfans",
        ],
    )
    with pytest.raises(SystemExit) as error:
        guest.main()
    assert error.value.code == 2


def test_shutdown_allows_guest_service_stop_deadline(tmp_path, monkeypatch):
    vm = runner.VM(tmp_path)
    clock = [0]
    monkeypatch.setattr(runner.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        runner.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setattr(vm, "alive", lambda: clock[0] < 90)
    shutdown = []
    monkeypatch.setattr(vm, "ssh", lambda command, **kwargs: shutdown.append(command))
    vm.stop()
    assert clock[0] == 90
    assert shutdown == ["sudo shutdown -h now"]


def test_shutdown_error_preserves_benchmark_failure(tmp_path, monkeypatch):
    import sys

    class VM:
        state = tmp_path

        def run(self, *args):
            raise RuntimeError("Benchmark failed; retained evidence")

        def stop(self):
            raise RuntimeError("Guest shutdown deadline")

    monkeypatch.setattr(runner, "VM", lambda state: VM())
    monkeypatch.setattr(
        sys, "argv", ["arm64_vm.py", "run", "--state-dir", str(tmp_path)]
    )
    with pytest.raises(RuntimeError, match="Benchmark failed") as failure:
        runner.main()
    assert failure.value.__notes__ == [
        "Guest shutdown also failed: Guest shutdown deadline"
    ]


def test_mixed_timeout_reports_failed_operation(tmp_path, monkeypatch):
    import threading

    mixed = load_script("arm64_mixed_test", "scripts/performance/arm64/mixed.py")
    fixture = mixed.MixedWork.__new__(mixed.MixedWork)
    fixture.started_event = threading.Event()
    fixture.started_event.set()
    fixture.stop_event = threading.Event()
    fixture.maintenance_interval = 300
    fixture.statistics_interval = 60
    fixture.output = tmp_path
    fixture.errors = []
    fixture.statistics = lambda **kwargs: {"response": {"snapshot": None}}

    def timed_out(path):
        raise TimeoutError("timed out")

    fixture.read_page = timed_out
    fixture.run()
    assert fixture.errors[0]["operation"] == "/api/v1/jobs?page=1&page_size=50"
    assert fixture.errors[0]["error"] == "TimeoutError('timed out')"
    assert fixture.errors[0]["seconds"] >= 0
    failure = json.loads((tmp_path / "mixed.jsonl").read_text().splitlines()[-1])
    assert failure["event"] == "error"
    assert failure["operation"] == fixture.errors[0]["operation"]


@pytest.mark.parametrize("failure_stage", ["process", "assessment"])
def test_failed_case_is_retained_in_report(tmp_path, monkeypatch, failure_stage):
    import sys
    from types import SimpleNamespace

    (tmp_path / "environment.json").write_text(
        json.dumps({"memory_total_bytes": 4 * guest.GIB, "swap_total_bytes": 0})
    )
    failure = {
        "type": "RuntimeError",
        "message": "Mixed-work fixture failed",
        "observers": {"mixed": {"operation": "/api/v1/jobs", "error": "timed out"}},
    }

    def run_case(command, **kwargs):
        case = Path(command[command.index("--output") + 1])
        case.mkdir()
        if failure_stage == "process":
            (case / "failure.json").write_text(json.dumps(failure))
        return SimpleNamespace(returncode=int(failure_stage == "process"))

    def assess_case(*args, **kwargs):
        raise AssertionError("Memory headroom check failed")

    monkeypatch.setattr(guest, "ROOT", tmp_path)
    (tmp_path / "runs").mkdir()
    monkeypatch.setattr(guest.os, "uname", lambda: SimpleNamespace(machine="aarch64"))
    monkeypatch.setattr(guest, "source_identity", lambda: "frozen-source")
    monkeypatch.setattr(
        guest.shutil, "disk_usage", lambda path: SimpleNamespace(free=64 * guest.GIB)
    )
    monkeypatch.setattr(guest.subprocess, "run", run_case)
    monkeypatch.setattr(guest, "assess", assess_case)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--mode",
            "diagnostic",
            "--duration",
            "1200",
            "--name",
            "failed-diagnostic",
            "--max-posts",
            "4",
            "--workload",
            "guest-onlyfans",
        ],
    )
    expected_error = RuntimeError if failure_stage == "process" else AssertionError
    with pytest.raises(expected_error):
        guest.main()
    report = json.loads((tmp_path / "runs/failed-diagnostic/report.json").read_text())
    assert report["passed"] is False and report["acceptance"] is False
    if failure_stage == "assessment":
        failure = {
            "type": "AssertionError",
            "message": "Memory headroom check failed",
            "returncode": 0,
        }
    assert report["cases"] == [
        {"name": "diagnostic-4", "passed": False, "failure": failure}
    ]


def test_real_workload_uses_explicit_guest_and_requested_performer():
    task = workload.job_payload(1000, 20, live=True)["tasks"][0]
    assert task["task_type"] == "scrape_user"
    assert task["params"] == {
        "site": "OnlyFans",
        "username": "onlyfans",
        "use_guest_auth": True,
        "download_media": True,
        "content_types": ["Posts"],
        "max_items": 20,
    }
    assert "auth_id" not in task["params"] and "user_id" not in task["params"]


def test_reset_refuses_paths_outside_disposable_media_root(tmp_path):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def scalars(self, *args):
            return self

        def all(self):
            return [str(tmp_path / "unowned.txt")]

    class Engine:
        def begin(self):
            return Connection()

    unowned = tmp_path / "unowned.txt"
    unowned.write_text("preserve")
    with pytest.raises(AssertionError, match="unowned"):
        workload.reset_live_media(Engine(), tmp_path / "media", 123)
    assert unowned.read_text() == "preserve"


@pytest.mark.parametrize(
    ("architecture", "memory", "swap"),
    [("x86_64", 4, 0), ("aarch64", 128, 0), ("aarch64", 4, 1)],
)
def test_acceptance_rejects_host_large_memory_or_guest_swap(architecture, memory, swap):
    with pytest.raises(AssertionError):
        runner.check_environment(
            {
                "architecture": architecture,
                "memory_total_bytes": memory * runner.GIB,
                "swap_total_bytes": swap * runner.GIB,
            }
        )


def test_snapshot_excludes_configuration_and_runtime_data(tmp_path):
    repo = tmp_path / "UltimaScraper"
    repo.mkdir()
    for relative in [
        "../UltimaScraperCore",
        "../UltimaBackends/UltimaScraperBackend",
        "../UltimaScraperAPI",
        "../UltimaDatabases/UltimaScraperDB",
        "../UltimaDatabases/UltimaScraperDBArchive",
    ]:
        root = repo / relative
        root.mkdir(parents=True)
        (root / "pyproject.toml").write_text("[project]\n")
        (root / "module.py").write_text("pass\n")
        (root / "migrations").mkdir()
        (root / "migrations/alembic.ini").write_text("[alembic]\n")
        (root / "accounts.json").write_text('{"secret":"excluded"}')
        (root / ".venv").mkdir()
        (root / ".venv/secret.py").write_text("SECRET='excluded'\n")
    selected = runner.source_files(repo)
    assert any(path.name == "module.py" for path in selected)
    assert any(path.name == "alembic.ini" for path in selected)
    assert not any(path.name in {"accounts.json", "secret.py"} for path in selected)


def test_shortened_duration_cannot_pass_even_with_completed_output(tmp_path):
    (tmp_path / "result.json").write_text(
        json.dumps({"target_met": False, "admission_stop": None, "initial_cgroup": {}})
    )
    (tmp_path / "shutdown-cgroup.json").write_text("{}")
    with pytest.raises(AssertionError):
        guest.assess(tmp_path, sustained=True)
