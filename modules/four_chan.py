import requests
from bs4 import BeautifulSoup
from modules.helpers import *

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
ignored_keywords = json_settings["ignored_keywords"]
maximum_length = 240
text_length = int(json_settings["text_length"]
                  ) if json_settings["text_length"] else maximum_length
if text_length > maximum_length:
    text_length = maximum_length

max_threads = multiprocessing.cpu_count()


def start_datascraper(session, board_name, site_name, link_type=None):
    user_id = link_check(session, board_name)
    if not user_id[0]:
        print(user_id[1])
        print("First time? Did you forget to edit your config.json file?")
        return [False]
    print("Board: " + board_name)
    array = scrape_choice(board_name)
    link_array = {}
    if multithreading:
        pool = ThreadPool(max_threads)
    else:
        pool = ThreadPool(1)
    threads = board_scraper(session, array[0], "")
    archive_threads = board_scraper(session, array[1], "archive")
    threads = threads + archive_threads
    print("Original Count: "+str(len(threads)))
    directory = j_directory
    directory += "/"+site_name + "/" + board_name + "/"
    if "/sites/" == j_directory:
        directory = os.path.dirname(
            os.path.dirname(os.path.realpath(
                __file__))) + directory
    else:
        directory = directory

    print("Scraping Threads")
    threads = pool.starmap(thread_scraper,
                           product(threads, [board_name], [session], [directory]))
    threads = [x for x in threads if x is not None]
    print("Filtered Count: "+str(len(threads)))
    print("Downloading Media")
    results = pool.starmap(download_media,
                           product(threads, [session], [directory], [board_name]))
    count_results = str(len([x for x in threads if x is None]))
    print("Valid Count: "+count_results)
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


def thread_scraper(thread_id, board_name, session, directory):
    thread_id = str(thread_id)
    link = "http://a.4cdn.org/" + board_name + "/thread/" + thread_id + ".json"
    r = session.get(link)
    if r.status_code == 404:
        return
    try:
        thread = json.loads(r.text)
        thread_master = thread["posts"][0]
    except Exception as e:
        print(e, link)
        return
    if "archived" in thread_master:
        location = "Archive"
    else:
        location = "Catalog"

    if "sub" in thread_master:
        title = thread_master["sub"].lower()
        if any(ignored_keyword in title for ignored_keyword in ignored_keywords):
            print("Removed From "+location+": ", title)
            return

    if "com" in thread_master:
        title = thread_master["com"].lower()
        if any(ignored_keyword in title for ignored_keyword in ignored_keywords):
            print("Removed From "+location+": ", title)
            return
    text = ""
    if "sub" in thread_master:
        text = thread_master["sub"][:text_length]
    else:
        text = thread_master["com"][:text_length]
    text = BeautifulSoup(text, 'html.parser').get_text().replace(
        "\n", " ").strip()
    text = re.sub(r'[\\/*?:"<>|]', '', text)
    thread["download_path"] = ""
    for post in thread["posts"]:
        if "name" not in post:
            post["name"] = "Anonymous"
        if "filename" in post:
            filename = str(post["tim"])
            ext = post["ext"].replace(".", "")
            filename = post["filename"]
            new_directory = directory+"/"+text+" - "+thread_id+"/"
            if not text:
                new_directory = new_directory.replace(" - ", "")

            date_object = datetime.fromtimestamp(post["time"])
            og_filename = filename
            download_path = os.path.dirname(reformat(
                new_directory, filename, text, ext, date_object, post["name"], format_path, date_format, text_length, maximum_length))
            size = len(download_path)
            size2 = len(thread["download_path"])
            if thread["download_path"]:
                if len(download_path) < len(thread["download_path"]):
                    thread["download_path"] = download_path
            else:
                thread["download_path"] = download_path
    return thread


def download_media(thread, session, directory, board_name):
    try:
        directory = thread["download_path"]+"/"
        valid = False
        for post in thread["posts"]:
            if "filename" in post:
                post["filename"] = re.sub(
                    r'[\\/*?:"<>|]', '', post["filename"])
                ext = post["ext"].replace(".", "")
                filename = str(post["tim"])+"."+ext
                link = "http://i.4cdn.org/" + board_name + "/" + filename
                filename = post["filename"]+"."+ext
                download_path = directory+filename
                count_string = len(download_path)
                if count_string > 259:
                    num_sum = count_string - 259
                    post["filename"] = post["filename"][:50]
                    download_path = directory+post["filename"]+"."+ext

                if not overwrite_files:
                    count = 1
                    found = False
                    og_filename = post["filename"]
                    while True:
                        if os.path.isfile(download_path):
                            remote_size = post["fsize"]
                            local_size = os.path.getsize(download_path)
                            if remote_size == local_size:
                                found = True
                                break
                            else:
                                download_path = directory+og_filename + \
                                    " ("+str(count)+")."+ext
                                count += 1
                                continue
                        else:
                            found = False
                            break
                    if found:
                        continue
                r = session.get(link, stream=True)
                if r.status_code != 404:
                    if not os.path.exists(os.path.dirname(download_path)):
                        os.makedirs(os.path.dirname(download_path))
                    with open(download_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024):
                            if chunk:  # filter out keep-alive new chunks
                                f.write(chunk)
                    print(download_path)
                    valid = True
        if valid:
            os.makedirs(directory, exist_ok=True)
            with open(directory+'archive.json', 'w') as outfile:
                json.dump(thread, outfile)
            return thread
        else:
            return
    except Exception as e:
        print("ERROR", e, directory)
        return


def create_session():
    session = requests.Session()
    print("Welcome Anon")
    option_string = "board or thread link"
    return [session, option_string]
