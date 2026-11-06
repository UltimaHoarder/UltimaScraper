"""Sign-in for the WebUI server: one password, cookie sessions.

Until a password is set, the first browser on this server's own network may
set it. A browser anywhere else, or behind a reverse proxy this server does not
trust, also needs the setup code from the log.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection
from ultima_scraper_core.claims import visitor_is_local

from .store import Store

SESSION_COOKIE = "usr_webui_session"
SESSION_LIFETIME_SECONDS = 30 * 24 * 3600
MIN_PASSWORD_LENGTH = 8
_PASSWORD_KEY = "password_hash"
_SCRYPT = {"n": 2**15, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_FORWARDING_HEADERS = ("forwarded", "x-forwarded-for", "x-real-ip")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt$" + "$".join(base64.b64encode(part).decode() for part in (salt, digest))


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    expected = base64.b64decode(digest)
    actual = hashlib.scrypt(
        password.encode("utf-8"), salt=base64.b64decode(salt), dklen=len(expected), **_SCRYPT
    )
    return hmac.compare_digest(actual, expected)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AttemptLimiter:
    """At most ``limit`` failed attempts per client address per ``window`` seconds."""

    def __init__(self, limit: int = 5, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def check(self, address: str) -> None:
        failures = self._failures[address]
        while failures and failures[0] < time.monotonic() - self.window:
            failures.popleft()
        if len(failures) >= self.limit:
            raise HTTPException(status_code=429, detail="Too many attempts. Wait a minute and try again.")

    def fail(self, address: str) -> None:
        self._failures[address].append(time.monotonic())


class Auth:
    def __init__(self, store: Store, trust_forwarded: bool = False) -> None:
        self.store = store
        # Whether a proxy in front is trusted to report the browser's address.
        self.trust_forwarded = trust_forwarded
        self.limiter = AttemptLimiter()
        # Shown in the log while no password is set, for remote first setup.
        self.setup_code = secrets.token_urlsafe(16)

    def password_set(self) -> bool:
        return self.store.get_setting(_PASSWORD_KEY) is not None

    def visitor_is_local(self, request: HTTPConnection) -> bool:
        """Whether this browser may set the first password without the setup code.

        Behind a proxy this server does not trust, every browser arrives from the
        proxy's own, usually private, address, so a forwarded request is not local.
        """
        if not self.trust_forwarded and any(name in request.headers for name in _FORWARDING_HEADERS):
            return False
        return visitor_is_local(client_address(request), None)

    def new_session(self, request: HTTPConnection | None = None) -> str:
        token = secrets.token_urlsafe(32)
        ip = client_address(request) if request else ""
        ua = request.headers.get("user-agent", "") if request else ""
        self.store.add_session(_token_hash(token), SESSION_LIFETIME_SECONDS, ip_address=ip, user_agent=ua)
        return token

    def authenticated(self, request: HTTPConnection) -> bool:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            return False
        th = _token_hash(token)
        valid = self.store.session_valid(th)
        if valid:
            ip = client_address(request)
            ua = request.headers.get("user-agent", "")
            self.store.touch_session(th, ip_address=ip, user_agent=ua)
        return valid

    def current_session_id(self, request: HTTPConnection) -> str | None:
        token = request.cookies.get(SESSION_COOKIE)
        return _token_hash(token)[:16] if token else None

    def revoke_session(self, session_id: str) -> bool:
        return self.store.delete_session_by_id(session_id)

    def end_session(self, request: Request) -> None:
        if token := request.cookies.get(SESSION_COOKIE):
            self.store.delete_session(_token_hash(token))

    def claim(self, request: Request, password: str, code: str | None) -> str:
        """Set the first password; returns a session token."""
        address = client_address(request)
        self.limiter.check(address)
        if len(password) < MIN_PASSWORD_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Use a password of at least {MIN_PASSWORD_LENGTH} characters.",
            )
        allowed = self.visitor_is_local(request) or (
            code is not None and hmac.compare_digest(code.strip(), self.setup_code)
        )
        if not allowed:
            self.limiter.fail(address)
            raise HTTPException(
                status_code=403,
                detail="Set the password from this server's network, or enter the setup code from its log.",
            )
        # Only the first claim wins, even if two arrive together.
        if not self.store.set_setting_once(_PASSWORD_KEY, hash_password(password)):
            raise HTTPException(status_code=409, detail="A password is already set. Sign in instead.")
        self.store.audit("password_set", address)
        return self.new_session(request)

    def login(self, request: Request, password: str) -> str:
        address = client_address(request)
        self.limiter.check(address)
        stored = self.store.get_setting(_PASSWORD_KEY)
        if stored is None or not verify_password(password, stored):
            self.limiter.fail(address)
            self.store.audit("login_failed", address)
            raise HTTPException(status_code=401, detail="Wrong password.")
        self.store.audit("login", address)
        return self.new_session(request)

    def confirm_password(self, request: Request, password: str, action: str) -> None:
        """Re-check the WebUI password before a destructive action, even when signed in."""
        address = client_address(request)
        self.limiter.check(address)
        stored = self.store.get_setting(_PASSWORD_KEY)
        if stored is None or not verify_password(password, stored):
            self.limiter.fail(address)
            self.store.audit(f"{action}_password_failed", address)
            # 403, not 401: the session is still valid, only this action is refused.
            raise HTTPException(status_code=403, detail="Wrong WebUI password.")

    def change_password(self, request: Request, current_password: str, new_password: str) -> str:
        address = client_address(request)
        self.limiter.check(address)
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Use a new password of at least {MIN_PASSWORD_LENGTH} characters.",
            )
        stored = self.store.get_setting(_PASSWORD_KEY)
        if stored is not None and not verify_password(current_password, stored):
            self.limiter.fail(address)
            self.store.audit("change_password_failed", address)
            raise HTTPException(status_code=401, detail="Current password is incorrect.")
        self.store.set_setting(_PASSWORD_KEY, hash_password(new_password))
        # Whoever knew the old password is signed out everywhere; the caller gets a new session.
        self.store.delete_all_sessions()
        self.store.audit("password_changed", address)
        return self.new_session(request)

    def revoke_other_sessions(self, request: Request) -> str:
        """Revokes all sessions and creates a fresh session for the caller."""
        address = client_address(request)
        self.store.delete_all_sessions()
        self.store.audit("sessions_revoked", address)
        return self.new_session(request)

    def require(self, request: Request) -> None:
        """Dependency: a signed-in session, and same-origin for writes."""
        if not self.authenticated(request):
            raise HTTPException(status_code=401, detail="Sign in to the WebUI.")
        require_same_origin(request)


def client_address(request: HTTPConnection) -> str:
    """The browser's address. This server is the edge, so the peer is the client."""
    return request.client.host if request.client else ""


def same_host(request: HTTPConnection, origin: str) -> bool:
    """Whether a browser Origin names this server.

    Hosts are compared without the scheme, because a TLS reverse proxy in front
    makes the browser's origin https:// while this server sees http://.
    """
    hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")}
    return urlsplit(origin).netloc in hosts - {None}


def require_same_origin(request: Request) -> None:
    """Refuse cross-site writes made with the browser's session cookie.

    The cookie is SameSite=Strict as well; this also covers browsers that
    ignore SameSite and requests whose Origin was rewritten by a proxy.
    """
    if request.method in _SAFE_METHODS:
        return
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="Cross-site request refused.")
    origin = request.headers.get("origin")
    if origin is not None and not same_host(request, origin):
        raise HTTPException(status_code=403, detail="Cross-site request refused.")
