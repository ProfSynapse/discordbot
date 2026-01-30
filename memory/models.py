"""
Location: /mnt/f/Code/discordbot/memory/models.py
Summary: Dataclasses for the conversational memory pipeline. Defines the core data
         structures used throughout the memory system: ConversationMessage for
         individual Discord messages, ChunkMetadata for conversation chunk context,
         TopicShiftResult for topic detection outcomes, and Reflection for
         AI-generated conversation analysis.

Used by: buffer.py, detector.py, packager.py, summarizer.py, pipeline.py
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any


@dataclass
class ConversationMessage:
    """Represents a single message in a Discord conversation.

    Captures the essential metadata needed to track conversation flow and
    generate meaningful summaries.

    Attributes:
        message_id: Discord message ID (unique identifier).
        channel_id: Discord channel ID where the message was sent.
        user_id: Discord user ID of the message author.
        username: Display name of the message author.
        content: Raw message content text.
        timestamp: When the message was sent (UTC).
        is_bot_response: True if this message was sent by the bot.
    """
    message_id: str
    channel_id: str
    user_id: str
    username: str
    content: str
    timestamp: datetime
    is_bot_response: bool = False


@dataclass
class ChunkMetadata:
    """Metadata for a conversation chunk (group of related messages).

    Stored alongside the conversation messages to provide context for
    retrieval and fine-tuning.

    Attributes:
        chunk_id: Unique identifier for this chunk (typically a hash).
        channel_id: Discord channel ID.
        channel_name: Human-readable channel name.
        timestamp_start: When the first message in the chunk was sent.
        timestamp_end: When the last message in the chunk was sent.
        participants: List of usernames who participated in this chunk.
        message_count: Number of messages in the chunk.
        topic: Topic summary (set after summarization).
    """
    chunk_id: str
    channel_id: str
    channel_name: str
    timestamp_start: datetime
    timestamp_end: datetime
    participants: List[str]
    message_count: int
    topic: Optional[str] = None


@dataclass
class TopicShiftResult:
    """Result from the topic detector indicating whether a topic shift occurred.

    Used by the pipeline to decide when to chunk conversations.

    Attributes:
        is_shift: True if a topic shift was detected.
        confidence: Confidence score (0.0 to 1.0) in the detection.
        topic_summary: Brief description of the new topic (if shift detected).
        reason: Explanation of why a shift was or wasn't detected.
        api_error: True if detection failed due to API error (vs genuine "no shift").
    """
    is_shift: bool
    confidence: float
    topic_summary: Optional[str] = None
    reason: Optional[str] = None
    api_error: bool = False


@dataclass
class Reflection:
    """AI-generated reflective analysis of a conversation chunk.

    Provides structured insights about what happened in the conversation,
    key learnings, and connections to other topics.

    Attributes:
        topic: Main topic of the conversation.
        what_happened: Narrative description of the conversation.
        key_insights: List of key takeaways from the conversation.
        about_the_user: What was learned about the user(s).
        decisions_made: Decisions or recommendations made in the conversation.
        what_went_well: Positive aspects of the conversation.
        what_could_improve: Areas where the conversation could have been better.
        connections: Dict with 'related_topics' and 'likely_next_questions'.
        tags: Extracted tags for categorization.
    """
    topic: str
    what_happened: str
    key_insights: List[str] = field(default_factory=list)
    about_the_user: List[str] = field(default_factory=list)
    decisions_made: List[str] = field(default_factory=list)
    what_went_well: List[str] = field(default_factory=list)
    what_could_improve: List[str] = field(default_factory=list)
    connections: Dict[str, List[str]] = field(default_factory=lambda: {
        'related_topics': [],
        'likely_next_questions': []
    })
    tags: List[str] = field(default_factory=list)


@dataclass
class ConversationChunk:
    """A complete conversation chunk ready for storage and upload.

    Combines messages, metadata, and reflection into a single unit.

    Attributes:
        messages: List of conversation messages in this chunk.
        metadata: Chunk metadata.
        reflection: AI-generated reflection on the conversation.
    """
    messages: List[ConversationMessage]
    metadata: ChunkMetadata
    reflection: Optional[Reflection] = None

    def to_chatml_messages(self) -> List[Dict[str, str]]:
        """Convert messages to ChatML format for JSONL output.

        Returns:
            List of dicts with 'role' and 'content' keys.
        """
        chatml = []
        for msg in self.messages:
            role = "assistant" if msg.is_bot_response else "user"
            chatml.append({
                "role": role,
                "content": msg.content
            })
        return chatml

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for JSONL serialization.

        Returns:
            Dict with 'messages', 'metadata', and 'reflection' keys.
        """
        result = {
            "messages": self.to_chatml_messages(),
            "metadata": {
                "chunk_id": self.metadata.chunk_id,
                "channel_id": self.metadata.channel_id,
                "channel_name": self.metadata.channel_name,
                "timestamp_start": self.metadata.timestamp_start.isoformat(),
                "timestamp_end": self.metadata.timestamp_end.isoformat(),
                "participants": self.metadata.participants,
                "message_count": self.metadata.message_count
            }
        }

        if self.reflection:
            result["reflection"] = {
                "topic": self.reflection.topic,
                "what_happened": self.reflection.what_happened,
                "key_insights": self.reflection.key_insights,
                "about_the_user": self.reflection.about_the_user,
                "decisions_made": self.reflection.decisions_made,
                "what_went_well": self.reflection.what_went_well,
                "what_could_improve": self.reflection.what_could_improve,
                "connections": self.reflection.connections
            }

        return result
