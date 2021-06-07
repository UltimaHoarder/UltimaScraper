import asyncio
import copy
import hashlib
import os
import re
import threading
import time
from itertools import chain, groupby, product, zip_longest
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from os.path import dirname as up
from random import randint
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp
import helpers.main_helper as main_helper
import python_socks
import requests
from aiohttp import ClientSession
from aiohttp.client_reqrep import ClientResponse
from aiohttp_socks import ChainProxyConnector, ProxyConnector, ProxyType
from database.models.media_table import media_table

from apis.onlyfans.classes import create_user

path = up(up(os.path.realpath(__file__)))
os.chdir(path)


global_settings = {}
global_settings[
    "dynamic_rules_link"
] = "https://raw.githubusercontent.com/DATAHOARDERS/dynamic-rules/main/onlyfans.json"


class set_settings:
    def __init__(self, option={}):
        global global_settings
        self.proxies = option.get("proxies")
        self.cert = option.get("cert")
        self.json_global_settings = option
        global_settings = self.json_global_settings


def chunks(l, n):
    final = [l[i * n : (i + 1) * n] for i in range((len(l) + n - 1) // n)]
    return final


def calculate_max_threads(max_threads=None):
    if not max_threads:
        max_threads = -1
    max_threads2 = cpu_count()
    if max_threads < 1 or max_threads >= max_threads2:
        max_threads = max_threads2
    return max_threads


def multiprocessing(max_threads=None):
    max_threads = calculate_max_threads(max_threads)
    pool = ThreadPool(max_threads)
    return pool


class session_manager:
    def __init__(
        self,
        auth,
        original_sessions=[],
        headers: dict = {},
        proxies: list[str] = [],
        session_retry_rules=None,
        max_threads=-1,
    ) -> None:
        self.sessions = self.add_sessions(original_sessions)
        self.pool = multiprocessing()
        self.max_threads = max_threads
        self.kill = False
        self.headers = headers
        self.proxies: list[str] = proxies
        self.session_retry_rules = session_retry_rules
        dr_link = global_settings["dynamic_rules_link"]
        dynamic_rules = requests.get(dr_link).json()
        self.dynamic_rules = dynamic_rules
        self.auth = auth

    def add_sessions(self, original_sessions: list, overwrite_old_sessions=True):
        if overwrite_old_sessions:
            sessions = []
        else:
            sessions = self.sessions
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
                                x for x in session_manager.sessions if x.ip == text
                            ]
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

    async def json_request(
        self,
        link: str,
        session: Optional[ClientSession] = None,
        method="GET",
        stream=False,
        json_format=True,
        data={},
        progress_bar=None,
        sleep=True,
        timeout=20,
        ignore_rules=False,
        force_json=False,
    ) -> Any:
        headers = {}
        custom_session = False
        if not session:
            custom_session = True
            proxies = self.proxies
            proxy = self.proxies[randint(0, len(proxies) - 1)] if proxies else ""
            connector = ProxyConnector.from_url(proxy) if proxy else None
            session = ClientSession(
                connector=connector, cookies=self.auth.cookies, read_timeout=None
            )
        headers = self.session_rules(link)
        headers["accept"] = "application/json, text/plain, */*"
        headers["Connection"] = "keep-alive"
        request_method = None
        if method == "HEAD":
            request_method = session.head
        elif method == "GET":
            request_method = session.get
        elif method == "POST":
            request_method = session.post
        elif method == "DELETE":
            request_method = session.delete
        try:
            async with request_method(link, headers=headers) as response:
                if method == "HEAD":
                    result = response
                else:
                    if json_format and not stream:
                        result = await response.json()
                    elif stream and not json_format:
                        buffer = []
                        if response.status == 200:
                            async for data in response.content.iter_chunked(4096):
                                buffer.append(data)
                                length = len(data)
                                progress_bar.update(length)
                        else:
                            if response.content_length:
                                progress_bar.update_total_size(-response.content_length)
                        final_buffer = b"".join(buffer)
                        result = [response, final_buffer]
                        print
                    else:
                        result = await response.read()
                if custom_session:
                    await session.close()
                return result
        except aiohttp.ClientConnectorError as e:
            return

    async def async_requests(self, items: list[str], json_format=True):
        tasks = []

        async def run(links):
            proxies = self.proxies
            proxy = self.proxies[randint(0, len(proxies) - 1)] if proxies else ""
            connector = ProxyConnector.from_url(proxy) if proxy else None
            async with ClientSession(
                connector=connector, cookies=self.auth.cookies, read_timeout=None
            ) as session:
                for link in links:
                    task = asyncio.ensure_future(self.json_request(link, session))
                    tasks.append(task)
                responses = await asyncio.gather(*tasks)
                return responses

        results = await asyncio.ensure_future(run(items))
        return results

    async def async_downloads(
        self, download_list: list[media_table], subscription: create_user
    ):
        async def run(download_list: list[media_table]):
            proxies = self.proxies
            proxy = self.proxies[randint(0, len(proxies) - 1)] if proxies else ""
            connector = ProxyConnector.from_url(proxy) if proxy else None
            async with ClientSession(
                connector=connector, cookies=self.auth.cookies, read_timeout=None
            ) as session:
                tasks = []
                # Get content_lengths
                for download_item in download_list:
                    link = download_item.link
                    if link:
                        task = asyncio.ensure_future(
                            self.json_request(
                                download_item.link,
                                session,
                                method="HEAD",
                                json_format=False,
                            )
                        )
                        tasks.append(task)
                responses = await asyncio.gather(*tasks)
                tasks.clear()

                async def check(download_item: media_table, response: ClientResponse):
                    filepath = os.path.join(
                        download_item.directory, download_item.filename
                    )
                    if response.status == 200:
                        if response.content_length:
                            download_item.size = response.content_length

                    if os.path.exists(filepath):
                        if os.path.getsize(filepath) == response.content_length:
                            download_item.downloaded = True
                        else:
                            return download_item
                    else:
                        return download_item

                for download_item in download_list:
                    temp_response = [
                        response
                        for response in responses
                        if response and response.url.name == download_item.filename
                    ]
                    if temp_response:
                        temp_response = temp_response[0]
                        task = check(download_item, temp_response)
                        tasks.append(task)
                result = await asyncio.gather(*tasks)
                download_list = [x for x in result if x]
                tasks.clear()
                progress_bar = None
                if download_list:
                    progress_bar = main_helper.download_session()
                    progress_bar.start(unit="B", unit_scale=True, miniters=1)
                    [progress_bar.update_total_size(x.size) for x in download_list]

                async def process_download(download_item: media_table):
                    response = await self.download_content(
                        download_item, session, progress_bar, subscription
                    )
                    if response:
                        data, download_item = response.values()
                        if data:
                            download_path = os.path.join(
                                download_item.directory, download_item.filename
                            )
                            os.makedirs(os.path.dirname(download_path), exist_ok=True)
                            with open(download_path, "wb") as f:
                                f.write(data)
                            download_item.size = len(data)
                            download_item.downloaded = True

                max_threads = calculate_max_threads(self.max_threads)
                download_groups = main_helper.grouper(max_threads, download_list)
                for download_group in download_groups:
                    tasks = []
                    for download_item in download_group:
                        task = process_download(download_item)
                        if task:
                            tasks.append(task)
                    result = await asyncio.gather(*tasks)
                if isinstance(progress_bar, main_helper.download_session):
                    progress_bar.close()
                return True

        results = await asyncio.ensure_future(run(download_list))
        return results

    async def download_content(
        self,
        download_item: media_table,
        session: ClientSession,
        progress_bar,
        subscription: create_user,
    ):
        attempt_count = 1
        new_task = {}
        while attempt_count <= 3:
            attempt_count += 1
            if not download_item.link:
                continue
            response: ClientResponse
            response, task = await asyncio.ensure_future(
                self.json_request(
                    download_item.link,
                    session,
                    json_format=False,
                    stream=True,
                    progress_bar=progress_bar,
                )
            )
            if response.status != 200:
                task = None
                if response.content_length:
                    progress_bar.update_total_size(-response.content_length)
                api_type = download_item.__module__.split(".")[-1]
                post_id = download_item.post_id
                new_result = None
                if api_type == "messages":
                    new_result = await subscription.get_message_by_id(
                        message_id=post_id
                    )
                elif api_type == "posts":
                    new_result = await subscription.get_post(post_id)
                    print
                if new_result and new_result.media:
                    media_list = [
                        x for x in new_result.media if x["id"] == download_item.media_id
                    ]
                    if media_list:
                        media = media_list[0]
                        quality = subscription.subscriber.extras["settings"][
                            "supported"
                        ]["onlyfans"]["settings"]["video_quality"]
                        link = main_helper.link_picker(media, quality)
                        download_item.link = link
                    continue
            new_task["response"] = task
            new_task["download_item"] = download_item
            break
        return new_task

    def session_rules(self, link: str) -> dict:
        headers = self.headers
        if "https://onlyfans.com/api2/v2/" in link:
            dynamic_rules = self.dynamic_rules
            headers["app-token"] = dynamic_rules["app_token"]
            # auth_id = headers["user-id"]
            a = [link, 0, dynamic_rules]
            headers2 = self.create_signed_headers(*a)
            headers |= headers2
        return headers

    def create_signed_headers(self, link: str, auth_id: int, dynamic_rules: dict):
        # Users: 300000 | Creators: 301000
        final_time = str(int(round(time.time())))
        path = urlparse(link).path
        query = urlparse(link).query
        path = path if not query else f"{path}?{query}"
        a = [dynamic_rules["static_param"], final_time, path, str(auth_id)]
        msg = "\n".join(a)
        message = msg.encode("utf-8")
        hash_object = hashlib.sha1(message)
        sha_1_sign = hash_object.hexdigest()
        sha_1_b = sha_1_sign.encode("ascii")
        checksum = (
            sum([sha_1_b[number] for number in dynamic_rules["checksum_indexes"]])
            + dynamic_rules["checksum_constant"]
        )
        headers = {}
        headers["sign"] = dynamic_rules["format"].format(sha_1_sign, abs(checksum))
        headers["time"] = final_time
        return headers


async def test_proxies(proxies: list[str]):
    final_proxies = []
    for proxy in proxies:
        connector = ProxyConnector.from_url(proxy) if proxy else None
        async with ClientSession(connector=connector) as session:
            link = "https://checkip.amazonaws.com"
            try:
                response = await session.get(link)
                ip = await response.text()
                ip = ip.strip()
                print("Session IP: " + ip + "\n")
                final_proxies.append(proxy)
            except python_socks._errors.ProxyConnectionError as e:
                print(f"Proxy Not Set: {proxy}\n")
                continue
    return final_proxies


def restore_missing_data(master_set2, media_set, split_by):
    count = 0
    new_set = []
    for item in media_set:
        if not item:
            link = master_set2[count]
            offset = int(link.split("?")[-1].split("&")[1].split("=")[1])
            limit = int(link.split("?")[-1].split("&")[0].split("=")[1])
            if limit == split_by + 1:
                break
            offset2 = offset
            limit2 = int(limit / split_by)
            for item in range(1, split_by + 1):
                link2 = link.replace("limit=" + str(limit), "limit=" + str(limit2))
                link2 = link2.replace("offset=" + str(offset), "offset=" + str(offset2))
                offset2 += limit2
                new_set.append(link2)
        count += 1
    new_set = new_set if new_set else master_set2
    return new_set


async def scrape_endpoint_links(links, session_manager: session_manager, api_type):
    media_set = []
    max_attempts = 100
    api_type = api_type.capitalize()
    for attempt in list(range(max_attempts)):
        if not links:
            continue
        print("Scrape Attempt: " + str(attempt + 1) + "/" + str(max_attempts))
        results = await session_manager.async_requests(links)
        not_faulty = [x for x in results if x]
        faulty = [
            {"key": k, "value": v, "link": links[k]}
            for k, v in enumerate(results)
            if not v
        ]
        last_number = len(results) - 1
        if faulty:
            positives = [x for x in faulty if x["key"] != last_number]
            false_positive = [x for x in faulty if x["key"] == last_number]
            if positives:
                attempt = attempt if attempt > 1 else attempt + 1
                num = int(len(faulty) * (100 / attempt))
                split_by = 2
                print("Missing " + str(num) + " Posts... Retrying...")
                links = restore_missing_data(links, results, split_by)
                media_set.extend(not_faulty)
            if not positives and false_positive:
                media_set.extend(results)
                break
            print
        else:
            media_set.extend(results)
            print("Found: " + api_type)
            break
    media_set = list(chain(*media_set))
    return media_set


def calculate_the_unpredictable(link, limit, multiplier=1):
    final_links = []
    a = list(range(1, multiplier + 1))
    for b in a:
        parsed_link = urlparse(link)
        q = parsed_link.query.split("&")
        offset = q[1]
        old_offset_num = int(re.findall("\\d+", offset)[0])
        new_offset_num = old_offset_num + (limit * b)
        new_link = link.replace(offset, f"offset={new_offset_num}")
        final_links.append(new_link)
    return final_links
