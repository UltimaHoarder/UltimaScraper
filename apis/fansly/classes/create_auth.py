import asyncio
import math
from datetime import datetime
from itertools import chain, product
from multiprocessing.pool import Pool
from typing import Any, Dict, List, Optional, Union

import jsonpickle
from apis import api_helper
from apis.fansly.classes.create_message import create_message
from apis.fansly.classes.create_post import create_post
from apis.fansly.classes.create_user import create_user
from apis.fansly.classes.extras import (
    auth_details,
    content_types,
    create_headers,
    endpoint_links,
    error_details,
    handle_refresh,
)
from dateutil.relativedelta import relativedelta
from user_agent import generate_user_agent


class create_auth(create_user):
    def __init__(
        self,
        option: dict[str, Any] = {},
        pool: Pool = None,
        max_threads: int = -1,
    ) -> None:
        create_user.__init__(self, option)
        if not self.username:
            self.username = f"u{self.id}"
        self.lists = {}
        self.links = content_types()
        self.subscriptions: list[create_user] = []
        self.chats = None
        self.archived_stories = {}
        self.mass_messages = []
        self.paid_content = []
        temp_pool = pool if pool else api_helper.multiprocessing()
        self.pool = temp_pool
        self.session_manager = api_helper.session_manager(
            self, max_threads=max_threads, use_cookies=False
        )
        self.auth_details: auth_details = auth_details()
        self.profile_directory = option.get("profile_directory", "")
        self.guest = False
        self.active: bool = False
        self.errors: list[error_details] = []
        self.extras: dict[str, Any] = {}

    def update(self, data: Dict[str, Any]):
        data = data["response"][0]
        if not data["username"]:
            data["username"] = f"u{data['id']}"
        for key, value in data.items():
            found_attr = hasattr(self, key)
            if found_attr:
                setattr(self, key, value)

    async def login(self, max_attempts: int = 10, guest: bool = False):
        auth_version = "(V1)"
        auth_items = self.auth_details
        if not auth_items:
            return self
        if guest and auth_items:
            auth_items.cookie.auth_id = "0"
            auth_items.user_agent = generate_user_agent()  # type: ignore
        link = endpoint_links().customer
        user_agent = auth_items.user_agent  # type: ignore
        # expected string error is fixed by auth_id
        dynamic_rules = self.session_manager.dynamic_rules
        a: List[Any] = [dynamic_rules, user_agent, link]
        self.session_manager.headers = create_headers(*a)
        if guest:
            print("Guest Authentication")
            return self

        count = 1
        while count < max_attempts + 1:
            string = f"Auth {auth_version} Attempt {count}/{max_attempts}"
            print(string)
            await self.get_authed()
            count += 1

            async def resolve_auth(auth: create_auth):
                if self.errors:
                    error = self.errors[-1]
                    print(error.message)
                    if error.code == 101:
                        if auth_items.support_2fa:
                            link = f"https://onlyfans.com/api2/v2/users/otp/check"
                            count = 1
                            max_count = 3
                            while count < max_count + 1:
                                print(
                                    "2FA Attempt " + str(count) + "/" + str(max_count)
                                )
                                code = input("Enter 2FA Code\n")
                                data = {"code": code, "rememberMe": True}
                                response = await self.session_manager.json_request(
                                    link, method="POST", payload=data
                                )
                                if isinstance(response, error_details):
                                    error.message = response.message
                                    count += 1
                                else:
                                    print("Success")
                                    auth.active = False
                                    auth.errors.remove(error)
                                    await self.get_authed()
                                    break

            await resolve_auth(self)
            if not self.active:
                if self.errors:
                    error = self.errors[-1]
                    error_message = error.message
                    if "token" in error_message:
                        break
                    if "Code wrong" in error_message:
                        break
                    if "Please refresh" in error_message:
                        break
                else:
                    print("Auth 404'ed")
                continue
            else:
                print(f"Welcome {self.name} | {self.username}")
                break
        return self

    async def get_authed(self):
        if not self.active:
            link = endpoint_links().settings
            response = await self.session_manager.json_request(link)
            if isinstance(response, dict):
                link = endpoint_links(response["response"]["accountId"]).customer
                response = await self.session_manager.json_request(link)
                self.resolve_auth_errors(response)
                if not self.errors:
                    # merged = self.__dict__ | response
                    # self = create_auth(merged,self.pool,self.session_manager.max_threads)
                    self.active = True
                    self.update(response)
            else:
                # 404'ed
                self.active = False
        return self

    def resolve_auth_errors(self, response: Union[dict[str, Any], error_details]):
        # Adds an error object to self.auth.errors
        if isinstance(response, error_details):
            error = response
        elif isinstance(response, dict) and "error" in response:
            error = response["error"]
            error = error_details(error)
        else:
            self.errors.clear()
            return
        error_message = error.message
        error_code = error.code
        if error_code == 0:
            pass
        elif error_code == 101:
            error_message = "Blocked by 2FA."
        elif error_code == 401:
            # Session/Refresh
            pass
        error.code = error_code
        error.message = error_message
        self.errors.append(error)

    async def get_lists(self, refresh=True, limit=100, offset=0):
        api_type = "lists"
        if not self.active:
            return
        if not refresh:
            subscriptions = handle_refresh(self, api_type)
            return subscriptions
        link = endpoint_links(global_limit=limit, global_offset=offset).lists
        results = await self.session_manager.json_request(link)
        self.lists = results
        return results

    async def get_user(
        self, identifier: Union[str, int]
    ) -> Union[create_user, error_details]:
        link = endpoint_links(identifier).customer
        response = await self.session_manager.json_request(link)
        if not isinstance(response, error_details):
            if response["response"]:
                response["session_manager"] = self.session_manager
                response = create_user(response["response"][0], self)
            else:
                response = error_details({"code": 69, "message": "User Doesn't Exist"})
        return response

    async def get_lists_users(
        self, identifier, check: bool = False, refresh=True, limit=100, offset=0
    ):
        if not self.active:
            return
        link = endpoint_links(
            identifier, global_limit=limit, global_offset=offset
        ).lists_users
        results = await self.session_manager.json_request(link)
        if len(results) >= limit and not check:
            results2 = await self.get_lists_users(
                identifier, limit=limit, offset=limit + offset
            )
            results.extend(results2)
        return results

    async def get_followings(self, identifiers: list[str]) -> list[create_user]:
        followings_link = endpoint_links(self.id).followings
        temp_followings: dict[str, Any] = await self.session_manager.json_request(
            followings_link
        )
        followings = temp_followings["response"]
        if followings:
            followings_id: str = ",".join([x["accountId"] for x in followings])
            customer_link = endpoint_links(followings_id).customer
            followings = await self.session_manager.json_request(customer_link)
            if identifiers:
                followings = [create_user(x, self) for x in followings["response"] for identifier in identifiers if x["username"] == identifier or x["id"] == identifier]
            else:
                followings = [create_user(x, self) for x in followings["response"]]
            for following in followings:
                if not following.subscribedByData:
                    new_date = datetime.now() + relativedelta(years=1)
                    new_date = int(new_date.timestamp()*1000)
                    following.subscribedByData = {}
                    following.subscribedByData["endsAt"] = new_date
                    print
        return followings

    async def get_subscription(
        self, check: bool = False, identifier="", limit=100, offset=0
    ) -> Union[create_user, None]:
        subscriptions = await self.get_subscriptions(refresh=False)
        valid = None
        for subscription in subscriptions:
            if identifier == subscription.username or identifier == subscription.id:
                valid = subscription
                break
        return valid

    async def get_subscriptions(
        self,
        resume=None,
        refresh=True,
        identifiers: list = [],
        extra_info=True,
        limit=20,
        offset=0,
    ) -> list[create_user]:
        if not self.active:
            return []
        if not refresh:
            subscriptions = self.subscriptions
            return subscriptions
        subscriptions_link = endpoint_links().subscriptions
        temp_subscriptions = await self.session_manager.json_request(subscriptions_link)
        subscriptions = temp_subscriptions["response"]["subscriptions"]

        # Following logic is unique to creators only
        results = []
        if self.isPerformer:
            temp_session_manager = self.session_manager
            temp_pool = self.pool
            temp_paid_content = self.paid_content
            delattr(self, "session_manager")
            delattr(self, "pool")
            delattr(self, "paid_content")
            json_authed = jsonpickle.encode(self, unpicklable=False)
            json_authed = jsonpickle.decode(json_authed)
            self.session_manager = temp_session_manager
            self.pool = temp_pool
            self.paid_content = temp_paid_content
            temp_auth = await self.get_user(self.username)
            if isinstance(json_authed, dict):
                json_authed = json_authed | temp_auth.__dict__

            subscription = create_user(json_authed, self)
            subscription.subscriber = self
            subscription.subscribedByData = {}
            new_date = datetime.now() + relativedelta(years=1)
            subscription.subscribedByData["expiredAt"] = new_date.isoformat()
            subscription = [subscription]
            results.append(subscription)
        if not identifiers:

            async def multi(item):
                valid_subscriptions = await self.get_user(item["accountId"])

                if (
                    valid_subscriptions.following
                    and not valid_subscriptions.subscribedByData
                ):
                    new_date = datetime.now() + relativedelta(years=1)
                    valid_subscriptions.subscribedByData = {}
                    valid_subscriptions.subscribedByData["endsAt"] = new_date
                return [valid_subscriptions]

            pool = self.pool
            tasks = pool.starmap(multi, product(subscriptions))
            results += await asyncio.gather(*tasks)
        else:
            for identifier in identifiers:
                if self.id == identifier or self.username == identifier:
                    continue
                link = endpoint_links(identifier=identifier).users
                result = await self.session_manager.json_request(link)
                if isinstance(result, error_details) or not result["subscribedBy"]:
                    continue
                subscription = create_user(result, self)
                if subscription.isBlocked:
                    continue
                subscription.session_manager = self.session_manager
                subscription.subscriber = self
                results.append([subscription])
                print
            print
        results = [x for x in results if x is not None]
        results = list(chain(*results))
        self.subscriptions = results
        return results

    async def get_chats(
        self,
        links: Optional[list] = None,
        limit=100,
        offset=0,
        refresh=True,
        inside_loop=False,
    ) -> list:
        api_type = "chats"
        if not self.active:
            return []
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        if links is None:
            links = []
        api_count = self.chatMessagesCount
        if api_count and not links:
            link = endpoint_links(
                identifier=self.id, global_limit=limit, global_offset=offset
            ).list_chats
            ceil = math.ceil(api_count / limit)
            numbers = list(range(ceil))
            for num in numbers:
                num = num * limit
                link = link.replace(f"limit={limit}", f"limit={limit}")
                new_link = link.replace("offset=0", f"offset={num}")
                links.append(new_link)
        multiplier = getattr(self.session_manager.pool, "_processes")
        if links:
            link = links[-1]
        else:
            link = endpoint_links(
                identifier=self.id, global_limit=limit, global_offset=offset
            ).list_chats
        links2 = api_helper.calculate_the_unpredictable(link, limit, multiplier)
        if not inside_loop:
            links += links2
        else:
            links = links2
        results = await self.session_manager.async_requests(links)
        has_more = results[-1]["hasMore"]
        final_results = [x["list"] for x in results]
        final_results = list(chain.from_iterable(final_results))

        if has_more:
            results2 = await self.get_chats(
                links=[links[-1]], limit=limit, offset=limit + offset, inside_loop=True
            )
            final_results.extend(results2)

        final_results.sort(key=lambda x: x["withUser"]["id"], reverse=True)
        self.chats = final_results
        return final_results

    async def get_mass_messages(
        self, resume=None, refresh=True, limit=10, offset=0
    ) -> list:
        api_type = "mass_messages"
        if not self.active:
            return []
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        link = endpoint_links(
            global_limit=limit, global_offset=offset
        ).mass_messages_api
        results = await self.session_manager.json_request(link)
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
                resume=resume, limit=limit, offset=limit + offset
            )
            items.extend(results2)
        if resume:
            items = resume

        items.sort(key=lambda x: x["id"], reverse=True)
        self.mass_messages = items
        return items

    async def get_paid_content(
        self,
        check: bool = False,
        refresh: bool = True,
        limit: int = 99,
        offset: int = 0,
        inside_loop: bool = False,
    ) -> list[Union[create_message, create_post]]:
        return []
        api_type = "paid_content"
        if not self.active:
            return []
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        link = endpoint_links(global_limit=limit, global_offset=offset).paid_api
        final_results = await self.session_manager.json_request(link)
        if not isinstance(final_results, error_details):
            if len(final_results) >= limit and not check:
                results2 = self.get_paid_content(
                    limit=limit, offset=limit + offset, inside_loop=True
                )
                final_results.extend(results2)
            if not inside_loop:
                temp = []
                for final_result in final_results:
                    content = None
                    if final_result["responseType"] == "message":
                        user = create_user(final_result["fromUser"], self)
                        content = create_message(final_result, user)
                        print
                    elif final_result["responseType"] == "post":
                        user = create_user(final_result["author"], self)
                        content = create_post(final_result, user)
                    if content:
                        temp.append(content)
                final_results = temp
            self.paid_content = final_results
        return final_results
