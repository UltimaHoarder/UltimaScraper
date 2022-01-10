from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import random
import re
import string
import time
from argparse import Namespace
from itertools import chain
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing.pool import Pool
from os.path import dirname as up
from random import randint
from typing import TYPE_CHECKING, Any, Optional
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
from mergedeep.mergedeep import Strategy, merge


def load_classes():
    import apis.fansly.classes as fansly_classes
    import apis.onlyfans.classes as onlyfans_classes
    import apis.starsavn.classes as starsavn_classes

    return onlyfans_classes, fansly_classes, starsavn_classes


def load_classes2():
    onlyfans_classes, fansly_classes, starsavn_classes = load_classes()
    auth_types = (
        onlyfans_classes.auth_model.create_auth
        | fansly_classes.auth_model.create_auth
        | starsavn_classes.auth_model.create_auth
    )
    user_types = (
        onlyfans_classes.user_model.create_user
        | fansly_classes.user_model.create_user
        | starsavn_classes.user_model.create_user
    )
    return auth_types, user_types


def load_extras():
    onlyfans_classes, fansly_classes, starsavn_classes = load_classes()
    return onlyfans_classes.extras, fansly_classes.extras, starsavn_classes.extras


if TYPE_CHECKING:
    onlyfans_classes, fansly_classes, starsavn_classes = load_classes()
    auth_types, user_types = load_classes2()
    onlyfans_extras, fansly_extras, starsavn_extras = load_extras()
    error_details_types = (
        onlyfans_extras.ErrorDetails
        | fansly_extras.ErrorDetails
        | starsavn_extras.ErrorDetails
    )
parsed_args = Namespace()

import sys
if getattr(sys, "frozen", False):
    path = up(sys.executable)
else:
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


def multiprocessing(max_threads: Optional[int] = None):
    max_threads = calculate_max_threads(max_threads)
    pool: Pool = ThreadPool(max_threads)
    return pool


def calculate_max_threads(max_threads: Optional[int] = None):
    if not max_threads:
        max_threads = -1
    max_threads2 = cpu_count()
    if max_threads < 1 or max_threads >= max_threads2:
        max_threads = max_threads2
    return max_threads


class session_manager:
    def __init__(
        self,
        auth: auth_types,
        headers: dict[str, Any] = {},
        proxies: list[str] = [],
        max_threads: int = -1,
        use_cookies: bool = True,
    ) -> None:
        self.pool: Pool = auth.pool if auth.pool else multiprocessing()
        max_threads = calculate_max_threads(max_threads)
        self.semaphore = asyncio.BoundedSemaphore(max_threads)
        self.max_threads = max_threads
        self.kill = False
        self.headers = headers
        self.proxies: list[str] = proxies
        dr_link = global_settings["dynamic_rules_link"]
        dynamic_rules = requests.get(dr_link).json()  # type: ignore
        self.dynamic_rules = dynamic_rules
        self.auth = auth
        self.use_cookies: bool = use_cookies

    async def get_cookies(self):
        _onlyfans_classes, fansly_classes, _starsavn_classes = load_classes()
        if isinstance(self.auth, fansly_classes.auth_model.create_auth):
            final_cookies: dict[str, Any] = {}
        else:
            final_cookies = self.auth.auth_details.cookie.format()
        return final_cookies

    async def create_client_session(self):
        proxy = self.get_proxy()
        connector = ProxyConnector.from_url(proxy) if proxy else None
        final_cookies = await self.get_cookies()
        client_session = ClientSession(
            connector=connector, cookies=final_cookies, read_timeout=None
        )
        return client_session

    def get_proxy(self) -> str:
        proxies = self.proxies
        proxy = self.proxies[randint(0, len(proxies) - 1)] if proxies else ""
        return proxy

    async def json_request(
        self,
        link: str,
        session: Optional[ClientSession] = None,
        method: str = "GET",
        stream: bool = False,
        json_format: bool = True,
        payload: dict[str, str | bool] = {},
        _handle_error_details: bool = True,
    ) -> Any:
        async with self.semaphore:
            headers = {}
            custom_session = False
            if not session:
                custom_session = True
                session = await self.create_client_session()
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

                                (
                                    onlyfans_classes,
                                    fansly_classes,
                                    _starsavn_classes,
                                ) = load_classes()
                                (
                                    onlyfans_extras,
                                    fansly_extras,
                                    _starsavn_extras,
                                ) = load_extras()
                                extras: dict[str, Any] = {}
                                extras["auth"] = self.auth
                                extras["link"] = link
                                if isinstance(
                                    self.auth, onlyfans_classes.auth_model.create_auth
                                ):
                                    result = await onlyfans_extras.ErrorDetails(
                                        result
                                    ).format(extras)
                                elif isinstance(
                                    self.auth, fansly_classes.auth_model.create_auth
                                ):
                                    result = fansly_extras.ErrorDetails(result)

                                if _handle_error_details:
                                    await handle_error_details(result)
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

    async def async_requests(self, items: list[str]) -> list[dict[str, Any]]:
        tasks: list[Any] = []

        async def run(links: list[str]):
            proxies = self.proxies
            proxy = self.proxies[randint(0, len(proxies) - 1)] if proxies else ""
            connector = ProxyConnector.from_url(proxy) if proxy else None
            temp_cookies = await self.get_cookies()
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
        onlyfans_extras, _fansly_extras, _starsavn_extras = load_extras()
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
                if isinstance(new_result, onlyfans_extras.ErrorDetails):
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

    def session_rules(
        self, link: str, signed_headers: dict[str, Any] = {}
    ) -> dict[str, Any]:
        _onlyfans_extras, fansly_extras, _starsavn_extras = load_extras()
        headers: dict[str, Any] = {}
        headers |= self.headers
        if "https://onlyfans.com/api2/v2/" in link:
            dynamic_rules = self.dynamic_rules
            headers["app-token"] = dynamic_rules["app_token"]
            if self.auth.guest:
                headers["x-bc"] = "".join(
                    random.choice(string.digits + string.ascii_lowercase)
                    for _ in range(40)
                )
            headers2 = self.create_signed_headers(link)
            headers |= headers2
        elif "https://apiv2.fansly.com" in link and isinstance(
            self.auth.auth_details, fansly_extras.auth_details
        ):
            headers["authorization"] = self.auth.auth_details.authorization
        return headers

    def create_signed_headers(
        self, link: str, auth_id: int = 0, time_: Optional[int] = None
    ):
        # Users: 300000 | Creators: 301000
        headers: dict[str, Any] = {}
        final_time = str(int(round(time.time()))) if not time_ else str(time_)
        path = urlparse(link).path
        query = urlparse(link).query
        if query:
            auth_id = self.auth.id if self.auth.id else auth_id
            headers["user-id"] = str(auth_id)
        path = path if not query else f"{path}?{query}"
        dynamic_rules = self.dynamic_rules
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
            except python_socks._errors.ProxyConnectionError | python_socks._errors.ProxyError as e:
                print(f"Proxy Not Set: {proxy}\n")
                continue
    return final_proxies


def restore_missing_data(master_set2: list[str], media_set, split_by):
    count = 0
    new_set: set[str] = set()
    for item in media_set:
        if not item:
            link = master_set2[count]
            offset = int(link.split("?")[-1].split("&")[1].split("=")[1])
            limit = int(link.split("?")[-1].split("&")[0].split("=")[1])
            if limit == split_by + 1:
                break
            offset2 = offset
            limit2 = int(limit / split_by) if limit > 1 else 1
            for item in range(1, split_by + 1):
                link2 = link.replace("limit=" + str(limit), "limit=" + str(limit2))
                link2 = link2.replace("offset=" + str(offset), "offset=" + str(offset2))
                offset2 += limit2
                new_set.add(link2)
        count += 1
    new_set = new_set if new_set else master_set2
    return list(new_set)


async def scrape_endpoint_links(
    links: list[str], session_manager: session_manager | None
):
    media_set: list[dict[str, str]] = []
    max_attempts = 100
    for attempt in list(range(max_attempts)):
        if not links or not session_manager:
            continue
        print("Scrape Attempt: " + str(attempt + 1) + "/" + str(max_attempts))
        results = await session_manager.async_requests(links)
        results = await handle_error_details(results, True, session_manager.auth)
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
        else:
            media_set.extend(not_faulty)
            break
    if media_set and "list" in media_set[0]:
        final_media_set = list(chain(*[x["list"] for x in media_set]))
    else:
        final_media_set = list(chain(*media_set))
    return final_media_set


def calculate_the_unpredictable(link: str, limit: int, multiplier: int = 1):
    final_links: list[str] = []
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


def parse_config_inputs(custom_input: Any) -> list[str]:
    if isinstance(custom_input, str):
        custom_input = custom_input.split(",")
    return custom_input


async def handle_error_details(
    item: error_details_types
    | dict[str, Any]
    | list[dict[str, Any]]
    | list[error_details_types],
    remove_errors: bool = False,
    api_type: Optional[auth_types] = None,
):
    results = []
    if isinstance(item, list):
        if remove_errors and api_type:
            onlyfans_classes, fansly_classes, _starsavn_classes = load_classes()
            onlyfans_extras, fansly_extras, starsavn_extras = load_extras()
            # if isinstance(item, onlyfans_extras.ErrorDetails):
            #     results = await onlyfans_extras.remove_errors(item)
            if isinstance(api_type, onlyfans_classes.auth_model.create_auth):
                results = await onlyfans_extras.remove_errors(item)
            elif isinstance(api_type, fansly_classes.auth_model.create_auth):
                results = await fansly_extras.remove_errors(item)
            else:
                results = await starsavn_extras.remove_errors(item)
    else:
        if parsed_args.verbose:
            # Will move to logging instead of printing later.
            print(f"Error: {item.__dict__}")
    return results


async def get_function_name(
    function_that_called: str = "", convert_to_api_type: bool = False
):
    if not function_that_called:
        function_that_called = inspect.stack()[1].function
    if convert_to_api_type:
        return function_that_called.split("_")[-1].capitalize()
    return function_that_called


async def handle_refresh(
    api: auth_types | user_types,
    api_type: str,
    refresh: bool,
    function_that_called: str,
):
    result: list[Any] = []
    # If refresh is False, get already set data
    if not api_type and not refresh:
        api_type = (
            await get_function_name(function_that_called, True)
            if not api_type
            else api_type
        )
        try:
            # We assume the class type is create_user
            result = getattr(api.temp_scraped, api_type)
        except AttributeError:
            # we assume the class type is create_auth
            api_type = api_type.lower()
            result = getattr(api, api_type)

    return result


async def default_data(
    api: auth_types | user_types, refresh: bool = False, api_type: str = ""
):
    status: bool = False
    result: list[Any] = []
    function_that_called = inspect.stack()[1].function
    auth_types, _user_types = load_classes2()
    if isinstance(api, auth_types):
        # create_auth class
        auth = api
        match function_that_called:
            case function_that_called if function_that_called in [
                "get_paid_content",
                "get_chats",
                "get_lists_users",
                "get_subscriptions",
            ]:
                if not auth.active or not refresh:
                    result = await handle_refresh(
                        auth, api_type, refresh, function_that_called
                    )
                    status = True
            case "get_mass_messages":
                if not auth.active or not auth.isPerformer:
                    result = await handle_refresh(
                        auth, api_type, refresh, function_that_called
                    )
                    status = True
            case _:
                result = await handle_refresh(
                    auth, api_type, refresh, function_that_called
                )
                if result:
                    status = True
    else:
        # create_user class
        user = api
        match function_that_called:
            case "get_stories":
                if not user.hasStories:
                    result = await handle_refresh(
                        user, api_type, refresh, function_that_called
                    )
                    status = True
            case "get_messages":
                if user.is_me():
                    result = await handle_refresh(
                        user, api_type, refresh, function_that_called
                    )
                    status = True
            case function_that_called if function_that_called in [
                "get_archived_stories"
            ]:
                if not (user.is_me() and user.isPerformer):
                    result = await handle_refresh(
                        user, api_type, refresh, function_that_called
                    )
                    status = True
            case _:
                result = await handle_refresh(
                    user, api_type, refresh, function_that_called
                )
                if result:
                    status = True
    return result, status


def merge_dictionaries(items: list[dict[str, Any]]):
    final_dictionary: dict[str, Any] = merge({}, *items, strategy=Strategy.ADDITIVE)  # type: ignore
    return final_dictionary
