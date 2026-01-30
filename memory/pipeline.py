"""
Location: /mnt/f/Code/discordbot/memory/pipeline.py
Summary: Main orchestrator for the conversational memory pipeline. Coordinates
         message tracking, topic detection, summarization, packaging, and upload.
         Runs a background task that periodically checks for topic shifts.

Used by: main.py (initialized and hooked into on_message)
Uses: buffer.py, detector.py, summarizer.py, packager.py, uploader.py, models.py
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Set, Callable, Awaitable

import discord

from memory.models import ConversationMessage
from memory.buffer import ConversationBuffer
from memory.detector import TopicDetector
from memory.summarizer import ConversationSummarizer
from memory.packager import ChunkPackager
from memory.uploader import MemoryUploader

logger = logging.getLogger(__name__)


class ConversationMemoryPipeline:
    """Orchestrates the full conversational memory pipeline.

    Coordinates:
    1. Message tracking (buffer)
    2. Topic shift detection (detector)
    3. Summary generation (summarizer)
    4. Chunk packaging (packager)
    5. RAG upload (uploader)

    Runs a background task that periodically checks for topic shifts
    and processes conversation chunks.

    Attributes:
        buffer: Per-channel message buffer.
        detector: Topic shift detector.
        summarizer: Reflection generator.
        packager: JSONL/Markdown packager.
        uploader: GPT Trainer upload manager.
        enabled_channels: Set of channel IDs to track.
        check_interval: Seconds between background checks.
    """

    def __init__(
        self,
        api_key: str,
        api_client,
        enabled_channels: Set[str],
        data_dir: str = "data/conversations",
        db_path: str = "data/memory_uploads.db",
        check_interval: int = 45,
        max_buffer_size: int = 100,
        time_gap_threshold: int = 1800
    ):
        """Initialize the pipeline.

        Args:
            api_key: Google API key for Gemini.
            api_client: GPTTrainerAPI instance.
            enabled_channels: Set of channel IDs to track.
            data_dir: Directory for JSONL storage.
            db_path: Path to upload queue database.
            check_interval: Seconds between detection checks.
            max_buffer_size: Max messages per channel buffer.
            time_gap_threshold: Seconds of inactivity for auto-shift.
        """
        self.buffer = ConversationBuffer(max_size=max_buffer_size)
        self.detector = TopicDetector(
            api_key=api_key,
            time_gap_threshold=time_gap_threshold
        )
        self.summarizer = ConversationSummarizer(api_key=api_key)
        self.packager = ChunkPackager(data_dir=data_dir)
        self.uploader = MemoryUploader(
            api_client=api_client,
            packager=self.packager,
            db_path=db_path
        )

        self.enabled_channels = enabled_channels
        self.check_interval = check_interval
        self._background_task: Optional[asyncio.Task] = None
        self._running = False
        self._channel_name_resolver: Optional[Callable[[str], Awaitable[str]]] = None

    async def initialize(self) -> None:
        """Initialize pipeline components."""
        await self.uploader.initialize()
        logger.info(
            f"Memory pipeline initialized for {len(self.enabled_channels)} channel(s)"
        )

    def set_channel_name_resolver(
        self,
        resolver: Callable[[str], Awaitable[str]]
    ) -> None:
        """Set a function to resolve channel IDs to names.

        Args:
            resolver: Async function that takes channel_id and returns name.
        """
        self._channel_name_resolver = resolver

    async def start(self) -> None:
        """Start the background processing task."""
        if self._running:
            logger.warning("Pipeline already running")
            return

        self._running = True
        self._background_task = asyncio.create_task(self._background_loop())
        await self.uploader.start_upload_task()
        logger.info("Memory pipeline background tasks started")

    async def stop(self) -> None:
        """Stop background tasks gracefully."""
        self._running = False

        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass

        await self.uploader.stop()
        logger.info("Memory pipeline stopped")

    def track_message(self, message: discord.Message) -> None:
        """Track a Discord message if it's in an enabled channel.

        Called from the bot's on_message handler. Converts the
        Discord message to our internal format and adds to buffer.

        Args:
            message: Discord message object.
        """
        channel_id = str(message.channel.id)

        # Only track enabled channels
        if channel_id not in self.enabled_channels:
            return

        # Skip empty messages
        if not message.content.strip():
            return

        # Convert to internal format
        conv_message = ConversationMessage(
            message_id=str(message.id),
            channel_id=channel_id,
            user_id=str(message.author.id),
            username=message.author.display_name,
            content=message.content,
            timestamp=message.created_at.replace(tzinfo=timezone.utc),
            is_bot_response=message.author.bot
        )

        self.buffer.add_message(conv_message)
        logger.debug(
            f"Tracked message in channel {channel_id} from {conv_message.username}"
        )

    async def _background_loop(self) -> None:
        """Background loop that checks for topic shifts."""
        while self._running:
            try:
                await self._process_all_channels()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background loop: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval * 2)

    async def _process_all_channels(self) -> None:
        """Check all active channels for topic shifts."""
        channel_ids = self.buffer.get_all_channel_ids()

        for channel_id in channel_ids:
            if not self._running:
                break

            try:
                await self._process_channel(channel_id)
            except Exception as e:
                logger.error(
                    f"Error processing channel {channel_id}: {e}",
                    exc_info=True
                )

    async def _process_channel(self, channel_id: str) -> None:
        """Process a single channel for topic shifts.

        Args:
            channel_id: The channel to process.
        """
        messages = self.buffer.get_messages(channel_id)

        if len(messages) < 4:
            # Not enough messages for meaningful detection
            return

        # Check for forced chunking (time/size limits)
        should_force = self.detector.should_force_chunk(messages)

        if should_force:
            logger.info(f"Force chunking channel {channel_id}")
            await self._create_chunk(channel_id, "Forced chunk due to time/size limits")
            return

        # Check for topic shift
        shift_result = await self.detector.detect_shift(messages)

        if shift_result.is_shift:
            logger.info(
                f"Topic shift detected in channel {channel_id}: "
                f"{shift_result.topic_summary} (confidence: {shift_result.confidence})"
            )
            await self._create_chunk(channel_id, shift_result.topic_summary)

    async def _create_chunk(
        self,
        channel_id: str,
        topic_hint: Optional[str] = None
    ) -> None:
        """Create a conversation chunk from the buffer.

        Args:
            channel_id: Channel to chunk.
            topic_hint: Optional topic summary from detection.
        """
        # Extract messages from buffer
        messages = self.buffer.extract_and_clear(channel_id)

        if not messages:
            return

        # Resolve channel name
        channel_name = await self._get_channel_name(channel_id)

        # Generate reflection
        try:
            reflection = await self.summarizer.generate_reflection(
                messages, channel_name
            )
        except Exception as e:
            logger.error(f"Failed to generate reflection: {e}")
            reflection = None

        # Package the chunk
        chunk = self.packager.package_chunk(
            messages=messages,
            channel_id=channel_id,
            channel_name=channel_name,
            reflection=reflection
        )

        # Save to JSONL
        try:
            jsonl_path = self.packager.save_jsonl(chunk)
            logger.info(f"Saved chunk to {jsonl_path}")
        except Exception as e:
            logger.error(f"Failed to save JSONL: {e}")

        # Queue for upload
        try:
            await self.uploader.queue_chunk(chunk)
        except Exception as e:
            logger.error(f"Failed to queue chunk for upload: {e}")

    async def _get_channel_name(self, channel_id: str) -> str:
        """Resolve channel ID to name.

        Args:
            channel_id: Discord channel ID.

        Returns:
            Channel name or ID if resolution fails.
        """
        if self._channel_name_resolver:
            try:
                return await self._channel_name_resolver(channel_id)
            except Exception as e:
                logger.debug(f"Failed to resolve channel name: {e}")

        return f"channel-{channel_id}"

    async def force_chunk_all(self) -> int:
        """Force chunk all active channels.

        Useful for shutdown or manual intervention.

        Returns:
            Number of chunks created.
        """
        chunks_created = 0
        channel_ids = self.buffer.get_all_channel_ids()

        for channel_id in channel_ids:
            messages = self.buffer.get_messages(channel_id)
            if messages:
                try:
                    await self._create_chunk(channel_id, "Manual/shutdown chunk")
                    chunks_created += 1
                except Exception as e:
                    logger.error(f"Failed to force chunk channel {channel_id}: {e}")

        return chunks_created

    def get_stats(self) -> dict:
        """Get pipeline statistics.

        Returns:
            Dict with buffer and processing stats.
        """
        return {
            'enabled_channels': len(self.enabled_channels),
            'active_channels': len(self.buffer.get_all_channel_ids()),
            'total_buffered_messages': self.buffer.total_messages(),
            'running': self._running
        }

    async def get_upload_stats(self) -> dict:
        """Get upload queue statistics.

        Returns:
            Dict with upload queue counts.
        """
        return await self.uploader.get_upload_stats()
