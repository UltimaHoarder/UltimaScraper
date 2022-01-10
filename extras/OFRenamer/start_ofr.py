#!/usr/bin/env python3
from sys import exit
import asyncio
import os
import shutil
import traceback
import urllib.parse as urlparse
from datetime import datetime
from itertools import chain
from pathlib import Path

import apis.fansly.classes as fansly_classes
import apis.onlyfans.classes as onlyfans_classes
import apis.starsavn.classes as starsavn_classes
import database.databases.user_data.user_database as user_database
from classes.make_settings import SiteSettings
from classes.prepare_metadata import prepare_reformat
from database.databases.user_data.models.api_table import api_table
from database.databases.user_data.models.media_table import template_media_table
from sqlalchemy.orm.scoping import scoped_session
from tqdm.asyncio import tqdm

user_types = (
    onlyfans_classes.user_model.create_user
    | fansly_classes.user_model.create_user
    | starsavn_classes.user_model.create_user
)


async def fix_directories(
    posts: list[api_table],
    subscription: user_types,
    database_session: scoped_session,
    api_type: str,
):
    new_directories = []
    authed = subscription.get_authed()
    api = authed.api
    site_settings = api.get_site_settings()

    async def fix_directories2(
        post: api_table, media_db: list[template_media_table], all_files: list[Path]
    ):
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

            file_directory_format = site_settings.file_directory_format
            filename_format = site_settings.filename_format
            date_format = site_settings.date_format
            text_length = site_settings.text_length
            download_path = subscription.directory_manager.root_download_directory
            option = {}
            option["site_name"] = api.site_name
            option["post_id"] = post_id
            option["media_id"] = media_id
            option["profile_username"] = authed.username
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
            file_directory = await prepared_format.reformat_2(file_directory_format)
            prepared_format.directory = file_directory
            old_filepath = ""
            if media.linked:
                filename_format = f"linked_{filename_format}"
            new_filepath = await prepared_format.reformat_2(filename_format)
            old_filepaths = [
                x
                for x in all_files
                if original_filename in x.name and x.parts != new_filepath.parts
            ]
            if not old_filepaths:
                old_filepaths = [x for x in all_files if str(media_id) in x.name]
                print
            if not media.linked:
                old_filepaths: list[Path] = [
                    x for x in old_filepaths if "linked_" not in x.parts
                ]
            if old_filepaths:
                old_filepath = old_filepaths[0]
            # a = randint(0,1)
            # await asyncio.sleep(a)
            if old_filepath and old_filepath != new_filepath:
                if new_filepath.exists():
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
            media.directory = file_directory.as_posix()
            media.filename = os.path.basename(new_filepath)
            new_directories.append(os.path.dirname(new_filepath))
        return delete_rows

    base_directory = subscription.directory_manager.user.find_legacy_directory(
        "download", api_type
    )
    temp_files: list[Path] = await subscription.directory_manager.walk(base_directory)
    result = database_session.query(user_database.media_table)
    media_db = result.all()
    pool = api.pool
    # tasks = pool.starmap(fix_directories2, product(posts, [media_db]))
    tasks = [
        asyncio.ensure_future(fix_directories2(post, media_db, temp_files))
        for post in posts
    ]
    settings = {"colour": "MAGENTA", "disable": False}
    delete_rows = await tqdm.gather(*tasks, **settings)
    delete_rows = list(chain(*delete_rows))
    for delete_row in delete_rows:
        database_session.query(user_database.media_table).filter(
            user_database.media_table.id == delete_row.id
        ).delete()
    database_session.commit()
    new_directories = list(set(new_directories))
    return posts, new_directories


async def start(
    subscription: user_types,
    api_type: str,
    Session: scoped_session,
    site_settings: SiteSettings,
):
    authed = subscription.get_authed()
    directory_manager = subscription.directory_manager
    api_table_ = user_database.table_picker(api_type)
    database_session: scoped_session = Session()
    # Slow
    authed_username = authed.username
    subscription_username = subscription.username
    site_name = authed.api.site_name
    p_r = prepare_reformat()
    p_r = await p_r.standard(
        site_name=site_name,
        profile_username=authed_username,
        user_username=subscription_username,
        date=datetime.today(),
        date_format=site_settings.date_format,
        text_length=site_settings.text_length,
        directory=directory_manager.root_metadata_directory,
    )
    p_r.api_type = api_type
    result: list[api_table] = database_session.query(api_table_).all()
    metadata = getattr(subscription.temp_scraped, api_type)

    await fix_directories(
        result,
        subscription,
        database_session,
        api_type,
    )
    database_session.close()
    return metadata


if __name__ == "__main__":
    # WORK IN PROGRESS
    input("You can't use this manually yet lmao xqcl")
    exit()
