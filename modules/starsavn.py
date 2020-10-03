import json
import logging
import math
import multiprocessing
import os
from datetime import datetime
from itertools import chain, count, product
from multiprocessing.dummy import Pool as ThreadPool
from random import randrange
import shutil
import copy

import requests
from requests.adapters import HTTPAdapter

import helpers.main_helper as main_helper
import classes.prepare_download as prepare_download
from types import SimpleNamespace

log_download = main_helper.setup_logger('downloads', 'downloads.log')

json_config = None
multithreading = None
json_settings = None
auto_choice = None
j_directory = None
format_path = None
overwrite_files = None
proxies = None
cert = None
date_format = None
ignored_keywords = None
ignore_type = None
export_metadata = None
delete_legacy_metadata = None
blacklist_name = None
webhook = None
maximum_length = None


def assign_vars(config, site_settings, site_name):
    global json_config, multithreading, proxies, cert, json_settings, auto_choice, j_directory, overwrite_files, date_format, format_path, ignored_keywords, ignore_type, export_metadata, blacklist_name, webhook, maximum_length

    json_config = config
    json_global_settings = json_config["settings"]
    multithreading = json_global_settings["multithreading"]
    proxies = json_global_settings["socks5_proxy"]
    cert = json_global_settings["cert"]
    json_settings = site_settings
    auto_choice = json_settings["auto_choice"]
    j_directory = main_helper.get_directory(
        json_settings['download_paths'], site_name)
    format_path = json_settings["file_name_format"]
    overwrite_files = json_settings["overwrite_files"]
    date_format = json_settings["date_format"]
    ignored_keywords = json_settings["ignored_keywords"]
    ignore_type = json_settings["ignore_type"]
    export_metadata = json_settings["export_metadata"]
    blacklist_name = json_settings["blacklist_name"]
    webhook = json_settings["webhook"]
    maximum_length = 255
    maximum_length = int(json_settings["text_length"]
                         ) if json_settings["text_length"] else maximum_length


def start_datascraper(sessions, identifier, site_name, app_token, choice_type=None):
    print("Scrape Processing")
    info = link_check(sessions[0], identifier)
    user = info["user"]
    user = json.loads(json.dumps(
        user), object_hook=lambda d: SimpleNamespace(**d))
    if not info["exists"]:
        info["user"] = user
        return [False, info]
    is_me = user.is_me
    post_counts = info["count"]
    post_count = post_counts[0]
    user_id = str(user.id)
    avatar = user.avatar
    username = user.username
    link = user.link
    info["download"] = prepare_download.start(
        username=username, link=link, image_url=avatar, post_count=post_count, webhook=webhook)
    if not info["subbed"]:
        print(f"You are not subbed to {user.username}")
        return [False, info]

    print("Name: "+username)
    api_array = scrape_choice(user_id, post_counts, is_me)
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
    prep_download = prepare_download.start(
        username=username, link=link, image_url=avatar, post_count=post_count, webhook=webhook)
    for item in apis:
        print("Type: "+item["api_type"])
        only_links = item["api_array"]["only_links"]
        post_count = str(item["api_array"]["post_count"])
        item["api_array"]["username"] = username
        api_type = item["api_type"]
        results = prepare_scraper(
            sessions, site_name, item)
        if results:
            for result in results[0]:
                if not only_links:
                    media_set = result
                    if not media_set["valid"]:
                        continue
                    directory = results[1]
                    location = result["type"]
                    info["download"].others.append(
                        [media_set["valid"], sessions, directory, username, post_count, location, api_type])
    # When profile is done scraping, this function will return True
    print("Scrape Completed"+"\n")
    return [True, info]


def link_check(session, identifier):
    model_link = f"https://stars.avn.com/{identifier}"
    link = f"https://stars.avn.com/api2/v2/users/{identifier}"
    y = main_helper.json_request(session, link)
    temp_user_id2 = dict()
    temp_user_id2["exists"] = True
    y["is_me"] = False
    if "error" in y:
        temp_user_id2["subbed"] = False
        y["username"] = identifier
        temp_user_id2["user"] = y
        temp_user_id2["exists"] = False
        return temp_user_id2
    now = datetime.utcnow().date()
    result_date = datetime.utcnow().date()
    if "email" not in y:
        if y["followedBy"]:
            subbed = True
        elif y["subscribedBy"]:
            subbed = True
        elif y["subscribedOn"]:
            subbed = True
        elif result_date >= now:
            subbed = True
        else:
            subbed = False
    else:
        subbed = True
        y["is_me"] = True
    if not subbed:
        temp_user_id2["subbed"] = False
    else:
        temp_user_id2["subbed"] = True
    temp_user_id2["user"] = y
    temp_user_id2["count"] = [y["postsCount"], [
        y["photosCount"], y["videosCount"]]]
    temp_user_id2["user"]["link"] = model_link
    return temp_user_id2


def scrape_choice(user_id, post_counts, is_me):
    post_count = post_counts[0]
    media_counts = post_counts[1]
    media_types = ["Images", "Videos"]
    x = dict(zip(media_types, media_counts))
    x = [k for k, v in x.items() if v != 0]
    if auto_choice:
        input_choice = auto_choice
    else:
        print('Scrape: a = Everything | b = Images | c = Videos')
        input_choice = input().strip()
    message_api = "https://stars.avn.com/api2/v2/chats/"+user_id + \
        "/messages?limit=50"
    stories_api = "https://stars.avn.com/api2/v2/users/"+user_id + \
        "/stories/?limit=10&marker=&offset=0"
    hightlights_api = "https://stars.avn.com/api2/v2/users/"+user_id + \
        "/stories/collections/?limit=10&marker=&offset=0"
    post_api = "https://stars.avn.com/api2/v2/users/"+user_id + \
        "/posts/?limit=10&marker=&offset=0"
    # ARGUMENTS
    only_links = False
    if "-l" in input_choice:
        only_links = True
        input_choice = input_choice.replace(" -l", "")
    mandatory = [j_directory, only_links]
    y = ["photo", "video", "stream", "gif", "audio"]
    s_array = ["You have chosen to scrape {}", [
        stories_api, x, *mandatory, post_count], "Stories"]
    h_array = ["You have chosen to scrape {}", [
        hightlights_api, x, *mandatory, post_count], "Highlights"]
    p_array = ["You have chosen to scrape {}", [
        post_api, x, *mandatory, post_count], "Posts"]
    # mm_array = ["You have chosen to scrape {}", [
    #     mass_messages_api, x, *mandatory, post_count], "Mass Messages"]
    # m_array = ["You have chosen to scrape {}", [
    #     message_api, x, *mandatory, post_count], "Messages"]
    array = [s_array, h_array, p_array]
    new_array = []
    valid_input = True
    for xxx in array:
        if xxx[2] == "Mass Messages":
            if not is_me:
                continue
        new_item = dict()
        new_item["api_message"] = xxx[0]
        new_item["api_array"] = {}
        new_item["api_array"]["api_link"] = xxx[1][0]
        new_item["api_array"]["media_types"] = xxx[1][1]
        new_item["api_array"]["directory"] = xxx[1][2]
        new_item["api_array"]["only_links"] = xxx[1][3]
        new_item["api_array"]["post_count"] = xxx[1][4]
        if input_choice == "a":
            name = "All"
            a = []
            for z in new_item["api_array"]["media_types"]:
                if z == "Images":
                    a.append([z, [y[0]]])
                if z == "Videos":
                    a.append([z, y[1:4]])
                if z == "Audios":
                    a.append([z, [y[4]]])
            new_item["api_array"]["media_types"] = a
        elif input_choice == "b":
            name = "Images"
            new_item["api_array"]["media_types"] = [[name, [y[0]]]]
        elif input_choice == "c":
            name = "Videos"
            new_item["api_array"]["media_types"] = [[name, y[1:4]]]
        elif input_choice == "d":
            name = "Audios"
            new_item["api_array"]["media_types"] = [[name, [y[4]]]]
        else:
            print("Invalid Choice")
            valid_input = False
            break
        new_item["api_type"] = xxx[2]
        if valid_input:
            new_array.append(new_item)
    return new_array


def prepare_scraper(sessions, site_name, item):
    api_type = item["api_type"]
    api_array = item["api_array"]
    link = api_array["api_link"]
    locations = api_array["media_types"]
    username = api_array["username"]
    directory = api_array["directory"]
    api_count = api_array["post_count"]
    seperator = " | "
    user_directory = ""
    metadata_directory = ""
    master_set = []
    media_set = []
    metadata_set = []
    original_link = link
    directories = []
    pool = ThreadPool()
    for location in locations:
        link = original_link
        print("Scraping ["+str(seperator.join(location[1])) +
              "]. Should take less than a minute.")
        array = main_helper.format_directory(
            j_directory, site_name, username, location[0], api_type)
        user_directory = array[0]
        metadata_directory = array[1]
        directories.append(array[2]+[location[1]])
    if api_type == "Posts":
        ceil = math.ceil(api_count / 100)
        a = list(range(ceil))
        for b in a:
            b = b * 100
            master_set.append(link.replace(
                "offset=0", "offset=" + str(b)))
    if api_type == "Archived":
        ceil = math.ceil(api_count / 100)
        a = list(range(ceil))
        for b in a:
            b = b * 100
            master_set.append(link.replace(
                "offset=0", "offset=" + str(b)))
    if api_type == "Stories":
        master_set.append(link)
    if api_type == "Highlights":
        r = main_helper.json_request(sessions[0], link)
        if "error" in r:
            return
        for item in r["list"]:
            link2 = "https://stars.avn.com/api2/v2/stories/collections/" + \
                str(item["id"])
            master_set.append(link2)
    master_set2 = main_helper.assign_session(master_set, sessions)
    media_set = []
    count = len(master_set2)
    max_attempts = 100
    for attempt in list(range(max_attempts)):
        print("Scrape Attempt: "+str(attempt+1)+"/"+str(max_attempts))
        media_set2 = pool.starmap(media_scraper, product(
            master_set2, [sessions], [directories], [username], [api_type]))
        media_set.extend(media_set2)
        if count > 1:
            faulty = [x for x in media_set2 if not x]
            if not faulty:
                print("Found: "+api_type)
                break
            else:
                num = len(faulty)*100
                print("Missing "+str(num)+" Posts... Retrying...")
                master_set2 = main_helper.restore_missing_data(
                    master_set2, media_set2)
        else:
            print("No "+api_type+" Found.")
            break
    media_set = main_helper.format_media_set(media_set)

    metadata_set = media_set
    if export_metadata:
        metadata_set = [x for x in metadata_set if x["valid"] or x["invalid"]]
        for item in metadata_set:
            if item["valid"] or item["invalid"]:
                legacy_metadata = os.path.join(
                    user_directory, api_type, "Metadata")
                if delete_legacy_metadata:
                    if os.path.isdir(legacy_metadata):
                        shutil.rmtree(legacy_metadata)
        if metadata_set:
            os.makedirs(metadata_directory, exist_ok=True)
            archive_directory = os.path.join(metadata_directory, api_type)
            metadata_set_copy = copy.deepcopy(metadata_set)
            metadata_set = main_helper.filter_metadata(metadata_set_copy)
            main_helper.export_archive(
                metadata_set, archive_directory, json_settings)
    return [media_set, directory]


def media_scraper(result, sessions, locations, username, api_type):
    link = result["link"]
    session = sessions[result["count"]]
    media_set = []
    y = main_helper.json_request(session, link)
    if not y or "error" in y:
        return media_set
    x = 0
    if api_type == "Highlights":
        y = y["stories"]
    if api_type == "Messages":
        y = y["list"]
    y = y["list"] if "list" in y else y
    for location in locations:
        master_date = "01-01-0001 00:00:00"
        media_type = location[-1]
        media_type2 = location[0][0]
        media_set2 = {}
        media_set2["type"] = media_type2
        media_set2["valid"] = []
        media_set2["invalid"] = []
        for media_api in y:
            if api_type == "Mass Messages":
                media_user = media_api["fromUser"]
                media_username = media_user["username"]
                if media_username != username:
                    continue
            new_api = (media_api["media"]
                       if "media" in media_api else [media_api])
            for media in new_api:
                date = "-001-11-30T00:00:00+00:00"
                size = 1
                src = media["src"]
                link = src["source"]
                date = media_api["createdAt"] if "createdAt" in media_api else media_api["postedAt"]
                if not link:
                    continue
                new_dict = dict()
                new_dict["post_id"] = media_api["id"]
                new_dict["links"] = [link]
                if date == "-001-11-30T00:00:00+00:00":
                    date_string = master_date
                    date_object = datetime.strptime(
                        master_date, "%d-%m-%Y %H:%M:%S")
                else:
                    date_object = datetime.fromisoformat(date)
                    date_string = date_object.replace(tzinfo=None).strftime(
                        "%d-%m-%Y %H:%M:%S")
                    master_date = date_string
                media["mediaType"] = media["mediaType"] if "mediaType" in media else media["type"]
                if media["mediaType"] not in media_type:
                    x += 1
                    continue
                if "text" not in media_api:
                    media_api["text"] = ""
                new_dict["text"] = media_api["text"] if media_api["text"] else ""
                new_dict["postedAt"] = date_string
                post_id = new_dict["post_id"]
                media_id = media["id"] if "id" in media else None
                media_id = media_id if isinstance(media_id, int) else None
                text = new_dict["text"]
                file_name = link.rsplit('/', 1)[-1]
                file_name, ext = os.path.splitext(file_name)
                ext = ext.__str__().replace(".", "").split('?')[0]
                file_path = main_helper.reformat(location[0][1], post_id, media_id, file_name,
                                                 text, ext, date_object, username, format_path, date_format, maximum_length)
                new_dict["directory"] = location[0][1]
                new_dict["filename"] = file_path.rsplit('/', 1)[-1]
                new_dict["size"] = size
                if size == 0:
                    media_set2["invalid"].append(new_dict)
                    continue
                new_dict["session"] = session
                media_set2["valid"].append(new_dict)
        media_set.append(media_set2)
    return media_set


def download_media(media_set, session, directory, username, post_count, location, api_type):
    def download(medias, session, directory, username):
        return_bool = True
        for media in medias:
            count = 0
            session = media["session"]
            while count < 11:
                links = media["links"]

                def choose_link(session, links):
                    for link in links:
                        r = main_helper.json_request(session, link, "HEAD",
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
                date_object = datetime.strptime(
                    media["postedAt"], "%d-%m-%Y %H:%M:%S")
                download_path = os.path.join(
                    media["directory"], media["filename"])
                timestamp = date_object.timestamp()
                if not overwrite_files:
                    if main_helper.check_for_dupe_file(download_path, content_length):
                        main_helper.format_image(download_path, timestamp)
                        return_bool = False
                        break
                r = main_helper.json_request(
                    session, link, stream=True, json_format=False)
                if not isinstance(r, requests.Response):
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
                    main_helper.log_error.exception(
                        str(e) + "\n Tries: "+str(count))
                    count += 1
                    continue
                main_helper.format_image(download_path, timestamp)
                log_download.info("Link: {}".format(link))
                log_download.info("Path: {}".format(download_path))
                break
        return return_bool
    string = "Download Processing\n"
    string += "Name: "+username+" | Directory: " + directory+"\n"
    string += "Downloading "+str(len(media_set))+" "+location+"\n"
    print(string)
    if multithreading:
        pool = ThreadPool()
    else:
        pool = ThreadPool(1)
    pool.starmap(download, product(
        media_set, [session], [directory], [username]))


def create_session(custom_proxy="", test_ip=True):
    session = [requests.Session()]
    if not proxies:
        return session

    max_threads = multiprocessing.cpu_count()

    def set_sessions(proxy):
        session = requests.Session()
        proxy_type = {'http': 'socks5h://'+proxy,
                      'https': 'socks5h://'+proxy}
        if proxy:
            session.proxies = proxy_type
            if cert:
                session.verify = cert
        session.mount(
            'https://', HTTPAdapter(pool_connections=max_threads, pool_maxsize=max_threads))
        if test_ip:
            link = 'https://checkip.amazonaws.com'
            r = main_helper.json_request(
                session, link, json_format=False, sleep=False)
            if not isinstance(r, requests.Response):
                print("Proxy Not Set: "+proxy+"\n")
                return
            ip = r.text.strip()
            print("Session IP: "+ip+"\n")
        return session
    pool = ThreadPool()
    sessions = []
    while not sessions:
        proxies2 = [custom_proxy] if custom_proxy else proxies
        sessions = pool.starmap(set_sessions, product(
            proxies2))
        sessions = [x for x in sessions if x]
    return sessions


def create_auth(sessions, user_agent, auth_array, max_auth=2):
    me_api = []
    auth_count = 1
    auth_version = "(V1)"
    count = 1
    try:
        auth_cookies = [
        ]
        while auth_count < max_auth+1:
            if auth_count == 2:
                auth_version = "(V2)"
                if auth_array["sess"]:
                    del auth_cookies[2]
                count = 1
            print("Auth "+auth_version)
            sess = auth_array["sess"]
            for session in sessions:
                session.headers = {
                    'User-Agent': user_agent, 'Referer': 'https://stars.avn.com/'}
                if auth_array["sess"]:
                    found = False
                    for auth_cookie in auth_cookies:
                        if auth_array["sess"] == auth_cookie["value"]:
                            found = True
                            break
                    if not found:
                        auth_cookies.append(
                            {'name': 'sess', 'value': auth_array["sess"], 'domain': '.stars.avn.com'})
                for auth_cookie in auth_cookies:
                    session.cookies.set(**auth_cookie)

            max_count = 10
            while count < 11:
                print("Auth Attempt "+str(count)+"/"+str(max_count))
                link = "https://stars.avn.com/api2/v2/users/me"
                for session in sessions:
                    a = [session, link, sess, user_agent]
                    session = main_helper.create_sign(*a)
                session = sessions[0]
                r = main_helper.json_request(session, link)
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
                        return [False, r["error"]["message"]]
                if "name" not in r:
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
                print("Welcome "+r["name"])
                option_string = "username or profile link"
                array = dict()
                array["sessions"] = sessions
                array["option_string"] = option_string
                array["subscriber_count"] = r["followingCount"]
                array["me_api"] = me_api
                return array
            auth_count += 1
    except Exception as e:
        main_helper.log_error.exception(e)
    array = dict()
    array["sessions"] = None
    array["me_api"] = me_api
    return array


def get_subscriptions(session, subscriber_count, me_api, auth_count=0):
    link = "https://stars.avn.com/api2/v2/subscriptions/following/?limit=10&marker=&offset=0"
    r = main_helper.json_request(session, link)
    if not r:
        return None
    for x in r["list"]:
        x["auth_count"] = auth_count
    return r["list"]


def format_options(array, choice_type):
    new_item = {}
    new_item["auth_count"] = -1
    new_item["username"] = "All"
    array = [new_item]+array
    name_count = len(array)

    count = 0
    names = []
    string = ""
    if "usernames" == choice_type:
        for x in array:
            name = x["username"]
            string += str(count)+" = "+name
            names.append([x["auth_count"], name])
            if count+1 != name_count:
                string += " | "
            count += 1
    if "apis" == choice_type:
        names = array
        for api in array:
            if "username" in api:
                name = api["username"]
            else:
                name = api["api_type"]
            string += str(count)+" = "+name
            if count+1 != name_count:
                string += " | "
            count += 1
    return [names, string]
