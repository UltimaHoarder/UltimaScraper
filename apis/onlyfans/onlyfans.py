import time
import base64
from typing import Optional, Union
from urllib.parse import urlparse
from urllib import parse
import hashlib
import math
from datetime import datetime
from dateutil.relativedelta import relativedelta
from itertools import chain, product
import requests

from sqlalchemy.orm.session import Session
from .. import api_helper
from mergedeep import merge, Strategy
import jsonpickle
import copy
from random import random


def create_headers(auth_id, user_agent="", x_bc="", sess="", link="https://onlyfans.com/"):
    headers = {}
    headers["user-agent"] = user_agent
    headers["referer"] = link
    headers["user-id"] = auth_id
    headers["x-bc"] = x_bc
    return headers


def create_signed_headers(link: str,  auth_id: int, dynamic_rules: dict):
    # Users: 300000 | Creators: 301000
    time2 = str(int(round(time.time())))
    path = urlparse(link).path
    query = urlparse(link).query
    path = path if not query else f"{path}?{query}"
    a = [dynamic_rules["static_param"], time2, path, str(auth_id)]
    msg = "\n".join(a)
    message = msg.encode("utf-8")
    hash_object = hashlib.sha1(message)
    sha_1_sign = hash_object.hexdigest()
    sha_1_b = sha_1_sign.encode("ascii")
    checksum = sum([sha_1_b[number] for number in dynamic_rules["checksum_indexes"]]
                   )+dynamic_rules["checksum_constant"]
    headers = {}
    headers["sign"] = dynamic_rules["format"].format(
        sha_1_sign, abs(checksum))
    headers["time"] = time2
    return headers


def session_rules(session_manager: api_helper.session_manager, link) -> dict:
    headers = session_manager.headers
    if "https://onlyfans.com/api2/v2/" in link:
        dynamic_rules = session_manager.dynamic_rules
        headers["app-token"] = "33d57ade8c02dbc5a333db99ff9ae26a"
        auth_id = headers["user-id"]
        a = [link, auth_id, dynamic_rules]
        headers2 = create_signed_headers(*a)
        headers |= headers2
    return headers


def session_retry_rules(r, link: str) -> int:
    """
    0 Fine, 1 Continue, 2 Break
    """
    status_code = 0
    if "https://onlyfans.com/api2/v2/" in link:
        text = r.text
        if "Invalid request sign" in text:
            status_code = 1
        elif "Access Denied" in text:
            status_code = 2
    else:
        if not r.status_code == 200:
            status_code = 1
    return status_code


class content_types():
    def __init__(self, option={}) -> None:
        class archived_types(content_types):
            def __init__(self) -> None:
                self.Posts = []
        self.Stories = []
        self.Posts = []
        self.Archived = archived_types()
        self.Chats = []
        self.Messages = []
        self.Highlights = []
        self.MassMessages = []

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class media_types():
    def __init__(self, option={}, assign_states=False) -> None:
        self.Images = option.get("Images", [])
        self.Videos = option.get("Videos", [])
        self.Audios = option.get("Audios", [])
        self.Texts = option.get("Texts", [])
        if assign_states:
            for k, v in self:
                setattr(self, k, assign_states())

    def remove_empty(self):
        copied = copy.deepcopy(self)
        for k, v in copied:
            if not v:
                delattr(self, k)
            print
        return self

    def get_status(self) -> list:
        x = []
        for key, item in self:
            for key2, item2 in item:
                new_status = list(chain.from_iterable(item2))
                x.extend(new_status)
        return x

    def extract(self, string: str) -> list:
        a = self.get_status()
        source_list = [getattr(x, string, None) for x in a]
        x = list(set(source_list))
        return x

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class auth_details():
    def __init__(self, option: dict = {}):
        self.username = option.get('username', "")
        self.auth_id = option.get('auth_id', "")
        self.sess = option.get('sess', "")
        self.user_agent = option.get('user_agent', "")
        self.auth_hash = option.get('auth_hash', "")
        self.auth_uniq_ = option.get('auth_uniq_', "")
        self.x_bc = option.get('x_bc', "")
        self.email = option.get('email', "")
        self.password = option.get('password', "")
        self.hashed = option.get('hashed', False)
        self.support_2fa = option.get('support_2fa', True)
        self.active = option.get('active', True)


class links(object):
    def __init__(self, identifier=None, identifier2=None, text="", only_links=True, global_limit=None, global_offset=None, app_token="33d57ade8c02dbc5a333db99ff9ae26a"):
        self.customer = f"https://onlyfans.com/api2/v2/users/me"
        self.users = f'https://onlyfans.com/api2/v2/users/{identifier}?app-token={app_token}'
        self.subscriptions = f"https://onlyfans.com/api2/v2/subscriptions/subscribes?limit=100&offset=0&type=active&app-token={app_token}"
        self.lists = f"https://onlyfans.com/api2/v2/lists?limit=100&offset=0&app-token={app_token}"
        self.lists_users = f"https://onlyfans.com/api2/v2/lists/{identifier}/users?limit=100&offset=0&query=&app-token={app_token}"
        self.list_chats = f"https://onlyfans.com/api2/v2/chats?limit=10&offset=0&order=desc&app-token={app_token}"
        self.post_by_id = f"https://onlyfans.com/api2/v2/posts/{identifier}"
        self.message_by_id = f"https://onlyfans.com/api2/v2/chats/{identifier}/messages?limit=10&offset=0&firstId={identifier2}&order=desc&skip_users=all&skip_users_dups=1"
        self.search_chat = f"https://onlyfans.com/api2/v2/chats/{identifier}/messages/search?query={text}&app-token={app_token}"
        self.message_api = f"https://onlyfans.com/api2/v2/chats/{identifier}/messages?limit=100&offset=0&order=desc&app-token={app_token}"
        self.search_messages = f"https://onlyfans.com/api2/v2/chats/{identifier}?limit=10&offset=0&filter=&order=activity&query={text}&app-token={app_token}"
        self.mass_messages_api = f"https://onlyfans.com/api2/v2/messages/queue/stats?limit=100&offset=0&format=infinite&app-token={app_token}"
        self.stories_api = f"https://onlyfans.com/api2/v2/users/{identifier}/stories?limit=100&offset=0&order=desc&app-token={app_token}"
        self.list_highlights = f"https://onlyfans.com/api2/v2/users/{identifier}/stories/highlights?limit=100&offset=0&order=desc&app-token={app_token}"
        self.highlight = f"https://onlyfans.com/api2/v2/stories/highlights/{identifier}?app-token={app_token}"
        self.post_api = f"https://onlyfans.com/api2/v2/users/{identifier}/posts?limit=100&offset=0&order=publish_date_desc&skip_users_dups=0"
        self.archived_posts = f"https://onlyfans.com/api2/v2/users/{identifier}/posts/archived?limit=100&offset=0&order=publish_date_desc&app-token={app_token}"
        self.archived_stories = f"https://onlyfans.com/api2/v2/stories/archive/?limit=100&offset=0&order=publish_date_desc&app-token={app_token}"
        self.paid_api = f"https://onlyfans.com/api2/v2/posts/paid?limit=100&offset=0&app-token={app_token}"
        self.pay = f"https://onlyfans.com/api2/v2/payments/pay"
        self.transactions = f"https://onlyfans.com/api2/v2/payments/all/transactions?limit=10&offset=0"
        self.two_factor = f"https://onlyfans.com/api2/v2/users/otp/check"
        full = {}
        items = self.__dict__.items()
        for key, link in items:
            parsed = urlparse(link)
            parameters = parse.parse_qsl(parsed.query)
            item2 = {}
            item2["link"] = link
            item2["max_limit"] = 0
            for parameter in parameters:
                if "limit" in parameter:
                    item2["max_limit"] = int(parameter[-1])
                    break
            max_limit = item2["max_limit"]
            for parameter in parameters:
                if "limit" in parameter and global_limit:
                    limit = max_limit if global_limit > max_limit else global_limit
                    og = "=".join(parameter)
                    item3 = f"limit={limit}"
                    link = link.replace(og, item3)
                if "offset" in parameter and global_offset:
                    og = "=".join(parameter)
                    item3 = f"offset={global_offset}"
                    link = link.replace(og, item3)
            item2["link"] = link
            full[key] = item2
            setattr(self, key, link)
        self.full = full


def handle_refresh(argument, argument2):
    argument = argument.get(
        argument2)
    return argument


class error_details():
    def __init__(self) -> None:
        self.code = None
        self.message = ""


class create_subscription():
    def __init__(self, option={}) -> None:
        class subscribedByData():
            def __init__(self, option={}) -> None:
                self.expiredAt = option.get("expiredAt")
                self.price = option.get("price")
                self.subscribePrice = option.get("subscribePrice")
        # Authed Creator Accounts Logic
        if "email" in option:
            option["is_me"] = True
            option["subscribedByData"] = dict()
            start_date = datetime.utcnow()
            end_date = start_date + relativedelta(years=1)
            end_date = end_date.isoformat()
            option["subscribedByData"]["expiredAt"] = end_date
            option["subscribedByData"]["price"] = option["subscribePrice"]
            option["subscribedByData"]["subscribePrice"] = 0
        self.id = option.get("id")
        self.username = option.get("username")
        if not self.username:
            self.username = f"u{self.id}"
        self.subscribedByData = subscribedByData(
            option.get("subscribedByData", {}))
        self.is_me = option.get("is_me", False)
        self.paid_content = option.get("paid_content", False)
        self.subscribePrice = option.get("subscribePrice", 0)
        self.postsCount = option.get("postsCount", 0)
        self.archivedPostsCount = option.get("archivedPostsCount", 0)
        self.photosCount = option.get("photosCount", 0)
        self.videosCount = option.get("videosCount", 0)
        self.audiosCount = option.get("audiosCount", 0)
        self.favoritedCount = option.get("favoritedCount", 0)
        self.avatar = option.get("avatar")
        self.header = option.get("header")
        self.hasStories = option.get("hasStories")
        self.link = option.get("link")
        self.links = content_types()
        self.scraped = content_types()
        self.auth_count = None
        self.session_manager: api_helper.session_manager = option.get(
            "session_manager")
        self.download_info = {}

        # Modify self
        valid_counts = ["postsCount", "archivedPostsCount"]
        identifier = self.id
        link_info = links(identifier=identifier).full
        x2 = [link_info["post_api"],
              link_info["archived_posts"]]
        items = dict(zip(valid_counts, x2))
        for key, value in items.items():
            if key in items:
                placement = ""
                key_name = ""
                if key == "postsCount":
                    key_name = "Posts"
                    placement = self.links
                elif key == "archivedPostsCount":
                    key_name = "Posts"
                    placement = self.links.Archived
                link = value["link"]
                max_limit = value["max_limit"]
                api_count = getattr(self, key)
                if api_count > 1500:
                    max_limit = 10
                ceil = math.ceil(api_count / max_limit)
                a = list(range(ceil))
                for b in a:
                    b = b * max_limit
                    link = link.replace(
                        f"limit={value['max_limit']}", f"limit={max_limit}")
                    new_link = link.replace(
                        "offset=0", f"offset={b}")
                    getattr(placement, key_name).append(new_link)
        print

    def get_stories(self, refresh=True, limit=100, offset=0) -> list:
        api_type = "stories"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        if not self.hasStories:
            return []
        link = [links(identifier=self.id, global_limit=limit,
                      global_offset=offset).stories_api]
        results = api_helper.scrape_check(link, self.session_manager, api_type)
        self.scraped.Stories = results
        return results

    def get_highlights(self, identifier="", refresh=True, limit=100, offset=0, hightlight_id="") -> list:
        api_type = "highlights"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        if not identifier:
            identifier = self.id
        if not hightlight_id:
            link = links(identifier=identifier, global_limit=limit,
                         global_offset=offset).list_highlights
        else:
            link = links(identifier=hightlight_id, global_limit=limit,
                         global_offset=offset).highlight
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        return results

    def get_posts(self, refresh=True, limit=99, offset=0) -> list:
        api_type = "posts"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        links = self.links.Posts
        results = api_helper.scrape_check(
            links, self.session_manager, api_type)
        self.scraped.Posts = results
        return results

    def get_post(self, identifier=None, limit=10, offset=0):
        if not identifier:
            identifier = self.id
        link = links(identifier=identifier, global_limit=limit,
                     global_offset=offset).post_by_id
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        item = {}
        item["session"] = session
        item["result"] = results
        return item

    def get_messages(self, identifier=None, resume=None, refresh=True, limit=10, offset=0):
        api_type = "messages"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        if not identifier:
            identifier = self.id
            if self.is_me:
                return []

        def process():
            link = links(identifier=identifier, global_limit=limit,
                         global_offset=offset).message_api
            session = self.session_manager.sessions[0]
            results = self.session_manager.json_request(link)
            item = {}
            item["session"] = session
            item["result"] = results
            return item
        unmerged = []
        while True:
            results = process()
            result = results["result"]
            error = result.get("error", None)
            if error:
                if error["code"] == 0:
                    break
            list = result["list"] if "list" in result else []
            if list:
                if resume:
                    for item in list:
                        if any(x["id"] == item["id"] for x in resume):
                            resume.sort(key=lambda x: x["id"], reverse=True)
                            self.scraped.Messages = resume
                            return resume
                        else:
                            resume.append(item)
                unmerged.append(result)
            if "hasMore" not in result:
                continue
            if not result["hasMore"]:
                break
            offset += limit
        results = merge({}, *unmerged, strategy=Strategy.ADDITIVE)
        self.scraped.Messages = [results]
        return results

    def get_message_by_id(self, identifier=None, identifier2=None, refresh=True, limit=10, offset=0):
        if not identifier:
            identifier = self.id
        link = links(identifier=identifier, identifier2=identifier2, global_limit=limit,
                     global_offset=offset).message_by_id
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        item = {}
        item["session"] = session
        item["result"] = results
        return item

    def get_archived_stories(self, refresh=True, limit=100, offset=0):
        api_type = "archived_stories"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        link = links(global_limit=limit,
                     global_offset=offset).archived_stories
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        self.archived_stories = results
        return results

    def get_archived_posts(self, refresh=True, limit=99, offset=0) -> list:
        api_type = "archived_posts"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        results = []
        links = self.links.Archived.Posts
        if links:
            results = api_helper.scrape_check(
                links, self.session_manager, api_type)
        self.scraped.Archived.Posts = results
        return results

    def get_archived(self, api):
        items = []
        if self.is_me:
            item = {}
            item["type"] = "Stories"
            item["results"] = [self.get_archived_stories()]
            items.append(item)
        item = {}
        item["type"] = "Posts"
        # item["results"] = test
        item["results"] = self.get_archived_posts()
        items.append(item)
        return items

    def search_chat(self, identifier="", text="", refresh=True, limit=10, offset=0):
        if identifier:
            identifier = parse.urljoin(identifier, "messages")
        link = links(identifier=identifier, text=text, global_limit=limit,
                     global_offset=offset).search_chat
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        return results

    def search_messages(self, identifier="", text="", refresh=True, limit=10, offset=0):
        if identifier:
            identifier = parse.urljoin(identifier, "messages")
        text = parse.quote_plus(text)
        link = links(identifier=identifier, text=text, global_limit=limit,
                     global_offset=offset).search_messages
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        return results

    def set_scraped(self, name, scraped: media_types):
        setattr(self.scraped, name, scraped)


class start():
    def __init__(self, custom_request=callable) -> None:
        self.auths: list[create_auth] = []
        self.custom_request = custom_request
        self.max_threads = -1
        self.lists = None
        self.links = links
        self.session_manager = api_helper.session_manager

    def set_auth_details(self, option={}):
        if not option.get("active"):
            return
        auth = create_auth()
        auth.auth_details = auth_details(option)
        self.auths.append(auth)
        return auth

    def set_auth(self, me):
        self.auth = me


class create_auth():
    def __init__(self, option={}, api: Optional[start] = None, init=False) -> None:
        self.id = option.get("id")
        self.username = option.get("username")
        if not self.username:
            self.username = f"u{self.id}"
        self.name = option.get("name")
        self.lists = {}
        self.links = content_types()
        self.isPerformer: bool = option.get("isPerformer")
        self.chatMessagesCount = option.get("chatMessagesCount")
        self.subscribesCount = option.get("subscribesCount")
        self.subscriptions = []
        self.chats = None
        self.archived_stories = {}
        self.mass_messages = []
        self.paid_content = {}
        self.session_manager = api_helper.session_manager(
            session_rules=session_rules, session_retry_rules=session_retry_rules)
        self.auth_details: Optional[auth_details] = None
        self.profile_directory = option.get("profile_directory", "")
        self.active = False
        self.errors: list[error_details] = []
        if api:
            api.auths.append(self)
        valid_counts = ["chatMessagesCount"]
        args = [self.username, False, False]
        link_info = links(*args).full
        x2 = [link_info["list_chats"]]
        items = dict(zip(valid_counts, x2))
        if not init:
            for key, value in items.items():
                if key in items:
                    key_name = ""
                    if key == "chatMessagesCount":
                        key_name = "Chats"
                    link = value["link"]
                    max_limit = value["max_limit"]
                    api_count = getattr(self, key)
                    if api_count:
                        ceil = math.ceil(api_count / max_limit)
                        a = list(range(ceil))
                        for b in a:
                            b = b * max_limit
                            getattr(self.links, key_name).append(link.replace(
                                "offset=0", "offset=" + str(b)))

    def login(self, full=False, max_attempts=10):
        auth_version = "(V1)"
        auth_items = self.auth_details
        link = links().customer
        user_agent = auth_items.user_agent
        auth_id = str(auth_items.auth_id)
        x_bc = auth_items.x_bc
        # expected string error is fixed by auth_id
        auth_cookies = [
            {'name': 'auth_id', 'value': auth_id},
            {'name': 'sess', 'value': auth_items.sess},
            {'name': 'auth_hash', 'value': auth_items.auth_hash},
            {'name': f'auth_uniq_{auth_id}', 'value': auth_items.auth_uniq_},
            {'name': f'auth_uid_{auth_id}', 'value': None},
        ]
        a = [auth_id, user_agent, x_bc, auth_items.sess, link]
        self.session_manager.headers = create_headers(*a)
        for session in self.session_manager.sessions:
            for auth_cookie in auth_cookies:
                session.cookies.set(**auth_cookie)
        count = 1
        while count < max_attempts + 1:
            string = f"Auth {auth_version} Attempt {count}/{max_attempts}"
            print(string)
            self.get_authed()
            count += 1

            def resolve_auth(auth: create_auth):
                if self.errors:
                    error = self.errors[-1]
                    print(error.message)
                    if error.code == 101:
                        if auth_items.support_2fa:
                            link = f"https://onlyfans.com/api2/v2/users/otp/check"
                            count = 1
                            max_count = 3
                            while count < max_count+1:
                                print("2FA Attempt "+str(count) +
                                      "/"+str(max_count))
                                code = input("Enter 2FA Code\n")
                                data = {'code': code, 'rememberMe': True}
                                r = self.session_manager.json_request(link,
                                                                      method="POST", data=data)
                                if "error" in r:
                                    error.message = r["error"]["message"]
                                    count += 1
                                else:
                                    print("Success")
                                    auth.active = True
                                    auth.errors.remove(error)
                                    break
            resolve_auth(self)
            if not self.active:
                if self.errors:
                    error = self.errors[-1]
                    error_message = error.message
                    if "token" in error_message:
                        break
                    if "Code wrong" in error_message:
                        break
                else:
                    print("Auth 404'ed")
                continue
            else:
                print(f"Welcome {self.name} | {self.username}")
                break
        return self

    def get_authed(self):
        if not self.active:
            link = links().customer
            r = self.session_manager.json_request(
                link, self.session_manager.sessions[0],  sleep=False)
            if r:
                self.resolve_auth_errors(r)
                if not self.errors:
                    me_api = create_auth(r)
                    me_api.active = True
                    me_api.session_manager = self.session_manager
                    self.__dict__.update(me_api.__dict__)
            else:
                # 404'ed
                self.active = False
        return self

    def resolve_auth_errors(self, r):
        # Adds an error object to self.auth.errors
        if 'error' in r:
            error = r["error"]
            error_message = r["error"]["message"]
            error_code = error["code"]
            error = error_details()
            if error_code == 0:
                pass
            if error_code == 101:
                error_message = "Blocked by 2FA."
            error.code = error_code
            error.message = error_message
            self.errors.append(error)

    def get_lists(self, refresh=True, limit=100, offset=0):
        api_type = "lists"
        if not self.active:
            return
        if not refresh:
            subscriptions = handle_refresh(self, api_type)
            return subscriptions
        link = links(global_limit=limit,
                     global_offset=offset).lists
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        self.lists = results
        return results

    def get_user(self, identifier):
        link = links(identifier).users
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        return results

    def get_lists_users(self, identifier, check: bool = False, refresh=True, limit=100, offset=0):
        if not self.active:
            return
        link = links(identifier, global_limit=limit,
                     global_offset=offset).lists_users
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        if len(results) >= limit and not check:
            results2 = self.get_lists_users(
                identifier, limit=limit, offset=limit+offset)
            results.extend(results2)
        return results

    def get_subscription(self, check: bool = False, identifier="", limit=100, offset=0) -> Union[create_subscription, None]:
        subscriptions = self.get_subscriptions(refresh=False)
        valid = None
        for subscription in subscriptions:
            if identifier == subscription.username or identifier == subscription.id:
                valid = subscription
                break
        return valid

    def get_subscriptions(self, resume=None, refresh=True, identifiers: list = [], extra_info=True, limit=20, offset=0) -> list[Union[create_subscription, None]]:
        if not self.active:
            return []
        if not refresh:
            subscriptions = self.subscriptions
            return subscriptions
        link = links(global_limit=limit, global_offset=offset).subscriptions
        session = self.session_manager.sessions[0]
        ceil = math.ceil(self.subscribesCount / limit)
        a = list(range(ceil))
        offset_array = []
        for b in a:
            b = b * limit
            link = links(global_limit=limit, global_offset=b).subscriptions
            offset_array.append(link)

        # Following logic is unique to creators only
        results = []
        if self.isPerformer:
            temp_session_manager = self.session_manager
            delattr(self, "session_manager")
            json_authed = jsonpickle.encode(
                self, unpicklable=False)
            json_authed = jsonpickle.decode(json_authed)
            self.session_manager = temp_session_manager
            json_authed = json_authed | self.get_user(self.username)

            subscription = create_subscription(json_authed)
            subscription.session_manager = self.session_manager
            subscription = [subscription]
            results.append(subscription)
        if not identifiers:
            def multi(item):
                link = item
                # link = item["link"]
                # session = item["session"]
                subscriptions = self.session_manager.json_request(link)
                valid_subscriptions = []
                extras = {}
                extras["auth_check"] = ""
                if isinstance(subscriptions, str):
                    input(subscriptions)
                    return
                subscriptions = [
                    subscription for subscription in subscriptions if "error" != subscription]
                for subscription in subscriptions:
                    subscription["session_manager"] = self.session_manager
                    if extra_info:
                        subscription2 = self.get_user(subscription["username"])
                        subscription = subscription | subscription2
                    subscription = create_subscription(subscription)
                    subscription.link = f"https://onlyfans.com/{subscription.username}"
                    valid_subscriptions.append(subscription)
                return valid_subscriptions
            pool = api_helper.multiprocessing()
            # offset_array= offset_array[:16]
            results += pool.starmap(multi, product(
                offset_array))
        else:
            for identifier in identifiers:
                if self.id == identifier or self.username == identifier:
                    continue
                link = links(identifier=identifier).users
                result = self.session_manager.json_request(link)
                if "error" in result or not result["subscribedBy"]:
                    continue
                subscription = create_subscription(result)
                subscription.link = f"https://onlyfans.com/{subscription.username}"
                subscription.session_manager = self.session_manager
                results.append([subscription])
                print
            print
        results = [x for x in results if x is not None]
        results = list(chain(*results))
        self.subscriptions = results
        return results

    def get_chats(self, resume=None, refresh=True, limit=10, offset=0):
        api_type = "chats"
        if not self.active:
            return
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        link = links(global_limit=limit,
                     global_offset=offset).list_chats
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        items = results["list"]
        if resume:
            for item in items:
                if any(x["id"] == item["id"] for x in resume):
                    resume.sort(key=lambda x: x["id"], reverse=True)
                    self.chats = resume
                    return resume
                else:
                    resume.append(item)

        if results["hasMore"]:
            results2 = self.get_chats(
                resume=resume, limit=limit, offset=limit+offset)
            items.extend(results2)
        if resume:
            items = resume

        items.sort(key=lambda x: x["withUser"]["id"], reverse=True)
        self.chats = items
        return items

    def get_mass_messages(self, resume=None, refresh=True, limit=10, offset=0) -> list:
        api_type = "mass_messages"
        if not self.active:
            return []
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        link = links(global_limit=limit,
                     global_offset=offset).mass_messages_api
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        items = results.get("list", [])
        if not items:
            return items
        if resume:
            for item in items:
                if any(x["id"] == item["id"] for x in resume):
                    resume.sort(key=lambda x: x["id"], reverse=True)
                    self.mass_messages = resume
                    return resume
                else:
                    resume.append(item)

        if results["hasMore"]:
            results2 = self.get_mass_messages(
                resume=resume, limit=limit, offset=limit+offset)
            items.extend(results2)
        if resume:
            items = resume

        items.sort(key=lambda x: x["id"], reverse=True)
        self.mass_messages = items
        return items

    def get_paid_content(self, check: bool = False, refresh: bool = True, limit: int = 99, offset: int = 0):
        api_type = "paid_content"
        if not self.active:
            return
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        link = links(global_limit=limit,
                     global_offset=offset).paid_api
        session = self.session_manager.sessions[0]
        results = self.session_manager.json_request(link)
        if len(results) >= limit and not check:
            results2 = self.get_paid_content(limit=limit, offset=limit+offset)
            results.extend(results2)
        self.paid_content = results
        return results
