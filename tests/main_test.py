from sys import exit
import sys
import os
from os.path import dirname as up

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
    file_name = "config.json"
    path = os.path.join(".settings", file_name)
    import helpers.main_helper as main_helper

    json_config, updated = main_helper.get_config(path)
    if updated:
        main_helper.prompt_modified(
            f"The .settings\\{file_name} file has been updated. Fill in whatever you need to fill in and then press enter when done.\n",
            path,
        )
    return json_config


def check_profiles():
    file_name = "config.json"
    path = os.path.join(".settings", file_name)
    import helpers.main_helper as main_helper
    from apis.onlyfans.onlyfans import auth_details as onlyfans_auth_details
    from apis.fansly.fansly import auth_details as fansly_auth_details
    from apis.starsavn.starsavn import auth_details as starsavn_auth_details

    json_config, json_config2 = main_helper.get_config(path)
    json_settings = json_config["settings"]
    profile_directories = json_settings["profile_directories"]
    profile_directory = profile_directories[0]
    matches = ["OnlyFans", "Fansly", "StarsAVN"]
    for string_match in matches:
        q = os.path.abspath(profile_directory)
        profile_site_directory = os.path.join(q, string_match)
        if os.path.exists(profile_site_directory):
            e = os.listdir(profile_site_directory)
            e = [os.path.join(profile_site_directory, x, "auth.json") for x in e]
            e = [x for x in e if os.path.exists(x)]
            if e:
                continue
        default_profile_directory = os.path.join(profile_site_directory, "default")
        os.makedirs(default_profile_directory, exist_ok=True)
        auth_filepath = os.path.join(default_profile_directory, "auth.json")
        if not os.path.exists(auth_filepath):
            new_item = {}
            match string_match:
                case "OnlyFans":
                    new_item["auth"] = onlyfans_auth_details().export()

                case "Fansly":
                    new_item["auth"] = fansly_auth_details().export()

                case "StarsAVN":
                    new_item["auth"] = starsavn_auth_details().export()
                case _:
                    continue
            main_helper.export_data(new_item, auth_filepath)
            main_helper.prompt_modified(
                f"{auth_filepath} has been created. Fill in the relevant details and then press enter to continue.",
                auth_filepath,
            )
        print
    print
