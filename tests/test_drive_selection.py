from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ultima_scraper_backend.api.routes.system as system_routes
import ultima_scraper_backend.config as config_module
from ultima_scraper_backend.api.routes.system import (
    AddDirectoryRequest,
    add_directory,
)
from ultima_scraper_backend.config import (
    DownloadPathSetup,
    Drive,
    UltimaScraperCollectionConfig,
)
from ultima_scraper_backend.job_system.drive_selection import (
    DriveSelectionError,
    UserDirectorySelection,
    _minimum_space_bytes,
    select_download_destination,
    select_user_destination,
    select_user_directory,
)


def test_minimum_space_bytes_uses_configured_bytes() -> None:
    twenty_gib = 20 * 1024**3
    assert _minimum_space_bytes(twenty_gib) == twenty_gib
    assert _minimum_space_bytes(-1) is None


def test_select_download_destination_allows_drive_when_free_space_exceeds_minimum(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    drive_root = tmp_path / "downloads"
    drive_root.mkdir()

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{model_username}/{api_type}/{value}/{media_type}"
        ),
        drives=[
            Drive(
                minimum_space=20 * 1024**3,
                overflow=False,
                directories=[drive_root],
            )
        ],
    )

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        lambda _: SimpleNamespace(
            total=200 * 1024**3,
            used=150 * 1024**3,
            free=50 * 1024**3,
        ),
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.root == drive_root


def test_select_download_destination_rejects_drive_when_free_space_below_minimum(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    drive_root = tmp_path / "downloads"
    drive_root.mkdir()

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{model_username}/{api_type}/{value}/{media_type}"
        ),
        drives=[
            Drive(
                minimum_space=20 * 1024**3,
                overflow=False,
                directories=[drive_root],
            )
        ],
    )

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        lambda _: SimpleNamespace(
            total=200 * 1024**3,
            used=185 * 1024**3,
            free=15 * 1024**3,
        ),
    )

    with pytest.raises(
        DriveSelectionError, match="No download directories satisfy space requirements"
    ):
        select_download_destination(
            setup,
            site_name="OnlyFans",
            performer_username="tester",
            api_type="Posts",
            value="Images",
            media_type="photo",
        )


def test_select_download_destination_can_ignore_space_requirements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    drive_root = tmp_path / "downloads"
    drive_root.mkdir()

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{model_username}/{api_type}/{value}/{media_type}"
        ),
        drives=[
            Drive(
                minimum_space=20 * 1024**3,
                overflow=False,
                directories=[drive_root],
            )
        ],
    )

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        lambda _: SimpleNamespace(
            total=200 * 1024**3,
            used=199 * 1024**3,
            free=1 * 1024**3,
        ),
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
        required_space=10 * 1024**3,
        ignore_space_requirements=True,
    )

    assert result.root == drive_root


def test_select_download_destination_allows_overflow_drive_below_minimum(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    drive_root = tmp_path / "downloads"
    drive_root.mkdir()

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{model_username}/{api_type}/{value}/{media_type}"
        ),
        drives=[
            Drive(
                minimum_space=20 * 1024**3,
                store=True,
                overflow=True,
                directories=[drive_root],
            )
        ],
    )

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        lambda _: SimpleNamespace(
            total=200 * 1024**3,
            used=185 * 1024**3,
            free=15 * 1024**3,
        ),
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.root == drive_root


def test_select_download_destination_uses_uppercase_first_letter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    drive_root = tmp_path / "downloads"
    drive_root.mkdir()

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_letter}/{model_username}/{api_type}/{value}/{media_type}"
        ),
        drives=[Drive(directories=[drive_root])],
    )

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        lambda _: SimpleNamespace(
            total=200 * 1024**3,
            used=100 * 1024**3,
            free=100 * 1024**3,
        ),
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.relative_path == Path(
        "OnlyFans", "T", "tester", "Posts", "Images", "photo"
    )


def test_select_user_directory_reuses_existing_lowercase_performer_folder(
    tmp_path: Path,
) -> None:
    drive_root = tmp_path / "downloads"
    legacy_performer_path = drive_root / "OnlyFans" / "t" / "tester"
    legacy_performer_path.mkdir(parents=True)

    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        drives=[Drive(directories=[drive_root])]
    )
    user_manager = SimpleNamespace(config=config)

    result = select_user_directory(
        user_id=1,
        usernames=["tester"],
        site_name="OnlyFans",
        user_manager=user_manager,
    )

    assert result == legacy_performer_path.resolve()


def test_select_user_directory_reuses_existing_alias_folder_across_drives(
    tmp_path: Path,
) -> None:
    # Simulates a renamed performer: current username ``lunadiaz12`` has no
    # folder on either drive, but the historical alias ``mxgroup`` already has
    # one on the first drive. Drive selection must reuse it instead of creating
    # a fresh folder on the emptier second drive.
    drive_one = tmp_path / "storage_a"
    drive_two = tmp_path / "storage_b"
    alias_folder = drive_one / "OnlyFans" / "M" / "mxgroup"
    alias_folder.mkdir(parents=True)
    drive_two.mkdir()

    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        drives=[Drive(directories=[drive_one]), Drive(directories=[drive_two])]
    )
    user_manager = SimpleNamespace(config=config)

    result = select_user_directory(
        user_id=1,
        usernames=["lunadiaz12", "mxgroup"],
        site_name="OnlyFans",
        user_manager=user_manager,
    )

    assert result == alias_folder.resolve()


def test_select_user_directory_reuses_existing_performer_on_non_store_drive(
    tmp_path: Path,
) -> None:
    drive_root = tmp_path / "downloads"
    performer_path = drive_root / "OnlyFans" / "T" / "tester"
    performer_path.mkdir(parents=True)

    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        drives=[Drive(store=False, overflow=False, directories=[drive_root])]
    )
    user_manager = SimpleNamespace(config=config)

    result = select_user_directory(
        user_id=1,
        usernames=["tester"],
        site_name="OnlyFans",
        user_manager=user_manager,
    )

    assert result == performer_path.resolve()


def test_select_user_directory_reuses_existing_folder_when_ignoring_space_requirements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    existing_drive = tmp_path / "existing-drive"
    overflow_drive = tmp_path / "overflow-drive"
    performer_path = existing_drive / "OnlyFans" / "O" / "onlyfans"
    performer_path.mkdir(parents=True)
    overflow_drive.mkdir()

    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        drives=[
            Drive(
                store=True,
                scan_existing=True,
                overflow=True,
                directories=[existing_drive],
            ),
            Drive(
                store=True,
                scan_existing=True,
                overflow=True,
                directories=[overflow_drive],
            ),
        ]
    )
    user_manager = SimpleNamespace(config=config)

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        lambda path: (
            SimpleNamespace(total=200 * 1024**3, used=190 * 1024**3, free=10 * 1024**3)
            if Path(path) == existing_drive
            else SimpleNamespace(
                total=200 * 1024**3,
                used=20 * 1024**3,
                free=180 * 1024**3,
            )
        ),
    )

    result = select_user_directory(
        user_id=1,
        usernames=["onlyfans"],
        site_name="OnlyFans",
        user_manager=user_manager,
        required_space=50 * 1024**3,
        ignore_space_requirements=True,
    )

    assert result == performer_path.resolve()


def test_select_user_directory_skips_existing_scan_on_disabled_drive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    slow_drive = tmp_path / "slow-drive"
    fast_drive = tmp_path / "fast-drive"
    slow_drive.mkdir()
    fast_drive.mkdir()

    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        drives=[
            Drive(store=False, scan_existing=False, directories=[slow_drive]),
            Drive(store=True, directories=[fast_drive]),
        ]
    )
    user_manager = SimpleNamespace(config=config)

    original_exists = Path.exists

    def guarded_exists(path: Path) -> bool:
        if str(path).startswith(str(slow_drive)):
            raise AssertionError("slow drive should not be scanned for existing users")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", guarded_exists)
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        lambda _: SimpleNamespace(
            total=200 * 1024**3,
            used=100 * 1024**3,
            free=100 * 1024**3,
        ),
    )

    result = select_user_directory(
        user_id=1,
        usernames=["tester"],
        site_name="OnlyFans",
        user_manager=user_manager,
    )

    assert result == (fast_drive / "OnlyFans" / "T" / "tester").resolve()


def test_select_user_directory_skips_permission_denied_drive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocked_drive = tmp_path / "blocked-drive"
    healthy_drive = tmp_path / "healthy-drive"
    blocked_drive.mkdir()
    healthy_drive.mkdir()

    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        drives=[
            Drive(directories=[blocked_drive]),
            Drive(directories=[healthy_drive]),
        ]
    )
    user_manager = SimpleNamespace(config=config)

    original_exists = Path.exists

    def guarded_exists(path: Path) -> bool:
        if str(path).startswith(str(blocked_drive)):
            raise PermissionError("Permission denied")
        return original_exists(path)

    def guarded_disk_usage(path: str | Path) -> SimpleNamespace:
        if Path(path) == blocked_drive:
            raise PermissionError("Permission denied")
        return SimpleNamespace(
            total=200 * 1024**3,
            used=100 * 1024**3,
            free=100 * 1024**3,
        )

    monkeypatch.setattr(Path, "exists", guarded_exists)
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        guarded_disk_usage,
    )

    result = select_user_directory(
        user_id=1,
        usernames=["tester"],
        site_name="OnlyFans",
        user_manager=user_manager,
    )

    assert result == (healthy_drive / "OnlyFans" / "T" / "tester").resolve()


def test_select_user_directory_does_not_place_new_performer_on_non_store_overflow_drive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    non_store_drive = tmp_path / "overflow-only"
    store_drive = tmp_path / "store-drive"
    non_store_drive.mkdir()
    store_drive.mkdir()

    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        drives=[
            Drive(
                minimum_space=50 * 1024**3,
                store=False,
                overflow=True,
                directories=[non_store_drive],
            ),
            Drive(
                minimum_space=10 * 1024**3,
                store=True,
                overflow=False,
                directories=[store_drive],
            ),
        ]
    )
    user_manager = SimpleNamespace(config=config)

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        lambda path: (
            SimpleNamespace(total=200 * 1024**3, used=185 * 1024**3, free=15 * 1024**3)
            if Path(path) == non_store_drive
            else SimpleNamespace(
                total=200 * 1024**3,
                used=150 * 1024**3,
                free=50 * 1024**3,
            )
        ),
    )

    result = select_user_directory(
        user_id=1,
        usernames=["tester"],
        site_name="OnlyFans",
        user_manager=user_manager,
    )

    assert result == (store_drive / "OnlyFans" / "T" / "tester").resolve()


def test_select_user_directory_prefers_normal_store_drive_over_overflow_when_ignoring_space(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    normal_drive = tmp_path / "normal-drive"
    overflow_drive = tmp_path / "overflow-drive"
    normal_drive.mkdir()
    overflow_drive.mkdir()

    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        drives=[
            Drive(
                minimum_space=50 * 1024**3,
                store=True,
                overflow=False,
                directories=[normal_drive],
            ),
            Drive(
                minimum_space=10 * 1024**3,
                store=True,
                overflow=True,
                directories=[overflow_drive],
            ),
        ]
    )
    user_manager = SimpleNamespace(config=config)

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        lambda path: (
            SimpleNamespace(total=200 * 1024**3, used=190 * 1024**3, free=10 * 1024**3)
            if Path(path) == normal_drive
            else SimpleNamespace(
                total=200 * 1024**3,
                used=20 * 1024**3,
                free=180 * 1024**3,
            )
        ),
    )

    result = select_user_directory(
        user_id=1,
        usernames=["tester"],
        site_name="OnlyFans",
        user_manager=user_manager,
        required_space=50 * 1024**3,
        ignore_space_requirements=True,
    )

    assert result == (normal_drive / "OnlyFans" / "T" / "tester").resolve()


def test_select_download_destination_prefers_canonical_existing_path_over_alt(
    tmp_path: Path,
) -> None:
    drive_root = tmp_path / "downloads"
    canonical_path = (
        drive_root / "OnlyFans" / "T" / "tester" / "Posts" / "Images" / "photo"
    )
    alt_path = (
        drive_root / "OnlyFans Vault" / "T" / "tester" / "Posts" / "Images" / "photo"
    )
    canonical_path.mkdir(parents=True)
    alt_path.mkdir(parents=True)

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        alt_directory_formats=[
            Path(
                "{site_name} Vault/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
            )
        ],
        drives=[Drive(directories=[drive_root])],
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.relative_path == canonical_path.relative_to(drive_root)
    assert result.directory_format == setup.directory_format


def test_select_download_destination_uses_alt_existing_path_when_canonical_missing(
    tmp_path: Path,
) -> None:
    drive_root = tmp_path / "downloads"
    alt_path = (
        drive_root / "OnlyFans Vault" / "T" / "tester" / "Posts" / "Images" / "photo"
    )
    alt_path.mkdir(parents=True)

    alt_directory_format = Path(
        "{site_name} Vault/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
    )
    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        alt_directory_formats=[alt_directory_format],
        drives=[Drive(directories=[drive_root])],
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.relative_path == alt_path.relative_to(drive_root)
    assert result.directory_format == alt_directory_format


def test_select_download_destination_falls_back_to_canonical_for_new_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    drive_root = tmp_path / "downloads"
    drive_root.mkdir()

    canonical_directory_format = Path(
        "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
    )
    setup = DownloadPathSetup(
        directory_format=canonical_directory_format,
        alt_directory_formats=[
            Path(
                "{site_name} Vault/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
            )
        ],
        drives=[Drive(directories=[drive_root])],
    )

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        lambda _: SimpleNamespace(
            total=200 * 1024**3,
            used=100 * 1024**3,
            free=100 * 1024**3,
        ),
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.relative_path == Path(
        "OnlyFans", "T", "tester", "Posts", "Images", "photo"
    )
    assert result.directory_format == canonical_directory_format


def test_select_download_destination_supports_alt_suffix_layouts(
    tmp_path: Path,
) -> None:
    drive_root = tmp_path / "downloads"
    alt_directory_format = Path(
        "{site_name} Vault/{first_username_letter}/{user_username}/Library/{media_type}/{content_type}/{value}"
    )
    alt_path = (
        drive_root
        / "OnlyFans Vault"
        / "T"
        / "tester"
        / "Library"
        / "photo"
        / "Posts"
        / "Images"
    )
    alt_path.mkdir(parents=True)

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        alt_directory_formats=[alt_directory_format],
        drives=[Drive(directories=[drive_root])],
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.relative_path == alt_path.relative_to(drive_root)
    assert result.directory_format == alt_directory_format


def test_select_download_destination_checks_alt_formats_in_order_after_canonical(
    tmp_path: Path,
) -> None:
    drive_root = tmp_path / "downloads"
    first_alt_directory_format = Path(
        "{site_name} Vault/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
    )
    second_alt_directory_format = Path(
        "Archive/{site_name}/{user_username}/{content_type}/{value}/{media_type}"
    )
    first_alt_path = (
        drive_root / "OnlyFans Vault" / "T" / "tester" / "Posts" / "Images" / "photo"
    )
    second_alt_path = (
        drive_root / "Archive" / "OnlyFans" / "tester" / "Posts" / "Images" / "photo"
    )
    first_alt_path.mkdir(parents=True)
    second_alt_path.mkdir(parents=True)

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        alt_directory_formats=[
            first_alt_directory_format,
            second_alt_directory_format,
        ],
        drives=[Drive(directories=[drive_root])],
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.relative_path == first_alt_path.relative_to(drive_root)
    assert result.directory_format == first_alt_directory_format


def test_select_download_destination_skips_permission_denied_dynamic_scan_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocked_drive = tmp_path / "blocked-drive"
    healthy_drive = tmp_path / "healthy-drive"
    blocked_drive.mkdir()
    healthy_drive.mkdir()
    healthy_existing = (
        healthy_drive / "OnlyFans" / "T" / "tester" / "Posts" / "Images" / "photo"
    )
    healthy_existing.mkdir(parents=True)

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_letter}/{model_username}/{api_type}/{value}/{media_type}"
        ),
        drives=[
            Drive(directories=[blocked_drive]),
            Drive(directories=[healthy_drive]),
        ],
    )

    original_iterdir = Path.iterdir

    def guarded_iterdir(path: Path):
        if path == blocked_drive:
            raise PermissionError("Permission denied")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", guarded_iterdir)

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.root == healthy_drive
    assert result.relative_path == healthy_existing.relative_to(healthy_drive)


def test_select_download_destination_skips_permission_denied_drive_capacity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocked_drive = tmp_path / "blocked-drive"
    healthy_drive = tmp_path / "healthy-drive"
    blocked_drive.mkdir()
    healthy_drive.mkdir()

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{model_username}/{api_type}/{value}/{media_type}"
        ),
        drives=[
            Drive(directories=[blocked_drive]),
            Drive(directories=[healthy_drive]),
        ],
    )

    def guarded_disk_usage(path: str | Path) -> SimpleNamespace:
        if Path(path) == blocked_drive:
            raise PermissionError("Permission denied")
        return SimpleNamespace(
            total=200 * 1024**3,
            used=100 * 1024**3,
            free=100 * 1024**3,
        )

    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        guarded_disk_usage,
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.root == healthy_drive


def test_select_download_destination_renders_full_alt_format_when_root_is_dynamic(
    tmp_path: Path,
) -> None:
    drive_root = tmp_path / "downloads"
    alt_directory_format = Path(
        "{site_name} Vault/{content_type}/{user_username}/{value}/{media_type}"
    )
    performer_root = drive_root / "OnlyFans Vault" / "Posts" / "tester"
    performer_root.mkdir(parents=True)

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        alt_directory_formats=[alt_directory_format],
        drives=[Drive(directories=[drive_root])],
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.relative_path == Path(
        "OnlyFans Vault", "Posts", "tester", "Images", "photo"
    )
    assert result.directory_format == alt_directory_format


@pytest.mark.parametrize("alias", ["OnlyFansImages", "OnlyFans Vault"])
def test_select_download_destination_reuses_existing_site_directory_alias_folder(
    tmp_path: Path, alias: str
) -> None:
    drive_root = tmp_path / "downloads"
    performer_root = drive_root / alias / "T" / "tester"
    performer_root.mkdir(parents=True)

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        site_directory_aliases={"onlyfans": [alias]},
        drives=[Drive(directories=[drive_root])],
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.relative_path == Path(
        alias, "T", "tester", "Posts", "Images", "photo"
    )


@pytest.mark.parametrize("alias", ["OnlyFansImages", "OnlyFans Vault"])
def test_select_download_destination_preserves_alias_for_dynamic_root_format(
    tmp_path: Path, alias: str
) -> None:
    drive_root = tmp_path / "downloads"
    performer_root = drive_root / alias / "Posts" / "tester"
    performer_root.mkdir(parents=True)

    setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{content_type}/{user_username}/{value}/{media_type}"
        ),
        site_directory_aliases={"onlyfans": [alias]},
        drives=[Drive(directories=[drive_root])],
    )

    result = select_download_destination(
        setup,
        site_name="OnlyFans",
        performer_username="tester",
        api_type="Posts",
        value="Images",
        media_type="photo",
    )

    assert result.relative_path == Path(
        alias, "Posts", "tester", "Images", "photo"
    )


def test_config_export_splits_mixed_mount_drive_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_mount(path: Path) -> str:
        return "/mnt/drive-a" if "drive-a" in str(path) else "/mnt/drive-b"

    monkeypatch.setattr(config_module, "_resolve_mount_point", fake_mount)

    setup = DownloadPathSetup(
        drives=[
            Drive(
                minimum_space=20 * 1024**3,
                store=False,
                overflow=True,
                directories=[
                    Path("/virtual/drive-a/downloads"),
                    Path("/virtual/drive-b/downloads"),
                    Path("/virtual/drive-a/archive"),
                ],
            )
        ]
    )

    # Mount normalization belongs to an explicit write, not model loading.
    assert len(setup.drives) == 1
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = setup
    config.persistence_payload()

    assert len(setup.drives) == 2
    assert setup.drives[0].directories == [
        Path("/virtual/drive-a/downloads"),
        Path("/virtual/drive-a/archive"),
    ]
    assert setup.drives[1].directories == [Path("/virtual/drive-b/downloads")]
    assert setup.drives[0].minimum_space == setup.drives[1].minimum_space
    assert setup.drives[0].store is False
    assert setup.drives[0].scan_existing is True
    assert setup.drives[1].overflow is True


@pytest.mark.asyncio
async def test_add_directory_appends_to_matching_mount_drive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    drive_a_directory = tmp_path / "drive-a" / "downloads"
    drive_b_directory = tmp_path / "drive-b" / "downloads"
    new_drive_b_directory = tmp_path / "drive-b" / "archive"
    drive_a_directory.mkdir(parents=True)
    drive_b_directory.mkdir(parents=True)

    monkeypatch.setattr(
        system_routes,
        "_get_mount_point",
        lambda path: "/mnt/drive-a" if "drive-a" in path else "/mnt/drive-b",
    )

    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        drives=[
            Drive(minimum_space=10, directories=[drive_a_directory]),
            Drive(minimum_space=20, directories=[drive_b_directory]),
        ]
    )
    persisted_configs: list[UltimaScraperCollectionConfig] = []

    def persist_config(
        working_config: UltimaScraperCollectionConfig,
        **_kwargs: object,
    ) -> SimpleNamespace:
        persisted_configs.append(working_config)
        return SimpleNamespace(version=2)

    propagate = AsyncMock(return_value=None)
    monkeypatch.setattr(system_routes, "_persist_storage_config", persist_config)
    monkeypatch.setattr(system_routes, "propagate_storage_config", propagate)

    response = await add_directory(
        AddDirectoryRequest(
            drive_path="/mnt/drive-b",
            directory_path=str(new_drive_b_directory),
            setup_type="download",
            target_backend_id="backend-test",
            expected_version=1,
        ),
        config,
        SimpleNamespace(instance_id="backend-test"),
    )

    assert response.success is True
    assert len(persisted_configs) == 1
    persisted_setup = persisted_configs[0].settings.download_setup
    assert len(persisted_setup.drives) == 2
    assert persisted_setup.drives[0].directories == [drive_a_directory]
    assert persisted_setup.drives[1].directories == [
        drive_b_directory,
        new_drive_b_directory,
    ]
    assert config.settings.download_setup.drives[1].directories == [drive_b_directory]
    propagate.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_directory_defaults_new_drive_scan_existing_to_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    new_directory = tmp_path / "drive-c" / "downloads"

    monkeypatch.setattr(system_routes, "_get_mount_point", lambda _path: "/mnt/drive-c")

    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(drives=[])
    persisted_configs: list[UltimaScraperCollectionConfig] = []

    def persist_config(
        working_config: UltimaScraperCollectionConfig,
        **_kwargs: object,
    ) -> SimpleNamespace:
        persisted_configs.append(working_config)
        return SimpleNamespace(version=2)

    propagate = AsyncMock(return_value=None)
    monkeypatch.setattr(system_routes, "_persist_storage_config", persist_config)
    monkeypatch.setattr(system_routes, "propagate_storage_config", propagate)

    response = await add_directory(
        AddDirectoryRequest(
            drive_path="/mnt/drive-c",
            directory_path=str(new_directory),
            setup_type="download",
            target_backend_id="backend-test",
            expected_version=1,
        ),
        config,
        SimpleNamespace(instance_id="backend-test"),
    )

    assert response.success is True
    assert len(persisted_configs) == 1
    persisted_setup = persisted_configs[0].settings.download_setup
    assert len(persisted_setup.drives) == 1
    assert persisted_setup.drives[0].directories == [new_directory]
    assert persisted_setup.drives[0].scan_existing is False
    assert config.settings.download_setup.drives == []
    propagate.assert_awaited_once()


def _find_only_setup(*roots: Path) -> DownloadPathSetup:
    return DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        site_directory_aliases={"onlyfans": ["OnlyFansImages", "OnlyFans (G)"]},
        find_only_site_directories={"OnlyFans": ["onlyfansimages"]},
        drives=[Drive(directories=list(roots))],
    )


def _select_tester(setup: DownloadPathSetup) -> UserDirectorySelection:
    return select_user_destination(
        user_id=7,
        usernames=["tester"],
        site_name="OnlyFans",
        user_manager=None,
        config=_config_for(setup),
    )


def _config_for(setup: DownloadPathSetup) -> UltimaScraperCollectionConfig:
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = setup
    return config


def test_a_find_only_alias_folder_is_found_but_not_downloaded_into(tmp_path: Path) -> None:
    old = tmp_path / "drive" / "OnlyFansImages" / "T" / "tester"
    old.mkdir(parents=True)

    result = _select_tester(_find_only_setup(tmp_path / "drive"))

    assert result.performer_relative_path == Path("OnlyFans/T/tester")
    assert result.site_name == "OnlyFans"
    assert result.kept_root == tmp_path / "drive"
    assert result.kept_relative_path == Path("OnlyFansImages/T/tester")


def test_the_find_only_folder_is_still_read_once_the_new_folder_exists(tmp_path: Path) -> None:
    (tmp_path / "drive" / "OnlyFansImages" / "T" / "tester").mkdir(parents=True)
    (tmp_path / "drive" / "OnlyFans" / "T" / "tester").mkdir(parents=True)

    result = _select_tester(_find_only_setup(tmp_path / "drive"))

    assert result.performer_relative_path == Path("OnlyFans/T/tester")
    assert result.kept_relative_path == Path("OnlyFansImages/T/tester")


def test_an_alias_that_is_not_find_only_is_still_downloaded_into(tmp_path: Path) -> None:
    folder = tmp_path / "drive" / "OnlyFans (G)" / "T" / "tester"
    folder.mkdir(parents=True)

    result = _select_tester(_find_only_setup(tmp_path / "drive"))

    assert result.performer_relative_path == Path("OnlyFans (G)/T/tester")
    assert result.kept_root is None


def test_a_find_only_folder_reached_through_an_alt_format_is_not_downloaded_into(tmp_path: Path) -> None:
    (tmp_path / "drive" / "OnlyFans (G)" / "T" / "tester").mkdir(parents=True)
    setup = _find_only_setup(tmp_path / "drive")
    setup.alt_directory_formats = [
        Path("{site_name} (G)/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}")
    ]
    setup.site_directory_aliases = {}
    setup.find_only_site_directories = {"onlyfans": ["OnlyFans (G)"]}

    result = _select_tester(setup)

    assert result.performer_relative_path == Path("OnlyFans/T/tester")
    assert result.kept_relative_path == Path("OnlyFans (G)/T/tester")


def test_files_already_in_the_find_only_folder_do_not_count_against_free_space(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "drive" / "OnlyFansImages" / "T" / "tester").mkdir(parents=True)
    monkeypatch.setattr(
        "ultima_scraper_backend.job_system.drive_selection.shutil.disk_usage",
        lambda path: SimpleNamespace(free=1024),
    )

    result = select_user_destination(
        user_id=7,
        usernames=["tester"],
        site_name="OnlyFans",
        user_manager=None,
        config=_config_for(_find_only_setup(tmp_path / "drive")),
        required_space=10**12,
    )

    assert result.performer_relative_path == Path("OnlyFans/T/tester")
