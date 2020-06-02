import sys
import os
import json
import helpers.main_helper as main_helper


def version_check():
    if sys.version_info.major < 3:
        string = "The script may not work with Python version 3.7 and below \n"
        string += "Execute the script with Python 3.8 \n"
        string += "Press enter to continue"
        input(string)


def check_config():
    path = os.path.join('.settings', 'config.json')
    if os.path.isfile(path):
        json_config = json.load(open(path))
        for key, value in json_config["supported"].items():
            file_name_format = value["settings"]["file_name_format"]
            top = ["{id}"]
            bottom = ["{media_id}"]
            z = list(zip(top, bottom))
            for x in z:
                if x[0] in file_name_format:
                    value["settings"]["file_name_format"] = file_name_format.replace(
                        x[0], x[1])
                    new = value["settings"]["file_name_format"]
                    print("Changed "+file_name_format+" to "+new + " for "+key)
                    print
        main_helper.update_config(json_config)
