import time
from typing import Union
from urllib.parse import urlparse
from urllib import parse
import hashlib
import math
from datetime import datetime
from dateutil.relativedelta import relativedelta
from itertools import chain, product
from .. import api_helper
from mergedeep import merge, Strategy
import jsonpickle
import copy


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


class content_types:
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


class auth_details():
    def __init__(self, option={}):
        self.username = option.get('username', "")
        self.sess = option.get('sess', "")
        self.user_agent = option.get('user_agent', "")
        self.support_2fa = option.get('support_2fa', True)
        self.active = option.get('active', True)


class endpoint_links(object):
    def __init__(self, identifier=None, identifier2=None, text="", only_links=True, global_limit=None, global_offset=None, access_token="33d57ade8c02dbc5a333db99ff9ae26a"):
        self.customer = f"https://stars.avn.com/api2/v2/users/me"
        self.users = f'https://onlyfans.com/api2/v2/users/{identifier}?app-token={access_token}'
        self.subscriptions = f"https://onlyfans.com/api2/v2/subscriptions/subscribes?limit=100&offset=0&type=active&app-token={access_token}"
        self.lists = f"https://onlyfans.com/api2/v2/lists?limit=100&offset=0&app-token={access_token}"
        self.lists_users = f"https://onlyfans.com/api2/v2/lists/{identifier}/users?limit=100&offset=0&query=&app-token={access_token}"
        self.list_chats = f"https://onlyfans.com/api2/v2/chats?limit=10&offset=0&order=desc&app-token={access_token}"
        self.message_by_id = f"https://onlyfans.com/api2/v2/chats/{identifier}/messages?limit=10&offset=0&firstId={identifier2}&order=desc&skip_users=all&skip_users_dups=1&app-token=33d57ade8c02dbc5a333db99ff9ae26a"
        self.search_chat = f"https://onlyfans.com/api2/v2/chats/{identifier}/messages/search?query={text}&app-token={access_token}"
        self.message_api = f"https://onlyfans.com/api2/v2/chats/{identifier}/messages?limit=100&offset=0&order=desc&app-token={access_token}"
        self.search_messages = f"https://onlyfans.com/api2/v2/chats/{identifier}?limit=10&offset=0&filter=&order=activity&query={text}&app-token={access_token}"
        self.mass_messages_api = f"https://onlyfans.com/api2/v2/messages/queue/stats?limit=100&offset=0&format=infinite&app-token={access_token}"
        self.stories_api = f"https://onlyfans.com/api2/v2/users/{identifier}/stories?limit=100&offset=0&order=desc&app-token={access_token}"
        self.list_highlights = f"https://onlyfans.com/api2/v2/users/{identifier}/stories/highlights?limit=100&offset=0&order=desc&app-token={access_token}"
        self.highlight = f"https://onlyfans.com/api2/v2/stories/highlights/{identifier}?app-token={access_token}"
        self.post_api = f"https://onlyfans.com/api2/v2/users/{identifier}/posts?limit=100&offset=0&order=publish_date_desc&skip_users_dups=0&app-token={access_token}"
        self.archived_posts = f"https://onlyfans.com/api2/v2/users/{identifier}/posts/archived?limit=100&offset=0&order=publish_date_desc&app-token={access_token}"
        self.archived_stories = f"https://onlyfans.com/api2/v2/stories/archive/?limit=100&offset=0&order=publish_date_desc&app-token={access_token}"
        self.paid_api = f"https://onlyfans.com/api2/v2/posts/paid?limit=100&offset=0&app-token={access_token}"
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


class create_auth():
    def __init__(self, option={}, init=False) -> None:
        self.id = option.get("id")
        self.username = option.get("username")
        if not self.username:
            self.username = f"u{self.id}"
        self.name = option.get("name")
        self.lists = {}
        self.links = content_types()
        self.isPerformer = option.get("isPerformer")
        self.chatMessagesCount = option.get("chatMessagesCount")
        self.subscribesCount = option.get("subscribesCount")
        self.subscriptions = []
        self.chats = None
        self.archived_stories = {}
        self.mass_messages = []
        self.paid_content = {}
        self.sessions = option.get("sessions")
        self.auth_details = auth_details()
        self.profile_directory = option.get("profile_directory", "")
        self.active = False
        valid_counts = ["chatMessagesCount"]
        args = [self.username, False, False]
        link_info = endpoint_links(*args).full
        x2 = [link_info["list_chats"]]
        items = dict(zip(valid_counts, x2))
        if not init:
            pass
            # for key, value in items.items():
            #     if key in items:
            #         key_name = ""
            #         if key == "chatMessagesCount":
            #             key_name = "Chats"
            #         link = value["link"]
            #         max_limit = value["max_limit"]
            #         api_count = getattr(self, key)
            #         ceil = math.ceil(api_count / max_limit)
            #         a = list(range(ceil))
            #         for b in a:
            #             b = b * max_limit
            #             getattr(self.links, key_name).append(link.replace(
            #                 "offset=0", "offset=" + str(b)))


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
        self.username = option.get("username")
        self.id = option.get("id")
        self.subscribedByData = subscribedByData(
            option.get("subscribedByData", {}))
        self.is_me = option.get("is_me", False)
        self.postsCount = option.get("postsCount", 0)
        self.archivedPostsCount = option.get("archivedPostsCount", 0)
        self.photosCount = option.get("photosCount", 0)
        self.videosCount = option.get("videosCount", 0)
        self.audiosCount = option.get("audiosCount", 0)
        self.favoritesCount = option.get("favoritesCount", 0)
        self.avatar = option.get("avatar")
        self.header = option.get("header")
        self.hasStories = option.get("hasStories")
        self.link = option.get("link")
        self.links = content_types()
        self.temp_scraped = content_types()
        self.scraped = content_types()
        self.auth_count = None
        self.sessions = option.get("sessions")
        self.download_info = {}

        # Modify self
        valid_counts = ["postsCount", "archivedPostsCount"]
        identifier = self.id
        link_info = endpoint_links(identifier=identifier).full
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
        link = [endpoint_links(identifier=self.id, global_limit=limit,
                      global_offset=offset).stories_api]
        results = api_helper.scrape_endpoint_links(link, self.sessions, api_type)
        self.temp_scraped.Stories = results
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
            link = endpoint_links(identifier=identifier, global_limit=limit,
                         global_offset=offset).list_highlights
        else:
            link = endpoint_links(identifier=hightlight_id, global_limit=limit,
                         global_offset=offset).highlight
        session = self.sessions[0]
        results = api_helper.json_request(link=link, session=session)
        return results

    def get_posts(self, refresh=True, limit=99, offset=0) -> list:
        api_type = "posts"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        links = self.links.Posts
        results = api_helper.scrape_endpoint_links(links, self.sessions, api_type)
        self.temp_scraped.Posts = results
        return results

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
            link = endpoint_links(identifier=identifier, global_limit=limit,
                         global_offset=offset).message_api
            session = self.sessions[0]
            results = api_helper.json_request(link=link, session=session)
            item = {}
            item["session"] = session
            item["result"] = results
            return item
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
                            self.temp_scraped.Messages = resume
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
        self.temp_scraped.Messages = [results]
        return results

    def get_message_by_id(self, identifier=None, identifier2=None, refresh=True, limit=10, offset=0):
        link = endpoint_links(identifier=identifier, identifier2=identifier2, global_limit=limit,
                     global_offset=offset).message_by_id
        session = self.sessions[0]
        results = api_helper.json_request(link=link, session=session)
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
        link = endpoint_links(global_limit=limit,
                     global_offset=offset).archived_stories
        session = self.sessions[0]
        results = api_helper.json_request(link=link, session=session)
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
            results = api_helper.scrape_endpoint_links(links, self.sessions, api_type)
        self.temp_scraped.Archived.Posts = results
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
        link = endpoint_links(identifier=identifier, text=text, global_limit=limit,
                     global_offset=offset).search_chat
        session = self.sessions[0]
        results = api_helper.json_request(link=link, session=session)
        return results

    def search_messages(self, identifier="", text="", refresh=True, limit=10, offset=0):
        if identifier:
            identifier = parse.urljoin(identifier, "messages")
        link = endpoint_links(identifier=identifier, text=text, global_limit=limit,
                     global_offset=offset).search_messages
        session = self.sessions[0]
        results = api_helper.json_request(link=link, session=session)
        return results

    def set_scraped(self, name, scraped: media_types):
        setattr(self.scraped, name, scraped)


class start():
    def __init__(self, sessions=[], custom_request=callable) -> None:
        sessions = api_helper.add_sessions(sessions)
        self.sessions = sessions
        self.auth = create_auth(init=True)
        self.custom_request = custom_request
        self.max_threads = -1
        self.lists = None
        self.links = links
        for session in sessions:
            session.headers["access-token"] = ""
            session.headers["sign"] = ""
            session.headers["time"] = ""
        api_helper.request_parameters(session_rules, session_retry_rules)
        self.json_request = api_helper.json_request

    # def auth_check(self):
    #     result = False
    #     auth = self.get_authed()
    #     if not auth or isinstance(auth, dict):
    #         if not self.auth_details:
    #             print("Not Authed")
    #         else:
    #             result = self.login()
    #     else:
    #         result = auth
    #     if not result:
    #         print("Could not authenticate")
    #     return result

    def add_auth(self, option):
        if not option["active"]:
            return
        self.auth.auth_details.username = option["username"]
        self.auth.auth_details.sess = option["sess"]
        if not option["user_agent"]:
            input(
                f"user_agent required for: {self.auth.auth_details.username}")
            exit()
        self.auth.auth_details.user_agent = option["user_agent"]
        self.auth.auth_details.support_2fa = option["support_2fa"]
        self.auth.auth_details.active = option["active"]

    def login(self, full=False, max_attempts=10) -> Union[create_auth, None]:
        auth_version = "(V1)"
        auth_items = self.auth.auth_details
        link = endpoint_links().customer
        user_agent = auth_items.user_agent
        auth_cookies = [
            {'name': 'sess', 'value': auth_items.sess}
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
            if me_api and not "error" in me_api:
                me_api = create_auth(me_api)
                me_api.active = True
            else:
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
                            link = f"https://onlyfans.com/api2/v2/users/otp/check"
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
            if not me_api.name:
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
            print(f"Welcome {me_api.name} | {me_api.username}")
            self.auth = me_api
            return self.auth

    def get_authed(self):
        if not self.auth.active:
            link = endpoint_links().customer
            r = api_helper.json_request(link, self.sessions[0],  sleep=False)
            if r:
                r["sessions"] = self.sessions
        else:
            r = self.auth
        return r

    def set_auth(self, me):
        self.auth = me

    def get_user(self, identifier):
        link = endpoint_links(identifier).users
        session = self.sessions[0]
        results = api_helper.json_request(link=link, session=session)
        return results

    def get_subscriptions(self, resume=None, refresh=True, extra_info=True, limit=20, offset=0) -> list[Union[create_subscription, None]]:
        authed = self.auth
        if not authed:
            return []
        if not refresh:
            subscriptions = authed.subscriptions
            return subscriptions
        link = endpoint_links(global_limit=limit, global_offset=offset).subscriptions
        session = self.sessions[0]
        ceil = math.ceil(authed.subscribesCount / limit)
        a = list(range(ceil))
        offset_array = []
        for b in a:
            b = b * limit
            link = endpoint_links(global_limit=limit, global_offset=b).subscriptions
            offset_array.append(link)

        # Following logic is unique to creators only
        results = []
        if authed.isPerformer:
            json_authed = jsonpickle.encode(
                authed, unpicklable=False)
            json_authed = jsonpickle.decode(json_authed)
            json_authed = json_authed | self.get_user(authed.username)

            subscription = create_subscription(json_authed)
            subscription.sessions = self.sessions
            subscription = [subscription]
            results.append(subscription)

        def multi(item, session=None):
            link = item
            # link = item["link"]
            # session = item["session"]
            subscriptions = api_helper.json_request(link=link, session=session)
            valid_subscriptions = []
            extras = {}
            extras["auth_check"] = ""
            for subscription in subscriptions:
                subscription["sessions"] = self.sessions
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
            offset_array, [session]))
        results = [x for x in results if x is not None]
        results = list(chain(*results))
        self.auth.subscriptions = results
        return results

    def get_subscription(self, check: bool = False, identifier="", limit=100, offset=0) -> Union[create_subscription, None]:
        subscriptions = self.get_subscriptions(refresh=False)
        valid = None
        for subscription in subscriptions:
            if identifier == subscription.username or identifier == subscription.id:
                valid = subscription
                break
        if not valid and not check:
            link = endpoint_links(identifier=identifier, global_limit=limit,
                         global_offset=offset).users
            session = self.sessions[0]
            results = api_helper.json_request(link=link, session=session)
            error = results.get("error", None)
            if error:
                if error["message"] == "User not found":
                    pass
                else:
                    string = "ERROR MESSAGE NOT HANDLED, PLEASE OPEN AN ISSUE ON GITHUB\n"
                    string += f"{error['message']}"
                    input()
                    exit()
            else:
                results["sessions"] = self.sessions
                if results["id"] == identifier or results["subscribedBy"]:
                    subscription = create_subscription(results)
                    valid = subscription
                    subscriptions.append(subscription)
        return valid

    def get_lists(self, refresh=True, limit=100, offset=0):
        api_type = "lists"
        authed = self.auth
        if not isinstance(authed, create_auth):
            return
        if not refresh:
            subscriptions = handle_refresh(self, api_type)
            return subscriptions
        link = endpoint_links(global_limit=limit,
                     global_offset=offset).lists
        session = self.sessions[0]
        results = api_helper.json_request(link=link, session=session)
        authed.lists = results
        return results

    def get_lists_users(self, identifier, refresh=True, limit=100, offset=0):
        authed = self.auth
        if not authed:
            return
        link = endpoint_links(identifier, global_limit=limit,
                     global_offset=offset).lists_users
        session = self.sessions[0]
        results = api_helper.json_request(link=link, session=session)
        return results

    def get_chats(self, resume=None, refresh=True, limit=10, offset=0):
        api_type = "chats"
        authed = self.auth
        if not authed:
            return
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        link = endpoint_links(global_limit=limit,
                     global_offset=offset).list_chats
        session = self.sessions[0]
        results = api_helper.json_request(link=link, session=session)
        items = results["list"]
        if resume:
            for item in items:
                if any(x["id"] == item["id"] for x in resume):
                    resume.sort(key=lambda x: x["id"], reverse=True)
                    self.auth.chats = resume
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
        self.auth.chats = items
        return items

    def get_mass_messages(self, resume=None, refresh=True, limit=10, offset=0):
        api_type = "mass_messages"
        authed = self.auth
        if not authed:
            return
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        link = endpoint_links(global_limit=limit,
                     global_offset=offset).mass_messages_api
        session = self.sessions[0]
        results = api_helper.json_request(link=link, session=session)
        items = results.get("list", [])
        if not items:
            return items
        if resume:
            for item in items:
                if any(x["id"] == item["id"] for x in resume):
                    resume.sort(key=lambda x: x["id"], reverse=True)
                    self.auth.mass_messages = resume
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
        self.auth.mass_messages = items
        return items

    def get_paid_content(self, check: bool = False, refresh: bool = True, limit: int = 99, offset: int = 0):
        api_type = "paid_content"
        authed = self.auth
        if not authed:
            return
        if not refresh:
            result = handle_refresh(authed, api_type)
            if result:
                return result
        link = endpoint_links(global_limit=limit,
                     global_offset=offset).paid_api
        session = self.sessions[0]
        results = api_helper.json_request(link=link, session=session)
        if len(results) >= limit and not check:
            results2 = self.get_paid_content(limit=limit, offset=limit+offset)
            results.extend(results2)
        self.auth.paid_content = results
        return results
