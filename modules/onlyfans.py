import hashlib
import shutil
import timeit
from helpers import db_helper
from helpers.db_helper import database_collection
from typing import Union
from apis.onlyfans.onlyfans import auth_details, content_types, create_auth, create_subscription, media_types, start
from classes.prepare_metadata import create_metadata, format_content, prepare_reformat
import os
from datetime import datetime, timedelta
from itertools import chain, product
from urllib.parse import urlparse
import copy
import json
import html
import extras.OFRenamer.start as ofrenamer

import requests

import helpers.main_helper as main_helper
from types import SimpleNamespace
from mergedeep import merge, Strategy
import sqlite3
import sqlalchemy
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import session, sessionmaker
from helpers.main_helper import download_session, export_data, import_archive
import time
from queue import Queue
from threading import Thread

multiprocessing = main_helper.multiprocessing

site_name = "OnlyFans"
json_config = None
json_global_settings = None
max_threads = -1
json_settings = None
auto_choice = None
profile_directory = ""
download_directory = ""
metadata_directory = ""
file_directory_format = None
filename_format = None
metadata_directory_format = ""
delete_legacy_metadata = False
overwrite_files = None
date_format = None
ignored_keywords = None
ignore_type = None
blacklist_name = None
webhook = None
text_length = None
app_token = None


def assign_vars(json_auth: auth_details, config, site_settings, site_name):
    global json_config, json_global_settings, max_threads, json_settings, auto_choice, profile_directory, download_directory, metadata_directory, metadata_directory_format, delete_legacy_metadata, overwrite_files, date_format, file_directory_format, filename_format, ignored_keywords, ignore_type, blacklist_name, webhook, text_length, app_token

    json_config = config
    json_global_settings = json_config["settings"]
    max_threads = json_global_settings["max_threads"]
    json_settings = site_settings
    auto_choice = json_settings["auto_choice"]
    profile_directory = main_helper.get_directory(
        json_global_settings['profile_directories'], ".profiles")
    download_directory = main_helper.get_directory(
        json_settings['download_directories'], ".sites")
    metadata_directory = main_helper.get_directory(
        json_settings['metadata_directories'], ".metadatas")
    file_directory_format = json_settings["file_directory_format"]
    filename_format = json_settings["filename_format"]
    metadata_directory_format = json_settings["metadata_directory_format"]
    delete_legacy_metadata = json_settings["delete_legacy_metadata"]
    overwrite_files = json_settings["overwrite_files"]
    date_format = json_settings["date_format"]
    ignored_keywords = json_settings["ignored_keywords"]
    ignore_type = json_settings["ignore_type"]
    blacklist_name = json_settings["blacklist_name"]
    webhook = json_settings["webhook"]
    text_length = json_settings["text_length"]
    app_token = json_auth.app_token


def account_setup(api: start, identifiers: list = [], jobs: dict = {}):
    status = False
    subscriptions = []
    authed = api.login()
    if isinstance(authed, create_auth):
        profile_directory = json_global_settings["profile_directories"][0]
        profile_directory = os.path.abspath(profile_directory)
        profile_directory = os.path.join(profile_directory, authed.username)
        profile_metadata_directory = os.path.join(
            profile_directory, "Metadata")
        metadata_filepath = os.path.join(
            profile_metadata_directory, "Mass Messages.json")
        print
        if authed.isPerformer:
            imported = import_archive(metadata_filepath)
            if "auth" in imported:
                imported = imported["auth"]
            mass_messages = api.get_mass_messages(resume=imported)
            if mass_messages:
                main_helper.export_data(mass_messages, metadata_filepath)
        # chats = api.get_chats()
        if identifiers or jobs["scrape_names"]:
            subscriptions += manage_subscriptions(
                api, -1, identifiers=identifiers)
        status = True
    return status, subscriptions

# The start lol


def start_datascraper(api: start, identifier, site_name, choice_type=None):
    print("Scrape Processing")
    subscription = api.get_subscription(identifier=identifier)
    if not subscription:
        return [False, subscription]
    post_count = subscription.postsCount
    user_id = str(subscription.id)
    avatar = subscription.avatar
    username = subscription.username
    link = subscription.link
    print("Name: "+username)
    api_array = scrape_choice(api, subscription)
    api_array = format_options(api_array, "apis")
    apis = api_array[0]
    api_string = api_array[1]
    if not json_settings["auto_scrape_apis"]:
        print(f"Apis: {api_string}")
        value = int(input().strip())
    else:
        value = 0
    if value:
        apis = [apis[value]]
    else:
        apis.pop(0)
    metadata_locations = {}
    for item in apis:
        print("Type: "+item["api_type"])
        only_links = item["api_array"]["only_links"]
        post_count = str(item["api_array"]["post_count"])
        item["api_array"]["username"] = username
        item["api_array"]["subscription"] = subscription
        api_type = item["api_type"]
        results = prepare_scraper(
            api, site_name, item)
        print
    print("Scrape Completed"+"\n")
    return [True, subscription]


# Checks if the model is valid and grabs content count
def link_check(api: start, identifier):
    y = api.get_user(identifier)
    return y


# Allows the user to choose which api they want to scrape
def scrape_choice(api: start, subscription):
    user_id = subscription.id
    post_count = subscription.postsCount
    archived_count = subscription.archivedPostsCount
    media_types = ["Images", "Videos", "Audios", "Texts"]
    if auto_choice:
        input_choice = auto_choice
    else:
        print('Scrape: a = Everything | b = Images | c = Videos | d = Audios | e = Texts')
        input_choice = input().strip()
    user_api = api.links(user_id).users
    message_api = api.links(user_id).message_api
    mass_messages_api = api.links().mass_messages_api
    stories_api = api.links(user_id).stories_api
    list_highlights = api.links(user_id).list_highlights
    post_api = api.links(user_id).post_api
    archived_api = api.links(user_id).archived_posts
    # ARGUMENTS
    only_links = False
    if "-l" in input_choice:
        only_links = True
        input_choice = input_choice.replace(" -l", "")
    mandatory = [download_directory, only_links]
    y = ["photo", "video", "stream", "gif", "audio", "text"]
    u_array = ["You have chosen to scrape {}", [
        user_api, media_types, *mandatory, post_count], "Profile"]
    s_array = ["You have chosen to scrape {}", [
        stories_api, media_types, *mandatory, post_count], "Stories"]
    h_array = ["You have chosen to scrape {}", [
        list_highlights, media_types, *mandatory, post_count], "Highlights"]
    p_array = ["You have chosen to scrape {}", [
        post_api, media_types, *mandatory, post_count], "Posts"]
    m_array = ["You have chosen to scrape {}", [
        message_api, media_types, *mandatory, post_count], "Messages"]
    a_array = ["You have chosen to scrape {}", [
        archived_api, media_types, *mandatory, archived_count], "Archived"]
    array = [u_array, s_array, p_array, a_array, m_array]
    # array = [u_array, s_array, p_array, a_array, m_array]
    # array = [s_array, h_array, p_array, a_array, m_array]
    # array = [s_array]
    # array = [u_array]
    # array = [p_array]
    # array = [a_array]
    # array = [m_array]
    new_array = []
    valid_input = True
    for xxx in array:
        if xxx[2] == "Mass Messages":
            if not subscription.is_me:
                continue
        new_item = dict()
        new_item["api_message"] = xxx[0]
        new_item["api_array"] = {}
        new_item["api_array"]["api_link"] = xxx[1][0]
        new_item["api_array"]["media_types"] = xxx[1][1]
        new_item["api_array"]["directory"] = xxx[1][2]
        new_item["api_array"]["only_links"] = xxx[1][3]
        new_item["api_array"]["post_count"] = xxx[1][4]
        formatted = format_media_types()
        if input_choice == "a":
            name = "All"
            new_item["api_array"]["media_types"] = formatted
        elif input_choice == "b":
            name = "Images"
            new_item["api_array"]["media_types"] = [formatted[0]]
            print
        elif input_choice == "c":
            name = "Videos"
            new_item["api_array"]["media_types"] = [formatted[1]]
        elif input_choice == "d":
            name = "Audios"
            new_item["api_array"]["media_types"] = [formatted[2]]
        elif input_choice == "e":
            name = "Texts"
            new_item["api_array"]["media_types"] = [formatted[3]]
        else:
            print("Invalid Choice")
            valid_input = False
            break
        new_item["api_type"] = xxx[2]
        if valid_input:
            new_array.append(new_item)
    return new_array


# Downloads the model's avatar and header
def profile_scraper(api: start, site_name, api_type, username, base_directory):
    reformats = {}
    reformats["metadata_directory_format"] = json_settings["metadata_directory_format"]
    reformats["file_directory_format"] = json_settings["file_directory_format"]
    reformats["file_directory_format"] = reformats["file_directory_format"].replace(
        "{value}", "")
    reformats["filename_format"] = json_settings["filename_format"]
    option = {}
    option["site_name"] = site_name
    option["api_type"] = api_type
    option["username"] = username
    option["date_format"] = date_format
    option["maximum_length"] = text_length
    option["directory"] = base_directory
    a, b, c = prepare_reformat(option, keep_vars=True).reformat(reformats)
    print
    y = api.get_subscription(identifier=username)
    override_media_types = []
    avatar = y.avatar
    header = y.header
    if avatar:
        override_media_types.append(["Avatars", avatar])
    if header:
        override_media_types.append(["Headers", header])
    d_session = download_session()
    d_session.start(unit='B', unit_scale=True,
                    miniters=1)
    for override_media_type in override_media_types:
        new_dict = dict()
        media_type = override_media_type[0]
        media_link = override_media_type[1]
        new_dict["links"] = [media_link]
        directory2 = os.path.join(b, media_type)
        os.makedirs(directory2, exist_ok=True)
        download_path = os.path.join(
            directory2, media_link.split("/")[-2]+".jpg")
        if not overwrite_files:
            if os.path.isfile(download_path):
                continue
        session = api.session_manager.sessions[0]
        r = api.json_request(media_link, session, stream=True,
                             json_format=False, sleep=False)
        if not isinstance(r, requests.Response):
            continue
        tsize = r.headers.get("content-length")
        d_session.update_total_size(tsize)
        downloaded = main_helper.downloader(r, download_path, d_session)
        if not downloaded:
            continue
    d_session.close()


def paid_content_scraper(apis: list[start], identifiers=[]):
    for api in apis:
        paid_contents = []
        paid_contents = api.get_paid_content()
        authed = api.auth
        if not authed.active:
            return
        authed.subscriptions = authed.subscriptions
        for paid_content in paid_contents:
            author = paid_content.get("author")
            author = paid_content.get("fromUser", author)
            subscription = api.get_subscription(
                check=True, identifier=author["id"])
            if not subscription:
                subscription = create_subscription(author)
                authed.subscriptions.append(subscription)
            if paid_content["responseType"] == "post":
                if paid_content["isArchived"]:
                    print(f"Model: {author['username']}")
                    # print(
                    #     "ERROR, PLEASE REPORT THIS AS AN ISSUE AND TELL ME WHICH MODEL YOU'RE SCRAPIMG, THANKS")
                    # input()
                    # exit()
            api_type = paid_content["responseType"].capitalize()+"s"
            api_media = getattr(subscription.scraped, api_type)
            api_media.append(paid_content)
        count = 0
        max_count = len(authed.subscriptions)
        for subscription in authed.subscriptions:
            if any(subscription.username != x for x in identifiers):
                continue
            string = f"Scraping - {subscription.username} | {count} / {max_count}"
            print(string)
            subscription.session_manager = api.session_manager
            username = subscription.username
            site_name = "OnlyFans"
            media_type = format_media_types()
            count += 1
            for api_type, paid_content in subscription.scraped:
                if api_type == "Archived":
                    if any(x for k, x in paid_content if not x):
                        input(
                            "OPEN A ISSUE GITHUB ON GITHUB WITH THE MODEL'S USERNAME AND THIS ERROR, THANKS")
                        exit(0)
                    continue
                mandatory_directories = {}
                mandatory_directories["profile_directory"] = profile_directory
                mandatory_directories["download_directory"] = download_directory
                mandatory_directories["metadata_directory"] = metadata_directory
                formatted_directories = format_directories(
                    mandatory_directories, site_name, username, metadata_directory_format, media_type, api_type)
                formatted_metadata_directory = formatted_directories["metadata_directory"]
                metadata_path = os.path.join(
                    formatted_metadata_directory, api_type+".db")
                unrefined_set = media_scraper(paid_content, api, subscription,
                                              formatted_directories, username, api_type)
                unrefined_set = [x for x in [unrefined_set]]
                new_metadata = main_helper.format_media_set(unrefined_set)
                new_metadata = new_metadata["content"]
                if new_metadata:
                    api_path = os.path.join(api_type, "")
                    old_metadata, delete_metadatas = process_legacy_metadata(
                        api, new_metadata, formatted_directories, subscription, api_type, api_path, metadata_path, site_name)
                    parent_type = ""
                    new_metadata = new_metadata + old_metadata
                    w = process_metadata(metadata_path, formatted_directories, new_metadata,
                                         site_name, parent_type, api_path, subscription, delete_metadatas)
                    print


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


def process_messages(api: start, subscription, messages) -> list:
    if "list" in messages:
        unrefined_set = messages["list"]
    elif not messages:
        unrefined_set = []
    else:
        unrefined_set = [messages]
    return unrefined_set


def process_mass_messages(api: start, subscription, metadata_directory, mass_messages) -> list:
    def compare_message(queue_id, remote_messages):
        for message in remote_messages:
            if "isFromQueue" in message and message["isFromQueue"]:
                if queue_id == message["queueId"]:
                    return message
                print
        print
    global_found = []
    chats = []
    session = api.session_manager.sessions[0]
    salt = json_global_settings["random_string"]
    encoded = f"{session.ip}{salt}"
    encoded = encoded.encode('utf-8')
    hash = hashlib.md5(encoded).hexdigest()
    profile_directory = json_global_settings["profile_directories"][0]
    profile_directory = os.path.abspath(profile_directory)
    profile_directory = os.path.join(profile_directory, subscription.username)
    profile_metadata_directory = os.path.join(profile_directory, "Metadata")
    mass_message_path = os.path.join(
        profile_metadata_directory, "Mass Messages.json")
    chats_path = os.path.join(profile_metadata_directory, "Chats.json")
    if os.path.exists(chats_path):
        chats = import_archive(chats_path)
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
        mass_message["date_hashed"] = mass_message.get(
            "date_hashed", date_string)
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
                list_chats2 = [
                    x for x in chats if x["identifier"] == identifier]
                if list_chats2:
                    chat2 = list_chats2[0]
                    messages = chat2["messages"]["list"]
                    messages = subscription.get_messages(
                        identifier=identifier, resume=messages)
                    for message in messages:
                        message["withUser"] = {
                            k: item["withUser"][k] for k in keep}
                        message["fromUser"] = {
                            k: message["fromUser"][k] for k in keep}
                    mass_found = compare_message(queue_id, messages)
                    if mass_found:
                        mass_message["found"] = mass_found
                        mass_message["status"] = True
                        break
                else:
                    item2 = {}
                    item2["identifier"] = identifier
                    item2["messages"] = subscription.get_messages(
                        identifier=identifier)
                    chats.append(item2)
                    messages = item2["messages"]["list"]
                    for message in messages:
                        message["withUser"] = {
                            k: item["withUser"][k] for k in keep}
                        message["fromUser"] = {
                            k: message["fromUser"][k] for k in keep}
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
                mass_message["date_hashed"], "%d-%m-%Y %H:%M:%S")
            next_date_object = date_hashed_object+timedelta(days=1)
            print
            if mass_message["hashed_ip"] != hash or date_object > next_date_object:
                print("Getting Message By ID")
                x = subscription.get_message_by_id(
                    identifier=identifier, identifier2=found["id"], limit=1)
                new_found = x["result"]["list"][0]
                new_found["withUser"] = found["withUser"]
                mass_message["found"] = new_found
                mass_message["hashed_ip"] = hash
                mass_message["date_hashed"] = date_string
            global_found.append(found)
        print
    print
    main_helper.export_data(
        mass_messages, mass_message_path)
    return global_found


def process_legacy_metadata(api: start, new_metadata_set, formatted_directories, subscription, api_type, api_path, archive_path, site_name):
    print("Processing metadata.")
    delete_metadatas = []
    legacy_metadata2 = formatted_directories["legacy_metadatas"]["legacy_metadata2"]
    legacy_metadata_path2 = os.path.join(
        legacy_metadata2, os.path.basename(archive_path))
    exists = os.path.exists(legacy_metadata_path2)
    exists2 = os.path.exists(archive_path)
    if legacy_metadata_path2 != archive_path:
        if exists and not exists2:
            os.makedirs(os.path.dirname(archive_path), exist_ok=True)
            shutil.move(legacy_metadata_path2, archive_path)
    archive_path = archive_path.replace("db", "json")
    legacy_metadata_object, delete_legacy_metadatas = legacy_metadata_fixer(
        formatted_directories, api)
    if delete_legacy_metadatas:
        print("Merging new metadata with legacy metadata.")
        delete_metadatas.extend(delete_legacy_metadatas)
    old_metadata_set = import_archive(archive_path)
    old_metadata_object = create_metadata(
        api, old_metadata_set, api_type=api_type)
    if old_metadata_set:
        print("Merging new metadata with old metadata.")
    old_metadata_object = compare_metadata(
        old_metadata_object, legacy_metadata_object)
    old_metadata_set = []
    for media_type, value in old_metadata_object.content:
        for status, value2 in value:
            for value3 in value2:
                x = value3.medias
                item = value3.convert(keep_empty_items=True)
                old_metadata_set.append(item)
            print
        print
    print
    if old_metadata_set:
        delete_metadatas.append(archive_path)
    final_set = []
    for item in old_metadata_set:
        item["api_type"] = api_type
        x = [x for x in new_metadata_set if x["post_id"] == item["post_id"]]
        if not x:
            final_set.append(item)
            print
        print
    print("Finished processing metadata.")
    return final_set, delete_metadatas


def process_metadata(archive_path: str, formatted_directories: dict, new_metadata_object, site_name, parent_type, api_path, subscription, delete_metadatas):
    print
    Session, api_type, folder = main_helper.export_sqlite(
        archive_path, new_metadata_object, parent_type)
    if not subscription.download_info:
        subscription.download_info["metadata_locations"] = {}
    subscription.download_info["directory"] = download_directory
    subscription.download_info["webhook"] = webhook
    database_name = parent_type if parent_type else api_type
    subscription.download_info["metadata_locations"][api_type] = {}
    subscription.download_info["metadata_locations"][api_type][database_name] = archive_path
    print("Renaming files.")
    new_metadata_object = ofrenamer.start(
        Session, parent_type, api_type, api_path, site_name, subscription, folder, json_settings)
    if delete_legacy_metadata:
        for old_metadata in delete_metadatas:
            if os.path.exists(old_metadata):
                os.remove(old_metadata)


def format_directories(directories, site_name, username, unformatted, locations: list = [], api_type="") -> dict:
    x = {}
    x["profile_directory"] = ""
    x["legacy_metadatas"] = {}
    for key, directory in directories.items():
        option = {}
        option["site_name"] = site_name
        option["username"] = username
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
                directory, site_name, username)
            x["legacy_metadatas"]["legacy_metadata"] = os.path.join(
                legacy_model_directory, api_type, "Metadata")
            x["legacy_metadatas"]["legacy_metadata2"] = os.path.join(
                legacy_model_directory, "Metadata")
        if key == "metadata_directory":
            x["metadata_directory"] = main_helper.reformat(
                prepared_format, unformatted)
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


def prepare_scraper(api: start, site_name, item):
    authed = api.auth
    api_type = item["api_type"]
    api_array = item["api_array"]
    subscription = api_array["subscription"]
    media_type = api_array["media_types"]
    username = api_array["username"]
    master_set = []
    pool = multiprocessing()
    mandatory_directories = {}
    mandatory_directories["profile_directory"] = profile_directory
    mandatory_directories["download_directory"] = download_directory
    mandatory_directories["metadata_directory"] = metadata_directory
    formatted_directories = format_directories(
        mandatory_directories, site_name, username, metadata_directory_format, media_type, api_type)
    legacy_model_directory = formatted_directories["legacy_model_directory"]
    formatted_download_directory = formatted_directories["download_directory"]
    formatted_metadata_directory = formatted_directories["metadata_directory"]
    if api_type == "Profile":
        profile_scraper(api, site_name, api_type, username,
                        formatted_download_directory)
        return True
    if api_type == "Stories":
        master_set = subscription.get_stories()
        highlights = subscription.get_highlights()
        valid_highlights = []
        for highlight in highlights:
            if "error" == highlight:
                continue
            highlight = subscription.get_highlights(
                hightlight_id=highlight["id"])
            valid_highlights.append(highlight)
        master_set.extend(valid_highlights)
        print
    if api_type == "Posts":
        master_set = subscription.get_posts()
    if api_type == "Archived":
        master_set = subscription.get_archived(api)
    if api_type == "Messages":
        unrefined_set = subscription.get_messages()
        unrefined_set = process_messages(api, subscription, unrefined_set)
        mass_messages = getattr(authed, "mass_messages")
        if subscription.is_me and mass_messages:
            mass_messages = getattr(authed, "mass_messages")
            unrefined_set2 = process_mass_messages(api,
                                                   subscription, formatted_metadata_directory, mass_messages)
            unrefined_set += unrefined_set2
        master_set = [unrefined_set]
    master_set2 = master_set
    parent_type = ""
    if "Archived" == api_type:
        unrefined_set = []
        for master_set3 in master_set2:
            if not isinstance(master_set3, dict):
                continue
            parent_type = master_set3["type"]
            results = master_set3["results"]
            unrefined_result = pool.starmap(media_scraper, product(
                results, [api], [subscription], [formatted_directories], [username], [api_type], [parent_type]))
            unrefined_set.append(unrefined_result)
        unrefined_set = list(chain(*unrefined_set))
    else:
        unrefined_set = pool.starmap(media_scraper, product(
            master_set2, [api], [subscription], [formatted_directories], [username], [api_type], [parent_type]))
        unrefined_set = [x for x in unrefined_set]
    new_metadata = main_helper.format_media_set(unrefined_set)
    if new_metadata:
        new_metadata = new_metadata["content"]
        metadata_path = os.path.join(
            formatted_metadata_directory, api_type+".db")
        api_path = os.path.join(api_type, parent_type)
        old_metadata, delete_metadatas = process_legacy_metadata(
            api, new_metadata, formatted_directories, subscription, api_type, api_path, metadata_path, site_name)
        new_metadata = new_metadata + old_metadata
        subscription.set_scraped(api_type, new_metadata)
        print
        w = process_metadata(metadata_path, formatted_directories, new_metadata,
                             site_name, parent_type, api_path, subscription, delete_metadatas)
        print
    else:
        print("No "+api_type+" Found.")
        delattr(subscription.scraped, api_type)

    return True


def legacy_metadata_fixer(formatted_directories: dict, api: object) -> tuple[create_metadata, list]:
    delete_legacy_metadatas = []
    legacy_metadatas = formatted_directories["legacy_metadatas"]
    new_metadata_directory = formatted_directories["metadata_directory"]
    old_metadata_directory = os.path.dirname(
        legacy_metadatas["legacy_metadata"])
    metadata_name = os.path.basename(f"{old_metadata_directory}.json")
    q = []
    for key, legacy_directory in legacy_metadatas.items():
        if legacy_directory == formatted_directories["metadata_directory"]:
            continue
        if os.path.exists(legacy_directory):
            folders = os.listdir(legacy_directory)
            api_names = [metadata_name]
            metadata_names = media_types()
            metadata_names = [f"{k}.json" for k, v in metadata_names]
            api_names += metadata_names
            print
            type_one_files = main_helper.remove_mandatory_files(
                folders, keep=api_names)
            new_format = []
            for type_one_file in type_one_files:
                api_type = type_one_file.removesuffix(".json")
                legacy_metadata_path = os.path.join(
                    legacy_directory, type_one_file)
                legacy_metadata = import_archive(legacy_metadata_path)
                if legacy_metadata:
                    delete_legacy_metadatas.append(legacy_metadata_path)
                legacy_metadata = create_metadata(
                    api, legacy_metadata, api_type=api_type).convert()
                new_format.append(legacy_metadata)
            new_format = dict(
                merge({}, *new_format, strategy=Strategy.ADDITIVE))
            old_metadata_object = create_metadata(api, new_format)
            if legacy_directory != new_metadata_directory:
                import_path = os.path.join(legacy_directory, metadata_name)
                new_metadata_set = import_archive(
                    import_path)
                if new_metadata_set:
                    new_metadata_object2 = create_metadata(
                        api, new_metadata_set)
                    old_metadata_object = compare_metadata(
                        new_metadata_object2, old_metadata_object)
            q.append(old_metadata_object)
            print
        print
    results = create_metadata()
    for merge_into in q:
        print
        results = compare_metadata(
            results, merge_into)
        print
    print
    return results, delete_legacy_metadatas


def test(new_item, old_item):
    new_found = None
    if old_item.media_id == None:
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


def compare_metadata(new_metadata: create_metadata, old_metadata: create_metadata) -> create_metadata:
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
                        new_items = [
                            x for x in new_status if post.post_id == x.post_id]
                        if new_items:
                            for new_item in (x for x in new_items if not new_found):
                                for new_media in (x for x in new_item.medias if not new_found):
                                    new_found = test(new_media, old_media)
                                    print
                        if new_found:
                            for key3, v in new_found:
                                if key3 in ["directory", "downloaded", "size", "filename"]:
                                    continue
                                setattr(old_media, key3, v)
                            setattr(new_found, "found", True)
                else:
                    new_items = [
                        x for x in new_status if post.post_id == x.post_id]
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
                        new_post for media in new_post.medias if not getattr(media, "found", None)][:1]
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


def media_scraper(results, api: start, subscription: create_subscription, formatted_directories, username, api_type, parent_type="", print_output=True):
    new_set = {}
    new_set["content"] = []
    directories = []
    session = api.session_manager.sessions[0]
    if api_type == "Stories":
        if "stories" in results:
            items = results["stories"]
            for item in items:
                item["text"] = results["title"]
            results = results["stories"]
    if api_type == "Archived":
        print
        pass
    if api_type == "Posts":
        print
    if api_type == "Messages":
        pass
    if not results or "error" in results:
        return new_set
    if "result" in results:
        session = results["session"]
        results = results["result"]
        if "error" in results:
            return new_set
    download_path = formatted_directories["download_directory"]
    for location in formatted_directories["locations"]:
        sorted_directories = copy.copy(location["sorted_directories"])
        master_date = "01-01-0001 00:00:00"
        media_type = location["media_type"]
        alt_media_type = location["alt_media_type"]
        file_directory_format = json_settings["file_directory_format"]
        if api_type == "Archived":
            x = file_directory_format.split(os.sep)
            for y in x:
                substr = "{api_type}"
                if substr == y:
                    new_path = os.path.join(substr, parent_type)
                    file_directory_format = file_directory_format.replace(
                        substr, new_path)
                    break
                print
            print
        seperator = " | "
        if print_output:
            print(
                f"Scraping [{seperator.join(alt_media_type)}]. Should take less than a minute.")
        for media_api in results:
            post_id = media_api["id"]
            new_post = {}
            new_post["medias"] = []
            rawText = media_api.get("rawText", "")
            text = media_api.get("text", "")
            final_text = rawText if rawText else text
            previews = media_api.get("preview", [])
            if api_type == "Stories":
                previews = []
            if api_type == "Messages":
                media_api["rawText"] = media_api["text"]
                previews = media_api.get("previews", None)
            if api_type == "Mass Messages":
                media_user = media_api["fromUser"]
                media_username = media_user["username"]
                if media_username != username:
                    continue
            elif api_type == "Archived":
                test_previews = media_api.get("previews", [])
                if test_previews:
                    input("REPORT THIS ERROR TO GITHUB, I'LL KNOW WHAT IT IS :)")
            # if previews == None:
            #     # REMOVE BEFORE PUSHING COMMIT
            #     input("PREVIEW NOT FOUND")
            date = media_api["postedAt"] if "postedAt" in media_api else media_api["createdAt"]
            if date == "-001-11-30T00:00:00+00:00":
                date_string = master_date
                date_object = datetime.strptime(
                    master_date, "%d-%m-%Y %H:%M:%S")
            else:
                date_object = datetime.fromisoformat(date)
                date_string = date_object.replace(tzinfo=None).strftime(
                    "%d-%m-%Y %H:%M:%S")
                master_date = date_string
            new_post["post_id"] = media_api["id"]
            new_post["text"] = final_text
            new_post["postedAt"] = date_string
            new_post["paid"] = False
            new_post["preview_media_ids"] = previews
            new_post["api_type"] = api_type
            price = new_post["price"] = media_api["price"]if "price" in media_api else None
            if price == None:
                price = 0
            canPurchase = media_api.get("canPurchase", None)
            if price:
                if all(media["canView"] for media in media_api["media"]):
                    new_post["paid"] = True
                else:
                    print
            for media in media_api["media"]:
                media_id = media["id"]
                date = "-001-11-30T00:00:00+00:00"
                size = 0
                link = ""
                preview_link = ""
                if "source" in media:
                    quality_key = "source"
                    source = media[quality_key]
                    link = source[quality_key]
                    if link:
                        if media["type"] == "video":
                            qualities = media["videoSources"]
                            qualities = dict(
                                sorted(qualities.items(), reverse=False))
                            qualities[quality_key] = source[quality_key]
                            for quality, quality_link in qualities.items():
                                video_quality_json = json_settings["video_quality"]
                                video_quality_json = video_quality_json.removesuffix(
                                    "p")
                                if quality == video_quality_json:
                                    if link:
                                        link = quality_link
                                        break
                                    print
                                print
                            print

                    size = media["info"]["preview"]["size"] if "info" in media_api else 1
                if "src" in media:
                    link = media["src"]
                    size = media["info"]["preview"]["size"] if "info" in media_api else 1
                    date = media_api["createdAt"]
                matches = ["us", "uk", "ca", "ca2", "de"]

                if not link:
                    continue
                url = urlparse(link)
                subdomain = url.hostname.split('.')[0]
                preview_link = media["preview"]
                if any(subdomain in nm for nm in matches):
                    subdomain = url.hostname.split('.')[1]
                    if "upload" in subdomain:
                        continue
                    if "convert" in subdomain:
                        link = preview_link
                rules = [link == "",
                         preview_link == ""]
                if all(rules):
                    continue
                new_media = dict()
                new_media["media_id"] = media_id
                new_media["links"] = []
                new_media["media_type"] = media_type
                new_media["preview"] = False
                if int(media_id) in new_post["preview_media_ids"]:
                    new_media["preview"] = True
                for xlink in link, preview_link:
                    if xlink:
                        new_media["links"].append(xlink)
                        break

                if media["type"] not in alt_media_type:
                    continue
                session.links.extend(new_media["links"])
                matches = [s for s in ignored_keywords if s in final_text]
                if matches:
                    print("Matches: ", matches)
                    continue
                filename = link.rsplit('/', 1)[-1]
                filename, ext = os.path.splitext(filename)
                ext = ext.__str__().replace(".", "").split('?')[0]

                option = {}
                option = option | new_post
                option["site_name"] = "OnlyFans"
                option["media_id"] = media_id
                option["filename"] = filename
                option["api_type"] = api_type
                option["media_type"] = media_type
                option["ext"] = ext
                option["username"] = username
                option["date_format"] = date_format
                option["text_length"] = text_length
                option["directory"] = download_path
                option["preview"] = new_media["preview"]

                prepared_format = prepare_reformat(option)
                file_directory = main_helper.reformat(
                    prepared_format, file_directory_format)
                prepared_format.directory = file_directory
                file_path = main_helper.reformat(
                    prepared_format, filename_format)
                new_media["directory"] = os.path.join(file_directory)
                new_media["filename"] = os.path.basename(file_path)
                if file_directory not in directories:
                    directories.append(file_directory)
                new_media["linked"] = None
                for k, v in subscription.scraped:
                    if k == api_type:
                        continue
                    if k == "Archived":
                        v = getattr(v, api_type, [])
                    if v:
                        for post in v:
                            try:
                                medias = post.get("medias",[])
                          
                                found_medias = [x for x in medias
                                                if x["filename"] == new_media["filename"]]
                          
                                if found_medias:
                                    for found_media in found_medias:
                                        found_media["linked"] = api_type
                                    new_media["linked"] = post["api_type"]
                                    new_media["filename"] = f"linked_{new_media['filename']}"
                                    print
                            except KeyError:
                                medias = post.get("media",[])
                            
                                found_medias = [x for x in medias
                                                if x["source"]["source"] == new_media["filename"]]
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
            found_post = [x for x in new_set["content"]
                          if x["post_id"] == post_id]
            if found_post:
                found_post = found_post[0]
                found_post["medias"] += new_post["medias"]
            else:
                new_set["content"].append(new_post)
    new_set["directories"] = directories
    return new_set


# Downloads scraped content
class download_media():
    def __init__(self, api=None, subscription=None) -> None:
        if api:
            username = subscription.username
            download_info = subscription.download_info
            if download_info:
                self.downloaded = True
                metadata_locations = download_info["metadata_locations"]
                directory = download_info["directory"]
                for parent_type, value in metadata_locations.items():
                    for api_type, metadata_path in value.items():
                        Session, engine = db_helper.create_database_session(
                            metadata_path)
                        database_session = Session()
                        database_name = api_type.lower()
                        db_collection = db_helper.database_collection()
                        database = db_collection.chooser(database_name)
                        api_table = database.api_table
                        media_table = database.media_table
                        result = database_session.query(media_table).all()
                        media_type_list = media_types()
                        for r in result:
                            item = getattr(media_type_list, r.media_type)
                            item.append(r)
                        media_type_list = media_type_list.__dict__
                        for location, v in media_type_list.items():
                            if location == "Texts":
                                continue
                            media_set = v
                            media_set_count = len(media_set)
                            if not media_set:
                                continue
                            string = "Download Processing\n"
                            string += f"Name: {username} | Type: {api_type} | Count: {media_set_count} {location} | Directory: {directory}\n"
                            print(string)
                            d_session = download_session()
                            d_session.start(unit='B', unit_scale=True,
                                            miniters=1)
                            pool = multiprocessing()
                            pool.starmap(self.prepare_download, product(
                                media_set, [api], [api_type], [subscription], [d_session]))
                            d_session.close()
                        database_session.commit()
            else:
                self.downloaded = False

    def prepare_download(self, media, api, api_type, subscription: create_subscription, d_session):
        return_bool = True
        if not overwrite_files and media.downloaded:
            return
        count = 0
        sessions = [
            x for x in api.session_manager.sessions if media.link in x.links]
        if not sessions:
            return
        session = sessions[0]
        while count < 11:
            links = [media.link]

            def choose_link(session, links):
                for link in links:
                    r = api.json_request(link, session, "HEAD",
                                         stream=False, json_format=False)
                    if not isinstance(r, requests.Response):
                        continue

                    header = r.headers
                    content_length = header.get('content-length')
                    if not content_length:
                        continue
                    content_length = int(content_length)
                    return [link, content_length]
            result = choose_link(session, links)
            if not result:
                result_list = []
                if api_type == "Messages":
                    result = subscription.get_message_by_id(
                        identifier2=media.post_id, limit=1)["result"]
                    result_list = result.get("list")
                    if not result_list:
                        print
                elif api_type == "Posts":
                    result = subscription.get_post(media.post_id)
                    result_list = [result.get("result")]
                else:
                    print
                mandatory_directories = {}
                mandatory_directories["profile_directory"] = profile_directory
                mandatory_directories["download_directory"] = download_directory
                mandatory_directories["metadata_directory"] = metadata_directory
                media_type = format_media_types()
                formatted_directories = format_directories(
                    mandatory_directories, site_name, subscription.username, metadata_directory_format, media_type, api_type)
                unrefined_set = media_scraper(result_list, api, subscription,
                                              formatted_directories, subscription.username, api_type, print_output=False)
                unrefined_set = [x for x in [unrefined_set]]
                new_metadata = main_helper.format_media_set(unrefined_set)
                new_metadata = new_metadata["content"]
                found_post = main_helper.format_media_set(new_metadata)
                if found_post:
                    found_media = [x for x in found_post["medias"]
                                   if x["media_id"] == media.media_id]
                    if found_media:
                        new_link = found_media[0]["links"][0]
                        media.link = new_link
                count += 1
                continue
            link = result[0]
            content_length = result[1]
            media.size = content_length
            date_object = media.created_at
            download_path = os.path.join(
                media.directory, media.filename)
            timestamp = date_object.timestamp()
            if not overwrite_files:
                if main_helper.check_for_dupe_file(download_path, content_length):
                    main_helper.format_image(download_path, timestamp)
                    return_bool = False
                    media.downloaded = True
                    break
            r = api.json_request(
                link, session, stream=True, json_format=False)
            if not isinstance(r, requests.Response):
                return_bool = False
                count += 1
                continue
            d_session.update_total_size(content_length)
            downloader = main_helper.downloader(
                r, download_path, d_session, count)
            if not downloader:
                count += 1
                continue
            main_helper.format_image(download_path, timestamp)
            media.downloaded = True
            break
        if not media.downloaded:
            print(f"Download Failed: {media.link}")
            d_session.colour = "Red"

        return return_bool


def manage_subscriptions(api: start, auth_count=0, identifiers: list = [], refresh: bool = True):
    results = api.get_subscriptions(identifiers=identifiers, refresh=refresh)
    if blacklist_name:
        r = api.get_lists()
        if not r:
            return [False, []]
        new_results = [c for c in r if blacklist_name == c["name"]]
        if new_results:
            item = new_results[0]
            list_users = item["users"]
            if int(item["usersCount"]) > 2:
                list_id = str(item["id"])
                list_users = api.get_lists_users(list_id)
            users = list_users
            bl_ids = [x["username"] for x in users]
            results2 = results.copy()
            for result in results2:
                identifier = result.username
                if identifier in bl_ids:
                    print("Blacklisted: "+identifier)
                    results.remove(result)
    results.sort(key=lambda x: x.subscribedByData.expiredAt)
    results.sort(key=lambda x: x.is_me, reverse=True)
    results2 = []
    hard_blacklist = ["onlyfanscreators"]
    for result in results:
        result.auth_count = auth_count
        username = result.username
        bl = [x for x in hard_blacklist if x == username]
        if bl:
            continue
        now = datetime.utcnow().date()
        # subscribedBy = result["subscribedBy"]
        subscribedByData = result.subscribedByData
        result_date = subscribedByData.expiredAt if subscribedByData else datetime.utcnow(
        ).isoformat()
        price = subscribedByData.price
        subscribePrice = subscribedByData.subscribePrice
        result_date = datetime.fromisoformat(
            result_date).replace(tzinfo=None).date()
        if ignore_type in ["paid"]:
            if price > 0:
                continue
        if ignore_type in ["free"]:
            if subscribePrice == 0:
                continue
        results2.append(result)
    api.auth.subscriptions = results2
    return results2


def format_options(f_list: list[Union[start, create_subscription, dict]], choice_type: str) -> list:
    new_item = {}
    new_item["auth_count"] = -1
    new_item["username"] = "All"
    new_item = json.loads(json.dumps(
        new_item), object_hook=lambda d: SimpleNamespace(**d))
    f_list = [new_item]+f_list
    name_count = len(f_list)

    count = 0
    names = []
    string = ""
    seperator = " | "
    if name_count > 1:
        if "users" == choice_type:
            for api in f_list:
                if not isinstance(api, start):
                    name = getattr(api, "username", None)
                else:
                    name = api.auth.auth_details.username
                names.append([api, name])
                string += str(count)+" = "+name
                if count+1 != name_count:
                    string += seperator
                count += 1
        if "usernames" == choice_type:
            for x in f_list:
                if isinstance(x, start) or isinstance(x, dict):
                    continue
                name = x.username
                string += str(count)+" = "+name
                names.append([x.auth_count, name])
                if count+1 != name_count:
                    string += seperator
                count += 1
        if "apis" == choice_type:
            names = f_list
            for api in f_list:
                if isinstance(api, SimpleNamespace):
                    name = getattr(api, "username", None)
                else:
                    if isinstance(api, start) or isinstance(api, create_subscription):
                        continue
                    name = api.get("api_type")
                string += f"{count} = {name}"
                if count+1 != name_count:
                    string += seperator
                count += 1
    return [names, string]
