"""In-memory stand-in for canonical favourites in fake-session route tests.

Routes always read ``management.favourites``; these tests use fake sessions
without that table, so the model's ``favorite`` attribute plays the store.
"""

from __future__ import annotations

import pytest
from ultima_scraper_backend.services import favourites_service


def install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(favourites_service, "ensure_active", lambda session, site=None: None)
    monkeypatch.setattr(
        favourites_service,
        "user_states",
        lambda session, site, users: {user.id for user in users if getattr(user, "favorite", False)},
    )

    def set_user_state(session, site, user, desired):
        user.favorite = desired

    monkeypatch.setattr(favourites_service, "set_user_state", set_user_state)
