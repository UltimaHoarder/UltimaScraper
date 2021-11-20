import copy
import os
from itertools import chain, groupby
from typing import Any, MutableMapping, Union

import jsonpickle
from apis.onlyfans.classes.create_auth import create_auth
from apis.onlyfans.classes.extras import media_types
from helpers import main_helper

global_version = 2


class create_metadata(object):
    def __init__(
        self,
        authed: create_auth = None,
        metadata: Union[list, dict, MutableMapping] = {},
        standard_format=False,
        api_type: str = "",
    ) -> None:
        self.version = global_version
        fixed_metadata = self.fix_metadata(metadata, standard_format, api_type)
        self.content = format_content(
            authed, fixed_metadata["version"], fixed_metadata["content"]
        ).content

    def fix_metadata(self, metadata, standard_format=False, api_type: str = "") -> dict:
        new_format = {}
        new_format["version"] = 1
        new_format["content"] = {}
        if isinstance(metadata, list):
            version = 0.3
            for m in metadata:
                new_format["content"] |= self.fix_metadata(m)["content"]
                print
            metadata = new_format
        else:
            version = metadata.get("version", None)
        if any(x for x in metadata if x in media_types().__dict__.keys()):
            standard_format = True
            print
        if not version and not standard_format and metadata:
            legacy_metadata = metadata
            media_type = legacy_metadata.get("type", None)
            if not media_type:
                version = 0.1
                media_type = api_type if api_type else media_type
            else:
                version = 0.2
            if version == 0.2:
                legacy_metadata.pop("type")
            new_format["content"][media_type] = {}
            for key, posts in legacy_metadata.items():
                if all(isinstance(x, list) for x in posts):
                    posts = list(chain(*posts))
                new_format["content"][media_type][key] = posts
                print
            print
        elif standard_format:
            if any(x for x in metadata if x in media_types().__dict__.keys()):
                metadata.pop("directories", None)
                for key, status in metadata.items():
                    if isinstance(status, int):
                        continue
                    for key2, posts in status.items():
                        if all(x and isinstance(x, list) for x in posts):
                            posts = list(chain(*posts))
                            metadata[key][key2] = posts
                        print
                    print
                print
            new_format["content"] = metadata
            print
        else:
            if global_version == version:
                new_format = metadata
            else:
                print
        print
        if "content" not in new_format:
            print
        return new_format

    def export(self, convert_type="json", keep_empty_items=False) -> dict:
        if not keep_empty_items:
            self.remove_empty()
        value = {}
        if convert_type == "json":
            new_format_copied = copy.deepcopy(self)
            for key, status in new_format_copied.content:
                for key2, posts in status:
                    for post in posts:
                        for media in post.medias:
                            delattr(media, "session")
                            if getattr(media, "old_filepath", None) != None:
                                delattr(media, "old_filepath")
                            if getattr(media, "new_filepath", None) != None:
                                delattr(media, "new_filepath")
                            print
                        print
                print
            value = jsonpickle.encode(new_format_copied, unpicklable=False)
            value = jsonpickle.decode(value)
            if not isinstance(value, dict):
                return {}
        return value

    def convert(self, convert_type="json", keep_empty_items=False) -> dict:
        if not keep_empty_items:
            self.remove_empty()
        value = {}
        if convert_type == "json":
            new_format_copied = copy.deepcopy(self)
            value = jsonpickle.encode(new_format_copied, unpicklable=False)
            value = jsonpickle.decode(value)
            if not isinstance(value, dict):
                return {}
        return value

    def remove_empty(self):
        copied = copy.deepcopy(self)
        for k, v in copied:
            if not v:
                delattr(self, k)
            print
        return self

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class format_content(object):
    def __init__(
        self,
        authed=None,
        version=None,
        temp_old_content: dict = {},
        export=False,
        reformat=False,
        args={},
    ):
        class assign_state(object):
            def __init__(self) -> None:
                self.valid = []
                self.invalid = []

            def __iter__(self):
                for attr, value in self.__dict__.items():
                    yield attr, value

        old_content = temp_old_content.copy()
        old_content.pop("directories", None)
        new_content = media_types(assign_states=assign_state)
        for key, new_item in new_content:
            old_item = old_content.get(key)
            if not old_item:
                continue
            for old_key, old_item2 in old_item.items():
                new_posts = []
                if global_version == version:
                    posts = old_item2
                    for old_post in posts:
                        post = self.post_item(old_post)
                        new_medias = []
                        for media in post.medias:
                            media["media_type"] = key
                            media2 = self.media_item(media)
                            new_medias.append(media2)
                        post.medias = new_medias
                        new_posts.append(post)
                        print

                elif version == 1:
                    old_item2.sort(key=lambda x: x["post_id"])
                    media_list = [
                        list(g)
                        for k, g in groupby(old_item2, key=lambda x: x["post_id"])
                    ]
                    for media_list2 in media_list:
                        old_post = media_list2[0]
                        post = self.post_item(old_post)
                        for item in media_list2:
                            item["media_type"] = key
                            media = self.media_item(item)
                            post.medias.append(media)
                        new_posts.append(post)
                else:
                    media_list = []
                    input("METADATA VERSION: INVALID")
                setattr(new_item, old_key, new_posts)
        self.content = new_content

    class post_item(create_metadata, object):
        def __init__(self, option={}):
            create_metadata.__init__(self, option)
            self.post_id = option.get("post_id", None)
            self.text = option.get("text", "")
            self.price = option.get("price", 0)
            self.paid = option.get("paid", False)
            self.medias = option.get("medias", [])
            self.postedAt = option.get("postedAt", "")

        def convert(self, convert_type="json", keep_empty_items=False) -> dict:
            if not keep_empty_items:
                self.remove_empty()
            value = {}
            if convert_type == "json":
                new_format_copied = copy.deepcopy(self)
                for media in new_format_copied.medias:
                    media.convert()
                value = jsonpickle.encode(new_format_copied, unpicklable=False)
                value = jsonpickle.decode(value)
                if not isinstance(value, dict):
                    return {}
            return value

    class media_item(create_metadata):
        def __init__(self, option={}):
            create_metadata.__init__(self, option)
            self.media_id = option.get("media_id", None)
            link = option.get("link", [])
            if link:
                link = [link]
            self.links = option.get("links", link)
            self.directory = option.get("directory", "")
            self.filename = option.get("filename", "")
            self.size = option.get("size", None)
            self.media_type = option.get("media_type", None)
            self.session = option.get("session", None)
            self.downloaded = option.get("downloaded", False)

        def convert(self, convert_type="json", keep_empty_items=False) -> dict:
            if not keep_empty_items:
                self.remove_empty()
            value = {}
            if convert_type == "json":
                value.pop("session", None)
                new_format_copied = copy.deepcopy(self)
                value = jsonpickle.encode(new_format_copied, unpicklable=False)
                value = jsonpickle.decode(value)
                if not isinstance(value, dict):
                    return {}
            return value

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class format_variables(object):
    def __init__(self):
        self.site_name = "{site_name}"
        self.first_letter = "{first_letter}"
        self.post_id = "{post_id}"
        self.media_id = "{media_id}"
        self.profile_username = "{profile_username}"
        self.model_username = "{model_username}"
        self.api_type = "{api_type}"
        self.media_type = "{media_type}"
        self.filename = "{filename}"
        self.value = "{value}"
        self.text = "{text}"
        self.date = "{date}"
        self.ext = "{ext}"

    def whitelist(self, wl):
        new_wl = []
        new_format_copied = copy.deepcopy(self)
        for key, value in new_format_copied:
            if value not in wl:
                new_wl.append(value)
        return new_wl

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class format_types:
    def __init__(self, options) -> None:
        self.file_directory_format = options.get("file_directory_format")
        self.filename_format = options.get("filename_format")
        self.metadata_directory_format = options.get("metadata_directory_format")

    def check_rules(self):
        bool_status = True
        wl = []
        invalid_list = []
        string = ""
        for key, value in self:
            if key == "file_directory_format":
                bl = format_variables()
                wl = [v for k, v in bl.__dict__.items()]
                bl = bl.whitelist(wl)
                invalid_list = []
                for b in bl:
                    if b in self.file_directory_format:
                        invalid_list.append(b)
            if key == "filename_format":
                bl = format_variables()
                wl = [v for k, v in bl.__dict__.items()]
                bl = bl.whitelist(wl)
                invalid_list = []
                for b in bl:
                    if b in self.filename_format:
                        invalid_list.append(b)
            if key == "metadata_directory_format":
                wl = [
                    "{site_name}",
                    "{first_letter}",
                    "{model_id}",
                    "{profile_username}",
                    "{model_username}",
                ]
                bl = format_variables().whitelist(wl)
                invalid_list = []
                for b in bl:
                    if b in self.metadata_directory_format:
                        invalid_list.append(b)
            bool_status = True
            if invalid_list:
                string += f"You cannot use {','.join(invalid_list)} in {key}. Use any from this list {','.join(wl)}"
                bool_status = False

        return string, bool_status

    def check_unique(self, return_unique=True):
        string = ""
        values = []
        unique = []
        new_format_copied = copy.deepcopy(self)
        option = {}
        option["string"] = ""
        option["bool_status"] = True
        option["unique"] = new_format_copied
        f = format_variables()
        for key, value in self:
            if key == "file_directory_format":
                unique = ["{media_id}", "{model_username}"]
                value = os.path.normpath(value)
                values = value.split(os.sep)
                option["unique"].file_directory_format = unique
            elif key == "filename_format":
                values = []
                unique = ["{media_id}", "{filename}"]
                value = os.path.normpath(value)
                for key2, value2 in f:
                    if value2 in value:
                        values.append(value2)
                option["unique"].filename_format = unique
            elif key == "metadata_directory_format":
                unique = ["{model_username}"]
                value = os.path.normpath(value)
                values = value.split(os.sep)
                option["unique"].metadata_directory_format = unique
            if key != "filename_format":
                e = [x for x in values if x in unique]
            else:
                e = [x for x in unique if x in values]
            if e:
                setattr(option["unique"], key, e)
            else:
                option[
                    "string"
                ] += f"{key} is a invalid format since it has no unique identifiers. Use any from this list {','.join(unique)}\n"
                option["bool_status"] = False
        return option

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class prepare_reformat(object):
    def __init__(self, option: dict[str, Any], keep_vars: bool = False):
        format_variables2 = format_variables()
        self.site_name = option.get("site_name", format_variables2.site_name)
        self.post_id = option.get("post_id", format_variables2.post_id)
        self.media_id = option.get("media_id", format_variables2.media_id)
        self.profile_username = option.get(
            "profile_username", format_variables2.profile_username
        )
        self.model_username = option.get(
            "model_username", format_variables2.model_username
        )
        self.api_type = option.get("api_type", format_variables2.api_type)
        self.media_type = option.get("media_type", format_variables2.media_type)
        self.filename = option.get("filename", format_variables2.filename)
        self.ext = option.get("ext", format_variables2.ext)
        text: str = option.get("text", format_variables2.text)
        self.text = str(text or "")
        self.date = option.get("postedAt", format_variables2.date)
        self.price = option.get("price", 0)
        self.archived = option.get("archived", False)
        self.date_format = option.get("date_format")
        self.maximum_length = 255
        self.text_length = option.get("text_length", self.maximum_length)
        self.directory = option.get("directory")
        self.preview = option.get("preview")
        if not keep_vars:
            for key, value in self:
                print
                if isinstance(value, str):
                    key = main_helper.find_between(value, "{", "}")
                    e = getattr(format_variables2, key, None)
                    if e:
                        setattr(self, key, "")
                        print
        print

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value

    async def reformat(self, unformatted_list) -> list[str]:
        x = []
        format_variables2 = format_variables()
        for key, unformatted_item in unformatted_list.items():
            if "filename_format" == key:
                unformatted_item = os.path.join(x[1], unformatted_item)
                print
            string = await main_helper.reformat(self, unformatted_item)
            final_path = []
            paths = string.split(os.sep)
            for path in paths:
                key = main_helper.find_between(path, "{", "}")
                e = getattr(format_variables2, key, None)
                if path == e:
                    break
                final_path.append(path)
            final_path = os.sep.join(final_path)
            print
            x.append(final_path)
        return x

    def convert(self, convert_type="json", keep_empty_items=False) -> dict:
        if not keep_empty_items:
            self.remove_empty()
        value = {}
        if convert_type == "json":
            new_format_copied = copy.deepcopy(self)
            delattr(new_format_copied, "session")
            value = jsonpickle.encode(new_format_copied, unpicklable=False)
            value = jsonpickle.decode(value)
            if not isinstance(value, dict):
                return {}
        return value

    def remove_empty(self):
        copied = copy.deepcopy(self)
        for k, v in copied:
            if not v:
                delattr(self, k)
            print
        return self
