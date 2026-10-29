"""Controlled platform responses and normal-job submission for owned runtime runs."""

import hashlib
import json
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import text


class PlatformHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    lock = threading.Lock()
    requests = 0
    active = 0
    peak = 0
    missing: ClassVar[set[str]] = set()
    body = b""
    files = 0
    delay = 0

    def respond(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        cls = type(self)
        parsed = urlsplit(self.path)
        path = parsed.path
        if path.endswith("/rules"):
            self.respond(
                {
                    "static_param": "fixture",
                    "format": "{}:{}",
                    "checksum_indexes": [0],
                    "checksum_constants": [0],
                    "checksum_constant": 0,
                    "app_token": "fixture",
                    "remove_headers": [],
                }
            )
        elif path.endswith(".jpg"):
            first, last = 0, len(cls.body) - 1
            status = 200
            if value := self.headers.get("Range"):
                start, end = value.removeprefix("bytes=").split("-")
                first, last = int(start), int(end) if end else last
                status = 206
            self.send_response(status)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(last - first + 1))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header(
                    "Content-Range", f"bytes {first}-{last}/{len(cls.body)}"
                )
            self.end_headers()
            if self.command == "HEAD":
                return
            with cls.lock:
                cls.active += 1
                cls.peak = max(cls.peak, cls.active)
                cls.requests += 1
            try:
                time.sleep(cls.delay)
                self.wfile.write(cls.body[first : last + 1])
            finally:
                with cls.lock:
                    cls.active -= 1
        elif path == "/api2/v2/users/me":
            self.respond(
                {
                    "id": 99,
                    "username": "fixture-buyer",
                    "name": "Fixture buyer",
                    "isAuth": True,
                    "postsCount": 0,
                    "subscribedBy": True,
                    "subscribePrice": 0,
                }
            )
        elif path == "/api2/v2/issues/login":
            self.respond({"data": []})
        elif path.startswith("/api2/v2/users/"):
            rest = path.removeprefix("/api2/v2/users/").split("/")
            user_id = int(rest[0]) if rest[0].isdigit() else 99
            if len(rest) == 1:
                self.respond(
                    {
                        "id": user_id,
                        "username": f"performer{user_id}",
                        "name": f"Performer {user_id}",
                        "isAuth": False,
                        "postsCount": cls.files,
                        "photosCount": cls.files,
                        "mediasCount": cls.files,
                        "subscribedBy": True,
                        "subscribePrice": 0,
                        "canViewStory": True,
                        "avatar": None,
                        "header": None,
                    }
                )
            elif rest[1] == "posts":
                offset = int(parse_qs(parsed.query).get("offset", ["0"])[0])
                limit = int(parse_qs(parsed.query).get("limit", ["50"])[0])
                base = f"http://127.0.0.1:{self.server.server_port}"
                self.respond(
                    [
                        {
                            "id": user_id * 1000000 + i,
                            "responseType": "post",
                            "price": 0,
                            "postedAt": "2026-09-07T00:00:00+00:00",
                            "postedAtPrecise": "0",
                            "text": "Fixture post",
                            "media": [
                                {
                                    "id": user_id * 1000000 + i,
                                    "type": "photo",
                                    "canView": True,
                                    "files": {
                                        "full": {
                                            "url": f"{base}/{user_id * 1000000 + i}.jpg",
                                            "size": len(cls.body),
                                        }
                                    },
                                }
                            ],
                        }
                        for i in range(offset, min(offset + limit, cls.files))
                    ]
                )
            elif rest[1] in {"socials", "links"}:
                self.respond([])
            else:
                cls.missing.add(path)
                self.respond(
                    {
                        "error": {
                            "code": 404,
                            "message": "Unconfigured fixture endpoint",
                        }
                    },
                    404,
                )
        else:
            cls.missing.add(path)
            self.respond(
                {"error": {"code": 404, "message": "Unconfigured fixture endpoint"}},
                404,
            )

    def log_message(self, *args):
        pass


def job_payload(profile, files, *, live=False):
    payload = {
        "job_name": f"Owned profile {profile}",
        "created_by": "runtime-benchmark",
        "tasks": [
            {
                "task_type": "scrape_and_download",
                "params": {
                    "site": "OnlyFans",
                    "user_id": profile,
                    "username": f"performer{profile}",
                    "auth_id": 99,
                    "content_types": ["Posts"],
                    "max_items": files,
                },
            }
        ],
    }
    if live:
        payload["job_name"] = f"Guest onlyfans cycle {profile}"
        payload["tasks"] = [
            {
                "task_type": "scrape_user",
                "params": {
                    "site": "OnlyFans",
                    "username": "onlyfans",
                    "use_guest_auth": True,
                    "download_media": True,
                    "content_types": ["Posts"],
                    "max_items": files,
                },
            }
        ]
    return payload


def submit(port, profile, files, *, live=False):
    payload = job_payload(profile, files, live=live)
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/jobs",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "X-USR-Admin-Token": "fixture-local-only",
        },
    )
    try:
        # Job creation imports and persists the normal ledger definition. Allow
        # for ARM64 CPU emulation without retrying a potentially accepted POST.
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)["job_id"]
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Owned job submission failed: {exc.code} {exc.read().decode()}"
        ) from exc


def network_metrics(directory):
    combined = {
        "auths": {},
        "performers": {},
        "active_downloads": 0,
        "peak_downloads": 0,
        "real_downloads": 0,
        "downloaded_bytes": 0,
    }
    for path in directory.glob("network-*.json"):
        row = json.loads(path.read_text())
        for name in ("auths", "performers"):
            combined[name].update(row[name])
        for name in ("active_downloads", "real_downloads", "downloaded_bytes"):
            combined[name] += row[name]
        combined["peak_downloads"] = max(
            combined["peak_downloads"], row["peak_downloads"]
        )
    return combined


def verify_live_cycle(engine, media_directory, job_id, *, output=None):
    """Verify this cycle's persisted sizes and files without exposing signed URLs."""
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM onlyfans.user_auths")) == 0
        users = connection.execute(
            text(
                "SELECT id,username FROM onlyfans.users WHERE lower(username)='onlyfans'"
            )
        ).all()
        assert len(users) == 1, users
        user_id = users[0].id
        rows = connection.execute(
            text("""
            SELECT m.id,m.size,f.filepath FROM onlyfans.media m
            JOIN onlyfans.filepaths f ON f.media_id=m.id
            WHERE m.user_id=:user_id AND m.downloaded AND f.downloaded
            ORDER BY m.id,f.id
        """),
            {"user_id": user_id},
        ).all()
        tasks = connection.execute(
            text("""
            SELECT status,result_json FROM management.job_tasks WHERE job_id=:job_id
        """),
            {"job_id": job_id},
        ).all()
    if output is not None:
        diagnostics = []
        for row in tasks:
            result = (
                json.loads(row.result_json)
                if isinstance(row.result_json, str)
                else row.result_json
            )
            diagnostics.append(
                {
                    "status": row.status,
                    "success": result.get("success"),
                    "message": result.get("message"),
                    "errors": result.get("errors"),
                    "metrics": result.get("metrics"),
                    "failure_breakdown": (result.get("output") or {}).get(
                        "failure_breakdown"
                    ),
                }
            )
        safe = re.sub(
            r'https?://[^\s"<>]+', "<redacted URL>", json.dumps(diagnostics, indent=2)
        )
        (output / f"{job_id}-tasks.json").write_text(safe + "\n")
    assert rows, (
        "Guest onlyfans yielded no downloaded media; see persisted task diagnostics"
    )
    assert len(tasks) == 2 and all(row.status == "completed" for row in tasks), tasks
    for row in tasks:
        result = row.result_json
        if isinstance(result, str):
            result = json.loads(result)
        assert result["success"], "A task reported failure"
        assert not result.get("metrics", {}).get("failed", 0), "A download failed"
    entries = []
    for row in rows:
        path = Path(row.filepath).resolve()
        assert path.is_relative_to(media_directory.resolve()), (
            "File escaped owned media root"
        )
        assert row.size > 0 and path.stat().st_size == row.size, (
            "Persisted size differs from file"
        )
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        entries.append({"media_id": row.id, "bytes": row.size, "sha256": digest})
    return {
        "job_id": job_id,
        "user_id": user_id,
        "username": users[0].username,
        "files_verified": len(entries),
        "bytes_verified": sum(row["bytes"] for row in entries),
        "files": entries,
        "stored_auths": 0,
    }


def reset_live_media(engine, media_directory, user_id):
    """Re-arm only the disposable performer after all its tasks have finished."""
    with engine.begin() as connection:
        paths = connection.scalars(
            text("""
            SELECT f.filepath FROM onlyfans.filepaths f
            JOIN onlyfans.media m ON f.media_id=m.id WHERE m.user_id=:user_id
        """),
            {"user_id": user_id},
        ).all()
        for filename in paths:
            path = Path(filename).resolve()
            assert path.is_relative_to(media_directory.resolve()), (
                "Refusing unowned file removal"
            )
            path.unlink(missing_ok=True)
        connection.execute(
            text("""
            UPDATE onlyfans.filepaths SET downloaded=false
            WHERE media_id IN (SELECT id FROM onlyfans.media WHERE user_id=:user_id)
        """),
            {"user_id": user_id},
        )
        connection.execute(
            text("UPDATE onlyfans.media SET downloaded=false WHERE user_id=:user_id"),
            {"user_id": user_id},
        )


def progress(engine, job_ids):
    if not job_ids:
        return {}
    with engine.connect() as connection:
        return {
            row.job_id: dict(row._mapping)
            for row in connection.execute(
                text("""
            SELECT job_id, status, result_message, result_error, result_data_json
            FROM management.jobs WHERE job_id=ANY(:ids)
        """),
                {"ids": job_ids},
            )
        }


def verify(engine, media_directory, *, profiles, files, body):
    expected = profiles * files
    with engine.connect() as connection:
        downloaded = connection.scalar(
            text("SELECT count(*) FROM onlyfans.media WHERE downloaded")
        )
        evidence = dict(
            connection.execute(
                text(
                    "SELECT kind,count(*) FROM management.task_media_evidence GROUP BY kind"
                )
            ).all()
        )
        failures = connection.scalar(
            text("SELECT count(*) FROM management.job_tasks WHERE status='failed'")
        )
        attempts = dict(
            connection.execute(
                text(
                    "SELECT state,count(*) FROM management.execution_attempts GROUP BY state"
                )
            ).all()
        )
    assert downloaded == expected, (downloaded, expected)
    assert evidence == {"files": expected, "download_results": expected}, evidence
    assert failures == 0, failures
    assert attempts == {"completed": profiles * 2}, attempts
    digest = hashlib.sha256(body).digest()
    checked = 0
    for path in media_directory.rglob("*.jpg"):
        with path.open("rb") as source:
            assert hashlib.file_digest(source, "sha256").digest() == digest, path
        checked += 1
    assert checked == expected, (checked, expected)
    return {
        "downloaded": downloaded,
        "files_verified": checked,
        "bytes_verified": checked * len(body),
        "evidence": evidence,
        "ledger_attempts": attempts,
    }


def verify_history(port, job_ids):
    """Check all generated jobs remain readable after Redis cache retirement."""

    def get(path):
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1/{path}",
            headers={"X-USR-Admin-Token": "fixture-local-only"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    seen = set()
    page = 1
    while True:
        rows = get(f"jobs?page={page}&page_size=17")["jobs"]
        for row in rows:
            assert row["status"] == "completed", row
            assert row["task_count"] == row["completed_tasks"] == 2, row
            assert row["job_id"] not in seen, row
            seen.add(row["job_id"])
        if len(rows) < 17:
            break
        page += 1
        assert page <= len(job_ids) // 17 + 2
    assert seen == set(job_ids), (len(seen), len(job_ids))
    oldest = get(f"jobs/{job_ids[0]}")
    assert oldest["status"] == "completed", oldest
    assert oldest["task_stats"]["total"] == oldest["task_stats"]["completed"] == 2
    tasks = get(f"jobs/{job_ids[0]}/tasks?limit=10")["tasks"]
    assert len(tasks) == 2 and all(
        row["status"] == "completed" and row["result"]["success"] for row in tasks
    ), tasks
    return {
        "jobs_verified": len(seen),
        "pages": page,
        "oldest_job_tasks_verified": len(tasks),
    }
