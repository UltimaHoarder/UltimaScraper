#!/usr/bin/env python3
import asyncio
import os
import shutil
import traceback
import urllib.parse as urlparse
from itertools import chain

from apis.onlyfans import onlyfans
from apis.onlyfans.classes.create_user import create_user
from database.databases.user_data.models.api_table import api_table
from database.databases.user_data.models.media_table import template_media_table
from sqlalchemy.orm.scoping import scoped_session
from tqdm.asyncio import tqdm


async def fix_directories(
    posts,
    api: onlyfans.start,
    subscription: create_user,
    all_files,
    database_session: scoped_session,
    folder,
    site_name,
    api_type,
    base_directory,
    json_settings,
):
    new_directories = []

    async def fix_directories2(post: api_table, media_db: list[template_media_table]):
        delete_rows = []
        final_api_type = (
            os.path.join("Archived", api_type) if post.archived else api_type
        )
        post_id = post.post_id
        media_db = [x for x in media_db if x.post_id == post_id]
        for media in media_db:
            media_id = media.media_id
            if media.link:
                path = urlparse.urlparse(media.link).path
            else:
                path: str = media.filename
            new_filename = os.path.basename(path)
            original_filename, ext = os.path.splitext(new_filename)
            ext = ext.replace(".", "")
            file_directory_format = json_settings["file_directory_format"]
            filename_format = json_settings["filename_format"]
            date_format = json_settings["date_format"]
            text_length = json_settings["text_length"]
            download_path = base_directory
            option = {}
            option["site_name"] = site_name
            option["post_id"] = post_id
            option["media_id"] = media_id
            option["profile_username"] = subscription.subscriber.username
            option["model_username"] = subscription.username
            option["api_type"] = final_api_type
            option["media_type"] = media.media_type
            option["filename"] = original_filename
            option["ext"] = ext
            option["text"] = post.text
            option["postedAt"] = media.created_at
            option["price"] = post.price
            option["date_format"] = date_format
            option["text_length"] = text_length
            option["directory"] = download_path
            option["preview"] = media.preview
            option["archived"] = post.archived
            prepared_format = prepare_reformat(option)
            file_directory = await main_helper.reformat(
                prepared_format, file_directory_format
            )
            prepared_format.directory = file_directory
            old_filepath = ""
            if media.linked:
                filename_format = f"linked_{filename_format}"
            old_filepaths = [
                x for x in all_files if original_filename in os.path.basename(x)
            ]
            if not old_filepaths:
                old_filepaths = [
                    x for x in all_files if str(media_id) in os.path.basename(x)
                ]
                print
            if not media.linked:
                old_filepaths: list[str] = [
                    x for x in old_filepaths if "linked_" not in x
                ]
            if old_filepaths:
                old_filepath = old_filepaths[0]
            # a = randint(0,1)
            # await asyncio.sleep(a)
            new_filepath = await main_helper.reformat(prepared_format, filename_format)
            if old_filepath and old_filepath != new_filepath:
                if os.path.exists(new_filepath):
                    os.remove(new_filepath)
                moved = None
                while not moved:
                    try:
                        if os.path.exists(old_filepath):
                            old_filename, old_ext = os.path.splitext(old_filepath)
                            if ".part" == old_ext:
                                os.remove(old_filepath)
                                continue
                            if media.size:
                                media.downloaded = True
                            found_dupes = [
                                x
                                for x in media_db
                                if x.filename == new_filename and x.id != media.id
                            ]
                            delete_rows.extend(found_dupes)
                            os.makedirs(os.path.dirname(new_filepath), exist_ok=True)
                            if media.linked:
                                if os.path.dirname(old_filepath) == os.path.dirname(
                                    new_filepath
                                ):
                                    moved = shutil.move(old_filepath, new_filepath)
                                else:
                                    moved = shutil.copy(old_filepath, new_filepath)
                            else:
                                moved = shutil.move(old_filepath, new_filepath)
                        else:
                            break
                    except OSError as e:
                        print(traceback.format_exc())
                    print
                print

            if os.path.exists(new_filepath):
                if media.size:
                    media.downloaded = True
            if prepared_format.text:
                pass
            media.directory = file_directory
            media.filename = os.path.basename(new_filepath)
            new_directories.append(os.path.dirname(new_filepath))
        return delete_rows

    result = database_session.query(folder.media_table)
    media_db = result.all()
    pool = api.pool
    # tasks = pool.starmap(fix_directories2, product(posts, [media_db]))
    tasks = [asyncio.ensure_future(fix_directories2(post, media_db)) for post in posts]
    settings = {"colour": "MAGENTA", "disable": False}
    delete_rows = await tqdm.gather(*tasks, **settings)
    delete_rows = list(chain(*delete_rows))
    for delete_row in delete_rows:
        database_session.query(folder.media_table).filter(
            folder.media_table.id == delete_row.id
        ).delete()
    database_session.commit()
    new_directories = list(set(new_directories))
    return posts, new_directories


async def start(
    api: onlyfans.start,
    Session,
    api_type,
    site_name,
    subscription: create_user,
    folder,
    json_settings,
):
    api_table = folder.table_picker(api_type)
    database_session = Session()
    # Slow
    result = database_session.query(api_table).all()
    metadata = getattr(subscription.temp_scraped, api_type)
    download_info = subscription.download_info
    root_directory = download_info["directory"]
    date_format = json_settings["date_format"]
    text_length = json_settings["text_length"]
    reformats = {}
    reformats["metadata_directory_format"] = json_settings["metadata_directory_format"]
    reformats["file_directory_format"] = json_settings["file_directory_format"]
    reformats["filename_format"] = json_settings["filename_format"]
    model_username = subscription.username
    option = {}
    option["site_name"] = site_name
    option["api_type"] = api_type
    option["profile_username"] = subscription.subscriber.username
    option["model_username"] = model_username
    option["date_format"] = date_format
    option["maximum_length"] = text_length
    option["directory"] = root_directory
    formatted = format_types(reformats).check_unique()
    unique = formatted["unique"]
    for key, value in reformats.items():
        key2 = getattr(unique, key)[0]
        reformats[key] = value.split(key2, 1)[0] + key2
        print
    print
    a, base_directory, c = await prepare_reformat(option, keep_vars=True).reformat(
        reformats
    )
    download_info["base_directory"] = base_directory
    print
    all_files = []
    for root, subdirs, files in os.walk(base_directory):
        x = [os.path.join(root, x) for x in files]
        all_files.extend(x)

    await fix_directories(
        result,
        api,
        subscription,
        all_files,
        database_session,
        folder,
        site_name,
        api_type,
        root_directory,
        json_settings,
    )
    database_session.close()
    return metadata


if __name__ == "__main__":
    # WORK IN PROGRESS
    input("You can't use this manually yet lmao xqcl")
    exit()
else:
    import helpers.main_helper as main_helper
    from classes.prepare_metadata import format_types, prepare_reformat
