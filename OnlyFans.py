import requests
from bs4 import BeautifulSoup
from urllib.request import urlretrieve
import os
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing import current_process, Pool
import multiprocessing
from itertools import product
import re
import json

# You MUST fill all of this in for the script to work :D
json_data = json.load(open('settings.json'))
j_directory = json_data['directory']+"/Users/"
app_token = json_data['app-token']
sess = json_data['sess']
user_agent = json_data['user-agent']

# You don't have to fill anything else in below this line :)
auth_cookie = {
    'domain': '.onlyfans.com',
    'expires': None,
    'name': 'sess',
    'path': '/',
    'value': sess,
    'version': 0
}

session = requests.Session()
session.cookies.set(**auth_cookie)
session.headers = {
    'User-Agent': user_agent, 'Referer': 'https://onlyfans.com/'}


def link_check(link):
    r = session.get(link)
    raw_html = r.content
    html = BeautifulSoup(raw_html, 'html.parser')
    temp_user_id = html.find("div", {"class": "b-users"}).find("a", attrs={"data-user", True})
    if temp_user_id:
        return temp_user_id["data-user"]
    return False


def scrape_choice():
    print('Scrape: a = Everything | b = Images | c = Videos')
    input_choice = input()
    image_api = "https://onlyfans.com/api2/v2/users/"+user_id+"/posts/photos?limit=1000&offset=0&order=publish_date_" \
                                                              "desc&app-token="+app_token+""
    video_api = "https://onlyfans.com/api2/v2/users/"+user_id+"/posts/videos?limit=1000&offset=0&order=publish_date_" \
                                                              "desc&app-token="+app_token+""
    if input_choice == "a":
        location = "/Images/"
        media_scraper(image_api, location, j_directory)
        print("Photos Finished")
        location = "/Videos/"
        media_scraper(video_api, location, j_directory)
        print("Videos Finished")
        return
    if input_choice == "b":
        location = "/Images/"
        media_scraper(image_api, location, j_directory)
        return
    if input_choice == "c":
        location = "/Videos/"
        media_scraper(video_api, location, j_directory)
        return


def media_scraper(link, location, directory):
    r = session.get(link)
    y = json.loads(r.text)

    media_set = dict([])
    media_count = 0
    for media_api in y:
        for media in media_api["media"]:
            file = media["source"]["source"]
            media_set[media_count] = {}
            media_set[media_count]["link"] = file
            media_count += 1

    if "/Users/" == directory:
        directory = os.path.dirname(os.path.realpath(__file__))+"/Users/"+username+location
    else:
        directory = directory+username+location

    print("DIRECTORY - " + directory)
    if not os.path.exists(directory):
        os.makedirs(directory)

    max_threads = multiprocessing.cpu_count()
    pool = ThreadPool(max_threads)
    pool.starmap(download_media, product(media_set.items(), [directory]))


def download_media(media, directory):
    link = media[1]["link"]
    file_name = link.rsplit('/', 1)[-1]
    urlretrieve(link, directory + file_name)
    print(link)
    return


while True:
    print('Input a username or profile link')
    input_link = input().strip()
    username = input_link.rsplit('/', 1)[-1]
    input_link = 'https://onlyfans.com/search/users/'+username
    user_id = link_check(input_link)
    if not user_id:
        print("User Not Found")
        print("First time? Did you forget to edit your settings.json file?")
        continue
    scrape_choice()
    print('Finished')
