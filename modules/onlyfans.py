import math
import multiprocessing
import os
import shutil
from datetime import datetime
from itertools import chain, groupby, product
from multiprocessing.dummy import Pool as ThreadPool
from urllib.parse import urlparse
import copy
import timeit


import requests
from requests.adapters import HTTPAdapter

import extras.OFSorter.ofsorter as ofsorter
import helpers.main_helper as main_helper

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
sort_free_paid_posts = None
blacklist_name = None
maximum_length = None
app_token = None


def assign_vars(json_auth, config, site_settings, site_name):
    global json_config, multithreading, proxies, cert, json_settings, auto_choice, j_directory, overwrite_files, date_format, format_path, ignored_keywords, ignore_type, export_metadata, delete_legacy_metadata, sort_free_paid_posts, blacklist_name, maximum_length, app_token

    json_config = config
    json_global_settings = json_config["settings"]
    multithreading = json_global_settings["multithreading"]
    proxies = json_global_settings["socks5_proxy"]
    cert = json_global_settings["cert"]
    json_settings = site_settings
    auto_choice = json_settings["auto_choice"]
    j_directory = main_helper.get_directory(
        json_settings['download_path'], site_name)
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
    app_token = json_auth['app_token']


# The start lol
def start_datascraper(sessions, identifier, site_name, app_token2, choice_type=None):
    global app_token
    print("Scrape Processing")
    app_token = app_token2
    info = link_check(sessions[0], identifier)
    if not info["subbed"]:
        print(info["user"])
        print("First time? Did you forget to edit your config.json file?")
        return [False, []]
    user = info["user"]
    is_me = user["is_me"]
    post_counts = info["count"]
    user_id = str(user["id"])
    username = user["username"]
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
    prep_download = []
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
                    prep_download.append(
                        [media_set["valid"], sessions, directory, username, post_count, location, api_type])
    print("Scrape Completed"+"\n")
    return [True, prep_download]


# Checks if the model is valid and grabs content count
def link_check(session, identifier):
    link = 'https://onlyfans.com/api2/v2/users/' + str(identifier) + \
           '?app-token=' + app_token
    y = main_helper.json_request(session, link)
    temp_user_id2 = dict()
    y["is_me"] = False
    if not y:
        temp_user_id2["subbed"] = False
        temp_user_id2["user"] = "No users found"
        return temp_user_id2
    if "error" in y:
        temp_user_id2["subbed"] = False
        temp_user_id2["user"] = y["error"]["message"]
        return temp_user_id2
    now = datetime.utcnow().date()
    result_date = datetime.utcnow().date()
    if "email" not in y:
        subscribedByData = y["subscribedByData"]
        if subscribedByData:
            expired_at = subscribedByData["expiredAt"]
            result_date = datetime.fromisoformat(
                expired_at).replace(tzinfo=None).date()
        if y["subscribedBy"]:
            subbed = True
        elif y["subscribedOn"]:
            subbed = True
        elif y["subscribedIsExpiredNow"] == False:
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
        temp_user_id2["user"] = "You're not subscribed to the user"
        return temp_user_id2
    else:
        temp_user_id2["subbed"] = True
        temp_user_id2["user"] = y
        temp_user_id2["count"] = [y["postsCount"], y["archivedPostsCount"], [
            y["photosCount"], y["videosCount"], y["audiosCount"]]]
        return temp_user_id2


# Allows the user to choose which api they want to scrape
def scrape_choice(user_id, post_counts, is_me):
    post_count = post_counts[0]
    archived_count = post_counts[1]
    media_counts = post_counts[2]
    media_types = ["Images", "Videos", "Audios"]
    x = dict(zip(media_types, media_counts))
    x = [k for k, v in x.items() if v != 0]
    if auto_choice:
        input_choice = auto_choice
    else:
        print('Scrape: a = Everything | b = Images | c = Videos | d = Audios')
        input_choice = input().strip()
    user_api_ = "https://onlyfans.com/api2/v2/users/"+user_id + \
        "?app-token="+app_token+""
    message_api = "https://onlyfans.com/api2/v2/chats/"+user_id + \
        "/messages?limit=100&offset=0&order=desc&app-token="+app_token+""
    mass_messages_api = "https://onlyfans.com/api2/v2/messages/queue/stats?offset=0&limit=30&app-token="+app_token+""
    stories_api = "https://onlyfans.com/api2/v2/users/"+user_id + \
        "/stories?limit=100&offset=0&order=desc&app-token="+app_token+""
    hightlights_api = "https://onlyfans.com/api2/v2/users/"+user_id + \
        "/stories/highlights?limit=100&offset=0&order=desc&app-token="+app_token+""
    post_api = "https://onlyfans.com/api2/v2/users/"+user_id + \
        "/posts?limit=0&offset=0&order=publish_date_desc&app-token="+app_token+""
    archived_api = "https://onlyfans.com/api2/v2/users/"+user_id + \
        "/posts/archived?limit=100&offset=0&order=publish_date_desc&app-token="+app_token+""
    # ARGUMENTS
    only_links = False
    if "-l" in input_choice:
        only_links = True
        input_choice = input_choice.replace(" -l", "")
    mandatory = [j_directory, only_links]
    y = ["photo", "video", "stream", "gif", "audio"]
    u_array = ["You have chosen to scrape {}", [
        user_api_, x, *mandatory, post_count], "Profile"]
    s_array = ["You have chosen to scrape {}", [
        stories_api, x, *mandatory, post_count], "Stories"]
    h_array = ["You have chosen to scrape {}", [
        hightlights_api, x, *mandatory, post_count], "Highlights"]
    p_array = ["You have chosen to scrape {}", [
        post_api, x, *mandatory, post_count], "Posts"]
    mm_array = ["You have chosen to scrape {}", [
        mass_messages_api, media_types, *mandatory, post_count], "Mass Messages"]
    m_array = ["You have chosen to scrape {}", [
        message_api, media_types, *mandatory, post_count], "Messages"]
    a_array = ["You have chosen to scrape {}", [
        archived_api, media_types, *mandatory, archived_count], "Archived"]
    array = [u_array, s_array, h_array, p_array, a_array, mm_array, m_array]
    # array = [s_array, h_array, p_array, a_array, m_array]
    # array = [u_array]
    # array = [h_array]
    # array = [p_array]
    # array = [a_array]
    # array = [mm_array]
    # array = [m_array]
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


# Downloads the model's avatar and header
def profile_scraper(link, session, directory, username):
    y = main_helper.json_request(session, link)
    q = []
    avatar = y["avatar"]
    header = y["header"]
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
        r = main_helper.json_request(session, media_link, stream=True,
                                     json_format=False, sleep=False)
        if not r:
            continue
        with open(download_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)


# Prepares the API links to be scraped
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
    if api_type == "Profile":
        profile_scraper(link, sessions[0], directory, username)
        return
    if api_type == "Posts":
        num = 50
        link = link.replace("limit=0", "limit="+str(num))
        original_link = link
        ceil = math.ceil(api_count / num)
        a = list(range(ceil))
        for b in a:
            b = b * num
            master_set.append(link.replace(
                "offset=0", "offset=" + str(b)))
    if api_type == "Archived":
        ceil = math.ceil(api_count / 100)
        a = list(range(ceil))
        for b in a:
            b = b * 100
            master_set.append(link.replace(
                "offset=0", "offset=" + str(b)))

    def xmessages(link):
        f_offset_count = 0
        while True:
            y = main_helper.json_request(sessions[0], link)
            if not y:
                return
            if "list" in y:
                if y["list"]:
                    master_set.append(link)
                    if y["hasMore"]:
                        f_offset_count2 = f_offset_count+100
                        f_offset_count = f_offset_count2-100
                        link = link.replace(
                            "offset=" + str(f_offset_count), "offset=" + str(f_offset_count2))
                        f_offset_count = f_offset_count2
                    else:
                        break
                else:
                    break
            else:
                break

    def process_chats(subscriber):
        fool = subscriber["withUser"]
        fool_id = str(fool["id"])
        link_2 = "https://onlyfans.com/api2/v2/chats/"+fool_id + \
            "/messages?limit=100&offset=0&order=desc&app-token="+app_token+""
        xmessages(link_2)
    if api_type == "Messages":
        xmessages(link)
    if api_type == "Mass Messages":
        results = []
        max_threads = multiprocessing.cpu_count()
        offset_count = 0
        offset_count2 = max_threads
        while True:
            def process_messages(link, session):
                y = main_helper.json_request(session, link)
                if y and "error" not in y:
                    return y
                else:
                    return []
            link_list = [link.replace(
                "offset=0", "offset="+str(i*30)) for i in range(offset_count, offset_count2)]
            link_list = pool.starmap(process_messages, product(
                link_list, [sessions[0]]))
            if all(not result for result in link_list):
                break
            link_list2 = list(chain(*link_list))

            results.append(link_list2)
            offset_count = offset_count2
            offset_count2 = offset_count*2
        unsorted_messages = list(chain(*results))
        unsorted_messages.sort(key=lambda x: x["id"])
        messages = unsorted_messages

        def process_mass_messages(message, limit):
            text = message["textCropped"].replace("&", "")
            link_2 = "https://onlyfans.com/api2/v2/chats?limit="+limit+"&offset=0&filter=&order=activity&query=" + \
                text+"&app-token="+app_token
            y = main_helper.json_request(sessions[0], link_2)
            if None == y or "error" in y:
                return []
            return y
        limit = "10"
        if len(messages) > 99:
            limit = "2"
        subscribers = pool.starmap(process_mass_messages, product(
            messages, [limit]))
        subscribers = filter(None, subscribers)
        subscribers = [
            item for sublist in subscribers for item in sublist["list"]]
        seen = set()
        subscribers = [x for x in subscribers if x["withUser"]
                       ["id"] not in seen and not seen.add(x["withUser"]["id"])]
        x = pool.starmap(process_chats, product(
            subscribers))
    if api_type == "Stories":
        master_set.append(link)
    if api_type == "Highlights":
        r = main_helper.json_request(sessions[0], link)
        if "error" in r:
            return
        for item in r:
            link2 = "https://onlyfans.com/api2/v2/stories/highlights/" + \
                str(item["id"])+"?app-token="+app_token+""
            master_set.append(link2)
    master_set2 = main_helper.assign_session(master_set, len(sessions))
    media_set = pool.starmap(media_scraper, product(
        master_set2, [sessions], [directories], [username], [api_type]))
    # media_set = main_helper.restore_missing_data(sessions, media_set)
    media_set = main_helper.format_media_set(media_set)
    seen = set()

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


# Scrapes the API for content
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
    if api_type == "Mass Messages":
        y = y["list"]
    for location in locations:
        master_date = "01-01-0001 00:00:00"
        media_type = location[-1]
        media_type2 = location[0][0]
        media_set2 = {}
        media_set2["type"] = media_type2
        media_set2["valid"] = []
        media_set2["invalid"] = []
        for media_api in y:
            if api_type == "Messages":
                media_api["rawText"] = media_api["text"]
            if api_type == "Mass Messages":
                media_user = media_api["fromUser"]
                media_username = media_user["username"]
                if media_username != username:
                    continue
            for media in media_api["media"]:
                date = "-001-11-30T00:00:00+00:00"
                size = 0
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

                if media["type"] not in media_type:
                    x += 1
                    continue
                if "rawText" not in media_api:
                    media_api["rawText"] = ""
                text = media_api["rawText"] if media_api["rawText"] else ""
                matches = [s for s in ignored_keywords if s in text]
                if matches:
                    print("Matches: ", matches)
                    continue
                text = main_helper.clean_text(text)
                new_dict["postedAt"] = date_string
                post_id = new_dict["post_id"]
                media_id = new_dict["media_id"]
                file_name = link.rsplit('/', 1)[-1]
                file_name, ext = os.path.splitext(file_name)
                ext = ext.__str__().replace(".", "").split('?')[0]
                file_path = main_helper.reformat(location[0][1], post_id, media_id, file_name,
                                                 text, ext, date_object, username, format_path, date_format, maximum_length)
                new_dict["text"] = text
                new_dict["paid"] = False
                if new_dict["price"]:
                    if api_type in ["Messages", "Mass Messages"]:
                        new_dict["paid"] = True
                    else:
                        if media["id"] not in media_api["preview"] and media["canView"]:
                            new_dict["paid"] = True
                new_dict["directory"] = os.path.join(location[0][1])
                if sort_free_paid_posts:
                    new_dict["directory"] = os.path.join(location[1][1])
                    if new_dict["paid"]:
                        new_dict["directory"] = os.path.join(location[2][1])
                new_dict["filename"] = os.path.basename(file_path)
                new_dict["size"] = size
                if size == 0:
                    media_set2["invalid"].append(new_dict)
                    continue
                new_dict["session"] = session
                media_set2["valid"].append(new_dict)
        media_set.append(media_set2)
    return media_set


# Downloads scraped content
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
    string += "Name: "+username+" | Type: " + \
        api_type+" | Directory: " + directory+"\n"
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
            if not r:
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


# Creates an authenticated session
def create_auth(sessions, user_agent, auth_array, max_auth=2):
    me_api = []
    auth_count = 1
    auth_version = "(V1)"
    count = 1
    try:
        auth_id = auth_array["auth_id"]
        auth_cookies = [
            {'name': 'auth_id', 'value': auth_id},
            {'name': 'sess', 'value': auth_array["sess"]},
            {'name': 'auth_hash', 'value': auth_array["auth_hash"]},
            {'name': 'auth_uniq_'+auth_id, 'value': auth_array["auth_uniq_"]},
            {'name': 'fp', 'value': auth_array["fp"]},
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
                    'user-agent': user_agent, 'referer': 'https://onlyfans.com/'}
                if auth_array["sess"]:
                    found = False
                    for auth_cookie in auth_cookies:
                        if auth_array["sess"] == auth_cookie["value"]:
                            found = True
                            break
                    if not found:
                        auth_cookies.append(
                            {'name': 'sess', 'value': auth_array["sess"], 'domain': '.onlyfans.com'})
                for auth_cookie in auth_cookies:
                    session.cookies.set(**auth_cookie)

            max_count = 10
            while count < 11:
                print("Auth Attempt "+str(count)+"/"+str(max_count))
                link = "https://onlyfans.com/api2/v2/users/customer?app-token="+app_token
                for session in sessions:
                    a = [session, link, sess, user_agent]
                    session = main_helper.create_sign(*a)
                session = sessions[0]
                r = main_helper.json_request(session, link, sleep=False)
                count += 1
                if not r:
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
                                    r = main_helper.json_request(
                                        session, link, "PUT", data=data)
                                    if "error" in r:
                                        count += 1
                                    else:
                                        print("Success")
                                        return [True, r]
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
                link = "https://onlyfans.com/api2/v2/subscriptions/count/all?app-token="+app_token
                r = main_helper.json_request(session, link, sleep=False)
                if not r:
                    break
                array = dict()
                array["sessions"] = sessions
                array["option_string"] = option_string
                array["subscriber_count"] = r["subscriptions"]["active"]
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
    link = "https://onlyfans.com/api2/v2/subscriptions/subscribes?offset=0&type=active&limit=99&app-token="+app_token
    ceil = math.ceil(subscriber_count / 99)
    a = list(range(ceil))
    offset_array = []
    for b in a:
        b = b * 99
        offset_array.append(
            [link.replace("offset=0", "offset=" + str(b)), False])
    if me_api["isPerformer"]:
        link = "https://onlyfans.com/api2/v2/users/" + \
            str(me_api["id"])+"?app-token="+app_token
        offset_array = [[link, True]] + offset_array

    def multi(array, session):
        link = array[0]
        performer = array[1]
        r = main_helper.json_request(session, link)
        # Following logic is unique to creators only
        if performer:
            if isinstance(r, dict):
                if not r["subscribedByData"]:
                    r["subscribedByData"] = dict()
                    r["subscribedByData"]["expiredAt"] = datetime.utcnow().isoformat()
                    r["subscribedByData"]["price"] = r["subscribePrice"]
                    r["subscribedByData"]["subscribePrice"] = 0
            if None != r:
                r = [r]
        return r
    link_count = len(offset_array) if len(offset_array) > 0 else 1
    pool = ThreadPool(link_count)
    results = pool.starmap(multi, product(
        offset_array, [session]))
    results = [x for x in results if x is not None]
    results = list(chain(*results))
    if blacklist_name:
        link = "https://onlyfans.com/api2/v2/lists?offset=0&limit=100&app-token="+app_token
        r = main_helper.json_request(session, link)
        if not r:
            return [False, []]
        x = [c for c in r if blacklist_name == c["name"]]
        if x:
            x = x[0]
            list_users = x["users"]
            if x["usersCount"] > 2:
                list_id = str(x["id"])
                link = "https://onlyfans.com/api2/v2/lists/"+list_id + \
                    "/users?offset=0&limit=100&query=&app-token="+app_token
                r = main_helper.json_request(session, link)
                list_users = r
            users = list_users
            bl_ids = [x["username"] for x in users]
            results2 = results.copy()
            for result in results2:
                identifier = result["username"]
                if identifier in bl_ids:
                    print("Blacklisted: "+identifier)
                    results.remove(result)
    if any("error" in result for result in results):
        print("Invalid App Token")
        return []
    else:
        results.sort(key=lambda x: x["subscribedByData"]['expiredAt'])
        results2 = []
        for result in results:
            result["auth_count"] = auth_count
            result["self"] = False
            username = result["username"]
            now = datetime.utcnow().date()
            # subscribedBy = result["subscribedBy"]
            subscribedByData = result["subscribedByData"]
            result_date = subscribedByData["expiredAt"] if subscribedByData else datetime.utcnow(
            ).isoformat()
            price = subscribedByData["price"]
            subscribePrice = subscribedByData["subscribePrice"]
            result_date = datetime.fromisoformat(
                result_date).replace(tzinfo=None).date()
            if ignore_type in ["paid"]:
                if price > 0:
                    continue
            if ignore_type in ["free"]:
                if subscribePrice == 0:
                    continue
            results2.append(result)
        return results2


# Ah yes, the feature that will probably never be done
def get_paid_posts(sessions):
    paid_api = "https://onlyfans.com/api2/v2/posts/paid?limit=100&offset=0&app-token="+app_token+""
    max_threads = multiprocessing.cpu_count()
    x = main_helper.create_link_group(max_threads)
    print
    result = {}
    result["link"] = paid_api
    directory = []
    print
    x = media_scraper(paid_api, sessions, "a", "a", "a")
    print


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
