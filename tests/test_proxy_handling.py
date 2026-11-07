from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, sentinel

import pytest

from ultima_scraper_backend.job_system import download_manager
from ultima_scraper_backend.usapi_initializer import (
    AssignedProxyResolutionError,
    USAPIInitializer,
    apply_assigned_proxy_to_auth_json,
    resolve_assigned_proxy_url,
    resolve_proxy_url,
)
from ultima_scraper_backend.config import Network, Proxy
from ultima_scraper_api.managers.session_manager import SessionManager


def test_apply_assigned_proxy_to_auth_json_adds_resolved_proxy(monkeypatch) -> None:
    monkeypatch.setattr(
        "ultima_scraper_backend.usapi_initializer.resolve_assigned_proxy_url",
        lambda proxy_id: f"socks5://resolved/{proxy_id}",
    )

    payload = {"id": 123, "username": "tester"}
    result = apply_assigned_proxy_to_auth_json(payload, "proxy-a")

    assert result is payload
    assert payload["proxy_url"] == "socks5://resolved/proxy-a"


def test_apply_assigned_proxy_to_auth_json_leaves_payload_unchanged_without_proxy() -> None:
    payload = {"id": 123, "username": "tester"}

    result = apply_assigned_proxy_to_auth_json(payload, None)

    assert result == {"id": 123, "username": "tester"}


def test_resolve_proxy_url_attaches_configured_credentials(monkeypatch) -> None:
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    configured = SimpleNamespace(
        settings=SimpleNamespace(
            network=SimpleNamespace(
                proxies=[
                    SimpleNamespace(
                        url="socks5://chain.local:1080",
                        username="chain user",
                        password="chain/pass",
                    )
                ]
            )
        )
    )
    monkeypatch.setattr(
        UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        lambda: configured,
    )

    resolved = resolve_proxy_url("socks5://chain.local:1080")

    assert resolved == "socks5://chain%20user:chain%2Fpass@chain.local:1080"


def test_resolve_assigned_proxy_url_rejects_disabled_configured_proxy(
    monkeypatch,
) -> None:
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    configured = SimpleNamespace(
        settings=SimpleNamespace(
            network=SimpleNamespace(
                proxies=[Proxy(url="socks5://disabled.local:1080", enabled=False)]
            )
        )
    )
    monkeypatch.setattr(
        UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        lambda: configured,
    )

    assert resolve_proxy_url("socks5://disabled.local:1080") is None
    with pytest.raises(AssignedProxyResolutionError, match="is disabled"):
        resolve_assigned_proxy_url("socks5://disabled.local:1080")


def test_session_manager_excludes_disabled_configured_proxies() -> None:
    enabled_proxy = Proxy(url="http://enabled.example:8080")
    disabled_proxy = Proxy(url="http://disabled.example:8080", enabled=False)

    session_manager = SessionManager(
        SimpleNamespace(),
        proxies=[enabled_proxy, disabled_proxy],
    )

    assert enabled_proxy.enabled is True
    assert session_manager.get_enabled_proxies() == [enabled_proxy]

    disabled_proxy.enabled = True
    assert session_manager.get_enabled_proxies() == [enabled_proxy, disabled_proxy]


def test_profile_proxy_fallback_excludes_disabled_proxies(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import users as users_module
    from ultima_scraper_backend.config import UltimaScraperCollectionConfig

    configured = SimpleNamespace(
        settings=SimpleNamespace(
            network=SimpleNamespace(
                proxies=[
                    Proxy(url="http://enabled.example:8080"),
                    Proxy(url="http://disabled.example:8080", enabled=False),
                ]
            )
        )
    )
    monkeypatch.setattr(
        UltimaScraperCollectionConfig,
        "load_or_create_default_config",
        lambda: configured,
    )

    assert users_module._configured_profile_proxy_urls() == (
        "http://enabled.example:8080",
    )


@pytest.mark.asyncio
async def test_proxy_update_persists_enabled_state(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    proxy = Proxy(url="http://proxy.example:8080")
    persist_config = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist_config)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=Network(proxies=[proxy])),
    )

    response = await proxies_module.update_proxy(
        proxy.url,
        proxies_module.ProxyUpdateRequest(enabled=False),
        config=config,
    )

    assert proxy.enabled is False
    assert response.enabled is False
    persist_config.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_proxy_assignment_rejects_disabled_configured_proxy() -> None:
    from fastapi import HTTPException

    from ultima_scraper_backend.api.routes import proxies as proxies_module

    proxy = Proxy(url="http://disabled.example:8080", enabled=False)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[proxy]))
    )

    with pytest.raises(HTTPException) as exc_info:
        await proxies_module.assign_proxy_to_auth(
            proxies_module.ProxyAssignmentRequest(auth_id=123, proxy_url=proxy.url),
            backend_manager=SimpleNamespace(),
            config=config,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Proxy is disabled"


def test_build_proxy_session_settings_uses_request_proxy_for_http() -> None:
    original_tcp_connector = download_manager.aiohttp.TCPConnector
    download_manager.aiohttp.TCPConnector = (
        lambda **kwargs: ("tcp-connector", kwargs)
    )
    try:
        connector, request_proxy = download_manager._build_proxy_session_settings(
            "http://proxy.local:8080"
        )
    finally:
        download_manager.aiohttp.TCPConnector = original_tcp_connector

    assert connector[0] == "tcp-connector"
    assert "ssl" in connector[1]
    assert connector[1]["ssl"].post_handshake_auth is True
    assert request_proxy == "http://proxy.local:8080"


def test_build_proxy_session_settings_uses_connector_for_socks(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        download_manager.ProxyConnector,
        "from_url",
        lambda proxy_url, **kwargs: sentinel.proxy_connector,
    )

    connector, request_proxy = download_manager._build_proxy_session_settings(
        "socks5://proxy.local:1080"
    )

    assert connector is sentinel.proxy_connector
    assert request_proxy is None


@pytest.mark.asyncio
async def test_create_cookie_auth_applies_assigned_proxy(monkeypatch) -> None:
    import ultima_scraper_backend.usapi_initializer as initializer_module

    account = SimpleNamespace(
        user_id=8770627,
        username="u8770627",
        cookie="cookie-value",
        x_bc="xbc-value",
        user_agent="ua-value",
        email="user@example.com",
        password="pw-value",
        proxy_id="proxy-a",
    )

    class FakeSession:
        def __init__(self, engine: object) -> None:
            self.engine = engine

        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def exec(self, _stmt):
            return SimpleNamespace(first=lambda: account)

        def expunge(self, _account: object) -> None:
            return None

    class FakeAPI:
        def __init__(self) -> None:
            self.auth_json: dict[str, object] | None = None

        async def login(
            self,
            *,
            auth_json: dict[str, object],
            ignore_auth_errors: bool = False,
        ):
            self.auth_json = auth_json
            self.ignore_auth_errors = ignore_auth_errors
            return object()

    monkeypatch.setattr(initializer_module, "Session", FakeSession)
    monkeypatch.setattr(
        initializer_module,
        "apply_assigned_proxy_to_auth_json",
        lambda auth_json, proxy_id: {
            **auth_json,
            "proxy_url": f"socks5://resolved/{proxy_id}",
        },
    )

    initializer = USAPIInitializer(engine=sentinel.engine)
    api = FakeAPI()

    authed = await initializer.create_cookie_auth(
        site="onlyfans",
        account_id=8770627,
        api_instance=api,
    )

    assert authed is not None
    assert api.auth_json is not None
    assert api.auth_json["proxy_url"] == "socks5://resolved/proxy-a"
    assert api.ignore_auth_errors is True


@pytest.mark.asyncio
async def test_onlyfans_login_can_register_auth_when_ignoring_auth_errors() -> None:
    from ultima_scraper_api.apis.onlyfans.onlyfans import OnlyFansAPI

    captured: dict[str, object] = {}

    class FakeAuthDetails:
        id: int | None = None
        username = ""
        active: bool | None = False

    class FakeAuthenticator:
        def __init__(
            self,
            api: object,
            auth_details: FakeAuthDetails,
            guest: bool,
        ) -> None:
            self.api = api
            self.auth_details = auth_details
            self.guest = guest
            self.__raw__: dict[str, object] | None = None
            captured["authenticator"] = self

        async def login(self, guest: bool = False) -> object | None:
            raise RuntimeError("invalid auth")

        def is_authed(self) -> bool:
            return bool(self.auth_details.active)

        def create_auth(self) -> object:
            captured["raw"] = self.__raw__
            return SimpleNamespace(
                id=self.auth_details.id,
                username=self.auth_details.username,
            )

        async def close(self) -> None:
            captured["closed"] = True

    class FakeAPI:
        _create_auth_ignoring_errors = OnlyFansAPI._create_auth_ignoring_errors

        def __init__(self) -> None:
            self.auths: dict[int, object] = {}
            self.authenticator = FakeAuthenticator

        def find_auth(self, identifier: int) -> object | None:
            return self.auths.get(identifier)

        def create_auth_details(self, auth_json: dict[str, object]) -> FakeAuthDetails:
            return FakeAuthDetails()

        def add_auth(self, auth: object) -> object:
            self.auths[getattr(auth, "id")] = auth
            return auth

    api = FakeAPI()

    authed = await OnlyFansAPI.login(
        api,
        auth_json={"id": 15585607, "username": "onlyfans"},
        ignore_auth_errors=True,
    )

    assert authed is api.auths[15585607]
    assert getattr(authed, "username") == "onlyfans"
    assert captured["raw"] == {
        "id": 15585607,
        "username": "onlyfans",
        "name": "onlyfans",
        "isAuth": False,
    }
    assert "closed" not in captured


@pytest.mark.asyncio
async def test_onlyfans_login_context_can_register_auth_when_ignoring_auth_errors() -> None:
    from ultima_scraper_api.apis.onlyfans.onlyfans import OnlyFansAPI

    captured: dict[str, object] = {}

    class FakeAuthDetails:
        id: int | None = None
        username = ""
        active: bool | None = False

    class FakeAuthenticator:
        def __init__(
            self,
            api: object,
            auth_details: FakeAuthDetails,
            guest: bool,
        ) -> None:
            self.api = api
            self.auth_details = auth_details
            self.guest = guest
            self.__raw__: dict[str, object] | None = None

        async def login(self, guest: bool = False) -> object | None:
            raise RuntimeError("invalid auth")

        def create_auth(self) -> object:
            captured["raw"] = self.__raw__
            return SimpleNamespace(
                id=self.auth_details.id,
                username=self.auth_details.username,
            )

    class FakeAPI:
        _create_auth_ignoring_errors = OnlyFansAPI._create_auth_ignoring_errors

        def __init__(self) -> None:
            self.auths: dict[int, object] = {}
            self.authenticator = FakeAuthenticator

        def find_auth(self, identifier: int) -> object | None:
            return self.auths.get(identifier)

        def create_auth_details(self, auth_json: dict[str, object]) -> FakeAuthDetails:
            return FakeAuthDetails()

        def add_auth(self, auth: object) -> object:
            self.auths[getattr(auth, "id")] = auth
            return auth

    api = FakeAPI()

    async with OnlyFansAPI.login_context(
        api,
        auth_json={"id": 15585607, "username": "onlyfans"},
        ignore_auth_errors=True,
    ) as authed:
        assert authed is api.auths[15585607]
        assert getattr(authed, "username") == "onlyfans"

    assert captured["raw"] == {
        "id": 15585607,
        "username": "onlyfans",
        "name": "onlyfans",
        "isAuth": False,
    }


def test_parse_proxy_line_various_formats() -> None:
    from ultima_scraper_backend.api.routes.proxies import parse_proxy_line

    # Standard URL with credentials
    url, user, pwd, grp = parse_proxy_line("http://anon:anon@203.0.113.10:6754")
    assert url == "http://203.0.113.10:6754"
    assert user == "anon"
    assert pwd == "anon"
    assert grp is None

    # SOCKS5 URL with credentials and comment group
    url, user, pwd, grp = parse_proxy_line("socks5://usr:secret@10.0.0.1:1080 # Datacenter")
    assert url == "socks5://10.0.0.1:1080"
    assert user == "usr"
    assert pwd == "secret"
    assert grp == "Datacenter"

    # host:port:user:pass with default group
    url, user, pwd, grp = parse_proxy_line("203.0.113.20:6014:alice:bob", default_group="Residential")
    assert url == "http://203.0.113.20:6014"
    assert user == "alice"
    assert pwd == "bob"
    assert grp == "Residential"

    # host:port only
    url, user, pwd, grp = parse_proxy_line("203.0.113.30:6462")
    assert url == "http://203.0.113.30:6462"
    assert user is None
    assert pwd is None


@pytest.mark.asyncio
async def test_add_proxy_with_group_and_embedded_credentials(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    persist = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[])),
    )

    req = proxies_module.ProxyCreateRequest(
        url="http://anon:anon@203.0.113.10:6754",
        group="ProxyGroup1",
    )
    res = await proxies_module.add_proxy(req, config=config)

    assert res.url == "http://203.0.113.10:6754"
    assert res.username == "anon"
    assert res.group == "ProxyGroup1"
    assert len(config.settings.network.proxies) == 1
    stored = config.settings.network.proxies[0]
    assert stored.url == "http://203.0.113.10:6754"
    assert stored.username == "anon"
    assert stored.password == "anon"
    assert stored.group == "ProxyGroup1"
    persist.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_update_proxy_group(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    proxy = Proxy(url="http://203.0.113.10:6754", group="OldGroup")
    persist = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=Network(proxies=[proxy])),
    )

    req = proxies_module.ProxyUpdateRequest(group="NewGroup")
    res = await proxies_module.update_proxy(proxy.url, req, config=config)

    assert res.group == "NewGroup"
    assert proxy.group == "NewGroup"
    persist.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_bulk_add_proxies_with_raw_text(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    persist = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[])),
    )

    raw_input = (
        "http://anon:anon@203.0.113.10:6754\n"
        "http://anon:anon@203.0.113.20:6014\n"
        "http://anon:anon@203.0.113.30:6462\n"
    )
    req = proxies_module.ProxyBulkCreateRequest(
        raw_text=raw_input,
        default_group="BulkGroupA",
    )
    res = await proxies_module.bulk_add_proxies(req, config=config)

    assert len(res.added) == 3
    assert all(p.group == "BulkGroupA" for p in res.added)
    assert len(config.settings.network.proxies) == 3
    persist.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_bulk_assign_group(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    p1 = Proxy(url="http://203.0.113.10:6754", group="OldA")
    p2 = Proxy(url="http://203.0.113.20:6014", group="OldB")
    p3 = Proxy(url="http://203.0.113.30:6462")
    persist = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[p1, p2, p3])),
    )

    req = proxies_module.ProxyBulkGroupRequest(
        proxy_urls=[p1.url, p3.url],
        group="ConsolidatedGroup",
    )
    res = await proxies_module.bulk_assign_group(req, config=config)

    assert res.updated_count == 2
    assert p1.group == "ConsolidatedGroup"
    assert p2.group == "OldB"
    assert p3.group == "ConsolidatedGroup"
    persist.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_update_group_settings(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    p1 = Proxy(url="http://203.0.113.10:6754", max_connections=4, group="TargetGroup")
    p2 = Proxy(url="http://203.0.113.20:6014", max_connections=4, group="TargetGroup")
    p3 = Proxy(url="http://203.0.113.30:6462", max_connections=4, group="OtherGroup")
    persist = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist)
    network = Network(proxies=[p1, p2, p3])
    network.downloads.per_domain_concurrency = 16
    config = SimpleNamespace(settings=SimpleNamespace(network=network))

    req = proxies_module.GroupSettingsUpdateRequest(
        max_connections=16,
        max_concurrency=8,
    )
    res = await proxies_module.update_group_settings("TargetGroup", req, config=config)

    assert res.updated_count == 2
    assert p1.max_connections == 16
    assert p1.downloads.max_concurrency == 8
    assert p2.max_connections == 16
    assert p2.downloads.max_concurrency == 8
    assert p3.max_connections == 4
    # Their own settings start from the network's, not the built-in defaults.
    assert p1.downloads.per_domain_concurrency == 16
    assert p3.downloads is None
    persist.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_bulk_test_proxies(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    async def fake_check_proxy_tcp(url: str, timeout_seconds: float = 5.0):
        if "203.0.113.10" in url:
            return True, "TCP connection succeeded", 45
        return False, "Connection refused", None

    monkeypatch.setattr(proxies_module, "_check_proxy_tcp", fake_check_proxy_tcp)

    req = proxies_module.ProxyBulkTestRequest(
        proxies=[
            proxies_module.ProxyBulkTestItem(url="http://203.0.113.10:6754"),
            proxies_module.ProxyBulkTestItem(url="http://203.0.113.20:6014"),
        ]
    )
    res = await proxies_module.bulk_test_proxies(req)

    assert len(res.results) == 2
    assert res.results[0].success is True
    assert res.results[0].latency_ms == 45
    assert res.results[1].success is False


@pytest.mark.asyncio
async def test_bulk_update_proxy_state(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    p1 = Proxy(url="http://203.0.113.10:6754", enabled=True)
    p2 = Proxy(url="http://203.0.113.20:6014", enabled=True)
    p3 = Proxy(url="http://203.0.113.30:6462", enabled=True)
    persist = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[p1, p2, p3])),
    )

    req = proxies_module.BulkProxyStateRequest(
        proxy_urls=["http://203.0.113.10:6754", "http://203.0.113.20:6014"],
        enabled=False,
    )
    res = await proxies_module.bulk_update_proxy_state(req, config=config)

    assert res.updated_count == 2
    assert res.enabled is False
    assert p1.enabled is False
    assert p2.enabled is False
    assert p3.enabled is True
    persist.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_bulk_delete_proxies(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    p1 = Proxy(url="http://203.0.113.10:6754")
    p2 = Proxy(url="http://203.0.113.20:6014")
    p3 = Proxy(url="http://203.0.113.30:6462")
    persist = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[p1, p2, p3])),
    )

    req = proxies_module.BulkProxyDeleteRequest(
        proxy_urls=["http://203.0.113.10:6754", "http://203.0.113.30:6462"],
    )
    res = await proxies_module.bulk_delete_proxies(req, config=config)

    assert res.deleted_count == 2
    assert len(config.settings.network.proxies) == 1
    assert config.settings.network.proxies[0].url == "http://203.0.113.20:6014"
    persist.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_bulk_sync_proxies(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    p1 = Proxy(
        url="http://203.0.113.10:6754",
        username="user1",
        password="secretpassword",
        enabled=False,
        max_connections=12,
        group="OldGroup",
    )
    p2 = Proxy(url="http://203.0.113.20:6014", username="user2")
    p3 = Proxy(url="http://203.0.113.30:6462")
    persist = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[p1, p2, p3])),
    )

    # New list: p1 (kept with original fields preserved, no replacement), and p4 (newly added).
    # p2 and p3 are omitted, so they should be deleted.
    req = proxies_module.ProxyBulkSyncRequest(
        raw_text="http://203.0.113.10:6754\nhttp://anon:anon@10.0.0.1:8080 # NewGroup",
    )
    res = await proxies_module.bulk_sync_proxies(req, config=config)

    assert res.status == "success"
    assert len(res.kept) == 1
    assert res.kept[0].url == "http://203.0.113.10:6754"
    assert len(res.added) == 1
    assert res.added[0].url == "http://10.0.0.1:8080"
    assert set(res.deleted) == {"http://203.0.113.20:6014", "http://203.0.113.30:6462"}

    # In config, p1 must be preserved intact without replacement:
    assert len(config.settings.network.proxies) == 2
    kept_in_config = config.settings.network.proxies[0]
    assert kept_in_config.url == "http://203.0.113.10:6754"
    assert kept_in_config.username == "user1"
    assert kept_in_config.password == "secretpassword"
    assert kept_in_config.enabled is False
    assert kept_in_config.max_connections == 12
    assert kept_in_config.group == "OldGroup"

    added_in_config = config.settings.network.proxies[1]
    assert added_in_config.url == "http://10.0.0.1:8080"
    assert added_in_config.username == "anon"
    assert added_in_config.password == "anon"
    assert added_in_config.group == "NewGroup"
    persist.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_bulk_sync_proxies_target_group_preserves_other_groups(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    # Setup proxies in different groups
    ga_1 = Proxy(url="http://1.1.1.1:8080", group="GroupA", max_connections=5)
    ga_2 = Proxy(url="http://1.1.1.2:8080", group="GroupA", max_connections=5)  # To be omitted & deleted
    gb_1 = Proxy(url="http://2.2.2.1:8080", group="GroupB", max_connections=10) # Out of scope
    gb_2 = Proxy(url="http://2.2.2.2:8080", group="GroupB", max_connections=10) # Out of scope
    ungrouped = Proxy(url="http://3.3.3.1:8080", group=None)                     # Out of scope

    persist = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[ga_1, ga_2, gb_1, gb_2, ungrouped])),
    )

    # Sync GroupA: keep ga_1, omit ga_2, add ga_3
    req = proxies_module.ProxyBulkSyncRequest(
        target_group="GroupA",
        raw_text="http://1.1.1.1:8080\nhttp://1.1.1.3:8080",
    )
    res = await proxies_module.bulk_sync_proxies(req, config=config)

    assert res.status == "success"
    assert res.target_group == "GroupA"
    assert len(res.kept) == 1
    assert res.kept[0].url == "http://1.1.1.1:8080"
    assert len(res.added) == 1
    assert res.added[0].url == "http://1.1.1.3:8080"
    assert res.added[0].group == "GroupA"
    # Only ga_2 should be deleted, NOT gb_1, gb_2, or ungrouped!
    assert res.deleted == ["http://1.1.1.2:8080"]

    # Verify final proxies in config
    config_urls = [p.url for p in config.settings.network.proxies]
    assert "http://1.1.1.1:8080" in config_urls  # ga_1 kept
    assert "http://1.1.1.3:8080" in config_urls  # ga_3 added
    assert "http://2.2.2.1:8080" in config_urls  # gb_1 preserved!
    assert "http://2.2.2.2:8080" in config_urls  # gb_2 preserved!
    assert "http://3.3.3.1:8080" in config_urls  # ungrouped preserved!
    assert "http://1.1.1.2:8080" not in config_urls  # ga_2 deleted
    assert len(config.settings.network.proxies) == 5
    persist.assert_called_once_with(config)


@pytest.mark.asyncio
async def test_bulk_sync_proxies_default_group_inferred_scope(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    # When user specifies default_group="Residential" without explicit target_group,
    # it must scope deletion to "Residential" and preserve "Datacenter"
    res_1 = Proxy(url="http://res.1:8080", group="Residential")
    res_2 = Proxy(url="http://res.2:8080", group="Residential")  # omitted
    dc_1 = Proxy(url="http://dc.1:8080", group="Datacenter")

    persist = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[res_1, res_2, dc_1])),
    )

    req = proxies_module.ProxyBulkSyncRequest(
        default_group="Residential",
        raw_text="http://res.1:8080\nhttp://res.3:8080",
    )
    res = await proxies_module.bulk_sync_proxies(req, config=config)

    assert res.deleted == ["http://res.2:8080"]
    config_urls = [p.url for p in config.settings.network.proxies]
    assert "http://dc.1:8080" in config_urls  # Datacenter completely untouched!
    assert "http://res.1:8080" in config_urls
    assert "http://res.3:8080" in config_urls
    assert "http://res.2:8080" not in config_urls


@pytest.mark.asyncio
async def test_bulk_sync_proxies_ungrouped_scope(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import proxies as proxies_module

    u1 = Proxy(url="http://u.1:8080", group=None)
    u2 = Proxy(url="http://u.2:8080", group=None)  # omitted
    g1 = Proxy(url="http://g.1:8080", group="NamedGroup")

    persist = Mock()
    monkeypatch.setattr(proxies_module, "_persist_proxy_config", persist)
    config = SimpleNamespace(
        settings=SimpleNamespace(network=SimpleNamespace(proxies=[u1, u2, g1])),
    )

    req = proxies_module.ProxyBulkSyncRequest(
        target_group="__ungrouped__",
        raw_text="http://u.1:8080",
    )
    res = await proxies_module.bulk_sync_proxies(req, config=config)

    assert res.deleted == ["http://u.2:8080"]
    config_urls = [p.url for p in config.settings.network.proxies]
    assert "http://g.1:8080" in config_urls  # NamedGroup preserved!
    assert "http://u.1:8080" in config_urls
    assert "http://u.2:8080" not in config_urls




