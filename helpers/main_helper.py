import copy
import csv
import hashlib
import json
import logging
import os
import platform
import re
from datetime import datetime
from itertools import chain, zip_longest, groupby
from os.path import dirname as up
from urllib.parse import urlparse
import time
import random
import socket
import psutil
import shutil

import requests
from bs4 import BeautifulSoup

import classes.make_settings as make_settings
import extras.OFRenamer.start as ofrenamer

path = up(up(os.path.realpath(__file__)))
os.chdir(path)

json_global_settings = None
min_drive_space = 0
os_name = platform.system()


def setup_logger(name, log_file, level=logging.INFO):
    """To setup as many loggers as you want"""
    log_filename = ".logs/"+log_file
    os.makedirs(os.path.dirname(log_filename), exist_ok=True)
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s')

    handler = logging.FileHandler(log_filename, 'w+', encoding='utf-8')
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger


log_error = setup_logger('errors', 'errors.log')


def assign_vars(config):
    global json_global_settings, min_drive_space

    json_config = config
    json_global_settings = json_config["settings"]
    min_drive_space = json_global_settings["min_drive_space"]


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
    string = BeautifulSoup(string, 'lxml').get_text()
    SAFE_PTN = "[^0-9a-zA-Z-_.'()]+"
    string = re.sub(SAFE_PTN, ' ',  string.strip()
                    ).strip()
    if remove_spaces:
        string = string.replace(' ', '_')
    return string


def format_media_set(media_set):
    media_set = list(chain(*media_set))
    media_set.sort(key=lambda x: x["type"])
    media_set = [list(g) for k, g in groupby(
        media_set, key=lambda x: x["type"])]
    new_list = []
    for item in media_set:
        item2 = {k: [d[k] for d in item] for k in item[0]}
        item2["type"] = item2["type"][0]
        item2["valid"] = list(chain(*item2["valid"]))
        item2["invalid"] = list(chain(*item2["invalid"]))
        if item2["valid"]:
            seen = set()
            item2["valid"] = [x for x in item2["valid"]
                              if x["filename"] not in seen and not seen.add(x["filename"])]
            seen = set()
            location_directories = [x["directory"] for x in item2["valid"]
                                    if x["directory"] not in seen and not seen.add(x["directory"])]
            for location_directory in location_directories:
                os.makedirs(location_directory, exist_ok=True)
            item2["valid"] = [list(g) for k, g in groupby(
                item2["valid"], key=lambda x: x["post_id"])]
        new_list.append(item2)
    print
    return new_list


def format_image(directory, timestamp):
    if os_name == "Windows":
        from win32_setctime import setctime
        setctime(directory, timestamp)
    os.utime(directory, (timestamp, timestamp))


def filter_metadata(datas):
    for data in datas:
        for items in data["valid"]:
            for item in items:
                item.pop("session")
    return datas


def export_archive(datas, archive_path, json_settings):
    # Not Finished
    export_type = json_global_settings["export_type"]
    if export_type == "json":
        archive_path = os.path.join(archive_path+".json")
        if os.path.exists(archive_path):
            datas2 = ofrenamer.start(archive_path, json_settings)
            if datas == datas2:
                return
        with open(archive_path, 'w') as outfile:
            json.dump(datas, outfile)
    if export_type == "csv":
        archive_path = os.path.join(archive_path+".csv")
        with open(archive_path, mode='w', encoding='utf-8', newline='') as csv_file:
            for data in datas:
                fieldnames = []
                media_type = data["type"].lower()
                valid = list(chain.from_iterable(data["valid"]))
                invalid = list(chain.from_iterable(data["invalid"]))
                if valid:
                    fieldnames.extend(valid[0].keys())
                elif invalid:
                    fieldnames.extend(invalid[0].keys())
                header = [media_type]+fieldnames
                if len(fieldnames) > 1:
                    writer = csv.DictWriter(csv_file, fieldnames=header)
                    writer.writeheader()
                    for item in valid:
                        writer.writerow({**{media_type: "valid"}, **item})
                    for item in invalid:
                        writer.writerow({**{media_type: "invalid"}, **item})


def format_paths(j_directories, site_name):
    paths = []
    for j_directory in j_directories:
        format_path = j_directory
        path = format_path.replace("{site_name}", site_name)
        paths.append(path)
    return paths


def reformat(directory, post_id, media_id, filename, text, ext, date, username, format_path, date_format, maximum_length):
    post_id = "" if post_id is None else str(post_id)
    media_id = "" if media_id is None else str(media_id)
    if type(date) is str:
        date = datetime.strptime(
            date, "%d-%m-%Y %H:%M:%S")
    has_text = False
    if "{text}" in format_path:
        has_text = True
    path = format_path.replace("{post_id}", post_id)
    path = path.replace("{media_id}", media_id)
    path = path.replace("{username}", username)
    filtered_text = text[:maximum_length]
    directory = directory.replace(text, filtered_text)
    path = path.replace("{text}", filtered_text)
    date = date.strftime(date_format)
    path = path.replace("{date}", date)
    path = path.replace("{file_name}", filename)
    path = path.replace("{ext}", ext)
    directory2 = os.path.join(directory, path)

    if has_text:
        count_string = len(path)
        text_count = len(filtered_text)
        if count_string > maximum_length:
            text_limit = count_string - text_count
            path = path.replace(
                filtered_text, filtered_text[:text_limit])
            directory2 = os.path.join(directory, path)
    return directory2


def get_directory(directories, site_name):
    directories = format_paths(directories, site_name)
    new_directories = []
    for directory in directories:
        if not os.path.isabs(directory):
            fp = os.path.abspath(".sites")
            x = os.path.join(fp, directory)
            directory = os.path.abspath(x)
        os.makedirs(directory, exist_ok=True)
        new_directories.append(directory)
    directory = check_space(new_directories, min_size=min_drive_space)
    return directory


def check_space(download_paths, min_size=min_drive_space, priority="download"):
    root = ""
    while not root:
        paths = []
        for download_path in download_paths:
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
            root = download_paths[0]
    return root


def format_directory(j_directory, site_name, username, location="", api_type=""):
    directory = j_directory
    user_directory = os.path.join(directory, username)
    metadata_directory = os.path.join(user_directory, "Metadata")
    directories = []
    cats = ["", "Free", "Paid"]
    for cat in cats:
        directories.append(
            [location, os.path.join(user_directory, api_type, cat, location)])
    return [user_directory, metadata_directory, directories]


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


def session_rules(session, link):
    if "https://onlyfans.com/api2/v2/" in link:
        sess = session.headers["access-token"]
        user_agent = session.headers["user-agent"]
        a = [session, link, sess, user_agent]
        session = create_sign(*a)
    return session


def session_retry_rules(r, link):
    # 0 Fine, 1 Continue, 2 Break
    boolean = 0
    if "https://onlyfans.com/api2/v2/" in link:
        text = r.text
        if "Invalid request sign" in text:
            boolean = 1
        elif "Access Denied" in text:
            boolean = 2
    return boolean


def json_request(session, link, method="GET", stream=False, json_format=True, data={}, sleep=True, timeout=20):
    session = session_rules(session, link)
    count = 0
    sleep_number = 0.5
    result = {}
    while count < 11:
        try:
            count += 1
            headers = session.headers
            if json_format:
                headers["accept"] = "application/json, text/plain, */*"
            if data:
                r = session.request(method, link, json=data,
                                    stream=stream, timeout=timeout)
            else:
                r = session.request(
                    method, link, stream=stream, timeout=timeout)
            rule = session_retry_rules(r, link)
            if rule == 1:
                continue
            elif rule == 2:
                break
            if json_format:
                content_type = r.headers['Content-Type']
                matches = ["application/json;", "application/vnd.api+json"]
                if all(match not in content_type for match in matches):
                    continue
                text = r.text
                if not text:
                    message = "ERROR: 100 Posts skipped. Please post the username you're trying to scrape on the issue "'100 Posts Skipped'""
                    log_error.exception(message)
                    return result
                return json.loads(text)
            else:
                return r
        except (ConnectionResetError) as e:
            continue
        except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError, requests.exceptions.ReadTimeout, socket.timeout) as e:
            if sleep:
                time.sleep(sleep_number)
                sleep_number += 0.5
            continue
        except Exception as e:
            log_error.exception(e)
            continue
    return result


def restore_missing_data(master_set2, media_set):
    count = 0
    new_set = []
    for item in media_set:
        if not item:
            new_set.append(master_set2[count])
        count += 1
    return new_set

# def restore_missing_data2(master_set2, media_set):
#     count = 0
#     new_set = []
#     for item in media_set:
#         if not item:
#             link_item = master_set2[count]
#             link = link_item["link"]
#             offset = int(link.split('?')[-1].split('&')[1].split("=")[1])
#             limit = int(link.split("?")[-1].split("&")[0].split("=")[1])
#             num = 2
#             x = []
#             limit2 = int(limit/num)
#             offset2 = offset
#             for item in range(1, num+1):
#                 link2 = link.replace("limit="+str(limit), "limit="+str(limit2))
#                 link2 = link2.replace(
#                     "offset="+str(offset), "offset="+str(offset2))
#                 offset2 += limit2
#                 i = {}
#                 i["link"] = link2
#                 i["count"] = link_item["count"]
#                 new_set.append(i)
#                 print(link2)
#             print
#         print(master_set2[count]["link"])
#         count += 1
#     return new_set


def get_config(config_path):
    if os.path.isfile(config_path):
        if os.stat(config_path).st_size > 0:
            json_config = json.load(open(config_path))
        else:
            json_config = {}
    else:
        json_config = {}
    file_name = os.path.basename(config_path)
    if file_name == "config.json":
        json_config2 = json.loads(json.dumps(make_settings.config(
            **json_config), default=lambda o: o.__dict__))
    else:
        if "onlyfans" in json_config:
            new = {}
            new["supported"] = json_config
            json_config = new
        json_config2 = json.loads(json.dumps(make_settings.extra_auth(
            **json_config), default=lambda o: o.__dict__))
    if json_config != json_config2:
        update_config(json_config2, file_name=file_name)
    if not json_config:
        input(
            f"The .settings\\{file_name} file has been created. Fill in whatever you need to fill in and then press enter when done.\n")
        json_config2 = json.load(open(config_path))

    json_config = copy.deepcopy(json_config2)
    return json_config, json_config2


def update_config(json_config, file_name="config.json"):
    directory = '.settings'
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, file_name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(json_config, f, ensure_ascii=False, indent=2)


def choose_auth(array):
    string = ""
    names = []
    array = [{"auth_count": -1, "username": "All"}]+array
    name_count = len(array)
    if name_count > 1:

        count = 0
        for x in array:
            name = x["username"]
            string += str(count)+" = "+name
            names.append(x)
            if count+1 != name_count:
                string += " | "

            count += 1

    print("Auth Usernames: "+string)
    value = int(input().strip())
    if value:
        names = [names[value]]
    else:
        names.pop(0)
    return names


def is_me(user_api):
    if "email" in user_api:
        return True
    else:
        return False


def update_metadata(path, metadata):
    with open(path, 'w') as outfile:
        json.dump(metadata, outfile)
    print


def create_sign(session, link, sess, user_agent, text="onlyfans"):
    # Users: 300000 | Creators: 301000
    time2 = str(int(round(time.time() * 1000-301000)))
    path = urlparse(link).path
    query = urlparse(link).query
    path = path+"?"+query
    a = [sess, time2, path, user_agent, text]
    msg = "\n".join(a)
    message = msg.encode("utf-8")
    hash_object = hashlib.sha1(message)
    sha_1 = hash_object.hexdigest()
    session.headers["access-token"] = sess
    session.headers["sign"] = sha_1
    session.headers["time"] = time2
    return session


def grouper(n, iterable, fillvalue=None):
    args = [iter(iterable)] * n
    return list(zip_longest(fillvalue=fillvalue, *args))


def assign_session(medias, item, key_one="link", key_two="count", capped=False):
    count = 0
    activate_cap = False
    number = len(item)
    medias2 = []
    for auth in medias:
        media2 = {}
        media2[key_one] = auth
        if not number:
            count = -1
        if activate_cap:
            media2[key_two] = -1
        else:
            media2[key_two] = count

        medias2.append(media2)
        count += 1
        if count >= number:
            count = 0
            if capped:
                activate_cap = True
    return medias2


def create_link_group(max_threads):
    x = range
    print


def metadata_fixer(directory):
    archive_file = os.path.join(directory, "archive.json")
    metadata_file = os.path.join(directory, "Metadata")
    if os.path.exists(archive_file):
        os.makedirs(metadata_file, exist_ok=True)
        new = os.path.join(metadata_file, "Archive.json")
        shutil.move(archive_file, new)
