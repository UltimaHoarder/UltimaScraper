#!/usr/bin/env python3
from apis.api_helper import multiprocessing
from classes.prepare_metadata import format_types, prepare_reformat
import urllib.parse as urlparse
import shutil
from datetime import datetime
import os
from itertools import product


def fix_directories(posts, base_directory, site_name, api_type, media_type, username, all_files, json_settings):
    new_directories = []

    def fix_directory(post):
        new_post_dict = post.convert(keep_empty_items=True)
        for media in post.medias:
            if media.links:
                path = urlparse.urlparse(media.links[0]).path
            else:
                path = media.filename
            new_filename = os.path.basename(path)
            filename, ext = os.path.splitext(new_filename)
            ext = ext.replace(".", "")
            file_directory_format = json_settings["file_directory_format"]
            filename_format = json_settings["filename_format"]
            date_format = json_settings["date_format"]
            text_length = json_settings["text_length"]
            download_path = base_directory
            today = datetime.today()
            today = today.strftime("%d-%m-%Y %H:%M:%S")
            new_media_dict = media.convert(keep_empty_items=True)
            option = {}
            option = option | new_post_dict | new_media_dict
            option["site_name"] = site_name
            option["filename"] = filename
            option["api_type"] = api_type
            option["media_type"] = media_type
            option["ext"] = ext
            option["username"] = username
            option["date_format"] = date_format
            option["maximum_length"] = text_length
            option["directory"] = download_path
            prepared_format = prepare_reformat(option)
            file_directory = main_helper.reformat(
                prepared_format, file_directory_format)
            prepared_format.directory = file_directory
            old_filepath = ""
            x = [x for x in all_files if media.filename == os.path.basename(x)]
            if x:
                # media.downloaded = True
                old_filepath = x[0]
                old_filepath = os.path.abspath(old_filepath)
            print
            new_filepath = main_helper.reformat(
                prepared_format, filename_format)
            if prepared_format.text:
                pass
            setattr(media, "old_filepath", old_filepath)
            setattr(media, "new_filepath", new_filepath)
            new_directories.append(os.path.dirname(new_filepath))
    pool = multiprocessing()
    pool.starmap(fix_directory, product(
        posts))
    new_directories = list(set(new_directories))
    return posts, new_directories


def fix_metadata(posts):
    for post in posts:
        for media in post.medias:
            def update(old_filepath, new_filepath):
                # if os.path.exists(old_filepath):
                #     if not media.session:
                #         media.downloaded = True
                if old_filepath != new_filepath:
                    if os.path.exists(new_filepath):
                        os.remove(new_filepath)
                    if os.path.exists(old_filepath):
                        if not media.session:
                            media.downloaded = True
                        shutil.move(old_filepath, new_filepath)
                return old_filepath, new_filepath
            old_filepath = media.old_filepath
            new_filepath = media.new_filepath
            old_filepath, new_filepath = update(old_filepath, new_filepath)
            media.directory = os.path.dirname(new_filepath)
            media.filename = os.path.basename(new_filepath)
    return posts


def start(subscription, api_type, api_path, site_name, json_settings):
    metadata = getattr(subscription.scraped, api_type)
    download_info = subscription.download_info
    root_directory = download_info["directory"]
    date_format = json_settings["date_format"]
    text_length = json_settings["text_length"]
    reformats = {}
    reformats["metadata_directory_format"] = json_settings["metadata_directory_format"]
    reformats["file_directory_format"] = json_settings["file_directory_format"]
    reformats["filename_format"] = json_settings["filename_format"]
    username = subscription.username
    option = {}
    option["site_name"] = site_name
    option["api_type"] = api_type
    option["username"] = username
    option["date_format"] = date_format
    option["maximum_length"] = text_length
    option["directory"] = root_directory
    formatted = format_types(reformats).check_unique()
    unique = formatted["unique"]
    for key, value in reformats.items():
        key2 = getattr(unique, key)[0]
        reformats[key] = value.split(key2, 1)[0]+key2
        print
    print
    a, base_directory, c = prepare_reformat(
        option, keep_vars=True).reformat(reformats)
    download_info["base_directory"] = base_directory
    print
    all_files = []
    for root, subdirs, files in os.walk(base_directory):
        x = [os.path.join(root, x) for x in files]
        all_files.extend(x)
    for media_type, value in metadata.content:
        if media_type == "Texts":
            continue
        for status, value2 in value:
            fixed, new_directories = fix_directories(
                value2, root_directory, site_name, api_path, media_type, username, all_files, json_settings)
            for new_directory in new_directories:
                directory = os.path.abspath(new_directory)
                os.makedirs(directory, exist_ok=True)
            fixed2 = fix_metadata(
                fixed)
            setattr(value, status, fixed2)
        setattr(metadata.content, media_type, value,)
    return metadata


if __name__ == "__main__":
    # WORK IN PROGRESS
    input("You can't use this manually yet lmao xqcl")
    exit()
else:
    import helpers.main_helper as main_helper
    from classes.prepare_metadata import create_metadata
