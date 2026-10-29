"""Test that BackendManager uses USAPI initializer for login."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from ultima_scraper_backend.manager import BackendManager
from ultima_scraper_db_archive import SubscriptionModel, UserAuthModel, UserModel


@pytest.fixture
def test_db_path(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_backend.db"
    return db_path


@pytest.fixture
def backend_with_data(test_db_path, requires_configured_postgres):
    """Create a backend manager with test data."""
    # Create backend
    backend = BackendManager(db_path=test_db_path, )

    # Add test data
    try:
        with Session(backend.engine) as session:
            # Create users
            user1 = UserModel(id=100, username="performer1", active=True)
            subscriber = UserModel(id=1, username="subscriber", active=True)
            session.add_all([user1, subscriber])

            # Create auth
            auth = UserAuthModel(
                id=1,
                site="onlyfans",
                username="subscriber",
                user_id=1,
                cookie="test_cookie",
                x_bc="test_bc",
                user_agent="test_agent",
            )
            session.add(auth)

            # Create subscription
            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            sub = SubscriptionModel(
                id=1,
                user_id=100,
                subscriber_id=1,
                active=True,
                expires_at=expires_at,
            )
            session.add(sub)
            session.commit()
    except SQLAlchemyError as exc:
        pytest.skip(f"Postgres unavailable for backend USAPI integration test: {exc}")

    return backend


def test_db_subscription_stub_hydrates_persisted_post_count():
    """DB-backed subscription users retain the pagination count needed by get_posts."""
    from ultima_scraper_backend.usapi_initializer import USAPIInitializer

    engine = MagicMock()
    subscription = SimpleNamespace(
        id=1,
        user_id=100,
        subscriber_id=1,
        active=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_user = SimpleNamespace(id=100, username="performer1")
    db_user_info = SimpleNamespace(post_count=554)
    authed = MagicMock()
    authed.find_user.return_value = None
    authed.get_api.return_value = authed.api

    with patch("ultima_scraper_backend.usapi_initializer.Session") as session_type:
        session = session_type.return_value.__enter__.return_value
        session.get.return_value = db_user
        session.exec.return_value.first.return_value = db_user_info
        converted = USAPIInitializer(engine=engine)._convert_db_to_api_subscription(
            subscription,
            authed,
            authed,
        )

    assert converted is not None
    assert converted.user.posts_count == 554


@pytest.mark.asyncio
async def test_backend_uses_usapi_initializer(backend_with_data):
    """Test that BackendManager._login_with_account uses USAPI initializer."""

    # Mock the initialize_usapi_with_db function at the right location
    with patch(
        "ultima_scraper_backend.usapi_initializer.initialize_usapi_with_db"
    ) as mock_init:
        # Setup mock return value
        mock_authed = MagicMock()
        mock_authed.username = "subscriber"
        mock_authed.id = 1
        mock_authed.subscriptions = []
        mock_init.return_value = mock_authed

        # Mock the API instance
        mock_api = MagicMock()

        with patch(
            "ultima_scraper_backend.manager.ultima_scraper_api.select_api"
        ) as mock_select:
            mock_select.return_value = mock_api

            # Call _login_with_account
            result = await backend_with_data._login_with_account(
                "onlyfans", account_id=1
            )

            # Verify initialize_usapi_with_db was called
            assert mock_init.called
            call_kwargs = mock_init.call_args[1] if mock_init.call_args else {}
            assert call_kwargs.get("site") == "onlyfans"
            assert call_kwargs.get("account_id") == 1
            assert call_kwargs.get("api_instance") == mock_api

            # Verify result is correct
            assert isinstance(result, tuple) and len(result) == 2
            api, authed = result
            assert authed == mock_authed


@pytest.mark.asyncio
async def test_backend_falls_back_for_non_onlyfans(backend_with_data):
    """Test that BackendManager falls back to standard login for non-OnlyFans sites."""

    # Add a fansly account
    with Session(backend_with_data.engine) as session:
        user2 = UserModel(id=2, username="fansly_user", active=True)
        auth2 = UserAuthModel(
            id=2,
            site="fansly",
            username="fansly_user",
            user_id=2,
            cookie="fansly_cookie",
            x_bc="",
            authorization="fansly_auth",
            user_agent="test_agent",
        )
        session.add_all([user2, auth2])
        session.commit()

    # Account was added directly to DB; list_accounts will pick it up

    # Mock the API
    with patch(
        "ultima_scraper_backend.manager.ultima_scraper_api.select_api"
    ) as mock_select:
        mock_api = MagicMock()
        mock_authed = MagicMock()
        mock_authed.username = "fansly_user"
        mock_api.login = AsyncMock(return_value=mock_authed)
        mock_select.return_value = mock_api

        # Call _login_with_account for fansly
        result = await backend_with_data._login_with_account("fansly", account_id=2)

        # Verify standard login was used (not initializer)
        assert mock_api.login.called

        # Verify result
        if isinstance(result, tuple):
            api, authed = result
            assert authed == mock_authed


@pytest.mark.asyncio
async def test_backend_can_disable_db_init(backend_with_data):
    """Test that BackendManager can disable DB initialization."""

    # Mock the API
    with patch(
        "ultima_scraper_backend.manager.ultima_scraper_api.select_api"
    ) as mock_select:
        mock_api = MagicMock()
        mock_authed = MagicMock()
        mock_authed.username = "subscriber"
        mock_api.login = AsyncMock(return_value=mock_authed)
        mock_select.return_value = mock_api

        # Call with use_db_init=False
        result = await backend_with_data._login_with_account(
            "onlyfans", account_id=1, use_db_init=False
        )

        # Verify standard login was used
        assert mock_api.login.called

        # Verify result
        if isinstance(result, tuple):
            api, authed = result
            assert authed == mock_authed


def test_backend_manager_logging_on_init(backend_with_data, caplog):
    """Test that backend logs when using USAPI initializer."""
    import logging

    caplog.set_level(logging.INFO)

    # This test just verifies the backend was created successfully
    # Actual logging happens during _login_with_account
    assert backend_with_data is not None
    assert len(backend_with_data.list_accounts()) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
