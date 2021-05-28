from apis.onlyfans.classes import create_user
from apis.onlyfans.classes.extras import (
    auth_details,
    content_types,
    endpoint_links,
)
from apis.onlyfans.classes.create_auth import create_auth
import time
import base64
from typing import List, Optional, Union
from urllib.parse import urlparse
from urllib import parse
import hashlib
import math
from datetime import datetime
from dateutil.relativedelta import relativedelta
from itertools import chain, product
import requests

from sqlalchemy.orm.session import Session
from .. import api_helper
from mergedeep import merge, Strategy
import jsonpickle
import copy
from random import random


def create_signed_headers(link: str, auth_id: int, dynamic_rules: dict):
    # Users: 300000 | Creators: 301000
    final_time = str(int(round(time.time())))
    path = urlparse(link).path
    query = urlparse(link).query
    path = path if not query else f"{path}?{query}"
    a = [dynamic_rules["static_param"], final_time, path, str(auth_id)]
    msg = "\n".join(a)
    message = msg.encode("utf-8")
    hash_object = hashlib.sha1(message)
    sha_1_sign = hash_object.hexdigest()
    sha_1_b = sha_1_sign.encode("ascii")
    checksum = (
        sum([sha_1_b[number] for number in dynamic_rules["checksum_indexes"]])
        + dynamic_rules["checksum_constant"]
    )
    headers = {}
    headers["sign"] = dynamic_rules["format"].format(sha_1_sign, abs(checksum))
    headers["time"] = final_time
    return headers


def session_rules(session_manager: api_helper.session_manager, link) -> dict:
    headers = session_manager.headers
    if "https://onlyfans.com/api2/v2/" in link:
        dynamic_rules = session_manager.dynamic_rules
        headers["app-token"] = dynamic_rules["app_token"]
        # auth_id = headers["user-id"]
        a = [link, 0, dynamic_rules]
        headers2 = create_signed_headers(*a)
        headers |= headers2
    return headers


def session_retry_rules(r, link: str) -> int:
    """
    0 Fine, 1 Continue, 2 Break
    """
    status_code = 0
    if "https://onlyfans.com/api2/v2/" in link:
        text = r.text
        if "Invalid request sign" in text:
            status_code = 1
        elif "Access Denied" in text:
            status_code = 2
    else:
        if not r.status_code == 200:
            status_code = 1
    return status_code


class start:
    def __init__(
        self,
        custom_request=callable,
        max_threads=-1,
        original_sessions: List[requests.Session] = [],
    ) -> None:
        self.auths: list[create_auth] = []
        self.subscriptions: list[create_user] = []
        self.custom_request = custom_request
        self.max_threads = max_threads
        self.lists = None
        self.endpoint_links = endpoint_links
        self.pool = api_helper.multiprocessing()
        self.session_manager = api_helper.session_manager(
            session_rules=session_rules,
            session_retry_rules=session_retry_rules,
            max_threads=max_threads,
            original_sessions=original_sessions,
        )
        self.settings = {}

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

    def add_auth(self, option={}, only_active=False):
        if only_active and not option.get("active"):
            return
        auth = create_auth(session_manager2=self.session_manager, pool=self.pool)
        auth.auth_details = auth_details(option)
        self.auths.append(auth)
        return auth

    def close_pools(self):
        self.pool.close()
        self.session_manager.pool.close()
