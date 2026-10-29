from __future__ import annotations

import importlib


def test_canonical_backend_manager_import_surface() -> None:
    module = importlib.import_module("ultima_scraper_backend.manager")
    assert hasattr(module, "BackendManager")
    assert hasattr(module, "AccountRecord")
    assert hasattr(module, "BackendResult")


def test_canonical_websocket_action_import_surface() -> None:
    module = importlib.import_module("ultima_scraper_backend.websocket_actions")
    assert hasattr(module, "WebSocketActionHandler")
    assert hasattr(module, "create_websocket_action_handler")
