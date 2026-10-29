"""Shared TLS policy avoids blocking each time a rate-limit probe starts."""

import ssl
from types import SimpleNamespace
from unittest.mock import Mock

from ultima_scraper_api.managers import session_manager


def test_tls_context_is_verified_and_scoped_to_session_manager():
    first = session_manager.SessionManager(api=None)
    second = session_manager.SessionManager(api=None)
    context = first.get_ssl_context()
    assert first.get_ssl_context() is context
    assert second.get_ssl_context() is not context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.post_handshake_auth is True


async def test_sequential_rate_limit_probes_load_certificates_once(monkeypatch):
    contexts = []
    closed = []
    context = SimpleNamespace(post_handshake_auth=False)
    create_context = Mock(return_value=context)
    monkeypatch.setattr(session_manager.ssl, "create_default_context", create_context)

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Probe:
        def __init__(self, connector, timeout):
            self.connector = connector

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append(self.connector)

        def get(self, url, **kwargs):
            return Response()

    monkeypatch.setattr(session_manager, "ClientSession", Probe)
    monkeypatch.setattr(
        session_manager.aiohttp, "TCPConnector", lambda *, ssl: contexts.append(ssl) or object()
    )
    manager = session_manager.SessionManager(api=None)
    for _ in range(3):
        manager._route_rate_limited["__direct__"] = True
        await manager.check_route_rate_limit()
        assert manager.is_route_rate_limited("__direct__") is False
    create_context.assert_called_once_with()
    assert contexts == [context, context, context]
    assert context.post_handshake_auth is True
    assert len(closed) == 3
