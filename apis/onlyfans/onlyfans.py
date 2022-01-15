from typing import Any, Literal, Optional, Union

from apis.api_streamliner import StreamlinedAPI
from apis.onlyfans.classes.auth_model import create_auth
from apis.onlyfans.classes.extras import auth_details, endpoint_links
from apis.onlyfans.classes.user_model import create_user

from classes.make_settings import Config


class start(StreamlinedAPI):
    def __init__(self, config: Config) -> None:
        self.site_name: Literal["OnlyFans"] = "OnlyFans"
        StreamlinedAPI.__init__(self, self, config)
        self.auths: list[create_auth] = []
        self.subscriptions: list[create_user] = []
        self.endpoint_links = endpoint_links

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

    class ContentTypes:
        def __init__(self) -> None:
            class ArchivedTypes:
                def __init__(self) -> None:
                    self.Posts = []

                def __iter__(self):
                    for attr, value in self.__dict__.items():
                        yield attr, value

            self.Stories = []
            self.Posts = []
            self.Archived = ArchivedTypes()
            self.Chats = []
            self.Messages = []
            self.Highlights = []
            self.MassMessages = []

        def __iter__(self):
            for attr, value in self.__dict__.items():
                yield attr, value

        async def get_keys(self):
            return [item[0] for item in self]

    class Locations:
        def __init__(self) -> None:
            self.Images = ["photo"]
            self.Videos = ["video", "stream", "gif"]
            self.Audios = ["audio"]
            self.Texts = ["text"]

        async def get_keys(self):
            return [item[0] for item in self.__dict__.items()]
