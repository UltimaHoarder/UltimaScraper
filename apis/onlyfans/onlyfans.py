import re
import time
from time import sleep
from typing import Any
from urllib.parse import urlparse
from urllib import parse
import hashlib
import math
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from itertools import chain, groupby, product
from multiprocessing.dummy import Pool as ThreadPool
from types import SimpleNamespace
import json
from .. import api_helper
from mergedeep import merge, Strategy


# Zero reason to do this lmao


def create_sign(session, link, sess, user_agent, text="onlyfans"):
    # Users: 300000 | Creators: 301000
    time2 = str(int(round(time.time() * 1000-301000)))
    path = urlparse(link).path
    query = urlparse(link).query
    path = path+"?"+query
    a = [sess, time2, path, user_agent, text]
    msg = "\n".join(a)
    message = msg.encode("utf-8")
    hash_object = hashlib.sha1(message)
    sha_1 = hash_object.hexdigest()
    session.headers["access-token"] = sess
    session.headers["sign"] = sha_1
    session.headers["time"] = time2
    return session


def session_rules(session, link):
    if "https://onlyfans.com/api2/v2/" in link:
        sess = session.headers["access-token"]
        user_agent = session.headers["user-agent"]
        a = [session, link, sess, user_agent]
        session = create_sign(*a)
    return session


def session_retry_rules(r, link):
    # 0 Fine, 1 Continue, 2 Break
    boolean = 0
    if "https://onlyfans.com/api2/v2/" in link:
        text = r.text
        if "Invalid request sign" in text:
            boolean = 1
        elif "Access Denied" in text:
            boolean = 2
    else:
        if not r.status_code == 200:
            boolean = 1
    return boolean


class media_types():
    def __init__(self, option={}) -> None:
        self.Images = option.get("Images")
        self.Videos = option.get("Videos")
        self.Audios = option.get("Audios")
        self.Texts = option.get("Texts")

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class media_types2():
    def __init__(self, option={}) -> None:
        self.Images = option.get("Images")
        self.Videos = option.get("Videos")
        self.Audios = option.get("Audios")
        self.Texts = option.get("Texts")

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class content_types:
    def __init__(self, option={}) -> None:
        class archived_types():
            Posts = []

        def __iter__(self):
            for attr, value in self.__dict__.items():
                yield attr, value
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


class auth_details():
    def __init__(self, option={}):
        self.username = option.get('username', "")
        self.auth_id = option.get('auth_id', "")
        self.auth_hash = option.get('auth_hash', "")
        self.auth_uniq_ = option.get('auth_uniq_', "")
        self.sess = option.get('sess', "")
        self.app_token = option.get(
            'app_token', '33d57ade8c02dbc5a333db99ff9ae26a')
        self.user_agent = option.get('user_agent', "")
        self.support_2fa = option.get('support_2fa', True)


class links(object):
    def __init__(self, identifier=None, identifier2=None, text="", only_links=True, global_limit=None, global_offset=None, app_token="33d57ade8c02dbc5a333db99ff9ae26a"):
        self.customer = f"https://onlyfans.com/api2/v2/users/customer?app-token={app_token}"
        self.users = f'https://onlyfans.com/api2/v2/users/{identifier}?app-token={app_token}'
        self.subscriptions = f"https://onlyfans.com/api2/v2/subscriptions/subscribes?limit=100&offset=0&type=active&app-token={app_token}"
        self.lists = f"https://onlyfans.com/api2/v2/lists?limit=100&offset=0&app-token={app_token}"
        self.lists_users = f"https://onlyfans.com/api2/v2/lists/{identifier}/users?limit=100&offset=0&query=&app-token={app_token}"
        self.list_chats = f"https://onlyfans.com/api2/v2/chats?limit=10&offset=0&order=desc&app-token={app_token}"
        self.message_by_id = f"https://onlyfans.com/api2/v2/chats/{identifier}/messages?limit=10&offset=0&firstId={identifier2}&order=desc&skip_users=all&skip_users_dups=1&app-token=33d57ade8c02dbc5a333db99ff9ae26a"
        self.search_chat = f"https://onlyfans.com/api2/v2/chats/{identifier}/messages/search?query={text}&app-token={app_token}"
        self.message_api = f"https://onlyfans.com/api2/v2/chats/{identifier}/messages?limit=100&offset=0&order=desc&app-token={app_token}"
        self.search_messages = f"https://onlyfans.com/api2/v2/chats/{identifier}?limit=10&offset=0&filter=&order=activity&query={text}&app-token={app_token}"
        self.mass_messages_api = f"https://onlyfans.com/api2/v2/messages/queue/stats?limit=100&offset=0&format=infinite&app-token={app_token}"
        self.stories_api = f"https://onlyfans.com/api2/v2/users/{identifier}/stories?limit=100&offset=0&order=desc&app-token={app_token}"
        self.list_highlights = f"https://onlyfans.com/api2/v2/users/{identifier}/stories/highlights?limit=100&offset=0&order=desc&app-token={app_token}"
        self.highlight = f"https://onlyfans.com/api2/v2/stories/highlights/{identifier}?app-token={app_token}"
        self.post_api = f"https://onlyfans.com/api2/v2/users/{identifier}/posts?limit=100&offset=0&order=publish_date_desc&skip_users_dups=0&app-token={app_token}"
        self.archived_posts = f"https://onlyfans.com/api2/v2/users/{identifier}/posts/archived?limit=100&offset=0&order=publish_date_desc&app-token={app_token}"
        self.archived_stories = f"https://onlyfans.com/api2/v2/stories/archive/?limit=100&offset=0&order=publish_date_desc&app-token={app_token}"
        self.paid_api = f"https://onlyfans.com/api2/v2/posts/paid?limit=100&offset=0&app-token={app_token}"
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


class start():
    def __init__(self, sessions=None, custom_request=callable) -> None:
        self.sessions = sessions
        self.auth = None
        self.custom_request = custom_request
        self.auth_details = None
        self.max_threads = -1
        self.links = links
        for session in sessions:
            session.headers["access-token"] = ""
            session.headers["sign"] = ""
            session.headers["time"] = ""
        api_helper.request_parameters(session_rules, session_retry_rules)
        self.json_request = api_helper.json_request

    def request(self, link="", session=None, format=False) -> Any:
        link2 = link
        if isinstance(link2, list):
            links = link2
            links = api_helper.assign_session(links, self.sessions)
            pool = api_helper.multiprocessing()
            r = pool.starmap(self.request, product(
                links, [None], [True]))
        else:
            if not session:
                session = self.sessions[0]
            if isinstance(link2, dict):
                session = self.sessions[link2["count"]]
                link2 = link2["link"]
            r = api_helper.json_request(link2, session)
        if format:
            item = {}
            item["session"] = session
            item["result"] = r
            return item
        return r

    def auth_check(self):
        result = False
        auth = self.get_authed()
        if not auth or "error" in auth:
            if not self.auth_details:
                print("Not Authed")
            else:
                result = self.login()
        else:
            result = auth
        if not result:
            print("Could not authenticate")
        return result

    def set_auth_details(self, username=None, auth_id=None, auth_hash=None, auth_uniq_=None, sess=None, app_token=None, user_agent=None, support_2fa=None, global_user_agent=None):
        user_agent = global_user_agent if not user_agent else user_agent
        option = locals()
        auth = auth_details(option)
        self.auth_details = auth

    def login(self, full=False, max_attempts=10):
        auth_version = "(V1)"
        auth_items = self.auth_details
        self.auth = None
        link = links().customer
        user_agent = auth_items.user_agent
        auth_id = auth_items.auth_id
        app_token = auth_items.app_token
        auth_cookies = [
            {'name': 'auth_id', 'value': auth_id},
            {'name': 'sess', 'value': auth_items.sess},
            {'name': 'auth_hash', 'value': auth_items.auth_hash},
            {'name': 'auth_uniq_'+auth_id, 'value': auth_items.auth_uniq_},
            {'name': 'auth_uid_'+auth_id, 'value': None},
        ]
        for session in self.sessions:
            a = [session, link, auth_items.sess, user_agent]
            session = create_sign(*a)
            session.headers["user-agent"] = user_agent
            session.headers["referer"] = 'https://onlyfans.com/'
            for auth_cookie in auth_cookies:
                session.cookies.set(**auth_cookie)
        count = 1
        while count < max_attempts+1:
            string = f"Auth {auth_version} Attempt {count}/{max_attempts}"
            print(string)
            me_api = self.get_authed()
            count += 1
            if not me_api:
                continue

            def resolve_auth(r):
                if 'error' in r:
                    error = r["error"]
                    error_message = r["error"]["message"]
                    error_code = error["code"]
                    if error_code == 0:
                        print(error_message)
                    if error_code == 101:
                        error_message = "Blocked by 2FA."
                        print(error_message)
                        if auth_items.support_2fa:
                            link = f"https://onlyfans.com/api2/v2/users/otp?app-token={app_token}"
                            count = 1
                            max_count = 3
                            while count < max_count+1:
                                print("2FA Attempt "+str(count) +
                                      "/"+str(max_count))
                                code = input("Enter 2FA Code\n")
                                data = {'code': code, 'rememberMe': True}
                                r = api_helper.json_request(link,
                                                            self.sessions[0], method="PUT", data=data)
                                if "error" in r:
                                    count += 1
                                else:
                                    print("Success")
                                    return [True, r]
                    return [False, r["error"]["message"]]
            if "name" not in me_api:
                result = resolve_auth(me_api)
                if not result[0]:
                    error_message = result[1]
                    if "token" in error_message:
                        break
                    if "Code wrong" in error_message:
                        break
                    continue
                else:
                    continue
            print("Welcome "+me_api["name"])
            me_api["links"] = content_types()
            valid_counts = ["chatMessagesCount"]
            args = [me_api["username"], False, False]
            link_info = self.links(*args).full
            x2 = [link_info["list_chats"]]
            items = dict(zip(valid_counts, x2))
            for key, value in items.items():
                if key in items:
                    key_name = ""
                    if key == "chatMessagesCount":
                        key_name = "Chats"
                    link = value["link"]
                    max_limit = value["max_limit"]
                    api_count = me_api.get(key)
                    ceil = math.ceil(api_count / max_limit)
                    a = list(range(ceil))
                    for b in a:
                        b = b * max_limit
                        getattr(me_api["links"], key_name).append(link.replace(
                            "offset=0", "offset=" + str(b)))
            self.set_auth(me_api)
            return self.auth

    def get_authed(self):
        if not self.auth:
            link = links().customer
            r = api_helper.json_request(link, self.sessions[0],  sleep=False)
        else:
            r = self.auth
        return r

    def set_auth(self, me):
        self.auth = me

    def get_user(self, identifier):
        link = links(identifier).users
        r = self.request(link=link)
        return r

    def get_subscriptions(self, refresh=True, extra_info=True, limit=20, offset=0):
        authed = self.auth_check()
        if not authed:
            return
        if not refresh:
            subscriptions = authed.get(
                "subscriptions")
            if subscriptions:
                return subscriptions
        link = links(global_limit=limit, global_offset=offset).subscriptions
        session = self.sessions[0]
        ceil = math.ceil(authed["subscribesCount"] / limit)
        a = list(range(ceil))
        offset_array = []
        for b in a:
            b = b * limit
            link = links(global_limit=limit, global_offset=b).subscriptions
            offset_array.append(link)
        performer = authed["isPerformer"]

        # Following logic is unique to creators only
        results = []
        if performer:
            r = self.get_user(authed["username"])
            if not r["subscribedByData"]:
                r["is_me"] = True
                r["subscribedByData"] = dict()
                start_date = datetime.utcnow()
                end_date = start_date + relativedelta(years=1)
                end_date = end_date.isoformat()
                r["subscribedByData"]["expiredAt"] = end_date
                r["subscribedByData"]["price"] = r["subscribePrice"]
                r["subscribedByData"]["subscribePrice"] = 0
                r["sessions"] = self.sessions

            subscription = [create_subscription(r)]
            results.append(subscription)

        def multi(item, session=None):
            link = item
            # link = item["link"]
            # session = item["session"]
            subscriptions = self.request(session=session, link=link)
            valid_subscriptions = []
            extras = {}
            extras["auth_check"] = ""
            for subscription in subscriptions:
                subscription["sessions"] = self.sessions
                if extra_info:
                    subscription2 = self.get_user(subscription["username"])
                    subscription = subscription | subscription2
                    subscription = create_subscription(subscription)
                else:
                    subscription = create_subscription(subscription)
                subscription.link = f"https://onlyfans.com/{subscription.username}"
                valid_subscriptions.append(subscription)
            return valid_subscriptions
        pool = api_helper.multiprocessing()
        # offset_array = api_helper.assign_session(offset_array, self.sessions,key_two="session",show_item=True)
        results += pool.starmap(multi, product(
            offset_array, [session]))

        def meh(subscriptions):
            for subscription in subscriptions:
                valid_counts = ["postsCount", "archivedPostsCount"]

                identifier = subscription.id
                args = [identifier, False, False]
                link_info = self.links(*args).full
                x2 = [link_info["post_api"],
                      link_info["archived_posts"]]
                items = dict(zip(valid_counts, x2))
                for key, value in items.items():
                    if key in items:
                        placement = ""
                        key_name = ""
                        if key == "postsCount":
                            key_name = "Posts"
                            placement = subscription.links
                        elif key == "archivedPostsCount":
                            key_name = "Posts"
                            placement = subscription.links.Archived
                        link = value["link"]
                        max_limit = value["max_limit"]
                        api_count = getattr(subscription, key)
                        ceil = math.ceil(api_count / max_limit)
                        a = list(range(ceil))
                        for b in a:
                            b = b * max_limit
                            getattr(placement, key_name).append(link.replace(
                                "offset=0", "offset=" + str(b)))
            return subscriptions
        results = [x for x in results if x is not None]
        results = list(chain(*results))
        results = meh(results)
        self.auth["subscriptions"] = results
        return results

    def get_subscription(self, identifier):
        subscriptions = self.get_subscriptions(refresh=False)
        valid = {}
        for subscription in subscriptions:
            if identifier == subscription.username or identifier == subscription.id:
                valid = subscription
                break
        return valid

    def get_lists(self, refresh=True, limit=100, offset=0):
        authed = self.auth_check()
        if not authed:
            return
        if not refresh:
            subscriptions = authed.get(
                "lists", self.get_subscriptions())
            return subscriptions
        link = links(global_limit=limit,
                     global_offset=offset).lists
        results = self.request(link=link)
        self.auth["lists"] = results
        return results

    def get_lists_users(self, identifier, refresh=True, limit=100, offset=0):
        authed = self.auth_check()
        if not authed:
            return
        link = links(identifier, global_limit=limit,
                     global_offset=offset).lists_users
        r = self.request(link=link)
        return r

    def handle_refresh(self, argument, argument2):
        argument = argument.get(
            argument2)
        return argument

    def get_chats(self, resume=None, refresh=True, limit=10, offset=0):
        api_type = "chats"
        authed = self.auth_check()
        if not authed:
            return
        if not refresh:
            result = self.handle_refresh(self, api_type)
            if result:
                return result
        link = links(global_limit=limit,
                     global_offset=offset).list_chats
        results = self.request(link=link)
        items = results["list"]
        if resume:
            for item in items:
                if any(x["id"] == item["id"] for x in resume):
                    resume.sort(key=lambda x: x["id"], reverse=True)
                    self.auth["chats"] = resume
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
        self.auth["chats"] = items
        return items

    def get_archived_stories(self, refresh=True, limit=100, offset=0):
        api_type = "archived_stories"
        if not refresh:
            result = self.handle_refresh(self, api_type)
            if result:
                return result
        link = links(global_limit=limit,
                     global_offset=offset).archived_stories
        results = self.request(link=link)
        self.auth["archived_stories"] = results
        return results

    def get_mass_messages(self, resume=None, refresh=True, limit=10, offset=0):
        api_type = "mass_messages"
        authed = self.auth_check()
        if not authed:
            return
        if not refresh:
            result = self.handle_refresh(self, api_type)
            if result:
                return result
        link = links(global_limit=limit,
                     global_offset=offset).mass_messages_api
        results = self.request(link=link)
        items = results["list"]
        if resume:
            for item in items:
                if any(x["id"] == item["id"] for x in resume):
                    resume.sort(key=lambda x: x["id"], reverse=True)
                    self.auth["mass_messages"] = resume
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
        self.auth["mass_messages"] = items
        return items

    def get_paid_content(self, check: bool = False, refresh: bool = True, limit: int = 99, offset: int = 0):
        api_type = "paid_content"
        authed = self.auth_check()
        if not authed:
            return
        if not refresh:
            result = self.handle_refresh(self, api_type)
            if result:
                return result
        link = links(global_limit=limit,
                     global_offset=offset).paid_api
        results = self.request(link=link)
        if len(results) >= limit and not check:
            results2 = self.get_paid_content(limit=limit, offset=limit+offset)
            results.extend(results2)
        self.auth["paid_content"] = results
        return results


class create_subscription(start):
    def __init__(self, option={}):
        class subscribedByData():
            def __init__(self, option={}) -> None:
                self.expiredAt = option.get("expiredAt")
                self.price = option.get("price")
                self.subscribePrice = option.get("subscribePrice")
        self.username = option.get("username")
        self.id = option.get("id")
        self.subscribedByData = subscribedByData(
            option.get("subscribedByData", {}))
        self.is_me = option.get("is_me", False)
        self.postsCount = option.get("postsCount",0)
        self.archivedPostsCount = option.get("archivedPostsCount",0)
        self.photosCount = option.get("photosCount",0)
        self.videosCount = option.get("videosCount",0)
        self.audiosCount = option.get("audiosCount",0)
        self.favoritesCount = option.get("favoritesCount",0)
        self.avatar = option.get("avatar")
        self.header = option.get("header")
        self.hasStories = option.get("hasStories")
        self.link = option.get("link")
        self.links = content_types()
        self.scraped = content_types()
        self.sessions = option.get("sessions")
        self.download_info = {}

    def get_stories(self, refresh=True, limit=100, offset=0):
        api_type = "stories"
        if not refresh:
            result = self.handle_refresh(self, api_type)
            if result:
                return result
        if not self.hasStories:
            return []
        link = [links(identifier=self.id, global_limit=limit,
                      global_offset=offset).stories_api]
        results = api_helper.scrape_check(link, self.sessions, api_type)
        self.scraped.Stories = results
        return results

    def get_highlights(self, identifier="", refresh=True, limit=100, offset=0, hightlight_id=""):
        api_type = "highlights"
        if not refresh:
            result = self.handle_refresh(self, api_type)
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
        results = self.request(link=link)
        return results

    def get_posts(self, refresh=True, limit=99, offset=0):
        api_type = "posts"
        if not refresh:
            result = self.handle_refresh(self, api_type)
            if result:
                return result
        links = self.links.Posts
        results = api_helper.scrape_check(links, self.sessions, api_type)
        self.scraped.Posts = results
        return results

    def get_messages(self, identifier=None, resume=None, refresh=True, limit=10, offset=0):
        api_type = "messages"
        if not refresh:
            result = self.handle_refresh(self, api_type)
            if result:
                return result
        if not identifier:
            identifier = self.id
            if self.is_me:
                return []

        def process():
            link = links(identifier=identifier, global_limit=limit,
                         global_offset=offset).message_api
            results = self.request(link=link, format=True)
            return results
        unmerged = []
        while True:
            results = process()
            result = results["result"]
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
            if not result["hasMore"]:
                break
            offset += limit
        results = merge({}, *unmerged, strategy=Strategy.ADDITIVE)
        self.scraped.Messages = [results]
        return results

    def get_message_by_id(self, identifier=None, identifier2=None, refresh=True, limit=10, offset=0):
        link = links(identifier=identifier, identifier2=identifier2, global_limit=limit,
                     global_offset=offset).message_by_id
        results = self.request(link=link, format=True)
        return results

    def get_archived_posts(self, refresh=True, limit=99, offset=0):
        api_type = "archived_posts"
        if not refresh:
            result = self.handle_refresh(self, api_type)
            if result:
                return result
        results = []
        links = self.links.Archived.Posts
        if links:
            results = api_helper.scrape_check(links, self.sessions, api_type)
        self.scraped.Archived.Posts = results
        return results

    def get_archived(self, api):
        items = []
        item = {}
        item["type"] = "Stories"
        # test = self.get_archived_posts()
        # item["results"] = test
        item["results"] = [api.get_archived_stories()]
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
        results = self.request(link=link)
        return results

    def search_messages(self, identifier="", text="", refresh=True, limit=10, offset=0):
        if identifier:
            identifier = parse.urljoin(identifier, "messages")
        link = links(identifier=identifier, text=text, global_limit=limit,
                     global_offset=offset).search_messages
        results = self.request(link=link)
        return results

    def set_scraped(self, name, scraped):
        setattr(self.scraped, name, scraped)
