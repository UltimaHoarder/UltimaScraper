from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import ultima_scraper_backend.api.routes.files as files_module
from ultima_scraper_backend.api.routes.files import (
    UsernameDirectoryResult,
    _build_directory_candidates,
    _build_user_directory_relpaths,
    _resolve_media_path,
    _search_username_directories,
)
from ultima_scraper_backend.config import (
    DownloadPathSetup,
    Drive,
    UltimaScraperCollectionConfig,
)


def _build_config(root: Path) -> UltimaScraperCollectionConfig:
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        alt_directory_formats=[
            Path(
                "{site_name} Vault/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
            )
        ],
        filename_format=Path("{media_filename}.{media_ext}"),
        drives=[Drive(directories=[root])],
    )
    return config


def test_build_directory_candidates_include_alt_formats_in_order(
    tmp_path: Path,
) -> None:
    root = tmp_path / "downloads"
    root.mkdir()
    config = _build_config(root)

    candidates = _build_directory_candidates(
        config,
        site_name="onlyfans",
        user_id=2468,
        username="tester",
        content_type="Posts",
        content_value="Paid",
        media_type="video",
        media_id=123,
        created_at=None,
    )

    assert candidates == [
        root / "OnlyFans" / "T" / "tester" / "Posts" / "Paid" / "Videos",
        root / "OnlyFans Vault" / "T" / "tester" / "Posts" / "Paid" / "Videos",
    ]


def test_build_directory_candidates_support_legacy_first_letter_token(
    tmp_path: Path,
) -> None:
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_letter}/{model_username}/{api_type}/{value}/{media_type}"
        ),
        filename_format=Path("{filename}.{ext}"),
        drives=[Drive(directories=[tmp_path])],
    )

    candidates = _build_directory_candidates(
        config,
        site_name="onlyfans",
        user_id=2468,
        username="tester",
        content_type="Posts",
        content_value="Free",
        media_type="image",
        media_id=123,
        created_at=None,
    )

    assert candidates == [
        tmp_path / "OnlyFans" / "T" / "tester" / "Posts" / "Free" / "Images"
    ]


def test_search_username_directories_finds_alt_matches(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    alt_directory = root / "OnlyFans Vault" / "T" / "tester"
    alt_directory.mkdir(parents=True)
    config = _build_config(root)

    matches, checked_patterns, rel_pattern = _search_username_directories(
        config=config,
        usernames=["tester"],
        site_name="onlyfans",
    )

    assert [match.path for match in matches] == [str(alt_directory)]
    assert str(root / "OnlyFans Vault" / "T" / "tester") in checked_patterns
    assert rel_pattern == "OnlyFans Vault/T/tester"


@pytest.mark.asyncio
async def test_search_username_directories_offloads_scan_to_thread(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _build_config(tmp_path / "downloads")
    to_thread_mock = AsyncMock(
        return_value=(
            [UsernameDirectoryResult(root="/root", path="/root/OnlyFans/T/tester")],
            ["/root/OnlyFans/T/tester"],
            "OnlyFans/T/tester",
        )
    )

    monkeypatch.setattr(
        files_module,
        "_resolve_all_usernames",
        lambda **_kwargs: (123, ["tester"]),
    )
    monkeypatch.setattr(files_module.asyncio, "to_thread", to_thread_mock)

    response = await files_module.search_username_directories(
        username="tester",
        user_id=None,
        site="onlyfans",
        config=config,
    )

    assert response.success is True
    assert [match.path for match in response.matches] == ["/root/OnlyFans/T/tester"]
    to_thread_mock.assert_awaited_once()
    assert (
        to_thread_mock.await_args.args[0] is files_module._search_username_directories
    )
    assert to_thread_mock.await_args.args[1:] == (config, ["tester"], "onlyfans")


def test_resolve_media_path_prefers_canonical_before_alt(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    canonical_file = (
        root / "OnlyFans" / "T" / "tester" / "Posts" / "Paid" / "Videos" / "clip.mp4"
    )
    alt_file = (
        root
        / "OnlyFans Vault"
        / "T"
        / "tester"
        / "Posts"
        / "Paid"
        / "Videos"
        / "clip.mp4"
    )
    canonical_file.parent.mkdir(parents=True)
    alt_file.parent.mkdir(parents=True)
    canonical_file.write_text("canonical")
    alt_file.write_text("alt")
    config = _build_config(root)

    resolved = _resolve_media_path(
        config=config,
        site_name="onlyfans",
        user_id=2468,
        username="tester",
        filenames=["clip.mp4"],
        content_type="Posts",
        content_values=["Paid"],
        media_type="video",
        media_id=123,
        created_at=None,
    )

    assert resolved == canonical_file


def test_resolve_media_path_uses_alt_when_canonical_missing(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    alt_file = (
        root
        / "OnlyFans Vault"
        / "T"
        / "tester"
        / "Posts"
        / "Paid"
        / "Videos"
        / "clip.mp4"
    )
    alt_file.parent.mkdir(parents=True)
    alt_file.write_text("alt")
    config = _build_config(root)

    resolved = _resolve_media_path(
        config=config,
        site_name="onlyfans",
        user_id=2468,
        username="tester",
        filenames=["clip.mp4"],
        content_type="Posts",
        content_values=["Paid"],
        media_type="video",
        media_id=123,
        created_at=None,
    )

    assert resolved == alt_file


def test_build_user_directory_relpaths_uses_site_directory_aliases() -> None:
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        site_directory_aliases={
            "onlyfans": ["OnlyFansImages", "OnlyFans Vault"]
        },
    )

    rel_paths = _build_user_directory_relpaths(
        config=config,
        site_name="onlyfans",
        username="tester",
    )

    assert rel_paths == [
        "OnlyFans/T/tester",
        "OnlyFansImages/T/tester",
        "OnlyFans Vault/T/tester",
    ]


def test_build_user_directory_relpaths_without_aliases_has_only_canonical() -> None:
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        site_directory_aliases={},
    )

    rel_paths = _build_user_directory_relpaths(
        config=config,
        site_name="onlyfans",
        username="tester",
    )

    assert rel_paths == ["OnlyFans/T/tester"]


def test_search_username_directories_finds_site_directory_alias_matches(
    tmp_path: Path,
) -> None:
    root = tmp_path / "downloads"
    alias_directory = root / "OnlyFansImages" / "T" / "tester"
    alias_directory.mkdir(parents=True)
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup = DownloadPathSetup(
        directory_format=Path(
            "{site_name}/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        site_directory_aliases={"onlyfans": ["OnlyFansImages"]},
        drives=[Drive(directories=[root])],
    )

    matches, checked_patterns, rel_pattern = _search_username_directories(
        config=config,
        usernames=["tester"],
        site_name="onlyfans",
    )

    assert [match.path for match in matches] == [str(alias_directory)]
    assert str(root / "OnlyFansImages" / "T" / "tester") in checked_patterns
    assert rel_pattern == "OnlyFansImages/T/tester"
