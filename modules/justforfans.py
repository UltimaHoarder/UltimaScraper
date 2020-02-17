import requests
from bs4 import BeautifulSoup
from modules.helpers import *

import os
import json
from itertools import product
import multiprocessing
from multiprocessing.dummy import Pool as ThreadPool
from datetime import datetime
import re
import logging
import math
import re

logger = logging.getLogger(__name__)

# Open config.json and fill in OPTIONAL information
path = os.path.join('settings', 'config.json')
json_config = json.load(open(path))
json_global_settings = json_config["settings"]
multithreading = json_global_settings["multithreading"]
json_settings = json_config["supported"]["justforfans"]["settings"]
auto_choice = json_settings["auto_choice"]
j_directory = get_directory(json_settings['directory'])
format_path = json_settings['file_name_format']
overwrite_files = json_settings["overwrite_files"]
date_format = json_settings["date_format"]
ignored_keywords = json_settings["ignored_keywords"]
maximum_length = 240
text_length = int(json_settings["text_length"]
                  ) if json_settings["text_length"] else maximum_length
if text_length > maximum_length:
    text_length = maximum_length


def start_datascraper(session, username, site_name, app_token=None):
    print("Scrape Processing")
    user_id = link_check(session, username)
    if not user_id[0]:
        print(user_id[1])
        print("First time? Did you forget to edit your config.json file?")
        return [False]

    post_count = user_id[2]
    array = scrape_choice(username, post_count)
    link_array = {}
    prep_download = []
    for item in array:
        item[1].append(username)
        only_links = item[1][4]
        post_count = str(item[1][5])
        item[1].pop(3)
        response = media_scraper(session, site_name, only_links, *item[1])
        link_array[item[1][1].lower()] = response[0]
        if not only_links:
            media_set = response[0]
            if not media_set["valid"]:
                continue
            directory = response[1]
            location = item[1][1]
            prep_download.append(
                [media_set["valid"], session, directory, username, post_count, location])
    # When profile is done scraping, this function will return True
    return [True, prep_download]


def link_check(session, username):
    link = 'https://justfor.fans/' + username
    r = session.get(link)
    rurl = r.url
    temp_user_id2 = dict()
    if "error=usernotfound" in rurl:
        temp_user_id2[0] = False
        temp_user_id2[1] = "No users found"
        return temp_user_id2

    else:
        temp_user_id2[0] = True
        temp_user_id2[1] = str(username)
        photo_count = int(BeautifulSoup(r.text, 'html.parser').findAll(
            "div", {"class": "profile-info-value"})[2].find("h3").get_text())
        video_count = int(BeautifulSoup(r.text, 'html.parser').findAll(
            "div", {"class": "profile-info-value"})[1].find("h3").get_text())
        temp_user_id2[2] = [photo_count, video_count]
        return temp_user_id2


def scrape_choice(username, post_count):
    if auto_choice:
        input_choice = auto_choice
    else:
        print('Scrape: a = Everything | b = Images | c = Videos')
        print(
            'Optional Arguments: -l = Only scrape links -()- Example: "a -l"')
        input_choice = input().strip()
    image_api = "https://justfor.fans/" + username + "?tab=photos&PhotoTabPage=0"
    video_api = "https://justfor.fans/" + username + "?tab=videos&VideoTabPage=0"
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
    return []


def scrape_array(link, session, media_type, directory, username):
    media_set = [[], []]
    r = session.get(link)
    if r.status_code == 404:
        return
    if "photo" == media_type:
        i_items = BeautifulSoup(r.text,
                                'html.parser').find("ul", {
                                    "class": "grid"
                                }).findAll("li", {
                                    "class": None,
                                    "style": None
                                })
        for x in i_items:
            if x.find('figure').find('a') is not None:
                img = x.find('figure').find('a').find('img')
                img_src = ""
                if "src" in img.attrs:
                    img_src = img["src"]
                if "data-src" in img.attrs:
                    img_src = img["data-src"]
                check = img_src[:5]
                img_url = ""
                if check == u"media":
                    img_url = "https://justfor.fans/" + img_src
                link = img_url
                new_dict = dict()
                new_dict["post_id"] = "https://justfor.fans/" + x.find(
                    'figure').find('a')['href']
                new_dict["link"] = link
                post_page = session.get(new_dict["post_id"]).text
                new_dict["post_id"] = new_dict["post_id"].rsplit('=')[-1]
                postdate = BeautifulSoup(post_page, 'html.parser').find("div", {"class": "timeline-item-header"}).\
                    find('small').find('a').get_text().strip('\n')
                date_object = datetime.strptime(
                    postdate, "%B %d, %Y, %I:%M %p")
                date_string = date_object.strftime("%d-%m-%Y %H:%M:%S")
                post_text = BeautifulSoup(post_page, 'html.parser').find("div", {"class": "timeline-item-post"}).\
                    find("div", {"class": "fr-view"}).get_text()
                new_dict["text"] = re.sub(r'(\t[ ]+)', '',
                                          post_text).replace('\n\t', '')
                new_dict["postedAt"] = date_string
                file_name = link.rsplit('/', 1)[-1]

                file_name, ext = os.path.splitext(file_name)
                ext = ext.replace(".", "")
                file_path = reformat(directory[0][1], file_name,
                                     new_dict["text"], ext, date_object, username, format_path, date_format, text_length, maximum_length)
                new_dict["directory"] = directory[0][1]
                new_dict["filename"] = file_path.rsplit('/', 1)[-1]
                media_set[0].append(new_dict)
    return media_set
    # elif "video" == media_type:
    #     v_items = BeautifulSoup(r.text, 'html.parser').findAll(
    #         "div", {"class": "variableVideoLI"})
    #     for x in v_items:
    #         if x.findAll('div') is not None:
    #             link = x.find(
    #                 'div',
    #                 id=lambda y: y and y.startswith('videopage')).find('a')['href']
    #             link = re.search(r"(https:\/\/autograph\.xvid\.com.+?)(?=')",
    #                              link)[0].replace('&amp;', '&')
    #             r = session.head(link, allow_redirects=True)
    #             link = r.url.split("&use_cdn")[0]
    #             new_dict = dict()
    #             new_dict["post_id"] = "https://justfor.fans/" + x.findAll(
    #                 'a')[-1]['href']
    #             new_dict["link"] = link
    #             post_page = session.get(new_dict["post_id"]).text
    #             new_dict["post_id"] = new_dict["post_id"].rsplit('=')[-1]
    #             postdate = BeautifulSoup(post_page, 'html.parser').find("div", {"class": "timeline-item-header"}).\
    #                 find('small').find('a').get_text().strip('\n')
    #             date_object = datetime.strptime(
    #                 postdate, "%B %d, %Y, %I:%M %p")
    #             date_string = date_object.strftime("%d-%m-%Y %H:%M:%S")
    #             post_text = BeautifulSoup(post_page, 'html.parser').find(
    #                 "div", {
    #                     "class": "timeline-item-post"
    #                 }).find("div", {
    #                     "class": "fr-view"
    #                 }).get_text()
    #             new_dict["text"] = re.sub(r'(\t[ ]+)', '',
    #                                       post_text).replace('\n\t', '')
    #             new_dict["postedAt"] = date_string
    #             file_name = link.rsplit('?')[0].rsplit('/', 1)[-1]

    #             file_name, ext = os.path.splitext(file_name)
    #             ext = ext.__str__().replace(".", "")
    #             file_path = reformat(directory[0][1], file_name,
    #                                  new_dict["text"], ext, date_object, username, format_path, date_format, text_length, maximum_length)
    #             new_dict["directory"] = directory
    #             new_dict["filename"] = file_path.rsplit('/', 1)[-1]
    #             media_set[0].append(new_dict)
    # return media_set


def media_scraper(session, site_name, only_links, link, location, media_type, directory, post_count, username):
    print("Scraping " + location + ". May take a few minutes.")
    array = format_directory(j_directory, site_name,
                             username, location, "Posts")
    user_directory = array[0]
    metadata_directory = array[1]
    directory = array[2]

    pool = ThreadPool()
    ceil = math.ceil(post_count / 100)
    a = list(range(ceil))
    offset_array = []
    for b in a:
        b = b * 100
        offset_array.append(link.replace("Page=0", "Page=" + str(b)))
    media_set = format_media_set(location, pool.starmap(scrape_array, product(
        offset_array, [session], [media_type], [directory], [username])))
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
        archive_directory = metadata_directory+location
        export_archive(media_set, archive_directory)
    return [media_set, directory]


def download_media(media_set, session, directory, username, post_count, location):
    def download(media, session, directory, username):
        while True:
            link = media["link"]
            r = session.head(link)

            date_object = datetime.strptime(
                media["postedAt"], "%d-%m-%Y %H:%M:%S")
            directory = directory+media["filename"]
            timestamp = date_object.timestamp()
            if not overwrite_files:
                if os.path.isfile(directory):
                    return
            if not os.path.exists(os.path.dirname(directory)):
                os.makedirs(os.path.dirname(directory))
            r = session.get(link, allow_redirects=True, stream=True)
            with open(directory, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:  # filter out keep-alive new chunks
                        f.write(chunk)
            format_image(directory, timestamp)
            logger.info("Link: {}".format(link))
            logger.info("Path: {}".format(directory))
            return True
    print("Download Processing")
    print("Name: "+username)
    print("Directory: " + directory)
    print("Downloading "+post_count+" "+location)
    if multithreading:
        pool = ThreadPool()
    else:
        pool = ThreadPool(1)
    pool.starmap(download, product(
        media_set, [session], [directory], [username]))


def create_session(user_agent, phpsessid, user_hash2):
    max_threads = multiprocessing.cpu_count()
    session = requests.Session()
    session.mount(
        'https://', requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=max_threads))
    session.headers = {
        'User-Agent': user_agent,
        'Referer': 'https://justfor.fans/'
    }
    auth_cookies = [
        {
            'name': 'PHPSESSID',
            'value': phpsessid
        },
        {
            'name': 'UserHash2',
            'value': user_hash2
        },
    ]
    for auth_cookie in auth_cookies:
        session.cookies.set(**auth_cookie)
    session.head("https://justfor.fans")
    response = session.get("https://justfor.fans/home.php").text
    login_name = BeautifulSoup(response,
                               'html.parser').find("span", {
                                   "class": "user-name"
                               }).get_text()
    if not login_name:
        print("Login Error")
        return [False]
    else:
        print("Welcome " + login_name)
    option_string = "username or profile link"
    return [session, option_string]


def get_subscriptions(session=[], app_token=""):
    return [[]]
