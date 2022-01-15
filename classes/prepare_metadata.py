from __future__ import annotations

import copy
import os
import shutil
from datetime import datetime
from itertools import chain, groupby
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from apis import api_helper
from apis.onlyfans.classes.extras import media_types
from helpers import main_helper


def load_classes():
    import apis.fansly.classes as fansly_classes
    import apis.onlyfans.classes as onlyfans_classes
    import apis.starsavn.classes as starsavn_classes

    return onlyfans_classes, fansly_classes, starsavn_classes


def load_classes2():
    onlyfans_classes, fansly_classes, starsavn_classes = load_classes()
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
    return auth_types, user_types


if TYPE_CHECKING:
    from classes.prepare_directories import DirectoryManager


auth_types, user_types = load_classes2()
global_version = 2

# Supports legacy metadata (.json and .db format) and converts it into the latest format (.db)
class create_metadata(object):
    def __init__(
        self,
        metadata: list[dict[str, Any]] | dict[str, Any] = {},
        standard_format: bool = False,
        api_type: str = "",
    ) -> None:
        self.version = global_version
        fixed_metadata = self.fix_metadata(metadata, standard_format, api_type)
        self.content = format_content(
            fixed_metadata["version"], fixed_metadata["content"]
        ).content

    def fix_metadata(
        self,
        metadata: dict[str, Any] | list[dict[str, Any]],
        standard_format: bool = False,
        api_type: str = "",
    ):
        new_format: dict[str, Any] = {}
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

    def compare_metadata(self, old_metadata: create_metadata) -> create_metadata:
        for key, value in old_metadata.content:
            new_value = getattr(self.content, key, None)
            if not new_value:
                continue
            if not value:
                setattr(old_metadata, key, new_value)
            for key2, value2 in value:
                new_value2 = getattr(new_value, key2)
                seen = set()
                old_status = []
                for d in value2:
                    if d.post_id not in seen:
                        seen.add(d.post_id)
                        old_status.append(d)
                    else:
                        print
                setattr(value, key2, old_status)
                value2 = old_status
                new_status = new_value2
                for post in old_status:
                    if key != "Texts":
                        for old_media in post.medias:
                            # if old_item.post_id == 1646808:
                            #     l = True
                            new_found = None
                            new_items = [
                                x for x in new_status if post.post_id == x.post_id
                            ]
                            if new_items:
                                for new_item in (x for x in new_items if not new_found):
                                    for new_media in (
                                        x for x in new_item.medias if not new_found
                                    ):
                                        new_found = test(new_media, old_media)
                                        print
                            if new_found:
                                for key3, v in new_found:
                                    if key3 in [
                                        "directory",
                                        "downloaded",
                                        "size",
                                        "filename",
                                    ]:
                                        continue
                                    setattr(old_media, key3, v)
                                setattr(new_found, "found", True)
                    else:
                        new_items = [x for x in new_status if post.post_id == x.post_id]
                        if new_items:
                            new_found = new_items[0]
                            for key3, v in new_found:
                                if key3 in [
                                    "directory",
                                    "downloaded",
                                    "size",
                                    "filename",
                                ]:
                                    continue
                                setattr(post, key3, v)
                            setattr(new_found, "found", True)
                        print
                for new_post in new_status:
                    not_found = []
                    if key != "Texts":
                        not_found = [
                            new_post
                            for media in new_post.medias
                            if not getattr(media, "found", None)
                        ][:1]
                    else:
                        found = getattr(new_post, "found", None)
                        if not found:
                            not_found.append(new_post)

                    if not_found:
                        old_status += not_found
                old_status.sort(key=lambda x: x.post_id, reverse=True)
        new_metadata = old_metadata
        return new_metadata

    def convert(
        self, convert_type: str = "json", keep_empty_items: bool = False
    ) -> dict[str, Any]:
        if not keep_empty_items:
            self.remove_empty()
        value: dict[str, Any] = {}
        if convert_type == "json":
            value = main_helper.object_to_json(self)
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
            # create_metadata.__init__(self, option)
            self.post_id = option.get("post_id", None)
            self.text = option.get("text", "")
            self.price = option.get("price", 0)
            self.paid = option.get("paid", False)
            self.medias = option.get("medias", [])
            self.postedAt = option.get("postedAt", "")

    class media_item(create_metadata):
        def __init__(self, option={}):
            # create_metadata.__init__(self, option)
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

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class format_attributes(object):
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

    def whitelist(self, wl: list[str]):
        new_wl: list[str] = []
        new_format_copied = copy.deepcopy(self)
        for _key, value in new_format_copied:
            if value not in wl:
                new_wl.append(value)
        return new_wl

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class prepare_reformat(object):
    def __init__(self, option: dict[str, Any] = {}, keep_vars: bool = False):
        format_variables2 = format_attributes()
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
        self.date_format = option.get("date_format", "%d-%m-%Y")
        self.maximum_length = 255
        self.text_length = option.get("text_length", self.maximum_length)
        self.directory: Optional[Path] = option.get("directory")
        self.preview = option.get("preview")
        self.ignore_value = False
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

    async def standard(
        self,
        site_name: str,
        profile_username: str,
        user_username: str,
        date: datetime,
        date_format: str,
        text_length: int,
        directory: Path,
    ):
        p_r = prepare_reformat()
        p_r.site_name = site_name
        p_r.profile_username = profile_username
        p_r.model_username = user_username
        p_r.date = date
        p_r.date_format = date_format
        p_r.text_length = text_length
        p_r.directory = directory
        return p_r

    # async def reformat(self, unformatted_list:dict[str,str]) -> list[str]:
    #     x:list[str] = []
    #     format_variables2 = format_variables()
    #     for key, unformatted_item in unformatted_list.items():
    #         if "filename_format" == key:
    #             unformatted_item = os.path.join(x[1], unformatted_item)
    #             print
    #         string = await self.reformat_2(unformatted_item)
    #         final_path = []
    #         paths = string.split(os.sep)
    #         for path in paths:
    #             key = main_helper.find_between(path, "{", "}")
    #             e = getattr(format_variables2, key, None)
    #             if path == e:
    #                 break
    #             final_path.append(path)
    #         final_path = os.sep.join(final_path)
    #         print
    #         x.append(final_path)
    #     return x

    async def reformat_2(self, unformatted: Path):
        post_id = self.post_id
        media_id = self.media_id
        date = self.date
        text = self.text
        value = "Free"
        maximum_length = self.maximum_length
        text_length = self.text_length
        post_id = "" if post_id is None else str(post_id)
        media_id = "" if media_id is None else str(media_id)
        unformatted_string = unformatted.as_posix()
        extra_count = 0
        if type(date) is str:
            format_variables2 = format_attributes()
            if date != format_variables2.date and date != "":
                date = datetime.strptime(date, "%d-%m-%Y %H:%M:%S")
                date = date.strftime(self.date_format)
        else:
            if isinstance(date, datetime):
                date = date.strftime(self.date_format)
        has_text = False
        if "{text}" in unformatted_string:
            has_text = True
            text = main_helper.clean_text(text)
            extra_count = len("{text}")
        if "{value}" in unformatted_string:
            if self.price:
                if not self.preview:
                    value = "Paid"
        directory = self.directory
        if not directory:
            raise Exception("Directory not found")
        path = unformatted_string.replace("{site_name}", self.site_name)
        path = path.replace("{first_letter}", self.model_username[0].capitalize())
        path = path.replace("{post_id}", post_id)
        path = path.replace("{media_id}", media_id)
        path = path.replace("{profile_username}", self.profile_username)
        path = path.replace("{model_username}", self.model_username)
        path = path.replace("{api_type}", self.api_type)
        path = path.replace("{media_type}", self.media_type)
        path = path.replace("{filename}", self.filename)
        path = path.replace("{ext}", self.ext)
        path = path.replace("{value}", value)
        path = path.replace("{date}", date)
        directory_count = len(str(directory))
        path_count = len(path)
        maximum_length = maximum_length - (directory_count + path_count - extra_count)
        text_length = text_length if text_length < maximum_length else maximum_length
        if has_text:
            # https://stackoverflow.com/a/43848928
            def utf8_lead_byte(b: int):
                """A UTF-8 intermediate byte starts with the bits 10xxxxxx."""
                return (b & 0xC0) != 0x80

            def utf8_byte_truncate(text: str, max_bytes: int):
                """If text[max_bytes] is not a lead byte, back up until a lead byte is
                found and truncate before that character."""
                utf8 = text.encode("utf8")
                if len(utf8) <= max_bytes:
                    return utf8
                i = max_bytes
                while i > 0 and not utf8_lead_byte(utf8[i]):
                    i -= 1
                return utf8[:i]

            filtered_text = utf8_byte_truncate(text, text_length).decode("utf8")
            path = path.replace("{text}", filtered_text)
        else:
            path = path.replace("{text}", "")
        x_path = directory.joinpath(path)
        return x_path

    def remove_empty(self):
        copied = copy.deepcopy(self)
        for k, v in copied:
            if not v:
                delattr(self, k)
            print
        return self

    async def remove_non_unique(
        self, directory_manager: DirectoryManager, format_key: str = ""
    ):
        formats = directory_manager.formats
        unique_formats: dict[str, Any] = formats.check_unique()
        new_dict: dict[str, Any] = {}

        def takewhile_including(iterable: list[str], value: str):
            for it in iterable:
                yield it
                if it == value:
                    return

        for key, unique_format in unique_formats["unique"].__dict__.items():
            if "filename" in key or format_key != key:
                continue
            unique_format: str = unique_format[0]
            new_dict[key] = unique_format
            path_parts = Path(getattr(formats, key)).parts
            p = Path(*takewhile_including(list(path_parts), unique_format))
            w = await self.reformat_2(p)
            if format_key:
                return w
            new_dict[f"{key}ted"] = w
        return new_dict

    async def find_metadata_files(
        self, filepaths: list[Path], legacy_files: bool = True
    ):
        new_list: list[Path] = []
        for filepath in filepaths:
            if not legacy_files:
                if "__legacy_metadata__" in filepath.parts:
                    continue
            match filepath.suffix:
                case ".db":
                    red_list = ["thumbs.db"]
                    status = [x for x in red_list if x == filepath.name.lower()]
                    if status:
                        continue
                    new_list.append(filepath)
                case ".json":
                    new_list.append(filepath)
        return new_list


async def process_legacy_metadata(
    user: user_types,
    api_type: str,
    metadata_filepath: Path,
    directory_manager: DirectoryManager,
):
    p_r = prepare_reformat()
    old_metadata_filepaths = await p_r.find_metadata_files(
        user.file_manager.files, legacy_files=False
    )
    for old_metadata_filepath in old_metadata_filepaths:
        new_m_f = directory_manager.user.metadata_directory.joinpath(
            old_metadata_filepath.name
        )
        if old_metadata_filepath.exists() and not new_m_f.exists():
            shutil.move(old_metadata_filepath, new_m_f)
    old_metadata_filepaths = await p_r.find_metadata_files(
        user.file_manager.files, legacy_files=False
    )
    legacy_metadata_filepaths = [
        x for x in old_metadata_filepaths if x.stem.find(api_type) == 0
    ]
    legacy_metadata_object, delete_legacy_metadatas = await legacy_metadata_fixer(
        metadata_filepath, legacy_metadata_filepaths
    )
    delete_metadatas: list[Path] = []
    if delete_legacy_metadatas:
        print("Merging new metadata with legacy metadata.")
        delete_metadatas.extend(delete_legacy_metadatas)
    final_set: list[dict[str, Any]] = []
    for _media_type, value in legacy_metadata_object.content:
        for _status, value2 in value:
            for value3 in value2:
                item = value3.convert(keep_empty_items=True)
                item["archived"] = False
                item["api_type"] = api_type
                final_set.append(item)
    print("Finished processing metadata.")
    return final_set, delete_metadatas


# Legacy .db and .json files
# We'll just merge things together based on their api_type
# create_metadata fixes metadata automatically
async def legacy_metadata_fixer(
    new_metadata_filepath: Path, legacy_metadata_filepaths: list[Path]
) -> tuple[create_metadata, list[Path]]:
    delete_legacy_metadatas: list[Path] = []
    new_format: list[dict[str, Any]] = []
    new_metadata_set = main_helper.import_json(new_metadata_filepath)
    for legacy_metadata_filepath in legacy_metadata_filepaths:
        if (
            legacy_metadata_filepath == new_metadata_filepath
            or not legacy_metadata_filepath.exists()
        ):
            continue
        api_type = legacy_metadata_filepath.stem
        legacy_metadata = main_helper.import_json(legacy_metadata_filepath)
        legacy_metadata = create_metadata(legacy_metadata, api_type=api_type).convert()
        new_format.append(legacy_metadata)
        delete_legacy_metadatas.append(legacy_metadata_filepath)
    new_metadata_object = create_metadata(new_metadata_set)
    old_metadata_set = dict(api_helper.merge_dictionaries(new_format))
    old_metadata_object = create_metadata(old_metadata_set)
    results = new_metadata_object.compare_metadata(old_metadata_object)
    return results, delete_legacy_metadatas


async def process_metadata(
    archive_path: Path,
    legacy_metadata_path: Path,
    new_metadata_object: list[dict[str, Any]],
    api_type: str,
    subscription: user_types,
    delete_metadatas: list[Path],
):
    import extras.OFRenamer.start_ofr as ofrenamer

    api = subscription.get_api()
    site_settings = api.get_site_settings()
    config = api.config
    if not (config and site_settings):
        return
    settings = config.settings
    # We could put this in proccess_legacy_metadata
    final_result, delete_metadatas = main_helper.legacy_sqlite_updater(
        legacy_metadata_path, api_type, subscription, delete_metadatas
    )
    new_metadata_object.extend(final_result)
    result = main_helper.export_sqlite(archive_path, api_type, new_metadata_object)
    if not result:
        return
    Session, api_type, _folder = result
    if settings.helpers.renamer:
        print("Renaming files.")
        new_metadata_object = await ofrenamer.start(
            subscription, api_type, Session, site_settings
        )
    for legacy_metadata in delete_metadatas:
        if site_settings.delete_legacy_metadata:
            os.remove(legacy_metadata)
        else:
            if legacy_metadata.exists():
                new_filepath = Path(
                    legacy_metadata.parent, "__legacy_metadata__", legacy_metadata.name
                )
                new_filepath.parent.mkdir(exist_ok=True)
                shutil.move(legacy_metadata, f"{new_filepath}")
