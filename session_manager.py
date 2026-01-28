"""
Session manager using SQLite for persistent storage.
Handles Discord user → GPT-Trainer session UUID mappings with Railway Volume persistence.
"""

import aiosqlite
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from pathlib import Path
from config import config
from api_client import api_client

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages user sessions with SQLite persistence on Railway Volume."""

    def __init__(self, db_path: str, api_client):
        """
        Initialize session manager.

        Args:
            db_path: Path to SQLite database file (e.g., /data/sessions.db)
            api_client: GPTTrainerAPI instance for creating sessions
        """
        self.db_path = db_path
        self.api_client = api_client

        # Ensure directory exists
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Session manager initialized with database: {db_path}")

    async def initialize(self):
        """Create database and tables if they don't exist."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Enable WAL mode for better concurrent access
                await db.execute("PRAGMA journal_mode=WAL")

                # Create sessions table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        user_id TEXT PRIMARY KEY,
                        session_uuid TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        last_used TEXT NOT NULL,
                        message_count INTEGER DEFAULT 0
                    )
                """)

                # Create index on last_used for cleanup queries
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_last_used
                    ON sessions(last_used)
                """)

                await db.commit()
                logger.info("Database initialized successfully")

                # Log session count
                count = await self.get_session_count()
                logger.info(f"Loaded {count} existing session(s)")

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise

    async def get_or_create_session(self, user_id: str) -> str:
        """
        Get existing session UUID or create a new one for the user.

        Args:
            user_id: Discord user ID

        Returns:
            GPT-Trainer session UUID
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Try to fetch existing session
                async with db.execute(
                    "SELECT session_uuid, message_count FROM sessions WHERE user_id = ?",
                    (user_id,)
                ) as cursor:
                    row = await cursor.fetchone()

                    if row:
                        session_uuid, msg_count = row

                        # Update last_used and increment message count
                        await db.execute("""
                            UPDATE sessions
                            SET last_used = ?, message_count = message_count + 1
                            WHERE user_id = ?
                        """, (datetime.utcnow().isoformat(), user_id))
                        await db.commit()

                        logger.debug(f"Reusing session for user {user_id}: {session_uuid[:8]}... (msg #{msg_count + 1})")
                        return session_uuid

                # No existing session - create new one
                logger.info(f"Creating new session for user {user_id}")
                session_uuid = await self.api_client.create_chat_session()

                now = datetime.utcnow().isoformat()
                await db.execute("""
                    INSERT INTO sessions (user_id, session_uuid, created_at, last_used, message_count)
                    VALUES (?, ?, ?, ?, ?)
                """, (user_id, session_uuid, now, now, 1))
                await db.commit()

                logger.info(f"Created new session for user {user_id}: {session_uuid[:8]}...")
                return session_uuid

        except Exception as e:
            logger.error(f"Error in get_or_create_session for user {user_id}: {e}", exc_info=True)
            raise

    async def reset_session(self, user_id: str) -> str:
        """
        Reset user's session (delete old, create new).

        Args:
            user_id: Discord user ID

        Returns:
            New GPT-Trainer session UUID
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Delete existing session
                await db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

                # Create new session
                session_uuid = await self.api_client.create_chat_session()

                now = datetime.utcnow().isoformat()
                await db.execute("""
                    INSERT INTO sessions (user_id, session_uuid, created_at, last_used, message_count)
                    VALUES (?, ?, ?, ?, ?)
                """, (user_id, session_uuid, now, now, 0))

                await db.commit()

                logger.info(f"Reset session for user {user_id}: {session_uuid[:8]}...")
                return session_uuid

        except Exception as e:
            logger.error(f"Error resetting session for user {user_id}: {e}", exc_info=True)
            raise

    async def get_session_info(self, user_id: str) -> Optional[Dict]:
        """
        Get session information for a user.

        Args:
            user_id: Discord user ID

        Returns:
            Dict with session info or None if no session exists
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    """SELECT session_uuid, created_at, last_used, message_count
                       FROM sessions WHERE user_id = ?""",
                    (user_id,)
                ) as cursor:
                    row = await cursor.fetchone()

                    if row:
                        return {
                            'session_uuid': row[0],
                            'created_at': row[1],
                            'last_used': row[2],
                            'message_count': row[3]
                        }
                    return None

        except Exception as e:
            logger.error(f"Error getting session info for user {user_id}: {e}")
            return None

    async def cleanup_old_sessions(self, max_age_days: int) -> int:
        """
        Remove sessions that haven't been used in X days.

        Args:
            max_age_days: Maximum age in days

        Returns:
            Number of sessions deleted
        """
        try:
            cutoff_date = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()

            async with aiosqlite.connect(self.db_path) as db:
                # Count sessions to be deleted
                async with db.execute(
                    "SELECT COUNT(*) FROM sessions WHERE last_used < ?",
                    (cutoff_date,)
                ) as cursor:
                    count = (await cursor.fetchone())[0]

                if count > 0:
                    # Delete old sessions
                    await db.execute(
                        "DELETE FROM sessions WHERE last_used < ?",
                        (cutoff_date,)
                    )
                    await db.commit()
                    logger.info(f"Cleaned up {count} old session(s)")

                return count

        except Exception as e:
            logger.error(f"Error cleaning up old sessions: {e}")
            return 0

    async def get_session_count(self) -> int:
        """
        Get total number of active sessions.

        Returns:
            Total session count
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("SELECT COUNT(*) FROM sessions") as cursor:
                    count = (await cursor.fetchone())[0]
                    return count
        except Exception as e:
            logger.error(f"Error getting session count: {e}")
            return 0

    async def get_all_sessions(self) -> List[Dict]:
        """
        Get all sessions (for admin/debugging).

        Returns:
            List of session dictionaries
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT user_id, session_uuid, created_at, last_used, message_count FROM sessions"
                ) as cursor:
                    rows = await cursor.fetchall()

                    return [
                        {
                            'user_id': row[0],
                            'session_uuid': row[1],
                            'created_at': row[2],
                            'last_used': row[3],
                            'message_count': row[4]
                        }
                        for row in rows
                    ]
        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")
            return []


# Singleton instance (initialized in main.py)
session_manager: Optional[SessionManager] = None
