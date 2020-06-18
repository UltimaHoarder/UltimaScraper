import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from helpers.main_helper import *

import os
import json
from itertools import product
import multiprocessing
from multiprocessing.dummy import Pool as ThreadPool
from datetime import datetime
import re

json_config = None
json_global_settings = None
multithreading = None
json_settings = None
auto_choice = None
j_directory = None
format_path = None
overwrite_files = None
date_format = None
boards = None
ignored_keywords = None
maximum_length = None

max_threads = multiprocessing.cpu_count()
log_download = setup_logger('downloads', 'downloads.log')


def assign_vars(config, site_settings, site_name):
    global json_config, multithreading, json_settings, auto_choice, j_directory, overwrite_files, date_format, format_path, boards, ignored_keywords, maximum_length

    json_config = config
    json_global_settings = json_config["settings"]
    multithreading = json_global_settings["multithreading"]
    json_settings = site_settings
    auto_choice = json_settings["auto_choice"]
    j_directory = get_directory(json_settings['download_path'], site_name)
    format_path = json_settings["file_name_format"]
    overwrite_files = json_settings["overwrite_files"]
    date_format = json_settings["date_format"]
    boards = json_settings["boards"]
    ignored_keywords = json_settings["ignored_keywords"]
    maximum_length = 255
    maximum_length = int(json_settings["text_length"]
                         ) if json_settings["text_length"] else maximum_length


def start_datascraper(session, board_name, site_name, link_type, choice_type=None):
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
    directory = format_directory(
        j_directory, site_name, board_name)
    directory = directory[0]
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
            text = thread_master["subject"][:maximum_length]

    if thread_master["message"]:
        title = thread_master["message"].lower()
        if any(ignored_keyword in title for ignored_keyword in ignored_keywords):
            print("Removed From "+location+": ", title)
            return
        else:
            if not text:
                text = thread_master["message"][:maximum_length]
    thread_master2 = thread_master.copy()
    for key in thread_master2:
        if "posts" != key:
            del thread_master[key]
    del thread_master2["posts"]
    thread["download_path"] = ""
    thread["posts"] = [thread_master2]+thread_master["posts"]
    found = False
    new_directory = ""
    for post in thread["posts"]:
        date_object = datetime.strptime(
            post["creation"], "%Y-%m-%dT%H:%M:%S.%fZ")
        post["creation"] = date_object.timestamp()
        for media in post["files"]:
            ext = media["mime"].split("/")[1]
            media["ext"] = ext
            file_name = os.path.splitext(media["originalName"])[0].strip()
            text = clean_text(text)
            new_directory = directory+"/"+text+" - "+thread_id+"/"
            if not text:
                new_directory = new_directory.replace(" - ", "")
            file_path = reformat(new_directory, None, None, file_name,
                                 text, ext, date_object, post["name"], format_path, date_format, maximum_length)
            media["download_path"] = file_path
            found = True
    if found:
        thread["directory"] = new_directory
        return thread


def download_media(media_set, session, directory, board_name):
    def download(thread, session, directory):
        os.makedirs(directory, exist_ok=True)
        return_bool = True
        posts = thread["posts"]
        directory = thread["directory"]
        metadata_directory = os.path.join(
            directory, "Metadata")
        os.makedirs(metadata_directory, exist_ok=True)
        metadata_filepath = os.path.join(metadata_directory, "Posts.json")
        with open(os.path.join(metadata_filepath), 'w') as outfile:
            json.dump(thread, outfile)
        for post in posts:
            for media in post["files"]:
                count = 0
                while count < 11:
                    if "download_path" not in media:
                        continue
                    link = "https://bbw-chan.nl" + media["path"]
                    r = json_request(session, link, "HEAD", True, False)
                    if not r:
                        return_bool = False
                        count += 1
                        continue

                    header = r.headers
                    content_length = int(header["content-length"])
                    download_path = media["download_path"]
                    timestamp = post["creation"]
                    if not overwrite_files:
                        if check_for_dupe_file(download_path, content_length):
                            return_bool = False
                            break
                    r = json_request(session, link, "GET", True, False)
                    if not r:
                        return_bool = False
                        count += 1
                        continue
                    os.makedirs(directory, exist_ok=True)
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
                        log_error.exception(e)
                        count += 1
                        continue
                    except Exception as e:
                        if delete:
                            os.unlink(download_path)
                        log_error.exception(
                            str(e) + "\n Tries: "+str(count))
                        count += 1
                        continue
                    format_image(download_path, timestamp)
                    log_download.info("Link: {}".format(link))
                    log_download.info("Path: {}".format(download_path))
                    break
        return return_bool
    string = "Download Processing\n"
    string += "Name: "+board_name+"\n"
    string += "Directory: " + directory+"\n"
    print(string)
    if multithreading:
        pool = ThreadPool()
    else:
        pool = ThreadPool(1)
    pool.starmap(download, product(media_set, [session], [directory]))


def create_session():
    session = requests.Session()
    session.mount(
        'http://', HTTPAdapter(pool_connections=max_threads, pool_maxsize=max_threads))
    session.mount(
        'https://', HTTPAdapter(pool_connections=max_threads, pool_maxsize=max_threads))
    print("Welcome Anon")
    option_string = "board or thread link"
    array = dict()
    array["session"] = session
    array["option_string"] = option_string
    return array


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
