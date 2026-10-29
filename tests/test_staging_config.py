from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from ultima_scraper_backend.api.routes.settings import (
    DRMConfig as SettingsDRMConfig,
)
from ultima_scraper_backend.api.routes.settings import (
    SettingsUpdateRequest,
    _merge_model_update,
)
from ultima_scraper_backend.api.routes.setup import DRMConfig as SetupDRMConfig
from ultima_scraper_backend.config import (
    DownloadPathSetup,
    Drive,
    StagingDirectory,
    StagingPolicy,
    StagingUsage,
    UltimaScraperCollectionConfig,
)


def test_local_drm_request_models_reject_legacy_decrypt_media_path() -> None:
    payload = {
        "device_client_blob_filepath": "/tmp/blob",
        "device_private_key_filepath": "/tmp/key",
        "decrypt_media_path": "/tmp/legacy",
    }

    with pytest.raises(ValidationError):
        SettingsDRMConfig.model_validate(payload)

    with pytest.raises(ValidationError):
        SetupDRMConfig.model_validate(payload)


def test_config_save_and_load_use_staging_directories_without_legacy_decrypt_path(
    tmp_path: Path,
) -> None:
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup.staging_directories = [
        StagingDirectory(
            path=tmp_path / "staging",
            usage=[
                StagingUsage.DOWNLOADS,
                StagingUsage.MERGE,
                StagingUsage.DRM,
            ],
            policy=[StagingPolicy.DRM_ONLY],
        )
    ]

    saved_payload = config.persistence_payload()
    assert "decrypt_media_path" not in saved_payload["settings"]["drm"]
    assert saved_payload["settings"]["download_setup"]["staging_directories"] == [
        {
            "path": str(tmp_path / "staging"),
            "usage": ["downloads", "merge", "drm"],
            "policy": ["drm_only"],
            "min_free_bytes": 0,
        }
    ]

    saved_payload["settings"]["drm"]["decrypt_media_path"] = str(tmp_path / "legacy")

    loaded_config = UltimaScraperCollectionConfig(**saved_payload)

    assert not hasattr(loaded_config.settings.drm, "decrypt_media_path")
    assert loaded_config.settings.download_setup.staging_directories[0].path == (
        tmp_path / "staging"
    )
    assert loaded_config.settings.download_setup.staging_directories[0].policy == [
        StagingPolicy.DRM_ONLY
    ]


def test_config_save_and_load_round_trips_alt_directory_formats() -> None:
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup.alt_directory_formats = [
        Path(
            "{site_name} Vault/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        Path("Archive/{site_name}/{user_id}/{content_type}/{value}/{media_type}"),
    ]

    saved_payload = config.persistence_payload()
    assert saved_payload["settings"]["download_setup"]["alt_directory_formats"] == [
        "{site_name} Vault/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}",
        "Archive/{site_name}/{user_id}/{content_type}/{value}/{media_type}",
    ]

    loaded_config = UltimaScraperCollectionConfig(**saved_payload)

    assert loaded_config.settings.download_setup.alt_directory_formats == [
        Path(
            "{site_name} Vault/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        ),
        Path("Archive/{site_name}/{user_id}/{content_type}/{value}/{media_type}"),
    ]


def test_download_path_setup_rejects_alt_directory_formats_without_unique_tokens() -> (
    None
):
    with pytest.raises(
        ValidationError, match="alt directory format must include one of"
    ):
        DownloadPathSetup(
            alt_directory_formats=[
                Path("{site_name}/{content_type}/{value}/{media_type}")
            ]
        )


@pytest.mark.parametrize("alias", ["../escape", "folder/name", "/absolute"])
def test_download_path_setup_rejects_directory_alias_paths(alias: str) -> None:
    with pytest.raises(ValidationError, match="single directory names"):
        DownloadPathSetup(site_directory_aliases={"onlyfans": [alias]})


def test_merge_model_update_preserves_unspecified_download_setup_fields(
    tmp_path: Path,
) -> None:
    config = UltimaScraperCollectionConfig()
    original_drive = tmp_path / "downloads"
    config.settings.download_setup = DownloadPathSetup(
        drives=[Drive(directories=[original_drive])],
        alt_directory_formats=[
            Path(
                "{site_name} Vault/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
            )
        ],
        directory_format=Path("{site_name}/{user_username}"),
        filename_format=Path("{filename}.{ext}"),
        overwrite_files=False,
    )

    update = SettingsUpdateRequest.model_validate(
        {
            "download_setup": {
                "directory_format": "{site_name}/{first_username_letter}/{user_username}"
            }
        }
    )
    assert update.download_setup is not None

    _merge_model_update(
        config.settings.download_setup,
        update.download_setup,
        {"directory_format": "{site_name}/{first_username_letter}/{user_username}"},
    )

    assert config.settings.download_setup.directory_format == Path(
        "{site_name}/{first_username_letter}/{user_username}"
    )
    assert config.settings.download_setup.filename_format == Path("{filename}.{ext}")
    assert config.settings.download_setup.overwrite_files is False
    assert config.settings.download_setup.alt_directory_formats == [
        Path(
            "{site_name} Vault/{first_username_letter}/{user_username}/{content_type}/{value}/{media_type}"
        )
    ]
    assert config.settings.download_setup.drives[0].directories == [original_drive]


def test_config_save_and_load_round_trips_site_directory_aliases() -> None:
    config = UltimaScraperCollectionConfig()
    config.settings.download_setup.site_directory_aliases = {
        "onlyfans": ["OnlyFansImages", "OnlyFans Vault"],
        "fansly": ["FanslyImages"],
    }

    saved_payload = config.persistence_payload()
    assert saved_payload["settings"]["download_setup"]["site_directory_aliases"] == {
        "onlyfans": ["OnlyFansImages", "OnlyFans Vault"],
        "fansly": ["FanslyImages"],
    }

    loaded_config = UltimaScraperCollectionConfig(**saved_payload)

    assert loaded_config.settings.download_setup.site_directory_aliases == {
        "onlyfans": ["OnlyFansImages", "OnlyFans Vault"],
        "fansly": ["FanslyImages"],
    }
    assert loaded_config.settings.download_setup.get_site_directory_aliases("onlyfans") == [
        "OnlyFansImages",
        "OnlyFans Vault",
    ]


def test_merge_model_update_updates_site_directory_aliases(tmp_path: Path) -> None:
    config = UltimaScraperCollectionConfig()
    original_drive = tmp_path / "downloads"
    config.settings.download_setup = DownloadPathSetup(
        drives=[Drive(directories=[original_drive])],
        site_directory_aliases={"onlyfans": ["OldAlias"]},
    )

    update = SettingsUpdateRequest.model_validate(
        {
            "download_setup": {
                "site_directory_aliases": {"onlyfans": ["OnlyFansImages", "OnlyFans Vault"]}
            }
        }
    )
    assert update.download_setup is not None

    _merge_model_update(
        config.settings.download_setup,
        update.download_setup,
        {"site_directory_aliases": {"onlyfans": ["OnlyFansImages", "OnlyFans Vault"]}},
    )

    assert config.settings.download_setup.site_directory_aliases == {
        "onlyfans": ["OnlyFansImages", "OnlyFans Vault"]
    }
    assert config.settings.download_setup.drives[0].directories == [original_drive]
