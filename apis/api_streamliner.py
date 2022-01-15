from __future__ import annotations
from multiprocessing.pool import Pool

from apis import api_helper

import apis.fansly.classes as fansly_classes
import apis.onlyfans.classes as onlyfans_classes
import apis.starsavn.classes as starsavn_classes
from classes.make_settings import Config
from classes.prepare_directories import DirectoryManager
from helpers import main_helper

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
error_types = (
    onlyfans_classes.extras.ErrorDetails
    | fansly_classes.extras.ErrorDetails
    | starsavn_classes.extras.ErrorDetails
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apis.fansly.fansly import start as FanslyAPI
    from apis.onlyfans.onlyfans import start as OnlyFansAPI
    from apis.starsavn.starsavn import start as StarsAVNAPI

    api_types = OnlyFansAPI | FanslyAPI | StarsAVNAPI


class StreamlinedAPI:
    def __init__(self, api: api_types, config: Config) -> None:
        self.api = api
        self.max_threads = config.settings.max_threads
        self.config = config
        self.lists = None
        self.pool: Pool = api_helper.multiprocessing()
        global_settings = self.get_global_settings()
        site_settings = self.get_site_settings()
        profile_root_directory = main_helper.check_space(
            global_settings.profile_directories
        )
        root_metadata_directory = main_helper.check_space(
            site_settings.metadata_directories
        )
        root_download_directory = main_helper.check_space(
            site_settings.download_directories
        )
        self.base_directory_manager = DirectoryManager(
            site_settings,
            profile_root_directory,
            root_metadata_directory,
            root_download_directory,
        )

    def get_site_settings(self):
        return self.config.supported.get_settings(self.api.site_name)

    def has_active_auths(self):
        return bool([x for x in self.api.auths if x.active])

    def get_auths_via_subscription_identifier(self, identifier: str):
        for auth in self.api.auths:
            if auth.username == identifier:
                print

    def get_global_settings(self):
        return self.config.settings

    def close_pools(self):
        self.pool.close()
        for auth in self.api.auths:
            if auth.session_manager:
                auth.session_manager.pool.close()
