from multiprocessing.pool import Pool
from typing import Any, Optional, Union

from apis.onlyfans.classes.auth_model import create_auth
from apis.onlyfans.classes.extras import auth_details, endpoint_links
from apis.onlyfans.classes.user_model import create_user

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
        max_threads: int = -1,
    ) -> None:
        self.auths: list[create_auth] = []
        self.subscriptions: list[create_user] = []
        self.max_threads = max_threads
        self.lists = None
        self.endpoint_links = endpoint_links
        self.pool: Pool = api_helper.multiprocessing()
        self.settings: dict[str, dict[str, Any]] = {}

    def add_auth(
        self, auth_json: dict[str, Any] = {}, only_active: bool = False
    ) -> create_auth:
        """Creates and appends an auth object to auths property

        Args:
            auth_json (dict[str, str], optional): []. Defaults to {}.
            only_active (bool, optional): [description]. Defaults to False.

        Returns:
            create_auth: [Auth object]
        """
        auth = create_auth(pool=self.pool, max_threads=self.max_threads, api=self)
        if only_active and not auth_json.get("active"):
            return auth
        temp_auth_details = auth_details(auth_json).upgrade_legacy(auth_json)
        auth.auth_details = temp_auth_details
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

    def create_auth_details(self, auth_json: dict[str, Any] = {}) -> auth_details:
        """If you've got a auth.json file, you can load it into python and pass it through here.

        Args:
            auth_json (dict[str, Any], optional): [description]. Defaults to {}.

        Returns:
            auth_details: [auth_details object]
        """
        return auth_details(auth_json).upgrade_legacy(auth_json)

    def close_pools(self):
        self.pool.close()
        for auth in self.auths:
            auth.session_manager.pool.close()

    def has_active_auths(self):
        return bool([x for x in self.auths if x.active])
