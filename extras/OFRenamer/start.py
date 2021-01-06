#!/usr/bin/env python3
from apis.onlyfans.onlyfans import media_types
from apis.api_helper import multiprocessing
from classes.prepare_metadata import format_types, prepare_reformat
import urllib.parse as urlparse
import shutil
from datetime import datetime
import os
from itertools import product


def fix_directories(posts, all_files, Session, folder, site_name, api_type, username, base_directory, json_settings):
    new_directories = []

    def fix_directories(post):
        database_session = Session()
        post_id = post.id
        result = database_session.query(folder.media_table)
        media_db = result.filter_by(post_id=post_id).all()
        for media in media_db:
            if media.link:
                path = urlparse.urlparse(media.link).path
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
            option = {}
            option["site_name"] = site_name
            option["post_id"] = post_id
            option["media_id"] = media.id
            option["username"] = username
            option["api_type"] = api_type
            option["media_type"] = media.media_type
            option["filename"] = filename
            option["ext"] = ext
            option["text"] = post.text
            option["postedAt"] = media.created_at
            option["price"] = post.price
            option["date_format"] = date_format
            option["text_length"] = text_length
            option["directory"] = download_path
            prepared_format = prepare_reformat(option)
            file_directory = main_helper.reformat(
                prepared_format, file_directory_format)
            prepared_format.directory = file_directory
            old_filepath = ""
            old_filepaths = [
                x for x in all_files if media.filename in os.path.basename(x)]
            if not old_filepaths:
                old_filepaths = [
                    x for x in all_files if str(media.id) in os.path.basename(x)]
                print
            if old_filepaths:
                old_filepath = old_filepaths[0]
            print
            new_filepath = main_helper.reformat(
                prepared_format, filename_format)
            if old_filepath and old_filepath != new_filepath:
                if os.path.exists(new_filepath):
                    os.remove(new_filepath)
                if os.path.exists(old_filepath):
                    if media.size:
                        media.downloaded = True
                    moved = None
                    while not moved:
                        try:
                            moved = shutil.move(old_filepath, new_filepath)
                        except OSError as e:
                            print(e)
                    print
                print
            else:
                print
            if prepared_format.text:
                pass
            media.directory = file_directory
            media.filename = os.path.basename(new_filepath)
            database_session.commit()
            new_directories.append(os.path.dirname(new_filepath))
        database_session.close()
    pool = multiprocessing()
    pool.starmap(fix_directories, product(
        posts))
    new_directories = list(set(new_directories))
    return posts, new_directories


def start(Session, api_type, api_path, site_name, subscription, folder, json_settings):
    api_table = folder.api_table
    media_table = folder.media_table
    database_session = Session()
    result = database_session.query(api_table).all()
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

    fixed, new_directories = fix_directories(
        result, all_files, Session, folder, site_name, api_type, username, root_directory, json_settings)
    database_session.close()
    return metadata


if __name__ == "__main__":
    # WORK IN PROGRESS
    input("You can't use this manually yet lmao xqcl")
    exit()
else:
    import helpers.main_helper as main_helper
    from classes.prepare_metadata import create_metadata
