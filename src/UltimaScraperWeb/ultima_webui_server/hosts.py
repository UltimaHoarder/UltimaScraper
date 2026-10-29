"""Which Host names this server answers to, and the headers on every response.

A DNS rebinding attack points a public name the attacker controls at this
server, so a page on that name can talk to it as its own origin. Requests are
answered only for names an attacker cannot control from outside: IP addresses,
single-label names, this machine's own names, names under TLDs that are never
publicly delegated, and the names in ``USR_WEBUI_ALLOWED_HOSTS``.
"""

from __future__ import annotations

import ipaddress
import socket

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Special-use names (RFC 6761, RFC 8375) and the common unregistered LAN TLDs.
_PRIVATE_SUFFIXES = (".localhost", ".local", ".lan", ".home.arpa", ".internal", ".test")

# The plugin sandbox is an srcdoc iframe, which inherits this policy, so scripts
# are not restricted here; framing, <base> and form targets are.
CONTENT_SECURITY_POLICY = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'"
_SECURITY_HEADERS = [
    (b"content-security-policy", CONTENT_SECURITY_POLICY.encode()),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
]


def host_name(value: str) -> str:
    """The name in a Host header, without its port and in lower case."""
    value = value.strip().lower().rstrip(".")
    if value.startswith("["):
        return value[1 : value.find("]")] if "]" in value else value
    name, colon, port = value.rpartition(":")
    return name if colon and port.isdigit() else value


def parse_allowed_hosts(value: str | None) -> tuple[str, ...]:
    """``USR_WEBUI_ALLOWED_HOSTS``: names, ``.example.com`` for a domain and its subdomains, or ``*``."""
    return tuple(part.strip().lower().rstrip(".") for part in (value or "").split(",") if part.strip())


def machine_names() -> set[str]:
    names = {socket.gethostname(), socket.getfqdn()}
    return {name.lower().rstrip(".") for name in names if name}


class HostPolicy:
    def __init__(self, allowed: tuple[str, ...] = (), local_names: set[str] | None = None) -> None:
        self.allowed = allowed
        self.local_names = machine_names() if local_names is None else local_names

    def allows(self, header: str | None) -> bool:
        if "*" in self.allowed:
            return True
        if not header:
            return False
        name = host_name(header)
        if not name:
            return False
        try:
            ipaddress.ip_address(name)
            return True
        except ValueError:
            pass
        if "." not in name or name in self.local_names or name.endswith(_PRIVATE_SUFFIXES):
            return True
        return any(
            name == entry or (entry.startswith(".") and (name.endswith(entry) or name == entry[1:]))
            for entry in self.allowed
        )


class HostGuard:
    """Refuses requests for unknown names and adds the security headers."""

    def __init__(self, app: ASGIApp, policy: HostPolicy) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        forwarded = headers.get("x-forwarded-host")
        if not self.policy.allows(headers.get("host")) or (forwarded is not None and not self.policy.allows(forwarded)):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            response = PlainTextResponse(
                "This WebUI does not answer to that host name. Add it to USR_WEBUI_ALLOWED_HOSTS.",
                status_code=400,
            )
            await response(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {name for name, _ in message.get("headers", [])}
                message["headers"] = [
                    *message.get("headers", []),
                    *(header for header in _SECURITY_HEADERS if header[0] not in existing),
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)
