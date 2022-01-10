from multiprocessing.pool import Pool
from typing import Any, Literal, Optional, Union

from apis.starsavn.classes.auth_model import create_auth
from apis.starsavn.classes.extras import auth_details, endpoint_links
from apis.starsavn.classes.user_model import create_user

from classes.make_settings import Config
from classes.prepare_directories import DirectoryManager

from .. import api_helper


class start:
    def __init__(self, max_threads: int = -1, config: Optional[Config] = None) -> None:
        from helpers.main_helper import check_space

        self.site_name: Literal["StarsAVN"] = "StarsAVN"
        self.auths: list[create_auth] = []
        self.subscriptions: list[create_user] = []
        self.max_threads = max_threads
        self.lists = None
        self.endpoint_links = endpoint_links
        self.pool: Pool = api_helper.multiprocessing()
        self.config = config
        self.base_directory_manager = DirectoryManager()
        site_settings = self.get_site_settings()
        if self.config and site_settings:
            self.base_directory_manager.profile.root_directory = check_space(
                self.config.settings.profile_directories
            )
            self.base_directory_manager.root_metadata_directory = check_space(
                site_settings.metadata_directories
            )
            self.base_directory_manager.root_download_directory = check_space(
                site_settings.download_directories
            )
            print

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
        auth = create_auth(self, pool=self.pool, max_threads=self.max_threads)
        if only_active and not auth_json.get("active"):
            return auth
        temp_auth_details = auth_details(auth_json).upgrade_legacy(auth_json)
        auth.auth_details = temp_auth_details
        auth.extras["settings"] = self.config
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
            if auth.session_manager:
                auth.session_manager.pool.close()

    def has_active_auths(self):
        return bool([x for x in self.auths if x.active])

    def get_auths_via_subscription_identifier(self, identifier: str):
        for auth in self.auths:
            if auth.username == identifier:
                print

    def get_site_settings(self):
        if self.config:
            return self.config.supported.get_settings(self.site_name)

    class Locations:
        def __init__(self) -> None:
            self.Images = ["photo"]
            self.Videos = ["video", "stream", "gif"]
            self.Audios = ["audio"]
            self.Texts = ["text"]
