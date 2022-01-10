from sys import exit
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
from datetime import datetime, timedelta
from itertools import product
from types import SimpleNamespace
from typing import Any, Optional, Union
from urllib.parse import urlparse
from apis import api_helper
from classes.make_settings import SiteSettings

import extras.OFLogin.start_ofl as oflogin
import extras.OFRenamer.start_ofr as ofrenamer
import helpers.db_helper as db_helper
import helpers.main_helper as main_helper
from apis.starsavn import starsavn as StarsAVN
from apis.starsavn.classes.auth_model import create_auth
from apis.starsavn.classes.message_model import create_message
from apis.starsavn.classes.post_model import create_post
from apis.starsavn.classes.product_model import create_product
from apis.starsavn.classes.story_model import create_story
from apis.starsavn.classes.user_model import create_user
from apis.starsavn.classes.extras import ErrorDetails, auth_details, media_types
from apis.starsavn.starsavn import start
from classes.prepare_metadata import create_metadata, prepare_reformat
from helpers import db_helper
from mergedeep import Strategy, merge
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm.scoping import scoped_session
from tqdm.asyncio import tqdm

# The start lol


class StarsAVNDataScraper:
    def __init__(self, api: start) -> None:
        self.api = api

    async def manage_subscriptions(
        self,
        authed: create_auth,
        identifiers: list[int | str] = [],
        refresh: bool = True,
    ):
        temp_subscriptions: list[create_user] = []
        results = await authed.get_subscriptions(
            identifiers=identifiers, refresh=refresh
        )
        site_settings = authed.api.get_site_settings()
        if not site_settings:
            return temp_subscriptions
        blacklists = site_settings.blacklists
        ignore_type = site_settings.ignore_type
        if blacklists:
            remote_blacklists = await authed.get_lists(refresh=True)
            if remote_blacklists:
                for remote_blacklist in remote_blacklists:
                    for blacklist in blacklists:
                        if remote_blacklist["name"] == blacklist:
                            list_users = remote_blacklist["users"]
                            if remote_blacklist["usersCount"] > 2:
                                list_id = remote_blacklist["id"]
                                list_users = await authed.get_lists_users(list_id)
                            if list_users:
                                users = list_users
                                bl_ids = [x["username"] for x in users]
                                results2 = results.copy()
                                for result in results2:
                                    identifier = result.username
                                    if identifier in bl_ids:
                                        print(f"Blacklisted: {identifier}")
                                        results.remove(result)
        results.sort(key=lambda x: x.subscribedByData["expiredAt"])
        results.sort(key=lambda x: x.is_me(), reverse=True)
        for result in results:
            path_formats: dict[str, Any] = {}
            path_formats[
                "metadata_directory_format"
            ] = site_settings.metadata_directory_format
            path_formats["file_directory_format"] = site_settings.file_directory_format
            path_formats["filename_format"] = site_settings.filename_format
            result.create_directory_manager(path_formats=path_formats)
            subscribePrice = result.subscribePrice
            if ignore_type in ["paid"]:
                if subscribePrice > 0:
                    continue
            if ignore_type in ["free"]:
                if subscribePrice == 0:
                    continue
            temp_subscriptions.append(result)
        authed.subscriptions = temp_subscriptions
        return authed.subscriptions

    async def start_datascraper(self, authed: create_auth, identifier: int | str):
        api = authed.api
        site_settings = api.get_site_settings()
        if not site_settings:
            return
        subscription = await authed.get_subscription(identifier=identifier)
        if not subscription:
            return [False, subscription]
        print("Scrape Processing")
        username = subscription.username
        print(f"Name: {username}")
        subscription_directory_manager = subscription.directory_manager
        if subscription_directory_manager:
            await main_helper.format_directories(
                subscription_directory_manager, subscription
            )
            some_list = [subscription_directory_manager]
            await main_helper.fix_sqlite(*some_list)
            api_array = scrape_choice(authed, subscription)
            api_array = format_options(api_array, "apis")
            apis: list[dict[str, Any]] = api_array[0]
            api_string = api_array[1]
            if not site_settings.auto_api_choice:
                print(f"Apis: {api_string}")
                value = int(input().strip())
            else:
                value = 0
            if value:
                apis = [apis[value]]
            else:
                apis.pop(0)
            for item in apis:
                print("Type: " + item["api_type"])
                item["api_array"]["username"] = username
                item["api_array"]["subscription"] = subscription
                await prepare_scraper(authed, item)
            print("Scrape Completed" + "\n")
            return True, subscription

    async def paid_content_scraper(self, authed: create_auth):
        return

    async def prepare_downloads(self, subscription: create_user):
        site_settings = subscription.get_authed().api.get_site_settings()
        subscription_directory_manager = subscription.directory_manager
        directory = subscription_directory_manager.root_download_directory
        print
        for api_type, metadata_path in subscription.scraped.__dict__.items():
            metadata_path = (
                subscription_directory_manager.user.metadata_directory.joinpath(
                    "user_data.db"
                )
            )
            database_session, _engine = await db_helper.import_database(metadata_path)
            db_collection = db_helper.database_collection()
            database = db_collection.database_picker("user_data")
            if database:
                media_table = database.media_table
                overwrite_files = site_settings.overwrite_files
                if overwrite_files:
                    download_list: Any = (
                        database_session.query(media_table)
                        .filter(media_table.api_type == api_type)
                        .all()
                    )
                    media_set_count = len(download_list)
                else:
                    download_list: Any = (
                        database_session.query(media_table)
                        .filter(media_table.downloaded == False)
                        .filter(media_table.api_type == api_type)
                    )
                    media_set_count = db_helper.get_count(download_list)
                location = ""
                string = "Download Processing\n"
                string += f"Name: {subscription.username} | Type: {api_type} | Count: {media_set_count}{location} | Directory: {directory}\n"
                if media_set_count:
                    print(string)
                    await main_helper.async_downloads(download_list, subscription)
                while True:
                    try:
                        database_session.commit()
                        break
                    except OperationalError:
                        database_session.rollback()
                database_session.close()
            print
        print


async def start_datascraper(
    authed: create_auth, identifier, site_name, choice_type=None
):
    subscription = await authed.get_subscription(identifier=identifier)
    if not subscription:
        return [False, subscription]
    print("Scrape Processing")
    username = subscription.username
    print(f"Name: {username}")
    some_list = [
        profile_directory,
        download_directory,
        metadata_directory,
        format_directories,
        authed,
        site_name,
        username,
        metadata_directory_format,
    ]
    await main_helper.fix_sqlite(*some_list)
    api_array = scrape_choice(authed, subscription)
    api_array = format_options(api_array, "apis")
    apis = api_array[0]
    api_string = api_array[1]
    if not json_settings["auto_api_choice"]:
        print(f"Apis: {api_string}")
        value = int(input().strip())
    else:
        value = 0
    if value:
        apis = [apis[value]]
    else:
        apis.pop(0)
    for item in apis:
        print("Type: " + item["api_type"])
        item["api_array"]["username"] = username
        item["api_array"]["subscription"] = subscription
        await prepare_scraper(authed, site_name, item)
    print("Scrape Completed" + "\n")
    return [True, subscription]


# Allows the user to choose which api they want to scrape
def scrape_choice(authed: create_auth, subscription: create_user):
    site_settings = authed.api.get_site_settings()
    if not site_settings:
        return
    user_id = subscription.id
    post_count = subscription.postsCount
    media_count = subscription.mediasCount["total"]
    archived_count = subscription.archivedPostsCount
    message = "Scrape: 0 = All | 1 = Images | 2 = Videos | 3 = Audios | 4 = Texts"
    media_types = [
        [["", "All"], ["", "Images"], ["", "Videos"], ["", "Audios"], ["", "Texts"]],
        message,
    ]
    choice_list = main_helper.choose_option(
        media_types, site_settings.auto_media_choice
    )
    user_api = StarsAVN.endpoint_links(user_id).users
    message_api = StarsAVN.endpoint_links(user_id).message_api
    # mass_messages_api = StarsAVN.endpoint_links().mass_messages_api
    stories_api = StarsAVN.endpoint_links(user_id).stories_api
    list_highlights = StarsAVN.endpoint_links(user_id).list_highlights
    post_api = StarsAVN.endpoint_links(user_id).post_api
    media_api = StarsAVN.endpoint_links(user_id).media_api
    archived_api = StarsAVN.endpoint_links(user_id).archived_posts
    # ARGUMENTS
    only_links = False
    mandatory = [only_links]
    y = ["photo", "video", "stream", "gif", "audio", "text"]
    u_array: list[str | list[Any]] = [
        "You have chosen to scrape {}",
        [user_api, media_types, *mandatory, post_count],
        "Profile",
    ]
    s_array: list[str | list[Any]] = [
        "You have chosen to scrape {}",
        [stories_api, media_types, *mandatory, post_count],
        "Stories",
    ]
    h_array: list[str | list[Any]] = [
        "You have chosen to scrape {}",
        [list_highlights, media_types, *mandatory, post_count],
        "Highlights",
    ]
    p_array: list[str | list[Any]] = [
        "You have chosen to scrape {}",
        [post_api, media_types, *mandatory, post_count],
        "Posts",
    ]
    pd_array: list[str | list[Any]] = [
        "You have chosen to scrape {}",
        [media_api, media_types, *mandatory, media_count],
        "Products",
    ]
    m_array: list[str | list[Any]] = [
        "You have chosen to scrape {}",
        [message_api, media_types, *mandatory, post_count],
        "Messages",
    ]
    a_array: list[str | list[Any]] = [
        "You have chosen to scrape {}",
        [archived_api, media_types, *mandatory, archived_count],
        "Archived",
    ]
    array = [u_array, s_array, p_array, pd_array, a_array, m_array]
    # array = [u_array, s_array, p_array, a_array, m_array]
    # array = [s_array, h_array, p_array, a_array, m_array]
    # array = [s_array]
    # array = [u_array]
    # array = [p_array]
    # array = [a_array]
    # array = [m_array]
    new_array: list[dict[str, Any]] = []
    valid_input = True
    for xxx in array:
        if xxx[2] == "Mass Messages":
            if not subscription.is_me():
                continue
        new_item: dict[str, Any] = dict()
        new_item["api_message"] = xxx[0]
        new_item["api_array"] = {}
        new_item["api_array"]["api_link"] = xxx[1][0]
        new_item["api_array"]["media_types"] = xxx[1][1]
        new_item["api_array"]["only_links"] = xxx[1][2]
        new_item["api_array"]["post_count"] = xxx[1][3]
        formatted = format_media_types()
        final_format = []
        for choice in choice_list:
            choice = choice[1]
            final_format.extend([result for result in formatted if result[0] == choice])
        new_item["api_array"]["media_types"] = final_format
        new_item["api_type"] = xxx[2]
        if valid_input:
            new_array.append(new_item)
    return new_array


# Downloads the model's avatar and header
async def profile_scraper(subscription: create_user, api_type: str):
    authed = subscription.get_authed()
    site_settings = authed.api.get_site_settings()
    if not (subscription.directory_manager and site_settings):
        return
    subscription_directory_manager = subscription.directory_manager
    authed_username = authed.username
    subscription_username = subscription.username
    site_name = authed.api.site_name
    authed = subscription.get_authed()
    override_media_types: list[list[Any]] = []
    avatar = subscription.avatar
    header = subscription.header
    override_media_types.extend([["Avatars", avatar], ["Headers", header]])
    session = await authed.session_manager.create_client_session()
    progress_bar = None
    p_r = prepare_reformat()
    p_r.site_name = site_name
    p_r.profile_username = authed_username
    p_r.model_username = subscription_username
    p_r.date_format = site_settings.date_format
    p_r.text_length = site_settings.text_length
    p_r.api_type = api_type
    p_r.directory = subscription_directory_manager.root_download_directory

    file_directory_format = site_settings.file_directory_format.replace("{value}", "")
    directory = await p_r.reformat_2(file_directory_format)
    for override_media_type in override_media_types:
        media_type = override_media_type[0]
        media_link = override_media_type[1]
        if not media_link:
            continue
        directory2 = directory.joinpath(media_type)
        os.makedirs(directory2, exist_ok=True)
        download_path = directory2.joinpath(f"{media_link.split('/')[-2]}.jpg")
        if os.path.isfile(download_path):
            continue
        response = await authed.session_manager.json_request(media_link, method="HEAD")
        if not response:
            continue
        if not progress_bar:
            progress_bar = main_helper.download_session()
            progress_bar.start(unit="B", unit_scale=True, miniters=1)
        progress_bar.update_total_size(response.content_length)
        response = await authed.session_manager.json_request(
            media_link,
            session,
            stream=True,
            json_format=False,
        )
        await main_helper.write_data(response, download_path, progress_bar)
    await session.close()
    if progress_bar:
        progress_bar.close()  # type: ignore


async def paid_content_scraper(api: start, identifiers: list[int] | list[str] = []):
    site_settings = api.get_site_settings()
    if not site_settings:
        return
    for authed in api.auths:
        paid_contents = await authed.get_paid_content()
        if not authed.active or isinstance(paid_contents, ErrorDetails):
            return
        authed.subscriptions = authed.subscriptions
        for paid_content in paid_contents:
            author = None
            author = await paid_content.get_author()
            if not author:
                continue
            subscription = await authed.get_subscription(identifier=author.id)
            if not subscription:
                subscription = author
                authed.subscriptions.append(subscription)
            subscription.subscriber = authed
            path_formats: dict[str, Any] = {}
            path_formats[
                "metadata_directory_format"
            ] = site_settings.metadata_directory_format
            path_formats["file_directory_format"] = site_settings.file_directory_format
            path_formats["filename_format"] = site_settings.filename_format
            subscription.create_directory_manager(path_formats=path_formats)
            if paid_content.responseType:
                api_type = paid_content.responseType.capitalize() + "s"
                api_media = getattr(subscription.temp_scraped, api_type)
                api_media.append(paid_content)
        count = 0
        max_count = len(authed.subscriptions)
        for subscription in authed.subscriptions:
            if any(subscription.username != x for x in identifiers):
                continue
            string = f"Scraping - {subscription.username} | {count+1} / {max_count}"
            print(string)
            subscription.session_manager = authed.session_manager
            subscription_directory_manager = subscription.directory_manager
            count += 1
            for api_type, paid_contents in subscription.temp_scraped:
                if api_type == "Archived":
                    if any(x for k, x in paid_contents if not x):
                        input(
                            "OPEN A ISSUE GITHUB ON GITHUB WITH THE MODEL'S USERNAME AND THIS ERROR, THANKS"
                        )
                        exit(0)
                    continue
                if not paid_contents:
                    continue
                await format_directories(
                    subscription_directory_manager,
                    subscription,
                )
                metadata_path = (
                    subscription_directory_manager.user.metadata_directory.joinpath(
                        subscription_directory_manager.user.metadata_directory,
                        "user_data.db",
                    )
                )
                pool = subscription.session_manager.pool
                tasks = pool.starmap(
                    media_scraper,
                    product(
                        paid_contents,
                        [subscription],
                        [subscription_directory_manager.root_download_directory],
                        [api_type],
                    ),
                )
                settings = {"colour": "MAGENTA"}
                unrefined_set = await tqdm.gather(*tasks, **settings)
                new_metadata = main_helper.format_media_set(unrefined_set)
                new_metadata = new_metadata["content"]
                legacy_metadata_path = (
                    subscription_directory_manager.user.find_legacy_directory(
                        "metadata", api_type
                    ).with_suffix(".db")
                )
                if new_metadata:
                    old_metadata, delete_metadatas = await process_legacy_metadata(
                        subscription,
                        api_type,
                        metadata_path,
                    )
                    new_metadata.extend(old_metadata)
                    subscription.set_scraped(api_type, new_metadata)
                    await process_metadata(
                        metadata_path,
                        legacy_metadata_path,
                        new_metadata,
                        api_type,
                        subscription,
                        delete_metadatas,
                    )


def format_media_types():
    media_types = ["Images", "Videos", "Audios", "Texts"]
    media_types2 = ["photo", "video", "stream", "gif", "audio", "text"]
    new_list = []
    for z in media_types:
        if z == "Images":
            new_list.append([z, [media_types2[0]]])
        if z == "Videos":
            new_list.append([z, media_types2[1:4]])
        if z == "Audios":
            new_list.append([z, [media_types2[4]]])
        if z == "Texts":
            new_list.append([z, [media_types2[5]]])
    return new_list


def process_messages(authed: create_auth, subscription, messages) -> list:
    unrefined_set = [messages]
    return unrefined_set


async def process_mass_messages(
    authed: create_auth, subscription, metadata_directory, mass_messages
) -> list:
    def compare_message(queue_id, remote_messages):
        for message in remote_messages:
            if "isFromQueue" in message and message["isFromQueue"]:
                if queue_id == message["queueId"]:
                    return message
                print
        print

    global_found = []
    chats = []
    salt = json_global_settings["random_string"]
    encoded = f"{salt}"
    encoded = encoded.encode("utf-8")
    hash = hashlib.md5(encoded).hexdigest()
    profile_directory = json_global_settings["profile_directories"][0]
    profile_directory = os.path.abspath(profile_directory)
    profile_directory = os.path.join(profile_directory, subscription.username)
    profile_metadata_directory = os.path.join(profile_directory, "Metadata")
    mass_message_path = os.path.join(profile_metadata_directory, "Mass Messages.json")
    chats_path = os.path.join(profile_metadata_directory, "Chats.json")
    if os.path.exists(chats_path):
        chats = main_helper.import_archive(chats_path)
    date_object = datetime.today()
    date_string = date_object.strftime("%d-%m-%Y %H:%M:%S")
    for mass_message in mass_messages:
        if "status" not in mass_message:
            mass_message["status"] = ""
        if "found" not in mass_message:
            mass_message["found"] = {}
        if "hashed_ip" not in mass_message:
            mass_message["hashed_ip"] = ""
        mass_message["hashed_ip"] = mass_message.get("hashed_ip", hash)
        mass_message["date_hashed"] = mass_message.get("date_hashed", date_string)
        if mass_message["isCanceled"]:
            continue
        queue_id = mass_message["id"]
        text = mass_message["textCropped"]
        text = html.unescape(text)
        mass_found = mass_message["found"]
        media_type = mass_message.get("mediaType")
        media_types = mass_message.get("mediaTypes")
        if mass_found or (not media_type and not media_types):
            continue
        identifier = None
        if chats:
            list_chats = chats
            for chat in list_chats:
                identifier = chat["identifier"]
                messages = chat["messages"]["list"]
                mass_found = compare_message(queue_id, messages)
                if mass_found:
                    mass_message["found"] = mass_found
                    mass_message["status"] = True
                    break
        if not mass_found:
            list_chats = subscription.search_messages(text=text, limit=2)
            if not list_chats:
                continue
            for item in list_chats["list"]:
                user = item["withUser"]
                identifier = user["id"]
                messages = []
                print("Getting Messages")
                keep = ["id", "username"]
                list_chats2 = [x for x in chats if x["identifier"] == identifier]
                if list_chats2:
                    chat2 = list_chats2[0]
                    messages = chat2["messages"]["list"]
                    messages = subscription.get_messages(
                        identifier=identifier, resume=messages
                    )
                    for message in messages:
                        message["withUser"] = {k: item["withUser"][k] for k in keep}
                        message["fromUser"] = {k: message["fromUser"][k] for k in keep}
                    mass_found = compare_message(queue_id, messages)
                    if mass_found:
                        mass_message["found"] = mass_found
                        mass_message["status"] = True
                        break
                else:
                    item2 = {}
                    item2["identifier"] = identifier
                    item2["messages"] = subscription.get_messages(identifier=identifier)
                    chats.append(item2)
                    messages = item2["messages"]["list"]
                    for message in messages:
                        message["withUser"] = {k: item["withUser"][k] for k in keep}
                        message["fromUser"] = {k: message["fromUser"][k] for k in keep}
                    mass_found = compare_message(queue_id, messages)
                    if mass_found:
                        mass_message["found"] = mass_found
                        mass_message["status"] = True
                        break
                    print
                print
            print
        if not mass_found:
            mass_message["status"] = False
    main_helper.export_data(chats, chats_path)
    for mass_message in mass_messages:
        found = mass_message["found"]
        if found and found["media"]:
            user = found["withUser"]
            identifier = user["id"]
            print
            date_hashed_object = datetime.strptime(
                mass_message["date_hashed"], "%d-%m-%Y %H:%M:%S"
            )
            next_date_object = date_hashed_object + timedelta(days=1)
            print
            if mass_message["hashed_ip"] != hash or date_object > next_date_object:
                print("Getting Message By ID")
                x = await subscription.get_message_by_id(
                    identifier=identifier, identifier2=found["id"], limit=1
                )
                new_found = x["result"]["list"][0]
                new_found["withUser"] = found["withUser"]
                mass_message["found"] = new_found
                mass_message["hashed_ip"] = hash
                mass_message["date_hashed"] = date_string
            global_found.append(found)
        print
    print
    main_helper.export_data(mass_messages, mass_message_path)
    return global_found


async def process_legacy_metadata(
    user: create_user,
    api_type: str,
    metadata_filepath: Path,
):
    site_settings = user.get_authed().api.get_site_settings()
    directory_manager = user.directory_manager
    if not (site_settings and directory_manager):
        return
    p_r = prepare_reformat()
    old_metadata_filepaths = await p_r.find_metadata_files(
        user.file_manager.files, legacy_files=False
    )
    for old_metadata_filepath in old_metadata_filepaths:
        new_m_f = directory_manager.user.metadata_directory.joinpath(
            old_metadata_filepath.name
        )
        if old_metadata_filepath.exists() and not new_m_f.exists():
            shutil.move(old_metadata_filepath, new_m_f)
    old_metadata_filepaths = await p_r.find_metadata_files(
        user.file_manager.files, legacy_files=False
    )
    legacy_metadata_filepaths = [
        x for x in old_metadata_filepaths if x.stem.find(api_type) == 0
    ]
    legacy_metadata_object, delete_legacy_metadatas = await legacy_metadata_fixer(
        metadata_filepath, legacy_metadata_filepaths
    )
    delete_metadatas: list[Path] = []
    if delete_legacy_metadatas:
        print("Merging new metadata with legacy metadata.")
        delete_metadatas.extend(delete_legacy_metadatas)
    final_set: list[dict[str, Any]] = []
    for _media_type, value in legacy_metadata_object.content:
        for _status, value2 in value:
            for value3 in value2:
                item = value3.convert(keep_empty_items=True)
                item["archived"] = False
                item["api_type"] = api_type
                final_set.append(item)
    print("Finished processing metadata.")
    return final_set, delete_metadatas


async def process_metadata(
    archive_path: str,
    legacy_metadata_path: str,
    new_metadata_object: list[dict[str, Any]],
    api_type: str,
    subscription: create_user,
    delete_metadatas: list[Path],
):
    api = subscription.get_api()
    site_settings = api.get_site_settings()
    config = api.config
    if not (config and site_settings):
        return
    settings = config.settings
    # We could put this in proccess_legacy_metadata
    final_result, delete_metadatas = main_helper.legacy_sqlite_updater(
        legacy_metadata_path, api_type, subscription, delete_metadatas
    )
    new_metadata_object.extend(final_result)
    result = main_helper.export_sqlite(archive_path, api_type, new_metadata_object)
    if not result:
        return
    Session, api_type, _folder = result
    if settings.helpers.renamer:
        print("Renaming files.")
        new_metadata_object = await ofrenamer.start(
            subscription, api_type, Session, site_settings
        )
    for legacy_metadata in delete_metadatas:
        if site_settings.delete_legacy_metadata:
            os.remove(legacy_metadata)
        else:
            if legacy_metadata.exists():
                new_filepath = Path(
                    legacy_metadata.parent, "__legacy_metadata__", legacy_metadata.name
                )
                new_filepath.parent.mkdir(exist_ok=True)
                shutil.move(legacy_metadata, f"{new_filepath}")


async def format_directories(
    directories: dict[str, Any],
    authed: create_auth,
    site_name: str,
    model_username: str,
    unformatted: str,
    locations: list = [],
    api_type: str = "",
) -> dict:
    x = {}
    x["profile_directory"] = ""
    x["legacy_metadatas"] = {}
    for key, directory in directories.items():
        option = {}
        option["site_name"] = site_name
        option["profile_username"] = authed.username
        option["model_username"] = model_username
        option["directory"] = directory
        option["postedAt"] = datetime.today()
        option["date_format"] = date_format
        option["text_length"] = text_length
        prepared_format = prepare_reformat(option)
        if key == "profile_directory":
            x["profile_directory"] = prepared_format.directory
        if key == "download_directory":
            x["download_directory"] = prepared_format.directory
            legacy_model_directory = x["legacy_model_directory"] = os.path.join(
                directory, site_name, model_username
            )
            x["legacy_metadatas"]["legacy_metadata"] = os.path.join(
                legacy_model_directory, api_type, "Metadata"
            )
            x["legacy_metadatas"]["legacy_metadata2"] = os.path.join(
                legacy_model_directory, "Metadata"
            )
        if key == "metadata_directory":
            x["metadata_directory"] = await main_helper.reformat(
                prepared_format, unformatted
            )
    x["locations"] = []
    for location in locations:
        directories = {}
        cats = ["Unsorted", "Free", "Paid"]
        for cat in cats:
            cat2 = cat
            if "Unsorted" in cat2:
                cat2 = ""
            path = os.path.join(api_type, cat2, location[0])
            directories[cat.lower()] = path
        y = {}
        y["sorted_directories"] = directories
        y["media_type"] = location[0]
        y["alt_media_type"] = location[1]
        x["locations"].append(y)
    return x


# Prepares the API links to be scraped


async def prepare_scraper(authed: create_auth, item: dict[str, Any]):
    api_type = item["api_type"]
    api_array = item["api_array"]
    subscription: create_user = api_array["subscription"]
    subscription_directory_manager = subscription.directory_manager
    if not subscription_directory_manager:
        return
    formatted_metadata_directory = (
        subscription_directory_manager.user.metadata_directory
    )
    master_set: list[Any] = []
    pool = authed.pool
    if api_type == "Profile":
        await profile_scraper(subscription, api_type)
        return True
    if api_type == "Stories":
        # master_set = await subscription.get_stories()
        # master_set += await subscription.get_archived_stories()
        # highlights = await subscription.get_highlights()
        highlights = []
        valid_highlights = []
        for highlight in highlights:
            highlight = await subscription.get_highlights(hightlight_id=highlight.id)
            valid_highlights.extend(highlight)
        master_set.extend(valid_highlights)
        print
    if api_type == "Posts":
        master_set = await subscription.get_posts()
        print(f"Type: Archived Posts")
        master_set += await subscription.get_archived_posts()
    if api_type == "Products":
        master_set = await subscription.get_medias()
        print
    # if api_type == "Archived":
    #     master_set = await subscription.get_archived(authed)
    if api_type == "Messages":
        unrefined_set = await subscription.get_messages()
        mass_messages = getattr(authed, "mass_messages")
        if subscription.is_me() and mass_messages:
            mass_messages = getattr(authed, "mass_messages")
            unrefined_set2 = await process_mass_messages(
                authed, subscription, formatted_metadata_directory, mass_messages
            )
            unrefined_set += unrefined_set2
        master_set = unrefined_set
    master_set2 = master_set
    parent_type = ""
    unrefined_set = []
    if master_set2:
        print(f"Processing Scraped {api_type}")
        tasks = pool.starmap(
            media_scraper,
            product(
                master_set2,
                [subscription],
                [subscription_directory_manager.root_download_directory],
                [api_type],
            ),
        )
        settings = {"colour": "MAGENTA"}
        unrefined_set = await tqdm.gather(*tasks, **settings)
        pass
    unrefined_set = [x for x in unrefined_set]
    new_metadata = main_helper.format_media_set(unrefined_set)
    metadata_path = formatted_metadata_directory.joinpath("user_data.db")
    legacy_metadata_path = formatted_metadata_directory.joinpath(api_type + ".db")
    if new_metadata:
        new_metadata = new_metadata["content"]
        print("Processing metadata.")
        old_metadata, delete_metadatas = await process_legacy_metadata(
            subscription,
            api_type,
            metadata_path,
        )
        new_metadata = new_metadata + old_metadata
        subscription.set_scraped(api_type, new_metadata)
        await process_metadata(
            metadata_path,
            legacy_metadata_path,
            new_metadata,
            api_type,
            subscription,
            delete_metadatas,
        )
    else:
        print("No " + api_type + " Found.")
    return True


async def legacy_metadata_fixer(
    new_metadata_filepath: Path, legacy_metadata_filepaths: list[Path]
) -> tuple[create_metadata, list[Path]]:
    delete_legacy_metadatas: list[Path] = []
    new_format: list[dict[str, Any]] = []
    new_metadata_set = main_helper.import_archive(new_metadata_filepath)
    for legacy_metadata_filepath in legacy_metadata_filepaths:
        if (
            legacy_metadata_filepath == new_metadata_filepath
            or not legacy_metadata_filepath.exists()
        ):
            continue
        api_type = legacy_metadata_filepath.stem
        legacy_metadata = main_helper.import_archive(legacy_metadata_filepath)
        legacy_metadata = create_metadata(legacy_metadata, api_type=api_type).convert()
        new_format.append(legacy_metadata)
        delete_legacy_metadatas.append(legacy_metadata_filepath)
    new_metadata_object = create_metadata(new_metadata_set)
    old_metadata_set = dict(api_helper.merge_dictionaries(new_format))
    old_metadata_object = create_metadata(old_metadata_set)
    results = compare_metadata(new_metadata_object, old_metadata_object)
    pass
    return results, delete_legacy_metadatas


def test(new_item, old_item):
    new_found = None
    if old_item.media_id is None:
        for link in old_item.links:
            # Handle Links
            a = urlparse(link)
            link2 = os.path.basename(a.path)
            if any(link2 in new_link for new_link in new_item.links):
                new_found = new_item
                break
            print
    elif old_item.media_id == new_item.media_id:
        new_found = new_item
    return new_found


def compare_metadata(
    new_metadata: create_metadata, old_metadata: create_metadata
) -> create_metadata:
    for key, value in old_metadata.content:
        new_value = getattr(new_metadata.content, key, None)
        if not new_value:
            continue
        if not value:
            setattr(old_metadata, key, new_value)
        for key2, value2 in value:
            new_value2 = getattr(new_value, key2)
            seen = set()
            old_status = []
            for d in value2:
                if d.post_id not in seen:
                    seen.add(d.post_id)
                    old_status.append(d)
                else:
                    print
            setattr(value, key2, old_status)
            value2 = old_status
            new_status = new_value2
            for post in old_status:
                if key != "Texts":
                    for old_media in post.medias:
                        # if old_item.post_id == 1646808:
                        #     l = True
                        new_found = None
                        new_items = [x for x in new_status if post.post_id == x.post_id]
                        if new_items:
                            for new_item in (x for x in new_items if not new_found):
                                for new_media in (
                                    x for x in new_item.medias if not new_found
                                ):
                                    new_found = test(new_media, old_media)
                                    print
                        if new_found:
                            for key3, v in new_found:
                                if key3 in [
                                    "directory",
                                    "downloaded",
                                    "size",
                                    "filename",
                                ]:
                                    continue
                                setattr(old_media, key3, v)
                            setattr(new_found, "found", True)
                else:
                    new_items = [x for x in new_status if post.post_id == x.post_id]
                    if new_items:
                        new_found = new_items[0]
                        for key3, v in new_found:
                            if key3 in ["directory", "downloaded", "size", "filename"]:
                                continue
                            setattr(post, key3, v)
                        setattr(new_found, "found", True)
                    print
            for new_post in new_status:
                not_found = []
                if key != "Texts":
                    not_found = [
                        new_post
                        for media in new_post.medias
                        if not getattr(media, "found", None)
                    ][:1]
                else:
                    found = getattr(new_post, "found", None)
                    if not found:
                        not_found.append(new_post)

                if not_found:
                    old_status += not_found
            old_status.sort(key=lambda x: x.post_id, reverse=True)
    new_metadata = old_metadata
    return new_metadata


# Scrapes the API for content


async def media_scraper(
    post_result: Union[create_story, create_post, create_message],
    subscription: create_user,
    formatted_directory: Path,
    api_type: str,
):
    authed = subscription.get_authed()
    api = authed.api
    site_settings = api.get_site_settings()
    if not site_settings:
        return
    new_set: dict[str, Any] = {}
    new_set["content"] = []
    directories = []
    if api_type == "Stories":
        pass
    if api_type == "Archived":
        pass
    if api_type == "Posts":
        pass
    if api_type == "Products":
        pass
    if api_type == "Messages":
        pass
    download_path = formatted_directory
    model_username = subscription.username
    date_format = site_settings.date_format
    locations = api.Locations()
    for media_type, alt_media_types in locations.__dict__.items():
        date_today = datetime.now()
        master_date = datetime.strftime(date_today, "%d-%m-%Y %H:%M:%S")
        file_directory_format = site_settings.file_directory_format
        post_id = post_result.id
        new_post = {}
        new_post["medias"] = []
        new_post["archived"] = False
        rawText = ""
        text = ""
        previews = []
        date = None
        price = None

        if isinstance(post_result, create_story):
            date = post_result.createdAt
        if isinstance(post_result, create_post):
            if post_result.isReportedByMe:
                continue
            rawText = post_result.rawText
            text = post_result.text
            previews = post_result.preview
            date = post_result.postedAt
            price = post_result.price
            new_post["archived"] = post_result.isArchived
        if isinstance(post_result, create_product):
            if post_result.isReportedByMe:
                continue
            rawText = post_result.rawText
            text = post_result.text
            previews = post_result.preview
            date = post_result.postedAt
            price = post_result.price
            new_post["archived"] = post_result.isArchived
        if isinstance(post_result, create_message):
            if post_result.isReportedByMe:
                continue
            text = post_result.text
            previews = post_result.previews
            date = post_result.createdAt
            price = post_result.price
            if api_type == "Mass Messages":
                media_user = post_result.fromUser
                media_username = media_user.username
                if media_username != model_username:
                    continue
        final_text = rawText if rawText else text

        if date == "-001-11-30T00:00:00+00:00":
            date_string = master_date
            date_object = datetime.strptime(master_date, "%d-%m-%Y %H:%M:%S")
        else:
            if not date:
                date = master_date
            if "T" in date:
                date_object = datetime.fromisoformat(date)
            else:
                date_object = datetime.strptime(date, "%d-%m-%Y %H:%M:%S")

            date_string = date_object.replace(tzinfo=None).strftime("%d-%m-%Y %H:%M:%S")
            master_date = date_string
        new_post["post_id"] = post_id
        new_post["user_id"] = subscription.id
        if isinstance(post_result, create_message):
            new_post["user_id"] = post_result.fromUser.id

        new_post["text"] = final_text
        new_post["postedAt"] = date_string
        new_post["paid"] = False
        new_post["preview_media_ids"] = previews
        new_post["api_type"] = api_type
        new_post["price"] = 0
        if price is None:
            price = 0
        if price:
            if all(media["canView"] for media in post_result.media):
                new_post["paid"] = True
            else:
                print
        new_post["price"] = price
        for media in post_result.media:
            media_id = media["id"]
            preview_link = ""
            link = await post_result.link_picker(media, site_settings.video_quality)
            matches = ["us", "uk", "ca", "ca2", "de"]

            if not link:
                continue
            url = urlparse(link)
            if not url.hostname:
                continue
            subdomain = url.hostname.split(".")[0]
            preview_link = media["preview"]
            if any(subdomain in nm for nm in matches):
                subdomain = url.hostname.split(".")[1]
                if "upload" in subdomain:
                    continue
                if "convert" in subdomain:
                    link = preview_link
            rules = [link == "", preview_link == ""]
            if all(rules):
                continue
            new_media: dict[str, Any] = dict()
            new_media["media_id"] = media_id
            new_media["links"] = []
            new_media["media_type"] = media_type
            new_media["preview"] = False
            new_media["created_at"] = new_post["postedAt"]
            if isinstance(post_result, create_story):
                date_object = datetime.fromisoformat(media["createdAt"])
                date_string = date_object.replace(tzinfo=None).strftime(
                    "%d-%m-%Y %H:%M:%S"
                )
                new_media["created_at"] = date_string
            if int(media_id) in new_post["preview_media_ids"]:
                new_media["preview"] = True
            for xlink in link, preview_link:
                if xlink:
                    new_media["links"].append(xlink)
                    break

            if media["type"] not in alt_media_types:
                continue
            matches = [s for s in site_settings.ignored_keywords if s in final_text]
            if matches:
                print("Ignoring - ", f"PostID: {post_id}")
                continue
            filename = link.rsplit("/", 1)[-1]
            filename, ext = os.path.splitext(filename)
            ext = ext.__str__().replace(".", "").split("?")[0]
            final_api_type = (
                os.path.join("Archived", api_type) if new_post["archived"] else api_type
            )
            option = {}
            option = option | new_post
            option["site_name"] = "StarsAVN"
            option["media_id"] = media_id
            option["filename"] = filename
            option["api_type"] = final_api_type
            option["media_type"] = media_type
            option["ext"] = ext
            option["profile_username"] = authed.username
            option["model_username"] = model_username
            option["date_format"] = date_format
            option["postedAt"] = new_media["created_at"]
            option["text_length"] = site_settings.text_length
            option["directory"] = download_path
            option["preview"] = new_media["preview"]
            option["archived"] = new_post["archived"]

            prepared_format = prepare_reformat(option)
            file_directory = await prepared_format.reformat_2(file_directory_format)
            prepared_format.directory = file_directory
            file_path = await prepared_format.reformat_2(site_settings.filename_format)
            new_media["directory"] = os.path.join(file_directory)
            new_media["filename"] = os.path.basename(file_path)
            if file_directory not in directories:
                directories.append(file_directory)
            new_media["linked"] = None
            for k, v in subscription.temp_scraped:
                if k == api_type:
                    continue
                if k == "Archived":
                    v = getattr(v, api_type, [])
                if v:
                    for post in v:
                        found_medias = []
                        medias = post.media
                        if medias:
                            for temp_media in medias:
                                temp_filename = temp_media.get("filename")
                                if temp_filename:
                                    if temp_filename == new_media["filename"]:
                                        found_medias.append(temp_media)
                                else:
                                    continue
                        # found_medias = [x for x in medias
                        #                 if x["filename"] == new_media["filename"]]
                        if found_medias:
                            for found_media in found_medias:
                                found_media["linked"] = api_type
                            new_media["linked"] = post["api_type"]
                            new_media["filename"] = f"linked_{new_media['filename']}"
                            print
                        print
                    print
                print
            new_post["medias"].append(new_media)
        found_post = [x for x in new_set["content"] if x["post_id"] == post_id]
        if found_post:
            found_post = found_post[0]
            found_post["medias"] += new_post["medias"]
        else:
            new_set["content"].append(new_post)
    new_set["directories"] = directories
    return new_set


# Downloads scraped content


async def prepare_downloads(subscription: create_user):
    download_info = subscription.download_info
    if not download_info:
        return
    directory = download_info["directory"]
    for api_type, metadata_path in download_info["metadata_locations"].items():
        Session, engine = db_helper.create_database_session(metadata_path)
        database_session: scoped_session = Session()
        db_collection = db_helper.database_collection()
        database = db_collection.database_picker("user_data")
        if database:
            media_table = database.media_table
            settings = subscription.subscriber.extras["settings"]["supported"][
                "starsavn"
            ]["settings"]
            overwrite_files = settings["overwrite_files"]
            if overwrite_files:
                download_list: Any = (
                    database_session.query(media_table)
                    .filter(media_table.api_type == api_type)
                    .all()
                )
                media_set_count = len(download_list)
            else:
                download_list: Any = (
                    database_session.query(media_table)
                    .filter(media_table.downloaded == False)
                    .filter(media_table.api_type == api_type)
                )
                media_set_count = db_helper.get_count(download_list)
            location = ""
            string = "Download Processing\n"
            string += f"Name: {subscription.username} | Type: {api_type} | Count: {media_set_count}{location} | Directory: {directory}\n"
            if media_set_count:
                print(string)
                await main_helper.async_downloads(download_list, subscription)
            while True:
                try:
                    database_session.commit()
                    break
                except OperationalError:
                    database_session.rollback()
            database_session.close()
        print
    print


def format_options(
    f_list: list[create_auth | create_user | SimpleNamespace | dict[str, Any] | str],
    choice_type: str,
    match_list: list[str] = [],
) -> list:
    new_item = {}
    new_item["auth_count"] = -1
    new_item["username"] = "All"
    new_item = json.loads(
        json.dumps(new_item), object_hook=lambda d: SimpleNamespace(**d)
    )
    f_list = [new_item] + f_list
    name_count = len(f_list)

    count = 0
    names: list[
        list[create_auth | create_user | SimpleNamespace | dict[str, Any] | str]
    ] = []
    string = ""
    separator = " | "
    if name_count > 1:
        match choice_type:
            case "users":
                for auth in f_list:
                    if not isinstance(auth, create_auth):
                        name = getattr(auth, "username", "")
                    else:
                        name = auth.auth_details.username
                    names.append([auth, name])
                    string += f"{count} = {name}"
                    if count + 1 != name_count:
                        string += separator
                    count += 1
            case "usernames":
                auth_count = 0
                for x in f_list:
                    if isinstance(x, create_auth) or isinstance(x, dict):
                        continue
                    name = x.username
                    string += f"{count} = {name}"
                    if isinstance(x, create_user):
                        auth_count = match_list.index(x.subscriber)
                    names.append([auth_count, name])
                    if count + 1 != name_count:
                        string += separator
                    count += 1
                    auth_count += 1
            case "apis":
                names = f_list
                for api in f_list:
                    if isinstance(api, SimpleNamespace):
                        name = getattr(api, "username", None)
                    else:
                        if isinstance(api, create_auth) or isinstance(api, create_user):
                            continue
                        name = api.get("api_type")
                    string += f"{count} = {name}"
                    if count + 1 != name_count:
                        string += separator
                    count += 1
    return [names, string]
