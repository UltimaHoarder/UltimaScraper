from pathlib import Path
from types import SimpleNamespace

import pytest

from ultima_scraper_backend.config import DownloadPathSetup, Drive
from ultima_scraper_backend.job_system import host_capacity, ledger, ledger_runtime
from ultima_scraper_backend.job_system.host_capacity import (
    DOWNLOAD_CAPABILITY,
    DownloadAdmission,
    media_process_slots,
)

GIB = 1024**3


def _setup(*directories: Path) -> DownloadPathSetup:
    return DownloadPathSetup(
        directory_format=Path("{site_name}/{user_username}"),
        filename_format=Path("{media_filename}.{media_ext}"),
        drives=[Drive(directories=list(directories))],
    )


def test_media_slots_follow_cores_and_memory() -> None:
    # A 4 GB Pi: one process; a big box: capped where disks, not CPUs, limit.
    assert media_process_slots(4, 3 * GIB) == 1
    assert media_process_slots(4, 7 * GIB) == 2
    assert media_process_slots(32, 60 * GIB) == 8
    assert media_process_slots(1, 0) == 1


def test_media_slots_respect_an_explicit_setting(monkeypatch) -> None:
    monkeypatch.setenv("ULTIMA_MEDIA_PROCESS_CONCURRENCY", "3")
    assert host_capacity.apply_media_process_slots() == 3

    monkeypatch.delenv("ULTIMA_MEDIA_PROCESS_CONCURRENCY")
    monkeypatch.setattr(host_capacity, "media_process_slots", lambda: 2)
    assert host_capacity.apply_media_process_slots() == 2
    assert host_capacity.os.environ["ULTIMA_MEDIA_PROCESS_CONCURRENCY"] == "2"


def test_admission_needs_a_reachable_drive(tmp_path) -> None:
    roomy = dict(min_available_bytes=0, max_cpu_percent=100)

    # A /mnt drive that is not mounted here, as on a host without the NAS.
    assert not DownloadAdmission(lambda: _setup(Path("/mnt/not-mounted-here/DHS")), **roomy).allows_downloads()
    assert DownloadAdmission(lambda: _setup(tmp_path / "DHS"), **roomy).allows_downloads()


def test_admission_needs_memory_to_spare(tmp_path) -> None:
    starved = DownloadAdmission(lambda: _setup(tmp_path), min_available_bytes=1 << 60, max_cpu_percent=100)

    assert starved.drive_reachable()
    assert not starved.allows_downloads()


def test_admission_rechecks_drives_after_the_probe_interval(tmp_path) -> None:
    drive = tmp_path / "mount"
    setup = _setup(Path("/mnt/not-mounted-here/DHS"))
    admission = DownloadAdmission(lambda: setup, probe_seconds=0, min_available_bytes=0, max_cpu_percent=100)
    assert not admission.drive_reachable()

    setup = _setup(drive)
    assert admission.drive_reachable()


def test_download_work_requires_the_download_capability() -> None:
    download = SimpleNamespace(capabilities=[], task_type=SimpleNamespace(value="download"))
    scrape = SimpleNamespace(capabilities=["proxy"], task_type=SimpleNamespace(value="scrape"))

    assert ledger._work_capabilities(download) == [DOWNLOAD_CAPABILITY]
    assert ledger._work_capabilities(scrape) == ["proxy"]


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [True, False])
async def test_workers_offer_downloads_only_when_admitted(monkeypatch, allowed) -> None:
    offered: list[list[str]] = []

    class Ledger:
        def claim_many(self, *, capabilities, count, **kwargs):
            offered.append(list(capabilities))
            return []

    async def run_now(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(ledger_runtime, "ExecutionLedger", Ledger)
    monkeypatch.setattr(ledger_runtime, "run_database_call", run_now)
    pool = SimpleNamespace(
        supported_sites=["onlyfans"],
        worker_count=1,
        worker_index=0,
        worker_id="worker-1",
        config=SimpleNamespace(settings=SimpleNamespace(download_setup=None)),
    )
    adapter = ledger_runtime.LedgerRouterAdapter(pool)

    async def offers():
        return allowed

    adapter.offers_downloads = offers

    await adapter.claim_ready_tasks("backend-1", count=4)

    assert (DOWNLOAD_CAPABILITY in offered[0]) is allowed
    assert {"onlyfans", "api_commands"} <= set(offered[0])


def test_the_repeated_drive_probe_stays_quiet(caplog) -> None:
    from ultima_scraper_backend.job_system import drive_selection

    setup = _setup(Path("/mnt/not-mounted-here/DHS"))
    with caplog.at_level("WARNING"):
        assert not drive_selection.has_usable_download_root(setup)
        assert not caplog.records
        drive_selection._prepare_drive_root_for_storage(Path("/mnt/not-mounted-here/DHS"))
    assert "not-mounted-here" in caplog.text  # a real selection still says why


def test_staging_on_a_mount_missing_here_is_skipped(tmp_path) -> None:
    from ultima_scraper_backend.config import StagingDirectory, StagingUsage
    from ultima_scraper_backend.job_system.download_manager import DownloadManager

    setup = _setup(tmp_path / "library")
    setup.staging_directories = [
        StagingDirectory(path=Path("/mnt/not-mounted-here/staging"), usage=list(StagingUsage)),
        StagingDirectory(path=tmp_path / "staging", usage=list(StagingUsage)),
    ]
    manager = DownloadManager.__new__(DownloadManager)
    manager.config = SimpleNamespace(settings=SimpleNamespace(download_setup=setup))
    manager._staging_reserved = {}

    chosen, _ = manager._select_staging_directory([StagingUsage.DOWNLOADS])
    assert chosen == tmp_path / "staging"

    setup.staging_directories = setup.staging_directories[:1]
    assert manager._select_staging_directory([StagingUsage.DOWNLOADS])[0] is None


def test_device_files_fall_back_to_this_backends_config_folder(tmp_path, monkeypatch) -> None:
    from ultima_scraper_backend import config as config_module

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    local = tmp_path / "config" / "ultima_scraper_verse" / "drm_device"
    local.mkdir(parents=True)
    (local / "device_client_id_blob").write_bytes(b"blob")
    elsewhere = Path("/home/another-host/.config/ultima_scraper_verse/drm_device")
    drm = config_module.DRM(
        device_client_blob_filepath=elsewhere / "device_client_id_blob",
        device_private_key_filepath=elsewhere / "device_private_key",
    )

    usapi = drm.to_usapi_drm()

    assert usapi.device_client_blob_filepath == local / "device_client_id_blob"
    # Nothing here either: the configured path stays, and the error names it.
    assert usapi.device_private_key_filepath == elsewhere / "device_private_key"
    present = tmp_path / "blob"
    present.write_bytes(b"x")
    assert config_module.local_device_file(present) == present  # an existing path is used as is
