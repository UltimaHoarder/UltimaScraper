"""HTTPS for the WebUI: a certificate you supply, or a self-signed one kept here.

USR_WEBUI_TLS_CERT_FILE and USR_WEBUI_TLS_KEY_FILE name a certificate and key
(e.g. from your own CA, or Let's Encrypt). USR_WEBUI_TLS=self-signed creates
one in the data directory instead, for this machine's names and addresses plus
USR_WEBUI_TLS_HOSTNAMES; browsers ask you to trust it once.
"""

from __future__ import annotations

import os
from pathlib import Path

from ultima_scraper_core.tls import TLSFiles, fingerprint
from ultima_scraper_core.tls import ensure_self_signed as _ensure_self_signed

_SELF_SIGNED = "self-signed"


class TLSConfigurationError(ValueError):
    pass


def tls_requested(environ: dict[str, str] | None = None) -> bool:
    """Whether HTTPS is configured, without creating anything."""
    env = os.environ if environ is None else environ
    mode = (env.get("USR_WEBUI_TLS") or "").strip().lower()
    return bool((env.get("USR_WEBUI_TLS_CERT_FILE") or "").strip()) or mode == _SELF_SIGNED


def tls_files(data_dir: Path, environ: dict[str, str] | None = None) -> TLSFiles | None:
    """The certificate to serve, from the environment; None serves plain HTTP."""
    env = os.environ if environ is None else environ
    cert = (env.get("USR_WEBUI_TLS_CERT_FILE") or "").strip()
    key = (env.get("USR_WEBUI_TLS_KEY_FILE") or "").strip()
    mode = (env.get("USR_WEBUI_TLS") or "").strip().lower()
    if cert or key:
        if not (cert and key):
            raise TLSConfigurationError("Set both USR_WEBUI_TLS_CERT_FILE and USR_WEBUI_TLS_KEY_FILE.")
        for path in (cert, key):
            if not Path(path).is_file():
                raise TLSConfigurationError(f"{path} does not exist.")
        return TLSFiles(Path(cert), Path(key))
    if mode in {"", "off", "0", "false", "no"}:
        return None
    if mode != _SELF_SIGNED:
        raise TLSConfigurationError("USR_WEBUI_TLS must be self-signed, or set the certificate files.")
    extra = [name.strip() for name in (env.get("USR_WEBUI_TLS_HOSTNAMES") or "").split(",") if name.strip()]
    return ensure_self_signed(data_dir / "tls", extra)


def ensure_self_signed(directory: Path, extra_names: list[str] | None = None) -> TLSFiles:
    """The WebUI's self-signed certificate (see ultima_scraper_core.tls)."""
    return _ensure_self_signed(directory, extra_names, common_name="UltimaScraper WebUI")


__all__ = ["TLSConfigurationError", "TLSFiles", "ensure_self_signed", "fingerprint", "tls_files", "tls_requested"]
