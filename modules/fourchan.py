import requests
from requests.adapters import HTTPAdapter
import helpers.main_helper as main_helper

import os
import json
from itertools import product
from datetime import datetime
import random
import classes.prepare_download as prepare_download
from multiprocessing import cpu_count

multiprocessing = main_helper.multiprocessing

# Open config.json and fill in OPTIONAL information
json_config = None
json_global_settings = None
max_threads = -1
json_settings = None
auto_choice = None
j_directory = None
file_directory_format = None
file_name_format = None
overwrite_files = None
date_format = None
boards = None
ignored_keywords = None
maximum_length = None
webhook = None


def assign_vars(config, site_settings, site_name):
    global json_config, max_threads, json_settings, auto_choice, j_directory, overwrite_files, date_format, file_directory_format, file_name_format, boards, ignored_keywords, webhook, maximum_length

    json_config = config
    json_global_settings = json_config["settings"]
    max_threads = json_global_settings["max_threads"]
    json_settings = site_settings
    auto_choice = json_settings["auto_choice"]
    j_directory = main_helper.get_directory(
        json_settings['download_paths'], site_name)
    file_directory_format = json_settings["file_directory_format"]
    file_name_format = json_settings["file_name_format"]
    overwrite_files = json_settings["overwrite_files"]
    date_format = json_settings["date_format"]
    boards = json_settings["boards"]
    ignored_keywords = json_settings["ignored_keywords"]
    webhook = json_settings["webhook"]
    maximum_length = 255
    maximum_length = int(json_settings["text_length"]
                         ) if json_settings["text_length"] else maximum_length


def start_datascraper(session, board_name, site_name, link_type, choice_type=None):
    print("Scrape Processing")
    info = link_check(session, board_name)
    if not info["exists"]:
        return [False, info]
    print("Board: " + board_name)
    array = scrape_choice(board_name)
    pool = multiprocessing()
    threads = board_scraper(session, array[0], "")
    archive_threads = board_scraper(session, array[1], "archive")
    threads = threads + archive_threads
    print("Original Count: "+str(len(threads)))
    formatted_directories = main_helper.format_directories(
        j_directory, site_name, board_name)
    model_directory = formatted_directories["model_directory"]
    metadata_directory = formatted_directories["metadata_directory"]
    api_directory = formatted_directories["api_directory"]
    directory = model_directory
    print("Scraping Threads")
    threads = pool.starmap(thread_scraper,
                           product(threads, [board_name], [session], [directory]))
    threads = [x for x in threads if x is not None]
    post_count = len(threads)
    print("Valid Count: "+str(post_count))
    print("Downloading Media")
    count_results = str(len([x for x in threads if x is None]))
    print("Invalid Count: "+count_results)
    num = random.randrange(0, 200)
    avatar = f"https://s.4cdn.org/image/title/{num}.png"
    link = info["link"]
    info["download"] = prepare_download.start(
        username=board_name, link=link, image_url=avatar, post_count=post_count, webhook=webhook)
    info["download"].others.append([threads, session, directory, board_name])
    # When profile is done scraping, this function will return True
    return [True, info]


def link_check(session, username):
    link = f"http://a.4cdn.org/{username}/catalog.json"
    r = session.head(link)
    temp_user_id2 = dict()
    temp_user_id2 = dict()
    temp_user_id2["exists"] = True
    temp_user_id2["subbed"] = True
    temp_user_id2["link"] = f"https://boards.4chan.org/{username}/catalog"
    if r.status_code == 404:
        temp_user_id2["exists"] = False
        temp_user_id2["subbed"] = False
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
    thread = json.loads(r.text)
    thread_master = thread["posts"][0]
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
        text = thread_master["sub"][:maximum_length]
    else:
        text = thread_master["com"][:maximum_length]
    found = False
    new_directory = ""
    seen = set()
    for post in thread["posts"]:
        if "name" not in post:
            post["name"] = "Anonymous"
        if "filename" in post:
            ext = post["ext"].replace(".", "")
            filename = main_helper.clean_text(post["filename"])
            if not filename:
                filename = str(post["no"])
            result = main_helper.rename_duplicates(seen, filename)
            seen = result[0]
            file_name = result[1]
            text = main_helper.clean_text(text)
            new_directory = directory+"/"+text+" - "+thread_id+"/"
            if not text:
                new_directory = new_directory.replace(" - ", "")
            date_object = datetime.fromtimestamp(post["time"])
            file_path = main_helper.reformat(new_directory, None, None, file_name,
                                             text, ext, date_object, post["name"], file_directory_format, file_name_format, date_format, maximum_length)
            post["download_path"] = file_path
            found = True
    if found:
        thread["directory"] = new_directory
        return thread


def download_media(media_set, session, directory, board_name):
    def download(thread, session, directory):
        thread_directory = thread["directory"]
        metadata_directory = os.path.join(
            thread_directory, "Metadata")
        os.makedirs(metadata_directory, exist_ok=True)
        metadata_filepath = os.path.join(metadata_directory, "Posts.json")
        with open(os.path.join(metadata_filepath), 'w') as outfile:
            json.dump(thread, outfile)
        return_bool = True
        medias = thread["posts"]
        for media in medias:
            count = 0
            while count < 11:
                if "download_path" not in media:
                    count += 1
                    continue
                ext = media["ext"].replace(".", "")
                filename = str(media["tim"])+"."+ext
                link = "http://i.4cdn.org/" + board_name + "/" + filename
                r = main_helper.json_request(
                    session, link, "HEAD", True, False)
                if not isinstance(r, requests.Response):
                    return_bool = False
                    count += 1
                    continue
                header = r.headers
                content_length = header.get('content-length')
                content_length = int(content_length)
                download_path = media["download_path"]
                timestamp = media["time"]
                if not overwrite_files:
                    if main_helper.check_for_dupe_file(download_path, content_length):
                        return_bool = False
                        break
                r = main_helper.json_request(session, link, "GET", True, False)
                if not isinstance(r, requests.Response):
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
                    count += 1
                    continue
                main_helper.format_image(download_path, timestamp)
                log_download.info("Link: {}".format(link))
                log_download.info("Path: {}".format(download_path))
                break
        return return_bool
    string = "Download Processing\n"
    string += "Name: "+board_name+"\n"
    string += "Directory: " + directory+"\n"
    print(string)
    pool = multiprocessing()
    os.makedirs(directory, exist_ok=True)
    pool.starmap(download, product(media_set, [session], [directory]))


def create_session():
    session = requests.Session()
    max_threads2 = cpu_count()
    session.mount(
        'http://', HTTPAdapter(pool_connections=max_threads2, pool_maxsize=max_threads2))
    session.mount(
        'https://', HTTPAdapter(pool_connections=max_threads2, pool_maxsize=max_threads2))
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
