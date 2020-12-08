import copy
from enum import unique
import os
from typing import Dict

from requests.api import get
from helpers import main_helper
from itertools import groupby, chain
from math import exp
import jsonpickle


class create_metadata(object):
    def __init__(self, content=None) -> None:
        self.version = 1
        self.content = None

    def convert(self) -> Dict:
        print
        return {}


class prepare_metadata(object):
    def __init__(self, metadata_types={}, export=False, reformat=False, args={}, api=None):
        def valid_invalid(valid, invalid, export):
            if all(isinstance(x, list) for x in valid):
                valid = list(chain.from_iterable(valid))
            if all(isinstance(x, list) for x in invalid):
                invalid = list(chain.from_iterable(invalid))
            valid = [self.media(x, export) for x in valid]
            valid = [list(g) for k, g in groupby(
                valid, key=lambda x: x.post_id)]
            invalid = [self.media(x, export) for x in invalid]
            invalid = [list(g) for k, g in groupby(
                invalid, key=lambda x: x.post_id)]
            return valid, invalid

        class assign_state(object):
            def __init__(self, valid, invalid, export) -> None:
                valid, invalid = valid_invalid(valid, invalid, export)
                self.valid = valid
                self.invalid = invalid

            def __iter__(self):
                for attr, value in self.__dict__.items():
                    yield attr, value

        if isinstance(metadata_types, list):
            new_format = {}
            for metadata_type in metadata_types:
                if "type" in metadata_type:
                    new_format[metadata_type["type"]] = metadata_type
                    metadata_type.pop("type")
                else:
                    # Sigh :(
                    input("NEW METADATA FORMAT FOUND")
            metadata_types = new_format
        metadata_types.pop("directories", None)
        collection = api.get_media_types()
        for key, item in metadata_types.items():
            if not item:
                continue
            x = assign_state(**item, export=export)
            setattr(collection, key, x)
        self.metadata = collection

    class media(object):
        def __init__(self, option={}, export=False, reformat=False):
            self.post_id = option.get("post_id", None)
            self.media_id = option.get("media_id", None)
            link = option.get("link", [])
            if link:
                link = [link]
            self.links = option.get("links", link)
            self.price = option.get("price", 0)
            self.text = option.get("text", "")
            self.postedAt = option.get("postedAt", "")
            self.paid = option.get("paid", False)
            self.directory = option.get("directory", "")
            self.filename = option.get("filename", "")
            self.size = option.get("size", None)
            self.session = option.get("session", None)
            self.downloaded = option.get("downloaded", False)

        def convert(self, convert_type="json", keep_empty_items=False) -> dict:
            if not keep_empty_items:
                self.remove_empty()
            value = {}
            if convert_type == "json":
                new_format_copied = copy.deepcopy(self)
                delattr(new_format_copied, "session")
                value = jsonpickle.encode(
                    new_format_copied, unpicklable=False)
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

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class format_variables(object):
    def __init__(self):
        self.site_name = "{site_name}"
        self.post_id = "{post_id}"
        self.media_id = "{media_id}"
        self.username = "{username}"
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


class format_types():
    def __init__(self, options) -> None:
        self.file_directory_format = options.get("file_directory_format")
        self.filename_format = options.get("filename_format")
        self.metadata_directory_format = options.get(
            "metadata_directory_format")

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
                wl = ["{site_name}", "{model_id}", "{username}"]
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
                unique = ["{media_id}", "{username}"]
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
                unique = ["{username}"]
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
                    "string"] += f"{key} is a invalid format since it has no unique identifiers. Use any from this list {','.join(unique)}\n"
                option["bool_status"] = False
        return option

    def __iter__(self):
        for attr, value in self.__dict__.items():
            yield attr, value


class prepare_reformat(object):
    def __init__(self, option, keep_vars=False):
        format_variables2 = format_variables()
        self.site_name = option.get('site_name', format_variables2.site_name)
        self.post_id = option.get('post_id', format_variables2.post_id)
        self.media_id = option.get('media_id', format_variables2.media_id)
        self.username = option.get('username', format_variables2.username)
        self.api_type = option.get('api_type', format_variables2.api_type)
        self.media_type = option.get(
            'media_type', format_variables2.media_type)
        self.filename = option.get('filename', format_variables2.filename)
        self.ext = option.get('ext', format_variables2.ext)
        self.text = option.get('text', format_variables2.text)
        self.date = option.get('postedAt', format_variables2.date)
        self.price = option.get('price', 0)
        self.date_format = option.get('date_format')
        self.maximum_length = option.get('maximum_length')
        self.directory = option.get(
            'directory')
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

    def reformat(self, unformatted_list) -> list[str]:
        x = []
        format_variables2 = format_variables()
        for key, unformatted_item in unformatted_list.items():
            if "filename_format" == key:
                unformatted_item = os.path.join(x[1], unformatted_item)
                print
            string = main_helper.reformat(self, unformatted_item)
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
            value = jsonpickle.encode(
                new_format_copied, unpicklable=False)
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
