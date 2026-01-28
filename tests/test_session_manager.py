"""
Tests for session_manager.py -- SessionManager class.

Uses an in-memory SQLite database (":memory:") and a mocked api_client
so no real network calls or file I/O occur.

Note: SessionManager imports `from config import config` and
`from api_client import api_client` at module level. The conftest.py
ensures the required env vars are set before these imports trigger.
We import SessionManager directly since conftest.py has set up the env.
"""

import pytest
import pytest_asyncio
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone


# We need to import SessionManager. The module imports config and api_client
# at module level, but conftest.py has set the env vars so config.from_env()
# will succeed. We just need to make sure the import path works.
from session_manager import SessionManager


@pytest.fixture
def mock_api_client():
    """Create a mock api_client with an async create_chat_session method."""
    client = AsyncMock()
    client.create_chat_session = AsyncMock(return_value="fake-session-uuid-1234")
    return client


@pytest_asyncio.fixture
async def session_mgr(mock_api_client, tmp_path):
    """Create and initialise a SessionManager with a temp-dir SQLite DB.

    We use tmp_path instead of ':memory:' because SessionManager creates
    the parent directory of db_path in __init__. Using a temp directory
    avoids side effects on the real filesystem.
    """
    db_path = str(tmp_path / "test_sessions.db")
    mgr = SessionManager(db_path, mock_api_client)
    await mgr.initialize()
    return mgr


class TestSessionManagerInitialize:
    """Tests for SessionManager.initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, mock_api_client, tmp_path):
        """initialize() should create the sessions table without error."""
        db_path = str(tmp_path / "init_test.db")
        mgr = SessionManager(db_path, mock_api_client)
        await mgr.initialize()

        # Verify by checking session count (should be 0 on fresh DB)
        count = await mgr.get_session_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, mock_api_client, tmp_path):
        """Calling initialize() twice should not raise or corrupt data."""
        db_path = str(tmp_path / "idempotent_test.db")
        mgr = SessionManager(db_path, mock_api_client)
        await mgr.initialize()
        await mgr.initialize()  # Second call should be safe

        count = await mgr.get_session_count()
        assert count == 0


class TestGetOrCreateSession:
    """Tests for SessionManager.get_or_create_session()."""

    @pytest.mark.asyncio
    async def test_creates_new_session_for_new_user(self, session_mgr, mock_api_client):
        """A new user should trigger create_chat_session and store the result."""
        session_uuid = await session_mgr.get_or_create_session("user-001")

        assert session_uuid == "fake-session-uuid-1234"
        mock_api_client.create_chat_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_existing_session_for_known_user(self, session_mgr, mock_api_client):
        """A returning user should get their existing session without creating a new one."""
        # First call creates
        uuid1 = await session_mgr.get_or_create_session("user-001")
        mock_api_client.create_chat_session.reset_mock()

        # Second call should reuse
        uuid2 = await session_mgr.get_or_create_session("user-001")

        assert uuid1 == uuid2
        mock_api_client.create_chat_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_different_users_get_different_sessions(self, session_mgr, mock_api_client):
        """Different user IDs should each get their own session."""
        mock_api_client.create_chat_session = AsyncMock(
            side_effect=["uuid-for-user-1", "uuid-for-user-2"]
        )

        uuid1 = await session_mgr.get_or_create_session("user-001")
        uuid2 = await session_mgr.get_or_create_session("user-002")

        assert uuid1 == "uuid-for-user-1"
        assert uuid2 == "uuid-for-user-2"
        assert mock_api_client.create_chat_session.call_count == 2

    @pytest.mark.asyncio
    async def test_message_count_increments(self, session_mgr):
        """Each call to get_or_create_session should increment message_count."""
        await session_mgr.get_or_create_session("user-001")
        await session_mgr.get_or_create_session("user-001")
        await session_mgr.get_or_create_session("user-001")

        info = await session_mgr.get_session_info("user-001")
        # First call sets message_count=1, second increments to 2, third to 3
        assert info["message_count"] == 3


class TestResetSession:
    """Tests for SessionManager.reset_session()."""

    @pytest.mark.asyncio
    async def test_reset_creates_new_session(self, session_mgr, mock_api_client):
        """reset_session should delete the old session and create a new one."""
        # Create initial session
        await session_mgr.get_or_create_session("user-001")
        mock_api_client.create_chat_session.reset_mock()

        # Now provide a different UUID for the new session
        mock_api_client.create_chat_session.return_value = "new-uuid-after-reset"
        new_uuid = await session_mgr.reset_session("user-001")

        assert new_uuid == "new-uuid-after-reset"
        mock_api_client.create_chat_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_clears_message_count(self, session_mgr, mock_api_client):
        """After reset, message_count should be 0."""
        await session_mgr.get_or_create_session("user-001")
        await session_mgr.get_or_create_session("user-001")
        await session_mgr.get_or_create_session("user-001")

        mock_api_client.create_chat_session.return_value = "reset-uuid"
        await session_mgr.reset_session("user-001")

        info = await session_mgr.get_session_info("user-001")
        assert info["message_count"] == 0

    @pytest.mark.asyncio
    async def test_reset_nonexistent_user_still_creates_session(self, session_mgr, mock_api_client):
        """Resetting a user with no existing session should still create one."""
        mock_api_client.create_chat_session.return_value = "brand-new-uuid"
        new_uuid = await session_mgr.reset_session("user-never-seen")

        assert new_uuid == "brand-new-uuid"


class TestGetSessionInfo:
    """Tests for SessionManager.get_session_info()."""

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_user(self, session_mgr):
        """get_session_info should return None for a user with no session."""
        info = await session_mgr.get_session_info("unknown-user")
        assert info is None

    @pytest.mark.asyncio
    async def test_returns_dict_with_expected_keys(self, session_mgr):
        """get_session_info should return a dict with the correct keys."""
        await session_mgr.get_or_create_session("user-001")
        info = await session_mgr.get_session_info("user-001")

        assert info is not None
        assert "session_uuid" in info
        assert "created_at" in info
        assert "last_used" in info
        assert "message_count" in info

    @pytest.mark.asyncio
    async def test_session_uuid_matches(self, session_mgr):
        """The returned session_uuid should match what was created."""
        await session_mgr.get_or_create_session("user-001")
        info = await session_mgr.get_session_info("user-001")

        assert info["session_uuid"] == "fake-session-uuid-1234"

    @pytest.mark.asyncio
    async def test_timestamps_are_iso_format(self, session_mgr):
        """created_at and last_used should be valid ISO format timestamps."""
        await session_mgr.get_or_create_session("user-001")
        info = await session_mgr.get_session_info("user-001")

        # These should parse without error
        created = datetime.fromisoformat(info["created_at"])
        last_used = datetime.fromisoformat(info["last_used"])

        assert isinstance(created, datetime)
        assert isinstance(last_used, datetime)


class TestCleanupOldSessions:
    """Tests for SessionManager.cleanup_old_sessions()."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_sessions(self, session_mgr, mock_api_client, tmp_path):
        """Sessions older than max_age_days should be removed."""
        import aiosqlite

        # Create a session, then manually backdate it
        await session_mgr.get_or_create_session("old-user")

        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        async with aiosqlite.connect(session_mgr.db_path) as db:
            await db.execute(
                "UPDATE sessions SET last_used = ? WHERE user_id = ?",
                (old_date, "old-user"),
            )
            await db.commit()

        # Cleanup sessions older than 30 days
        removed = await session_mgr.cleanup_old_sessions(max_age_days=30)
        assert removed == 1

        # Verify it was removed
        info = await session_mgr.get_session_info("old-user")
        assert info is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_recent_sessions(self, session_mgr):
        """Recent sessions should not be removed by cleanup."""
        await session_mgr.get_or_create_session("active-user")

        removed = await session_mgr.cleanup_old_sessions(max_age_days=30)
        assert removed == 0

        info = await session_mgr.get_session_info("active-user")
        assert info is not None

    @pytest.mark.asyncio
    async def test_cleanup_returns_zero_on_empty_db(self, session_mgr):
        """Cleanup on an empty database should return 0."""
        removed = await session_mgr.cleanup_old_sessions(max_age_days=30)
        assert removed == 0


class TestGetSessionCount:
    """Tests for SessionManager.get_session_count()."""

    @pytest.mark.asyncio
    async def test_count_starts_at_zero(self, session_mgr):
        """A fresh database should have 0 sessions."""
        count = await session_mgr.get_session_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_count_after_adding_sessions(self, session_mgr, mock_api_client):
        """Count should reflect the number of sessions added."""
        mock_api_client.create_chat_session = AsyncMock(
            side_effect=["uuid-1", "uuid-2", "uuid-3"]
        )

        await session_mgr.get_or_create_session("user-1")
        await session_mgr.get_or_create_session("user-2")
        await session_mgr.get_or_create_session("user-3")

        count = await session_mgr.get_session_count()
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_after_reset(self, session_mgr, mock_api_client):
        """Resetting a session should not change the total count (reset replaces, not removes)."""
        await session_mgr.get_or_create_session("user-1")
        assert await session_mgr.get_session_count() == 1

        mock_api_client.create_chat_session.return_value = "new-uuid"
        await session_mgr.reset_session("user-1")
        assert await session_mgr.get_session_count() == 1
