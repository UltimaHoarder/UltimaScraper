"""Trusting a backend's self-signed certificate by its fingerprint.

A backend in a cluster serves HTTPS with a self-signed certificate and reports
its SHA-256 fingerprint. The fingerprint comes from somewhere already trusted:
the invite, or a member reached over a pinned connection. The certificate is
then fetched once, checked against it, and kept; from then on that exact
certificate is the only one a connection to the backend accepts, during the
TLS handshake, before anything (a token) is sent.
"""

from __future__ import annotations

import asyncio
import functools
import ssl
from urllib.parse import urlsplit

from ultima_scraper_core.tls import fingerprint_der

_FETCH_TIMEOUT = 10.0


class PinMismatch(ValueError):
    """The backend presented a certificate other than the one expected."""


def normalise_fingerprint(value: str) -> str:
    cleaned = value.strip().replace(":", "").replace(" ", "").upper()
    return ":".join(cleaned[index : index + 2] for index in range(0, len(cleaned), 2))


def certificate_fingerprint(certificate_pem: str) -> str:
    return fingerprint_der(ssl.PEM_cert_to_DER_cert(certificate_pem))


async def fetch_certificate(base_url: str) -> tuple[str, str]:
    """The certificate an HTTPS address presents (PEM) and its fingerprint, unverified."""
    parts = urlsplit(base_url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"{base_url} is not an https:// address.")
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(parts.hostname, parts.port or 443, ssl=context, server_hostname=parts.hostname),
        timeout=_FETCH_TIMEOUT,
    )
    try:
        ssl_object = writer.get_extra_info("ssl_object")
        der = ssl_object.getpeercert(binary_form=True) if ssl_object else None
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, ssl.SSLError):
            pass
    if not der:
        raise ValueError(f"{base_url} presented no certificate.")
    return ssl.DER_cert_to_PEM_cert(der), fingerprint_der(der)


async def pinned_certificate(base_url: str, expected_fingerprint: str) -> str:
    """The backend's certificate, when it is the one expected; raises PinMismatch otherwise."""
    pem, found = await fetch_certificate(base_url)
    if found != normalise_fingerprint(expected_fingerprint):
        raise PinMismatch(
            f"{base_url} presented a certificate with fingerprint {found}, not the expected "
            f"{normalise_fingerprint(expected_fingerprint)}."
        )
    return pem


@functools.lru_cache(maxsize=64)
def pinned_context(certificate_pem: str) -> ssl.SSLContext:
    """An SSL context that accepts that one certificate and nothing else.

    The self-signed certificate is the only trust anchor; partial-chain lets a
    leaf certificate be one. Its names are not checked: a backend is reached by
    address, and the pin is what identifies it.
    """
    context = ssl.create_default_context(cadata=certificate_pem)
    context.check_hostname = False
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return context
