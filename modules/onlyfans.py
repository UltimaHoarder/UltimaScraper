import requests
from bs4 import BeautifulSoup
from win32_setctime import setctime
from modules.helpers import reformat
from modules.helpers import format_media_set

import os
import json
from itertools import product
from itertools import chain
import multiprocessing
from multiprocessing import current_process, Pool
from multiprocessing.dummy import Pool as ThreadPool
from datetime import datetime
import re
import logging
import inspect
import math
import platform

# Open config.json and fill in OPTIONAL information
json_config = json.load(open('config.json'))
json_global_settings = json_config["settings"]
auto_choice = json_global_settings["auto_choice"]
multithreading = json_global_settings["multithreading"]
json_settings = json_config["supported"]["onlyfans"]["settings"]
j_directory = json_settings['directory'] + "/sites/"
format_path = json_settings['file_name_format']
overwrite_files = json_settings["overwrite_files"]
date_format = json_settings["date_format"]
ignored_keywords = json_settings["ignored_keywords"]
maximum_length = 240
text_length = int(json_settings["text_length"]
                  ) if json_settings["text_length"] else maximum_length
if text_length > maximum_length:
    text_length = maximum_length

max_threads = multiprocessing.cpu_count()


def start_datascraper(session, username, site_name, app_token):
    logging.basicConfig(
        filename='errors.log',
        level=logging.ERROR,
        format='%(asctime)s %(levelname)s %(name)s %(message)s')
    user_id = link_check(session, app_token, username)
    if not user_id[0]:
        print(user_id[1])
        print("First time? Did you forget to edit your config.json file?")
        return [False]

    post_count = user_id[2]
    user_id = user_id[1]
    array = scrape_choice(user_id, app_token, post_count)
    link_array = {}
    for item in array:
        item[1].append(username)
        only_links = item[1][4]
        item[1].pop(3)
        response = media_scraper(session, site_name, only_links, *item[1])
        link_array[item[1][1].lower()] = response[0]
        if not only_links:
            media_set = response[0]
            directory = response[1]
            if multithreading:
                pool = ThreadPool(max_threads)
            else:
                pool = ThreadPool(1)
            pool.starmap(download_media, product(
                media_set["valid"], [session], [directory], [username]))
    # When profile is done scraping, this function will return True
    return [True, link_array]


def link_check(session, app_token, username):
    link = 'https://onlyfans.com/api2/v2/users/' + username + \
           '&app-token=' + app_token
    r = session.get(link)
    y = json.loads(r.text)
    temp_user_id2 = dict()
    if not y:
        temp_user_id2[0] = False
        temp_user_id2[1] = "No users found"
        return temp_user_id2
    if "error" in y:
        temp_user_id2[0] = False
        temp_user_id2[1] = y["error"]["message"]
        return temp_user_id2

    subbed = y["subscribedBy"]
    if not subbed:
        temp_user_id2[0] = False
        temp_user_id2[1] = "You're not subscribed to the user"
        return temp_user_id2
    else:
        temp_user_id2[0] = True
        temp_user_id2[1] = str(y["id"])
        temp_user_id2[2] = [y["photosCount"],
                            y["videosCount"], y["audiosCount"]]
        return temp_user_id2


def scrape_choice(user_id, app_token, post_count):
    if auto_choice:
        input_choice = auto_choice
    else:
        print('Scrape: a = Everything | b = Images | c = Videos | d = Audios')
        print('Optional Arguments: -l = Only scrape links -()- Example: "a -l"')
        input_choice = input().strip()
    image_api = "https://onlyfans.com/api2/v2/users/"+user_id + \
        "/posts/photos?limit=100&offset=0&order=publish_date_desc&app-token="+app_token+""
    video_api = "https://onlyfans.com/api2/v2/users/"+user_id + \
        "/posts/videos?limit=100&offset=0&order=publish_date_desc&app-token="+app_token+""
    audio_api = "https://onlyfans.com/api2/v2/users/"+user_id + \
        "/posts/audios?limit=100&offset=0&order=publish_date_desc&app-token="+app_token+""
    # ARGUMENTS
    only_links = False
    if "-l" in input_choice:
        only_links = True
        input_choice = input_choice.replace(" -l", "")
    mandatory = [j_directory, only_links]
    i_array = ["You have chosen to scrape images", [
        image_api, 'Images', "photo", *mandatory, post_count[0]], 'Images Completed']
    v_array = ["You have chosen to scrape videos", [
        video_api, 'Videos', "video", *mandatory, post_count[1]], 'Videos Completed']
    a_array = ["You have chosen to scrape audio", [
        audio_api, 'Audios', "audio", *mandatory, post_count[2]], 'Audios Completed']
    array = [i_array] + [v_array] + [a_array]
    valid_input = False
    if input_choice == "a":
        valid_input = True
    if input_choice == "b":
        array = [array[0]]
        valid_input = True
    if input_choice == "c":
        array = [array[1]]
        valid_input = True
    if input_choice == "d":
        array = [array[2]]
        valid_input = True
    if valid_input:
        return array
    else:
        print("Invalid Choice")
    return False


def scrape_array(link, session, media_type):
    media_set = [[],[]]
    master_date = "00-00-0000"
    count = 0
    found = False
    while count < 10:
        r = session.get(link)
        y = json.loads(r.text)
        if not y:
            count += 1
            continue
        found = True
        break
    if not found:
        return media_set
    x = 0
    for media_api in y:
        for media in media_api["media"]:
            if media["type"] != media_type:
                x += 1
                continue
            if "source" in media:
                source = media["source"]
                file = source["source"]
                if not file:
                    continue
                if "ca2.convert" in file:
                    file = media["preview"]
                new_dict = dict()
                new_dict["post_id"] = media_api["id"]
                new_dict["link"] = file
                if media_api["postedAt"] == "-001-11-30T00:00:00+00:00":
                    dt = master_date
                else:
                    dt = datetime.fromisoformat(media_api["postedAt"]).replace(tzinfo=None).strftime(
                        "%d-%m-%Y %H:%M:%S")
                    master_date = dt
                new_dict["text"] = media_api["text"]
                new_dict["postedAt"] = dt

                if source["size"] == 0:
                    media_set[1].append(new_dict)
                    continue
                media_set[0].append(new_dict)
    return media_set


def media_scraper(session, site_name, only_links, link, location, media_type, directory, post_count, username):
    print("Scraping "+location+". Should take less than a minute.")
    pool = ThreadPool(max_threads)
    ceil = math.ceil(post_count / 100)
    a = list(range(ceil))
    offset_array = []
    for b in a:
        b = b * 100
        offset_array.append(link.replace("offset=0", "offset=" + str(b)))
    media_set = format_media_set(pool.starmap(scrape_array, product(
        offset_array, [session], [media_type])))
    directory = j_directory
    if post_count:
        user_directory = directory+"/"+site_name + "/"+username+"/"
        metadata_directory = user_directory+"/metadata/"
        directory = user_directory + location+"/"
        if "/sites/" == j_directory:
            user_directory = os.path.dirname(os.path.dirname(
                os.path.realpath(__file__))) + user_directory
            metadata_directory = os.path.dirname(os.path.dirname(
                os.path.realpath(__file__))) + metadata_directory
            directory = os.path.dirname(os.path.dirname(
                os.path.realpath(__file__))) + directory

        if not only_links:
            print("DIRECTORY - " + directory)
            os.makedirs(directory, exist_ok=True)
        os.makedirs(metadata_directory, exist_ok=True)

        with open(metadata_directory+location+".json", 'w') as outfile:
            json.dump(media_set, outfile)
    return [media_set, directory]


def download_media(media, session, directory, username):
    while True:
        link = media["link"]
        r = session.head(link)
        file_name = link.rsplit('/', 1)[-1]
        result = file_name.split("_", 1)
        if len(result) > 1:
            file_name = result[1]
        else:
            file_name = result[0]

        file_name, ext = os.path.splitext(file_name)
        ext = ext.replace(".", "")
        date_object = datetime.strptime(media["postedAt"], "%d-%m-%Y %H:%M:%S")
        directory = reformat(directory, file_name,
                             media["text"], ext, date_object, username, format_path, date_format, text_length, maximum_length)
        timestamp = date_object.timestamp()
        if not overwrite_files:
            if os.path.isfile(directory):
                return
        if not os.path.exists(os.path.dirname(directory)):
            os.makedirs(os.path.dirname(directory))
        r = session.get(link, stream=True)
        with open(directory, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)
        os_name = platform.system()
        if os_name == "Windows":
            setctime(directory, timestamp)
        print(link)
        return True


def show_error(error):
    print(error["error"]["message"])
    return


def create_session(user_agent, auth_id, auth_hash, app_token):
    session = requests.Session()
    session.headers = {
        'User-Agent': user_agent, 'Referer': 'https://onlyfans.com/'}
    auth_cookies = [
        {'name': 'auth_id', 'value': auth_id},
        {'name': 'auth_hash', 'value': auth_hash},
        {'name': 'sess', 'value': 'None'}
    ]
    for auth_cookie in auth_cookies:
        session.cookies.set(**auth_cookie)
    session.head("https://onlyfans.com")
    response = json.loads(session.get(
        "https://onlyfans.com/api2/v2/users/me?app-token="+app_token).text)
    if 'error' in response:
        show_error(response)
        return False
    else:
        print("Welcome "+response["name"])
    option_string = "username or profile link"
    return [session, option_string]


def get_subscriptions(session, app_token):
    response = json.loads(session.get("https://onlyfans.com/api2/v2/subscriptions/subscribes?limit=100&offset=0&type="
                                      "active&app-token="+app_token).text)
    if 'error' in response:
        print("Invalid App Token")
        return False
    else:
        return response
