import os
import json
import copy
import extra_classes.make_settings as make_settings


def get_config(config_path):
    if os.path.isfile(config_path):
        if os.stat(config_path).st_size > 0:
            json_config = json.load(open(config_path))
        else:
            json_config = {}
    else:
        json_config = {}
    file_name = os.path.basename(config_path)
    json_config2 = json.loads(json.dumps(make_settings.config(
        **json_config), default=lambda o: o.__dict__))
    if json_config != json_config2:
        update_config(json_config2, file_name=file_name)
    if not json_config:
        input("The .settings\\config.json file has been created. Fill in whatever you need to fill in and then press enter when done.\n")
        json_config2 = json.load(open(config_path))

    json_config = copy.deepcopy(json_config2)
    return json_config, json_config2


def update_config(json_config, file_name="config.json"):
    directory = '.settings'
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, file_name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(json_config, f, ensure_ascii=False, indent=2)
