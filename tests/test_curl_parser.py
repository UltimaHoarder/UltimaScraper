from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ultima_scraper_backend.api.routes import curl_parser as curl_parser_module
from ultima_scraper_backend.api.routes.curl_parser import (
    CURL_INPUT_ERROR,
    RAW_AUTH_INPUT_ERROR,
    AuthJsonParseRequest,
    CurlParseRequest,
    parse_auth_json,
    parse_curl,
    parse_onlyfans_auth_payload,
)


class _FakeExecResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def first(self) -> object | None:
        return self._value


class _FakeImportSession:
    def __init__(self, first_results: list[object | None]) -> None:
        self._first_results = list(first_results)
        self.added: list[object] = []

    def exec(self, _query: object) -> _FakeExecResult:
        value = self._first_results.pop(0) if self._first_results else None
        return _FakeExecResult(value)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def refresh(self, obj: object) -> None:
        if getattr(obj, "id", None) is None:
            setattr(obj, "id", getattr(obj, "user_id", None))

    def close(self) -> None:
        return None


class _FakeSiteDB:
    def __init__(self, session: _FakeImportSession) -> None:
        self._session = session

    def get_session(self) -> _FakeImportSession:
        return self._session


ONLYFANS_AUTH_PAYLOAD = """
{
  "sess": "fakesessiontwo000000000000",
  "auth_id": "222222222",
  "auth_uid_": "222222222",
  "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
  "x_bc": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "app-token": "33d57ade8c02dbc5a333db99ff9ae26a"
}
""".strip()


def test_parse_onlyfans_auth_payload_builds_cookie_and_user_id() -> None:
    parsed = parse_onlyfans_auth_payload(ONLYFANS_AUTH_PAYLOAD)

    assert parsed.success is True
    assert parsed.site == "onlyfans"
    assert (
        parsed.cookie
        == "sess=fakesessiontwo000000000000; auth_id=222222222; auth_uid_=222222222"
    )
    assert parsed.auth_id == "222222222"
    assert parsed.user_id == 222222222
    assert parsed.sess == "fakesessiontwo000000000000"
    assert parsed.x_bc == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert parsed.app_token == "33d57ade8c02dbc5a333db99ff9ae26a"
    assert parsed.raw_headers["cookie"] == parsed.cookie
    assert parsed.raw_headers["app-token"] == parsed.app_token


@pytest.mark.asyncio
async def test_parse_curl_accepts_raw_onlyfans_auth_payload() -> None:
    parsed = await parse_auth_json(
        AuthJsonParseRequest(auth_json=ONLYFANS_AUTH_PAYLOAD, site="onlyfans")
    )

    assert parsed.success is True
    assert parsed.user_id == 222222222
    assert parsed.auth_id == "222222222"


@pytest.mark.asyncio
async def test_parse_curl_rejects_json_payload() -> None:
    parsed = await parse_curl(
        CurlParseRequest(curl_command=ONLYFANS_AUTH_PAYLOAD, site="onlyfans")
    )

    assert parsed.success is False
    assert parsed.error == CURL_INPUT_ERROR


def test_parse_onlyfans_auth_payload_rejects_invalid_json() -> None:
    parsed = parse_onlyfans_auth_payload("not valid import text")

    assert parsed.success is False
    assert parsed.error == RAW_AUTH_INPUT_ERROR


@pytest.mark.asyncio
async def test_add_auth_from_curl_syncs_imported_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ultima_scraper_backend.database.factory as db_factory

    parsed = curl_parser_module.ParsedCurlData(
        success=True,
        site="onlyfans",
        cookie="sess=abc; auth_id=123",
        x_bc="xbc",
        user_agent="ua",
        user_id=123,
    )
    session = _FakeImportSession([None, None])
    site_db = _FakeSiteDB(session)
    sync_mock = AsyncMock(return_value=True)
    publish_mock = AsyncMock(return_value=None)

    monkeypatch.setattr(
        curl_parser_module, "parse_curl", AsyncMock(return_value=parsed)
    )
    monkeypatch.setattr(
        curl_parser_module,
        "_test_parsed_auth",
        AsyncMock(return_value=(True, "Authentication is valid")),
    )
    monkeypatch.setattr(curl_parser_module, "_sync_imported_auth_user", sync_mock)
    monkeypatch.setattr(curl_parser_module, "publish_auth_added", publish_mock)
    monkeypatch.setattr(
        db_factory,
        "MultiSiteDatabaseManager",
        lambda: SimpleNamespace(get_or_create_manager=lambda _site: site_db),
    )

    request = curl_parser_module.AddAuthFromCurlRequest(
        curl_command="curl https://example.test",
        site="onlyfans",
    )

    backend_manager = SimpleNamespace(redis=None)
    response = await curl_parser_module.add_auth_from_curl(
        request,
        backend_manager=backend_manager,
    )

    assert response.success is True
    assert response.user_id == 123
    sync_mock.assert_awaited_once_with(
        site="onlyfans",
        parsed=parsed,
        site_db=site_db,
        backend_manager=backend_manager,
        account_id=123,
        proxy_url=None,
    )
    publish_mock.assert_awaited_once()
