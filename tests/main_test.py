from apis.onlyfans.onlyfans import auth_details
from genericpath import exists
from re import L
import sys
import os


def version_check():
    version_info = sys.version_info
    python_version = f"{version_info.major}.{version_info.minor}"
    python_version = float(python_version)
    if python_version < 3.9:
        string = "Execute the script with Python 3.9 \n"
        string += "Press enter to continue"
        input(string)

# Updating any outdated config values


def check_config():
    file_name = "config.json"
    path = os.path.join('.settings', file_name)
    import helpers.main_helper as main_helper
    json_config, json_config2 = main_helper.get_config(path)
    if json_config != json_config2:
        input(
            f"The .settings\\{file_name} file has been updated. Fill in whatever you need to fill in and then press enter when done.\n")


def check_profiles():
    file_name = "config.json"
    path = os.path.join('.settings', file_name)
    import helpers.main_helper as main_helper
    json_config, json_config2 = main_helper.get_config(path)
    json_settings = json_config["settings"]
    profile_directories = json_settings["profile_directories"]
    profile_directory = profile_directories[0]
    matches = ["OnlyFans"]
    for match in matches:
        q = os.path.abspath(profile_directory)
        profile_site_directory = os.path.join(q, match)
        if os.path.exists(profile_site_directory):
            e = os.listdir(profile_site_directory)
            e = [os.path.join(profile_site_directory, x, "auth.json")
                 for x in e]
            e = [x for x in e if os.path.exists(x)]
            if e:
                continue
        default_profile_directory = os.path.join(
            profile_site_directory, "default")
        os.makedirs(default_profile_directory, exist_ok=True)
        auth_filepath = os.path.join(default_profile_directory, "auth.json")
        if not os.path.exists(auth_filepath):
            x = auth_details().__dict__
            main_helper.export_json(auth_filepath, x)
            print
        print
    print
