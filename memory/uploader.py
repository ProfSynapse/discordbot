"""
Location: /mnt/f/Code/discordbot/memory/uploader.py
Summary: Handles uploading conversation chunks to GPT Trainer for RAG retrieval.
         Manages an upload queue with SQLite persistence for reliability and
         implements retry logic with exponential backoff.

Used by: pipeline.py (queues chunks for upload after packaging)
Uses: models.py (ConversationChunk), api_client.py (GPTTrainerAPI)
"""

import asyncio
import aiosqlite
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from memory.models import ConversationChunk
from memory.packager import ChunkPackager

logger = logging.getLogger(__name__)


class MemoryUploader:
    """Manages conversation chunk uploads to GPT Trainer RAG.

    Features:
    - SQLite queue for persistence across restarts
    - Exponential backoff retry logic
    - Background upload task

    Attributes:
        api_client: GPTTrainerAPI instance for uploads.
        packager: ChunkPackager for markdown conversion.
        db_path: Path to SQLite database for upload queue.
    """

    def __init__(
        self,
        api_client,
        packager: ChunkPackager,
        db_path: str = "data/memory_uploads.db"
    ):
        """Initialize the uploader.

        Args:
            api_client: GPTTrainerAPI instance.
            packager: ChunkPackager for format conversion.
            db_path: Path to SQLite database.
        """
        self.api_client = api_client
        self.packager = packager
        self.db_path = db_path
        self._upload_task: Optional[asyncio.Task] = None
        self._running = False

        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Initialize the SQLite database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS conversation_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_hash TEXT UNIQUE NOT NULL,
                    channel_id TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    message_count INTEGER NOT NULL,
                    topic_summary TEXT,
                    markdown_content TEXT NOT NULL,
                    upload_status TEXT DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    uploaded_at TEXT,
                    error_message TEXT
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_upload_status
                ON conversation_chunks(upload_status)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_channel_time
                ON conversation_chunks(channel_id, end_time)
            """)

            await db.commit()
            logger.info("Memory uploader database initialized")

    async def queue_chunk(self, chunk: ConversationChunk) -> bool:
        """Add a chunk to the upload queue.

        The chunk is converted to markdown and stored in SQLite.
        The background task will pick it up for upload.

        Args:
            chunk: Conversation chunk to upload.

        Returns:
            True if queued successfully, False if duplicate.
        """
        markdown_content = self.packager.to_markdown(chunk)

        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT OR IGNORE INTO conversation_chunks
                    (chunk_hash, channel_id, start_time, end_time, message_count,
                     topic_summary, markdown_content, upload_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """, (
                    chunk.metadata.chunk_id,
                    chunk.metadata.channel_id,
                    chunk.metadata.timestamp_start.isoformat(),
                    chunk.metadata.timestamp_end.isoformat(),
                    chunk.metadata.message_count,
                    chunk.reflection.topic if chunk.reflection else None,
                    markdown_content,
                    datetime.now(timezone.utc).isoformat()
                ))

                if db.total_changes > 0:
                    await db.commit()
                    logger.info(f"Queued chunk {chunk.metadata.chunk_id} for upload")
                    return True
                else:
                    logger.debug(f"Chunk {chunk.metadata.chunk_id} already in queue")
                    return False

        except Exception as e:
            logger.error(f"Failed to queue chunk: {e}")
            return False

    async def start_upload_task(self) -> None:
        """Start the background upload task."""
        if self._upload_task is not None and not self._upload_task.done():
            logger.warning("Upload task already running")
            return

        self._running = True
        self._upload_task = asyncio.create_task(self._upload_loop())
        logger.info("Started memory upload background task")

    async def stop(self) -> None:
        """Stop the background upload task."""
        self._running = False
        if self._upload_task:
            self._upload_task.cancel()
            try:
                await self._upload_task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped memory upload background task")

    async def _upload_loop(self) -> None:
        """Background loop that processes the upload queue."""
        while self._running:
            try:
                # Get pending chunks
                pending = await self._get_pending_chunks()

                if pending:
                    for chunk_data in pending:
                        if not self._running:
                            break
                        await self._process_upload(chunk_data)

                # Wait before next check
                await asyncio.sleep(30)  # Check every 30 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in upload loop: {e}")
                await asyncio.sleep(60)  # Wait longer on error

    async def _get_pending_chunks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get chunks pending upload from the database.

        Args:
            limit: Maximum chunks to retrieve.

        Returns:
            List of chunk data dictionaries.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT id, chunk_hash, markdown_content, retry_count
                FROM conversation_chunks
                WHERE upload_status = 'pending' AND retry_count < 5
                ORDER BY created_at ASC
                LIMIT ?
            """, (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def _process_upload(self, chunk_data: Dict[str, Any]) -> None:
        """Process a single chunk upload.

        Args:
            chunk_data: Dictionary with chunk details from database.
        """
        chunk_id = chunk_data['id']
        chunk_hash = chunk_data['chunk_hash']
        markdown = chunk_data['markdown_content']
        retry_count = chunk_data['retry_count']

        # Calculate backoff delay
        if retry_count > 0:
            delay = min(60 * (2 ** retry_count), 3600)  # Max 1 hour
            logger.info(f"Retry {retry_count} for chunk {chunk_hash}, waiting {delay}s")
            await asyncio.sleep(delay)

        try:
            # Upload to GPT Trainer
            success = await self._upload_to_gpt_trainer(markdown, chunk_hash)

            if success:
                await self._mark_uploaded(chunk_id)
                logger.info(f"Successfully uploaded chunk {chunk_hash}")
            else:
                await self._mark_retry(chunk_id, "Upload returned failure")

        except Exception as e:
            logger.error(f"Upload failed for chunk {chunk_hash}: {e}")
            await self._mark_retry(chunk_id, str(e))

    async def _upload_to_gpt_trainer(
        self,
        markdown_content: str,
        chunk_id: str
    ) -> bool:
        """Upload markdown content to GPT Trainer RAG.

        Uses the api_client to upload text content. If a direct text
        upload method doesn't exist, falls back to creating a data source.

        Args:
            markdown_content: The markdown text to upload.
            chunk_id: Unique identifier for logging.

        Returns:
            True if upload succeeded.
        """
        try:
            # Check if api_client has upload_text method
            if hasattr(self.api_client, 'upload_text'):
                result = await self.api_client.upload_text(
                    content=markdown_content,
                    filename=f"conversation_{chunk_id}.md"
                )
                return result.get('success', False)

            # Fallback: Return False so retry logic can handle it.
            # The chunk is saved locally in JSONL format but upload failed.
            logger.warning(
                f"No upload_text method available, chunk {chunk_id} saved locally only. "
                "Upload marked as failed to enable retry when method becomes available."
            )
            return False  # Upload did not succeed - allow retry logic to handle

        except Exception as e:
            logger.error(f"GPT Trainer upload failed: {e}")
            raise

    async def _mark_uploaded(self, chunk_id: int) -> None:
        """Mark a chunk as successfully uploaded.

        Args:
            chunk_id: Database ID of the chunk.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE conversation_chunks
                SET upload_status = 'uploaded',
                    uploaded_at = ?
                WHERE id = ?
            """, (datetime.now(timezone.utc).isoformat(), chunk_id))
            await db.commit()

    async def _mark_retry(self, chunk_id: int, error_message: str) -> None:
        """Mark a chunk for retry after failure.

        Args:
            chunk_id: Database ID of the chunk.
            error_message: Error message to record.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE conversation_chunks
                SET retry_count = retry_count + 1,
                    error_message = ?
                WHERE id = ?
            """, (error_message, chunk_id))

            # Check if max retries exceeded
            async with db.execute(
                "SELECT retry_count FROM conversation_chunks WHERE id = ?",
                (chunk_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row and row[0] >= 5:
                    await db.execute("""
                        UPDATE conversation_chunks
                        SET upload_status = 'failed'
                        WHERE id = ?
                    """, (chunk_id,))

            await db.commit()

    async def get_upload_stats(self) -> Dict[str, int]:
        """Get statistics about the upload queue.

        Returns:
            Dict with counts for pending, uploaded, and failed chunks.
        """
        async with aiosqlite.connect(self.db_path) as db:
            stats = {}
            for status in ['pending', 'uploaded', 'failed']:
                async with db.execute(
                    "SELECT COUNT(*) FROM conversation_chunks WHERE upload_status = ?",
                    (status,)
                ) as cursor:
                    row = await cursor.fetchone()
                    stats[status] = row[0] if row else 0
            return stats

    async def is_chunk_processed(self, chunk_hash: str) -> bool:
        """Check if a chunk has already been processed.

        Args:
            chunk_hash: The unique hash of the chunk.

        Returns:
            True if chunk exists in database (any status).
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM conversation_chunks WHERE chunk_hash = ?",
                (chunk_hash,)
            ) as cursor:
                return await cursor.fetchone() is not None
