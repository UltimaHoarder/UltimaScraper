"""Run the WebUI server: ``ultimascraper-webui`` or ``python -m ultima_webui_server``."""

from __future__ import annotations

import logging
import re

import uvicorn

from .app import create_app
from .config import Settings
from .tls import fingerprint, tls_files


# Browsers on the legacy routes may still put an admin token in the query string.
_TOKEN_QUERY = re.compile(r"((?:^|[?&])(?:admin_token|token|x_usr_admin_token)=)[^&\s\"]+")


class RedactTokens(logging.Filter):
    """Keeps tokens in request URLs out of the access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(
                _TOKEN_QUERY.sub(r"\1[REDACTED]", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        record.msg = _TOKEN_QUERY.sub(r"\1[REDACTED]", str(record.msg))
        return True


def server_options(settings: Settings) -> dict:
    """uvicorn options: address, forwarded headers, and HTTPS when configured."""
    options: dict = {
        "host": settings.host,
        "port": settings.port,
        # The connecting peer is the browser, so a forwarded header is believed
        # only from a proxy named in USR_WEBUI_TRUSTED_PROXIES (the dev server).
        "proxy_headers": settings.trusted_proxies is not None,
        "forwarded_allow_ips": settings.trusted_proxies,
    }
    tls = tls_files(settings.data_dir)
    if tls is not None:
        options.update(ssl_certfile=str(tls.cert_file), ssl_keyfile=str(tls.key_file))
        if tls.self_signed:
            logging.getLogger("ultima_webui_server").warning(
                "Serving HTTPS with a self-signed certificate (%s). Browsers ask you to trust it "
                "once; check its SHA-256 fingerprint first: %s",
                tls.cert_file,
                fingerprint(tls.cert_file),
            )
    return options


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    config = uvicorn.Config(create_app(settings), **server_options(settings))
    # Config sets up uvicorn's loggers, so the filter is added after it.
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(RedactTokens())
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
