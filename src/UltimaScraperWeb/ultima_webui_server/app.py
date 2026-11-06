"""The WebUI server application."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.types import Scope
from ultima_scraper_core.claims import visitor_is_local

from .auth import SESSION_COOKIE, SESSION_LIFETIME_SECONDS, Auth, client_address, require_same_origin, same_host
from .config import Settings
from .cluster_membership import ClusterClientOut, ClusterJoinOut, ClusterMembership
from .clusters import (
    ClusterOverview,
    ClusterOverviews,
    ClustersOut,
    Identity,
    cluster_connections,
    cluster_name,
    cluster_peers,
    describe_clusters,
    known_identity,
    rename_cluster,
)
from .connections import (
    DEFAULT_CONNECTION_ID,
    ClusterInviteOut,
    ClusterNameIn,
    InviteExcludedOut,
    InviteMemberOut,
    InvitePreviewMemberOut,
    InvitePreviewOut,
    ConnectionIn,
    ConnectionOut,
    Connections,
    ConnectionTest,
    PluginTrustIn,
    TicketIn,
    TicketOut,
    TicketParseOut,
)
from .tickets import (
    create_cluster_invite,
    create_ticket,
    is_cluster_join_invite,
    parse_cluster_invite,
    parse_ticket,
    shareable_fields,
)
from .installer.routes import DeploymentOut, InstallStarted, deployment_router, install_router
from .fleet_hosts import ClusterHostsOut, build_hosts, rename_host
from .hosts import HostGuard, HostPolicy
from .installer.runner import (
    CredentialsIn,
    ImageSource,
    Installer,
    OperationIn,
    _local_lan_ip,
    in_container,
    register_worker_inventory,
)
from .local_services import LocalServices, LocalServicesIn, LocalServicesOut
from .local_services import available as local_services_available
from .proxy import BackendProxy, BackendUnreachable
from .self_update import SelfUpdater, self_update_router
from .store import DeploymentRecord, Store
from .tunnels import TunnelManager, TunnelUnavailable
from .vault import Vault, load_or_create_key

logger = logging.getLogger("ultima_webui_server")

_MAIN_CLUSTER_KEY = "main_cluster"
_PROXY_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
# Paths the SPA fallback must never answer, so a missing route stays a 404.
# App pages under /b/{connection}/ are the SPA; that backend's own api/ and ws/
# routes are matched by the proxy routes first.
_RESERVED_PREFIXES = ("api/", "ws/", "webui/")
_RESERVED_CONNECTION_PATH = re.compile(r"b/[^/]+/(api|ws)(/|$)")


class SessionStatus(BaseModel):
    authenticated: bool
    password_set: bool
    # No password yet, and this browser may set it without the setup code.
    can_claim: bool
    # Where the app opens: a member of the main cluster, when one is chosen.
    default_connection: str | None
    # The main cluster's connections; a browser's last one outside them is not reopened.
    main_connections: list[str] = []


class MainClusterIn(BaseModel):
    # None: no main cluster; the app opens where it was last used.
    cluster_id: str | None = Field(default=None, max_length=200)


class HostNameIn(BaseModel):
    key: str = Field(min_length=1, max_length=300)
    # Empty: back to the name it is found by.
    name: str = Field(default="", max_length=80)


class ClaimRequest(BaseModel):
    password: str = Field(max_length=500)
    code: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    password: str = Field(max_length=500)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(default="", max_length=500)
    new_password: str = Field(min_length=1, max_length=500)


class ClusterUpgradeIn(BaseModel):
    version: str = Field(min_length=1, max_length=128)
    image_source: ImageSource | None = None
    image_prefix: str = Field(default="", max_length=300)
    # SSH credentials per deployment id; asked for every time, never stored.
    credentials: dict[str, CredentialsIn] = {}
    # Which of the cluster's deployments; all of them when omitted.
    deployment_ids: list[str] | None = None


class ClientSessionOut(BaseModel):
    id: str
    ip_address: str
    user_agent: str
    device_info: str
    is_local: bool
    created_at: float
    last_seen: float
    is_current: bool


def parse_device_info(ua: str) -> str:
    if not ua:
        return "Web Client"
    platform = ""
    if "iPhone" in ua or "iPad" in ua:
        platform = "iOS"
    elif "Android" in ua:
        platform = "Android"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        platform = "macOS"
    elif "Windows" in ua:
        platform = "Windows"
    elif "Ubuntu" in ua:
        platform = "Ubuntu"
    elif "Linux" in ua:
        platform = "Linux"
    elif "CrOS" in ua:
        platform = "ChromeOS"

    browser = ""
    if "Edg/" in ua or "Edge/" in ua:
        browser = "Edge"
    elif "OPR/" in ua or "Opera/" in ua:
        browser = "Opera"
    elif "Chrome/" in ua and "Chromium/" not in ua:
        if "Mobile" in ua and platform in ("Android", "iOS"):
            browser = "Chrome Mobile"
        else:
            browser = "Chrome"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Safari/" in ua and "Chrome/" not in ua:
        if "Mobile" in ua or platform in ("iOS", "Android"):
            browser = "Mobile Safari"
        else:
            browser = "Safari"
    elif ua.startswith("curl/"):
        return ua.split()[0]
    elif "python" in ua.lower():
        return "Python Client"
    elif "testclient" in ua.lower():
        return "Test Client"

    if browser and platform:
        return f"{browser} on {platform}"
    if browser:
        return browser
    if platform:
        return f"Browser on {platform}"
    return ua.split("/")[0] if "/" in ua else (ua[:30] + "…" if len(ua) > 30 else ua)


class ImmutableStaticFiles(StaticFiles):
    """Vite fingerprints asset names, so they can be cached for good."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_LIFETIME_SECONDS),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
        path="/",
    )


# Reads of data a cluster's shared database holds; any member can answer them.
# Settings (stored per backend id), media files, system and plugin routes
# belong to one backend and are never served by another.
_SHARED_READS = re.compile(
    r"v1/(jobs|tasks|users|chats|orders|favourites|statistics|subscriptions|account-purchases|search-loadouts)(/|$)"
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = Store(settings.data_dir / "webui.db")
    vault = Vault(load_or_create_key(settings.data_dir))
    auth = Auth(store, trust_forwarded=settings.trusted_proxies is not None)
    connections = Connections(settings, store, vault)
    proxy = BackendProxy()
    tunnels = TunnelManager()
    installer = Installer(store, connections, tunnels, local_allowed=not in_container())
    local_services = LocalServices(
        store,
        vault,
        connections,
        tunnels,
        read_stores=lambda connection_id: installer.get_cluster_stores(connection_id=connection_id),
        cluster_connections=lambda cluster_id: [
            connection for connection, _ in cluster_connections(connections, store, cluster_id)
        ],
        register_worker=register_worker_inventory,
    )
    self_updater = SelfUpdater()

    def ensure_main_cluster() -> str | None:
        """The main cluster; the first one this WebUI is in becomes it when none is.

        "First": the cluster of the deployment's own backend, else of the
        oldest connection. A main cluster this WebUI is no longer in is replaced.
        """
        current = store.get_setting(_MAIN_CLUSTER_KEY)
        if current and cluster_connections(connections, store, current):
            return current
        known = store.identities()
        # The default connection first, then the others oldest first.
        for connection in connections.all():
            raw = known.get(connection.id)
            if raw is None:
                continue
            try:
                cluster_id = Identity.model_validate(json.loads(raw[0])).cluster_id
            except ValueError:
                continue
            if cluster_id:
                store.set_setting(_MAIN_CLUSTER_KEY, cluster_id)
                store.audit("main_cluster_set", f"{cluster_id} (first cluster)")
                return cluster_id
        return None

    async def reachable(connection_id: str):
        """The connection, through its SSH tunnel when it has one."""
        try:
            return await tunnels.resolve(connections.get(connection_id))
        except TunnelUnavailable as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not auth.password_set():
            rule = "=" * 72
            logger.warning(
                "\n%s\nUltimaScraper WebUI: no password is set yet.\n"
                "Open http://%s:%s from a browser on this server's network to set one.\n"
                "From anywhere else, you will also need this setup code: %s\n%s",
                rule,
                "localhost" if settings.host in {"0.0.0.0", "::"} else settings.host,
                settings.port,
                auth.setup_code,
                rule,
            )
        sync_task = asyncio.create_task(membership.run())
        await local_services.resume()
        yield
        sync_task.cancel()
        await local_services.stop_all()
        await proxy.aclose()
        await tunnels.close()
        store.close()

    app = FastAPI(title="UltimaScraper WebUI", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.auth = auth
    app.state.connections = connections
    app.state.installer = installer
    app.state.local_services = local_services
    app.state.self_updater = self_updater

    @app.get("/health", response_class=PlainTextResponse, include_in_schema=False)
    def health() -> str:
        return "healthy\n"

    # ---- Sign-in -------------------------------------------------------

    @app.get("/webui/api/v1/session", response_model=SessionStatus)
    def session(request: Request) -> SessionStatus:
        password_set = auth.password_set()
        authenticated = auth.authenticated(request)
        default_connection = DEFAULT_CONNECTION_ID if settings.default_backend_url else None
        main: list[str] = []
        main_cluster = ensure_main_cluster() if authenticated else None
        if main_cluster:
            main = [connection.id for connection, _ in cluster_connections(connections, store, main_cluster)]
            if main and default_connection not in main:
                default_connection = main[0]
        return SessionStatus(
            authenticated=authenticated,
            password_set=password_set,
            can_claim=not password_set and auth.visitor_is_local(request),
            default_connection=default_connection,
            main_connections=main,
        )

    @app.post("/webui/api/v1/session/claim", status_code=204)
    def claim(body: ClaimRequest, request: Request, response: Response) -> None:
        require_same_origin(request)
        _set_session_cookie(request, response, auth.claim(request, body.password, body.code))

    @app.post("/webui/api/v1/session/login", status_code=204)
    def login(body: LoginRequest, request: Request, response: Response) -> None:
        require_same_origin(request)
        _set_session_cookie(request, response, auth.login(request, body.password))

    @app.post("/webui/api/v1/session/logout", status_code=204)
    def logout(request: Request, response: Response) -> None:
        require_same_origin(request)
        auth.end_session(request)
        response.delete_cookie(SESSION_COOKIE, path="/")

    # ---- Backend connections & session management ---------------------

    signed_in = [Depends(auth.require)]

    @app.post("/webui/api/v1/session/password", status_code=204, dependencies=signed_in)
    def change_password(body: ChangePasswordRequest, request: Request, response: Response) -> None:
        require_same_origin(request)
        _set_session_cookie(request, response, auth.change_password(request, body.current_password, body.new_password))

    @app.post("/webui/api/v1/session/revoke-all", status_code=204, dependencies=signed_in)
    def revoke_all_sessions(request: Request, response: Response) -> None:
        require_same_origin(request)
        _set_session_cookie(request, response, auth.revoke_other_sessions(request))

    @app.get("/webui/api/v1/clients", response_model=list[ClientSessionOut], dependencies=signed_in)
    def list_clients(request: Request) -> list[ClientSessionOut]:
        current_id = auth.current_session_id(request)
        sessions = store.list_sessions()
        return [
            ClientSessionOut(
                id=s.id,
                ip_address=s.ip_address,
                user_agent=s.user_agent,
                device_info=parse_device_info(s.user_agent),
                is_local=visitor_is_local(s.ip_address, None) if s.ip_address else True,
                created_at=s.created_at,
                last_seen=s.last_seen,
                is_current=(s.id == current_id),
            )
            for s in sessions
        ]

    @app.delete("/webui/api/v1/clients/{session_id}", status_code=204, dependencies=signed_in)
    def revoke_client(session_id: str, request: Request, response: Response) -> None:
        require_same_origin(request)
        current_id = auth.current_session_id(request)
        if session_id == current_id:
            auth.end_session(request)
            response.delete_cookie(SESSION_COOKIE, path="/")
        else:
            auth.revoke_session(session_id)

    @app.get("/webui/api/v1/connections", response_model=list[ConnectionOut], dependencies=signed_in)
    def list_connections() -> list[ConnectionOut]:
        return [connections.describe(connection) for connection in connections.all()]

    @app.post("/webui/api/v1/connections", response_model=ConnectionOut, status_code=201, dependencies=signed_in)
    def add_connection(body: ConnectionIn) -> ConnectionOut:
        return connections.describe(connections.create(body))

    @app.put("/webui/api/v1/connections/{connection_id}", response_model=ConnectionOut, dependencies=signed_in)
    def update_connection(connection_id: str, body: ConnectionIn) -> ConnectionOut:
        return connections.describe(connections.update(connection_id, body))

    @app.delete("/webui/api/v1/connections/{connection_id}", status_code=204, dependencies=signed_in)
    async def remove_connection(connection_id: str) -> None:
        connections.delete(connection_id)
        await tunnels.close(connection_id)

    @app.put(
        "/webui/api/v1/connections/{connection_id}/plugin-trust", response_model=ConnectionOut, dependencies=signed_in
    )
    def set_plugin_trust(connection_id: str, body: PluginTrustIn) -> ConnectionOut:
        return connections.describe(connections.set_plugin_trust(connection_id, body.trusted))

    @app.post("/webui/api/v1/connections/{connection_id}/test", response_model=ConnectionTest, dependencies=signed_in)
    async def test_connection(connection_id: str) -> ConnectionTest:
        return await connections.test(await reachable(connection_id))

    @app.get("/webui/api/v1/connections/{connection_id}/ticket", response_model=TicketOut, dependencies=signed_in)
    async def get_connection_ticket(connection_id: str) -> TicketOut:
        connection = connections.get(connection_id)
        identity = await known_identity(store, reachable, connection)
        name, base_url, warning = shareable_fields(
            name=connection.name,
            base_url=connection.base_url,
            default_connection=connection.id == DEFAULT_CONNECTION_ID,
            backend_id=identity.backend_id if identity else None,
            api_url=identity.api_url if identity else None,
        )
        ticket = create_ticket(
            name=name,
            base_url=base_url,
            token=connection.token(),
            tls_verify=connection.tls_verify,
            cluster_id=identity.cluster_id if identity else None,
        )
        return TicketOut(ticket=ticket, name=name, base_url=base_url, warning=warning)

    @app.post("/webui/api/v1/connections/parse-ticket", response_model=TicketParseOut, dependencies=signed_in)
    def parse_connection_ticket(body: TicketIn) -> TicketParseOut:
        try:
            parsed = parse_ticket(body.ticket)
            return TicketParseOut(**parsed)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/webui/api/v1/clusters", response_model=ClustersOut, dependencies=signed_in)
    async def list_clusters() -> ClustersOut:
        described = await describe_clusters(connections, store, reachable)
        described.main_cluster_id = ensure_main_cluster()
        return described

    @app.put("/webui/api/v1/clusters/main", response_model=MainClusterIn, dependencies=signed_in)
    def set_main_cluster(body: MainClusterIn) -> MainClusterIn:
        if body.cluster_id is None:
            store.delete_setting(_MAIN_CLUSTER_KEY)
        else:
            if not cluster_connections(connections, store, body.cluster_id):
                raise HTTPException(status_code=404, detail="This WebUI has no connection in that cluster.")
            store.set_setting(_MAIN_CLUSTER_KEY, body.cluster_id)
        store.audit("main_cluster_set", body.cluster_id or "none")
        return body

    overviews = ClusterOverviews(connections, store, reachable)
    membership = ClusterMembership(connections, store, reachable, overviews)
    app.state.membership = membership

    @app.get("/webui/api/v1/clusters/{cluster_id}/overview", response_model=ClusterOverview, dependencies=signed_in)
    async def cluster_overview(cluster_id: str) -> ClusterOverview:
        return await overviews.get(cluster_id)

    @app.put("/webui/api/v1/clusters/{cluster_id}/name", response_model=ClusterNameIn, dependencies=signed_in)
    async def set_cluster_name(cluster_id: str, body: ClusterNameIn) -> ClusterNameIn:
        if not cluster_connections(connections, store, cluster_id):
            raise HTTPException(status_code=404, detail="This WebUI has no connection in that cluster.")
        name = rename_cluster(store, cluster_id, body.name)
        await membership.push_name(cluster_id, name)
        return ClusterNameIn(name=name)

    @app.get(
        "/webui/api/v1/clusters/{cluster_id}/clients", response_model=list[ClusterClientOut], dependencies=signed_in
    )
    async def cluster_clients(cluster_id: str) -> list[ClusterClientOut]:
        return await membership.clients(cluster_id)

    @app.delete("/webui/api/v1/clusters/{cluster_id}/clients/{client_id}", status_code=204, dependencies=signed_in)
    async def revoke_cluster_client(cluster_id: str, client_id: str) -> None:
        await membership.revoke(cluster_id, client_id)

    def cluster_deployments(cluster_id: str) -> list[DeploymentRecord]:
        """The deployments this WebUI manages in the cluster: API servers first,
        since they bring the shared database up to date."""
        members = {connection.id for connection, _ in cluster_connections(connections, store, cluster_id)}
        found = [
            record
            for record in store.list_deployments()
            if record.state == "active"
            and (record.connection_id in members or record.details.get("join_connection_id") in members)
        ]
        return sorted(found, key=lambda record: (not record.details.get("components", {}).get("backend"), record.name))

    @app.get("/webui/api/v1/clusters/{cluster_id}/hosts", response_model=ClusterHostsOut, dependencies=signed_in)
    async def cluster_hosts(cluster_id: str) -> ClusterHostsOut:
        members = cluster_connections(connections, store, cluster_id)
        if not members:
            raise HTTPException(status_code=404, detail="This WebUI has no connection in that cluster.")
        backends_path, database_path, settings_path = (
            "/api/v1/system/backends",
            "/api/v1/system/database",
            "/api/v1/settings/",
        )
        answered_by, read = await membership.read_from_one(
            cluster_id, [backends_path, database_path, settings_path]
        )
        listed = read.get(backends_path) or None
        try:
            clients = [client.model_dump() for client in await membership.clients(cluster_id)]
        except HTTPException:
            clients = []
        redis = ((read.get(settings_path) or {}).get("redis") or {}) if answered_by else {}
        redis_address = (
            f"{redis['host']}:{redis.get('port') or 6379}" if redis.get("host") and redis.get("enabled", True) else None
        )
        return build_hosts(
            store=store,
            cluster_id=cluster_id,
            cluster_name=cluster_name(store, cluster_id),
            backends=list(listed.get("backends") or []) if listed else None,
            reporter_backend_id=listed.get("local_backend_id") if listed else None,
            clients=clients,
            databases=list((read.get(database_path) or {}).get("databases") or []),
            redis_address=redis_address,
            connections_by_backend={identity.backend_id: connection.id for connection, identity in members},
            deployments=cluster_deployments(cluster_id),
            this_machine=_local_lan_ip(),
            answered_by=answered_by,
            local=local_services.local_host(),
            local_services_available=local_services_available(),
        )

    # ---- The backend and workers in this WebUI's own container ----------

    @app.get("/webui/api/v1/local-services", response_model=LocalServicesOut, dependencies=signed_in)
    def get_local_services() -> LocalServicesOut:
        return local_services.describe()

    @app.put("/webui/api/v1/local-services", response_model=LocalServicesOut, dependencies=signed_in)
    async def set_local_services(body: LocalServicesIn) -> LocalServicesOut:
        if not cluster_connections(connections, store, body.cluster_id):
            raise HTTPException(status_code=404, detail="This WebUI has no connection in that cluster.")
        return await local_services.configure(body)

    @app.put("/webui/api/v1/hosts/name", response_model=HostNameIn, dependencies=signed_in)
    def set_host_name(body: HostNameIn) -> HostNameIn:
        return HostNameIn(key=body.key, name=rename_host(store, body.key, body.name))

    @app.get(
        "/webui/api/v1/clusters/{cluster_id}/deployments", response_model=list[DeploymentOut], dependencies=signed_in
    )
    def list_cluster_deployments(cluster_id: str) -> list[DeploymentOut]:
        return [
            DeploymentOut(
                id=record.id,
                name=record.name,
                target=record.target,
                details=record.details,
                connection_id=record.connection_id,
            )
            for record in cluster_deployments(cluster_id)
        ]

    @app.post(
        "/webui/api/v1/clusters/{cluster_id}/upgrade",
        response_model=InstallStarted,
        status_code=202,
        dependencies=signed_in,
    )
    async def upgrade_cluster(cluster_id: str, body: ClusterUpgradeIn) -> InstallStarted:
        records = cluster_deployments(cluster_id)
        if body.deployment_ids is not None:
            chosen = set(body.deployment_ids)
            records = [record for record in records if record.id in chosen]
        try:
            requests = [
                (
                    record.id,
                    OperationIn(
                        action="upgrade",
                        version=body.version,
                        image_source=body.image_source,
                        image_prefix=body.image_prefix,
                        credentials=body.credentials.get(record.id, CredentialsIn()),
                    ),
                )
                for record in records
            ]
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.errors()[0]["msg"]) from exc
        run_id = installer.start_upgrades(cluster_name(store, cluster_id), requests)
        store.audit("cluster_upgrade_started", f"{cluster_id} {len(requests)} to {body.version}")
        return InstallStarted(id=run_id)

    @app.get("/webui/api/v1/clusters/{cluster_id}/invite", response_model=ClusterInviteOut, dependencies=signed_in)
    async def cluster_invite(cluster_id: str) -> ClusterInviteOut:
        members = cluster_connections(connections, store, cluster_id)
        if not members:
            raise HTTPException(status_code=404, detail="This WebUI has no connection in that cluster.")
        label = cluster_name(store, cluster_id)
        try:
            created = await membership.create_invite(cluster_id)
        except HTTPException as exc:
            logger.info("No one-time invite for cluster %s: %s", cluster_id, exc.detail)
            created = None
        if created is not None:
            store.audit("cluster_invite_created", cluster_id)
            return ClusterInviteOut(
                invite=created.invite,
                name=label,
                members=[
                    InviteMemberOut(name=member.name, base_url=member.api_url)
                    for member in created.members
                    if member.api_url
                ],
                excluded=[
                    InviteExcludedOut(name=member.name, reason="It serves no HTTPS address for other machines.")
                    for member in created.members
                    if not member.api_url
                ],
                version=2,
                expires_at=created.expires_at,
            )
        shared: list[dict] = []
        excluded: list[InviteExcludedOut] = []
        for connection, identity in members:
            name, base_url, warning = shareable_fields(
                name=connection.name,
                base_url=connection.base_url,
                default_connection=connection.id == DEFAULT_CONNECTION_ID,
                backend_id=identity.backend_id,
                api_url=identity.api_url,
            )
            token = connection.token()
            if warning:
                excluded.append(InviteExcludedOut(name=name, reason=warning))
            elif not token:
                excluded.append(InviteExcludedOut(name=name, reason="This WebUI has no admin token for it."))
            else:
                shared.append(
                    {
                        "name": name,
                        "backend_id": identity.backend_id,
                        "base_url": base_url,
                        "token": token,
                        "tls_verify": connection.tls_verify,
                    }
                )
        if not shared:
            reasons = "; ".join(f"{item.name}: {item.reason}" for item in excluded)
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No backend of this cluster is reachable from other machines yet ({reasons}). "
                    "Let other machines use one: in its Edit config, turn on \"Serve HTTPS for other machines\" "
                    "and restart it. Its invites are then one-time codes, over HTTPS."
                ),
            )
        store.audit("cluster_invite_copied", cluster_id)
        return ClusterInviteOut(
            invite=create_cluster_invite(cluster_id=cluster_id, name=label, members=shared),
            name=label,
            members=[InviteMemberOut(name=item["name"], base_url=item["base_url"]) for item in shared],
            excluded=excluded,
            warning=(
                "No member of this cluster serves HTTPS for other machines, so this invite carries the "
                "backends' admin tokens. Share it only over a channel you trust, or turn on "
                "\"Let other machines use this backend\" for a one-time invite instead."
            ),
        )

    def _connected_to(member: dict) -> bool:
        """Whether this WebUI already reaches that backend, by address or by its id."""
        known = store.identities()
        for connection in connections.all():
            if connection.base_url.rstrip("/") == member["base_url"]:
                return True
            raw = known.get(connection.id)
            if raw and json.loads(raw[0]).get("backend_id") == member["backend_id"]:
                return True
        return False

    def _read_invite(invite: str) -> dict:
        try:
            return parse_cluster_invite(invite)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/webui/api/v1/clusters/preview-invite", response_model=InvitePreviewOut, dependencies=signed_in)
    async def preview_invite(body: TicketIn) -> InvitePreviewOut:
        if is_cluster_join_invite(body.ticket):
            checked = await membership.preview(body.ticket)
            return InvitePreviewOut(
                cluster_id=None,
                name="A cluster",
                members=[],
                version=2,
                entry_url=checked.entry_url,
                fingerprint=checked.fingerprint,
                verified=checked.verified,
                error=checked.error,
            )
        parsed = _read_invite(body.ticket)
        return InvitePreviewOut(
            cluster_id=parsed["cluster_id"],
            name=parsed["name"] or f"Cluster {parsed['cluster_id'][:8]}",
            members=[
                InvitePreviewMemberOut(
                    name=member["name"],
                    backend_id=member["backend_id"],
                    base_url=member["base_url"],
                    already_connected=_connected_to(member),
                )
                for member in parsed["members"]
            ],
        )

    @app.post("/webui/api/v1/clusters/join", response_model=ClusterJoinOut, dependencies=signed_in)
    async def join_cluster(body: TicketIn) -> ClusterJoinOut:
        if is_cluster_join_invite(body.ticket):
            return await membership.join(body.ticket)
        parsed = _read_invite(body.ticket)
        cluster_id = parsed["cluster_id"]
        created: list[str] = []
        skipped: list[str] = []
        for member in parsed["members"]:
            if _connected_to(member):
                skipped.append(member["name"])
                continue
            connection = connections.create(
                ConnectionIn(
                    name=member["name"],
                    base_url=member["base_url"],
                    token=member["token"],
                    tls_verify=member["tls_verify"],
                )
            )
            # Known to be in the cluster before it is first asked.
            store.save_identity(
                connection.id, Identity(backend_id=member["backend_id"], cluster_id=cluster_id).model_dump_json()
            )
            created.append(connection.id)
        if parsed["name"] and store.get_setting(f"cluster_name:{cluster_id}") is None:
            rename_cluster(store, cluster_id, parsed["name"])
        overviews.forget(cluster_id)
        store.audit("cluster_joined", f"{cluster_id} {len(created)} added")
        return ClusterJoinOut(
            cluster_id=cluster_id, name=cluster_name(store, cluster_id), created=created, skipped=skipped
        )

    app.include_router(install_router(installer, auth))
    app.include_router(deployment_router(installer, auth))
    app.include_router(self_update_router(self_updater, auth))

    # ---- Proxies -------------------------------------------------------

    async def forward_to(connection_id: str, request: Request, path: str) -> Response:
        """Raises BackendUnreachable when neither the backend nor its tunnel answers."""
        try:
            connection = await reachable(connection_id)
        except HTTPException as exc:
            if exc.status_code != 502:
                raise
            raise BackendUnreachable(connections.get(connection_id).name) from exc
        return await proxy.forward(request, connection, path, inject_token=True)

    @app.api_route("/b/{connection_id}/api/{path:path}", methods=_PROXY_METHODS, include_in_schema=False)
    async def backend_api(connection_id: str, path: str, request: Request) -> Response:
        auth.require(request)
        try:
            return await forward_to(connection_id, request, f"api/{path}")
        except BackendUnreachable as unreachable:
            if request.method not in ("GET", "HEAD") or not _SHARED_READS.match(path):
                return unreachable.response()
            # Cluster members share a database: another one can answer reads
            # of what it holds. The response says which one did.
            for peer in cluster_peers(connections, store, connection_id):
                try:
                    response = await forward_to(peer, request, f"api/{path}")
                except BackendUnreachable:
                    continue
                response.raw_headers.append((b"x-usr-served-by", peer.encode()))
                return response
            return unreachable.response()

    @app.websocket("/b/{connection_id}/ws/{path:path}")
    async def backend_ws(websocket: WebSocket, connection_id: str, path: str) -> None:
        if not _websocket_signed_in(websocket):
            await websocket.close(code=4401, reason="Sign in to the WebUI.")
            return
        try:
            connection = await reachable(connection_id)
        except HTTPException as exc:
            await websocket.close(code=4404 if exc.status_code == 404 else 1011, reason=str(exc.detail))
            return
        await proxy.bridge_websocket(websocket, connection, f"ws/{path}", inject_token=True)

    # The WebUI's own routes, kept so it works as it did behind nginx. A signed-in
    # browser gets the default backend's token; otherwise the browser's own token
    # (or none, for the backend's public routes) passes through unchanged.
    @app.api_route("/api/{path:path}", methods=_PROXY_METHODS, include_in_schema=False)
    async def default_api(path: str, request: Request) -> Response:
        signed = auth.authenticated(request)
        if signed:
            require_same_origin(request)
        try:
            return await proxy.forward(request, connections.default(), f"api/{path}", inject_token=signed)
        except BackendUnreachable as unreachable:
            return unreachable.response()

    @app.websocket("/ws/{path:path}")
    async def default_ws(websocket: WebSocket, path: str) -> None:
        try:
            connection = connections.default()
        except HTTPException:
            await websocket.close(code=4404, reason="This WebUI has no default backend.")
            return
        await proxy.bridge_websocket(
            websocket, connection, f"ws/{path}", inject_token=_websocket_signed_in(websocket)
        )

    def _websocket_signed_in(websocket: WebSocket) -> bool:
        """A session cookie, on a same-origin upgrade (blocks cross-site hijacking)."""
        origin = websocket.headers.get("origin")
        return origin is not None and same_host(websocket, origin) and auth.authenticated(websocket)

    # ---- The WebUI itself ----------------------------------------------

    static_dir = settings.static_dir
    if (static_dir / "assets").is_dir():
        app.mount("/assets", ImmutableStaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith(_RESERVED_PREFIXES) or _RESERVED_CONNECTION_PATH.match(path):
            raise HTTPException(status_code=404)
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
            return FileResponse(candidate)
        return _index(static_dir)

    app.add_middleware(HostGuard, policy=HostPolicy(settings.allowed_hosts))
    return app


def _index(static_dir: Path) -> HTMLResponse:
    index = static_dir / "index.html"
    if not index.is_file():
        return HTMLResponse("<h1>UltimaScraper WebUI</h1><p>The WebUI build is missing.</p>", status_code=503)
    return HTMLResponse(index.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})
