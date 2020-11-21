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
    if json_config != json_config2:
        input(
            f"The .settings\\{file_name} file has been updated. Fill in whatever you need to fill in and then press enter when done.\n")


# def check_extra_auth():
#     file_name = "extra_auth.json"
#     path = os.path.join('.settings', file_name)
#     json_config, json_config2 = main_helper.get_config(
#         path)
#     if json_config:
#         if json_config != json_config2:
#             input(
#                 f"The .settings\\{file_name} file has been updated. Fill in whatever you need to fill in and then press enter when done.\n")
