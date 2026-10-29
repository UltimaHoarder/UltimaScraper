"""Fresh-process memory boundaries and the deferred operations they protect."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def isolated(source: str, tmp_path: Path):
    env = {
        "PATH": os.defpath,
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    prelude = (
        "import site, sys, socket\n"
        f"site.addsitedir({str(REPO / '.venv/lib/python3.14/site-packages')!r})\n"
        "def forbidden(*args, **kwargs):\n"
        "    raise AssertionError('Import boundary attempted network access')\n"
        "socket.socket.connect = forbidden\n"
        "socket.socket.connect_ex = forbidden\n"
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", prelude + source],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_worker_import_does_not_load_migration_execution(tmp_path):
    isolated(
        "from ultima_scraper_backend.workers.worker_pool import Worker\n"
        "assert 'alembic' not in sys.modules\n"
        "assert 'mako' not in sys.modules\n"
        "assert 'pygments.lexers.jvm' not in sys.modules\n",
        tmp_path,
    )


def test_worker_import_does_not_build_migration_schema_copies(tmp_path):
    isolated(
        "from ultima_scraper_backend.workers.worker_pool import Worker\n"
        "from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates import postgres_site as schema\n"
        "assert 'merged_metadata' not in vars(schema)\n",
        tmp_path,
    )


def test_plain_media_models_do_not_load_widevine(tmp_path):
    isolated(
        "from ultima_scraper_backend.workers.worker_pool import Worker\n"
        "from ultima_scraper_api.apis.onlyfans.classes.only_drm import DRMMedia, MediaFormatter\n"
        "assert 'pywidevine' not in sys.modules\n"
        "assert 'pymp4' not in sys.modules\n"
        "assert 'construct' not in sys.modules\n",
        tmp_path,
    )


def test_deferred_schema_is_complete_and_shared_across_threads(tmp_path):
    isolated(
        "from concurrent.futures import ThreadPoolExecutor\n"
        "from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates import postgres_site as schema\n"
        "assert 'merged_metadata' not in vars(schema)\n"
        "with ThreadPoolExecutor(max_workers=8) as pool:\n"
        "    results = list(pool.map(lambda _: schema.merged_metadata, range(16)))\n"
        "assert all(result is results[0] for result in results)\n"
        "for site in ('onlyfans', 'fansly', 'loyalfans'):\n"
        "    users = results[0].tables[site + '.users']\n"
        "    assert list(users.columns.keys()) == list(schema.UserModel.__table__.columns.keys())\n"
        "    for fk in results[0].tables[site + '.subscriptions'].foreign_keys:\n"
        "        assert fk.column.table.schema == site\n"
        "assert schema.UserModel.__table__.schema is None\n"
        "from ultima_scraper_db_archive import USDBArchiveModule\n"
        "assert USDBArchiveModule().definition.metadata is results[0]\n",
        tmp_path,
    )


def test_deferred_schema_recovers_after_construction_failure(tmp_path):
    isolated(
        "from ultima_scraper_db_archive.databases.ultima_archive.schemas.templates import postgres_site as schema\n"
        "assert 'merged_metadata' not in vars(schema)\n"
        "original = schema.create_merged_metadata\n"
        "def fail(base):\n"
        "    raise ValueError('fixture failure')\n"
        "schema.create_merged_metadata = fail\n"
        "try:\n"
        "    schema.merged_metadata\n"
        "except ValueError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('failure swallowed')\n"
        "schema.create_merged_metadata = original\n"
        "assert 'onlyfans.users' in schema.merged_metadata.tables\n",
        tmp_path,
    )


def test_deferred_widevine_keeps_device_and_session_isolation(tmp_path):
    isolated(
        "from pathlib import Path\n"
        "from ultima_scraper_api.apis.onlyfans.classes.only_drm import OnlyDRM\n"
        "assert 'pywidevine' not in sys.modules\n"
        "import pywidevine, pywidevine.cdm\n"
        "class Device:\n"
        "    def __init__(self, **kwargs): self.values = kwargs\n"
        "class Cdm:\n"
        "    @classmethod\n"
        "    def from_device(cls, device):\n"
        "        value = cls(); value.device = device; return value\n"
        "    def open(self): return object()\n"
        "pywidevine.Device = Device\n"
        "pywidevine.cdm.Cdm = Cdm\n"
        "Path('client').write_bytes(b'client fixture')\n"
        "Path('key').write_bytes(b'key fixture')\n"
        "a, b = object(), object()\n"
        "first = OnlyDRM(Path('client'), Path('key'), a, Path('decrypt'), Path('dump'), auto_start_workers=False)\n"
        "second = OnlyDRM(Path('client'), Path('key'), b, Path('decrypt'), Path('dump'), auto_start_workers=False)\n"
        "assert first.authed is a and second.authed is b\n"
        "assert first.device is not second.device and first.cdm is not second.cdm\n"
        "assert first.session_id is not second.session_id\n"
        "assert first.device.values['client_id'] == b'client fixture'\n",
        tmp_path,
    )


@pytest.mark.asyncio
async def test_deferred_pssh_parser_preserves_license_request():
    from types import SimpleNamespace
    from uuid import UUID

    from pywidevine.pssh import PSSH
    from ultima_scraper_api.apis.onlyfans.classes.only_drm import OnlyDRM

    raw = PSSH.new(
        system_id=PSSH.SystemId.Widevine,
        key_ids=[UUID("12345678-1234-5678-1234-567812345678")],
    ).dumps()
    calls = []

    def challenge(session, pssh):
        assert session == b"session fixture"
        assert pssh.key_ids == [UUID("12345678-1234-5678-1234-567812345678")]
        return b"challenge fixture"

    async def read():
        return b"license fixture"

    released = []

    async def request(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(
            read=read,
            raise_for_status=lambda: None,
            release=lambda: released.append(url),
        )

    drm = OnlyDRM.__new__(OnlyDRM)
    drm.session_id = b"session fixture"
    drm.cdm = SimpleNamespace(get_license_challenge=challenge)
    requester = SimpleNamespace(
        request=request,
        get_session_manager=lambda: SimpleNamespace(max_attempts=1),
    )
    drm.authed = SimpleNamespace(get_requester=lambda: requester)
    media = SimpleNamespace(media_id=123, content_id=456, content_type="posts")
    assert await drm.get_license(media, raw) == b"license fixture"
    assert len(calls) == 1
    assert "/media/123/drm/post/456" in calls[0][0]
    assert calls[0][1] == {"method": "POST", "data": b"challenge fixture"}
    assert released == [calls[0][0]]  # the license response is always released


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_migration_upgrade_preserves_config_connection_and_failure(
    tmp_path, monkeypatch, fail
):
    from contextlib import asynccontextmanager

    from alembic import command
    from sqlalchemy.engine import make_url
    from ultima_scraper_db import MigrationBundle, MigrationRunner

    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    (tmp_path / "alembic").mkdir()
    bundle = MigrationBundle(tmp_path)
    connection = object()
    calls = []

    def upgrade(config, revision):
        calls.append((config, revision))
        assert config.attributes["connection"] is connection
        assert config.get_main_option("sqlalchemy.url").endswith("db%25name")
        if fail:
            raise ValueError("migration rejected")

    monkeypatch.setattr(command, "upgrade", upgrade)

    class Engine:
        url = make_url("postgresql+asyncpg://local/db%25name")
        exited = False

        @asynccontextmanager
        async def begin(self):
            try:
                yield self
            finally:
                self.exited = True

        async def run_sync(self, callback):
            return callback(connection)

    engine = Engine()
    if fail:
        with pytest.raises(ValueError, match="migration rejected"):
            await MigrationRunner().upgrade(engine, bundle, "fixture-revision")
    else:
        await MigrationRunner().upgrade(engine, bundle, "fixture-revision")
    assert engine.exited
    assert len(calls) == 1 and calls[0][1] == "fixture-revision"
