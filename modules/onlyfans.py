import requests
from bs4 import BeautifulSoup
from urllib.request import urlretrieve
from win32_setctime import setctime

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
import time
import math

# Open config.json and fill in OPTIONAL information
json_config = json.load(open('config.json'))
json_settings = json_config["settings"]
j_directory = json_settings['directory'] + "/users/"
format_path = json_settings['file_name_format']
auto_choice = json_settings["auto_choice"]
overwrite_files = json_settings["overwrite_files"]
date_format = json_settings["date_format"]

session = requests.Session()
username = ''


def start_datascraper(app_token, user_agent, sess, username2):
    auth_cookie = {
        'domain': '.onlyfans.com',
        'expires': None,
        'name': 'sess',
        'path': '/',
        'value': sess,
        'version': 0
    }
    session.cookies.set(**auth_cookie)
    session.headers = {
        'User-Agent': user_agent, 'Referer': 'https://onlyfans.com/'}
    logging.basicConfig(filename='errors.log', level=logging.ERROR,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')

    global username
    username = username2
    user_id = link_check(app_token)
    if not user_id[0]:
        print(user_id[1])
        print("First time? Did you forget to edit your config.json file?")
        return

    post_count = user_id[2]
    user_id = user_id[1]
    scrape_choice(user_id, app_token, post_count)
    print('Task Completed!')


def link_check(app_token):
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
        temp_user_id2[2] = y["postsCount"]
        return temp_user_id2


def scrape_choice(user_id, app_token, post_count):
    if auto_choice:
        input_choice = auto_choice
    else:
        print('Scrape: a = Everything | b = Images | c = Videos')
        print('Optional Arguments: -l = Only scrape links -()- Example: "a -l"')
        input_choice = input().strip()
    image_api = "https://onlyfans.com/api2/v2/users/"+user_id+"/posts/photos?limit=100&offset=0&order=publish_date_" \
                                                              "desc&app-token="+app_token+""
    video_api = "https://onlyfans.com/api2/v2/users/"+user_id+"/posts/videos?limit=100&offset=0&order=publish_date_" \
                                                              "desc&app-token="+app_token+""
    # ARGUMENTS
    only_links = False
    if "-l" in input_choice:
        only_links = True
        input_choice = input_choice.replace(" -l", "")
    mandatory = [j_directory, only_links, post_count]
    i_array = ["You have chosen to scrape images", [image_api, 'Images', *mandatory], 'Images Completed']
    v_array = ["You have chosen to scrape videos", [video_api, 'Videos', *mandatory], 'Videos Completed']
    array = [i_array] + [v_array]
    if input_choice == "a":
        for item in array:
            print(item[0])
            media_scraper(*item[1])
            print(item[2])
        return
    if input_choice == "b":
        item = array[0]
        print(item[0])
        media_scraper(*item[1])
        print(item[2])
        return
    if input_choice == "c":
        item = array[1]
        print(item[0])
        media_scraper(*item[1])
        print(item[2])
        return
    print("Invalid Choice")
    return


def reformat(directory2, file_name2, text, ext, date):
    path = format_path.replace("{username}", username)
    text = BeautifulSoup(text, 'html.parser').get_text().replace("\n", " ").strip()
    filtered_text = re.sub(r'[\\/*?:"<>|]', '', text)
    path = path.replace("{text}", filtered_text)
    date = date.strftime(date_format)
    path = path.replace("{date}", date)
    path = path.replace("{file_name}", file_name2)
    path = path.replace("{ext}", ext)
    directory2 += path
    count_string = len(directory2)
    if count_string > 260:
        num_sum = count_string - 260
        directory2 = directory2.replace(text, text[:-num_sum])

    return directory2


def scrape_array(link):
    media_set = []
    master_date = "00-00-0000"
    r = session.get(link)
    y = json.loads(r.text)
    if not y:
        return
    for media_api in y:
        for media in media_api["media"]:
            if "source" in media:
                file = media["source"]["source"]
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
                media_set.append(new_dict)
    return media_set


def media_scraper(link, location, directory, only_links, post_count):
    max_threads = multiprocessing.cpu_count()
    pool = ThreadPool(max_threads)
    floor = math.floor(post_count / 100)
    if floor == 0:
        floor = 1
    a = list(range(floor))
    offset_array = []
    for b in a:
        b = b * 100
        offset_array.append(link.replace("offset=0", "offset=" + str(b)))
    media_set = pool.starmap(scrape_array, product(offset_array))
    media_set = [x for x in media_set if x is not None]
    media_set = list(chain.from_iterable(media_set))
    if "/users/" == directory:
        directory = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))+"/users/"+username+"/"+location+"/"
    else:
        directory = directory+username+"/"+location+"/"

    print("DIRECTORY - " + directory)
    if not os.path.exists(directory):
        os.makedirs(directory)

    with open(directory+'links.json', 'w') as outfile:
        json.dump(media_set, outfile)
    if not only_links:
        pool.starmap(download_media, product(media_set, [directory]))


def download_media(media, directory):
    while True:
        link = media["link"]
        r = session.head(link)
        if r.status_code != 200:
            return
        file_name = link.rsplit('/', 1)[-1]
        result = file_name.split("_", 1)
        if len(result) > 1:
            file_name = result[1]
        else:
            file_name = result[0]

        file_name, ext = os.path.splitext(file_name)
        ext = ext.replace(".", "")
        date_object = datetime.strptime(media["postedAt"], "%d-%m-%Y %H:%M:%S")
        directory = reformat(directory, file_name, media["text"], ext, date_object)
        timestamp = date_object.timestamp()
        if not overwrite_files:
            if os.path.isfile(directory):
                return
        urlretrieve(link, directory)
        setctime(directory, timestamp)
        print(link)
        return
