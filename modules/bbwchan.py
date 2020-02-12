import requests
from modules.helpers import *

import os
import json
from itertools import product
import multiprocessing
from multiprocessing.dummy import Pool as ThreadPool
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)

# Open config.json and fill in OPTIONAL information
path = os.path.join('settings', 'config.json')
json_config = json.load(open(path))
json_global_settings = json_config["settings"]
multithreading = json_global_settings["multithreading"]
json_settings = json_config["supported"]["bbwchan"]["settings"]
auto_choice = json_settings["auto_choice"]
j_directory = get_directory(json_settings['directory'])
format_path = json_settings['file_name_format']
overwrite_files = json_settings["overwrite_files"]
date_format = json_settings["date_format"]
boards = json_settings["boards"]
ignored_keywords = json_settings["ignored_keywords"]
maximum_length = 240
text_length = int(json_settings["text_length"]
                  ) if json_settings["text_length"] else maximum_length
if text_length > maximum_length:
    text_length = maximum_length

max_threads = multiprocessing.cpu_count()


def start_datascraper(session, board_name, site_name, link_type=None):
    print("Scrape Processing")
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
    archive_threads = []
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
    post_count = len(threads)
    print("Valid Count: "+str(post_count))
    print("Downloading Media")
    count_results = str(len([x for x in threads if x is None]))
    print("Invalid Count: "+count_results)
    prep_download = [[threads, session, directory, board_name]]
    # When profile is done scraping, this function will return True
    return [True, prep_download]


def link_check(session, username):
    link = "https://bbw-chan.nl/" + username + "/catalog.json"
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
    catalog = "https://bbw-chan.nl/" + username + "/catalog.json"
    return [catalog]


def board_scraper(session, link, category):
    r = session.get(link)
    y = json.loads(r.text)
    threads = []
    if "archive" not in category:
        for thread in y:
            threads.append(thread["threadId"])
    else:
        threads = y
    return threads


def thread_scraper(thread_id, board_name, session, directory):
    thread_id = str(thread_id)
    link = "https://bbw-chan.nl/" + board_name + "/res/" + thread_id + ".json"
    r = session.get(link)
    if r.status_code == 404:
        return
    thread = json.loads(r.text)
    thread_master = thread
    if "archived" in thread_master:
        location = "Archive"
    else:
        location = "Catalog"
    text = ""
    if thread_master["subject"]:
        title = thread_master["subject"].lower()
        if any(ignored_keyword in title for ignored_keyword in ignored_keywords):
            print("Removed From "+location+": ", title)
            return
        else:
            text = thread_master["subject"][:text_length]

    if thread_master["message"]:
        title = thread_master["message"].lower()
        if any(ignored_keyword in title for ignored_keyword in ignored_keywords):
            print("Removed From "+location+": ", title)
            return
        else:
            if not text:
                text = thread_master["message"][:text_length]
    text = BeautifulSoup(text, 'html.parser').get_text().replace(
        "\n", " ").replace(
        "\r", " ").strip()
    text = re.sub(r'[\\/*?:"<>|]', '', text)
    text = re.sub(' {2,}', ' ', text)
    thread_master2 = thread_master.copy()
    for key in thread_master2:
        if "posts" != key:
            del thread_master[key]
    del thread_master2["posts"]
    thread["download_path"] = ""
    thread["posts"] = [thread_master2]+thread_master["posts"]
    for post in thread["posts"]:
        for media in post["files"]:
            ext = media["mime"].split("/")[1]
            media["ext"] = ext
            filename = os.path.splitext(media["originalName"])[0].strip()
            media["alt_filename"] = media["path"].rsplit(
                "a/")[1].rsplit("-")[0][:13]+"."+ext
            new_directory = directory+"/"+text+" - "+thread_id+"/"
            if not text:
                new_directory = new_directory.replace(" - ", "")
            date_object = datetime.strptime(
                post["creation"], "%Y-%m-%dT%H:%M:%S.%fZ")
            date_string = date_object.replace(tzinfo=None).strftime(
                "%d-%m-%Y %H:%M:%S")
            download_path = os.path.dirname(reformat(
                new_directory, filename, text, ext, date_object, post["name"], format_path, date_format, text_length, maximum_length))
            thread["download_path"] = download_path
    return thread


def download_media(media_set, session, directory, board_name):
    def download(thread, session, directory):
        directory = thread["download_path"]+"/"
        valid = False
        for post in thread["posts"]:
            name_key = "originalName"
            for media in post["files"]:
                filename = re.sub(
                    r'[\\/*?:"<>|]', '', media[name_key])
                ext = media["ext"]
                alt_name = media["alt_filename"]
                link = "https://bbw-chan.nl" + media["path"]
                download_path = directory+filename
                count_string = len(download_path)
                lp = are_long_paths_enabled()
                if not lp:
                    if count_string > maximum_length:
                        num_sum = count_string - maximum_length
                        name_key = "alt_filename"
                        download_path = directory+post[name_key]+"."+ext

                og_filename = os.path.splitext(filename)[0]
                dp = check_for_dupe_file(
                    overwrite_files, media, download_path, og_filename, directory)
                if dp[0]:
                    continue
                download_path = dp[1]
                r = session.get(link, stream=True)
                if r.status_code != 404:
                    if not os.path.exists(os.path.dirname(download_path)):
                        os.makedirs(os.path.dirname(download_path))
                    with open(download_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024):
                            if chunk:  # filter out keep-alive new chunks
                                f.write(chunk)
                    logger.info("Link: {}".format(link))
                    logger.info("Path: {}".format(download_path))
                    valid = True
                else:
                    logger.info("Fail (Link): {}".format(link))
                    logger.info("Fail (Path): {}".format(download_path))
        if valid:
            os.makedirs(directory, exist_ok=True)
            with open(directory+'archive.json', 'w') as outfile:
                json.dump(thread, outfile)
            return thread
        else:
            return
    print("Download Processing")
    print("Name: "+board_name)
    print("Directory: " + directory)
    # print("Downloading "+post_count+" "+location)
    max_threads = len(media_set)
    if multithreading:
        pool = ThreadPool(max_threads)
    else:
        pool = ThreadPool(1)
    session.mount(
        'https://', requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=max_threads))
    pool.starmap(download, product(media_set, [session], [directory]))


def create_session():
    session = requests.Session()
    session.mount(
        'http://', requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=16))
    session.mount(
        'https://', requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=16))
    print("Welcome Anon")
    option_string = "board or thread link"
    return [session, option_string]


def get_subscriptions(session=[], app_token=""):
    names = boards
    return names


def format_options(array):
    string = ""
    names = []
    array = ["All"]+array
    name_count = len(array)
    if name_count > 1:

        count = 0
        for x in array:
            name = x
            string += str(count)+" = "+name
            names.append(name)
            if count+1 != name_count:
                string += " | "

            count += 1
    return [names, string]
