from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from cryptography import x509

from ultima_webui_server import Settings, create_app
from ultima_webui_server.__main__ import server_options
from ultima_webui_server.tls import TLSConfigurationError, ensure_self_signed, fingerprint, tls_files, tls_requested


def _names(cert_file: Path) -> set[str]:
    certificate = x509.load_pem_x509_certificate(cert_file.read_bytes())
    alternative = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    return {str(name.value) for name in alternative}


def test_plain_http_unless_configured(tmp_path: Path) -> None:
    assert tls_files(tmp_path, {}) is None
    assert tls_files(tmp_path, {"USR_WEBUI_TLS": "off"}) is None
    assert not tls_requested({})


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"USR_WEBUI_TLS_CERT_FILE": "/x/cert.pem"}, "both"),
        ({"USR_WEBUI_TLS_CERT_FILE": "/missing/cert.pem", "USR_WEBUI_TLS_KEY_FILE": "/missing/key.pem"}, "does not exist"),
        ({"USR_WEBUI_TLS": "letsencrypt"}, "self-signed"),
    ],
)
def test_incomplete_settings_are_refused(tmp_path: Path, environ: dict, message: str) -> None:
    with pytest.raises(TLSConfigurationError, match=message):
        tls_files(tmp_path, environ)


def test_a_self_signed_certificate_is_kept_and_renewed_for_new_names(tmp_path: Path) -> None:
    first = tls_files(tmp_path, {"USR_WEBUI_TLS": "self-signed", "USR_WEBUI_TLS_HOSTNAMES": "nas.lan, 10.0.0.5"})
    assert first is not None and first.self_signed
    assert {"localhost", "127.0.0.1", "nas.lan", "10.0.0.5"} <= _names(first.cert_file)
    assert first.key_file.stat().st_mode & 0o777 == 0o600
    pem = first.cert_file.read_bytes()

    # Kept while it covers the names asked for.
    again = ensure_self_signed(tmp_path / "tls", ["nas.lan", "10.0.0.5"])
    assert again.cert_file.read_bytes() == pem
    # A new name gets a new certificate.
    renewed = ensure_self_signed(tmp_path / "tls", ["nas.lan", "10.0.0.5", "usr.example.test"])
    assert renewed.cert_file.read_bytes() != pem and "usr.example.test" in _names(renewed.cert_file)
    assert len(fingerprint(renewed.cert_file).split(":")) == 32


def test_your_own_certificate_is_served_as_given(tmp_path: Path) -> None:
    made = ensure_self_signed(tmp_path / "made")
    given = tls_files(
        tmp_path,
        {"USR_WEBUI_TLS_CERT_FILE": str(made.cert_file), "USR_WEBUI_TLS_KEY_FILE": str(made.key_file)},
    )
    assert given is not None and not given.self_signed and given.cert_file == made.cert_file


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_the_server_answers_over_https_and_its_healthcheck_follows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ultima_webui_server import healthcheck

    port = _free_port()
    monkeypatch.setenv("USR_WEBUI_TLS", "self-signed")
    monkeypatch.setenv("USR_WEBUI_PORT", str(port))
    settings = Settings(data_dir=tmp_path / "data", static_dir=tmp_path, host="127.0.0.1", port=port)
    options = server_options(settings)
    assert options["ssl_certfile"].endswith("cert.pem") and options["proxy_headers"] is False

    server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="warning", **options))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert healthcheck.main() == 0
        # Over HTTPS the session cookie is Secure.
        import httpx

        origin = f"https://127.0.0.1:{port}"
        claimed = httpx.post(
            f"{origin}/webui/api/v1/session/claim",
            json={"password": "a-long-password"},
            headers={"origin": origin},
            verify=False,
        )
        assert claimed.status_code == 204 and "secure" in claimed.headers["set-cookie"].lower()
        # Asked over plain HTTP, the same port does not answer as healthy.
        monkeypatch.delenv("USR_WEBUI_TLS")
        assert healthcheck.main() == 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_the_native_public_port_serves_https(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ultima_webui_server import launcher

    monkeypatch.setenv("USR_WEBUI_TLS", "self-signed")
    monkeypatch.setenv("USR_WEBUI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("USR_WEBUI_PORT", raising=False)

    alone = launcher.WebUIServer(tmp_path, behind_dev_server=False)
    assert alone.url.startswith("https://") and alone.child_environment()["USR_WEBUI_TLS"] == "self-signed"

    # Behind the dev server, it terminates HTTPS; the loopback hop stays plain.
    behind = launcher.WebUIServer(tmp_path, behind_dev_server=True)
    assert behind.url.startswith("http://") and "USR_WEBUI_TLS" not in behind.child_environment()
    cert_file, key_file = launcher.resolve_tls()
    assert cert_file.is_file() and key_file.is_file()
