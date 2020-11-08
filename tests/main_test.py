import sys
import os
import json
import helpers.main_helper as main_helper


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
    json_config, json_config2 = main_helper.get_config(path)
    if json_config:
        new_settings = json_config["settings"].copy()
        for key, value in json_config["settings"].items():
            if key == "socks5_proxy":
                if not isinstance(value, list):
                    new_settings[key] = [value]
            if key == "global_user-agent":
                new_settings["global_user_agent"] = value
                del new_settings["global_user-agent"]
        json_config["settings"] = new_settings

        for key, value in json_config["supported"].items():
            settings = value["settings"]
            if "directory" in settings:
                if not settings["directory"]:
                    settings["directory"] = ["{site_name}"]
                settings["download_path"] = settings["directory"]
                del settings["directory"]
            if "download_path" in settings:
                settings["download_paths"] = [settings["download_path"]]
                del settings["download_path"]
            file_name_format = settings["file_name_format"]
            top = ["{id}"]
            bottom = ["{media_id}"]
            z = list(zip(top, bottom))
            for x in z:
                if x[0] in file_name_format:
                    settings["file_name_format"] = file_name_format.replace(
                        x[0], x[1])
                    new = settings["file_name_format"]
                    print("Changed "+file_name_format+" to "+new + " for "+key)
        if json_config != json_config2:
            main_helper.update_config(json_config)
            input(
                f"The .settings\\{file_name} file has been updated. Fill in whatever you need to fill in and then press enter when done.\n")


def check_extra_auth():
    file_name = "extra_auth.json"
    path = os.path.join('.settings', file_name)
    json_config, json_config2 = main_helper.get_config(
        path)
    if json_config:
        if json_config != json_config2:
            main_helper.update_config(json_config, file_name=file_name)
            input(
                f"The .settings\\{file_name} file has been updated. Fill in whatever you need to fill in and then press enter when done.\n")
