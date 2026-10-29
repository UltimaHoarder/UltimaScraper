"""Container healthcheck: ``python -m ultima_webui_server.healthcheck``.

Asks this server's /health over HTTP or HTTPS, as it is configured. A
self-signed certificate is not verified: only the server's own answer counts.
"""

from __future__ import annotations

import os
import ssl
import sys
import urllib.request

from .tls import tls_requested


def main() -> int:
    port = int(os.environ.get("USR_WEBUI_PORT") or 21120)
    if tls_requested():
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        url = f"https://127.0.0.1:{port}/health"
    else:
        context, url = None, f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=4, context=context) as response:
            return 0 if response.status == 200 else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
