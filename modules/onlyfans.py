import math
import multiprocessing
import os
import shutil
from datetime import datetime
from itertools import chain, groupby, product
from multiprocessing.dummy import Pool as ThreadPool
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

import extras.OFSorter.ofsorter as ofsorter
from helpers.main_helper import (check_for_dupe_file, clean_text, create_sign,
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


def start_datascraper(session, identifier, site_name, app_token,choice_type=None):
    print("Scrape Processing")
    info = link_check(session, app_token, identifier)
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
    api_array = scrape_choice(user_id, app_token, post_counts, is_me)
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
        print("Type: "+item[2])
        only_links = item[1][3]
        post_count = str(item[1][4])
        item[1].append(username)
        item[1].pop(3)
        api_type = item[2]
        results = prepare_scraper(
            session, site_name, only_links, *item[1], api_type, app_token)
        for result in results[0]:
            if not only_links:
                media_set = result
                if not media_set["valid"]:
                    continue
                directory = results[1]
                location = result["type"]
                prep_download.append(
                    [media_set["valid"], session, directory, username, post_count, location, api_type])
    # When profile is done scraping, this function will return True
    print("Scrape Completed"+"\n")
    return [True, prep_download]


def link_check(session, app_token, identifier):
    link = 'https://onlyfans.com/api2/v2/users/' + str(identifier) + \
           '?app-token=' + app_token
    y = json_request(session, link)
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


def scrape_choice(user_id, app_token, post_counts, is_me):
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
    array = [s_array, h_array, p_array, a_array, mm_array, m_array]
    # array = [s_array, h_array, p_array, a_array, m_array]
    # array = [p_array]
    # array = [a_array]
    # array = [mm_array]
    # array = [m_array]
    # new = dict()
    # for xxx in array:
    #     new["api_message"] = xxx[0]
    #     new["api_array"] = xxx[1]
    #     new["api_type"] = xxx[2]
    #     print
    if not is_me:
        if len(array) > 3:
            del array[4]
    valid_input = False
    if input_choice == "a":
        valid_input = True
        for item in array:
            a = []
            for z in item[1][1]:
                if z == "Images":
                    a.append([z, [y[0]]])
                if z == "Videos":
                    a.append([z, y[1:4]])
                if z == "Audios":
                    a.append([z, [y[4]]])
            item[0] = array[0][0].format("all")
            item[1][1] = a
    if input_choice == "b":
        name = "Images"
        for item in array:
            item[0] = item[0].format(name)
            item[1][1] = [[name, [y[0]]]]
        valid_input = True
    if input_choice == "c":
        name = "Videos"
        for item in array:
            item[0] = item[0].format(name)
            item[1][1] = [[name, y[1:4]]]
        valid_input = True
    if input_choice == "d":
        name = "Audios"
        for item in array:
            item[0] = item[0].format(name)
            item[1][1] = [[name, [y[4]]]]
        valid_input = True
    if valid_input:
        return array
    else:
        print("Invalid Choice")
    return []


def media_scraper(link, session, directory, username, api_type):
    media_set = [[], []]
    media_type = directory[-1]
    y = json_request(session, link)
    if not y or "error" in y:
        return media_set
    x = 0
    if api_type == "Highlights":
        y = y["stories"]
    if api_type == "Messages":
        y = y["list"]
    if api_type == "Mass Messages":
        y = y["list"]
    master_date = "01-01-0001 00:00:00"
    for media_api in y:
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
            text = clean_text(text)
            new_dict["postedAt"] = date_string
            post_id = new_dict["post_id"]
            media_id = new_dict["media_id"]
            file_name = link.rsplit('/', 1)[-1]
            file_name, ext = os.path.splitext(file_name)
            ext = ext.__str__().replace(".", "").split('?')[0]
            file_path = reformat(directory[0][1], post_id, media_id, file_name,
                                 text, ext, date_object, username, format_path, date_format, maximum_length)
            new_dict["text"] = text
            new_dict["paid"] = False
            if new_dict["price"]:
                if api_type in ["Messages", "Mass Messages"]:
                    new_dict["paid"] = True
                else:
                    if media["id"] not in media_api["preview"] and media["canView"]:
                        new_dict["paid"] = True
            new_dict["directory"] = os.path.join(directory[0][1])
            if sort_free_paid_posts:
                new_dict["directory"] = os.path.join(directory[1][1])
                if new_dict["paid"]:
                    new_dict["directory"] = os.path.join(directory[2][1])
            new_dict["filename"] = file_path.rsplit('/', 1)[-1]
            new_dict["size"] = size
            if size == 0:
                media_set[1].append(new_dict)
                continue
            media_set[0].append(new_dict)
    return media_set


def prepare_scraper(session, site_name, only_links, link, locations, directory, api_count, username, api_type, app_token):
    seperator = " | "
    user_directory = ""
    metadata_directory = ""
    master_set = []
    media_set = []
    metadata_set = []
    original_link = link
    for location in locations:
        pool = ThreadPool()
        link = original_link
        print("Scraping ["+str(seperator.join(location[1])) +
              "]. Should take less than a minute.")
        array = format_directory(
            j_directory, site_name, username, location[0], api_type)
        user_directory = array[0]
        location_directory = array[2][0][1]
        metadata_directory = array[1]
        directories = array[2]+[location[1]]
        if not master_set:
            if api_type == "Posts":
                num = 100
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
                    y = json_request(session, link)
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
                        y = json_request(session, link)
                        if y and "error" not in y:
                            return y
                        else:
                            return []
                    link_list = [link.replace(
                        "offset=0", "offset="+str(i*30)) for i in range(offset_count, offset_count2)]
                    link_list = pool.starmap(process_messages, product(
                        link_list, [session]))
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
                    y = json_request(session, link_2)
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
                r = json_request(session, link)
                if "error" in r:
                    break
                for item in r:
                    link2 = "https://onlyfans.com/api2/v2/stories/highlights/" + \
                        str(item["id"])+"?app-token="+app_token+""
                    master_set.append(link2)
        x = pool.starmap(media_scraper, product(
            master_set, [session], [directories], [username], [api_type]))
        print
        results = format_media_set(location[0], x)
        seen = set()
        results["valid"] = [x for x in results["valid"]
                            if x["filename"] not in seen and not seen.add(x["filename"])]
        seen = set()
        location_directories = [x["directory"] for x in results["valid"]
                                if x["directory"] not in seen and not seen.add(x["directory"])]
        if results["valid"]:
            results["valid"] = [list(g) for k, g in groupby(
                results["valid"], key=lambda x: x["post_id"])]
            os.makedirs(directory, exist_ok=True)
            for location_directory in location_directories:
                os.makedirs(location_directory, exist_ok=True)
        if results["invalid"]:
            results["invalid"] = [list(g) for k, g in groupby(
                results["invalid"], key=lambda x: x["post_id"])]
        if sort_free_paid_posts:
            ofsorter.sorter(user_directory, api_type, location[0], results)
        metadata_set.append(results)
        media_set.append(results)

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
            export_archive(metadata_set, archive_directory, json_settings)
    return [media_set, directory]


def download_media(media_set, session, directory, username, post_count, location, api_type):
    def download(medias, session, directory, username):
        return_bool = True
        for media in medias:
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
                download_path = media["directory"]+media["filename"]
                timestamp = date_object.timestamp()
                if not overwrite_files:
                    if check_for_dupe_file(download_path, content_length):
                        format_image(download_path, timestamp)
                        return_bool = False
                        count += 1
                        break
                r = json_request(session, link, stream=True, json_format=False)
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


def create_session(custom_proxy="",test_ip=True):
    for proxy2 in proxy:
        max_threads = multiprocessing.cpu_count()
        session = requests.Session()
        proxy2 = custom_proxy if custom_proxy else proxy2
        proxies = {'http': 'socks5h://'+proxy2,
                'https': 'socks5h://'+proxy2}
        if proxy2:
            session.proxies = proxies
            if cert:
                session.verify = cert
        session.mount(
            'https://', HTTPAdapter(pool_connections=max_threads, pool_maxsize=max_threads))
        if test_ip:
            link = 'https://checkip.amazonaws.com'
            r = json_request(session, link, json_format=False)
            if not r:
                continue
            ip = r.text.strip()
            print("Session IP: "+ip)
        return session


def get_paid_posts(session, app_token):
    paid_api = "https://onlyfans.com/api2/v2/posts/paid?limit=100&offset=0&app-token="+app_token+""
    directory = []
    directory.append
    x = media_scraper(paid_api, session)
    print


def create_auth(session, user_agent, app_token, auth_array, max_auth=2):
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
            session.headers = {
                'User-Agent': user_agent, 'Referer': 'https://onlyfans.com/'}
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
                a = [session, link, sess, user_agent]
                session = create_sign(*a)
                r = json_request(session, link)
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
                                    r = json_request(
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
                r = json_request(session, link)
                if not r:
                    break
                array = dict()
                array["session"] = session
                array["option_string"] = option_string
                array["subscriber_count"] = r["subscriptions"]["active"]
                array["me_api"] = me_api
                return array
            auth_count += 1
    except Exception as e:
        log_error.exception(e)
    array = dict()
    array["session"] = None
    array["me_api"] = me_api
    return array


def get_subscriptions(session, app_token, subscriber_count, me_api, auth_count=0):
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
        r = json_request(session, link)
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
        r = json_request(session, link)
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
                r = json_request(session, link)
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


def format_options(array, choice_type):
    string = ""
    names = []
    array = [{"auth_count": -1, "username": "All"}]+array
    name_count = len(array)
    if "usernames" == choice_type:
        if name_count > 1:

            count = 0
            for x in array:
                name = x["username"]
                string += str(count)+" = "+name
                names.append([x["auth_count"], name])
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
