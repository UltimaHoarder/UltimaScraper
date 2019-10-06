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


def start_datascraper(session, username):
    logging.basicConfig(filename='errors.log', level=logging.ERROR,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s')
    user_id = link_check(session, username)
    if not user_id[0]:
        print(user_id[1])
        print("First time? Did you forget to edit your config.json file?")
        return [False]

    post_count = int(user_id[2])
    array = scrape_choice(username, post_count)
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
        temp_user_id2[2] = BeautifulSoup(r.text, 'html.parser').find("div", {"class": "profile-info-value"}).find("h3").get_text()
        return temp_user_id2


def scrape_choice(username, post_count):
    if auto_choice:
        input_choice = auto_choice
    else:
        print('Scrape: a = Everything | b = Images | c = Videos')
        print('Optional Arguments: -l = Only scrape links -()- Example: "a -l"')
        input_choice = input().strip()
    image_api = "https://justfor.fans/" + username + "?tab=photos&PhotoTabPage=0&VideoTabPage=9999"
    video_api = "https://justfor.fans/" + username + "?tab=videos&PhotoTabPage=9999&VideoTabPage=0"
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
    UTC_OFFSET_TIMEDELTA = datetime.utcnow() - datetime.now()
    r = session.get(link)
    itemsi = BeautifulSoup(r.text, 'html.parser').find("ul", {"class": "grid"}).findAll("li", {"class": None, "style": None})
    itemsv = BeautifulSoup(r.text, 'html.parser').findAll("div", {"class": "variableVideoLI"})
    for x in itemsi:
        if x.find('figure').find('a') is not None:
            imgsrc = x.find('figure').find('a').find('img')['src']
            check = imgsrc[:5]
            if check == u"media":
                imgurl = "https://justfor.fans/" + imgsrc
            try:
                datasrc = x.find('figure').find('a').find('img')['data-src']
                check = datasrc[:5]
                if check == u"media":
                    imgurl = "https://justfor.fans/" + datasrc
            except KeyError:
                pass
            file = imgurl
            new_dict = dict()
            new_dict["post_id"] = "https://justfor.fans/" + x.find('figure').find('a')['href']
            new_dict["link"] = file
            postpage = session.get(new_dict["post_id"]).text
            new_dict["post_id"] = new_dict["post_id"].rsplit('=')[-1]
            postdate = BeautifulSoup(postpage, 'html.parser').find("div", {"class": "timeline-item-header"}).find('small').find('a').get_text().strip('\n')
            local_datetime = datetime.strptime(postdate, "%B %d, %Y, %I:%M %p")
            result_utc_datetime = local_datetime + UTC_OFFSET_TIMEDELTA
            dt = result_utc_datetime.strftime("%d-%m-%Y %H:%M:%S")
            posttext = BeautifulSoup(postpage, 'html.parser').find("div", {"class": "timeline-item-post"}).find("div", {"class": "fr-view"}).get_text()
            new_dict["text"] = re.sub(r'(\t[ ]+)', '', posttext).replace('\n\t','')
            new_dict["postedAt"] = dt
            media_set.append(new_dict)
    for x in itemsv:
        if x.findAll('div') is not None:
            file = x.find('div', id=lambda y: y and y.startswith('videopage')).find('a')['href']
            file = re.search(r"(https:\/\/autograph\.xvid\.com.+?)(?=')",file)[0].replace('&amp;','&')
            new_dict = dict()
            new_dict["post_id"] = "https://justfor.fans/" + x.findAll('a')[-1]['href']
            new_dict["link"] = file
            postpage = session.get(new_dict["post_id"]).text
            new_dict["post_id"] = new_dict["post_id"].rsplit('=')[-1]
            postdate = BeautifulSoup(postpage, 'html.parser').find("div", {"class": "timeline-item-header"}).find('small').find('a').get_text().strip('\n')
            local_datetime = datetime.strptime(postdate, "%B %d, %Y, %I:%M %p")
            result_utc_datetime = local_datetime + UTC_OFFSET_TIMEDELTA
            dt = result_utc_datetime.strftime("%d-%m-%Y %H:%M:%S")
            posttext = BeautifulSoup(postpage, 'html.parser').find("div", {"class": "timeline-item-post"}).find("div", {"class": "fr-view"}).get_text()
            new_dict["text"] = re.sub(r'(\t[ ]+)', '', posttext).replace('\n\t','')
            new_dict["postedAt"] = dt
            media_set.append(new_dict)
    return media_set


def media_scraper(session, link, location, directory, post_count, username):
    print("Scraping "+location+". May take a few minutes.")
    pool = ThreadPool(max_threads)
    i = 0
    offset_array = []
    iterlink = link
    page = session.get(iterlink)
    items = BeautifulSoup(page.text, 'html.parser').find("ul", {"class": "grid"}).findAll("li", {"class": None, "style": None})
    items = items + BeautifulSoup(page.text, 'html.parser').findAll("div", {"class": "variableVideoLI"})
    while len(items) > 0:
        offset_array.append(iterlink)
        i += 1
        iterlink = link.replace("Page=0", "Page=" + str(i))
        page = session.get(iterlink)
        items = BeautifulSoup(page.text, 'html.parser').find("ul", {"class": "grid"}).findAll("li", {"class": None, "style": None})
        items = items + BeautifulSoup(page.text, 'html.parser').findAll("div", {"class": "variableVideoLI"})
    media_set = pool.starmap(scrape_array, product(offset_array, [session]))
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
    return [media_set, directory]


def download_media(media, session, directory, username):
    while True:
        link = media["link"]
        r = session.head(link, allow_redirects=True)
        if r.status_code != 200:
            return
        link = r.url
        file_name = link.rsplit('/', 1)[-1].rsplit("?", 1)[0]
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
        r = session.get(link, allow_redirects=True, stream=True)
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

def create_session(user_agent, phpsessid, userhash2):
    session = requests.Session()
    session.headers = {
        'User-Agent': user_agent, 'Referer': 'https://justfor.fans/'}
    auth_cookies = [
        {'name': 'PHPSESSID', 'value': phpsessid},
        {'name': 'UserHash2', 'value': userhash2},
    ]
    for auth_cookie in auth_cookies:
        session.cookies.set(**auth_cookie)
    session.head("https://justfor.fans")
    response = session.get("https://justfor.fans/home.php").text
    loginname = BeautifulSoup(response, 'html.parser').find("span", {"class": "user-name"}).get_text()
    if type(loginname) == None:
        print("Login Error")
        return False
    else:
        print("Welcome "+ loginname)
    return session