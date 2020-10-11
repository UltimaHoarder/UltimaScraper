#!/usr/bin/env python3
from os.path import dirname as up
import urllib.parse as urlparse
import shutil
from datetime import datetime
import json
import os
import sys
from multiprocessing.dummy import Pool as ThreadPool
from itertools import product


def fix_metadata(posts, json_settings, username, site_name, metadata_categories):
    def start(post, metadata_categories):
        model_folder = ""
        for model in post:
            model_folder = model.directory
            metadata_categories2 = metadata_categories
            meta_categories = list(os.path.split(metadata_categories2))
            q = main_helper.find_between(
                model_folder, *meta_categories).replace(os.sep, "")
            meta_categories.insert(-1, q)
            categories = os.path.join(*meta_categories)
            file_directory_formatted = model.directory.split(categories)
            if len(file_directory_formatted) > 0:
                file_directory_formatted = file_directory_formatted[-1]
                model.directory = model_folder.replace(
                    file_directory_formatted, "")
            if model.links:
                path = urlparse.urlparse(model.links[0]).path
            else:
                path = model.filename
            filename = os.path.basename(path)
            filepath = os.path.join(model_folder, filename)
            post_id = str(model.post_id)
            filename, ext = os.path.splitext(filename)
            ext = ext.replace(".", "")
            sort_free_paid_posts = json_settings.get(
                "sort_free_paid_posts", False)
            if sort_free_paid_posts:
                q = "Free"
                if model.paid:
                    q = "Paid"
                if q not in meta_categories:
                    meta_categories.insert(-1, q)
                metadata_categories2 = os.path.join(*meta_categories)
            model.directory = model.directory.replace(
                categories, metadata_categories2)
            file_directory_format = json_settings["file_directory_format"]
            file_name_format = json_settings["file_name_format"]
            date_format = json_settings["date_format"]
            text_length = json_settings["text_length"]
            download_path = json_settings["download_paths"]
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
                    self.file_directory_format = file_directory_format
                    self.file_name_format = file_name_format
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
                    if not os.path.isfile(new_format):
                        shutil.move(filepath, new_format)
                return new_format, filepath
            if os.path.isfile(filepath):
                filepath, old_filepath = update(filepath)
            else:
                folder = os.path.dirname(filepath)
                folder = os.path.abspath(folder)
                while not os.path.exists(folder):
                    print(f"NOT FOUND: {folder}\n")
                    if os.path.exists(reformat.directory):
                        folder = reformat.directory
                        continue
                    last_path = folder.split(
                        username+os.sep)
                    last_path = last_path[1] if len(
                        last_path) > 1 else last_path[0]
                    last_path = last_path.replace(file_directory_formatted, "")
                    directory = main_helper.get_directory(
                        download_path, site_name)
                    folder = os.path.join(directory, username, last_path)
                    os.makedirs(folder, exist_ok=True)
                    reformat.directory = folder
                print(f"FOUND: {folder}\n")
                files = os.listdir(folder)
                y = [file_ for file_ in files if filename in file_]
                if y:
                    y = y[0]
                    filepath = os.path.join(folder, y)
                    filepath, old_filepath = update(filepath)
            model.filename = os.path.basename(filepath)
        return model_folder
    pool = ThreadPool()
    old_folders = pool.starmap(start, product(
        posts, [metadata_categories]))
    old_folders = list(dict.fromkeys(old_folders))
    for old_folder in old_folders:
        if "Posts" in old_folder:
            print
    return posts


def start(metadata_filepath, json_settings):
    if os.path.getsize(metadata_filepath) > 0:
        metadatas = json.load(open(metadata_filepath, encoding='utf-8'))
        metadatas2 = prepare_metadata(metadatas).items
        model_path = up(up(metadata_filepath))
        username = os.path.basename(model_path)
        site_name = os.path.basename(up(up(up(metadata_filepath))))
        metadata_filename = os.path.basename(metadata_filepath)
        name = metadata_filename.split(".")[0]
        for metadata in metadatas2:
            category = os.path.join(name, metadata.type)
            metadata.valid = fix_metadata(
                metadata.valid, json_settings, username, site_name, category)
            metadata.invalid = fix_metadata(
                metadata.invalid, json_settings, username, site_name, category)
        metadatas2 = json.loads(json.dumps(
            metadatas2, default=lambda o: o.__dict__))
        if metadatas != metadatas2:
            main_helper.update_metadata(metadata_filepath, metadatas2)
        return metadatas2


if __name__ == "__main__":
    # WORK IN PROGRESS
    import extra_helpers.main_helper as main_helper2
    directory = os.path.abspath(os.path.join(
        os.pardir, os.pardir))
    settings_directory = os.path.join(directory, ".settings")
    if os.path.exists(settings_directory):
        print
    else:
        while not os.path.exists(settings_directory):
            config = os.path.join('.settings', 'config.json')
            json_config, json_config2 = main_helper2.get_config(config)
            directory = json_config["ofd_directory"]
            if not directory:
                input(
                    "Add the OnlyFans Datascraper directory to .settings/config.json and press enter\n")
                continue
            settings_directory = os.path.join(directory, ".settings")
    while True:
        config = os.path.join(settings_directory, 'config.json')
        sys.path.append(directory)
        import helpers.main_helper as main_helper
        from classes.prepare_metadata import prepare_metadata
        json_config, json_config = main_helper.get_config(config)
        if not json_config:
            input(
                "Add the OnlyFans Datascraper config filepath to .settings/config.json and press enter\n")
            continue

        print
        json_config = json_config["supported"]
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
        match = ["All", "OnlyFans", "Patreon", "StarsAVN", "4Chan", "BBWChan"]
        choices = list(zip(choices, match))
        x = 1
        x = int(input())
        if x == 0:
            del choices[0]
        else:
            choices = [choices[x]]
        for choice in choices:
            name = choice[1]
            choice = choice[0]
            json_settings = json_config[choice]["settings"]
            download_paths = json_settings["download_paths"]
            directory = main_helper.get_directory(download_paths, name)
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
                        l = os.listdir(type_metadata)
                        x = []
                        ext = ".json"
                        for item in l:
                            if ext in item:
                                path = os.path.join(type_metadata, item)
                                filename, ext = os.path.splitext(item)
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
else:
    import helpers.main_helper as main_helper
    from classes.prepare_metadata import prepare_metadata
