"""Streams HTTP and WebSocket traffic between the browser and a backend."""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from .connections import Connection

# Meaningful only for one hop, so never forwarded.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)
# Set by this proxy instead of trusting the browser's values.
_REPLACED = frozenset({"host", "cookie", "x-forwarded-host", "x-forwarded-proto"})
_TOKEN_HEADERS = frozenset({"x-usr-admin-token", "authorization"})
_TOKEN_QUERY = frozenset({"token", "admin_token", "x_usr_admin_token"})
# Backends must not set cookies on this origin, which every backend shares.
_RESPONSE_DROPPED = _HOP_BY_HOP | {"set-cookie", "x-content-type-options"}
# Backend responses share this origin with every connection's session. Opened
# as a page, they run in an opaque origin instead, so a backend cannot serve
# a document that acts as the WebUI. Fetches, media and downloads are unaffected.
_RESPONSE_ADDED = [
    (b"content-security-policy", b"sandbox allow-scripts allow-downloads allow-popups"),
    (b"x-content-type-options", b"nosniff"),
]


def _query(request_query: str, inject_token: bool) -> str:
    if not inject_token:
        return request_query
    pairs = [(key, value) for key, value in parse_qsl(request_query, keep_blank_values=True) if key not in _TOKEN_QUERY]
    return urlencode(pairs)


def _forwarded_for(existing: str | None, client: str) -> str:
    # The backend trusts only the last hop, which is the address this server saw.
    return f"{existing}, {client}" if existing else client


class BackendUnreachable(Exception):
    """The backend did not answer; callers decide whether another can."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name

    def response(self) -> JSONResponse:
        return JSONResponse({"detail": f"The backend {self.name} is unreachable."}, status_code=502)


class BackendProxy:
    def __init__(self) -> None:
        # Pooled connections belong to the event loop that opened them.
        self._clients: dict[tuple[str, bool | str, int], httpx.AsyncClient] = {}

    def _client(self, connection: Connection) -> httpx.AsyncClient:
        # A pinned certificate is part of how the backend is reached.
        trust = connection.tls_certificate or connection.tls_verify
        key = (connection.base_url, trust, id(asyncio.get_running_loop()))
        if key not in self._clients:
            self._clients[key] = httpx.AsyncClient(
                verify=connection.verify,
                # No read timeout: event streams and long downloads stay open.
                timeout=httpx.Timeout(connect=10.0, read=None, write=60.0, pool=30.0),
                follow_redirects=False,
            )
        return self._clients[key]

    async def aclose(self) -> None:
        loop = id(asyncio.get_running_loop())
        for key in [key for key in self._clients if key[2] == loop]:
            await self._clients.pop(key).aclose()

    async def forward(
        self, request: Request, connection: Connection, path: str, *, inject_token: bool
    ) -> Response:
        client_host = request.client.host if request.client else ""
        headers: list[tuple[str, str]] = []
        for name, value in request.headers.items():
            if name in _HOP_BY_HOP or name in _REPLACED or name == "x-forwarded-for":
                continue
            if inject_token and name in _TOKEN_HEADERS:
                continue
            headers.append((name, value))
        headers += [
            ("x-forwarded-for", _forwarded_for(request.headers.get("x-forwarded-for"), client_host)),
            ("x-forwarded-host", request.headers.get("host", "")),
            ("x-forwarded-proto", request.headers.get("x-forwarded-proto", request.url.scheme)),
        ]
        if inject_token and (token := connection.token()):
            headers.append(("x-usr-admin-token", token))

        has_body = "content-length" in request.headers or "transfer-encoding" in request.headers
        upstream_request = self._client(connection).build_request(
            request.method,
            f"{connection.base_url}/{path}",
            params=_query(request.url.query, inject_token),
            headers=headers,
            content=request.stream() if has_body else None,
        )
        try:
            upstream = await self._client(connection).send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            raise BackendUnreachable(connection.name) from exc
        response = StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            background=BackgroundTask(upstream.aclose),
        )
        # Raw pairs keep repeated headers; the body stays encoded, so its
        # content-encoding and content-length still apply.
        response.raw_headers = [
            (name.lower(), value)
            for name, value in upstream.headers.raw
            if name.lower().decode("latin-1") not in _RESPONSE_DROPPED
        ] + _RESPONSE_ADDED
        return response

    async def bridge_websocket(
        self, websocket: WebSocket, connection: Connection, path: str, *, inject_token: bool
    ) -> None:
        base = connection.base_url
        scheme, rest = base.split("://", 1)
        target = f"{'wss' if scheme == 'https' else 'ws'}://{rest}/{path}"
        if query := _query(websocket.url.query, inject_token):
            target += f"?{query}"
        client_host = websocket.client.host if websocket.client else ""
        headers = {"x-forwarded-for": _forwarded_for(websocket.headers.get("x-forwarded-for"), client_host)}
        if inject_token and (token := connection.token()):
            headers["x-usr-admin-token"] = token
        tls: ssl.SSLContext | None = None
        if scheme == "https" and connection.tls_certificate:
            tls = connection.verify  # type: ignore[assignment]
        elif scheme == "https" and not connection.tls_verify:
            tls = ssl._create_unverified_context()

        try:
            upstream = await connect(
                target,
                additional_headers=headers,
                ssl=tls,
                max_size=None,
                open_timeout=10,
            )
        except Exception:
            await websocket.close(code=1011, reason="The backend is unreachable.")
            return

        await websocket.accept()
        to_backend = asyncio.create_task(_browser_to_backend(websocket, upstream))
        to_browser = asyncio.create_task(_backend_to_browser(websocket, upstream))
        done, pending = await asyncio.wait({to_backend, to_browser}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await upstream.close()
        with contextlib.suppress(Exception):
            await websocket.close(code=upstream.close_code or 1000)


async def _browser_to_backend(websocket: WebSocket, upstream: ClientConnection) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        if (text := message.get("text")) is not None:
            await upstream.send(text)
        elif (data := message.get("bytes")) is not None:
            await upstream.send(data)


async def _backend_to_browser(websocket: WebSocket, upstream: ClientConnection) -> None:
    with contextlib.suppress(ConnectionClosed):
        async for message in upstream:
            if isinstance(message, str):
                await websocket.send_text(message)
            else:
                await websocket.send_bytes(message)
