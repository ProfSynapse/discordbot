"""
Location: /mnt/f/Code/discordbot/memory/packager.py
Summary: Generates dual output formats from conversation chunks: ChatML/JSONL for
         fine-tuning and Obsidian-style markdown with frontmatter for GPT Trainer RAG.
         Handles file persistence for JSONL and provides text for upload.

Used by: pipeline.py (packages chunks after summarization)
Uses: models.py (ConversationChunk, ChunkMetadata, Reflection)
"""

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from memory.models import ConversationChunk, ConversationMessage, ChunkMetadata, Reflection

logger = logging.getLogger(__name__)


class ChunkPackager:
    """Packages conversation chunks into JSONL and Markdown formats.

    Produces two outputs:
    1. ChatML/JSONL: Appended to daily files for fine-tuning
    2. Obsidian Markdown: Text with frontmatter for RAG upload

    Attributes:
        data_dir: Base directory for conversation data files.
    """

    def __init__(self, data_dir: str = "data/conversations"):
        """Initialize the packager.

        Args:
            data_dir: Base directory for storing JSONL files.
        """
        self.data_dir = Path(data_dir)
        self._ensure_data_dir()

    def _ensure_data_dir(self) -> None:
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def package_chunk(
        self,
        messages: List[ConversationMessage],
        channel_id: str,
        channel_name: str,
        reflection: Optional[Reflection] = None
    ) -> ConversationChunk:
        """Package messages into a ConversationChunk with metadata.

        Creates the chunk object with generated metadata including
        a unique hash-based ID.

        Args:
            messages: List of messages to package.
            channel_id: Discord channel ID.
            channel_name: Human-readable channel name.
            reflection: Optional AI-generated reflection.

        Returns:
            Complete ConversationChunk ready for storage/upload.
        """
        if not messages:
            raise ValueError("Cannot package empty message list")

        # Generate unique chunk ID based on content
        chunk_id = self._generate_chunk_id(messages)

        # Extract participants (non-bot users)
        participants = list(set(
            msg.username for msg in messages if not msg.is_bot_response
        ))

        metadata = ChunkMetadata(
            chunk_id=chunk_id,
            channel_id=channel_id,
            channel_name=channel_name,
            timestamp_start=messages[0].timestamp,
            timestamp_end=messages[-1].timestamp,
            participants=participants,
            message_count=len(messages),
            topic=reflection.topic if reflection else None
        )

        return ConversationChunk(
            messages=messages,
            metadata=metadata,
            reflection=reflection
        )

    def _generate_chunk_id(
        self,
        messages: List[ConversationMessage]
    ) -> str:
        """Generate a unique ID for the chunk based on content.

        Uses SHA256 hash of message IDs and timestamps to ensure
        uniqueness.

        Args:
            messages: Messages to hash.

        Returns:
            12-character hex string.
        """
        content = '|'.join(
            f"{msg.message_id}:{msg.timestamp.isoformat()}"
            for msg in messages
        )
        hash_digest = hashlib.sha256(content.encode()).hexdigest()
        return hash_digest[:12]

    def save_jsonl(self, chunk: ConversationChunk) -> str:
        """Save chunk to JSONL file (appends to daily file).

        Files are organized by channel and date:
        data/conversations/{channel_id}/{YYYY-MM-DD}.jsonl

        Args:
            chunk: The conversation chunk to save.

        Returns:
            Path to the JSONL file.
        """
        # Create channel directory
        channel_dir = self.data_dir / chunk.metadata.channel_id
        channel_dir.mkdir(parents=True, exist_ok=True)

        # Use end timestamp for file naming (when chunk was completed)
        date_str = chunk.metadata.timestamp_end.strftime("%Y-%m-%d")
        file_path = channel_dir / f"{date_str}.jsonl"

        # Convert chunk to JSON and append
        chunk_json = json.dumps(chunk.to_dict(), ensure_ascii=False)

        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(chunk_json + '\n')

        logger.info(f"Saved chunk {chunk.metadata.chunk_id} to {file_path}")
        return str(file_path)

    def to_markdown(self, chunk: ConversationChunk) -> str:
        """Convert chunk to Obsidian-style markdown with frontmatter.

        Produces text suitable for GPT Trainer RAG upload:
        - YAML frontmatter with metadata
        - Reflection sections
        - Transcript with timestamps

        Args:
            chunk: The conversation chunk to convert.

        Returns:
            Markdown string ready for upload.
        """
        lines = []

        # Build frontmatter
        lines.append("---")
        lines.append("type: conversation")
        if chunk.reflection:
            lines.append(f"topic: {chunk.reflection.topic}")
        lines.append(f"channel: {chunk.metadata.channel_name}")
        lines.append(f'channel_id: "{chunk.metadata.channel_id}"')
        lines.append(f"date: {chunk.metadata.timestamp_end.strftime('%Y-%m-%d')}")
        lines.append(f'time_start: "{chunk.metadata.timestamp_start.strftime("%H:%M:%S")}"')
        lines.append(f'time_end: "{chunk.metadata.timestamp_end.strftime("%H:%M:%S")}"')

        # Calculate duration
        duration = chunk.metadata.timestamp_end - chunk.metadata.timestamp_start
        duration_minutes = int(duration.total_seconds() / 60)
        lines.append(f"duration_minutes: {duration_minutes}")

        # Participants
        if chunk.metadata.participants:
            lines.append("participants:")
            for participant in chunk.metadata.participants:
                lines.append(f"  - {participant}")

        lines.append(f"message_count: {chunk.metadata.message_count}")

        # Tags from reflection
        if chunk.reflection and chunk.reflection.tags:
            lines.append("tags:")
            for tag in chunk.reflection.tags:
                lines.append(f"  - {tag}")

        # Related topics as wiki-links
        if chunk.reflection and chunk.reflection.connections.get('related_topics'):
            lines.append("related:")
            for topic in chunk.reflection.connections['related_topics']:
                # Convert to wiki-link format
                wiki_link = f"[[{topic.title()}]]"
                lines.append(f"  - {wiki_link}")

        lines.append("---")
        lines.append("")

        # Title
        topic = chunk.reflection.topic if chunk.reflection else "Conversation"
        lines.append(f"# {topic}")
        lines.append("")

        # Reflection section
        if chunk.reflection:
            lines.append("## Reflection")
            lines.append("")

            # What Happened
            if chunk.reflection.what_happened:
                lines.append("### What Happened")
                lines.append(chunk.reflection.what_happened)
                lines.append("")

            # Key Insights
            if chunk.reflection.key_insights:
                lines.append("### Key Insights")
                for insight in chunk.reflection.key_insights:
                    lines.append(f"- {insight}")
                lines.append("")

            # About the User
            if chunk.reflection.about_the_user:
                lines.append("### What I Learned About the User")
                for item in chunk.reflection.about_the_user:
                    lines.append(f"- {item}")
                lines.append("")

            # Decisions Made
            if chunk.reflection.decisions_made:
                lines.append("### Decisions Made")
                for decision in chunk.reflection.decisions_made:
                    lines.append(f"- {decision}")
                lines.append("")

            # What Went Well
            if chunk.reflection.what_went_well:
                lines.append("### What Went Well")
                for item in chunk.reflection.what_went_well:
                    lines.append(f"- {item}")
                lines.append("")

            # What Could Improve
            if chunk.reflection.what_could_improve:
                lines.append("### What Could Be Improved")
                for item in chunk.reflection.what_could_improve:
                    lines.append(f"- {item}")
                lines.append("")

            # Connections
            connections = chunk.reflection.connections
            if connections.get('related_topics') or connections.get('likely_next_questions'):
                lines.append("### Connections")
                if connections.get('related_topics'):
                    lines.append(f"- Related to: {', '.join(connections['related_topics'])}")
                if connections.get('likely_next_questions'):
                    lines.append(f"- User might next ask about: {', '.join(connections['likely_next_questions'])}")
                lines.append("")

        # Separator
        lines.append("---")
        lines.append("")

        # Transcript
        lines.append("## Transcript")
        for msg in chunk.messages:
            timestamp = msg.timestamp.strftime("%H:%M:%S")
            author = "Bot" if msg.is_bot_response else msg.username
            lines.append(f"[{timestamp}] {author}: {msg.content}")

        return '\n'.join(lines)

    def get_daily_chunks(
        self,
        channel_id: str,
        date: datetime
    ) -> List[dict]:
        """Load all chunks from a specific day's JSONL file.

        Args:
            channel_id: Discord channel ID.
            date: Date to load chunks from.

        Returns:
            List of chunk dictionaries.
        """
        date_str = date.strftime("%Y-%m-%d")
        file_path = self.data_dir / channel_id / f"{date_str}.jsonl"

        if not file_path.exists():
            return []

        chunks = []
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        chunks.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse chunk: {e}")

        return chunks
