#!/usr/bin/env python3
import json
import os
import shutil
import sys
import urllib.parse as urlparse
from datetime import datetime
from os.path import dirname as up

import helpers.main_helper as main_helper
from classes.prepare_metadata import prepare_metadata


def fix_metadata(posts, json_settings, username, site_name):
    for post in posts:
        for model in post:
            model_folder = model.directory
            if model.links:
                path = urlparse.urlparse(model.links[0]).path
            else:
                path = model.filename
            filename = os.path.basename(path)
            filepath = os.path.join(model_folder, filename)
            filename, ext = os.path.splitext(filename)
            ext = ext.replace(".", "")
            format_path = json_settings["file_name_format"]
            date_format = json_settings["date_format"]
            text_length = json_settings["text_length"]
            download_path = json_settings["download_path"]
            today = datetime.today()
            today = today.strftime("%d-%m-%Y %H:%M:%S")

            class prepare_reformat(object):
                def __init__(self, option):
                    self.directory = option.get(
                        'directory')
                    self.post_id = option.get('post_id', "")
                    self.media_id = option.get('media_id', "")
                    self.filename = filename
                    self.text = main_helper.clean_text(option.get('text', ""))
                    self.ext = option.get('ext', ext)
                    self.date = option.get('postedAt', today)
                    self.username = option.get('username', username)
                    self.format_path = format_path
                    self.date_format = date_format
                    self.maximum_length = int(text_length)
            model2 = json.loads(json.dumps(
                model, default=lambda o: o.__dict__))
            reformat = prepare_reformat(model2)

            def update(filepath):
                temp = json.loads(json.dumps(
                    reformat, default=lambda o: o.__dict__))
                filepath = os.path.abspath(filepath)
                new_format = main_helper.reformat(**temp)
                new_format = os.path.abspath(new_format)
                if filepath != new_format:
                    shutil.move(filepath, new_format)
                return new_format
            if os.path.isfile(filepath):
                filepath = update(filepath)
            else:
                folder = os.path.dirname(filepath)
                folder = os.path.abspath(folder)
                while not os.path.exists(folder):
                    print("NOT FOUND: "+folder)
                    last_path = folder.split(username+"\\")[1]
                    directory = main_helper.get_directory(
                        download_path, site_name)
                    folder = os.path.join(directory, username, last_path)
                    reformat.directory = folder
                print("FOUND: "+folder)
                files = os.listdir(folder)
                y = [file_ for file_ in files if filename in file_]
                if y:
                    y = y[0]
                    filepath = os.path.join(folder, y)
                    filepath = update(filepath)
            model.filename = os.path.basename(filepath)
    return posts


def start(metadata_filepath, json_settings):
    metadatas = json.load(open(metadata_filepath))
    metadatas2 = prepare_metadata(metadatas).items
    username = os.path.basename(up(up(metadata_filepath)))
    site_name = os.path.basename(up(up(up(metadata_filepath))))
    for metadata in metadatas2:
        metadata.valid = fix_metadata(
            metadata.valid, json_settings, username, site_name)
        metadata.invalid = fix_metadata(
            metadata.invalid, json_settings, username, site_name)
    metadatas2 = json.loads(json.dumps(
        metadatas2, default=lambda o: o.__dict__))
    if metadatas != metadatas2:
        main_helper.update_metadata(metadata_filepath, metadatas2)
    return metadatas2


if __name__ == "__main__":
    sys.path.append('.')
    # WORK IN PROGRESS
    config = os.path.join('.settings', 'config.json')
    config_path = json.load(open(config))["parent_config"]
    if not config_path:
        input("Add the OnlyFans Datascraper config filepath to .settings/config.json and restart script")
        exit(0)
    json_config = json.load(open(config_path))["supported"]
    choices = ["All"] + list(json_config.keys())
    count = 0
    max_count = len(choices)
    string = ""
    for choice in choices:
        string += str(count) + " = "+choice
        count += 1
        if count < max_count:
            string += " | "
    print(string)
    match = ["All", "OnlyFans", "StarsAVN", "4Chan", "BBWChan"]
    choices = list(zip(choices, match))
    x = int(input())
    if x == 0:
        del choices[0]
    else:
        choices = [choices[x]]
    for choice in choices:
        name = choice[1]
        choice = choice[0]
        json_settings = json_config[choice]["settings"]
        download_path = json_settings["download_path"]
        directory = main_helper.get_directory(download_path, name)
        if "OFRenamer\\.sites" in directory:
            directory = os.path.join(up(up(config_path)), ".sites", name)
        content_folders = os.listdir(directory)
        # content_folders = ["queenarri"]
        models_folders2 = []
        if name in ["4Chan", "BBWChan"]:
            for models_folder in content_folders:
                directory2 = os.path.join(directory, models_folder)
                content_list = os.listdir(directory2)
                for content in content_list:
                    content = os.path.join(directory2, content)
                    x = main_helper.metadata_fixer(content)
                    models_folders2.append(content)
            continue
        else:
            for models_folder in content_folders:
                directory2 = os.path.join(directory, models_folder)
                models_folders2.append(directory2)
        content_folders = models_folders2
        for content_folder in content_folders:
            metadata_directory = os.path.join(content_folder, "Metadata")
            folders = []
            if os.path.exists(metadata_directory):
                folders = os.listdir(metadata_directory)
                matches = ["desktop.ini"]
                folders = [x for x in folders if x not in matches]
            if not folders:
                folders2 = os.listdir(content_folder)
                matches = ["Metadata", "desktop.ini"]
                folders2 = [x for x in folders2 if x not in matches]
                for folder in folders2:
                    type_metadata = os.path.join(
                        content_folder, folder, "Metadata")
                    if not os.path.exists(type_metadata):
                        continue
                    os.makedirs(metadata_directory, exist_ok=True)
                    files = os.listdir(type_metadata)
                    x = []
                    ext = ".json"
                    for file in files:
                        if ext in file:
                            path = os.path.join(type_metadata, file)
                            filename, ext = os.path.splitext(file)
                            metadata = json.load(open(path))
                            x.append(metadata)
                    filename = folder+ext
                    metadata_filepath = os.path.join(
                        metadata_directory, filename)
                    main_helper.update_metadata(metadata_filepath, x)
                    folders.append(filename)
            # folders = list(reversed(folders))
            for metadata_file in folders:
                metadata_filepath = os.path.join(
                    metadata_directory, metadata_file)
                start(metadata_filepath, json_settings)
