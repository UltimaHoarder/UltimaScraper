import re
from bs4 import BeautifulSoup
import platform
import csv
import json
from PIL import Image
import os
from os.path import dirname as up

path = up(up(os.path.realpath(__file__)))
os.chdir(path)

# Open config.json and fill in OPTIONAL information
json_config = json.load(open('config.json'))
json_global_settings = json_config["settings"]
export_type = json_global_settings["export_type"]
os_name = platform.system()


def parse_links(site_name, input_link):
    if site_name in {"onlyfans", "justforfans"}:
        username = input_link.rsplit('/', 1)[-1]
        return username

    if site_name in {"4chan", "bbwchan"}:
        if "catalog" in input_link:
            input_link = input_link.split("/")[1]
            print(input_link)
            return input_link
        if input_link[-1:] == "/":
            input_link = input_link.split("/")[3]
            return input_link
        if "4chan.org" not in input_link:
            return input_link


def reformat(directory, file_name, text, ext, date, username, format_path, date_format, text_length, maximum_length):
    path = format_path.replace("{username}", username)
    text = BeautifulSoup(text, 'html.parser').get_text().replace(
        "\n", " ").strip()
    filtered_text = re.sub(r'[\\/*?:"<>|]', '', text)
    path = path.replace("{text}", filtered_text)
    date = date.strftime(date_format)
    path = path.replace("{date}", date)
    path = path.replace("{file_name}", file_name)
    path = path.replace("{ext}", ext)
    directory2 = directory + path

    lp = are_long_paths_enabled()
    if not lp:
        count_string = len(directory2)
        if count_string > maximum_length:
            num_sum = count_string - maximum_length
            directory2 = directory2.replace(
                filtered_text, filtered_text[:text_length])
        count_string = len(directory2)
        if count_string > maximum_length:
            num_sum = count_string - maximum_length
            directory2 = directory2.replace(
                filtered_text, filtered_text[:-num_sum])
            count_string = len(directory2)
            if count_string > maximum_length:
                directory2 = directory
        count_string = len(directory2)
        if count_string > maximum_length:
            num_sum = count_string - maximum_length
            directory2 = directory2.replace(
                filtered_text, filtered_text[:50])
            count_string = len(directory2)
            if count_string > maximum_length:
                directory2 = directory
    filename = os.path.basename(directory2)
    if len(filename) > 240:
        directory2 = directory2.replace(filename, filename[:240]+"."+ext)
    return directory2


def format_media_set(location, media_set):
    x = {}
    x["type"] = location
    x["valid"] = []
    x["invalid"] = []
    for y in media_set:
        x["valid"].extend(y[0])
        x["invalid"].extend(y[1])
    return x


def format_image(directory, timestamp):
    os_name = platform.system()
    if os_name == "Windows":
        from win32_setctime import setctime
        setctime(directory, timestamp)


def export_archive(data, archive_directory):
    # Not Finished
    if export_type == "json":
        with open(archive_directory+".json", 'w') as outfile:
            json.dump(data, outfile)
    if export_type == "csv":
        with open(archive_directory+'.csv', mode='w', encoding='utf-8', newline='') as csv_file:
            fieldnames = []
            if data["valid"]:
                fieldnames.extend(data["valid"][0].keys())
            elif data["invalid"]:
                fieldnames.extend(data["invalid"][0].keys())
            header = [""]+fieldnames
            if len(fieldnames) > 1:
                writer = csv.DictWriter(csv_file, fieldnames=header)
                writer.writeheader()
                for item in data["valid"]:
                    writer.writerow({**{"": "valid"}, **item})
                for item in data["invalid"]:
                    writer.writerow({**{"": "invalid"}, **item})


def get_directory(directory):
    if directory:
        os.makedirs(directory, exist_ok=True)
        return directory
    else:
        return "/sites/"


def format_directory(j_directory, site_name, username, location, api_type):
    directory = j_directory

    user_directory = directory+"/"+site_name + "/"+username+"/"
    metadata_directory = user_directory+api_type+"/Metadata/"
    directories = []
    count = 0
    if "/sites/" == j_directory:
        user_directory = os.path.dirname(os.path.dirname(
            os.path.realpath(__file__))) + user_directory
        metadata_directory = os.path.dirname(os.path.dirname(
            os.path.realpath(__file__))) + metadata_directory
        directories.append(
            [location, user_directory+api_type + "/" + location+"/"])
    else:
        directories.append(
            [location, user_directory+api_type + "/" + location+"/"])
        count += 1
    return [user_directory, metadata_directory, directories]


def are_long_paths_enabled():
    if os_name == "Windows":
        from ctypes import WinDLL, c_ubyte
        ntdll = WinDLL('ntdll')

        if hasattr(ntdll, 'RtlAreLongPathsEnabled'):

            ntdll.RtlAreLongPathsEnabled.restype = c_ubyte
            ntdll.RtlAreLongPathsEnabled.argtypes = ()
            return bool(ntdll.RtlAreLongPathsEnabled())

        else:
            return False


def check_for_dupe_file(overwrite_files, media, download_path, og_filename, directory):
    count = 1
    found = False
    ext = media["ext"]
    if not overwrite_files:
        while True:
            if os.path.isfile(download_path):
                remote_size = media["size"]
                local_size = os.path.getsize(download_path)
                if remote_size == local_size:
                    found = True
                    break
                else:
                    try:
                        im = Image.open(download_path)
                        im.verify()  # I perform also verify, don't know if he sees other types o defects
                        im.close()  # reload is necessary in my case
                        im = Image.open(download_path)
                        im.transpose(Image.FLIP_LEFT_RIGHT)
                        im.close()
                    except Exception as e:
                        print(e)
                        os.remove(download_path)
                        continue
                    download_path = directory+og_filename + \
                        " ("+str(count)+")."+ext
                    count += 1
                    continue
            else:
                found = False
                break
    return [found, download_path]


def json_request(session, link, type="GET"):
    count = 0
    while count < 11:
        try:
            r = session.get(link, stream=True)
            return r
        except ConnectionResetError:
            count += 1

def update_config(json_config):
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(json_config, f, ensure_ascii=False, indent=2)
