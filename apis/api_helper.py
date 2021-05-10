import copy
import time
from typing import Any, Union

import requests
from requests.sessions import Session
import ujson
import socket
import os
from multiprocessing import cpu_count
from requests.adapters import HTTPAdapter
from multiprocessing.dummy import Pool as ThreadPool
from itertools import product, chain, zip_longest, groupby
from os.path import dirname as up
import threading

path = up(up(os.path.realpath(__file__)))
os.chdir(path)


global_settings = {}


class set_settings():
    def __init__(self, option={}):
        global global_settings
        self.proxies = option.get("proxies")
        self.cert = option.get("cert")
        self.json_global_settings = option
        global_settings = self.json_global_settings


def chunks(l, n):
    final = [l[i * n:(i + 1) * n] for i in range((len(l) + n - 1) // n)]
    return final


def multiprocessing(max_threads=None):
    if not max_threads:
        max_threads = global_settings.get("max_threads", -1)
    max_threads2 = cpu_count()
    if max_threads < 1 or max_threads >= max_threads2:
        pool = ThreadPool()
    else:
        pool = ThreadPool(max_threads)
    return pool


class session_manager():
    def __init__(self, original_sessions=[], headers: dict = {}, session_rules=None, session_retry_rules=None) -> None:
        self.sessions = self.copy_sessions(original_sessions)
        self.pool = multiprocessing()
        self.max_threads = self.pool._processes
        self.kill = False
        self.headers = headers
        self.session_rules = session_rules
        self.session_retry_rules = session_retry_rules
        self.dynamic_rules = None

    def copy_sessions(self, original_sessions):
        sessions = []
        for original_session in original_sessions:
            cloned_session = copy.deepcopy(original_session)
            ip = getattr(original_session, "ip", "")
            cloned_session.ip = ip
            cloned_session.links = []
            sessions.append(cloned_session)
        self.sessions = sessions
        return self.sessions

    def stimulate_sessions(self):
        # Some proxies switch IP addresses if no request have been made for x amount of secondss
        def do(session_manager):
            while not session_manager.kill:
                for session in session_manager.sessions:
                    def process_links(link, session):
                        r = session.get(link)
                        text = r.text.strip("\n")
                        if text == session.ip:
                            print
                        else:
                            found_dupe = [
                                x for x in session_manager.sessions if x.ip == text]
                            if found_dupe:
                                return
                            cloned_session = copy.deepcopy(session)
                            cloned_session.ip = text
                            cloned_session.links = []
                            session_manager.sessions.append(cloned_session)
                            print(text)
                            print
                        return text
                    time.sleep(62)
                    link = "https://checkip.amazonaws.com"
                    ip = process_links(link, session)
                    print
        t1 = threading.Thread(target=do, args=[self])
        t1.start()

    def json_request(self, link: str, session: Union[Session] = None, method="GET", stream=False, json_format=True, data={}, sleep=True, timeout=20, ignore_rules=False, force_json=False) -> Any:
        headers = {}
        if not session:
            session = self.sessions[0]
        if self.session_rules and not ignore_rules:
            headers |= self.session_rules(self, link)
        session = copy.deepcopy(session)
        count = 0
        sleep_number = 0.5
        result = {}
        while count < 11:
            try:
                count += 1
                if json_format:
                    headers["accept"] = "application/json, text/plain, */*"
                if data:
                    r = session.request(method, link, json=data,
                                        stream=stream, timeout=timeout, headers=headers)
                else:
                    r = session.request(
                        method, link, stream=stream, timeout=timeout, headers=headers)
                if self.session_retry_rules:
                    rule = self.session_retry_rules(r, link)
                    if rule == 1:
                        continue
                    elif rule == 2:
                        break
                if json_format:
                    content_type = r.headers['Content-Type']
                    matches = ["application/json;", "application/vnd.api+json"]
                    if not force_json and all(match not in content_type for match in matches):
                        continue
                    text = r.text
                    if not text:
                        message = "ERROR: 100 Posts skipped. Please post the username you're trying to scrape on the issue "'100 Posts Skipped'""
                        return result
                    return ujson.loads(text)
                else:
                    return r
            except (ConnectionResetError) as e:
                continue
            except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError, requests.exceptions.ReadTimeout, socket.timeout) as e:
                if sleep:
                    time.sleep(sleep_number)
                    sleep_number += 0.5
                continue
            except Exception as e:
                print(e)
                continue
        return result


def create_session(settings={}, custom_proxy="", test_ip=True):

    def test_session(proxy=None, cert=None, max_threads=None):
        session = requests.Session()
        proxy_type = {'http': proxy,
                      'https': proxy}
        if proxy:
            session.proxies = proxy_type
            if cert:
                session.verify = cert
        session.mount(
            'https://', HTTPAdapter(pool_connections=max_threads, pool_maxsize=max_threads))
        if test_ip:
            link = 'https://checkip.amazonaws.com'
            r = session_manager().json_request(
                link, session, json_format=False, sleep=False)
            if not isinstance(r, requests.Response):
                print(f"Proxy Not Set: {proxy}\n")
                return
            ip = r.text.strip()
            print("Session IP: "+ip+"\n")
            setattr(session, "ip", ip)
            setattr(session, "links", [])
        return session
    sessions = []
    settings = set_settings(settings)
    pool = multiprocessing()
    max_threads = pool._processes
    proxies = settings.proxies
    cert = settings.cert
    while not sessions:
        proxies = [custom_proxy] if custom_proxy else proxies
        if proxies:
            sessions = pool.starmap(test_session, product(
                proxies, [cert], [max_threads]))
        else:
            session = test_session(max_threads=max_threads)
            sessions.append(session)
    return sessions


def assign_session(medias, item, key_one="link", key_two="count", show_item=False, capped=False):
    count = 0
    activate_cap = False
    number = len(item)
    medias2 = []
    for auth in medias:
        media2 = {}
        media2[key_one] = auth
        if not number:
            count = -1
        if activate_cap:
            media2[key_two] = -1
        else:
            if show_item:
                media2[key_two] = item[count]
            else:
                media2[key_two] = count

        medias2.append(media2)
        count += 1
        if count >= number:
            count = 0
            if capped:
                activate_cap = True
    return medias2


def restore_missing_data(master_set2, media_set, split_by):
    count = 0
    new_set = []
    for item in media_set:
        if not item:
            link = master_set2[count]
            offset = int(link.split('?')[-1].split('&')[1].split("=")[1])
            limit = int(link.split("?")[-1].split("&")[0].split("=")[1])
            if limit == split_by+1:
                break
            offset2 = offset
            limit2 = int(limit/split_by)
            for item in range(1, split_by+1):
                link2 = link.replace("limit="+str(limit), "limit="+str(limit2))
                link2 = link2.replace(
                    "offset="+str(offset), "offset="+str(offset2))
                offset2 += limit2
                new_set.append(link2)
        count += 1
    new_set = new_set if new_set else master_set2
    return new_set


def scrape_check(links, session_manager: session_manager, api_type):
    def multi(item):
        link = item["link"]
        item = {}
        session = session_manager.sessions[0]
        result = session_manager.json_request(link, session)
        if "error" in result:
            result = []
        # if result:
        #     print(f"Found: {link}")
        # else:
        #     print(f"Not Found: {link}")
        if result:
            item["session"] = session
            item["result"] = result
        return item
    media_set = []
    max_attempts = 100
    count = len(links)
    api_type = api_type.capitalize()
    for attempt in list(range(max_attempts)):
        print("Scrape Attempt: "+str(attempt+1)+"/"+str(max_attempts))
        if not links:
            continue
        items = assign_session(links, session_manager.sessions)
        # item_groups = grouper(300,items)
        pool = multiprocessing()
        results = pool.starmap(multi, product(
            items))
        not_faulty = [x for x in results if x]
        faulty = [{"key": k, "value": v, "link": links[k]}
                  for k, v in enumerate(results) if not v]
        last_number = len(results)-1
        if faulty:
            positives = [x for x in faulty if x["key"] != last_number]
            false_positive = [x for x in faulty if x["key"] == last_number]
            if positives:
                attempt = attempt if attempt > 1 else attempt + 1
                num = int(len(faulty)*(100/attempt))
                split_by = 2
                print("Missing "+str(num)+" Posts... Retrying...")
                links = restore_missing_data(
                    links, results, split_by)
                media_set.extend(not_faulty)
            if not positives and false_positive:
                media_set.extend(results)
                break
            print
        else:
            media_set.extend(results)
            print("Found: "+api_type)
            break
    media_set = [x for x in media_set]
    return media_set


def grouper(n, iterable, fillvalue=None):
    args = [iter(iterable)] * n
    return list(zip_longest(fillvalue=fillvalue, *args))
