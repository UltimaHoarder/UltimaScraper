import os
import sys
from pathlib import Path
from sys import exit
from typing import Any


def version_check():
    version_info = sys.version_info
    if version_info < (3, 10):
        version_info = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        string = f"You're executing the script with Python {version_info}. Execute the script with Python 3.10.1+"
        print(string)
        exit(0)


# Updating any outdated config values


def check_start_up():
    from ultima_scraper_api.managers.storage_managers.filesystem_manager import (
        FilesystemManager,
    )

    fsm = FilesystemManager()
    fsm.check()

    version_check()
    check_config(fsm.settings_directory)
    check_profiles(fsm.settings_directory, fsm.profiles_directory)


def check_config(directory: Path):
    import ultima_scraper_api.helpers.main_helper as main_helper

    config_path = directory.joinpath("config.json")
    json_config, _updated = main_helper.get_config(config_path)
    return json_config


def check_profiles(settings_directory: Path, profiles_directory: Path):
    import ultima_scraper_api.helpers.main_helper as main_helper
    from ultima_scraper_api.apis.fansly.classes.extras import (
        auth_details as fansly_auth_details,
    )
    from ultima_scraper_api.apis.onlyfans.classes.extras import (
        auth_details as onlyfans_auth_details,
    )

    # config, _updated = main_helper.get_config(config_path)
    matches = ["OnlyFans", "Fansly"]
    for string_match in matches:
        profile_site_directory = profiles_directory.joinpath(string_match)
        if os.path.exists(profile_site_directory):
            e = os.listdir(profile_site_directory)
            e = [os.path.join(profile_site_directory, x, "auth.json") for x in e]
            e = [x for x in e if os.path.exists(x)]
            if e:
                continue
        default_profile_directory = profile_site_directory.joinpath("default")
        os.makedirs(default_profile_directory, exist_ok=True)
        auth_filepath = default_profile_directory.joinpath("auth.json")
        if not os.path.exists(auth_filepath):
            new_item: dict[str, Any] = {}
            match string_match:
                case "OnlyFans":
                    new_item["auth"] = onlyfans_auth_details().export()

                case "Fansly":
                    new_item["auth"] = fansly_auth_details().export()

                case _:
                    continue
            main_helper.export_json(new_item, auth_filepath)
            main_helper.prompt_modified(
                f"{auth_filepath} has been created. Fill in the relevant details and then press enter to continue.",
                auth_filepath,
            )
