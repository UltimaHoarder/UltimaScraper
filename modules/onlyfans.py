import requests
from bs4 import BeautifulSoup
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
import math
import platform

# Open config.json and fill in OPTIONAL information
json_config = json.load(open('config.json'))
json_settings = json_config["settings"]
j_directory = json_settings['directory'] + "/users/"
format_path = json_settings['file_name_format']
auto_choice = json_settings["auto_choice"]
overwrite_files = json_settings["overwrite_files"]
date_format = json_settings["date_format"]
multithreading = json_settings["multithreading"]

max_threads = multiprocessing.cpu_count()


def start_datascraper(session, username, app_token):
    logging.basicConfig(filename='errors.log', level=logging.ERROR,
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
        only_links = item[1][3]
        item[1].pop(3)
        response = media_scraper(session, *item[1])
        link_array[item[1][1].lower()] = response[0]
        if not only_links:
            media_set = response[0]
            directory = response[1]
            if multithreading:
                pool = ThreadPool(max_threads)
            else:
                pool = ThreadPool(1)
            pool.starmap(download_media, product(media_set, [session], [directory], [username]))

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
    valid_input = False
    if input_choice == "a":
        valid_input = True
    if input_choice == "b":
        array = [array[0]]
        valid_input = True
    if input_choice == "c":
        array = [array[1]]
        valid_input = True
    if valid_input:
        return array
    else:
        print("Invalid Choice")
    return False


def scrape_array(link, session):
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
                if not file:
                    return
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


def media_scraper(session, link, location, directory, post_count, username):
    print("Scraping "+location+". Should take less than a minute.")
    pool = ThreadPool(max_threads)
    floor = math.floor(post_count / 100)
    if floor == 0:
        floor = 1
    a = list(range(floor))
    offset_array = []
    for b in a:
        b = b * 100
        offset_array.append(link.replace("offset=0", "offset=" + str(b)))
    media_set = pool.starmap(scrape_array, product(offset_array, [session]))
    media_set = [x for x in media_set if x is not None]
    media_set = list(chain.from_iterable(media_set))
    if "/users/" == directory:
        directory = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))+"/users/onlyfans/"+username+"/"\
                    + location+"/"
    else:
        directory = directory+username+"/"+location+"/"

    print("DIRECTORY - " + directory)
    if not os.path.exists(directory):
        os.makedirs(directory)

    with open(directory+'links.json', 'w') as outfile:
        json.dump(media_set, outfile)
    return [media_set, directory]


def download_media(media, session, directory, username):
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
        directory = reformat(directory, file_name, media["text"], ext, date_object, username)
        timestamp = date_object.timestamp()
        if not overwrite_files:
            if os.path.isfile(directory):
                return
        r = session.get(link, stream=True)
        with open(directory, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)
        os_name = platform.system()
        if os_name != "macOS":
            setctime(directory, timestamp)
        print(link)
        return True


def reformat(directory2, file_name2, text, ext, date, username):
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
    if count_string > 259:
        num_sum = count_string - 259
        directory2 = directory2.replace(filtered_text, filtered_text[:-num_sum])

    return directory2


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
    response = json.loads(session.get("https://onlyfans.com/api2/v2/users/me?app-token="+app_token).text)
    if 'error' in response:
        show_error(response)
        return False
    else:
        print("Welcome "+response["name"])
    return session


def get_subscriptions(session, app_token):
    response = json.loads(session.get("https://onlyfans.com/api2/v2/subscriptions/subscribes?limit=100&offset=0&type="
                                      "active&app-token="+app_token).text)
    if 'error' in response:
        print("Invalid App Token")
        return False
    else:
        return response
