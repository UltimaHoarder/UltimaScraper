"""Encryption for backend tokens stored on disk.

This keeps tokens out of plain sight in backups and copies of the database. It
does not protect against someone who can read the data directory, because the
key lives there too unless USR_WEBUI_SECRET_KEY(_FILE) supplies it.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import env_secret

_PREFIX = "v1:"


def load_or_create_key(data_dir: Path) -> bytes:
    """The configured key, or one generated once into the data directory."""
    configured = env_secret("USR_WEBUI_SECRET_KEY")
    if configured is None:
        key_file = data_dir / "secrets" / "USR_WEBUI_SECRET_KEY"
        if not key_file.exists():
            key_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            candidate = key_file.with_name(f".{key_file.name}.{os.getpid()}")
            candidate.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            candidate.chmod(0o600)
            try:
                # link refuses an existing target, so concurrent starts keep one key.
                os.link(candidate, key_file)
            except FileExistsError:
                pass
            finally:
                candidate.unlink(missing_ok=True)
        configured = key_file.read_text(encoding="utf-8").strip()
    return hashlib.sha256(configured.encode("utf-8")).digest()


class Vault:
    def __init__(self, key: bytes) -> None:
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(12)
        sealed = self._aead.encrypt(nonce, plaintext.encode("utf-8"), None)
        return _PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode("ascii")

    def decrypt(self, stored: str) -> str:
        if not stored.startswith(_PREFIX):
            raise ValueError("Unknown encrypted value format")
        raw = base64.urlsafe_b64decode(stored[len(_PREFIX):])
        return self._aead.decrypt(raw[:12], raw[12:], None).decode("utf-8")
