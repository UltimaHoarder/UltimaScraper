from __future__ import annotations

import pytest
from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from starlette.requests import Request

from ultima_scraper_backend.security import (
    SECURITY_METRICS,
    ensure_http_admin_auth,
    redact_sensitive_text,
    validate_outbound_url,
)
from ultima_scraper_db_archive import crypto as crypto_module
from ultima_scraper_db_archive.crypto import (
    decrypt_secret_value,
    encrypt_secret_value,
    is_encrypted_secret,
)


def _build_request(
    path: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "headers": headers or [(b"host", b"127.0.0.1")],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 21121),
    }
    return Request(scope)


def test_security_auth_required_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY_ENFORCEMENT", "strict")
    monkeypatch.setenv("USR_ADMIN_TOKEN_REQUIRED", "true")
    monkeypatch.setenv("USR_ADMIN_TOKEN", "test-admin-token")

    request = _build_request("/api/v1/jobs")
    with pytest.raises(HTTPException) as exc:
        ensure_http_admin_auth(
            request,
            request_id="req-1",
            bypass_paths={"/api/v1/admin/health"},
        )
    assert exc.value.status_code == 401

    authorized_request = _build_request(
        "/api/v1/jobs",
        headers=[
            (b"host", b"127.0.0.1"),
            (b"authorization", b"Bearer test-admin-token"),
        ],
    )
    ensure_http_admin_auth(
        authorized_request,
        request_id="req-2",
        bypass_paths={"/api/v1/admin/health"},
    )

    query_token_request = _build_request(
        "/api/v1/jobs/stream",
        query_string=b"admin_token=test-admin-token",
    )
    ensure_http_admin_auth(
        query_token_request,
        request_id="req-3",
        bypass_paths={"/api/v1/admin/health"},
    )


def test_security_ssrf_block_local_targets() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_outbound_url(
            "http://127.0.0.1:8000/private",
            allowed_domains=["127.0.0.1"],
            allow_private=False,
        )
    assert exc.value.status_code == 403


def test_security_secret_encryption_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USR_ENCRYPT_SECRETS", "true")
    monkeypatch.setenv("USR_SECRET_KEY", "unit-test-key")
    crypto_module.get_secret_crypto.cache_clear()

    encrypted = encrypt_secret_value("super-secret")
    assert isinstance(encrypted, str)
    assert encrypted != "super-secret"
    assert is_encrypted_secret(encrypted)
    assert decrypt_secret_value(encrypted) == "super-secret"


@pytest.mark.parametrize("database_value", [False, True])
@pytest.mark.parametrize("missing_key", [False, True])
def test_archive_crypto_reports_each_decryption_failure_once(
    monkeypatch: pytest.MonkeyPatch, database_value: bool, missing_key: bool
) -> None:
    encrypted = crypto_module.SecretCrypto("original-key").encrypt("secret")
    crypto = None if missing_key else crypto_module.SecretCrypto("wrong-key")
    monkeypatch.setattr(crypto_module, "get_secret_crypto", lambda: crypto)
    before = SECURITY_METRICS["secret_decrypt_fail_total"]

    with pytest.raises(RuntimeError if missing_key else InvalidToken):
        if database_value:
            crypto_module.EncryptedText().process_result_value(encrypted, None)
        else:
            decrypt_secret_value(encrypted)

    assert SECURITY_METRICS["secret_decrypt_fail_total"] == before + 1


def test_security_log_redaction() -> None:
    redacted = redact_sensitive_text(
        "Authorization: Bearer abc123 token=abc cookie=sessionid=xyz password=hunter2"
    )
    assert "abc123" not in redacted
    assert "hunter2" not in redacted
    assert "[REDACTED]" in redacted
