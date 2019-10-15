import requests
from bs4 import BeautifulSoup
from win32_setctime import setctime
from modules.helpers import reformat

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
json_settings = json_config["supported"]["4chan"]["settings"]
j_directory = json_settings['directory'] + "/sites/"
format_path = json_settings['file_name_format']
overwrite_files = json_settings["overwrite_files"]
date_format = json_settings["date_format"]

max_threads = multiprocessing.cpu_count()


def start_datascraper(session, board_name, site_name, link_type=None):
    logging.basicConfig(
        filename='errors.log',
        level=logging.ERROR,
        format='%(asctime)s %(levelname)s %(name)s %(message)s')
    user_id = link_check(session, board_name)
    if not user_id[0]:
        print(user_id[1])
        print("First time? Did you forget to edit your config.json file?")
        return [False]
    array = scrape_choice(board_name)
    link_array = {}
    if multithreading:
        pool = ThreadPool(max_threads)
    else:
        pool = ThreadPool(1)
    threads = board_scraper(session, array[0], "")
    archive_threads = board_scraper(session, array[1], "archive")
    threads = threads + archive_threads
    print("Scraping Threads")
    threads = pool.starmap(thread_scraper,
                           product(threads, [board_name], [session]))
    directory = j_directory
    directory += "/"+site_name + "/" + board_name + "/"
    if "/sites/" == j_directory:
        directory = os.path.dirname(
            os.path.dirname(os.path.realpath(
                __file__))) + directory
    else:
        directory = directory

    print("Downloading Media")
    pool.starmap(download_media,
                 product(threads, [session], [directory], [board_name]))

    # When profile is done scraping, this function will return True
    return [True, link_array]


def link_check(session, username):
    link = "http://a.4cdn.org/" + username + "/catalog.json"
    r = session.head(link)
    temp_user_id2 = dict()
    if r.status_code == 404:
        temp_user_id2[0] = False
        temp_user_id2[1] = "Incorrect URL Format"
        return temp_user_id2
    else:
        temp_user_id2[0] = True
        temp_user_id2[1] = username
        return temp_user_id2


def scrape_choice(username):
    catalog = "http://a.4cdn.org/" + username + "/catalog.json"
    archive = catalog.replace("catalog", "archive")
    return [catalog, archive]


def board_scraper(session, link, category):
    r = session.get(link)
    y = json.loads(r.text)
    threads = []
    if "archive" not in category:
        for page in y:
            for thread in page["threads"]:
                threads.append(thread["no"])
    else:
        threads = y
    return threads


def thread_scraper(thread_id, board_name, session):
    link = "http://a.4cdn.org/" + board_name + "/thread/" + str(
        thread_id) + ".json"
    r = session.get(link)
    y = json.loads(r.text)
    return y


def download_media(thread, session, directory, board_name):
    thread_master = thread["posts"][0]
    thread_id = str(thread_master["no"])
    text = ""
    if "sub" in thread_master:
        text = thread_master["sub"]
    else:
        if "com" in thread_master:
            text = thread_master["com"]
    text = BeautifulSoup(text, 'html.parser').get_text().replace(
        "\n", " ").strip()
    text = re.sub(r'[\\/*?:"<>|]', '', text)
    for post in thread["posts"]:
        if "filename" in post:
            filename = str(post["tim"])
            ext = post["ext"].replace(".", "")
            link = "http://i.4cdn.org/" + board_name + "/" + filename+"."+ext
            new_directory = directory+"/"+text+" - "+thread_id+"/"
            if not text:
                new_directory = new_directory.replace(" - ", "")
            date_object = datetime.fromtimestamp(post["time"])
            new_directory = reformat(new_directory, filename, text, ext, date_object, post["name"], format_path,
                                     date_format)
            if not overwrite_files:
                if os.path.isfile(new_directory):
                    continue
            r = session.get(link, stream=True)
            if r.status_code != 404:
                if not os.path.exists(os.path.dirname(new_directory)):
                    os.makedirs(os.path.dirname(new_directory))
                with open(new_directory, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:  # filter out keep-alive new chunks
                            f.write(chunk)
                print(link, new_directory)


def create_session():
    session = requests.Session()
    print("Welcome Anon")
    option_string = "board or thread link"
    return [session, option_string]
