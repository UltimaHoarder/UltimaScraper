from __future__ import annotations

import asyncio
import copy
import json
import math
import os
import platform
import random
import re
import secrets
import shutil
import string
import subprocess
import traceback
from datetime import datetime
from itertools import zip_longest
from multiprocessing.dummy import Pool as ThreadPool
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, BinaryIO, Optional, Tuple, Union

import classes.make_settings as make_settings
import classes.prepare_webhooks as prepare_webhooks
import requests
import ujson
from aiohttp.client import ClientSession
from aiohttp.client_exceptions import (
    ClientOSError,
    ClientPayloadError,
    ContentTypeError,
    ServerDisconnectedError,
)
from aiohttp.client_reqrep import ClientResponse
from aiohttp_socks.connector import ProxyConnector
from apis import api_helper
from apis.fansly import fansly as Fansly
from apis.onlyfans import onlyfans as OnlyFans
from apis.onlyfans.classes.extras import content_types
from apis.onlyfans.classes.user_model import create_user
from apis.starsavn import starsavn as StarsAVN
from bs4 import BeautifulSoup
from classes.prepare_directories import DirectoryManager
from database.databases.user_data.models.media_table import template_media_table
from mergedeep import Strategy, merge
from modules.fansly import FanslyDataScraper
from modules.onlyfans import OnlyFansDataScraper
from modules.starsavn import StarsAVNDataScraper
from sqlalchemy import inspect
from sqlalchemy.orm.session import Session
from tqdm import tqdm

import helpers.db_helper as db_helper

if TYPE_CHECKING:

    import apis.fansly.classes as fansly_classes
    import apis.onlyfans.classes as onlyfans_classes
    import apis.starsavn.classes as starsavn_classes

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

json_global_settings = {}
min_drive_space = 0
webhooks: dict[str, Any] = {}
max_threads = -1
os_name = platform.system()
proxies = None
cert = None

if os_name == "Windows":
    import ctypes

try:
    from psutil import disk_usage
except ImportError:
    import errno
    from collections import namedtuple

    # https://github.com/giampaolo/psutil/blob/master/psutil/_common.py#L176
    sdiskusage = namedtuple("sdiskusage", ["total", "used", "free", "percent"])

    # psutil likes to round the disk usage percentage to 1 decimal
    # https://github.com/giampaolo/psutil/blob/master/psutil/_common.py#L365
    def disk_usage(path: str, round_: int = 1):

        # check if path exists
        if not os.path.exists(path):
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)

        # on POSIX systems you can pass either a file or a folder path
        # Windows only allows folder paths
        if not os.path.isdir(path):
            path = os.path.dirname(path)

        if os_name == "Windows":
            total_bytes = ctypes.c_ulonglong(0)
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(path),
                None,
                ctypes.pointer(total_bytes),
                ctypes.pointer(free_bytes),
            )
            return sdiskusage(
                total_bytes.value,
                total_bytes.value - free_bytes.value,
                free_bytes.value,
                round(
                    (total_bytes.value - free_bytes.value) * 100 / total_bytes.value,
                    round_,
                ),
            )
        else:  # Linux, Darwin, ...
            st = os.statvfs(path)
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used = total - free
            return sdiskusage(total, used, free, round(100 * used / total, round_))


def getfrozencwd():
    import sys
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    else:
        return os.getcwd()


def assign_vars(config: dict[Any, Any]):
    global json_global_settings, min_drive_space, webhooks, max_threads, proxies, cert

    json_config = config
    json_global_settings = json_config["settings"]
    min_drive_space = json_global_settings["min_drive_space"]
    webhooks = json_global_settings["webhooks"]
    max_threads = json_global_settings["max_threads"]
    proxies = json_global_settings["proxies"]
    cert = json_global_settings["cert"]


def rename_duplicates(seen, filename):
    filename_lower = filename.lower()
    if filename_lower not in seen:
        seen.add(filename_lower)
    else:
        count = 1
        while filename_lower in seen:
            filename = filename + " (" + str(count) + ")"
            filename_lower = filename.lower()
            count += 1
        seen.add(filename_lower)
    return [seen, filename]


def parse_links(site_name, input_link):
    if site_name in {"onlyfans", "fansly", "starsavn"}:
        username = input_link.rsplit("/", 1)[-1]
        return username

    if site_name in {"patreon", "fourchan", "bbwchan"}:
        if "catalog" in input_link:
            input_link = input_link.split("/")[1]
            print(input_link)
            return input_link
        if input_link[-1:] == "/":
            input_link = input_link.split("/")[3]
            return input_link
        if "4chan.org" not in input_link:
            return input_link


def clean_text(string: str, remove_spaces: bool = False):
    matches = ["\n", "<br>"]
    for m in matches:
        string = string.replace(m, " ").strip()
    string = " ".join(string.split())
    string = BeautifulSoup(string, "lxml").get_text()
    SAFE_PTN = r"[|\^&+\-%*/=!:\"?><]"
    string = re.sub(SAFE_PTN, " ", string.strip()).strip()
    if remove_spaces:
        string = string.replace(" ", "_")
    return string


def format_media_set(media_set):
    merged = merge({}, *media_set, strategy=Strategy.ADDITIVE)
    if "directories" in merged:
        for directory in merged["directories"]:
            os.makedirs(directory, exist_ok=True)
        merged.pop("directories")
    return merged


async def format_image(filepath: str, timestamp: float):
    if json_global_settings["helpers"]["reformat_media"]:
        while True:
            try:
                if os_name == "Windows":
                    from win32_setctime import setctime

                    setctime(filepath, timestamp)
                    # print(f"Updated Creation Time {filepath}")
                os.utime(filepath, (timestamp, timestamp))
                # print(f"Updated Modification Time {filepath}")
            except Exception as e:
                continue
            break


async def async_downloads(
    download_list: list[template_media_table], subscription: user_types
):
    async def run(download_list: list[template_media_table]):
        session_m = subscription.get_session_manager()
        proxies = session_m.proxies
        proxy = (
            session_m.proxies[random.randint(0, len(proxies) - 1)] if proxies else ""
        )
        connector = ProxyConnector.from_url(proxy) if proxy else None
        final_cookies: dict[Any, Any] = (
            session_m.auth.auth_details.cookie.format() if session_m.use_cookies else {}
        )
        async with ClientSession(
            connector=connector,
            cookies=final_cookies,
            read_timeout=None,
        ) as session:
            tasks = []
            # Get content_lengths
            for download_item in download_list:
                link = download_item.link
                if link:
                    task = asyncio.ensure_future(
                        session_m.json_request(
                            download_item.link,
                            session,
                            method="HEAD",
                            json_format=False,
                        )
                    )
                    tasks.append(task)
            responses = await asyncio.gather(*tasks)
            tasks.clear()

            async def check(
                download_item: template_media_table, response: ClientResponse
            ):
                filepath = os.path.join(download_item.directory, download_item.filename)
                response_status = False
                if response.status == 200:
                    response_status = True
                    if response.content_length:
                        download_item.size = response.content_length

                if os.path.exists(filepath):
                    if os.path.getsize(filepath) == response.content_length:
                        download_item.downloaded = True
                    else:
                        return download_item
                else:
                    if response_status:
                        return download_item

            for download_item in download_list:
                temp_response = [
                    response
                    for response in responses
                    if response and str(response.url) == download_item.link
                ]
                if temp_response:
                    temp_response = temp_response[0]
                    task = check(download_item, temp_response)
                    tasks.append(task)
            result = await asyncio.gather(*tasks)
            download_list = [x for x in result if x]
            tasks.clear()
            progress_bar = None
            if download_list:
                progress_bar = download_session()
                progress_bar.start(unit="B", unit_scale=True, miniters=1)
                [progress_bar.update_total_size(x.size) for x in download_list]

            async def process_download(download_item: template_media_table):
                while True:
                    result = await session_m.download_content(
                        download_item, session, progress_bar, subscription
                    )
                    if result:
                        response, download_item = result.values()
                        if response:
                            download_path = os.path.join(
                                download_item.directory, download_item.filename
                            )
                            status_code = await write_data(
                                response, download_path, progress_bar
                            )
                            if not status_code:
                                pass
                            elif status_code == 1:
                                continue
                            elif status_code == 2:
                                break
                            timestamp = download_item.created_at.timestamp()
                            await format_image(download_path, timestamp)
                            download_item.size = response.content_length
                            download_item.downloaded = True
                    break

            max_threads = api_helper.calculate_max_threads(session_m.max_threads)
            download_groups = grouper(max_threads, download_list)
            for download_group in download_groups:
                tasks = []
                for download_item in download_group:
                    task = process_download(download_item)
                    if task:
                        tasks.append(task)
                await asyncio.gather(*tasks)
            if isinstance(progress_bar, download_session):
                progress_bar.close()
            return True

    results = await asyncio.ensure_future(run(download_list))
    return results


def filter_metadata(datas):
    for key, item in datas.items():
        for items in item["valid"]:
            for item2 in items:
                item2.pop("session")
    return datas


def import_archive(archive_path: Path) -> Any:
    metadata: dict[str, Any] = {}
    if (
        archive_path.exists()
        and archive_path.stat().st_size
        and archive_path.suffix != ".db"
    ):
        with open(archive_path, "r", encoding="utf-8") as outfile:
            while not metadata:
                try:
                    metadata = ujson.load(outfile)
                except OSError as e:
                    print(traceback.format_exc())
    return metadata


def legacy_database_fixer(database_path, database, database_name, database_exists):
    database_directory = os.path.dirname(database_path)
    old_database_path = database_path
    old_filename = os.path.basename(old_database_path)
    new_filename = f"Pre_Alembic_{old_filename}"
    pre_alembic_path = os.path.join(database_directory, new_filename)
    pre_alembic_database_exists = False
    if os.path.exists(pre_alembic_path):
        database_path = pre_alembic_path
        pre_alembic_database_exists = True
    datas = []
    if database_exists:
        Session, engine = db_helper.create_database_session(database_path)
        database_session = Session()
        result = inspect(engine).has_table("alembic_version")
        if not result:
            if not pre_alembic_database_exists:
                os.rename(old_database_path, pre_alembic_path)
                pre_alembic_database_exists = True
    if pre_alembic_database_exists:
        Session, engine = db_helper.create_database_session(pre_alembic_path)
        database_session = Session()
        api_table = database.api_table()
        media_table = database.media_table()
        legacy_api_table = api_table.legacy(database_name)
        legacy_media_table = media_table.legacy()
        result = database_session.query(legacy_api_table)
        post_db = result.all()
        for post in post_db:
            post_id = post.id
            created_at = post.created_at
            new_item = {}
            new_item["post_id"] = post_id
            new_item["text"] = post.text
            new_item["price"] = post.price
            new_item["paid"] = post.paid
            new_item["postedAt"] = created_at
            new_item["medias"] = []
            result2 = database_session.query(legacy_media_table)
            media_db = result2.filter_by(post_id=post_id).all()
            for media in media_db:
                new_item2 = {}
                new_item2["media_id"] = media.id
                new_item2["post_id"] = media.post_id
                new_item2["links"] = [media.link]
                new_item2["directory"] = media.directory
                new_item2["filename"] = media.filename
                new_item2["size"] = media.size
                new_item2["media_type"] = media.media_type
                new_item2["downloaded"] = media.downloaded
                new_item2["created_at"] = created_at
                new_item["medias"].append(new_item2)
            datas.append(new_item)
        print
        database_session.close()
        export_sqlite2(old_database_path, datas, database_name, legacy_fixer=True)


async def fix_sqlite(
    directory_manager: DirectoryManager,
):
    items = content_types().__dict__.items()
    for final_metadata in directory_manager.user.legacy_metadata_directories:
        archived_database_path = final_metadata.joinpath("Archived.db")
        if archived_database_path.exists():
            Session2, engine = db_helper.create_database_session(archived_database_path)
            database_session: Session = Session2()
            cwd = getfrozencwd()
            for api_type, value in items:
                database_path = os.path.join(final_metadata, f"{api_type}.db")
                database_name = api_type.lower()
                alembic_location = os.path.join(
                    cwd, "database", "archived_databases", database_name
                )
                result = inspect(engine).has_table(database_name)
                if result:
                    db_helper.run_migrations(alembic_location, archived_database_path)
                    db_helper.run_migrations(alembic_location, database_path)
                    Session3, engine2 = db_helper.create_database_session(database_path)
                    db_collection = db_helper.database_collection()
                    database_session2: Session = Session3()
                    database = db_collection.database_picker("user_data")
                    if not database:
                        return
                    table_name = database.table_picker(api_type, True)
                    if not table_name:
                        return
                    archived_result = database_session.query(table_name).all()
                    for item in archived_result:
                        result2 = (
                            database_session2.query(table_name)
                            .filter(table_name.post_id == item.post_id)
                            .first()
                        )
                        if not result2:
                            item2 = item.__dict__
                            item2.pop("id")
                            item2.pop("_sa_instance_state")
                            item = table_name(**item2)
                            item.archived = True
                            database_session2.add(item)
                    database_session2.commit()
                    database_session2.close()
            database_session.commit()
            database_session.close()
            new_filepath = Path(
                archived_database_path.parent,
                "__legacy_metadata__",
                archived_database_path.name,
            )
            shutil.move(archived_database_path, f"{new_filepath}")


def export_sqlite2(archive_path, datas, parent_type, legacy_fixer=False):
    metadata_directory = os.path.dirname(archive_path)
    os.makedirs(metadata_directory, exist_ok=True)
    cwd = getfrozencwd()
    api_type: str = os.path.basename(archive_path).removesuffix(".db")
    database_path = archive_path
    database_name = parent_type if parent_type else api_type
    database_name = database_name.lower()
    db_collection = db_helper.database_collection()
    database = db_collection.database_picker(database_name)
    if not database:
        return
    alembic_location = os.path.join(cwd, "database", "databases", database_name)
    database_exists = os.path.exists(database_path)
    if database_exists:
        if os.path.getsize(database_path) == 0:
            os.remove(database_path)
            database_exists = False
    if not legacy_fixer:
        legacy_database_fixer(database_path, database, database_name, database_exists)
    db_helper.run_migrations(alembic_location, database_path)
    print
    Session, engine = db_helper.create_database_session(database_path)
    database_session = Session()
    api_table = database.api_table
    media_table = database.media_table

    for post in datas:
        post_id = post["post_id"]
        postedAt = post["postedAt"]
        date_object = None
        if postedAt:
            if not isinstance(postedAt, datetime):
                date_object = datetime.strptime(postedAt, "%d-%m-%Y %H:%M:%S")
            else:
                date_object = postedAt
        result = database_session.query(api_table)
        post_db = result.filter_by(post_id=post_id).first()
        if not post_db:
            post_db = api_table()
        post_db.post_id = post_id
        post_db.text = post["text"]
        if post["price"] is None:
            post["price"] = 0
        post_db.price = post["price"]
        post_db.paid = post["paid"]
        post_db.archived = post["archived"]
        if date_object:
            post_db.created_at = date_object
        database_session.add(post_db)
        for media in post["medias"]:
            if media["media_type"] == "Texts":
                continue
            media_id = media.get("media_id", None)
            result = database_session.query(media_table)
            media_db = result.filter_by(media_id=media_id).first()
            if not media_db:
                media_db = result.filter_by(
                    filename=media["filename"], created_at=date_object
                ).first()
                if not media_db:
                    media_db = media_table()
            if legacy_fixer:
                media_db.size = media["size"]
                media_db.downloaded = media["downloaded"]
            media_db.media_id = media_id
            media_db.post_id = post_id
            media_db.link = media["links"][0]
            media_db.preview = media.get("preview", False)
            media_db.directory = media["directory"]
            media_db.filename = media["filename"]
            media_db.api_type = api_type
            media_db.media_type = media["media_type"]
            media_db.linked = media.get("linked", None)
            if date_object:
                media_db.created_at = date_object
            database_session.add(media_db)
            print
        print
    print

    database_session.commit()
    database_session.close()
    return Session, api_type, database


def legacy_sqlite_updater(
    legacy_metadata_path: str,
    api_type: str,
    subscription: user_types,
    delete_metadatas: list[Path],
):
    final_result: list[dict[str, Any]] = []
    if os.path.exists(legacy_metadata_path):
        cwd = getfrozencwd()
        alembic_location = os.path.join(
            cwd, "database", "archived_databases", api_type.lower()
        )
        db_helper.run_migrations(alembic_location, legacy_metadata_path)
        database_name = "user_data"
        session, engine = db_helper.create_database_session(legacy_metadata_path)
        database_session: Session = session()
        db_collection = db_helper.database_collection()
        database = db_collection.database_picker(database_name)
        if database:
            if api_type == "Messages":
                api_table_table = database.table_picker(api_type, True)
            else:
                api_table_table = database.table_picker(api_type)
            media_table_table = database.media_table.media_legacy_table
            if api_table_table:
                result = database_session.query(api_table_table).all()
                result2 = database_session.query(media_table_table).all()
                for item in result:
                    item = item.__dict__
                    item["medias"] = []
                    for item2 in result2:
                        if item["post_id"] != item2.post_id:
                            continue
                        item2 = item2.__dict__
                        item2["links"] = [item2["link"]]
                        item["medias"].append(item2)
                        print
                    item["user_id"] = subscription.id
                    item["postedAt"] = item["created_at"]
                    final_result.append(item)
                delete_metadatas.append(legacy_metadata_path)
        database_session.close()
    return final_result, delete_metadatas


def export_sqlite(database_path: str, api_type: str, datas: list[dict[str, Any]]):
    metadata_directory = os.path.dirname(database_path)
    os.makedirs(metadata_directory, exist_ok=True)
    database_name = os.path.basename(database_path).replace(".db", "")
    cwd = getfrozencwd()
    alembic_location = os.path.join(cwd, "database", "databases", database_name.lower())
    db_helper.run_migrations(alembic_location, database_path)
    Session, engine = db_helper.create_database_session(database_path)
    db_collection = db_helper.database_collection()
    database = db_collection.database_picker(database_name)
    if not database:
        return
    database_session = Session()
    api_table = database.table_picker(api_type)
    if not api_table:
        return
    for post in datas:
        post_id = post["post_id"]
        postedAt = post["postedAt"]
        date_object = None
        if postedAt:
            if not isinstance(postedAt, datetime):
                date_object = datetime.strptime(postedAt, "%d-%m-%Y %H:%M:%S")
            else:
                date_object = postedAt
        result = database_session.query(api_table)
        post_db = result.filter_by(post_id=post_id).first()
        if not post_db:
            post_db = api_table()
        if api_type == "Messages":
            post_db.user_id = post.get("user_id", None)
        post_db.post_id = post_id
        post_db.text = post["text"]
        if post["price"] is None:
            post["price"] = 0
        post_db.price = post["price"]
        post_db.paid = post["paid"]
        post_db.archived = post["archived"]
        if date_object:
            post_db.created_at = date_object
        database_session.add(post_db)
        for media in post["medias"]:
            if media["media_type"] == "Texts":
                continue
            created_at = media.get("created_at", postedAt)
            if not isinstance(created_at, datetime):
                date_object = datetime.strptime(created_at, "%d-%m-%Y %H:%M:%S")
            else:
                date_object = postedAt
            media_id = media.get("media_id", None)
            result = database_session.query(database.media_table)
            media_db = result.filter_by(media_id=media_id).first()
            if not media_db:
                media_db = result.filter_by(
                    filename=media["filename"], created_at=date_object
                ).first()
                if not media_db:
                    media_db = database.media_table()
            media_db.media_id = media_id
            media_db.post_id = post_id
            if "_sa_instance_state" in post:
                media_db.size = media["size"]
                media_db.downloaded = media["downloaded"]
            media_db.link = media["links"][0]
            media_db.preview = media.get("preview", False)
            media_db.directory = media["directory"]
            media_db.filename = media["filename"]
            media_db.api_type = api_type
            media_db.media_type = media["media_type"]
            media_db.linked = media.get("linked", None)
            if date_object:
                media_db.created_at = date_object
            database_session.add(media_db)
            print
        print
    print
    database_session.commit()
    database_session.close()
    return Session, api_type, database


def format_paths(j_directories, site_name):
    paths = []
    for j_directory in j_directories:
        paths.append(j_directory)
    return paths


def get_directory(directories: list[str], extra_path: str):
    directories = format_paths(directories, extra_path)
    new_directories = []
    if not directories:
        directories = [""]
    for directory in directories:
        if not os.path.isabs(directory):
            if directory:
                fp: str = os.path.abspath(directory)
            else:
                fp: str = os.path.abspath(extra_path)
            directory = os.path.abspath(fp)
        os.makedirs(directory, exist_ok=True)
        new_directories.append(directory)
    directory = check_space(new_directories, min_size=min_drive_space)
    return directory


def check_space(
    download_paths: list[Path],
    min_size: int = min_drive_space,
    priority: str = "download",
    create_directory: bool = True,
) -> Path:
    root = ""
    while not root:
        paths = []
        for download_path in download_paths:
            if create_directory:
                os.makedirs(download_path, exist_ok=True)
            obj_Disk = disk_usage(str(download_path))
            free = obj_Disk.free / (1024.0 ** 3)
            x = {}
            x["path"] = download_path
            x["free"] = free
            paths.append(x)
        if priority == "download":
            for item in paths:
                download_path = item["path"]
                free = item["free"]
                if free > min_size:
                    root = download_path
                    break
        elif priority == "upload":
            paths.sort(key=lambda x: x["free"])
            item = paths[0]
            root = item["path"]
    return root


def find_model_directory(username, directories) -> Tuple[str, bool]:
    download_path = ""
    status = False
    for directory in directories:
        download_path = os.path.join(directory, username)
        if os.path.exists(download_path):
            status = True
            break
    return download_path, status


def are_long_paths_enabled():
    if os_name != "Windows":
        return True

    ntdll = ctypes.WinDLL("ntdll")

    if not hasattr(ntdll, "RtlAreLongPathsEnabled"):
        return False

    ntdll.RtlAreLongPathsEnabled.restype = ctypes.c_ubyte
    ntdll.RtlAreLongPathsEnabled.argtypes = ()
    return bool(ntdll.RtlAreLongPathsEnabled())


def check_for_dupe_file(download_path, content_length):
    found = False
    if os.path.isfile(download_path):
        content_length = int(content_length)
        local_size = os.path.getsize(download_path)
        if local_size == content_length:
            found = True
    return found


class download_session(tqdm):
    def start(
        self,
        unit: str = "B",
        unit_scale: bool = True,
        miniters: int = 1,
        tsize: int = 0,
    ):
        self.unit = unit
        self.unit_scale = unit_scale
        self.miniters = miniters
        self.total = 0
        self.colour = "Green"
        if tsize:
            tsize = int(tsize)
            self.total += tsize

    def update_total_size(self, tsize: Optional[int]):
        if tsize:
            tsize = int(tsize)
            self.total += tsize


def prompt_modified(message: str, path: str):
    editor = shutil.which(
        os.environ.get("EDITOR", "notepad" if os_name == "Windows" else "nano")
    )
    if editor:
        print(message)
        subprocess.run([editor, path], check=True)
    else:
        input(message)


def get_config(config_path: Path):
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as fp:
            json_config = ujson.load(fp)
    else:
        json_config: dict[str, Any] = {}
    json_config2 = copy.deepcopy(json_config)
    json_config = make_settings.fix(json_config)
    file_name = os.path.basename(config_path)
    wow = make_settings.Config(**json_config)
    json_config = ujson.loads(
        json.dumps(
            make_settings.Config(**json_config).export(), default=lambda o: o.__dict__
        )
    )
    updated = False
    if json_config != json_config2:
        updated = True
        filepath = os.path.join(".settings", "config.json")
        export_data(json_config, filepath)
    if not json_config:
        prompt_modified(
            f"The .settings\\{file_name} file has been created. Fill in whatever you need to fill in and then press enter when done.\n",
            config_path,
        )
        with open(config_path, encoding="utf-8") as fp:
            json_config = ujson.load(fp)
    return json_config, updated


class OptionsFormat:
    def __init__(
        self,
        items: list[Any],
        options_type: str,
        auto_choice: list[int | str] | int | str | bool = False,
    ) -> None:
        self.items = items
        self.item_keys: list[str] = []
        self.string = ""
        self.auto_choice = auto_choice
        self.final_choices = []
        self.formatter(options_type)

    def formatter(self, options_type: str):
        final_string = f"Choose {options_type.capitalize()}: All = 0"
        if isinstance(self.auto_choice, str):
            self.auto_choice = self.auto_choice.split(",")

        match options_type:
            case "profiles":
                self.item_keys = [x.auth_details.username for x in self.items]
                my_string = " | ".join(
                    map(
                        lambda x: f"{self.items.index(x)+1} = {x.auth_details.username}",
                        self.items,
                    )
                )
                final_string = f"{final_string} | {my_string}"
                self.string = final_string
                final_list = self.choose_option()
                self.final_choices = [
                    key
                    for choice in final_list
                    for key in self.items
                    if choice == key.auth_details.username
                ]
            case "subscriptions":
                self.item_keys = [x.username for x in self.items]
                my_string = " | ".join(
                    map(lambda x: f"{self.items.index(x)+1} = {x.username}", self.items)
                )
                final_string = f"{final_string} | {my_string}"
                self.string = final_string
                final_list = self.choose_option()
                self.final_choices = [
                    key
                    for choice in final_list
                    for key in self.items
                    if choice == key.username
                ]

    def choose_option(self):
        input_list: list[str] = self.item_keys
        final_list: list[str] = []
        if isinstance(self.auto_choice, list):
            if not self.auto_choice:
                print(self.string)
                input_value = int(input())
                if input_value != 0:
                    input_list = []
                    input_values = [input_value]
                    for input_value in input_values:
                        try:
                            input_list.append(self.item_keys[input_value - 1])
                        except IndexError:
                            continue
            else:
                input_list = self.auto_choice
        final_list = [
            choice for choice in input_list for key in self.item_keys if choice == key
        ]
        return final_list


def choose_option(
    subscription_list, auto_scrape: Union[str, bool], use_default_message: bool = False
):
    names = subscription_list[0]
    default_message = ""
    separator = " | "
    if use_default_message:
        default_message = f"Names: Username = username {separator}"
    new_names = []
    if names:
        if isinstance(auto_scrape, bool):
            if auto_scrape:
                values = [x[1] for x in names]
            else:
                print(f"{default_message}{subscription_list[1]}")
                values = input().strip().split(",")
        else:
            if not auto_scrape:
                print(f"{default_message}{subscription_list[1]}")
                values = input().strip().split(",")
            else:
                values = auto_scrape
                if isinstance(auto_scrape, str):
                    values = auto_scrape.split(",")
        for value in values:
            if value.isdigit():
                if value == "0":
                    new_names = names[1:]
                    break
                else:
                    new_name = names[int(value)]
                    new_names.append(new_name)
            else:
                new_name = [name for name in names if value == name[1]]
                new_names.extend(new_name)
    new_names = [x for x in new_names if not isinstance(x[0], SimpleNamespace)]
    return new_names


def process_profiles(
    json_settings: dict[str, Any],
    proxies: list[str],
    api: OnlyFans.start | Fansly.start | StarsAVN.start,
):
    site_name = api.site_name
    profile_directories: list[str] = json_settings["profile_directories"]
    for profile_directory in profile_directories:
        x = os.path.join(profile_directory, site_name)
        x = os.path.abspath(x)
        os.makedirs(x, exist_ok=True)
        temp_users = os.listdir(x)
        temp_users = remove_mandatory_files(temp_users)
        if not temp_users:
            default_profile_directory = os.path.join(x, "default")
            os.makedirs(default_profile_directory)
            temp_users.append("default")
        for user in temp_users:
            user_profile = os.path.join(x, user)
            user_auth_filepath = os.path.join(user_profile, "auth.json")
            datas = {}
            if os.path.exists(user_auth_filepath):
                with open(user_auth_filepath, encoding="utf-8") as fp:
                    temp_json_auth = ujson.load(fp)
                json_auth = temp_json_auth["auth"]
                if not json_auth.get("active", None):
                    continue
                json_auth["username"] = user
                auth = api.add_auth(json_auth)
                auth.session_manager.proxies = proxies
                auth.profile_directory = user_profile
                datas["auth"] = auth.auth_details.export()
            if datas:
                export_data(datas, user_auth_filepath)
            print
        print
    return api


async def account_setup(
    auth: auth_types,
    datascraper: OnlyFansDataScraper | FanslyDataScraper | StarsAVNDataScraper,
    site_settings: make_settings.SiteSettings,
    identifiers: list[int | str] = [],
) -> tuple[bool, list[user_types]]:
    status = False
    subscriptions: list[user_types] = []
    authed = await auth.login()
    if authed.active and authed.directory_manager and site_settings:
        metadata_filepath = (
            authed.directory_manager.profile.metadata_directory.joinpath(
                "Mass Messages.json"
            )
        )
        if authed.isPerformer:
            imported = import_archive(metadata_filepath)
            if "auth" in imported:
                imported = imported["auth"]
            mass_messages = await authed.get_mass_messages(resume=imported)
            if mass_messages:
                export_data(mass_messages, metadata_filepath)
        # chats = api.get_chats()
        if identifiers or site_settings.jobs.scrape.subscriptions:
            subscriptions.extend(
                await datascraper.manage_subscriptions(
                    authed, identifiers=identifiers  # type: ignore
                )
            )
        status = True
    elif (
        auth.auth_details.email
        and auth.auth_details.password
        and site_settings.browser.auth
    ):
        # domain = "https://onlyfans.com"
        # oflogin.login(auth, domain, auth.session_manager.get_proxy())
        pass
    return status, subscriptions


async def process_jobs(
    datascraper: OnlyFansDataScraper | FanslyDataScraper | StarsAVNDataScraper,
    subscription_list: list[user_types],
):
    for authed in datascraper.api.auths:
        await datascraper.paid_content_scraper(authed)  # type: ignore
    if not subscription_list:
        print("There's nothing to scrape.")
    for subscription in subscription_list:
        # Extra Auth Support
        authed = subscription.get_authed()
        await datascraper.start_datascraper(authed, subscription.username)  # type: ignore
    return subscription_list


async def process_downloads(
    api: OnlyFans.start | Fansly.start | StarsAVN.start,
    datascraper: OnlyFansDataScraper | FanslyDataScraper | StarsAVNDataScraper,
):
    if json_global_settings["helpers"]["downloader"]:
        for auth in api.auths:
            subscriptions = await auth.get_subscriptions(refresh=False)
            for subscription in subscriptions:
                if not await subscription.if_scraped():
                    continue
                await datascraper.prepare_downloads(subscription)
                if json_global_settings["helpers"]["delete_empty_directories"]:
                    delete_empty_directories(
                        subscription.download_info.get("base_directory", "")
                    )


async def process_webhooks(
    api: OnlyFans.start | Fansly.start | StarsAVN.start, category: str, category2: str
):
    global_webhooks = webhooks["global_webhooks"]
    global_status = webhooks["global_status"]
    webhook = webhooks[category]
    webhook_state = webhook[category2]
    webhook_links = []
    webhook_status = global_status
    webhook_hide_sensitive_info = True
    if webhook_state["status"] != None:
        webhook_status = webhook_state["status"]
    if global_webhooks:
        webhook_links = global_webhooks
    if webhook_state["webhooks"]:
        webhook_links = webhook_state["webhooks"]
    if webhook_status:
        for auth in api.auths:
            await send_webhook(
                auth, webhook_hide_sensitive_info, webhook_links, category, category2
            )
        print
    print


def is_me(user_api):
    if "email" in user_api:
        return True
    else:
        return False


def open_partial(path: str) -> BinaryIO:
    prefix, extension = os.path.splitext(path)
    while True:
        partial_path = "{}-{}{}.part".format(prefix, secrets.token_hex(6), extension)
        try:
            return open(partial_path, "xb")
        except FileExistsError:
            pass


async def write_data(
    response: ClientResponse, download_path: Path, progress_bar: download_session
):
    status_code = 0
    if response.status == 200:
        total_length = 0
        os.makedirs(os.path.dirname(download_path), exist_ok=True)
        partial_path: Optional[str] = None
        try:
            with open_partial(download_path) as f:
                partial_path = f.name
                try:
                    async for data in response.content.iter_chunked(4096):
                        length = len(data)
                        total_length += length
                        progress_bar.update(length)  # type: ignore
                        f.write(data)
                except (
                    ClientPayloadError,
                    ContentTypeError,
                    ClientOSError,
                    ServerDisconnectedError,
                ) as e:
                    status_code = 1
        except:
            if partial_path:
                os.unlink(partial_path)
            raise
        else:
            if status_code:
                os.unlink(partial_path)
            else:
                try:
                    os.replace(partial_path, download_path)
                except OSError:
                    pass
    else:
        if response.content_length:
            progress_bar.update_total_size(-response.content_length)
        status_code = 2
    return status_code


def export_data(
    metadata: list[Any] | dict[str, Any], path: Path, encoding: Optional[str] = "utf-8"
):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding=encoding) as outfile:
        ujson.dump(metadata, outfile, indent=2, escape_forward_slashes=False)


def grouper(n, iterable, fillvalue: Optional[Union[str, int]] = None):
    args = [iter(iterable)] * n
    final_grouped = list(zip_longest(fillvalue=fillvalue, *args))
    if not fillvalue:
        grouped = []
        for group in final_grouped:
            group = [x for x in group if x]
            grouped.append(group)
        final_grouped = grouped
    return final_grouped


def remove_mandatory_files(files, keep=[]):
    matches = ["desktop.ini", ".DS_Store", ".DS_store", "@eaDir"]
    folders = [x for x in files if x not in matches]
    if keep:
        folders = [x for x in files if x in keep]
    return folders


def legacy_metadata(directory):
    if os.path.exists(directory):
        items = os.listdir(directory)
        matches = ["desktop.ini"]
        metadatas = []
        items = [x for x in items if x not in matches]
        if items:
            for item in items:
                path = os.path.join(directory, item)
                with open(path, encoding="utf-8") as fp:
                    metadata = ujson.load(fp)
                metadatas.append(metadata)
                print
        print


def metadata_fixer(directory):
    archive_file = os.path.join(directory, "archive.json")
    metadata_file = os.path.join(directory, "Metadata")
    if os.path.exists(archive_file):
        os.makedirs(metadata_file, exist_ok=True)
        new = os.path.join(metadata_file, "Archive.json")
        shutil.move(archive_file, new)


def ordinal(n):
    return "%d%s" % (n, "tsnrhtdd"[(n / 10 % 10 != 1) * (n % 10 < 4) * n % 10 :: 4])


def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    return "".join(random.choice(chars) for _ in range(size))


def humansize(nbytes):
    i = 0
    suffixes = ["B", "KB", "MB", "GB", "TB", "PB"]
    while nbytes >= 1024 and i < len(suffixes) - 1:
        nbytes /= 1024.0
        i += 1
    f = ("%.2f" % nbytes).rstrip("0").rstrip(".")
    return "%s %s" % (f, suffixes[i])


def byteToGigaByte(n):
    return n / math.pow(10, 9)


async def send_webhook(
    item, webhook_hide_sensitive_info, webhook_links, category, category2: str
):
    if category == "auth_webhook":
        for webhook_link in webhook_links:
            auth = item
            username = auth.username
            if webhook_hide_sensitive_info:
                username = "REDACTED"
            message = prepare_webhooks.discord()
            embed = message.embed()
            embed.title = f"Auth {category2.capitalize()}"
            embed.add_field("username", username)
            message.embeds.append(embed)
            message = ujson.loads(json.dumps(message, default=lambda o: o.__dict__))
            requests.post(webhook_link, json=message)
    if category == "download_webhook":
        subscriptions: list[create_user] = await item.get_subscriptions(refresh=False)
        for subscription in subscriptions:
            download_info = subscription.download_info
            if download_info:
                for webhook_link in webhook_links:
                    message = prepare_webhooks.discord()
                    embed = message.embed()
                    embed.title = f"Downloaded: {subscription.username}"
                    embed.add_field("username", subscription.username)
                    embed.add_field("post_count", subscription.postsCount)
                    embed.add_field("link", subscription.get_link())
                    embed.image.url = subscription.avatar
                    message.embeds.append(embed)
                    message = ujson.loads(
                        json.dumps(message, default=lambda o: o.__dict__)
                    )
                    requests.post(webhook_link, json=message)


def find_between(s, start, end):
    format = f"{start}(.+?){end}"
    x = re.search(format, s)
    if x:
        x = x.group(1)
    else:
        x = s
    return x


def delete_empty_directories(directory):
    def start(directory):
        for root, dirnames, files in os.walk(directory, topdown=False):
            for dirname in dirnames:
                full_path = os.path.realpath(os.path.join(root, dirname))
                contents = os.listdir(full_path)
                if not contents:
                    shutil.rmtree(full_path, ignore_errors=True)
                else:
                    content_count = len(contents)
                    if content_count == 1 and "desktop.ini" in contents:
                        shutil.rmtree(full_path, ignore_errors=True)

    start(directory)
    if os.path.exists(directory):
        if not os.listdir(directory):
            os.rmdir(directory)


def multiprocessing():
    if max_threads < 1:
        pool = ThreadPool()
    else:
        pool = ThreadPool(max_threads)
    return pool


def module_chooser(domain: str, json_sites: dict[str, Any]):
    string = "Select Site: "
    separator = " | "
    site_names: list[str] = []
    wl = ["onlyfans", "fansly", "starsavn"]
    bl = []
    site_count = len(json_sites)
    count = 0
    for x in json_sites:
        if not wl:
            if x in bl:
                continue
        elif x not in wl:
            continue
        string += str(count) + " = " + x
        site_names.append(x)
        if count + 1 != site_count:
            string += separator

        count += 1
    if domain and domain not in site_names:
        string = f"{domain} not supported"
        site_names = []
    return string, site_names


async def move_to_old(
    folder_directory: str,
    base_download_directories: list,
    first_letter: str,
    model_username: str,
    source: str,
):
    # MOVE TO OLD
    local_destinations = [
        os.path.join(x, folder_directory) for x in base_download_directories
    ]
    local_destination = check_space(local_destinations, min_size=100)
    local_destination = os.path.join(local_destination, first_letter, model_username)
    print(f"Moving {source} -> {local_destination}")
    shutil.copytree(source, local_destination, dirs_exist_ok=True)
    shutil.rmtree(source)


async def format_directories(
    directory_manager: DirectoryManager,
    subscription: user_types,
) -> DirectoryManager:
    from classes.prepare_metadata import prepare_reformat

    authed = subscription.get_authed()
    site_settings = authed.api.get_site_settings()
    if site_settings:
        authed_username = authed.username
        subscription_username = subscription.username
        site_name = authed.api.site_name
        p_r = prepare_reformat()
        prepared_metadata_format = await p_r.standard(
            site_name,
            authed_username,
            subscription_username,
            datetime.today(),
            site_settings.date_format,
            site_settings.text_length,
            directory_manager.root_metadata_directory,
        )
        string = await prepared_metadata_format.reformat_2(
            site_settings.metadata_directory_format
        )
        directory_manager.user.metadata_directory = Path(string)
        prepared_download_format = copy.copy(prepared_metadata_format)
        prepared_download_format.directory = directory_manager.root_download_directory
        string = await prepared_download_format.reformat_2(
            site_settings.file_directory_format
        )
        directory_manager.user.download_directory = Path(string)
        await subscription.file_manager.set_default_files(
            prepared_metadata_format, prepared_download_format
        )
        metadata_filepaths = await subscription.file_manager.find_metadata_files(
            legacy_files=False
        )
        for metadata_filepath in metadata_filepaths:
            new_m_f = directory_manager.user.metadata_directory.joinpath(
                metadata_filepath.name
            )
            if metadata_filepath != new_m_f:
                counter = 0
                while True:
                    if not new_m_f.exists():
                        shutil.move(metadata_filepath, new_m_f)
                        break
                    else:
                        new_m_f = new_m_f.with_stem(
                            f"{metadata_filepath.stem}_{counter}"
                        )
                        counter += 1
        await subscription.file_manager.set_default_files(
            prepared_metadata_format, prepared_download_format
        )
        user_metadata_directory = directory_manager.user.metadata_directory
        _user_download_directory = directory_manager.user.download_directory
        legacy_metadata_directory = user_metadata_directory
        directory_manager.user.legacy_metadata_directories.append(
            legacy_metadata_directory
        )
        items = content_types().__dict__.items()
        for api_type, _ in items:
            legacy_metadata_directory_2 = user_metadata_directory.joinpath(api_type)
            directory_manager.user.legacy_metadata_directories.append(
                legacy_metadata_directory_2
            )
        legacy_model_directory = directory_manager.root_download_directory.joinpath(
            site_name, subscription_username
        )
        directory_manager.user.legacy_download_directories.append(
            legacy_model_directory
        )
    return directory_manager
