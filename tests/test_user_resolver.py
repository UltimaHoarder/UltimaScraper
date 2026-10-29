"""Tests for username resolution utility."""

import asyncio

from unittest.mock import MagicMock

import pytest

from ultima_scraper_backend.helpers import resolve_user_identifier


class TestResolveUserIdentifier:
    """Test suite for resolve_user_identifier function."""

    @pytest.fixture(autouse=True)
    def inline_to_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _inline_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", _inline_to_thread)

    @pytest.mark.asyncio
    async def test_integer_passthrough(self):
        """Test that valid integer IDs are passed through unchanged."""
        backend = MagicMock()

        result = await resolve_user_identifier(12345, backend)

        assert result == 12345
        assert isinstance(result, int)

    @pytest.mark.asyncio
    async def test_zero_returns_none(self):
        """Test that user_id=0 returns None (invalid)."""
        backend = MagicMock()

        result = await resolve_user_identifier(0, backend)

        assert result is None

    @pytest.mark.asyncio
    async def test_negative_returns_none(self):
        """Test that negative user_id returns None (invalid)."""
        backend = MagicMock()

        result = await resolve_user_identifier(-1, backend)

        assert result is None

    @pytest.mark.asyncio
    async def test_valid_username_resolves_to_user_id(self):
        """Test that valid username is resolved to user_id via database."""
        # Mock backend with database manager
        backend = MagicMock()
        mock_db_manager = MagicMock()
        backend.db_managers = {"onlyfans": mock_db_manager}

        # Mock user object returned from database
        mock_user = MagicMock()
        mock_user.id = 67890
        mock_db_manager.get_user = MagicMock(return_value=mock_user)

        result = await resolve_user_identifier("phoenixrebirthed", backend)

        assert result == 67890
        mock_db_manager.get_user.assert_called_once_with("phoenixrebirthed")

    @pytest.mark.asyncio
    async def test_invalid_username_returns_none(self):
        """Test that non-existent username returns None."""
        # Mock backend with database manager
        backend = MagicMock()
        mock_db_manager = MagicMock()
        backend.db_managers = {"onlyfans": mock_db_manager}

        # Mock database returning None (user not found)
        mock_db_manager.get_user = MagicMock(return_value=None)

        result = await resolve_user_identifier("nonexistent_user", backend)

        assert result is None
        mock_db_manager.get_user.assert_called_once_with("nonexistent_user")

    @pytest.mark.asyncio
    async def test_empty_string_returns_none(self):
        """Test that empty string returns None."""
        backend = MagicMock()
        backend.db_managers = {"onlyfans": MagicMock()}

        result = await resolve_user_identifier("", backend)

        assert result is None

    @pytest.mark.asyncio
    async def test_whitespace_string_returns_none(self):
        """Test that whitespace-only string returns None."""
        backend = MagicMock()
        backend.db_managers = {"onlyfans": MagicMock()}

        result = await resolve_user_identifier("   ", backend)

        assert result is None

    @pytest.mark.asyncio
    async def test_none_identifier_returns_none(self):
        """Test that None identifier returns None."""
        backend = MagicMock()

        result = await resolve_user_identifier(None, backend)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_backend_with_username_returns_none(self):
        """Test that username without backend returns None."""
        result = await resolve_user_identifier("someuser", None)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_db_manager_returns_none(self):
        """Test that username with backend but no db_managers returns None."""
        backend = MagicMock()
        backend.db_managers = None

        result = await resolve_user_identifier("someuser", backend)

        assert result is None

    @pytest.mark.asyncio
    async def test_no_onlyfans_db_manager_returns_none(self):
        """Test that username with backend but no OnlyFans manager returns None."""
        backend = MagicMock()
        backend.db_managers = {}  # Empty dict, no OnlyFans manager

        result = await resolve_user_identifier("someuser", backend)

        assert result is None

    @pytest.mark.asyncio
    async def test_database_error_returns_none(self):
        """Test that database errors are handled gracefully."""
        backend = MagicMock()
        mock_db_manager = MagicMock()
        backend.db_managers = {"onlyfans": mock_db_manager}

        # Mock database raising an exception
        mock_db_manager.get_user = MagicMock(
            side_effect=Exception("Database connection error")
        )

        result = await resolve_user_identifier("someuser", backend)

        assert result is None

    @pytest.mark.asyncio
    async def test_numeric_string_converts_to_int(self):
        """Test that numeric string is converted to integer."""
        backend = MagicMock()

        result = await resolve_user_identifier("12345", backend)

        assert result == 12345
        assert isinstance(result, int)

    @pytest.mark.asyncio
    async def test_user_with_zero_id_returns_none(self):
        """Test that user with id=0 from database returns None."""
        backend = MagicMock()
        mock_db_manager = MagicMock()
        backend.db_managers = {"onlyfans": mock_db_manager}

        # Mock user with invalid id=0
        mock_user = MagicMock()
        mock_user.id = 0
        mock_db_manager.get_user = MagicMock(return_value=mock_user)

        result = await resolve_user_identifier("baduser", backend)

        assert result is None

    @pytest.mark.asyncio
    async def test_user_with_negative_id_returns_none(self):
        """Test that user with negative id from database returns None."""
        backend = MagicMock()
        mock_db_manager = MagicMock()
        backend.db_managers = {"onlyfans": mock_db_manager}

        # Mock user with invalid id=-1
        mock_user = MagicMock()
        mock_user.id = -1
        mock_db_manager.get_user = MagicMock(return_value=mock_user)

        result = await resolve_user_identifier("baduser", backend)

        assert result is None
