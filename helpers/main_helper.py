import math
from types import SimpleNamespace
from typing import Any, Tuple, Union

from deepdiff.deephash import DeepHash
from sqlalchemy.ext.declarative import api
from sqlalchemy.ext.declarative.api import declarative_base
from classes.prepare_metadata import format_variables
import copy
import json
import os
import platform
import re
from datetime import datetime
import time
from itertools import chain, zip_longest, groupby
import psutil
import shutil
from multiprocessing.dummy import Pool as ThreadPool
import ujson
from tqdm import tqdm
import string
import random

import requests
from bs4 import BeautifulSoup

import classes.make_settings as make_settings
import classes.prepare_webhooks as prepare_webhooks
from mergedeep import merge, Strategy
import helpers.db_helper as db_helper
from alembic.config import Config
from alembic import command
import traceback
json_global_settings = None
min_drive_space = 0
webhooks = None
max_threads = -1
os_name = platform.system()
proxies = None
cert = None


def assign_vars(config):
    global json_global_settings, min_drive_space, webhooks, max_threads, proxies, cert

    json_config = config
    json_global_settings = json_config["settings"]
    min_drive_space = json_global_settings["min_drive_space"]
    webhooks = json_global_settings["webhooks"]
    max_threads = json_global_settings["max_threads"]
    proxies = json_global_settings["proxies"]
    cert = json_global_settings["cert"]


def rename_duplicates(seen, filename):
    filename_lower = filename.lower()
    if filename_lower not in seen:
        seen.add(filename_lower)
    else:
        count = 1
        while filename_lower in seen:
            filename = filename+" ("+str(count)+")"
            filename_lower = filename.lower()
            count += 1
        seen.add(filename_lower)
    return [seen, filename]


def parse_links(site_name, input_link):
    if site_name in {"onlyfans", "starsavn"}:
        username = input_link.rsplit('/', 1)[-1]
        return username

    if site_name in {"patreon", "fourchan", "bbwchan"}:
        if "catalog" in input_link:
            input_link = input_link.split("/")[1]
            print(input_link)
            return input_link
        if input_link[-1:] == "/":
            input_link = input_link.split("/")[3]
            return input_link
        if "4chan.org" not in input_link:
            return input_link


def clean_text(string, remove_spaces=False):
    matches = ["\n", "<br>"]
    for m in matches:
        string = string.replace(
            m, " ").strip()
    string = ' '.join(string.split())
    string = BeautifulSoup(string, "lxml").get_text()
    SAFE_PTN = r"[|\^&+\-%*/=!:\"?><]"
    string = re.sub(SAFE_PTN, ' ',  string.strip()
                    ).strip()
    if remove_spaces:
        string = string.replace(' ', '_')
    return string


def format_media_set(media_set):
    merged = merge({}, *media_set, strategy=Strategy.ADDITIVE)
    if "directories" in merged:
        for directory in merged["directories"]:
            os.makedirs(directory, exist_ok=True)
        merged.pop("directories")
    return merged


def format_image(filepath, timestamp):
    while True:
        try:
            if os_name == "Windows":
                from win32_setctime import setctime
                setctime(filepath, timestamp)
                # print(f"Updated Creation Time {filepath}")
            os.utime(filepath, (timestamp, timestamp))
            # print(f"Updated Modification Time {filepath}")
        except Exception as e:
            continue
        break


def filter_metadata(datas):
    for key, item in datas.items():
        for items in item["valid"]:
            for item2 in items:
                item2.pop("session")
    return datas


def import_archive(archive_path) -> Any:
    metadata = {}
    if os.path.exists(archive_path) and os.path.getsize(archive_path):
        with open(archive_path, 'r', encoding='utf-8') as outfile:
            while not metadata:
                try:
                    metadata = ujson.load(outfile)
                except OSError as e:
                    print(traceback.format_exc())
    return metadata


def legacy_database_fixer(database_path, database, database_name, database_exists):
    database_directory = os.path.dirname(database_path)
    old_database_path = database_path
    old_filename = os.path.basename(old_database_path)
    new_filename = f"Pre_Alembic_{old_filename}"
    pre_alembic_path = os.path.join(database_directory, new_filename)
    pre_alembic_database_exists = False
    if os.path.exists(pre_alembic_path):
        database_path = pre_alembic_path
        pre_alembic_database_exists = True
    datas = []
    if database_exists:
        Session, engine = db_helper.create_database_session(database_path)
        database_session = Session()
        result = engine.dialect.has_table(engine, 'alembic_version')
        if not result:
            if not pre_alembic_database_exists:
                os.rename(old_database_path, pre_alembic_path)
                pre_alembic_database_exists = True
    if pre_alembic_database_exists:
        Session, engine = db_helper.create_database_session(pre_alembic_path)
        database_session = Session()
        api_table = database.api_table()
        media_table = database.media_table()
        Base = declarative_base()
        # DON'T FORGET TO REMOVE
        # database_name = "posts"
        # DON'T FORGET TO REMOVE
        legacy_api_table = api_table.legacy(Base, database_name)
        legacy_media_table = media_table.legacy(Base)
        result = database_session.query(legacy_api_table)
        post_db = result.all()
        for post in post_db:
            post_id = post.id
            created_at = post.created_at
            new_item = {}
            new_item["post_id"] = post_id
            new_item["text"] = post.text
            new_item["price"] = post.price
            new_item["paid"] = post.paid
            new_item["postedAt"] = created_at
            new_item["medias"] = []
            result2 = database_session.query(legacy_media_table)
            media_db = result2.filter_by(post_id=post_id).all()
            for media in media_db:
                new_item2 = {}
                new_item2["media_id"] = media.id
                new_item2["post_id"] = media.post_id
                new_item2["links"] = [media.link]
                new_item2["directory"] = media.directory
                new_item2["filename"] = media.filename
                new_item2["size"] = media.size
                new_item2["media_type"] = media.media_type
                new_item2["downloaded"] = media.downloaded
                new_item2["created_at"] = created_at
                new_item["medias"].append(new_item2)
            datas.append(new_item)
        print
        database_session.close()
        x = export_sqlite(old_database_path, datas,
                          database_name, legacy_fixer=True)
    print


def export_sqlite(archive_path, datas, parent_type, legacy_fixer=False, api=None):
    metadata_directory = os.path.dirname(archive_path)
    os.makedirs(metadata_directory, exist_ok=True)
    cwd = os.getcwd()
    api_type: str = os.path.basename(archive_path).removesuffix(".db")
    database_path = archive_path
    database_name = parent_type if parent_type else api_type
    database_name = database_name.lower()
    db_collection = db_helper.database_collection()
    database = db_collection.chooser(database_name)
    alembic_location = os.path.join(
        cwd, "database", "databases", database_name)
    database_exists = os.path.exists(database_path)
    if database_exists:
        if os.path.getsize(database_path) == 0:
            os.remove(database_path)
            database_exists = False
    if not legacy_fixer:
        x = legacy_database_fixer(
            database_path, database, database_name, database_exists)
    db_helper.run_migrations(alembic_location, database_path, api)
    print
    Session, engine = db_helper.create_database_session(database_path)
    database_session = Session()
    api_table = database.api_table
    media_table = database.media_table
    # api_table = db_helper.api_table()
    # media_table = db_helper.media_table()

    for post in datas:
        post_id = post["post_id"]
        postedAt = post["postedAt"]
        date_object = None
        if postedAt:
            if not isinstance(postedAt, datetime):
                date_object = datetime.strptime(
                    postedAt, "%d-%m-%Y %H:%M:%S")
            else:
                date_object = postedAt
        result = database_session.query(api_table)
        post_db = result.filter_by(post_id=post_id).first()
        if not post_db:
            post_db = api_table()
        post_db.post_id = post_id
        post_db.text = post["text"]
        if post["price"] == None:
            post["price"] = 0
        post_db.price = post["price"]
        post_db.paid = post["paid"]
        if date_object:
            post_db.created_at = date_object
        database_session.add(post_db)
        for media in post["medias"]:
            if media["media_type"] == "Texts":
                continue
            media_id = media.get("media_id", None)
            result = database_session.query(media_table)
            media_db = result.filter_by(media_id=media_id).first()
            if not media_db:
                media_db = result.filter_by(
                    filename=media["filename"], created_at=date_object).first()
                if not media_db:
                    media_db = media_table()
            if legacy_fixer:
                media_db.size = media["size"]
                media_db.downloaded = media["downloaded"]
            media_db.media_id = media_id
            media_db.post_id = post_id
            media_db.link = media["links"][0]
            media_db.preview = media.get("preview", False)
            media_db.directory = media["directory"]
            media_db.filename = media["filename"]
            media_db.media_type = media["media_type"]
            media_db.linked = media.get("linked", None)
            if date_object:
                media_db.created_at = date_object
            database_session.add(media_db)
            print
        print
    print

    database_session.commit()
    database_session.close()
    return Session, api_type, database


def format_paths(j_directories, site_name):
    paths = []
    for j_directory in j_directories:
        paths.append(j_directory)
    return paths


def reformat(prepared_format, unformatted):
    post_id = prepared_format.post_id
    media_id = prepared_format.media_id
    date = prepared_format.date
    text = prepared_format.text
    value = "Free"
    maximum_length = prepared_format.maximum_length
    text_length = prepared_format.text_length
    post_id = "" if post_id is None else str(post_id)
    media_id = "" if media_id is None else str(media_id)
    extra_count = 0
    if type(date) is str:
        format_variables2 = format_variables()
        if date != format_variables2.date and date != "":
            date = datetime.strptime(
                date, "%d-%m-%Y %H:%M:%S")
            date = date.strftime(prepared_format.date_format)
    else:
        if date != None:
            date = date.strftime(prepared_format.date_format)
    has_text = False
    if "{text}" in unformatted:
        has_text = True
        text = clean_text(text)
        extra_count = len("{text}")
    if "{value}" in unformatted:
        if prepared_format.price:
            if not prepared_format.preview:
                value = "Paid"
    directory = prepared_format.directory
    path = unformatted.replace("{site_name}", prepared_format.site_name)
    path = path.replace(
        "{first_letter}", prepared_format.username[0].capitalize())
    path = path.replace("{post_id}", post_id)
    path = path.replace("{media_id}", media_id)
    path = path.replace("{username}", prepared_format.username)
    path = path.replace("{api_type}", prepared_format.api_type)
    path = path.replace("{media_type}", prepared_format.media_type)
    path = path.replace("{filename}", prepared_format.filename)
    path = path.replace("{ext}", prepared_format.ext)
    path = path.replace("{value}", value)
    path = path.replace("{date}", date)
    directory_count = len(directory)
    path_count = len(path)
    maximum_length = maximum_length - (directory_count+path_count-extra_count)
    text_length = text_length if text_length < maximum_length else maximum_length
    if has_text:
        filtered_text = text[:text_length]
        path = path.replace("{text}", filtered_text)
    else:
        path = path.replace("{text}", "")
    directory2 = os.path.join(directory, path)
    directory3 = os.path.abspath(directory2)
    return directory3


def get_directory(directories: list[str], extra_path):
    directories = format_paths(directories, extra_path)
    new_directories = []
    if not directories:
        directories = [""]
    for directory in directories:
        if not os.path.isabs(directory):
            if directory:
                fp: str = os.path.abspath(directory)
            else:
                fp: str = os.path.abspath(extra_path)
            directory = os.path.abspath(fp)
        os.makedirs(directory, exist_ok=True)
        new_directories.append(directory)
    directory = check_space(new_directories, min_size=min_drive_space)
    return directory


def check_space(download_paths, min_size=min_drive_space, priority="download", create_directory=True):
    root = ""
    while not root:
        paths = []
        for download_path in download_paths:
            if create_directory:
                os.makedirs(download_path, exist_ok=True)
            obj_Disk = psutil.disk_usage(download_path)
            free = obj_Disk.free / (1024.0 ** 3)
            x = {}
            x["path"] = download_path
            x["free"] = free
            paths.append(x)
        if priority == "download":
            for item in paths:
                download_path = item["path"]
                free = item["free"]
                if free > min_size:
                    root = download_path
                    break
        elif priority == "upload":
            paths.sort(key=lambda x: x["free"])
            item = paths[0]
            root = item["path"]
    return root


def find_model_directory(username, directories) -> Tuple[str, bool]:
    download_path = ""
    status = False
    for directory in directories:
        download_path = os.path.join(directory, username)
        if os.path.exists(download_path):
            status = True
            break
    return download_path, status


def are_long_paths_enabled():
    if os_name == "Windows":
        from ctypes import WinDLL, c_ubyte
        ntdll = WinDLL('ntdll')

        if hasattr(ntdll, 'RtlAreLongPathsEnabled'):

            ntdll.RtlAreLongPathsEnabled.restype = c_ubyte
            ntdll.RtlAreLongPathsEnabled.argtypes = ()
            return bool(ntdll.RtlAreLongPathsEnabled())

        else:
            return False


def check_for_dupe_file(download_path, content_length):
    found = False
    if os.path.isfile(download_path):
        content_length = int(content_length)
        local_size = os.path.getsize(download_path)
        if local_size == content_length:
            found = True
    return found


class download_session(tqdm):
    def start(self, unit='B', unit_scale=True,
              miniters=1, tsize=0):
        self.unit = unit
        self.unit_scale = unit_scale
        self.miniters = miniters
        self.total = 0
        self.colour = "Green"
        if tsize:
            tsize = int(tsize)
            self.total += tsize

    def update_total_size(self, tsize):
        tsize = int(tsize)
        self.total += tsize

    def update_to(self, b=1, bsize=1, tsize=None):
        x = bsize
        print
        self.update(b)


def downloader(r, download_path, d_session, count=0):
    delete = False
    try:
        with open(download_path, 'wb') as f:
            delete = True
            for chunk in r.iter_content(chunk_size=4096):
                if chunk:  # filter out keep-alive new chunks
                    size = f.write(chunk)
                    d_session.update(size)
    except (ConnectionResetError) as e:
        if delete:
            os.unlink(download_path)
        return
    except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
        return
    except Exception as e:
        if delete:
            deleted = None
            while not deleted:
                try:
                    os.unlink(download_path)
                    deleted = True
                except PermissionError as e2:
                    print(e2)
        string = f"{e}\n Tries: {count}"
        return
    return True


def get_config(config_path):
    if os.path.exists(config_path):
        json_config = json.load(open(config_path))
    else:
        json_config = {}
    json_config2 = copy.deepcopy(json_config)
    json_config, string = make_settings.fix(json_config)
    file_name = os.path.basename(config_path)
    json_config = json.loads(json.dumps(make_settings.config(
        **json_config), default=lambda o: o.__dict__))
    hashed = DeepHash(json_config)[json_config]
    hashed2 = DeepHash(json_config2)[json_config2]
    updated = False
    if hashed != hashed2:
        updated = True
        update_config(json_config, file_name=file_name)
    if not json_config:
        input(
            f"The .settings\\{file_name} file has been created. Fill in whatever you need to fill in and then press enter when done.\n")
        json_config = json.load(open(config_path))
    return json_config, updated


def update_config(json_config, file_name="config.json"):
    directory = '.settings'
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, file_name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(json_config, f, ensure_ascii=False, indent=2)


def choose_auth(array):
    names = []
    array = [{"auth_count": -1, "username": "All"}]+array
    string = ""
    seperator = " | "
    name_count = len(array)
    if name_count > 1:

        count = 0
        for x in array:
            name = x["username"]
            string += str(count)+" = "+name
            names.append(x)
            if count+1 != name_count:
                string += seperator

            count += 1

    print("Auth Usernames: "+string)
    value = int(input().strip())
    if value:
        names = [names[value]]
    else:
        names.pop(0)
    return names


def choose_option(subscription_list, auto_scrape: Union[str, bool]):
    names = subscription_list[0]
    new_names = []
    if names:
        seperator = " | "
        if isinstance(auto_scrape, bool):
            if auto_scrape:
                values = [x[1] for x in names]
            else:
                print(
                    f"Names: Username = username {seperator} {subscription_list[1]}")
                values = input().strip().split(",")
        else:
            if not auto_scrape:
                print(
                    f"Names: Username = username {seperator} {subscription_list[1]}")
                values = input().strip().split(",")
            else:
                values = auto_scrape.split(",")
        for value in values:
            if value.isdigit():
                if value == "0":
                    new_names = names[1:]
                    break
                else:
                    new_name = names[int(value)]
                    new_names.append(new_name)
            else:
                new_name = [name for name in names if value == name[1]]
                new_names.extend(new_name)
    new_names = [x for x in new_names if not isinstance(x[0], SimpleNamespace)]
    return new_names


def process_profiles(json_settings, session_manager, site_name, original_api):
    apis = []
    profile_directories = json_settings["profile_directories"]
    for profile_directory in profile_directories:
        x = os.path.join(profile_directory, site_name)
        x = os.path.abspath(x)
        os.makedirs(x, exist_ok=True)
        temp_users = os.listdir(x)
        temp_users = remove_mandatory_files(temp_users)
        if not temp_users:
            default_profile_directory = os.path.join(x, "default")
            os.makedirs(default_profile_directory)
            temp_users.append("default")
        for user in temp_users:
            user_profile = os.path.join(x, user)
            user_auth_filepath = os.path.join(
                user_profile, "auth.json")
            api = original_api.start(
                session_manager)
            if os.path.exists(user_auth_filepath):
                temp_json_auth = ujson.load(
                    open(user_auth_filepath))
                json_auth = temp_json_auth["auth"]
                if not json_auth.get("active", None):
                    continue
                json_auth["username"] = user
                api.auth.profile_directory = user_profile
                api.set_auth_details(
                    json_auth)
            datas = {}
            datas["auth"] = api.auth.auth_details.__dict__
            export_data(
                datas, user_auth_filepath, encoding=None)
            apis.append(api)
            print
        print
    return apis


def process_names(module, subscription_list, auto_scrape, session_array, json_config, site_name_lower, site_name) -> list:
    names = choose_option(
        subscription_list, auto_scrape)
    if not names:
        print("There's nothing to scrape.")
    for name in names:
        # Extra Auth Support
        auth_count = name[0]
        api = session_array[auth_count]
        name = name[-1]
        assign_vars(json_config)
        username = parse_links(site_name_lower, name)
        result = module.start_datascraper(
            api, username, site_name)
    return names


def process_downloads(apis, module):
    for api in apis:
        subscriptions = api.get_subscriptions(refresh=False)
        for subscription in subscriptions:
            download_info = subscription.download_info
            if download_info:
                module.download_media(api, subscription)
                delete_empty_directories(
                    download_info["base_directory"])


def process_webhooks(apis: list, category, category2):
    global_webhooks = webhooks["global_webhooks"]
    global_status = webhooks["global_status"]
    webhook = webhooks[category]
    webhook_state = webhook[category2]
    webhook_links = []
    webhook_status = global_status
    webhook_hide_sensitive_info = True
    if webhook_state["status"] != None:
        webhook_status = webhook_state["status"]
    if global_webhooks:
        webhook_links = global_webhooks
    if webhook_state["webhooks"]:
        webhook_links = webhook_state["webhooks"]
    if webhook_status:
        for api in apis:
            send_webhook(api, webhook_hide_sensitive_info,
                         webhook_links, category, category2)
        print
    print


def is_me(user_api):
    if "email" in user_api:
        return True
    else:
        return False


def export_data(metadata: Union[list, dict], path: str, encoding: Union[str, None] = "utf-8"):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding=encoding) as outfile:
        ujson.dump(metadata, outfile, indent=2)


def grouper(n, iterable, fillvalue=None):
    args = [iter(iterable)] * n
    return list(zip_longest(fillvalue=fillvalue, *args))


def create_link_group(max_threads):
    x = range
    print


def remove_mandatory_files(files, keep=[]):
    matches = ["desktop.ini", ".DS_Store", ".DS_store", "@eaDir"]
    folders = [x for x in files if x not in matches]
    if keep:
        folders = [x for x in files if x in keep]
    return folders


def legacy_metadata(directory):
    if os.path.exists(directory):
        items = os.listdir(directory)
        matches = ["desktop.ini"]
        metadatas = []
        items = [x for x in items if x not in matches]
        if items:
            for item in items:
                path = os.path.join(directory, item)
                metadata = json.load(open(path))
                metadatas.append(metadata)
                print
        print


def metadata_fixer(directory):
    archive_file = os.path.join(directory, "archive.json")
    metadata_file = os.path.join(directory, "Metadata")
    if os.path.exists(archive_file):
        os.makedirs(metadata_file, exist_ok=True)
        new = os.path.join(metadata_file, "Archive.json")
        shutil.move(archive_file, new)


def ordinal(n): return "%d%s" % (
    n, "tsnrhtdd"[(n/10 % 10 != 1)*(n % 10 < 4)*n % 10::4])


def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def humansize(nbytes):
    i = 0
    suffixes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    while nbytes >= 1024 and i < len(suffixes)-1:
        nbytes /= 1024.
        i += 1
    f = ('%.2f' % nbytes).rstrip('0').rstrip('.')
    return '%s %s' % (f, suffixes[i])


def byteToGigaByte(n):
    return (n / math.pow(10, 9))


def send_webhook(item, webhook_hide_sensitive_info, webhook_links, category, category2: str):
    if category == "auth_webhook":
        for webhook_link in webhook_links:
            auth = item.auth
            username = auth.username
            if webhook_hide_sensitive_info:
                username = "REDACTED"
            message = prepare_webhooks.discord()
            embed = message.embed()
            embed.title = f"Auth {category2.capitalize()}"
            embed.add_field("username", username)
            message.embeds.append(embed)
            message = json.loads(json.dumps(
                message, default=lambda o: o.__dict__))
            x = requests.post(webhook_link, json=message)
    if category == "download_webhook":
        subscriptions = item.get_subscriptions(refresh=False)
        for subscription in subscriptions:
            download_info = subscription.download_info
            if download_info:
                for webhook_link in webhook_links:
                    message = prepare_webhooks.discord()
                    embed = message.embed()
                    embed.title = f"Downloaded: {subscription.username}"
                    embed.add_field("username", subscription.username)
                    embed.add_field("post_count", subscription.postsCount)
                    embed.add_field("link", subscription.link)
                    embed.image.url = subscription.avatar
                    message.embeds.append(embed)
                    message = json.loads(json.dumps(
                        message, default=lambda o: o.__dict__))
                    x = requests.post(webhook_link, json=message)
                    print


def find_between(s, start, end):
    format = f'{start}(.+?){end}'
    x = re.search(format, s)
    if x:
        x = x.group(1)
    else:
        x = s
    return x


def delete_empty_directories(directory):
    def start(directory):
        for root, dirnames, files in os.walk(directory, topdown=False):
            for dirname in dirnames:
                full_path = os.path.realpath(os.path.join(root, dirname))
                contents = os.listdir(full_path)
                if not contents:
                    shutil.rmtree(full_path, ignore_errors=True)
                else:
                    content_count = len(contents)
                    if content_count == 1 and "desktop.ini" in contents:
                        shutil.rmtree(full_path, ignore_errors=True)
    x = start(directory)
    if os.path.exists(directory):
        if not os.listdir(directory):
            os.rmdir(directory)


def multiprocessing():
    if max_threads < 1:
        pool = ThreadPool()
    else:
        pool = ThreadPool(max_threads)
    return pool


def module_chooser(domain, json_sites):
    string = "Site: "
    seperator = " | "
    site_names = []
    wl = ["onlyfans"]
    bl = ["patreon"]
    site_count = len(json_sites)
    count = 0
    for x in json_sites:
        if not wl:
            if x in bl:
                continue
        elif x not in wl:
            continue
        string += str(count)+" = "+x
        site_names.append(x)
        if count+1 != site_count:
            string += seperator

        count += 1
    string += "x = Exit"
    if domain and domain not in site_names:
        string = f"{domain} not supported"
        site_names = []
    return string, site_names
