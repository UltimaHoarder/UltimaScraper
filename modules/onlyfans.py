import requests
from modules.helpers import get_directory, json_request, reformat, format_directory, format_media_set, export_archive, format_image

import os
import json
from itertools import product
from itertools import chain
import multiprocessing
from multiprocessing.dummy import Pool as ThreadPool
from datetime import datetime
import logging
import math

logger = logging.getLogger(__name__)

# Open config.json and fill in OPTIONAL information
path = os.path.join('settings', 'config.json')
json_config = json.load(open(path))
json_global_settings = json_config["settings"]
multithreading = json_global_settings["multithreading"]
json_settings = json_config["supported"]["onlyfans"]["settings"]
auto_choice = json_settings["auto_choice"]
j_directory = get_directory(json_settings['directory'])
format_path = json_settings['file_name_format']
overwrite_files = json_settings["overwrite_files"]
date_format = json_settings["date_format"]
ignored_keywords = json_settings["ignored_keywords"]
ignore_unfollowed_accounts = json_settings["ignore_unfollowed_accounts"]
export_metadata = json_settings["export_metadata"]
maximum_length = 240
text_length = int(json_settings["text_length"]
                  ) if json_settings["text_length"] else maximum_length
if text_length > maximum_length:
    text_length = maximum_length


def start_datascraper(session, identifier, site_name, app_token):
    print("Scrape Processing")
    info = link_check(session, app_token, identifier)
    if not info["subbed"]:
        print(info["user"])
        print("First time? Did you forget to edit your config.json file?")
        return [False, []]
    user = info["user"]
    post_counts = info["count"]
    user_id = str(user["id"])
    username = user["username"]
    print("Name: "+username)
    array = scrape_choice(user_id, app_token, post_counts)
    prep_download = []
    for item in array:
        print("Type: "+item[2])
        only_links = item[1][3]
        post_count = str(item[1][4])
        item[1].append(username)
        item[1].pop(3)
        api_type = item[2]
        results = media_scraper(
            session, site_name, only_links, *item[1], api_type, app_token)
        for result in results[0]:
            if not only_links:
                media_set = result
                if not media_set["valid"]:
                    continue
                directory = results[1]
                location = result["type"]
                prep_download.append(
                    [media_set["valid"], session, directory, username, post_count, location])
    # When profile is done scraping, this function will return True
    print("Scrape Completed"+"\n")
    return [True, prep_download]


def link_check(session, app_token, identifier):
    link = 'https://onlyfans.com/api2/v2/users/' + str(identifier) + \
           '&app-token=' + app_token
    y = json_request(session, link)
    temp_user_id2 = dict()
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
    if not subbed:
        temp_user_id2["subbed"] = False
        temp_user_id2["user"] = "You're not subscribed to the user"
        return temp_user_id2
    else:
        temp_user_id2["subbed"] = True
        temp_user_id2["user"] = y
        temp_user_id2["count"] = [y["postsCount"], [y["photosCount"],
                                                    y["videosCount"], y["audiosCount"]]]
        return temp_user_id2


def scrape_choice(user_id, app_token, post_counts):
    post_count = post_counts[0]
    media_counts = post_counts[1]
    x = ["Images", "Videos", "Audios"]
    x = dict(zip(x, media_counts))
    x = [k for k, v in x.items() if v != 0]
    if auto_choice:
        input_choice = auto_choice
    else:
        print('Scrape: a = Everything | b = Images | c = Videos | d = Audios')
        input_choice = input().strip()
    message_api = "https://onlyfans.com/api2/v2/chats/"+user_id + \
        "/messages?limit=100&offset=0&order=desc&app-token="+app_token+""
    stories_api = "https://onlyfans.com/api2/v2/users/"+user_id + \
        "/stories?limit=100&offset=0&order=desc&app-token="+app_token+""
    hightlights_api = "https://onlyfans.com/api2/v2/users/"+user_id + \
        "/stories/highlights?limit=100&offset=0&order=desc&app-token="+app_token+""
    post_api = "https://onlyfans.com/api2/v2/users/"+user_id + \
        "/posts?limit=100&offset=0&order=publish_date_desc&app-token="+app_token+""
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
    m_array = ["You have chosen to scrape {}", [
        message_api, x, *mandatory, post_count], "Messages"]
    array = [s_array, h_array, p_array, m_array]
    valid_input = False
    if input_choice == "a":
        valid_input = True
        a = []
        for z in x:
            if z == "Images":
                a.append([z, [y[0]]])
            if z == "Videos":
                a.append([z, y[1:4]])
            if z == "Audios":
                a.append([z, [y[4]]])
        for item in array:
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


def scrape_array(link, session, directory, username, api_type):
    media_set = [[], []]
    media_type = directory[1]
    count = 0
    found = False
    y = json_request(session, link)
    if "error" in y:
        return media_set
    x = 0
    if api_type == "Highlights":
        y = y["stories"]
    if api_type == "Messages":
        y = y["list"]
    master_date = "01-01-0001 00:00:00"
    for media_api in y:
        for media in media_api["media"]:
            date = "-001-11-30T00:00:00+00:00"
            size = 0
            if "source" in media:
                source = media["source"]
                link = source["source"]
                size = source["size"]
                date = media_api["postedAt"] if "postedAt" in media_api else media_api["createdAt"]
            if "src" in media:
                link = media["src"]
                size = media["info"]["preview"]["size"] if "info" in media_api else 1
                date = media_api["createdAt"]
            if not link:
                continue
            if "ca2.convert" in link:
                link = media["preview"]
            new_dict = dict()
            new_dict["post_id"] = media_api["id"]
            new_dict["link"] = link
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
            if "text" not in media_api:
                media_api["text"] = ""
            new_dict["text"] = media_api["text"] if media_api["text"] else ""
            new_dict["postedAt"] = date_string
            file_name = link.rsplit('/', 1)[-1]
            file_name, ext = os.path.splitext(file_name)
            ext = ext.__str__().replace(".", "").split('?')[0]
            file_path = reformat(directory[0][1], file_name,
                                 new_dict["text"], ext, date_object, username, format_path, date_format, text_length, maximum_length)
            new_dict["directory"] = directory[0][1]
            new_dict["filename"] = file_path.rsplit('/', 1)[-1]
            new_dict["size"] = size
            if size == 0:
                media_set[1].append(new_dict)
                continue
            media_set[0].append(new_dict)
    return media_set


def media_scraper(session, site_name, only_links, link, locations, directory, post_count, username, api_type, app_token):
    seperator = " | "
    media_set = []
    original_link = link
    for location in locations:
        link = original_link
        print("Scraping ["+str(seperator.join(location[1])) +
              "]. Should take less than a minute.")
        array = format_directory(
            j_directory, site_name, username, location[0], api_type)
        user_directory = array[0]
        location_directory = array[2][0][1]
        metadata_directory = array[1]
        directories = array[2]+[location[1]]

        pool = ThreadPool()
        ceil = math.ceil(post_count / 100)
        a = list(range(ceil))
        offset_array = []
        if api_type == "Posts":
            for b in a:
                b = b * 100
                offset_array.append(link.replace(
                    "offset=0", "offset=" + str(b)))
        if api_type == "Messages":
            offset_count = 0
            while True:
                y = json_request(session, link)
                if "list" in y:
                    if y["list"]:
                        offset_array.append(link)
                        if y["hasMore"]:
                            offset_count2 = offset_count+100
                            offset_count = offset_count2-100
                            link = link.replace(
                                "offset=" + str(offset_count), "offset=" + str(offset_count2))
                            offset_count = offset_count2
                        else:
                            break
                    else:
                        break
                else:
                    break
        if api_type == "Stories":
            offset_array.append(link)
        if api_type == "Highlights":
            r = json_request(session, link)
            if "error" in r:
                break
            for item in r:
                link2 = "https://onlyfans.com/api2/v2/stories/highlights/" + \
                    str(item["id"])+"?app-token="+app_token+""
                offset_array.append(link2)
        x = pool.starmap(scrape_array, product(
            offset_array, [session], [directories], [username], [api_type]))
        results = format_media_set(location[0], x)
        if results["valid"]:
            os.makedirs(directory, exist_ok=True)
            os.makedirs(location_directory, exist_ok=True)
            if export_metadata:
                os.makedirs(metadata_directory, exist_ok=True)
                archive_directory = metadata_directory+location[0]
                export_archive(results, archive_directory)
        media_set.append(results)

    return [media_set, directory]


def download_media(media_set, session, directory, username, post_count, location):
    def download(media, session, directory, username):
        count = 0
        while count < 11:
            link = media["link"]
            r = json_request(session, link, "HEAD", True, False)
            if not r:
                return False

            header = r.headers
            content_length = int(header["content-length"])
            date_object = datetime.strptime(
                media["postedAt"], "%d-%m-%Y %H:%M:%S")
            og_filename = media["filename"]
            media["ext"] = os.path.splitext(og_filename)[1]
            media["ext"] = media["ext"].replace(".", "")
            download_path = media["directory"]+media["filename"]
            timestamp = date_object.timestamp()
            if not overwrite_files:
                if os.path.isfile(download_path):
                    local_size = os.path.getsize(download_path)
                    if local_size == content_length:
                        return
            r = json_request(session, link, "GET", True, False)
            if not r:
                return False
            try:
                with open(download_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:  # filter out keep-alive new chunks
                            f.write(chunk)
            except (ConnectionResetError):
                count += 1
                continue
            format_image(download_path, timestamp)
            logger.info("Link: {}".format(link))
            logger.info("Path: {}".format(download_path))
            return True
    print("Download Processing")
    print("Name: "+username+" | Directory: " + directory)
    print("Downloading "+str(len(media_set))+" "+location+"\n")
    if multithreading:
        pool = ThreadPool()
    else:
        pool = ThreadPool(1)
    pool.starmap(download, product(
        media_set, [session], [directory], [username]))


def create_session(user_agent, app_token, auth_array):
    me_api = []
    auth_count = 1
    auth_version = "(V1)"
    count = 1
    auth_cookies = [
        {'name': 'auth_id', 'value': auth_array["auth_id"]},
        {'name': 'auth_hash', 'value': auth_array["auth_hash"]}
    ]
    while auth_count < 3:
        if auth_count == 2:
            auth_version = "(V2)"
            if auth_array["sess"]:
                del auth_cookies[2]
            count = 1
        while count < 11:
            session = requests.Session()
            print("Auth "+auth_version+" Attempt "+str(count)+"/"+"10")
            max_threads = multiprocessing.cpu_count()
            session.mount(
                'https://', requests.adapters.HTTPAdapter(pool_connections=max_threads, pool_maxsize=max_threads))
            session.headers = {
                'User-Agent': user_agent, 'Referer': 'https://onlyfans.com/', "accept": "application/json, text/plain, */*"}
            if auth_array["sess"]:
                auth_cookies.append(
                    {'name': 'sess', 'value': auth_array["sess"]})
            for auth_cookie in auth_cookies:
                session.cookies.set(**auth_cookie)

            link = "https://onlyfans.com/api2/v2/users/customer?app-token="+app_token

            # r = json_request(session, link, "HEAD", True, False)
            r = json_request(session, link, json_format=True)
            count += 1
            if not r:
                continue
            me_api = r
            if 'error' in r:
                error_message = r["error"]["message"]
                print(error_message)
                if "token" in error_message:
                    break
                continue
            else:
                print("Welcome "+r["name"])
            option_string = "username or profile link"
            link = "https://onlyfans.com/api2/v2/subscriptions/count/all?app-token="+app_token
            r = json_request(session, link)
            if not r:
                break
            subscriber_count = r["subscriptions"]["all"]
            return [session, option_string, subscriber_count, me_api]
        auth_count += 1
    return [False, me_api]


def get_subscriptions(session, app_token, subscriber_count, me_api, auth_count=0):
    link = "https://onlyfans.com/api2/v2/subscriptions/subscribes?limit=99&offset=0&app-token="+app_token
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
        if performer:
            session = requests.Session()
            x = json_request(session, link)
            if not x["subscribedByData"]:
                x["subscribedByData"] = dict()
                x["subscribedByData"]["expiredAt"] = datetime.utcnow().isoformat()
                x["subscribedByData"]["price"] = x["subscribePrice"]
                x["subscribedByData"]["subscribePrice"] = 0
            x = [x]
        else:
            x = json_request(session, link)
        return x
    link_count = len(offset_array) if len(offset_array) > 0 else 1
    pool = ThreadPool(link_count)
    results = pool.starmap(multi, product(
        offset_array, [session]))
    results = list(chain(*results))
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
            subscribedBy = result["subscribedBy"]
            subscribedByData = result["subscribedByData"]
            result_date = subscribedByData["expiredAt"] if subscribedByData else datetime.utcnow(
            ).isoformat()
            price = subscribedByData["price"]
            subscribePrice = subscribedByData["subscribePrice"]
            result_date = datetime.fromisoformat(
                result_date).replace(tzinfo=None).date()
            if result_date >= now:
                if not subscribedBy:
                    if ignore_unfollowed_accounts in ["all", "paid"]:
                        if price > 0:
                            continue
                    if ignore_unfollowed_accounts in ["all", "free"]:
                        if subscribePrice == 0:
                            continue
                results2.append(result)
        return results2


def format_options(array):
    string = ""
    names = []
    array = [{"auth_count": -1, "username": "All"}]+array
    name_count = len(array)
    if name_count > 1:

        count = 0
        for x in array:
            name = x["username"]
            string += str(count)+" = "+name
            names.append([x["auth_count"], name])
            if count+1 != name_count:
                string += " | "

            count += 1
    return [names, string]
