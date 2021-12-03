import asyncio
import copy
import hashlib
import json
import os
import re
import threading
import time
from itertools import chain
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing.pool import Pool
from os.path import dirname as up
from random import randint
from typing import Any, Optional, Union
from urllib.parse import urlparse

import python_socks
import requests
from aiohttp import ClientSession
from aiohttp.client_exceptions import (
    ClientConnectorError,
    ClientOSError,
    ClientPayloadError,
    ContentTypeError,
    ServerDisconnectedError,
)
from aiohttp.client_reqrep import ClientResponse
from aiohttp_socks import ProxyConnectionError, ProxyConnector, ProxyError
from database.databases.user_data.models.media_table import template_media_table

import apis.onlyfans.classes as onlyfans_classes
onlyfans_extras = onlyfans_classes.extras
import apis.fansly.classes as fansly_classes
fansly_extras = fansly_classes.extras
import apis.starsavn.classes as starsavn_classes
starsavn_extras = starsavn_classes.extras

path = up(up(os.path.realpath(__file__)))
os.chdir(path)


global_settings: dict[str, Any] = {}
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


def multiprocessing(max_threads: Optional[int] = None):
    max_threads = calculate_max_threads(max_threads)
    pool = ThreadPool(max_threads)
    return pool


class session_manager:
    def __init__(
        self,
        auth: Union[onlyfans_classes.create_auth, fansly_classes.create_auth],
        headers: dict[str, Any] = {},
        proxies: list[str] = [],
        max_threads: int = -1,
        use_cookies: bool = True,
    ) -> None:
        self.pool: Pool = auth.pool if auth.pool else multiprocessing()
        self.max_threads = max_threads
        self.kill = False
        self.headers = headers
        self.proxies: list[str] = proxies
        dr_link = global_settings["dynamic_rules_link"]
        dynamic_rules = requests.get(dr_link).json()  # type: ignore
        self.dynamic_rules = dynamic_rules
        self.auth = auth
        self.use_cookies: bool = use_cookies

    def create_client_session(self):
        proxy = self.get_proxy()
        connector = ProxyConnector.from_url(proxy) if proxy else None

        final_cookies = (
            self.auth.auth_details.cookie.format() if self.use_cookies else {}
        )
        client_session = ClientSession(
            connector=connector, cookies=final_cookies, read_timeout=None
        )
        return client_session

    def get_proxy(self) -> str:
        proxies = self.proxies
        proxy = self.proxies[randint(0, len(proxies) - 1)] if proxies else ""
        return proxy

    def stimulate_sessions(self):
        # Some proxies switch IP addresses if no request have been made for x amount of secondss
        def do(session_manager):
            while not session_manager.kill:
                for session in session_manager.sessions:

                    def process_links(link, session):
                        response = session.get(link)
                        text = response.text.strip("\n")
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
        method: str = "GET",
        stream: bool = False,
        json_format: bool = True,
        payload: dict[str, str] = {},
    ) -> Any:
        headers = {}
        custom_session = False
        if not session:
            custom_session = True
            session = self.create_client_session()
        headers = self.session_rules(link)
        headers["accept"] = "application/json, text/plain, */*"
        headers["Connection"] = "keep-alive"
        temp_payload = payload.copy()

        request_method = None
        result = None
        if method == "HEAD":
            request_method = session.head
        elif method == "GET":
            request_method = session.get
        elif method == "POST":
            request_method = session.post
            headers["content-type"] = "application/json"
            temp_payload = json.dumps(payload)
        elif method == "DELETE":
            request_method = session.delete
        else:
            return None
        while True:
            try:
                response = await request_method(
                    link, headers=headers, data=temp_payload
                )
                if method == "HEAD":
                    result = response
                else:
                    if json_format and not stream:
                        result = await response.json()
                        if "error" in result:
                            if isinstance(self.auth, onlyfans_classes.create_auth):
                                result = onlyfans_extras.error_details(result)
                            elif isinstance(self.auth, fansly_classes.create_auth):
                                result = fansly_extras.error_details(result)
                    elif stream and not json_format:
                        result = response
                    else:
                        result = await response.read()
                break
            except (ClientConnectorError, ProxyError):
                break
            except (
                ClientPayloadError,
                ContentTypeError,
                ClientOSError,
                ServerDisconnectedError,
                ProxyConnectionError,
                ConnectionResetError,
            ):
                continue
        if custom_session:
            await session.close()
        return result

    async def async_requests(self, items: list[str]) -> list[dict[str,Any]]:
        tasks = []

        async def run(links: list[str]) -> list:
            proxies = self.proxies
            proxy = self.proxies[randint(0, len(proxies) - 1)] if proxies else ""
            connector = ProxyConnector.from_url(proxy) if proxy else None
            temp_cookies: dict[Any, Any] = (
                self.auth.auth_details.cookie.format()
                if hasattr(self.auth.auth_details, "cookie")
                else {}
            )
            async with ClientSession(
                connector=connector,
                cookies=temp_cookies,
                read_timeout=None,
            ) as session:
                for link in links:
                    task = asyncio.ensure_future(self.json_request(link, session))
                    tasks.append(task)
                responses = list(await asyncio.gather(*tasks))
                return responses

        results = await asyncio.ensure_future(run(items))
        return results

    async def download_content(
        self,
        download_item: template_media_table,
        session: ClientSession,
        progress_bar,
        subscription: onlyfans_classes.create_user,
    ):
        attempt_count = 1
        new_task = {}
        while attempt_count <= 3:
            attempt_count += 1
            if not download_item.link:
                continue
            response: ClientResponse
            response = await asyncio.ensure_future(
                self.json_request(
                    download_item.link,
                    session,
                    json_format=False,
                    stream=True,
                )
            )
            if response and response.status != 200:
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
                if isinstance(new_result, onlyfans_extras.error_details):
                    continue
                if new_result and new_result.media:
                    media_list = [
                        x for x in new_result.media if x["id"] == download_item.media_id
                    ]
                    if media_list:
                        media = media_list[0]
                        quality = subscription.subscriber.extras["settings"][
                            "supported"
                        ]["onlyfans"]["settings"]["video_quality"]
                        link = await new_result.link_picker(media, quality)
                        download_item.link = link
                    continue
            new_task["response"] = response
            new_task["download_item"] = download_item
            break
        return new_task

    def session_rules(self, link: str) -> dict[str, Any]:
        headers = self.headers
        if "https://onlyfans.com/api2/v2/" in link:
            dynamic_rules = self.dynamic_rules
            headers["app-token"] = dynamic_rules["app_token"]
            # auth_id = headers["user-id"]
            a = [link, 0, dynamic_rules]
            headers2 = self.create_signed_headers(*a)
            headers |= headers2
        elif "https://apiv2.fansly.com" in link and isinstance(
            self.auth.auth_details, fansly_extras.auth_details
        ):
            headers["authorization"] = self.auth.auth_details.authorization
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
            except python_socks._errors.ProxyConnectionError|python_socks._errors.ProxyError as e:
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


async def scrape_endpoint_links(links:list[str], session_manager: Union[session_manager,None], api_type:str):
    media_set:list[dict[str,str]] = []
    max_attempts = 100
    api_type = api_type.capitalize()
    for attempt in list(range(max_attempts)):
        if not links:
            continue
        print("Scrape Attempt: " + str(attempt + 1) + "/" + str(max_attempts))
        results = await session_manager.async_requests(links)
        match type(session_manager.auth):
            case starsavn_classes.create_auth:
                results = await starsavn_extras.remove_errors(results)
            case _:
                results = await onlyfans_extras.remove_errors(results)
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
                media_set.extend(not_faulty)
                break
            print
        else:
            media_set.extend(not_faulty)
            break
    final_media_set = list(chain(*media_set))
    return final_media_set


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

def parse_config_inputs(custom_input:Any) -> list[str]:
    if isinstance(custom_input,str):
        custom_input = custom_input.split(",")
    return custom_input