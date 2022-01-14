from pathlib import Path
from sys import exit
import sys
import os
from os.path import dirname as up
from typing import Any

if getattr(sys, "frozen", False):
    path = up(sys.executable)
else:
    path = up(up(os.path.realpath(__file__)))
os.chdir(path)


def version_check():
    version_info = sys.version_info
    if version_info < (3, 10):
        version_info = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        string = f"You're executing the script with Python {version_info}. Execute the script with Python 3.10.1+"
        print(string)
        exit(0)


# Updating any outdated config values


def check_config():
    import helpers.main_helper as main_helper

    config_path = Path(".settings", "config.json")
    json_config, _updated = main_helper.get_config(config_path)
    return json_config


def check_profiles():
    config_path = Path(".settings", "config.json")
    import helpers.main_helper as main_helper
    from apis.onlyfans.onlyfans import auth_details as onlyfans_auth_details
    from apis.fansly.fansly import auth_details as fansly_auth_details
    from apis.starsavn.starsavn import auth_details as starsavn_auth_details

    config, _updated = main_helper.get_config(config_path)
    settings = config.settings
    profile_directories = settings.profile_directories
    profile_directory = profile_directories[0]
    matches = ["OnlyFans", "Fansly", "StarsAVN"]
    for string_match in matches:
        profile_site_directory = profile_directory.joinpath(string_match)
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

                case "StarsAVN":
                    new_item["auth"] = starsavn_auth_details().export()
                case _:
                    continue
            main_helper.export_json(new_item, auth_filepath)
            main_helper.prompt_modified(
                f"{auth_filepath} has been created. Fill in the relevant details and then press enter to continue.",
                auth_filepath,
            )
        print
    print
