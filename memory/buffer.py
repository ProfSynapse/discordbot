"""
Location: /mnt/f/Code/discordbot/memory/buffer.py
Summary: Per-channel conversation buffer using bounded deques. Maintains a sliding
         window of recent messages for each channel, providing the raw material
         for topic detection and chunk creation.

Used by: pipeline.py (adds messages, retrieves for detection/chunking)
Uses: models.py (ConversationMessage)
"""

from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional
import logging

from memory.models import ConversationMessage

logger = logging.getLogger(__name__)


class ConversationBuffer:
    """Per-channel ring buffer for storing recent conversation messages.

    Maintains a bounded deque for each channel to limit memory usage.
    Messages are automatically evicted when the buffer reaches capacity.

    Attributes:
        max_size: Maximum messages per channel buffer.
        _buffers: Dict mapping channel_id to deque of messages.
        _last_activity: Dict mapping channel_id to last message timestamp.
    """

    def __init__(self, max_size: int = 100):
        """Initialize the conversation buffer.

        Args:
            max_size: Maximum number of messages to retain per channel.
        """
        self.max_size = max_size
        self._buffers: Dict[str, deque[ConversationMessage]] = {}
        self._last_activity: Dict[str, datetime] = {}

    def add_message(self, message: ConversationMessage) -> None:
        """Add a message to the appropriate channel buffer.

        Creates a new buffer for the channel if one doesn't exist.
        Old messages are automatically evicted when the buffer is full.

        Args:
            message: The message to add.
        """
        channel_id = message.channel_id

        if channel_id not in self._buffers:
            self._buffers[channel_id] = deque(maxlen=self.max_size)
            logger.debug(f"Created new buffer for channel {channel_id}")

        self._buffers[channel_id].append(message)
        self._last_activity[channel_id] = message.timestamp

        logger.debug(
            f"Added message to channel {channel_id}, "
            f"buffer size: {len(self._buffers[channel_id])}"
        )

    def get_messages(
        self,
        channel_id: str,
        count: Optional[int] = None
    ) -> List[ConversationMessage]:
        """Get messages from a channel buffer.

        Args:
            channel_id: The channel to retrieve messages from.
            count: Maximum number of messages to return (None = all).

        Returns:
            List of messages in chronological order (oldest first).
        """
        if channel_id not in self._buffers:
            return []

        messages = list(self._buffers[channel_id])

        if count is not None:
            messages = messages[-count:]

        return messages

    def get_messages_since(
        self,
        channel_id: str,
        since: datetime
    ) -> List[ConversationMessage]:
        """Get messages from a channel after a specific timestamp.

        Args:
            channel_id: The channel to retrieve messages from.
            since: Only return messages after this timestamp.

        Returns:
            List of messages in chronological order (oldest first).
        """
        if channel_id not in self._buffers:
            return []

        return [
            msg for msg in self._buffers[channel_id]
            if msg.timestamp > since
        ]

    def get_last_activity(self, channel_id: str) -> Optional[datetime]:
        """Get the timestamp of the last message in a channel.

        Args:
            channel_id: The channel to check.

        Returns:
            Timestamp of last message, or None if no messages.
        """
        return self._last_activity.get(channel_id)

    def get_all_channel_ids(self) -> List[str]:
        """Get all channel IDs with active buffers.

        Returns:
            List of channel IDs.
        """
        return list(self._buffers.keys())

    def clear_channel(self, channel_id: str) -> None:
        """Clear all messages from a channel buffer.

        Args:
            channel_id: The channel to clear.
        """
        if channel_id in self._buffers:
            self._buffers[channel_id].clear()
            logger.debug(f"Cleared buffer for channel {channel_id}")

    def extract_and_clear(
        self,
        channel_id: str,
        count: Optional[int] = None
    ) -> List[ConversationMessage]:
        """Extract messages from buffer and clear them.

        Used when chunking a conversation -- extracts the messages that
        will be included in the chunk, leaving the buffer empty or with
        remaining messages.

        Args:
            channel_id: The channel to extract from.
            count: Number of messages to extract (None = all).

        Returns:
            List of extracted messages in chronological order.
        """
        if channel_id not in self._buffers:
            return []

        buffer = self._buffers[channel_id]

        if count is None or count >= len(buffer):
            # Extract all
            messages = list(buffer)
            buffer.clear()
        else:
            # Extract oldest N messages
            messages = []
            for _ in range(count):
                if buffer:
                    messages.append(buffer.popleft())

        logger.debug(
            f"Extracted {len(messages)} messages from channel {channel_id}, "
            f"remaining: {len(buffer)}"
        )

        return messages

    def size(self, channel_id: str) -> int:
        """Get the number of messages in a channel buffer.

        Args:
            channel_id: The channel to check.

        Returns:
            Number of messages in the buffer.
        """
        if channel_id not in self._buffers:
            return 0
        return len(self._buffers[channel_id])

    def total_messages(self) -> int:
        """Get total messages across all channel buffers.

        Returns:
            Total message count.
        """
        return sum(len(buf) for buf in self._buffers.values())

    def get_time_since_last_activity(
        self,
        channel_id: str
    ) -> Optional[float]:
        """Get seconds since last activity in a channel.

        Args:
            channel_id: The channel to check.

        Returns:
            Seconds since last message, or None if no messages.
        """
        last_activity = self._last_activity.get(channel_id)
        if last_activity is None:
            return None

        now = datetime.now(timezone.utc)

        # Handle timezone-naive datetimes (assume UTC)
        if last_activity.tzinfo is None:
            last_activity = last_activity.replace(tzinfo=timezone.utc)

        return (now - last_activity).total_seconds()
