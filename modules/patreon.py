import math
import mimetypes
import multiprocessing
import os
import shutil
from datetime import datetime
from itertools import chain, groupby, product
from multiprocessing.dummy import Pool as ThreadPool
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from requests.sessions import session

import extras.OFSorter.ofsorter as ofsorter
from helpers.main_helper import (check_for_dupe_file, clean_text,
                                 export_archive, format_directory,
                                 format_image, format_media_set, get_directory,
                                 json_request, log_error, reformat,
                                 setup_logger)

log_download = setup_logger('downloads', 'downloads.log')

json_config = None
multithreading = None
json_settings = None
auto_choice = None
j_directory = None
format_path = None
overwrite_files = None
proxy = None
cert = None
date_format = None
ignored_keywords = None
ignore_type = None
export_metadata = None
delete_legacy_metadata = None
sort_free_paid_posts = None
blacklist_name = None
maximum_length = None


def assign_vars(config, site_settings, site_name):
    global json_config, multithreading, proxy, cert, json_settings, auto_choice, j_directory, overwrite_files, date_format, format_path, ignored_keywords, ignore_type, export_metadata, delete_legacy_metadata, sort_free_paid_posts, blacklist_name, maximum_length

    json_config = config
    json_global_settings = json_config["settings"]
    multithreading = json_global_settings["multithreading"]
    proxy = json_global_settings["socks5_proxy"]
    cert = json_global_settings["cert"]
    json_settings = site_settings
    auto_choice = json_settings["auto_choice"]
    j_directory = get_directory(json_settings['download_path'], site_name)
    format_path = json_settings["file_name_format"]
    overwrite_files = json_settings["overwrite_files"]
    date_format = json_settings["date_format"]
    ignored_keywords = json_settings["ignored_keywords"]
    ignore_type = json_settings["ignore_type"]
    export_metadata = json_settings["export_metadata"]
    delete_legacy_metadata = json_settings["delete_legacy_metadata"]
    sort_free_paid_posts = json_settings["sort_free_paid_posts"]
    blacklist_name = json_settings["blacklist_name"]
    maximum_length = 255
    maximum_length = int(json_settings["text_length"]
                         ) if json_settings["text_length"] else maximum_length


def create_session(test_ip=True):
    max_threads = multiprocessing.cpu_count()
    session = requests.Session()
    proxies = {'http': 'socks5h://'+proxy,
               'https': 'socks5h://'+proxy}
    if proxy:
        session.proxies = proxies
        if cert:
            session.verify = cert
    session.mount(
        'https://', HTTPAdapter(pool_connections=max_threads, pool_maxsize=max_threads))
    if test_ip:
        ip = session.get('https://checkip.amazonaws.com').text.strip()
        print("Session IP: "+ip)
    return session


def create_auth(session, user_agent, auth_array, max_auth=2):
    me_api = []
    auth_count = 1
    auth_version = "(V1)"
    count = 1
    try:
        auth_cookie = []
        auth_cookies = [{'name': 'cf_clearance', 'value': auth_array["cf_clearance"], 'domain': '.patreon.com'}
                        ]
        print
        while auth_count < max_auth+1:
            if auth_count == 2:
                auth_version = "(V2)"
                if auth_array["session_id"]:
                    del auth_cookies[2]
                count = 1
            print("Auth "+auth_version)
            session.headers = {
                'User-Agent': user_agent, 'Referer': 'https://patreon.com/'}
            if auth_array["session_id"]:
                found = False
                for auth_cookie in auth_cookies:
                    if auth_array["session_id"] == auth_cookie["value"]:
                        found = True
                        break
                if not found:
                    auth_cookies.append(
                        {'name': 'session_id', 'value': auth_array["session_id"], 'domain': '.patreon.com'})
            for auth_cookie in auth_cookies:
                session.cookies.set(**auth_cookie)

            max_count = 10
            while count < 11:
                print("Auth Attempt "+str(count)+"/"+str(max_count))
                link = "https://www.patreon.com/api/current_user"
                r = json_request(session, link)
                count += 1
                if not r:
                    auth_cookies = []
                    continue
                me_api = r

                def resolve_auth(r):
                    if 'error' in r:
                        error = r["error"]
                        error_message = r["error"]["message"]
                        error_code = error["code"]
                        if error_code == 0:
                            print(error_message)
                        if error_code == 101:
                            error_message = "Blocked by 2FA."
                            print(error_message)
                            if auth_array["support_2fa"]:
                                link = "https://onlyfans.com/api2/v2/users/otp?app-token="+app_token
                                count = 1
                                max_count = 3
                                while count < max_count+1:
                                    print("2FA Attempt "+str(count) +
                                          "/"+str(max_count))
                                    code = input("Enter 2FA Code\n")
                                    data = {'code': code, 'rememberMe': True}
                                    r = json_request(
                                        session, link, "PUT", data=data)
                                    if "error" in r:
                                        count += 1
                                    else:
                                        print("Success")
                                        return [True, r]
                        return [False, r["error"]["message"]]
                r = r["data"]
                if "id" not in r:
                    result = resolve_auth(r)
                    if not result[0]:
                        error_message = result[1]
                        if "token" in error_message:
                            break
                        if "Code wrong" in error_message:
                            break
                        continue
                    else:
                        continue
                r = r["attributes"]
                print("Welcome "+r["full_name"])
                option_string = "username or profile link"
                array = dict()
                array["session"] = session
                array["option_string"] = option_string
                array["me_api"] = me_api
                return array
            auth_count += 1
    except Exception as e:
        log_error.exception(e)
        # input("Enter to continue")
    array = dict()
    array["session"] = None
    array["me_api"] = me_api
    return array


def get_subscriptions(session, auth_count=0):
    link = "https://www.patreon.com/api/pledges?include=campaign&fields[campaign]=avatar_photo_url,cover_photo_url,is_monthly,is_non_profit,name,pay_per_name,pledge_url,published_at,url&fields[user]=thumb_url,url,full_name&json-api-use-default-includes=false&json-api-version=1.0"
    r = json_request(session, link)
    if not r:
        return
    datas = r["included"]
    for data in datas:
        data["attributes"]["auth_count"] = auth_count
    return datas


def format_options(array, choice_type):
    string = ""
    names = []
    array = [{"auth_count": -1, "name": "All"}]+array
    name_count = len(array)
    if "usernames" == choice_type:
        if name_count > 1:

            count = 0
            uid = 0
            for x in array:
                if "attributes" in x:
                    uid = x["id"]
                    x = x["attributes"]
                name = x["name"]
                string += str(count)+" = "+name
                names.append([x["auth_count"], name, uid])
                if count+1 != name_count:
                    string += " | "

                count += 1
    if "apis" == choice_type:
        count = 0
        names = array
        for api in array:
            if "username" in api:
                name = api["username"]
            else:
                name = api[2]
            string += str(count)+" = "+name
            if count+1 != name_count:
                string += " | "

            count += 1
    return [names, string]


def start_datascraper(session, identifier, site_name, app_token, choice_type=None):
    print("Scrape Processing")
    info = link_check(session, identifier)
    if not info["subbed"]:
        print(info["user"])
        print("First time? Did you forget to edit your config.json file?")
        return [False, []]
    user = info["user"]
    user_id = str(user["id"])
    username = user["name"]
    print("Name: "+username)
    identifiers = [identifier, username]
    results = prepare_scraper(
        session, identifiers)
    # When profile is done scraping, this function will return True
    print("Scrape Completed"+"\n")
    prep_download = []
    return [False, prep_download]


def link_check(session, identifier):
    print
    link = "https://www.patreon.com/api/campaigns/" + \
        str(identifier) + \
        "?include=access_rules.tier.null&fields[access_rule]=access_rule_type%2Camount_cents%2Cpost_count&fields[reward]=title%2Cid%2Camount_cents&json-api-version=1.0"
    y = json_request(session, link)
    print
    temp_user_id2 = dict()
    if not y:
        temp_user_id2["subbed"] = False
        temp_user_id2["user"] = "No users found"
        return temp_user_id2
    if "errors" in y:
        temp_user_id2["subbed"] = False
        temp_user_id2["user"] = y["error"]["message"]
        return temp_user_id2
    temp_user_id2["subbed"] = True
    data = y["data"]
    temp_user_id2["user"] = data["attributes"]
    temp_user_id2["user"]["id"] = data["id"]
    return temp_user_id2


def prepare_scraper(session, identifiers):
    user_id = identifiers[0]
    username = identifiers[1]
    link = "https://www.patreon.com/api/posts?include=audio,images,media&filter[campaign_id]=" + \
        user_id+"&sort=-published_at"
    posts = []
    directory = os.path.join(str(j_directory), username)
    while True:
        print
        y = json_request(session, link)
        included = y["included"]
        for x in included:
            att = x["attributes"]
            try:
                x["links"] = [att["download_url"]]
                file_name = att["file_name"]
                if not file_name or "patreonusercontent" in file_name:
                    ext = mimetypes.guess_extension(att["mimetype"])
                    file_name = x["id"]+ext
                if "https" in file_name:
                    file_name = os.path.basename(file_name)
                owner_type = att["owner_type"].capitalize()
                owner_relationship = att["owner_relationship"].capitalize()
                if owner_relationship in ["Main", "Inline"]:
                    owner_relationship = "Images"
                    print
                x["file_name"] = file_name
                x["size"] = att["size_bytes"]
                directory2 = os.path.join(
                    directory, owner_type, owner_relationship)
                os.makedirs(directory2, exist_ok=True)
                x["download_path"] = os.path.join(directory2, file_name)
                date_string = datetime.fromisoformat(
                    att["created_at"]).replace(tzinfo=None).strftime(
                    "%d-%m-%Y %H:%M:%S")
                x["postedAt"] = date_string
            except Exception as e:
                print(e)
        posts.append(y["included"])
        if "links" not in y:
            break
        link = y["links"]["next"]
    posts = list(chain(*posts))
    seen = set()
    posts = [x for x in posts
             if x["file_name"]+str(x["size"]) not in seen and not seen.add(x["file_name"]+str(x["size"]))]
    posts.sort(key=lambda x: x["id"], reverse=True)

    def download(media, session):
        return_bool = True
        count = 0
        while count < 11:
            links = media["links"]

            def choose_link(session, links):
                for link in links:
                    r = json_request(session, link, "HEAD", True, False)
                    if not r:
                        continue

                    header = r.headers
                    content_length = int(header["content-length"])
                    if not content_length:
                        continue
                    return [link, content_length]
            result = choose_link(session, links)
            if not result:
                count += 1
                continue
            link = result[0]
            content_length = result[1]
            date_object = datetime.strptime(
                media["postedAt"], "%d-%m-%Y %H:%M:%S")
            download_path = media["download_path"]
            timestamp = date_object.timestamp()
            if not overwrite_files:
                if check_for_dupe_file(download_path, content_length):
                    format_image(download_path, timestamp)
                    return_bool = False
                    count += 1
                    break
            r = json_request(session, link, "GET", True, False)
            if not r:
                return_bool = False
                count += 1
                continue
            delete = False
            try:
                with open(download_path, 'wb') as f:
                    delete = True
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:  # filter out keep-alive new chunks
                            f.write(chunk)
            except (ConnectionResetError) as e:
                if delete:
                    os.unlink(download_path)
                count += 1
                continue
            except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
                count += 1
                continue
            except Exception as e:
                if delete:
                    os.unlink(download_path)
                log_error.exception(str(e) + "\n Tries: "+str(count))
                count += 1
                continue
            format_image(download_path, timestamp)
            log_download.info("Link: {}".format(link))
            log_download.info("Path: {}".format(download_path))
            break
        return return_bool
    pool = ThreadPool()
    pool.starmap(download, product(
        posts, [session]))
    print
