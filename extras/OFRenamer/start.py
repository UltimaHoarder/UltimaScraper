#!/usr/bin/env python3
from sqlalchemy.orm.scoping import scoped_session
from database.models.api_table import api_table
from database.models.media_table import media_table
import urllib.parse as urlparse
import shutil
from datetime import datetime
import os
from itertools import product
import traceback


def fix_directories(posts, all_files, Session: scoped_session, folder, site_name, parent_type, api_type, username, base_directory, json_settings):
    new_directories = []

    def fix_directories(post: api_table, media_db: list[media_table]):
        final_type = ""
        if parent_type:
            final_type = f"{api_type}{os.path.sep}{parent_type}"
            print
        final_type = final_type if final_type else api_type
        post_id = post.post_id
        media_db = [x for x in media_db if x.post_id == post_id]
        for media in media_db:
            media_id = media.media_id
            if media.link:
                path = urlparse.urlparse(media.link).path
            else:
                path: str = media.filename
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
            option["media_id"] = media_id
            option["username"] = username
            option["api_type"] = final_type if parent_type else api_type
            option["media_type"] = media.media_type
            option["filename"] = filename
            option["ext"] = ext
            option["text"] = post.text
            option["postedAt"] = media.created_at
            option["price"] = post.price
            option["date_format"] = date_format
            option["text_length"] = text_length
            option["directory"] = download_path
            option["preview"] = media.preview
            prepared_format = prepare_reformat(option)
            file_directory = main_helper.reformat(
                prepared_format, file_directory_format)
            prepared_format.directory = file_directory
            old_filepath = ""
            old_filepaths = [
                x for x in all_files if media.filename in os.path.basename(x)]
            if not old_filepaths:
                old_filepaths = [
                    x for x in all_files if str(media_id) in os.path.basename(x)]
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
                            print(traceback.format_exc())
                    print
                print

            if os.path.exists(new_filepath):
                if media.size:
                    media.downloaded = True
            else:
                media.downloaded = False
            if prepared_format.text:
                pass
            media.directory = file_directory
            media.filename = os.path.basename(new_filepath)
            new_directories.append(os.path.dirname(new_filepath))
    pool = multiprocessing()
    database_session = Session()
    result = database_session.query(folder.media_table)
    media_db = result.all()
    pool.starmap(fix_directories, product(
        posts, [media_db]))
    database_session.commit()
    new_directories = list(set(new_directories))
    return posts, new_directories


def start(Session, parent_type, api_type, api_path, site_name, subscription, folder, json_settings):
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

    database_session.close()
    fixed, new_directories = fix_directories(
        result, all_files, Session, folder, site_name, parent_type, api_type, username, root_directory, json_settings)
    return metadata


if __name__ == "__main__":
    # WORK IN PROGRESS
    input("You can't use this manually yet lmao xqcl")
    exit()
else:
    import helpers.main_helper as main_helper
    from apis.api_helper import multiprocessing
    from classes.prepare_metadata import format_types, prepare_reformat
