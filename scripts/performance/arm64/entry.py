"""Launch the owned stack; replace platform traffic only in offline fixture mode."""

import ipaddress
import json
import multiprocessing
import os
import site
import socket
import sys
from pathlib import Path

REPO = Path(os.environ.get("USR_BENCH_REPO", "/srv/usr/project/UltimaScraper"))
OFFLINE = os.environ["USR_BENCH_WORKLOAD"] == "offline-fixture"
site.addsitedir(str(REPO / ".venv/lib/python3.14/site-packages"))
sys.path.insert(0, str(REPO))

if os.environ.get("USR_BENCH_DIAGNOSTICS") == "1":
    # Spawn re-imports this entry point for each owned Python process.
    sys.path.insert(0, str(Path(__file__).parent))
    from diagnostics import install

    install()

# Fail on accidental upstream traffic. PostgreSQL has its own private Unix
# socket; the only TCP destinations are the owned Redis, rules and API ports.
allowed_ports = {int(value) for value in os.environ["FIXTURE_ALLOWED_PORTS"].split(",")}
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex


def guard(address):
    if isinstance(address, tuple):
        host, port = address[:2]
        if not ipaddress.ip_address(host).is_loopback or port not in allowed_ports:
            raise RuntimeError(f"Offline fixture forbids TCP destination {host}:{port}")


def connect(self, address):
    guard(address)
    return original_connect(self, address)


def connect_ex(self, address):
    guard(address)
    return original_connect_ex(self, address)


if OFFLINE:
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex

from urllib.parse import urlsplit, urlunsplit

import aiohttp

original_request = aiohttp.ClientSession._request


async def local_platform_request(self, method, url, **kwargs):
    parts = urlsplit(str(url))
    if parts.hostname == "onlyfans.com":
        base = urlsplit(os.environ["FIXTURE_PLATFORM_URL"])
        url = urlunsplit(
            (base.scheme, base.netloc, parts.path, parts.query, parts.fragment)
        )
    return await original_request(self, method, url, **kwargs)


if OFFLINE:
    aiohttp.ClientSession._request = local_platform_request

if multiprocessing.current_process().name.startswith("UltimaWorker-"):
    from ultima_scraper_api import UltimaScraperAPI

    async def offline_guest_init(self, ignore_sites=None):
        # Real API objects and pools are constructed; guest network authentication
        # is excluded; authenticated login uses the owned HTTP platform fixture.
        pass

    if OFFLINE:
        UltimaScraperAPI.init = offline_guest_init

    from ultima_scraper_api.managers.websocket_manager.connection import (
        WebSocketConnection,
    )
    from ultima_scraper_backend.workers.worker_pool import Worker

    async def offline_platform_websocket(self):
        # Retain the real connection object/callbacks; external push traffic is
        # not part of this controlled scrape/download workload.
        return None

    if OFFLINE:
        WebSocketConnection.start = offline_platform_websocket

    if not OFFLINE:
        from ultima_scraper_api.apis.onlyfans.classes.auth_model import (
            OnlyFansAuthModel,
        )
        from ultima_scraper_api.apis.onlyfans.onlyfans import OnlyFansAPI
        from ultima_scraper_backend.job_system.download_manager import DownloadManager

        traffic = {
            "auths": {},
            "performers": {},
            "active_downloads": 0,
            "peak_downloads": 0,
            "real_downloads": 0,
            "downloaded_bytes": 0,
        }

        def save_traffic():
            path = (
                Path(os.environ["FIXTURE_METRICS_DIR"]) / f"network-{os.getpid()}.json"
            )
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(traffic) + "\n")
            temporary.replace(path)

        original_login = OnlyFansAPI.login

        async def guest_login(self, *args, **kwargs):
            if not kwargs.get("guest", False):
                raise RuntimeError(
                    "The onlyfans benchmark requires guest authentication"
                )
            authed = await original_login(self, *args, **kwargs)
            if authed is None or not authed.guest:
                raise RuntimeError("OnlyFans did not create a guest session")
            traffic["auths"][str(authed.id)] = {"guest": bool(authed.guest)}
            save_traffic()
            return authed

        OnlyFansAPI.login = guest_login
        original_get_user = OnlyFansAuthModel.get_user

        async def onlyfans_user(self, *args, **kwargs):
            if not self.guest:
                raise RuntimeError("A non-guest auth reached the benchmark workload")
            user = await original_get_user(self, *args, **kwargs)
            if user is not None:
                if user.username.casefold() != "onlyfans":
                    raise RuntimeError("The benchmark resolved an unexpected performer")
                traffic["performers"][str(user.id)] = {"username": user.username}
                save_traffic()
            return user

        OnlyFansAuthModel.get_user = onlyfans_user
        original_download = DownloadManager.download

        async def measured_download(self, item):
            traffic["active_downloads"] += 1
            traffic["peak_downloads"] = max(
                traffic["peak_downloads"], traffic["active_downloads"]
            )
            save_traffic()
            try:
                outcome = await original_download(self, item)
                if outcome and item.downloaded_this_run:
                    traffic["real_downloads"] += 1
                    traffic["downloaded_bytes"] += item.size or 0
                return outcome
            finally:
                traffic["active_downloads"] -= 1
                save_traffic()

        DownloadManager.download = measured_download

    original_execute = Worker._execute_ready_task

    async def record_task(self, job_id, task_id, **kwargs):
        try:
            return await original_execute(self, job_id, task_id, **kwargs)
        finally:
            counts = {}
            for site_name, api in self.apis.items():
                auths = api.auths.values() if isinstance(api.auths, dict) else api.auths
                counts[site_name] = {
                    str(auth.id): {
                        "users": len(auth.users),
                        "subscriptions": len(auth.subscriptions),
                        "user_timers": len(auth.cache.data["users"]),
                        "chats": len(auth.chats),
                        "cached_posts": sum(
                            len(user.scrape_manager.scraped.Posts)
                            for user in auth.users.values()
                        ),
                    }
                    for auth in auths
                }
            entry = {
                "pid": os.getpid(),
                "job_id": job_id,
                "task_id": task_id,
                "cache_counts": counts,
            }
            path = (
                Path(os.environ["FIXTURE_METRICS_DIR"]) / f"worker-{os.getpid()}.jsonl"
            )
            with path.open("a") as output:
                output.write(json.dumps(entry) + "\n")

    Worker._execute_ready_task = record_task

    original_initialize = Worker.initialize

    async def instrument_initialize(self):
        result = await original_initialize(self)
        if result:
            (Path(os.environ["FIXTURE_READY_DIR"]) / str(os.getpid())).write_text(
                json.dumps({"pid": os.getpid(), "worker_id": self.worker_id})
            )
        return result

    Worker.initialize = instrument_initialize

if __name__ == "__main__":
    from main import cli_main

    cli_main()
