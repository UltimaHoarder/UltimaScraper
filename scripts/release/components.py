#!/usr/bin/env python3
"""Pin, check out and verify the sibling repositories a release is built from.

The release images contain wheels built from five sibling repositories. Their
exact commits live in release/components.lock.json, so CI builds the same
sources a maintainer tested:

    scripts/release/components.py pin               # record the siblings' HEADs
    scripts/release/components.py checkout --root .. # CI: fetch exactly those
        [--mirror-base https://forge.example/owner]  # private repos from a mirror
    scripts/release/components.py verify --root ..  # HEADs match and are clean
    scripts/release/components.py export-env FILE    # *_REVISION=sha lines
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import NoReturn, Sequence

ROOT_DIR = Path(__file__).resolve().parents[2]
LOCK_FILE = ROOT_DIR / "release" / "components.lock.json"
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


class Component:
    def __init__(self, repository: str, path: str, revision_arg: str, *, mirrored: bool = False) -> None:
        self.repository = repository
        # Relative to the directory holding the UltimaScraper checkout.
        self.path = Path(path)
        # Dockerfile build argument that labels the image with this commit.
        self.revision_arg = revision_arg
        # Private upstream: CI fetches it from --mirror-base under the same name.
        self.mirrored = mirrored

    def fetch_url(self, mirror_base: str | None) -> str:
        if self.mirrored and mirror_base:
            return f"{mirror_base.rstrip('/')}/{self.repository.rsplit('/', 1)[-1]}"
        return self.repository


COMPONENTS = {
    "usr_backend": Component(
        "https://github.com/UltimaHoarder/UltimaScraperBackend.git",
        "UltimaBackends/UltimaScraperBackend",
        "USR_BACKEND_REVISION",
        mirrored=True,
    ),
    "usdb": Component(
        "https://github.com/DATAHOARDERS/UltimaScraperDB.git",
        "UltimaDatabases/UltimaScraperDB",
        "USDB_REVISION",
        mirrored=True,
    ),
    "usdb_archive": Component(
        "https://github.com/UltimaHoarder/UltimaScraperDBArchive.git",
        "UltimaDatabases/UltimaScraperDBArchive",
        "USDB_ARCHIVE_REVISION",
        mirrored=True,
    ),
    "usr_api": Component(
        "https://github.com/UltimaHoarder/UltimaScraperAPI.git",
        "UltimaScraperAPI",
        "USR_API_REVISION",
    ),
    "usr_core": Component(
        "https://github.com/UltimaHoarder/UltimaScraperCore.git",
        "UltimaScraperCore",
        "USR_CORE_REVISION",
    ),
}


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def read_lock(lock_file: Path = LOCK_FILE) -> dict[str, str]:
    """Commit per component, after checking the lock names exactly COMPONENTS."""
    document = json.loads(lock_file.read_text(encoding="utf-8"))
    if set(document) != {"schema", "components"} or document["schema"] != 1:
        fail("unsupported component lock schema")
    components = document["components"]
    if set(components) != set(COMPONENTS):
        fail("component lock does not list exactly the release components")
    commits: dict[str, str] = {}
    for name, entry in components.items():
        if set(entry) != {"repository", "commit"}:
            fail(f"invalid component lock entry: {name}")
        if entry["repository"] != COMPONENTS[name].repository:
            fail(f"component repository is not approved: {name}")
        if not SHA_RE.fullmatch(entry["commit"]):
            fail(f"component is not pinned to a full commit: {name}")
        commits[name] = entry["commit"]
    return commits


def write_lock(commits: dict[str, str], lock_file: Path = LOCK_FILE) -> None:
    document = {
        "schema": 1,
        "components": {
            name: {"repository": COMPONENTS[name].repository, "commit": commits[name]}
            for name in COMPONENTS
        },
    }
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def pin(root: Path) -> None:
    """Record each sibling's HEAD; it must already be pushed for CI to fetch it."""
    commits: dict[str, str] = {}
    for name, component in COMPONENTS.items():
        path = root / component.path
        head = git(path, "rev-parse", "HEAD")
        if not git(path, "branch", "--remotes", "--contains", head):
            fail(f"{name} HEAD {head} is not on any remote branch; push it first")
        if git(path, "status", "--porcelain", "--untracked-files=no"):
            print(f"warning: {name} has uncommitted changes that the release will not include")
        commits[name] = head
    write_lock(commits)
    print(f"Pinned {', '.join(f'{name}={sha[:12]}' for name, sha in commits.items())}")


def checkout(root: Path, mirror_base: str | None = None) -> None:
    """Fetch each pinned commit; the commit check makes the source host irrelevant."""
    commits = read_lock()
    for name, component in COMPONENTS.items():
        destination = root / component.path
        if destination.exists():
            fail(f"component checkout destination already exists: {destination}")
        destination.mkdir(parents=True)
        git(destination, "init", "--quiet")
        git(destination, "remote", "add", "origin", component.fetch_url(mirror_base))
        git(destination, "fetch", "--quiet", "--no-tags", "--depth=1", "origin", commits[name])
        git(destination, "checkout", "--quiet", "--detach", "FETCH_HEAD")
    verify(root)


def verify(root: Path) -> None:
    for name, commit in read_lock().items():
        path = root / COMPONENTS[name].path
        actual = git(path, "rev-parse", "HEAD")
        if actual != commit:
            fail(f"{name} checkout is {actual}; expected {commit}")
        if git(path, "status", "--porcelain", "--untracked-files=all"):
            fail(f"{name} checkout is dirty")


def export_env(destination: Path) -> None:
    commits = read_lock()
    with destination.open("a", encoding="utf-8") as output:
        for name, component in COMPONENTS.items():
            output.write(f"{component.revision_arg}={commits[name]}\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("pin", "checkout", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--root", type=Path, default=ROOT_DIR.parent)
        if command == "checkout":
            sub.add_argument("--mirror-base", help="where the private components are fetched from")
    commands.add_parser("export-env").add_argument("destination", type=Path)
    args = parser.parse_args(argv)

    if args.command == "export-env":
        export_env(args.destination)
    elif args.command == "checkout":
        checkout(args.root.resolve(), args.mirror_base)
    else:
        {"pin": pin, "checkout": checkout, "verify": verify}[args.command](args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
