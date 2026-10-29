"""Connection ticket generation and parsing for UltimaScraper WebUI and backends."""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

TICKET_SCHEME_PREFIX = "usr://ticket/"
CLUSTER_INVITE_PREFIX = "usr://cluster/"
_LOOPBACK_HOSTS = frozenset({"localhost", "::1"})
TICKET_PREFIX = "usr_ticket_"


def create_ticket(
    *,
    name: str,
    base_url: str,
    token: str | None = None,
    tls_verify: bool = True,
    cluster_id: str | None = None,
) -> str:
    """Create a shareable base64 connection ticket.

    Format: usr://ticket/<urlsafe_base64_json>
    """
    payload: dict[str, Any] = {
        "v": 1,
        "name": name.strip(),
        "base_url": base_url.strip().rstrip("/"),
        "tls_verify": bool(tls_verify),
    }
    if token and token.strip():
        payload["token"] = token.strip()
    if cluster_id and cluster_id.strip():
        payload["cluster_id"] = cluster_id.strip()

    raw_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
    return f"{TICKET_SCHEME_PREFIX}{encoded}"


def local_only(base_url: str) -> bool:
    """Whether an address only works from this WebUI's host: loopback, or a bare
    name such as the "backend" service of a Docker Compose network."""
    host = (urlparse(base_url).hostname or "").lower()
    return host in _LOOPBACK_HOSTS or host.startswith("127.") or ("." not in host and ":" not in host)


def shareable_fields(
    *,
    name: str,
    base_url: str,
    default_connection: bool,
    backend_id: str | None,
    api_url: str | None,
) -> tuple[str, str, str | None]:
    """The name and address a ticket gives another WebUI, and a warning when that
    address will not work there.

    The default connection's name ("This server") only means something on this
    WebUI, so the backend's own id names it instead. An address that only works
    from here is replaced by the one the backend advertises (its identity's api_url).
    """
    shared_name = (backend_id or name) if default_connection else name
    if not local_only(base_url):
        return shared_name, base_url, None
    if api_url and not local_only(api_url):
        return shared_name, api_url, None
    warning = (
        f"{base_url} only works from this WebUI's host, and the backend advertises no other "
        "address. Edit the address after importing, to one the other machine can reach."
    )
    return shared_name, base_url, warning


def parse_ticket(ticket_string: str) -> dict[str, Any]:
    """Parse a connection ticket string into its connection fields.

    Supported formats:
    - usr://ticket/<urlsafe_base64_json>
    - usr_ticket_<urlsafe_base64_json>
    - Raw URL-safe or standard Base64 JSON
    - Standard URI: usr://[token@]host[:port][?name=...&tls=...]

    Returns:
        dict with keys: 'name', 'base_url', 'token', 'tls_verify', and optional 'cluster_id'.

    Raises:
        ValueError if the ticket cannot be parsed or lacks required fields.
    """
    cleaned = ticket_string.strip()
    if not cleaned:
        raise ValueError("Ticket string cannot be empty.")
    if cleaned.startswith(CLUSTER_INVITE_PREFIX):
        raise ValueError("This is a cluster invite: join the cluster with it instead.")

    if cleaned.startswith(TICKET_SCHEME_PREFIX):
        payload_b64 = cleaned[len(TICKET_SCHEME_PREFIX) :]
        return _decode_json_payload(payload_b64)

    if cleaned.startswith(TICKET_PREFIX):
        payload_b64 = cleaned[len(TICKET_PREFIX) :]
        return _decode_json_payload(payload_b64)

    if cleaned.startswith("usr://"):
        return _parse_usr_uri(cleaned)

    # Fallback: attempt decoding as raw base64 JSON
    try:
        return _decode_json_payload(cleaned)
    except Exception as exc:
        raise ValueError(f"Invalid connection ticket format: {exc}") from exc


def _decode_json_payload(b64_str: str) -> dict[str, Any]:
    b64_clean = b64_str.strip().rstrip("/")
    padding = len(b64_clean) % 4
    if padding:
        b64_clean += "=" * (4 - padding)

    try:
        decoded = base64.urlsafe_b64decode(b64_clean.encode("ascii"))
    except Exception:
        decoded = base64.b64decode(b64_clean.encode("ascii"))

    try:
        data = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Ticket payload is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Ticket payload must be a JSON object.")

    base_url = data.get("base_url") or data.get("url")
    if not base_url or not isinstance(base_url, str):
        raise ValueError("Ticket is missing a valid 'base_url'.")

    name = data.get("name") or "Backend"
    token = data.get("token") or None
    tls_verify = bool(data.get("tls_verify", True))
    cluster_id = data.get("cluster_id") or None

    return {
        "name": str(name).strip(),
        "base_url": str(base_url).strip().rstrip("/"),
        "token": str(token).strip() if token else None,
        "tls_verify": tls_verify,
        "cluster_id": str(cluster_id).strip() if cluster_id else None,
    }


def _parse_usr_uri(uri: str) -> dict[str, Any]:
    parsed = urlparse(uri)
    token = parsed.username or parsed.password or None
    host = parsed.hostname or ""
    if not host:
        raise ValueError("Ticket URI is missing host.")

    port = f":{parsed.port}" if parsed.port else ""
    qs = parse_qs(parsed.query)

    name = qs.get("name", ["Backend"])[0]
    tls_str = qs.get("tls", qs.get("tls_verify", ["false"]))[0].lower()
    is_https = tls_str in ("1", "true", "yes") or parsed.port == 443
    scheme = "https" if is_https else "http"
    tls_verify = tls_str not in ("0", "false", "no")

    base_url = f"{scheme}://{host}{port}{parsed.path}".rstrip("/")
    return {
        "name": name.strip(),
        "base_url": base_url,
        "token": token.strip() if token else None,
        "tls_verify": tls_verify,
        "cluster_id": qs.get("cluster_id", [None])[0],
    }


def create_cluster_join_invite(*, code: str, entry_url: str, fingerprint: str) -> str:
    """A version 2 invite: a one-time code, the member to redeem it at, and that
    member's certificate fingerprint.

    Format: usr://cluster/<code>@<host:port>#<fingerprint>. The code works once,
    so the invite holds no lasting secret; the fingerprint means the joining
    WebUI trusts only that member's certificate.
    """
    parts = urlparse(entry_url)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("An invite names an https:// member.")
    return f"{CLUSTER_INVITE_PREFIX}{code}@{parts.netloc}#{fingerprint}"


def is_cluster_join_invite(invite: str) -> bool:
    cleaned = invite.strip()
    return cleaned.startswith(CLUSTER_INVITE_PREFIX) and "@" in cleaned


def parse_cluster_join_invite(invite: str) -> dict[str, str]:
    """The code, entry address and fingerprint of a version 2 invite."""
    cleaned = invite.strip()
    if not is_cluster_join_invite(cleaned):
        raise ValueError("Not a cluster invite (usr://cluster/<code>@<address>#<fingerprint>).")
    body, _, fingerprint = cleaned[len(CLUSTER_INVITE_PREFIX) :].partition("#")
    code, _, netloc = body.rpartition("@")
    netloc = netloc.strip().rstrip("/")
    if not code or not netloc or not fingerprint.strip():
        raise ValueError("The invite needs a code, an address and a fingerprint.")
    parts = urlparse(f"https://{netloc}")
    try:
        _ = parts.port
    except ValueError as exc:
        raise ValueError(f"The invite's address is not valid: {exc}") from exc
    if not parts.hostname:
        raise ValueError("The invite's address is not valid.")
    return {"code": code.strip(), "entry_url": f"https://{netloc}", "fingerprint": fingerprint.strip()}


def _encode(payload: dict[str, Any]) -> str:
    raw_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")


def create_cluster_invite(*, cluster_id: str, name: str, members: list[dict[str, Any]]) -> str:
    """One invite for a whole cluster: each member's name, id, address and token.

    Format: usr://cluster/<urlsafe_base64_json>. It holds admin tokens, so it
    is as secret as they are.
    """
    payload = {
        "v": 1,
        "cluster_id": cluster_id,
        "name": name.strip(),
        "members": [
            {
                "name": str(member["name"]).strip(),
                "backend_id": str(member["backend_id"]),
                "base_url": str(member["base_url"]).strip().rstrip("/"),
                "token": member.get("token") or None,
                "tls_verify": bool(member.get("tls_verify", True)),
            }
            for member in members
        ],
    }
    return f"{CLUSTER_INVITE_PREFIX}{_encode(payload)}"


def parse_cluster_invite(invite: str) -> dict[str, Any]:
    """The cluster and members an invite names; raises ValueError for anything else."""
    cleaned = invite.strip()
    if not cleaned.startswith(CLUSTER_INVITE_PREFIX):
        raise ValueError("Not a cluster invite (usr://cluster/...).")
    if is_cluster_join_invite(cleaned):
        raise ValueError("This is a version 2 invite: redeem it with parse_cluster_join_invite.")
    body = cleaned[len(CLUSTER_INVITE_PREFIX) :].strip().rstrip("/")
    body += "=" * (-len(body) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(body.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"The invite could not be read: {exc}") from exc
    if not isinstance(data, dict) or data.get("v") != 1 or not isinstance(data.get("members"), list):
        raise ValueError("The invite is not a version 1 cluster invite.")
    cluster_id = str(data.get("cluster_id") or "").strip()
    if not cluster_id:
        raise ValueError("The invite names no cluster.")
    members: list[dict[str, Any]] = []
    for entry in data["members"]:
        if not isinstance(entry, dict) or not entry.get("base_url") or not entry.get("backend_id"):
            raise ValueError("The invite has a member without an address or id.")
        members.append(
            {
                "name": str(entry.get("name") or entry["backend_id"]).strip(),
                "backend_id": str(entry["backend_id"]).strip(),
                "base_url": str(entry["base_url"]).strip().rstrip("/"),
                "token": str(entry["token"]).strip() if entry.get("token") else None,
                "tls_verify": bool(entry.get("tls_verify", True)),
            }
        )
    return {"cluster_id": cluster_id, "name": str(data.get("name") or "").strip(), "members": members}
