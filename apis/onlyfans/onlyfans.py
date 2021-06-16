from typing import  Any, Dict, Optional, Union

from apis.onlyfans.classes import create_user
from apis.onlyfans.classes.create_auth import create_auth
from apis.onlyfans.classes.extras import (auth_details,
                                          endpoint_links)

from .. import api_helper


# def session_retry_rules(response, link: str) -> int:
#     """
#     0 Fine, 1 Continue, 2 Break
#     """
#     status_code = 0
#     if "https://onlyfans.com/api2/v2/" in link:
#         text = response.text
#         if "Invalid request sign" in text:
#             status_code = 1
#         elif "Access Denied" in text:
#             status_code = 2
#     else:
#         if not response.status_code == 200:
#             status_code = 1
#     return status_code


class start:
    def __init__(
        self,
        max_threads:int=-1,
    ) -> None:
        self.auths: list[create_auth] = []
        self.subscriptions: list[create_user] = []
        self.max_threads = max_threads
        self.lists = None
        self.endpoint_links = endpoint_links
        self.pool = api_helper.multiprocessing()
        self.settings:Dict[str,dict[str,Any]] = {}

    def add_auth(self, option:Dict[str,bool]={}, only_active:bool=False):
        if only_active and not option.get("active"):
            return
        auth = create_auth(pool=self.pool, max_threads=self.max_threads)
        auth.auth_details = auth_details(option)
        auth.extras["settings"] = self.settings
        self.auths.append(auth)
        return auth

    def get_auth(self, identifier: Union[str, int]) -> Optional[create_auth]:
        final_auth = None
        for auth in self.auths:
            if auth.id == identifier:
                final_auth = auth
            elif auth.username == identifier:
                final_auth = auth
            if final_auth:
                break
        return final_auth

    def close_pools(self):
        self.pool.close()
        for auth in self.auths:
            auth.session_manager.pool.close()
