import hashlib
from apis.onlyfans.onlyfans import create_subscription
from classes.prepare_metadata import prepare_metadata
import os
from datetime import datetime, timedelta
from itertools import chain, groupby, product
from urllib.parse import urlparse
import copy
import json
import jsonpickle
from deepdiff import DeepHash
import html
import shutil

import requests

import helpers.main_helper as main_helper
import classes.prepare_download as prepare_download
from types import SimpleNamespace

from helpers.main_helper import import_archive, export_archive

multiprocessing = main_helper.multiprocessing
log_download = main_helper.setup_logger('downloads', 'downloads.log')

json_config = None
json_global_settings = None
max_threads = -1
json_settings = None
auto_choice = None
j_directory = ""
file_directory_format = None
file_name_format = None
overwrite_files = None
date_format = None
ignored_keywords = None
ignore_type = None
export_metadata = None
delete_legacy_metadata = None
sort_free_paid_posts = None
blacklist_name = None
webhook = None
maximum_length = None
app_token = None


def assign_vars(json_auth, config, site_settings, site_name):
    global json_config, json_global_settings, max_threads, json_settings, auto_choice, j_directory, overwrite_files, date_format, file_directory_format, file_name_format, ignored_keywords, ignore_type, export_metadata, delete_legacy_metadata, sort_free_paid_posts, blacklist_name, webhook, maximum_length, app_token

    json_config = config
    json_global_settings = json_config["settings"]
    max_threads = json_global_settings["max_threads"]
    json_settings = site_settings
    auto_choice = json_settings["auto_choice"]
    j_directory = main_helper.get_directory(
        json_settings['download_paths'], site_name)
    file_directory_format = json_settings["file_directory_format"]
    file_name_format = json_settings["file_name_format"]
    overwrite_files = json_settings["overwrite_files"]
    date_format = json_settings["date_format"]
    ignored_keywords = json_settings["ignored_keywords"]
    ignore_type = json_settings["ignore_type"]
    export_metadata = json_settings["export_metadata"]
    delete_legacy_metadata = json_settings["delete_legacy_metadata"]
    sort_free_paid_posts = json_settings["sort_free_paid_posts"]
    blacklist_name = json_settings["blacklist_name"]
    webhook = json_settings["webhook"]
    maximum_length = 255
    maximum_length = int(json_settings["text_length"]
                         ) if json_settings["text_length"] else maximum_length
    app_token = json_auth['app_token']


def account_setup(api):
    status = False
    auth = api.login()
    if auth:
        # chats = api.get_chats()
        subscriptions = api.get_subscriptions()
        status = True
    return status

# The start lol


def start_datascraper(api, identifier, site_name, choice_type=None):
    print("Scrape Processing")
    subscription = api.get_subscription(identifier)
    if not subscription:
        return [False, subscription]
    post_count = subscription.postsCount
    user_id = str(subscription.id)
    avatar = subscription.avatar
    username = subscription.username
    link = subscription.link
    formatted_directories = main_helper.format_directories(
        j_directory, site_name, username)
    metadata_directory = formatted_directories["metadata_directory"]
    archive_path = os.path.join(metadata_directory, "Mass Messages.json")
    if subscription.is_me:
        imported = import_archive(archive_path)
        mass_messages = api.get_mass_messages(resume=imported)
        export_archive(mass_messages, archive_path,
                       json_settings, rename=False)
    info = {}
    info["download"] = prepare_download.start(
        username=username, link=link, image_url=avatar, post_count=post_count, webhook=webhook)
    print("Name: "+username)
    api_array = scrape_choice(api, subscription)
    api_array = format_options(api_array, "apis")
    apis = api_array[0]
    api_string = api_array[1]
    if not json_settings["auto_scrape_apis"]:
        print("Apis: "+api_string)
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
        metadata_locations[api_type] = results
    if any(x for x in subscription.scraped):
        subscription.download_info["directory"] = j_directory
        subscription.download_info["model_directory"] = os.path.join(
            j_directory, username)
        subscription.download_info["webhook"] = webhook
        subscription.download_info["metadata_locations"] = metadata_locations
    print("Scrape Completed"+"\n")
    return [True, info]


# Checks if the model is valid and grabs content count
def link_check(api, identifier):
    y = api.get_user(identifier)
    return y


# Allows the user to choose which api they want to scrape
def scrape_choice(api, subscription):
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
    mandatory = [j_directory, only_links]
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
def profile_scraper(api, directory, username):
    y = api.get_subscription(username)
    q = []
    avatar = y.avatar
    header = y.header
    if avatar:
        q.append(["Avatars", avatar])
    if header:
        q.append(["Headers", header])
    for x in q:
        new_dict = dict()
        media_type = x[0]
        media_link = x[1]
        new_dict["links"] = [media_link]
        directory2 = os.path.join(directory, username, "Profile", media_type)
        os.makedirs(directory2, exist_ok=True)
        download_path = os.path.join(
            directory2, media_link.split("/")[-2]+".jpg")
        if not overwrite_files:
            if os.path.isfile(download_path):
                continue
        session = api.sessions[0]
        r = api.json_request(media_link, session, stream=True,
                             json_format=False, sleep=False)
        if not isinstance(r, requests.Response):
            continue
        while True:
            downloader = main_helper.downloader(r, download_path)
            if not downloader:
                continue
            break


def paid_content_scraper(api):
    paid_contents = api.get_paid_content(refresh=False)
    results = []
    for paid_content in paid_contents:
        metadata_locations = {}
        author = paid_content.get("author")
        author = paid_content.get("fromUser", author)
        subscription = create_subscription(author)
        subscription.sessions = api.sessions
        subscription.download_info["directory"] = j_directory
        username = subscription.username
        model_directory = os.path.join(j_directory, username)
        metadata_folder = os.path.join(model_directory, "Metadata")
        api_type = paid_content["responseType"].capitalize()+"s"
        subscription.download_info["metadata_locations"] = j_directory
        metadata_path = os.path.join(
            metadata_folder, api_type+".json")
        metadata_locations[api_type] = metadata_path
        subscription.download_info["metadata_locations"] = metadata_locations
        site_name = "OnlyFans"
        media_type = format_media_types()
        formatted_directories = main_helper.format_directories(
            j_directory, site_name, username, media_type, api_type)
        metadata_set = media_scraper([paid_content], api,
                                     formatted_directories, username, api_type)
        for directory in metadata_set["directories"]:
            os.makedirs(directory, exist_ok=True)
        old_metadata = import_archive(metadata_path)
        old_metadata = metadata_fixer(directory=metadata_path.replace(
            ".json", ""), metadata_types=old_metadata)
        old_metadata_set = prepare_metadata(old_metadata).metadata
        old_metadata_set2 = jsonpickle.encode(
            old_metadata_set, unpicklable=False)
        old_metadata_set2 = jsonpickle.decode(old_metadata_set2)
        metadata_set = compare_metadata(metadata_set, old_metadata_set2)
        metadata_set = prepare_metadata(metadata_set).metadata
        metadata_set2 = jsonpickle.encode(metadata_set, unpicklable=False)
        metadata_set2 = jsonpickle.decode(metadata_set2)
        metadata_set2 = main_helper.filter_metadata(metadata_set2)
        subscription.set_scraped(api_type, metadata_set)
        os.makedirs(model_directory, exist_ok=True)
        if export_metadata:
            export_archive(metadata_set2, metadata_path, json_settings)
        download_media(api, subscription)
    return results


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


def process_mass_message(api, subscription, metadata_directory, mass_messages):
    def compare_message(queue_id, remote_messages):
        for message in remote_messages:
            if "isFromQueue" in message and message["isFromQueue"]:
                if queue_id == message["queueId"]:
                    return message
                print
        print
    global_found = []
    chats = []
    session = api.sessions[0]
    salt = json_global_settings["random_string"]
    encoded = f"{session.ip}{salt}"
    encoded = encoded.encode('utf-8')
    hash = hashlib.md5(encoded).hexdigest()
    mass_message_path = os.path.join(metadata_directory, "Mass Messages.json")
    chats_path = os.path.join(metadata_directory, "Chats.json")
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
        if mass_message["found"] or not mass_message["mediaType"]:
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
    main_helper.export_archive(
        chats, chats_path, json_settings, rename=False)
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
    main_helper.export_archive(
        mass_messages, mass_message_path, json_settings, rename=False)
    return global_found
# Prepares the API links to be scraped


def prepare_scraper(api, site_name, item):
    authed = api.auth
    sessions = api.sessions
    api_type = item["api_type"]
    api_array = item["api_array"]
    link = api_array["api_link"]
    subscription = api_array["subscription"]
    locations = api_array["media_types"]
    username = api_array["username"]
    directory = api_array["directory"]
    api_count = api_array["post_count"]
    master_set = []
    media_set = []
    metadata_set = []
    pool = multiprocessing()
    formatted_directories = main_helper.format_directories(
        j_directory, site_name, username, locations, api_type)
    model_directory = formatted_directories["model_directory"]
    api_directory = formatted_directories["api_directory"]
    metadata_directory = formatted_directories["metadata_directory"]
    archive_directory = os.path.join(metadata_directory, api_type)
    archive_path = archive_directory+".json"
    imported = import_archive(archive_path)
    legacy_metadata_directory = os.path.join(api_directory, "Metadata")
    if api_type == "Profile":
        profile_scraper(api, directory, username)
        return
    if api_type == "Stories":
        master_set = subscription.get_stories()
        highlights = subscription.get_highlights()
        valid_highlights = []
        for highlight in highlights:
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
        if "list" in unrefined_set:
            unrefined_set = unrefined_set["list"]
        if subscription.is_me:
            mass_messages = authed["mass_messages"]
            unrefined_set2 = process_mass_message(api,
                                                  subscription, metadata_directory, mass_messages)
            unrefined_set += unrefined_set2
            print
        master_set = [unrefined_set]
    master_set2 = master_set
    parent_type = ""
    if "Archived" == api_type:
        unrefined_set = []
        for master_set3 in master_set2:
            parent_type = master_set3["type"]
            results = master_set3["results"]
            unrefined_result = pool.starmap(media_scraper, product(
                results, [api], [formatted_directories], [username], [api_type], [parent_type]))
            unrefined_set.append(unrefined_result)
        unrefined_set = list(chain(*unrefined_set))
        for location in formatted_directories["locations"]:
            sorted_directories = copy.copy(location["sorted_directories"])
            for key, value in sorted_directories.items():
                x = value.split(os.sep)
                x.insert(1, parent_type)
                sorted_directories[key] = os.path.join(*x)
                if parent_type == "Posts":
                    old_archive = os.path.join(model_directory, value)
                    new_archive = os.path.join(
                        model_directory, sorted_directories[key])
                    if os.path.exists(old_archive):
                        file_list = os.listdir(old_archive)
                        if file_list:
                            os.makedirs(new_archive, exist_ok=True)
                            for file_name in file_list:
                                old_filepath = os.path.join(
                                    old_archive, file_name)
                                new_filepath = os.path.join(
                                    new_archive, file_name)
                                shutil.move(old_filepath, new_filepath)
    else:
        unrefined_set = pool.starmap(media_scraper, product(
            master_set2, [api], [formatted_directories], [username], [api_type], [parent_type]))
        unrefined_set = [x for x in unrefined_set]
    metadata_set = main_helper.format_media_set(unrefined_set)
    if not metadata_set:
        print("No "+api_type+" Found.")
        delattr(subscription.scraped, api_type)
    if metadata_set:
        if export_metadata:
            os.makedirs(metadata_directory, exist_ok=True)
            old_metadata = metadata_fixer(archive_directory)
            old_metadata_set = prepare_metadata(old_metadata).metadata
            old_metadata_set2 = jsonpickle.encode(
                old_metadata_set, unpicklable=False)
            old_metadata_set2 = jsonpickle.decode(old_metadata_set2)
            metadata_set = compare_metadata(metadata_set, old_metadata_set2)
            metadata_set = prepare_metadata(metadata_set).metadata
            metadata_set2 = jsonpickle.encode(metadata_set, unpicklable=False)
            metadata_set2 = jsonpickle.decode(metadata_set2)
            metadata_set2 = main_helper.filter_metadata(metadata_set2)
            metadata_set2 = legacy_metadata_fixer(
                legacy_metadata_directory, metadata_set2)
            main_helper.export_archive(
                metadata_set2, archive_path, json_settings, legacy_directory=legacy_metadata_directory)
        else:
            metadata_set = prepare_metadata(metadata_set).metadata
        subscription = api.get_subscription(username)
        subscription.set_scraped(api_type, metadata_set)
    return archive_path


def legacy_metadata_fixer(legacy_directory, new_metadata):
    if os.path.exists(legacy_directory):
        folders = os.listdir(legacy_directory)
        new_format = []
        for folder in (x for x in folders if "desktop.ini" not in folders):
            legacy_metadata_path = os.path.join(legacy_directory, folder)
            metadata_type = import_archive(legacy_metadata_path)
            valid = metadata_type["valid"]
            valid.sort(key=lambda x: x["post_id"], reverse=False)
            metadata_type["valid"] = [list(g) for k, g in groupby(
                valid, key=lambda x: x["post_id"])]
            new_format.append(metadata_type)
        old_metadata = metadata_fixer(metadata_types=new_format, export=False)
        old_metadata = prepare_metadata(old_metadata).metadata
        old_metadata = jsonpickle.encode(old_metadata, unpicklable=False)
        old_metadata = jsonpickle.decode(old_metadata)
        new_metadata = compare_metadata(
            new_metadata, old_metadata, new_chain=True)
        new_metadata = prepare_metadata(new_metadata).metadata
        new_metadata = jsonpickle.encode(new_metadata, unpicklable=False)
        new_metadata = jsonpickle.decode(new_metadata)
    return new_metadata


def metadata_fixer(directory="", metadata_types=[], export=True):
    metadata_path = directory+".json"
    if not metadata_types:
        metadata_types = import_archive(metadata_path)
    new_format = {}
    if isinstance(metadata_types, list):
        force = True
        for metadata_type in metadata_types:
            new_format[metadata_type["type"]] = metadata_type
            metadata_type.pop("type")
    else:
        force = False
        new_format = metadata_types
    new_format_copied = copy.deepcopy(new_format)
    for key, value in new_format.items():
        for key2, posts in value.items():
            if key2 != "valid":
                continue
            for post in posts:
                for media in post:
                    media["media_id"] = media.get("media_id", None)
                    if "link" in media:
                        media["links"] = [media["link"]]
                        media.pop("link")
                        print
                    directory = media["directory"]
                    if directory:
                        media["directory"] = os.path.realpath(
                            media["directory"])
                print
            print
        print
    print
    hashed = DeepHash(new_format)[new_format]
    hashed2 = DeepHash(new_format_copied)[new_format_copied]
    if (force or hashed != hashed2) and export:
        with open(metadata_path, 'w') as outfile:
            json.dump(new_format, outfile)
    return new_format


def compare_metadata(new_metadata, old_metadata, new_chain=False):
    new_metadata = old_metadata | new_metadata
    for key, value in old_metadata.items():
        old_valid = value["valid"]
        old_valid = list(chain.from_iterable(old_valid))
        new_type = new_metadata.get(key)
        new_valid = new_type["valid"]
        if all(isinstance(item, list) for item in new_valid):
            new_valid = list(chain.from_iterable(new_valid))
        for old_item in old_valid:
            if key == "Texts":
                if any(d["post_id"] == old_item["post_id"] for d in new_valid):
                    pass
                else:
                    new_valid.append(old_item)
            else:
                if old_item["media_id"] == None:
                    found = []
                    for link in old_item["links"]:
                        link = link.split("?")[0]
                        for new_item in new_valid:
                            if any(link in new_link for new_link in new_item["links"]):
                                found.append(old_item)
                                break
                    if not found:
                        new_valid.append(old_item)
                else:
                    for x in new_valid:
                        if old_item["media_id"] == x["media_id"]:
                            x["downloaded"] = old_item["downloaded"]
                            x["size"] = old_item["size"]
                    if not any(d["media_id"] == old_item["media_id"] for d in new_valid):
                        new_valid.append(old_item)
        new_valid.sort(key=lambda x: x["post_id"], reverse=True)
        new_metadata[key]["valid"] = new_valid
    return new_metadata

# Scrapes the API for content


def media_scraper(results, api, formatted_directories, username, api_type, parent_type=""):
    media_set = {}
    directories = []
    session = api.sessions[0]
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
        return media_set
    if "result" in results:
        session = results["session"]
        results = results["result"]
    model_directory = formatted_directories["model_directory"]
    for location in formatted_directories["locations"]:
        sorted_directories = copy.copy(location["sorted_directories"])
        master_date = "01-01-0001 00:00:00"
        media_type = location["media_type"]
        alt_media_type = location["alt_media_type"]
        if api_type == "Archived":
            for key, value in sorted_directories.items():
                x = value.split(os.sep)
                x.insert(1, parent_type)
                sorted_directories[key] = os.path.join(*x)
        seperator = " | "
        print(
            f"Scraping [{seperator.join(alt_media_type)}]. Should take less than a minute.")
        media_set2 = {}
        media_set2["valid"] = []
        media_set2["invalid"] = []
        for media_api in results:
            if api_type == "Messages":
                media_api["rawText"] = media_api["text"]
            if api_type == "Mass Messages":
                media_user = media_api["fromUser"]
                media_username = media_user["username"]
                if media_username != username:
                    continue
            if not media_api["media"] and "rawText" in media_api:
                if media_type == "Texts":
                    new_dict = dict()
                    new_dict["post_id"] = media_api["id"]
                    new_dict["text"] = media_api["rawText"]
                    media_set2["valid"].append(new_dict)
                    print
                print
            for media in media_api["media"]:
                date = "-001-11-30T00:00:00+00:00"
                size = 0
                link = ""
                if "source" in media:
                    source = media["source"]
                    link = source["source"]
                    size = media["info"]["preview"]["size"] if "info" in media_api else 1
                    date = media_api["postedAt"] if "postedAt" in media_api else media_api["createdAt"]
                if "src" in media:
                    link = media["src"]
                    size = media["info"]["preview"]["size"] if "info" in media_api else 1
                    date = media_api["createdAt"]
                if not link:
                    continue
                matches = ["us", "uk", "ca", "ca2", "de"]

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
                new_dict = dict()
                new_dict["post_id"] = media_api["id"]
                new_dict["media_id"] = media["id"]
                new_dict["links"] = []
                for xlink in link, preview_link:
                    if xlink:
                        new_dict["links"].append(xlink)
                        break
                new_dict["price"] = media_api["price"]if "price" in media_api else None
                if date == "-001-11-30T00:00:00+00:00":
                    date_string = master_date
                    date_object = datetime.strptime(
                        master_date, "%d-%m-%Y %H:%M:%S")
                else:
                    date_object = datetime.fromisoformat(date)
                    date_string = date_object.replace(tzinfo=None).strftime(
                        "%d-%m-%Y %H:%M:%S")
                    master_date = date_string

                if media["type"] not in alt_media_type:
                    continue
                if "rawText" not in media_api:
                    media_api["rawText"] = ""
                text = media_api["rawText"] if media_api["rawText"] else ""
                matches = [s for s in ignored_keywords if s in text]
                if matches:
                    print("Matches: ", matches)
                    continue
                new_dict["postedAt"] = date_string
                post_id = new_dict["post_id"]
                media_id = new_dict["media_id"]
                file_name = link.rsplit('/', 1)[-1]
                file_name, ext = os.path.splitext(file_name)
                ext = ext.__str__().replace(".", "").split('?')[0]
                media_directory = os.path.join(
                    model_directory, sorted_directories["unsorted"])
                new_dict["paid"] = False
                if new_dict["price"]:
                    if api_type in ["Messages", "Mass Messages"]:
                        new_dict["paid"] = True
                    else:
                        if media["id"] not in media_api["preview"] and media["canView"]:
                            new_dict["paid"] = True
                if sort_free_paid_posts:
                    media_directory = os.path.join(
                        model_directory, sorted_directories["free"])
                    if new_dict["paid"]:
                        media_directory = os.path.join(
                            model_directory, sorted_directories["paid"])
                file_path = main_helper.reformat(media_directory, post_id, media_id, file_name,
                                                 text, ext, date_object, username, file_directory_format, file_name_format, date_format, maximum_length)
                new_dict["text"] = text
                file_directory = os.path.dirname(file_path)
                new_dict["directory"] = os.path.join(file_directory)
                new_dict["filename"] = os.path.basename(file_path)
                new_dict["session"] = session
                if size == 0:
                    media_set2["invalid"].append(new_dict)
                    continue
                if file_directory not in directories:
                    directories.append(file_directory)
                media_set2["valid"].append(new_dict)
        if media_set2["valid"] or media_set2["invalid"]:
            media_set[media_type] = media_set2
        else:
            print
    media_set["directories"] = directories
    return media_set


# Downloads scraped content
class download_media():
    def __init__(self, api=None, subscription=None) -> None:
        if api:
            username = subscription.username
            download_info = subscription.download_info
            metadata_locations = download_info["metadata_locations"]
            directory = download_info["directory"]
            for api_type, value in subscription.scraped:
                if not value or api_type == "Texts":
                    continue
                if not isinstance(value, dict):
                    continue
                for location, v in value.items():
                    if location == "Texts":
                        continue
                    media_set = v.valid
                    string = "Download Processing\n"
                    string += f"Name: {username} | Type: {api_type} | Count: {len(media_set)} {location} | Directory: {directory}\n"
                    print(string)
                    pool = multiprocessing()
                    pool.starmap(self.download, product(
                        media_set, [api]))
                metadata_path = metadata_locations.get(api_type)
                if metadata_path:
                    value = jsonpickle.encode(
                        value, unpicklable=False)
                    value = jsonpickle.decode(value)
                    new_metadata = prepare_metadata(
                        value, export=True).metadata
                    value = jsonpickle.encode(
                        new_metadata, unpicklable=False)
                    value = jsonpickle.decode(value)
                    if export_metadata:
                        export_archive(value, metadata_path,
                                       json_settings, rename=False)
                else:
                    print

    def download(self, medias, api):
        return_bool = True
        for media in medias:
            if not overwrite_files and media.downloaded:
                continue
            count = 0
            session = media.session
            if not session:
                continue
            while count < 11:
                links = media.links

                def choose_link(session, links):
                    for link in links:
                        r = api.json_request(link, session, "HEAD",
                                             stream=True, json_format=False)
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
                    count += 1
                    continue
                link = result[0]
                content_length = result[1]
                media.size = content_length
                date_object = datetime.strptime(
                    media.postedAt, "%d-%m-%Y %H:%M:%S")
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
                downloader = main_helper.downloader(r, download_path, count)
                if not downloader:
                    count += 1
                    continue
                main_helper.format_image(download_path, timestamp)
                log_download.info("Link: {}".format(link))
                log_download.info("Path: {}".format(download_path))
                media.downloaded = True
                break
        return return_bool


def manage_subscriptions(api, auth_count=0):
    results = api.get_subscriptions(refresh=False)
    if blacklist_name:
        r = api.get_lists()
        if not r:
            return [False, []]
        new_results = [c for c in r if blacklist_name == c["name"]]
        if new_results:
            item = new_results[0]
            list_users = item["users"]
            if item["usersCount"] > 2:
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
    for result in results:
        result.auth_count = auth_count
        result.self = False
        username = result.username
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
    api.auth["subscriptions"] = results2
    return results2


def format_options(f_list, choice_type):
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
    if name_count > 1:
        if "usernames" == choice_type:
            for x in f_list:
                name = x.username
                string += str(count)+" = "+name
                names.append([x.auth_count, name])
                if count+1 != name_count:
                    string += " | "
                count += 1
        if "apis" == choice_type:
            names = f_list
            for api in f_list:
                if hasattr(api, "username"):
                    name = api.username
                else:
                    name = api["api_type"]
                string += str(count)+" = "+name
                if count+1 != name_count:
                    string += " | "
                count += 1
    return [names, string]
