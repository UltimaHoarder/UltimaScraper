from __future__ import annotations

import asyncio
import math
from datetime import datetime
from itertools import chain, product
from multiprocessing.pool import Pool
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from apis import api_helper
from apis.fansly.classes.extras import (
    ErrorDetails,
    auth_details,
    content_types,
    create_headers,
    endpoint_links,
    handle_refresh,
)
from apis.fansly.classes.message_model import create_message
from apis.fansly.classes.post_model import create_post
from apis.fansly.classes.user_model import create_user

if TYPE_CHECKING:
    from apis.fansly.fansly import start

from dateutil.relativedelta import relativedelta
from user_agent import generate_user_agent


class create_auth(create_user):
    def __init__(
        self,
        api: start,
        option: dict[str, Any] = {},
        pool: Optional[Pool] = None,
        max_threads: int = -1,
    ) -> None:
        self.api = api
        create_user.__init__(self, option, self)
        if not self.username:
            self.username = f"u{self.id}"
        self.lists = {}
        self.links = content_types()
        self.subscriptions: list[create_user] = []
        self.chats = None
        self.archived_stories = {}
        self.mass_messages = []
        self.paid_content: list[create_message | create_post] = []
        temp_pool = pool if pool else api_helper.multiprocessing()
        self.pool = temp_pool
        self.session_manager = self._session_manager(
            self, max_threads=max_threads, use_cookies=False
        )
        self.auth_details = auth_details()
        self.guest = False
        self.active: bool = False
        self.errors: list[ErrorDetails] = []
        self.extras: dict[str, Any] = {}

    class _session_manager(api_helper.session_manager):
        def __init__(
            self,
            auth: create_auth,
            headers: dict[str, Any] = {},
            proxies: list[str] = [],
            max_threads: int = -1,
            use_cookies: bool = True,
        ) -> None:
            api_helper.session_manager.__init__(
                self, auth, headers, proxies, max_threads, use_cookies
            )

    async def convert_to_user(self):
        user = await self.get_user(self.username)
        for k, _v in user.__dict__.items():
            setattr(user, k, getattr(self, k))
        return user

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
            auth_items.user_agent = generate_user_agent()
        link = endpoint_links().customer
        user_agent = auth_items.user_agent
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
                                if isinstance(response, ErrorDetails):
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
                print(
                    f"Welcome {' | '.join([x for x in [self.name, self.username] if x])}"
                )
                self.create_directory_manager()
                break
        return self

    async def get_authed(self):
        if not self.active:
            link = endpoint_links().settings
            response = await self.session_manager.json_request(link)
            if isinstance(response, dict):
                final_response: dict[str, Any] = response
                link = endpoint_links(final_response["response"]["accountId"]).customer
                final_response = await self.session_manager.json_request(link)
                await self.resolve_auth_errors(final_response)
                if not self.errors:
                    # merged = self.__dict__ | final_response
                    # self = create_auth(merged,self.pool,self.session_manager.max_threads)
                    self.active = True
                    self.update(final_response)
            else:
                # 404'ed
                self.active = False
        return self

    async def resolve_auth_errors(self, response: ErrorDetails | dict[str, Any]):
        # Adds an error object to self.auth.errors
        if isinstance(response, ErrorDetails):
            error = response
        elif "error" in response:
            error = response["error"]
            error = ErrorDetails(error)
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

    async def get_lists(self, refresh: bool = True, limit: int = 100, offset: int = 0):
        result, status = await api_helper.default_data(self, refresh)
        if status:
            return result
        link = endpoint_links(global_limit=limit, global_offset=offset).lists
        results = await self.session_manager.json_request(link)
        self.lists = results
        return results

    async def get_user(self, identifier: int | str) -> Union[create_user, ErrorDetails]:
        link = endpoint_links().list_users([identifier])
        response = await self.session_manager.json_request(link)
        if not isinstance(response, ErrorDetails):
            if response["response"]:
                response["session_manager"] = self.session_manager
                response = create_user(response["response"][0], self)
            else:
                response = ErrorDetails({"code": 69, "message": "User Doesn't Exist"})
        return response

    async def get_lists_users(
        self,
        identifier: int | str,
        check: bool = False,
        limit: int = 100,
        offset: int = 0,
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

    async def get_followings(self, identifiers: list[int | str]) -> list[create_user]:
        offset_count = 0
        followings: list[dict[str, Any]] = []
        while True:
            followings_link = endpoint_links().list_followings(self.id, offset_count)
            temp_followings: dict[str, Any] = await self.session_manager.json_request(
                followings_link
            )
            account_ids = temp_followings["response"]
            if account_ids:
                followings.extend(account_ids)
                offset_count += 100
            else:
                break
        final_followings: list[create_user] = []
        if followings:
            followings_id: str = ",".join([x["accountId"] for x in followings])
            customer_link = endpoint_links(followings_id).customer
            temp_followings = await self.session_manager.json_request(customer_link)
            if identifiers:
                final_followings = [
                    create_user(x, self)
                    for x in temp_followings["response"]
                    for identifier in identifiers
                    if x["username"] == identifier or x["id"] == identifier
                ]
            else:
                final_followings = [
                    create_user(x, self) for x in temp_followings["response"]
                ]
            for following in final_followings:
                if not following.subscribedByData:
                    new_date = datetime.now() + relativedelta(years=1)
                    new_date = int(new_date.timestamp() * 1000)
                    following.subscribedByData = {}
                    following.subscribedByData["endsAt"] = new_date
        return final_followings

    async def get_subscription(
        self,
        identifier: int | str = "",
    ) -> create_user | None:
        subscriptions = await self.get_subscriptions(refresh=False)
        valid = None
        for subscription in subscriptions:
            if identifier == subscription.username or identifier == subscription.id:
                valid = subscription
                break
        return valid

    async def get_subscriptions(
        self, refresh: bool = True, identifiers: list[int | str] = []
    ) -> list[create_user]:
        result, status = await api_helper.default_data(self, refresh)
        if status:
            return result
        subscriptions_link = endpoint_links().subscriptions
        temp_subscriptions = await self.session_manager.json_request(subscriptions_link)
        subscriptions = temp_subscriptions["response"]["subscriptions"]

        # If user is a creator, add them to the subscription list
        results: list[list[create_user]] = []
        if self.isPerformer:
            subscription = await self.convert_to_user()
            if isinstance(subscription, ErrorDetails):
                return result
            subscription.subscribedByData = {}
            new_date = datetime.now() + relativedelta(years=1)
            subscription.subscribedByData["expiredAt"] = new_date.isoformat()
            subscriptions_ = [subscription]
            results.append(subscriptions_)
        if not identifiers:

            async def multi(item: dict[str, Any]):
                subscription = await self.get_user(item["accountId"])
                valid_subscriptions: list[create_user] = []

                if (
                    isinstance(subscription, create_user)
                    and subscription.following
                    and not subscription.subscribedByData
                ):
                    new_date = datetime.now() + relativedelta(years=1)
                    new_date = int(new_date.timestamp() * 1000)
                    subscription.subscribedByData = {}
                    subscription.subscribedByData["endsAt"] = new_date
                    valid_subscriptions.append(subscription)
                return valid_subscriptions

            pool = self.pool
            tasks = pool.starmap(multi, product(subscriptions))
            results += await asyncio.gather(*tasks)
        else:
            for identifier in identifiers:
                results_2 = await self.get_user(identifier)
                results_2 = await api_helper.remove_errors(results_2)
                if isinstance(results_2, create_user):
                    x = [x for x in subscriptions if x["accountId"] == results_2.id]
                    if x:
                        results_2.subscribedByData = {}
                        results_2.subscribedByData["endsAt"] = x[0]["endsAt"]
                    results.append([results_2])
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
        self,
        resume: Optional[list[dict[str, Any]]] = None,
        refresh: bool = True,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        result, status = await api_helper.default_data(self, refresh)
        if status:
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
    ) -> list[create_message | create_post]:
        return []
        # api_type = "paid_content"
        # if not self.active:
        #     return []
        # if not refresh:
        #     result = handle_refresh(self, api_type)
        #     if result:
        #         return result
        # link = endpoint_links(global_limit=limit, global_offset=offset).paid_api
        # final_results = await self.session_manager.json_request(link)
        # if not isinstance(final_results, error_details):
        #     if len(final_results) >= limit and not check:
        #         results2 = self.get_paid_content(
        #             limit=limit, offset=limit + offset, inside_loop=True
        #         )
        #         final_results.extend(results2)
        #     if not inside_loop:
        #         temp = []
        #         for final_result in final_results:
        #             content = None
        #             if final_result["responseType"] == "message":
        #                 user = create_user(final_result["fromUser"], self)
        #                 content = create_message(final_result, user)
        #                 print
        #             elif final_result["responseType"] == "post":
        #                 user = create_user(final_result["author"], self)
        #                 content = create_post(final_result, user)
        #             if content:
        #                 temp.append(content)
        #         final_results = temp
        #     self.paid_content = final_results
        # return final_results
