import copy
import os
from pathlib import Path
from typing import Any, Literal

from classes.prepare_metadata import format_attributes, prepare_reformat


class DirectoryManager:
    def __init__(
        self,
        profile_directory: str | Path = "",
        metadata_directory: str | Path = "",
        download_directory: str | Path = "",
        path_formats: dict[str, Any] = {},
    ) -> None:
        self.root_directory = Path()
        self.root_metadata_directory = Path(metadata_directory)
        self.root_download_directory = Path(download_directory)
        self.profile = self.ProfileDirectories(Path(profile_directory))
        self.user = self.UserDirectories()
        self.formats = FormatTypes(path_formats)
        pass

    class ProfileDirectories:
        def __init__(self, root_directory: Path) -> None:
            self.root_directory = Path(root_directory)
            self.metadata_directory = self.root_directory.joinpath("Metadata")

    class UserDirectories:
        def __init__(self) -> None:
            self.metadata_directory = Path()
            self.download_directory = Path()
            self.legacy_download_directories: list[Path] = []
            self.legacy_metadata_directories: list[Path] = []

        def find_legacy_directory(
            self,
            directory_type: Literal["metadata", "download"] = "metadata",
            api_type: str = "",
        ):
            match directory_type:
                case "metadata":
                    directories = self.legacy_metadata_directories
                case _:
                    directories = self.legacy_download_directories
            final_directory = directories[0]
            for directory in directories:
                for part in directory.parts:
                    if api_type in part:
                        return directory
            return final_directory

    async def walk(self, directory: Path):
        all_files: list[Path] = []
        for root, _subdirs, files in os.walk(directory):
            x = [Path(root, x) for x in files]
            all_files.extend(x)
        return all_files


class FileManager:
    def __init__(self, directory_manager: DirectoryManager) -> None:
        self.files: list[Path] = []
        self.directory_manager = directory_manager

    async def set_default_files(
        self,
        prepared_metadata_format: prepare_reformat,
        prepared_download_format: prepare_reformat,
    ):
        self.files = []
        await self.add_files(prepared_metadata_format, "metadata_directory_format")
        await self.add_files(prepared_download_format, "file_directory_format")

    async def add_files(self, reformatter: prepare_reformat, format_key: str):
        directory_manager = self.directory_manager
        formatted_directory = await reformatter.remove_non_unique(
            directory_manager, format_key
        )
        files: list[Path] = []
        if isinstance(formatted_directory, Path):
            files = await directory_manager.walk(formatted_directory)
            self.files.extend(files)
        return files

    async def find_metadata_files(self, legacy_files: bool = True):
        new_list: list[Path] = []
        for filepath in self.files:
            if not legacy_files:
                if "__legacy_metadata__" in filepath.parts:
                    continue
            match filepath.suffix:
                case ".db":
                    new_list.append(filepath)
                case ".json":
                    new_list.append(filepath)
        return new_list


class FormatTypes:
    def __init__(self, options: dict[str, Any]) -> None:
        self.metadata_directory_format = options.get("metadata_directory_format")
        self.file_directory_format = options.get("file_directory_format")
        self.filename_format = options.get("filename_format")

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
        f = format_attributes()
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
