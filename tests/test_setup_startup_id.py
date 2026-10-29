from __future__ import annotations

import pytest

from ultima_scraper_backend.api.routes import setup as setup_route


def test_startup_id_uses_shared_control_runtime_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USR_BACKEND_STARTUP_ID", "shared-control-runtime")

    assert setup_route.get_backend_startup_id() == "shared-control-runtime"
    assert (
        setup_route.SetupStatusResponse().startup_id
        == "shared-control-runtime"
    )
